"""Transform: bronze Price Paid rows -> clean, typed silver table.

Also implements change-data-capture (CDC) for the monthly update file, which
flags each record as A (added), C (changed) or D (deleted).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import Config

log = logging.getLogger(__name__)

PROPERTY_TYPES = {"D": "Detached", "S": "Semi-detached", "T": "Terraced",
                  "F": "Flat/Maisonette", "O": "Other"}
TENURES = {"F": "Freehold", "L": "Leasehold"}

SILVER_COLUMNS = [
    "transaction_id", "price", "sale_date", "sale_month", "postcode", "outcode",
    "property_type_code", "property_type", "is_new_build", "tenure",
    "paon", "saon", "street", "locality", "town_city", "district", "county",
    "ppd_category", "is_standard", "is_price_outlier", "loaded_at",
]


def _title(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.strip().str.title()


def clean_price_paid(raw: pd.DataFrame, min_price: int = 10_000, max_price: int = 5_000_000) -> pd.DataFrame:
    """Type, standardise and flag raw PPD rows. Rows are never silently dropped
    here except those that cannot be parsed at all (no id, price or date)."""
    df = pd.DataFrame()
    df["transaction_id"] = raw["transaction_id"].astype(str).str.strip().str.strip("{}")
    df["price"] = pd.to_numeric(raw["price"], errors="coerce")
    df["sale_date"] = pd.to_datetime(raw["date_of_transfer"].astype(str).str.slice(0, 10),
                                     format="%Y-%m-%d", errors="coerce")
    df["sale_month"] = df["sale_date"].dt.to_period("M").dt.to_timestamp()

    pc = raw["postcode"].fillna("").astype(str).str.upper().str.strip()
    df["postcode"] = pc.where(pc != "", None)
    df["outcode"] = pc.str.split(" ").str[0].where(pc != "", None)

    df["property_type_code"] = raw["property_type"].astype(str).str.strip().str.upper()
    df["property_type"] = df["property_type_code"].map(PROPERTY_TYPES).fillna("Unknown")
    df["is_new_build"] = raw["old_new"].astype(str).str.strip().str.upper().eq("Y")
    df["tenure"] = raw["duration"].astype(str).str.strip().str.upper().map(TENURES).fillna("Other")

    for col in ("paon", "saon", "street", "locality", "town_city"):
        df[col] = _title(raw[col])
    df["district"] = raw["district"].fillna("").astype(str).str.strip().str.upper()
    df["county"] = raw["county"].fillna("").astype(str).str.strip().str.upper()

    df["ppd_category"] = raw["ppd_category"].astype(str).str.strip().str.upper()
    df["is_standard"] = df["ppd_category"].eq("A") & df["property_type_code"].ne("O")
    df["is_price_outlier"] = (df["price"] < min_price) | (df["price"] > max_price)
    df["loaded_at"] = datetime.now(timezone.utc).replace(tzinfo=None)

    unparseable = df["transaction_id"].eq("") | df["price"].isna() | df["sale_date"].isna()
    if unparseable.any():
        log.warning("Dropping %s unparseable rows", int(unparseable.sum()))
    df = df[~unparseable].copy()
    df["price"] = df["price"].astype("int64")
    return df[SILVER_COLUMNS]


def apply_changes(current: pd.DataFrame, changes_raw: pd.DataFrame, **clean_kwargs) -> pd.DataFrame:
    """Merge a monthly update file into the silver table.

    A = insert, C = replace the row with the same id, D = delete that id.
    Returns the new silver table.
    """
    status = changes_raw["record_status"].astype(str).str.strip().str.upper()
    ids = changes_raw["transaction_id"].astype(str).str.strip().str.strip("{}")

    deletes = set(ids[status.eq("D")])
    upserts = clean_price_paid(changes_raw[status.isin(["A", "C"])], **clean_kwargs)
    upserts = upserts.drop_duplicates("transaction_id", keep="last")

    keep = ~current["transaction_id"].isin(deletes | set(upserts["transaction_id"]))
    merged = pd.concat([current[keep], upserts], ignore_index=True)
    log.info("CDC merge: %s added/changed, %s deleted -> %s rows",
             f"{len(upserts):,}", f"{len(deletes):,}", f"{len(merged):,}")
    return merged.sort_values(["sale_date", "transaction_id"]).reset_index(drop=True)


def _bounds(cfg: Config) -> dict:
    q = cfg["quality"]
    return {"min_price": q["outlier_min_price"], "max_price": q["outlier_max_price"]}


def silver_path(cfg: Config) -> Path:
    return cfg.paths.silver / "sales.parquet"


def build_silver_from_yearly(cfg: Config, bronze_files: list[Path]) -> Path:
    raw = pd.concat([pd.read_parquet(p) for p in bronze_files], ignore_index=True)
    silver = clean_price_paid(raw, **_bounds(cfg))
    silver = (silver.sort_values("loaded_at")
                    .drop_duplicates("transaction_id", keep="last")
                    .sort_values(["sale_date", "transaction_id"])
                    .reset_index(drop=True))
    silver = silver[silver["sale_date"].dt.year >= cfg["start_year"]]
    silver.to_parquet(silver_path(cfg), index=False)
    log.info("Silver sales: %s rows (%s to %s)", f"{len(silver):,}",
             silver["sale_date"].min().date(), silver["sale_date"].max().date())
    return silver_path(cfg)


def build_silver_incremental(cfg: Config, monthly_bronze: Path) -> Path:
    current = pd.read_parquet(silver_path(cfg))
    changes = pd.read_parquet(monthly_bronze)
    merged = apply_changes(current, changes, **_bounds(cfg))
    merged = merged[merged["sale_date"].dt.year >= cfg["start_year"]]
    merged.to_parquet(silver_path(cfg), index=False)
    return silver_path(cfg)
