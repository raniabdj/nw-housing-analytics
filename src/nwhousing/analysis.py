"""Statistical analysis on the gold layer.

1. Mix-adjusted (hedonic) price index
   A simple median moves when the *mix* of homes sold changes (e.g. more flats
   one month). A regression of log(price) on month, district, property type,
   new-build and tenure isolates the pure time effect. It is fitted on
   cell-level aggregates with frequency weights, which gives exactly the same
   coefficients as fitting all individual sales but runs in seconds. Standard
   errors are rescaled with the within-cell variance so they also match the
   individual-level OLS.

2. Interest-rate sensitivity of transaction volumes
   log(monthly sales) regressed on Bank Rate lagged 0-9 months, with
   month-of-year seasonality, a linear trend and dummies for the 2020 lockdown
   and stamp duty holiday. The lag with the best AIC is reported, with
   Newey-West (HAC) standard errors because monthly series are autocorrelated.
   This is an association, not a causal estimate.

3. Headline numbers shared by the report and Power BI.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from . import warehouse
from .config import Config

log = logging.getLogger(__name__)

MAX_LAG = 9


# ---------------------------------------------------------------- price index
def _cells(cfg: Config) -> pd.DataFrame:
    with warehouse.connect(cfg) as con:
        return con.execute("""
            SELECT strftime(f.sale_month, '%Y-%m')    AS month,
                   f.district,
                   f.property_type_code              AS ptype,
                   CAST(f.is_new_build AS INTEGER)   AS new_build,
                   CAST(f.tenure = 'Leasehold' AS INTEGER) AS leasehold,
                   count(*)                          AS n,
                   avg(ln(price))                    AS mean_log_price,
                   sum(ln(price) * ln(price))        AS sum_sq
            FROM fact_sales f
            CROSS JOIN meta_cutoff c
            WHERE f.in_analysis AND f.sale_month <= c.last_complete_month
            GROUP BY ALL
        """).df()


def price_index(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    cells = _cells(cfg)
    months = sorted(cells["month"].unique())
    base_months = [m for m in months if m.startswith(str(cfg["baseline_year"]))] or months[:12]

    focus = cfg["focus_district"].upper()
    ref_district = focus if focus in set(cells["district"]) else sorted(cells["district"].unique())[0]
    model = smf.wls(
        f"mean_log_price ~ C(month, Treatment(reference='{months[0]}')) "
        f"+ C(district, Treatment(reference='{ref_district}')) "
        "+ C(ptype, Treatment(reference='T')) + new_build + leasehold",
        data=cells, weights=cells["n"],
    ).fit()

    # Rescale covariance to individual-level OLS: add within-cell sum of squares.
    n_total = cells["n"].sum()
    within_ss = (cells["sum_sq"] - cells["n"] * cells["mean_log_price"] ** 2).clip(lower=0).sum()
    between_ss = float(model.ssr)
    sigma2 = (between_ss + within_ss) / (n_total - model.df_model - 1)
    cov = model.cov_params() * (sigma2 / model.scale)
    se = np.sqrt(np.diag(cov))
    se = pd.Series(se, index=model.params.index)

    # Month effects -> index (baseline year average = 100)
    month_effects = {months[0]: 0.0}
    for name, coef in model.params.items():
        if name.startswith("C(month"):
            month_effects[name.split("[T.")[1].rstrip("]")] = coef
    idx = pd.Series(month_effects).sort_index()
    idx = np.exp(idx - idx[base_months].mean()) * 100

    with warehouse.connect(cfg) as con:
        med = con.execute("""
            SELECT strftime(month, '%Y-%m') AS month, median_price, sales
            FROM mart_region_month WHERE is_complete_month ORDER BY month""").df()
    med = med.set_index("month")
    med["median_index"] = med["median_price"] / med.loc[med.index.isin(base_months), "median_price"].mean() * 100

    out = pd.DataFrame({"mix_adjusted_index": idx}).join(med[["median_index", "median_price", "sales"]])
    out.index.name = "month"
    out = out.reset_index()
    out["month"] = pd.to_datetime(out["month"] + "-01")

    # Price drivers: % premium of each characteristic, holding the rest constant
    labels = {"C(ptype, Treatment(reference='T'))[T.D]": ("Property type", "Detached vs terraced"),
              "C(ptype, Treatment(reference='T'))[T.S]": ("Property type", "Semi-detached vs terraced"),
              "C(ptype, Treatment(reference='T'))[T.F]": ("Property type", "Flat vs terraced"),
              "new_build": ("Build", "New build vs existing"),
              "leasehold": ("Tenure", "Leasehold vs freehold")}
    rows = []
    for key, (group, label) in labels.items():
        if key in model.params:
            b, s = model.params[key], se[key]
            rows.append({"factor": group, "comparison": label,
                         "premium": np.exp(b) - 1,
                         "ci_low": np.exp(b - 1.96 * s) - 1, "ci_high": np.exp(b + 1.96 * s) - 1})
    for name, b in model.params.items():
        if name.startswith("C(district)"):
            rows.append({"factor": "District",
                         "comparison": f'{name.split("[T.")[1].rstrip("]").title()} vs {ref_district.title()}',
                         "premium": np.exp(b) - 1,
                         "ci_low": np.exp(b - 1.96 * se[name]) - 1, "ci_high": np.exp(b + 1.96 * se[name]) - 1})
    drivers = pd.DataFrame(rows)
    drivers["r_squared_cells"] = model.rsquared
    drivers["n_sales"] = int(n_total)
    log.info("Hedonic model: %s sales in %s cells, cell R² %.3f", f"{n_total:,}", len(cells), model.rsquared)
    return out, drivers


# ------------------------------------------------------------ rate sensitivity
def _controls(df: pd.DataFrame) -> pd.DataFrame:
    m = df["month"]
    df["moy"] = m.dt.month.astype(str)
    df["trend"] = np.arange(len(df)) / 12
    df["lockdown"] = m.between("2020-04-01", "2020-06-01").astype(int)
    df["sdlt_holiday"] = m.between("2020-07-01", "2021-09-01").astype(int)
    df["sdlt_deadline"] = m.isin(pd.to_datetime(["2021-06-01", "2021-09-01", "2025-03-01"])).astype(int)
    return df


def rate_sensitivity(cfg: Config) -> pd.DataFrame:
    with warehouse.connect(cfg) as con:
        sales = con.execute("""SELECT month, sales FROM mart_region_month
                               WHERE is_complete_month ORDER BY month""").df()
        rates = con.execute("SELECT month, * EXCLUDE (month, date_key) FROM fact_rates_monthly").df()
    sales["month"] = pd.to_datetime(sales["month"])
    rates["month"] = pd.to_datetime(rates["month"])
    rates = rates.set_index("month").sort_index()

    rows = []
    for rate_col in [c for c in ("bank_rate", "mortgage_2y_fixed_75ltv") if c in rates]:
        for lag in range(MAX_LAG + 1):
            lagged = rates[rate_col].shift(lag, freq="MS").rename("rate")
            df = _controls(sales.join(lagged, on="month").dropna().reset_index(drop=True))
            if len(df) < 36:
                continue
            fit = smf.ols("np.log(sales) ~ rate + C(moy) + trend + lockdown + sdlt_holiday + sdlt_deadline",
                          data=df).fit(cov_type="HAC", cov_kwds={"maxlags": 3})
            b, (lo, hi) = fit.params["rate"], fit.conf_int().loc["rate"]
            rows.append({"rate_measure": rate_col, "lag_months": lag, "coefficient": b,
                         "effect_per_1pp": np.exp(b) - 1, "ci_low": np.exp(lo) - 1, "ci_high": np.exp(hi) - 1,
                         "p_value": fit.pvalues["rate"], "r_squared": fit.rsquared, "aic": fit.aic,
                         "n_months": int(fit.nobs)})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["is_best_lag"] = out.groupby("rate_measure")["aic"].transform("min").eq(out["aic"])
    best = out[out.is_best_lag & (out.rate_measure == "bank_rate")]
    if not best.empty:
        b = best.iloc[0]
        log.info("Rate sensitivity: +1pp Bank Rate -> %.1f%% sales after %d months (p=%.3g)",
                 b.effect_per_1pp * 100, b.lag_months, b.p_value)
    return out


# --------------------------------------------------------------- headlines
def headlines(cfg: Config, index: pd.DataFrame, sens: pd.DataFrame) -> pd.DataFrame:
    focus = cfg["focus_district"].upper()
    with warehouse.connect(cfg) as con:
        rm = con.execute("SELECT * FROM mart_region_month WHERE is_complete_month ORDER BY month").df()
        seg = con.execute("SELECT * FROM mart_segment_change").df()
        cutoff = con.execute("SELECT * FROM meta_cutoff").df().iloc[0]
        total = con.execute("SELECT count(*) FROM fact_sales").fetchone()[0]
        n_analysis = con.execute("SELECT count(*) FROM fact_sales WHERE in_analysis").fetchone()[0]
        focus_rows = con.execute(
            "SELECT * FROM mart_district_month WHERE district = ? AND is_complete_month ORDER BY month",
            [focus]).df()

    last12 = rm.tail(12)
    prev12 = rm.iloc[-24:-12]
    peak_rate_row = rm.loc[rm["bank_rate"].idxmax()]
    low_period = rm[(rm["month"] >= "2021-01-01") & (rm["month"] <= "2021-12-01")]
    pay_now = last12["median_monthly_payment"].dropna()
    pay_low = low_period["median_monthly_payment"].dropna()

    def seg_val(dim, name, col):
        s = seg[(seg.dimension == dim) & (seg.segment.str.upper() == name.upper())]
        return float(s[col].iloc[0]) if not s.empty else np.nan

    region = cfg["region_name"]
    best = sens[(sens.rate_measure == "bank_rate") & sens.is_best_lag] if not sens.empty else sens
    vals = {
        "data_through": pd.Timestamp(cutoff["last_complete_month"]).strftime("%B %Y"),
        "latest_registered_month": pd.Timestamp(cutoff["latest_month"]).strftime("%B %Y"),
        "total_sales_loaded": int(total),
        "sales_in_analysis": int(n_analysis),
        "median_price_last12": float(last12["median_price"].median()),
        "median_price_yoy": float(last12["median_price"].median() / prev12["median_price"].median() - 1)
                            if len(prev12) else np.nan,
        "sales_last12": int(last12["sales"].sum()),
        "sales_yoy": float(last12["sales"].sum() / prev12["sales"].sum() - 1) if len(prev12) else np.nan,
        "region_volume_change_vs_baseline": seg_val("Region", region, "volume_change"),
        "region_price_change_vs_baseline": seg_val("Region", region, "price_change"),
        "focus_volume_change_vs_baseline": seg_val("District", focus.title(), "volume_change"),
        "focus_price_change_vs_baseline": seg_val("District", focus.title(), "price_change"),
        "focus_median_price_last12": float(focus_rows.tail(12)["median_price"].median()) if len(focus_rows) else np.nan,
        "peak_bank_rate": float(peak_rate_row["bank_rate"]),
        "bank_rate_latest": float(rm["bank_rate_month_end"].dropna().iloc[-1]),
        "monthly_payment_last12": float(pay_now.mean()) if len(pay_now) else np.nan,
        "monthly_payment_2021": float(pay_low.mean()) if len(pay_low) else np.nan,
        "mix_index_latest": float(index["mix_adjusted_index"].iloc[-1]),
        "median_index_latest": float(index["median_index"].iloc[-1]),
        "rate_effect_per_1pp": float(best["effect_per_1pp"].iloc[0]) if len(best) else np.nan,
        "rate_effect_ci_low": float(best["ci_low"].iloc[0]) if len(best) else np.nan,
        "rate_effect_ci_high": float(best["ci_high"].iloc[0]) if len(best) else np.nan,
        "rate_effect_lag_months": int(best["lag_months"].iloc[0]) if len(best) else -1,
        "rate_effect_p_value": float(best["p_value"].iloc[0]) if len(best) else np.nan,
        "baseline_year": cfg["baseline_year"],
        "focus_district": focus.title(),
        "region_name": region,
        "is_demo": cfg.demo,
    }
    vals["monthly_payment_change_vs_2021"] = (vals["monthly_payment_last12"] / vals["monthly_payment_2021"] - 1
                                              if vals["monthly_payment_2021"] else np.nan)
    return pd.DataFrame({"metric": list(vals), "value": [str(v) for v in vals.values()]})


def run(cfg: Config) -> list[str]:
    index, drivers = price_index(cfg)
    sens = rate_sensitivity(cfg)
    heads = headlines(cfg, index, sens)
    warehouse.write_table(cfg, "analysis_price_index", index)
    warehouse.write_table(cfg, "analysis_price_drivers", drivers)
    warehouse.write_table(cfg, "analysis_rate_sensitivity", sens)
    warehouse.write_table(cfg, "analysis_headlines", heads)
    return ["analysis_price_index", "analysis_price_drivers", "analysis_rate_sensitivity", "analysis_headlines"]
