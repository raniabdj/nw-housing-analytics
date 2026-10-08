"""Extract: Bank of England Interactive Database (IADB).

Pulls Official Bank Rate (daily) and quoted mortgage rates (monthly) as CSV.
Series codes are configured in config/pipeline.yaml.
"""
from __future__ import annotations

import io
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import Config
from ..http import get_text, make_session

log = logging.getLogger(__name__)


def build_params(series_codes: list[str], start: date, end: date) -> dict:
    fmt = "%d/%b/%Y"                                  # the IADB expects e.g. 01/Jan/2018
    return {
        "csv.x": "yes",
        "Datefrom": start.strftime(fmt),
        "Dateto": end.strftime(fmt),
        "SeriesCodes": ",".join(series_codes),
        "CSVF": "TN",                                 # tabular, no titles
        "UsingCodes": "Y",
        "VPD": "Y",
        "VFD": "N",
    }


def parse_iadb_csv(text: str, series: dict[str, str]) -> pd.DataFrame:
    """Parse IADB CSV into long format: date, series_code, series_name, value."""
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip().upper() for c in df.columns]
    date_col = df.columns[0]
    df["date"] = pd.to_datetime(df[date_col].astype(str).str.strip(), format="mixed", dayfirst=True)
    value_cols = [c for c in df.columns if c in {k.upper() for k in series}]
    if not value_cols:
        raise ValueError(f"No requested series found in BoE response. Columns: {list(df.columns)}")
    long = df.melt(id_vars="date", value_vars=value_cols, var_name="series_code", value_name="value")
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long = long.dropna(subset=["value"])
    name_map = {k.upper(): v for k, v in series.items()}
    long["series_name"] = long["series_code"].map(name_map)
    return long[["date", "series_code", "series_name", "value"]].sort_values(["series_code", "date"])


def extract_rates(cfg: Config) -> Path:
    series: dict[str, str] = cfg["bank_of_england"]["series"]
    start = date(cfg["start_year"] - 1, 1, 1)         # one extra year so lagged models have history
    end = date.today()
    out_dir = cfg.paths.bronze / "boe"
    out_dir.mkdir(parents=True, exist_ok=True)

    override = cfg.extra.get("boe_file")              # file:// URL used for demo/offline runs
    if override:
        df = parse_iadb_csv(get_text(override), series)
    else:
        frames = []
        session = make_session()
        for code in series:                            # one request per series is more robust
            text = get_text(cfg["bank_of_england"]["url"],
                            params=build_params([code], start, end), session=session)
            if text.lstrip().startswith("<"):
                raise RuntimeError(f"BoE returned HTML instead of CSV for {code}; check the series code")
            frames.append(parse_iadb_csv(text, {code: series[code]}))
        df = pd.concat(frames, ignore_index=True)

    out = out_dir / "rates.parquet"
    df.to_parquet(out, index=False)
    (out_dir / "rates.manifest.json").write_text(json.dumps({
        "source": override or cfg["bank_of_england"]["url"],
        "series": series,
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": len(df),
    }, indent=2))
    log.info("Bank of England: %s observations across %s series", f"{len(df):,}", df["series_code"].nunique())
    return out
