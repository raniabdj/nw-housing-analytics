"""Build the static HTML report (published to GitHub Pages by the scheduled workflow).

Figures are built in Python as Plotly JSON. Colours are written as role tokens
("var:series-1") and resolved in the browser from CSS variables, so the same
report renders correctly in light and dark mode.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import warehouse
from .config import Config

log = logging.getLogger(__name__)
TEMPLATES = Path(__file__).parent / "templates"


# ----------------------------------------------------------------- formatting
def _num(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return v


def gbp(v, dp=0):
    return "n/a" if v is None else f"£{v:,.{dp}f}"


def pct(v, signed=True, dp=1):
    if v is None:
        return "n/a"
    s = f"{v * 100:+.{dp}f}%" if signed else f"{v * 100:.{dp}f}%"
    return s.replace("-", "−")


def _dates(s: pd.Series) -> list[str]:
    return pd.to_datetime(s).dt.strftime("%Y-%m-%d").tolist()


def _clean(values) -> list:
    return [None if (isinstance(v, float) and math.isnan(v)) else v for v in values]


BASE_LAYOUT = {
    "margin": {"l": 56, "r": 16, "t": 8, "b": 40},
    "hovermode": "x unified",
    "showlegend": True,
    "legend": {"orientation": "h", "y": 1.08, "x": 0, "font": {"size": 12}},
    "xaxis": {"showgrid": False, "linecolor": "var:axis", "tickfont": {"size": 12}},
    "yaxis": {"gridcolor": "var:grid", "zeroline": False, "tickfont": {"size": 12}},
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "font": {"family": "Inter, system-ui, sans-serif", "color": "var:text-secondary"},
}


def _layout(**overrides) -> dict:
    lay = json.loads(json.dumps(BASE_LAYOUT))
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(lay.get(k), dict):
            lay[k].update(v)
        else:
            lay[k] = v
    return lay


def _period_shapes(periods: pd.DataFrame, yref="paper", only=("Pandemic & stamp duty holiday", "Rates rising")):
    shapes, notes = [], []
    for p in periods.itertuples():
        if p.market_period in only:
            shapes.append({"type": "rect", "xref": "x", "yref": yref, "x0": str(p.start_month)[:10],
                           "x1": (pd.Timestamp(p.end_month) + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d"), "y0": 0, "y1": 1, "fillcolor": "var:band",
                           "line": {"width": 0}, "layer": "below"})
            notes.append({"x": str(p.start_month)[:10], "y": 1, "xref": "x", "yref": "paper",
                          "text": p.market_period, "showarrow": False, "xanchor": "left", "yanchor": "top",
                          "font": {"size": 11, "color": "var:text-muted"}})
    return shapes, notes


# ------------------------------------------------------------------- figures
def fig_volume_and_rates(rm: pd.DataFrame, periods: pd.DataFrame) -> tuple[dict, dict]:
    """Two charts sharing a time axis (never a dual-axis chart)."""
    comp = rm[rm.is_complete_month]
    prov = rm[~rm.is_complete_month]
    shapes, notes = _period_shapes(periods)
    vol = {
        "data": [
            {"type": "bar", "x": _dates(comp.month), "y": comp.sales.tolist(), "name": "Sales registered",
             "marker": {"color": "var:series-1-soft"}, "hovertemplate": "%{y:,} sales<extra></extra>"},
            {"type": "bar", "x": _dates(prov.month), "y": prov.sales.tolist(), "name": "Provisional (registration lag)",
             "marker": {"color": "var:provisional"}, "hovertemplate": "%{y:,} so far<extra></extra>"},
            {"type": "scatter", "mode": "lines", "x": _dates(comp.month), "y": _clean(comp.sales_3m_avg.round(0)),
             "name": "3-month average", "line": {"color": "var:series-1", "width": 2},
             "hovertemplate": "%{y:,.0f} avg<extra></extra>"},
        ],
        "layout": _layout(shapes=shapes, annotations=notes, bargap=0.15,
                          yaxis={"title": {"text": "Sales per month", "font": {"size": 12}}, "tickformat": ","}),
    }
    rate_traces = [
        {"type": "scatter", "mode": "lines", "x": _dates(rm.month), "y": _clean(rm.bank_rate_month_end),
         "name": "Bank Rate", "line": {"color": "var:series-1", "width": 2, "shape": "hv"},
         "hovertemplate": "%{y:.2f}%<extra></extra>"},
    ]
    if "mortgage_2y_fixed_75ltv" in rm and rm.mortgage_2y_fixed_75ltv.notna().any():
        rate_traces.append({"type": "scatter", "mode": "lines", "x": _dates(rm.month),
                            "y": _clean(rm.mortgage_2y_fixed_75ltv), "name": "2-year fixed mortgage (75% LTV)",
                            "line": {"color": "var:series-2", "width": 2},
                            "hovertemplate": "%{y:.2f}%<extra></extra>"})
    rates = {"data": rate_traces,
             "layout": _layout(shapes=shapes, yaxis={"title": {"text": "Interest rate (%)", "font": {"size": 12}},
                                                     "ticksuffix": "%", "rangemode": "tozero"})}
    return vol, rates


def fig_price_index(idx: pd.DataFrame, base_year: int) -> dict:
    return {
        "data": [
            {"type": "scatter", "mode": "lines", "x": _dates(idx.month), "y": _clean(idx.median_index.round(1)),
             "name": "Raw median price", "line": {"color": "var:series-2", "width": 2},
             "hovertemplate": "%{y:.1f}<extra></extra>"},
            {"type": "scatter", "mode": "lines", "x": _dates(idx.month), "y": _clean(idx.mix_adjusted_index.round(1)),
             "name": "Mix-adjusted index", "line": {"color": "var:series-1", "width": 2},
             "hovertemplate": "%{y:.1f}<extra></extra>"},
        ],
        "layout": _layout(yaxis={"title": {"text": f"Index ({base_year} = 100)", "font": {"size": 12}}},
                          shapes=[{"type": "line", "xref": "paper", "x0": 0, "x1": 1, "y0": 100, "y1": 100,
                                   "line": {"color": "var:axis", "width": 1}}]),
    }


def fig_payment(rm: pd.DataFrame, ltv: float, term: int) -> dict:
    d = rm[rm.is_complete_month & rm.median_monthly_payment.notna()]
    return {
        "data": [{"type": "scatter", "mode": "lines", "x": _dates(d.month),
                  "y": _clean(d.median_monthly_payment.round(0)), "name": "Monthly repayment",
                  "line": {"color": "var:series-1", "width": 2}, "fill": "tozeroy", "fillcolor": "var:series-1-fill",
                  "hovertemplate": "£%{y:,.0f} a month<extra></extra>"}],
        "layout": _layout(showlegend=False, yaxis={"tickprefix": "£", "tickformat": ",",
                                                   "title": {"text": "£ per month", "font": {"size": 12}}}),
        "note": f"Median price × {ltv:.0%} loan, {term}-year repayment mortgage at the 2-year fixed rate.",
    }


def fig_rate_lags(sens: pd.DataFrame) -> dict:
    d = sens[sens.rate_measure == "bank_rate"].sort_values("lag_months")
    colors = ["var:series-1" if b else "var:muted-mark" for b in d.is_best_lag]
    return {
        "data": [{"type": "scatter", "mode": "markers", "x": d.lag_months.tolist(),
                  "y": (d.effect_per_1pp * 100).round(2).tolist(), "name": "Effect on sales",
                  "marker": {"size": 10, "color": colors, "line": {"width": 2, "color": "var:surface"}},
                  "error_y": {"type": "data", "symmetric": False,
                              "array": ((d.ci_high - d.effect_per_1pp) * 100).round(2).tolist(),
                              "arrayminus": ((d.effect_per_1pp - d.ci_low) * 100).round(2).tolist(),
                              "color": "var:axis", "thickness": 1.5, "width": 0},
                  "customdata": d.p_value.tolist(),
                  "hovertemplate": "Lag %{x} months: %{y:.1f}% per +1pp<br>p = %{customdata:.2g}<extra></extra>"}],
        "layout": _layout(showlegend=False, hovermode="closest",
                          xaxis={"title": {"text": "Months after the rate change", "font": {"size": 12}}, "dtick": 1,
                                 "zeroline": False},
                          yaxis={"title": {"text": "% change in sales per +1pp", "font": {"size": 12}},
                                 "ticksuffix": "%"},
                          shapes=[{"type": "line", "xref": "paper", "x0": 0, "x1": 1, "y0": 0, "y1": 0,
                                   "line": {"color": "var:axis", "width": 1}}]),
    }


def fig_segments(seg: pd.DataFrame, dimension: str, focus: str, metric: str, label: str) -> dict:
    d = seg[seg.dimension == dimension].sort_values(metric)
    colors = ["var:series-1" if s.upper() == focus.upper() else "var:muted-mark" for s in d.segment]
    if dimension != "District":
        colors = ["var:series-1"] * len(d)
    vals = d[metric] * 100
    lo, hi = min(0.0, float(vals.min())), max(0.0, float(vals.max()))
    pad = max(hi - lo, 1.0) * 0.22
    x_range = [lo - (pad if lo < 0 else 0), hi + (pad if hi > 0 else pad * 0.15)]
    return {
        "data": [{"type": "bar", "orientation": "h", "y": d.segment.tolist(), "x": (d[metric] * 100).round(1).tolist(),
                  "marker": {"color": colors}, "name": label,
                  "text": [pct(v) for v in d[metric]], "textposition": "outside", "cliponaxis": False,
                  "textfont": {"size": 11, "color": "var:text-secondary"},
                  "hovertemplate": "%{y}: %{x:.1f}%<extra></extra>"}],
        "layout": _layout(showlegend=False, hovermode="closest", bargap=0.35,
                          margin={"l": 170, "r": 56, "t": 8, "b": 40},
                          height=max(220, 26 * len(d) + 60),
                          xaxis={"ticksuffix": "%", "showgrid": True, "gridcolor": "var:grid", "range": x_range,
                                 "zeroline": True, "zerolinecolor": "var:axis"},
                          yaxis={"gridcolor": "rgba(0,0,0,0)", "automargin": True, "ticksuffix": "  "}),
    }


def fig_drivers(drivers: pd.DataFrame) -> dict:
    d = drivers[drivers.factor != "District"].iloc[::-1]
    return {
        "data": [{"type": "scatter", "mode": "markers", "y": d.comparison.tolist(),
                  "x": (d.premium * 100).round(1).tolist(), "name": "Price premium",
                  "marker": {"size": 10, "color": "var:series-1", "line": {"width": 2, "color": "var:surface"}},
                  "error_x": {"type": "data", "symmetric": False, "array": ((d.ci_high - d.premium) * 100).round(2).tolist(),
                              "arrayminus": ((d.premium - d.ci_low) * 100).round(2).tolist(),
                              "color": "var:axis", "thickness": 1.5, "width": 0},
                  "hovertemplate": "%{y}: %{x:+.1f}%<extra></extra>"}],
        "layout": _layout(showlegend=False, hovermode="closest", margin={"l": 190, "r": 24, "t": 8, "b": 40},
                          height=260, xaxis={"ticksuffix": "%", "showgrid": True, "gridcolor": "var:grid",
                                             "zeroline": True, "zerolinecolor": "var:axis"}),
    }


# ---------------------------------------------------------------- narrative
def findings(h: dict) -> list[str]:
    out = []
    h = dict(h)
    h["baseline_year"] = int(h["baseline_year"])
    if h.get("region_volume_change_vs_baseline") is not None:
        out.append(
            f"Sales in {h['region_name']} over the latest 12 complete months are "
            f"{pct(h['region_volume_change_vs_baseline'])} versus {h['baseline_year']}, "
            f"while the median price is {pct(h['region_price_change_vs_baseline'])}. "
            "Fewer homes are changing hands, but prices have not fallen.")
    if h.get("rate_effect_per_1pp") is not None and h.get("rate_effect_lag_months", -1) >= 0:
        sig = "statistically significant" if (h.get("rate_effect_p_value") or 1) < 0.05 else "not statistically significant"
        out.append(
            f"After controlling for seasonality, trend, the 2020 lockdown and the stamp duty holiday, each "
            f"1 percentage point rise in Bank Rate is associated with {pct(h['rate_effect_per_1pp'])} monthly sales "
            f"(95% CI {pct(h['rate_effect_ci_low'])} to {pct(h['rate_effect_ci_high'])}), with the strongest "
            f"fit about {int(h['rate_effect_lag_months'])} months after the change ({sig}).")
    if h.get("monthly_payment_2021"):
        out.append(
            f"The monthly repayment on a median-priced home has moved from {gbp(h['monthly_payment_2021'])} in 2021 "
            f"to {gbp(h['monthly_payment_last12'])} over the last year ({pct(h['monthly_payment_change_vs_2021'])}), "
            "which is how higher rates reach buyers even when prices barely move.")
    if h.get("focus_volume_change_vs_baseline") is not None:
        out.append(
            f"{h['focus_district']}: sales {pct(h['focus_volume_change_vs_baseline'])} and median price "
            f"{pct(h['focus_price_change_vs_baseline'])} against {h['baseline_year']}, compared with "
            f"{pct(h['region_volume_change_vs_baseline'])} and {pct(h['region_price_change_vs_baseline'])} for the region.")
    if h.get("mix_index_latest") and h.get("median_index_latest"):
        gap = h["median_index_latest"] - h["mix_index_latest"]
        lead = (f"The mix-adjusted price index stands at {h['mix_index_latest']:.1f} against "
                f"{h['median_index_latest']:.1f} for the raw median ({h['baseline_year']} = 100). ")
        if abs(gap) < 2:
            out.append(lead + "The two agree closely, so changes in the type of homes sold explain little "
                              "of the headline price movement.")
        else:
            direction = "overstates" if gap > 0 else "understates"
            out.append(lead + f"The raw median {direction} true like-for-like growth by {abs(gap):.1f} points, "
                              "because the mix of homes being sold has shifted.")
    return out


# --------------------------------------------------------------------- build
def build(cfg: Config) -> Path:
    t = lambda name: warehouse.read_table(cfg, name)  # noqa: E731
    rm, seg, idx = t("mart_region_month"), t("mart_segment_change"), t("analysis_price_index")
    sens, drivers, dq = t("analysis_rate_sensitivity"), t("analysis_price_drivers"), t("dq_results")
    periods, events = t("dim_market_period"), t("dim_market_event")
    heads = {r.metric: _num(r.value) for r in t("analysis_headlines").itertuples()}
    heads["is_demo"] = str(heads.get("is_demo")) == "True"

    ma = cfg["mortgage_assumptions"]
    focus = cfg["focus_district"].title()
    vol, rates = fig_volume_and_rates(rm, periods)
    figures = {
        "volume": vol, "rates": rates,
        "index": fig_price_index(idx, cfg["baseline_year"]),
        "payment": fig_payment(rm, ma["loan_to_value"], ma["term_years"]),
        "lags": fig_rate_lags(sens),
        "seg_type": fig_segments(seg, "Property type", focus, "volume_change", "Sales change"),
        "seg_district_vol": fig_segments(seg, "District", focus, "volume_change", "Sales change"),
        "seg_district_price": fig_segments(seg, "District", focus, "price_change", "Price change"),
        "drivers": fig_drivers(drivers),
    }

    kpis = [
        {"label": "Median price, last 12 months", "value": gbp(heads.get("median_price_last12")),
         "delta": pct(heads.get("median_price_yoy")), "delta_label": "vs previous 12 months"},
        {"label": "Sales, last 12 months", "value": f"{int(heads.get('sales_last12') or 0):,}",
         "delta": pct(heads.get("region_volume_change_vs_baseline")),
         "delta_label": f"monthly rate vs {cfg['baseline_year']}"},
        {"label": "Bank Rate now", "value": f"{heads.get('bank_rate_latest', 0):.2f}%",
         "delta": f"peak {heads.get('peak_bank_rate', 0):.2f}%", "delta_label": "in this period"},
        {"label": "Monthly repayment, median home", "value": gbp(heads.get("monthly_payment_last12")),
         "delta": pct(heads.get("monthly_payment_change_vs_2021")), "delta_label": "vs 2021"},
    ]

    dq_rows = dq.assign(status=np.where(dq.passed, "Pass", np.where(dq.severity == "error", "Fail", "Warning")))
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    html = env.get_template("report.html.j2").render(
        h=heads, kpis=kpis, findings=findings(heads), figures=json.dumps(figures),
        dq=dq_rows.to_dict("records"), events=events.to_dict("records"),
        seg_table=seg[seg.dimension == "District"].sort_values("volume_change").to_dict("records"),
        focus=focus, region=cfg["region_name"], baseline_year=cfg["baseline_year"],
        generated=datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC"),
        payment_note=figures["payment"]["note"], gbp=gbp, pct=pct, year=datetime.now().year,
        provisional=int(cfg.raw.get("provisional_months", 6)),
    )
    out = cfg.paths.site_dir / ("index_demo.html" if cfg.demo else "index.html")
    out.write_text(html, encoding="utf-8")
    log.info("Report written to %s", out)
    return out
