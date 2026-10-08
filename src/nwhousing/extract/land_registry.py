"""Extract: HM Land Registry Price Paid Data.

The national files are large (~150 MB per year), so they are streamed to disk
and filtered to North West counties in chunks. Only the filtered rows are kept
in the bronze layer, still as raw strings, alongside a JSON manifest that
records where the data came from (lineage).

Source: https://www.gov.uk/government/statistical-data-sets/price-paid-data-downloads
Licence: Open Government Licence v3.0
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import Config
from ..http import download_file, make_session

log = logging.getLogger(__name__)

PPD_COLUMNS = [
    "transaction_id", "price", "date_of_transfer", "postcode", "property_type",
    "old_new", "duration", "paon", "saon", "street", "locality", "town_city",
    "district", "county", "ppd_category", "record_status",
]


def _base_url(cfg: Config) -> str:
    return cfg.extra.get("land_registry_base") or cfg["land_registry"]["base_url"]


def yearly_url(cfg: Config, year: int) -> str:
    return f"{_base_url(cfg)}/{cfg['land_registry']['yearly_file'].format(year=year)}"


def monthly_url(cfg: Config) -> str:
    return f"{_base_url(cfg)}/{cfg['land_registry']['monthly_file']}"


def filter_region(csv_path: Path, counties: list[str], chunk_rows: int) -> tuple[pd.DataFrame, int]:
    """Stream a headerless PPD CSV and keep rows whose County is in `counties`.

    Yearly and monthly files both carry 16 columns; older extracts have 15
    (no record status), so the column count is detected from the first row.
    """
    first = pd.read_csv(csv_path, header=None, nrows=1, dtype=str)
    names = PPD_COLUMNS[: first.shape[1]]
    wanted = set(counties)

    kept, rows_read = [], 0
    for chunk in pd.read_csv(csv_path, header=None, names=names, dtype=str,
                             chunksize=chunk_rows, keep_default_na=False):
        rows_read += len(chunk)
        kept.append(chunk[chunk["county"].str.upper().isin(wanted)])
    df = pd.concat(kept, ignore_index=True) if kept else pd.DataFrame(columns=names)
    if "record_status" not in df.columns:
        df["record_status"] = "A"
    return df, rows_read


def extract_price_paid(cfg: Config, url: str, label: str) -> Path:
    """Download one PPD file, filter to the region, write bronze parquet + manifest."""
    landing = cfg.paths.data_dir / "landing" / f"{label}.csv"
    out_dir = cfg.paths.bronze / "price_paid"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{label}.parquet"

    manifest = download_file(url, landing, session=make_session())
    df, rows_read = filter_region(landing, cfg.counties, cfg["land_registry"]["chunk_rows"])
    df.to_parquet(out, index=False)

    manifest.update({
        "label": label,
        "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows_read": rows_read,
        "rows_kept": len(df),
        "counties": cfg.counties,
    })
    (out_dir / f"{label}.manifest.json").write_text(json.dumps(manifest, indent=2))
    landing.unlink(missing_ok=True)          # raw national file is not needed once filtered
    log.info("%s: kept %s of %s rows for the region", label, f"{len(df):,}", f"{rows_read:,}")
    return out


def extract_years(cfg: Config, years: list[int]) -> list[Path]:
    return [extract_price_paid(cfg, yearly_url(cfg, y), f"pp-{y}") for y in years]


def extract_monthly_update(cfg: Config) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return extract_price_paid(cfg, monthly_url(cfg), f"pp-monthly-{stamp}")
