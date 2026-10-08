"""Load: build the DuckDB star schema from silver data and export the gold layer."""
from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd

from .config import PROJECT_ROOT, Config

log = logging.getLogger(__name__)

SQL_DIR = Path(__file__).parent / "sql"

# Tables exported for Power BI and the report. Large fact tables go to Parquet only.
GOLD_TABLES = {
    "dim_date": ("parquet", "csv"),
    "dim_property_type": ("parquet", "csv"),
    "dim_district": ("parquet", "csv"),
    "dim_outcode": ("parquet", "csv"),
    "dim_market_period": ("parquet", "csv"),
    "dim_market_event": ("parquet", "csv"),
    "fact_sales": ("parquet",),
    "fact_rates_monthly": ("parquet", "csv"),
    "mart_region_month": ("parquet", "csv"),
    "mart_district_month": ("parquet", "csv"),
    "mart_segment_change": ("parquet", "csv"),
    "dq_results": ("parquet", "csv"),
}


def connect(cfg: Config) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(cfg.paths.warehouse))


def _posix(p: Path) -> str:
    return p.resolve().as_posix()


def build_models(cfg: Config) -> None:
    params = {
        "silver": _posix(cfg.paths.silver),
        "bronze": _posix(cfg.paths.bronze),
        "config": _posix(PROJECT_ROOT / "config"),
        "ltv": cfg["mortgage_assumptions"]["loan_to_value"],
        "term_months": cfg["mortgage_assumptions"]["term_years"] * 12,
        "baseline_year": cfg["baseline_year"],
        "region": cfg["region_name"],
    }
    with connect(cfg) as con:
        for sql_file in sorted(SQL_DIR.glob("*.sql")):
            log.info("Running model %s", sql_file.name)
            con.execute(sql_file.read_text().format(**params))
        for (name,) in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_type = 'BASE TABLE' ORDER BY 1").fetchall():
            n = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
            log.info("  %-24s %10s rows", name, f"{n:,}")


def write_table(cfg: Config, name: str, df: pd.DataFrame) -> None:
    """Persist a pandas DataFrame (e.g. DQ results, model outputs) into the warehouse."""
    with connect(cfg) as con:
        con.register("_df", df)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _df")
        con.unregister("_df")


def read_table(cfg: Config, name: str) -> pd.DataFrame:
    with connect(cfg) as con:
        return con.execute(f"SELECT * FROM {name}").df()


def export_gold(cfg: Config, extra_tables: list[str] | None = None) -> list[Path]:
    out_dir = cfg.paths.gold
    written: list[Path] = []
    tables = dict(GOLD_TABLES)
    for t in extra_tables or []:
        tables.setdefault(t, ("parquet", "csv"))
    with connect(cfg) as con:
        existing = {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()}
        for name, formats in tables.items():
            if name not in existing:
                continue
            for fmt in formats:
                path = out_dir / f"{name}.{fmt}"
                opts = "(FORMAT parquet, COMPRESSION zstd)" if fmt == "parquet" else "(HEADER, DELIMITER ',')"
                con.execute(f"COPY {name} TO '{_posix(path)}' {opts}")
                written.append(path)
    log.info("Exported %s gold files to %s", len(written), out_dir)
    return written
