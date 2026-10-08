"""Transform: Bank of England observations -> one row per month."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..config import Config

log = logging.getLogger(__name__)


def to_monthly(long: pd.DataFrame) -> pd.DataFrame:
    """Daily/monthly observations (long format) -> wide monthly table.

    Each series becomes its monthly average; Bank Rate also gets the rate in
    force at month end. Gaps between observations are forward-filled, because
    a rate stays in force until it is changed; months after a series' latest
    publication are left empty rather than extrapolated.
    """
    df = long.copy()
    df["month"] = df["date"].dt.to_period("M").dt.to_timestamp()

    wide = df.pivot_table(index="month", columns="series_name", values="value", aggfunc="mean")
    wide.columns.name = None

    if "bank_rate" in df["series_name"].unique():
        end = (df[df["series_name"] == "bank_rate"].sort_values("date")
                 .groupby("month")["value"].last().rename("bank_rate_month_end"))
        wide = wide.join(end)

    full = pd.date_range(wide.index.min(), wide.index.max(), freq="MS")
    wide = wide.reindex(full).ffill(limit_area="inside")   # fill gaps, never invent future values
    wide.index.name = "month"
    return wide.round(4).reset_index()


def build_silver_rates(cfg: Config, bronze_file: Path) -> Path:
    monthly = to_monthly(pd.read_parquet(bronze_file))
    out = cfg.paths.silver / "rates_monthly.parquet"
    monthly.to_parquet(out, index=False)
    log.info("Silver rates: %s months, columns %s", len(monthly), list(monthly.columns[1:]))
    return out
