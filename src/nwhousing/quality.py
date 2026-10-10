"""Data quality checks run between silver and gold.

Each check returns a row in a results table that is written to the warehouse,
shown in the report and available to Power BI. Any failed check with severity
"error" stops the pipeline before bad data reaches the gold layer.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import pandas as pd

from .config import Config

log = logging.getLogger(__name__)


@dataclass
class CheckResult:
    dataset: str
    check: str
    severity: str        # "error" stops the run, "warn" is reported only
    passed: bool
    observed: str
    expectation: str


class DataQualityError(RuntimeError):
    pass


def check_sales(df: pd.DataFrame, cfg: Config) -> list[CheckResult]:
    q = cfg["quality"]
    n = len(df)
    r: list[CheckResult] = []
    add = lambda *a: r.append(CheckResult("sales", *a))  # noqa: E731

    add("row_count", "error", n > 0, f"{n:,} rows", "> 0 rows")
    nulls = int(df[["transaction_id", "price", "sale_date", "district"]].isna().sum().sum())
    add("required_fields_not_null", "error", nulls == 0, f"{nulls} nulls",
        "no nulls in id, price, date, district")
    dupes = int(df["transaction_id"].duplicated().sum())
    add("transaction_id_unique", "error", dupes == 0, f"{dupes} duplicates", "0 duplicates")
    nonpos = int((df["price"] <= 0).sum())
    add("price_positive", "error", nonpos == 0, f"{nonpos} rows <= 0", "all prices > 0")

    today = pd.Timestamp.today().normalize()
    future = int((df["sale_date"] > today).sum())
    early = int((df["sale_date"].dt.year < cfg["start_year"]).sum())
    add("sale_date_in_range", "error", future == 0 and early == 0,
        f"{future} future, {early} before {cfg['start_year']}", f"{cfg['start_year']} to today")

    bad_type = int((~df["property_type_code"].isin(list("DSTFO"))).sum())
    add("property_type_valid", "error", bad_type == 0, f"{bad_type} invalid codes", "codes D,S,T,F,O")

    unknown_county = int((~df["county"].isin(cfg.counties)).sum())
    add("county_in_region", "error", unknown_county == 0, f"{unknown_county} rows", "all rows in NW counties")

    miss_pc = df["postcode"].isna().mean() if n else 0
    add("postcode_completeness", "warn", miss_pc <= q["max_missing_postcode_share"],
        f"{miss_pc:.2%} missing", f"<= {q['max_missing_postcode_share']:.0%} missing")

    outl = df["is_price_outlier"].mean() if n else 0
    add("price_outlier_share", "warn", outl <= 0.01, f"{outl:.2%} flagged", "<= 1% outside price bounds")

    if n:
        monthly = df.groupby("sale_month").size()
        full = pd.date_range(monthly.index.min(), monthly.index.max(), freq="MS")
        missing = [m.strftime("%Y-%m") for m in full.difference(monthly.index)]
        add("no_missing_months", "warn", not missing, f"{len(missing)} missing months",
            "every month between first and last sale has data")
        # Registrations lag completions, so the last `provisional_months` months are
        # treated as provisional. Check that the newest "complete" month really looks
        # complete; if this fails, increase provisional_months in pipeline.yaml.
        p = int(cfg.raw.get("provisional_months", 6))
        if len(monthly) > p + 13:
            first_complete = monthly.iloc[-(p + 1)]
            typical = monthly.iloc[-(p + 13):-(p + 1)].median()
            add("complete_month_volume", "warn", first_complete >= 0.7 * typical,
                f"{monthly.index[-(p + 1)]:%b %Y}: {first_complete:,} vs typical {typical:,.0f}",
                f"newest complete month >= 70% of prior 12-month median ({p} provisional months)")
    return r


def check_rates(df: pd.DataFrame) -> list[CheckResult]:
    r: list[CheckResult] = []
    add = lambda *a: r.append(CheckResult("rates", *a))  # noqa: E731
    add("row_count", "error", len(df) > 0, f"{len(df)} months", "> 0 months")
    if "bank_rate" in df:
        br = df["bank_rate"].dropna()
        ok = br.between(0, 20).all()
        add("bank_rate_range", "error", bool(ok), f"{br.min():.2f}% to {br.max():.2f}%", "0% to 20%")
        gaps = int(df["bank_rate"].isna().sum())
        add("bank_rate_complete", "error", gaps == 0, f"{gaps} empty months", "no empty months")
        # Rates are reused from the previous run if the BoE is unavailable; flag staleness.
        last = pd.Timestamp(df.loc[df["bank_rate"].notna(), "month"].max())
        months_old = (pd.Timestamp.today().to_period("M") - last.to_period("M")).n
        add("rates_freshness", "warn", months_old <= 1, f"latest rate {last:%b %Y} ({months_old} months old)",
            "Bank Rate available for this or last month")
    else:
        add("bank_rate_present", "error", False, "missing", "bank_rate column present")
    return r


def run_checks(sales: pd.DataFrame, rates: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    results = check_sales(sales, cfg) + check_rates(rates)
    df = pd.DataFrame([asdict(x) for x in results])
    df["checked_at"] = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in df.itertuples():
        level = logging.INFO if row.passed else (logging.ERROR if row.severity == "error" else logging.WARNING)
        log.log(level, "DQ %-6s %-28s %s (%s)", "PASS" if row.passed else "FAIL",
                f"{row.dataset}.{row.check}", row.observed, row.expectation)
    return df


def enforce(results: pd.DataFrame) -> None:
    failed = results[(~results["passed"]) & (results["severity"] == "error")]
    if not failed.empty:
        raise DataQualityError(
            "Blocking data quality failures: " + ", ".join(failed["dataset"] + "." + failed["check"]))
