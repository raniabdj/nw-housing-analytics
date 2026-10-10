"""Orchestration: extract -> transform -> quality -> load -> analyse -> report.

Run modes
---------
backfill     download every yearly file from `start_year` and rebuild silver
incremental  apply the Land Registry monthly change file (A/C/D) to silver
refresh      re-download the two most recent yearly files and replace those years
auto         (default) backfill if there is no silver data yet; refresh if the
             last successful run was more than 40 days ago (a monthly update was
             probably missed); otherwise incremental
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import pandas as pd
import requests

from . import analysis, report, warehouse
from .config import Config
from .extract import boe, land_registry, postcodes
from .quality import enforce, run_checks
from .transform import rates as t_rates
from .transform import sales as t_sales

log = logging.getLogger(__name__)


def _state_path(cfg: Config):
    return cfg.paths.data_dir / "run_state.json"


def _load_state(cfg: Config) -> dict:
    p = _state_path(cfg)
    return json.loads(p.read_text()) if p.exists() else {"runs": []}


def _save_state(cfg: Config, state: dict) -> None:
    state["runs"] = state["runs"][-50:]
    _state_path(cfg).write_text(json.dumps(state, indent=2, default=str))


def _setup_demo(cfg: Config) -> None:
    from .demo import generate
    src = cfg.paths.data_dir / "demo_source"
    if not (src / "boe.csv").exists():
        log.info("Generating synthetic demo source files in %s", src)
        generate(src, start_year=cfg["start_year"])
    cfg.extra.update({
        "land_registry_base": src.resolve().as_uri(),
        "boe_file": (src / "boe.csv").resolve().as_uri(),
        "outcodes_file": str(src / "outcodes.json"),
    })


def resolve_mode(cfg: Config, mode: str, state: dict) -> str:
    if mode != "auto":
        return mode
    if not t_sales.silver_path(cfg).exists():
        return "backfill"
    ok = [r for r in state["runs"] if r.get("status") == "success"]
    if ok:
        last = datetime.fromisoformat(ok[-1]["finished_at"])
        if (datetime.now(timezone.utc) - last).days > 40:
            return "refresh"
    return "incremental"


def _extract_years(cfg: Config, years: list[int]):
    files = []
    this_year = datetime.now().year
    for y in years:
        try:
            files += land_registry.extract_years(cfg, [y])
        except requests.HTTPError as exc:
            # The new year's file only appears after its first monthly publication.
            if y == this_year and exc.response is not None and exc.response.status_code in (403, 404):
                log.warning("No file published yet for %s; skipping", y)
            else:
                raise
        except FileNotFoundError:
            if y == this_year:
                log.warning("No demo file for %s; skipping", y)
            else:
                raise
    return files


def extract_and_transform_sales(cfg: Config, mode: str) -> None:
    this_year = datetime.now().year
    if mode == "backfill":
        files = _extract_years(cfg, list(range(cfg["start_year"], this_year + 1)))
        t_sales.build_silver_from_yearly(cfg, files)
    elif mode == "refresh":
        years = [this_year - 1, this_year]
        fresh = _extract_years(cfg, years)
        current = pd.read_parquet(t_sales.silver_path(cfg))
        kept = current[~current["sale_date"].dt.year.isin(years)]
        new = t_sales.clean_price_paid(pd.concat([pd.read_parquet(p) for p in fresh]),
                                       min_price=cfg["quality"]["outlier_min_price"],
                                       max_price=cfg["quality"]["outlier_max_price"])
        merged = pd.concat([kept, new]).drop_duplicates("transaction_id", keep="last")
        merged.sort_values(["sale_date", "transaction_id"]).to_parquet(t_sales.silver_path(cfg), index=False)
        log.info("Refreshed %s; silver now %s rows", years, f"{len(merged):,}")
    elif mode == "incremental":
        try:
            monthly = land_registry.extract_monthly_update(cfg)
        except requests.RequestException as exc:
            # If the change file is unavailable (moved/renamed), fall back to re-pulling
            # the recent yearly files, which always contain the latest corrections.
            log.warning("Monthly change file unavailable (%s); falling back to refresh", exc)
            return extract_and_transform_sales(cfg, "refresh")
        t_sales.build_silver_incremental(cfg, monthly)
    else:
        raise ValueError(f"Unknown mode {mode!r}")


def run(cfg: Config, mode: str = "auto", with_report: bool = True) -> dict:
    t0 = time.time()
    state = _load_state(cfg)
    if cfg.demo:
        _setup_demo(cfg)
    mode = resolve_mode(cfg, mode, state)
    started = datetime.now(timezone.utc)
    log.info("=== Pipeline start (mode=%s, demo=%s) ===", mode, cfg.demo)
    record = {"started_at": started.isoformat(timespec="seconds"), "mode": mode, "demo": cfg.demo}

    try:
        # 1. Extract + transform
        extract_and_transform_sales(cfg, mode)
        rates_cache = cfg.paths.silver / "rates_monthly.parquet"
        try:
            t_rates.build_silver_rates(cfg, boe.extract_rates(cfg))
        except (boe.BoEUnavailable, requests.RequestException) as exc:
            # Rates change rarely; reusing last run's table beats failing the whole refresh.
            # The data quality check `rates_freshness` reports how stale they are.
            if not rates_cache.exists():
                raise
            log.warning("Bank of England unavailable (%s); reusing rates from the previous run", exc)
            record["rates_from_cache"] = True
        sales = pd.read_parquet(t_sales.silver_path(cfg))
        postcodes.extract_outcodes(cfg, sales["outcode"].dropna().unique().tolist())

        # 2. Data quality gate
        rates_m = pd.read_parquet(cfg.paths.silver / "rates_monthly.parquet")
        dq = run_checks(sales, rates_m, cfg)
        enforce(dq)

        # 3. Load star schema
        warehouse.build_models(cfg)
        warehouse.write_table(cfg, "dq_results", dq)

        # 4. Statistical analysis
        extra_tables = analysis.run(cfg)

        # 5. Export gold + report
        warehouse.export_gold(cfg, extra_tables)
        if with_report:
            report.build(cfg)

        record.update(status="success", rows=len(sales),
                      dq_warnings=int((~dq["passed"]).sum()))
    except Exception as exc:
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        record["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        record["seconds"] = round(time.time() - t0, 1)
        state["runs"].append(record)
        _save_state(cfg, state)
        log.info("=== Pipeline %s in %.1fs ===", record.get("status"), record["seconds"])
    return record
