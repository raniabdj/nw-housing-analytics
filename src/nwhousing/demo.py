"""Synthetic demo data in the exact formats of the real sources.

Used for:
  * `python -m nwhousing run --demo`: try the full pipeline offline in ~1 minute
  * the end-to-end test in CI, so tests never depend on government websites

The numbers are SYNTHETIC. They imitate the shape of the market (seasonality,
the 2020 lockdown, the stamp duty holiday, the rate cycle) so charts look
sensible, but they are not real findings. Every demo report carries a banner.
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

# district -> (county, base price £k, relative volume, [(outcode, lat, lon)])
DISTRICTS = {
    "LIVERPOOL": ("MERSEYSIDE", 175, 1.6, [("L1", 53.402, -2.982), ("L8", 53.389, -2.966), ("L15", 53.397, -2.919), ("L18", 53.370, -2.909), ("L25", 53.366, -2.851)]),
    "WIRRAL": ("MERSEYSIDE", 200, 1.2, [("CH41", 53.393, -3.031), ("CH43", 53.380, -3.060), ("CH48", 53.380, -3.170), ("CH60", 53.333, -3.090)]),
    "SEFTON": ("MERSEYSIDE", 195, 1.0, [("L20", 53.453, -2.990), ("L23", 53.483, -3.020), ("PR8", 53.631, -3.010)]),
    "KNOWSLEY": ("MERSEYSIDE", 160, 0.5, [("L34", 53.433, -2.830), ("L36", 53.410, -2.840)]),
    "ST HELENS": ("MERSEYSIDE", 165, 0.6, [("WA9", 53.443, -2.715), ("WA10", 53.455, -2.760)]),
    "MANCHESTER": ("GREATER MANCHESTER", 240, 1.7, [("M1", 53.479, -2.236), ("M14", 53.448, -2.226), ("M20", 53.427, -2.231), ("M40", 53.511, -2.191)]),
    "SALFORD": ("GREATER MANCHESTER", 215, 0.9, [("M5", 53.480, -2.282), ("M6", 53.493, -2.293), ("M28", 53.514, -2.397)]),
    "TRAFFORD": ("GREATER MANCHESTER", 340, 0.8, [("WA14", 53.385, -2.354), ("WA15", 53.381, -2.320), ("M33", 53.424, -2.321)]),
    "STOCKPORT": ("GREATER MANCHESTER", 290, 1.0, [("SK1", 53.408, -2.150), ("SK4", 53.420, -2.180), ("SK7", 53.364, -2.137)]),
    "BOLTON": ("GREATER MANCHESTER", 180, 0.9, [("BL1", 53.588, -2.441), ("BL3", 53.565, -2.437)]),
    "WIGAN": ("GREATER MANCHESTER", 170, 1.0, [("WN1", 53.551, -2.630), ("WN6", 53.570, -2.680)]),
    "OLDHAM": ("GREATER MANCHESTER", 175, 0.7, [("OL1", 53.546, -2.110), ("OL8", 53.528, -2.113)]),
    "PRESTON": ("LANCASHIRE", 170, 0.7, [("PR1", 53.759, -2.699), ("PR2", 53.782, -2.708)]),
    "LANCASTER": ("LANCASHIRE", 200, 0.6, [("LA1", 54.047, -2.799), ("LA4", 54.070, -2.860)]),
    "BLACKPOOL": ("BLACKPOOL", 135, 0.6, [("FY1", 53.816, -3.053), ("FY4", 53.795, -3.030)]),
    "BLACKBURN WITH DARWEN": ("BLACKBURN WITH DARWEN", 140, 0.5, [("BB1", 53.750, -2.480), ("BB2", 53.740, -2.500)]),
    "CHESHIRE EAST": ("CHESHIRE EAST", 300, 1.1, [("SK9", 53.326, -2.231), ("CW1", 53.097, -2.440), ("SK10", 53.262, -2.130)]),
    "CHESHIRE WEST AND CHESTER": ("CHESHIRE WEST AND CHESTER", 270, 1.0, [("CH1", 53.191, -2.892), ("CW8", 53.250, -2.570)]),
    "WARRINGTON": ("WARRINGTON", 250, 0.7, [("WA1", 53.390, -2.585), ("WA4", 53.370, -2.570)]),
    "HALTON": ("HALTON", 170, 0.4, [("WA7", 53.330, -2.700), ("WA8", 53.365, -2.730)]),
}
OUTSIDE_REGION = ("LEEDS", "WEST YORKSHIRE", 250, 0.8, [("LS6", 53.819, -1.574)])

TYPE_MIX = {"D": (0.18, 1.65), "S": (0.30, 1.05), "T": (0.33, 0.80), "F": (0.15, 0.70), "O": (0.04, 1.2)}

# Approximate Bank Rate path (synthetic demo uses the real shape of the cycle)
BANK_RATE_CHANGES = [
    ("2017-01-01", 0.25), ("2017-11-02", 0.50), ("2018-08-02", 0.75), ("2020-03-11", 0.25),
    ("2020-03-19", 0.10), ("2021-12-16", 0.25), ("2022-02-03", 0.50), ("2022-03-17", 0.75),
    ("2022-05-05", 1.00), ("2022-06-16", 1.25), ("2022-08-04", 1.75), ("2022-09-22", 2.25),
    ("2022-11-03", 3.00), ("2022-12-15", 3.50), ("2023-02-02", 4.00), ("2023-03-23", 4.25),
    ("2023-05-11", 4.50), ("2023-06-22", 5.00), ("2023-08-03", 5.25), ("2024-08-01", 5.00),
    ("2024-11-07", 4.75), ("2025-02-06", 4.50), ("2025-05-08", 4.25), ("2025-08-07", 4.00),
]


def _bank_rate_daily(end: date) -> pd.Series:
    idx = pd.bdate_range("2017-01-02", end)
    s = pd.Series(np.nan, index=idx)
    for d, r in BANK_RATE_CHANGES:
        s[s.index >= pd.Timestamp(d)] = r
    return s.ffill()


def _shock(month: pd.Timestamp) -> float:
    ym = month.strftime("%Y-%m")
    return {"2020-04": 0.35, "2020-05": 0.45, "2020-06": 0.7, "2021-03": 1.45, "2021-06": 1.9,
            "2021-09": 1.4, "2022-10": 0.9, "2022-11": 0.85, "2025-03": 1.35}.get(ym, 1.0)


def generate(dest: Path, start_year: int = 2018, seed: int = 7) -> dict[str, Path]:
    rng = np.random.default_rng(seed)
    dest.mkdir(parents=True, exist_ok=True)
    today = pd.Timestamp.today().normalize()
    last_month = (today - pd.DateOffset(months=2)).to_period("M").to_timestamp()
    months = pd.date_range(f"{start_year}-01-01", last_month, freq="MS")

    br_daily = _bank_rate_daily(today.date())
    br_month = br_daily.resample("MS").mean()

    rows = []
    districts = list(DISTRICTS.items()) + [(OUTSIDE_REGION[0], OUTSIDE_REGION[1:])]
    for i, m in enumerate(months):
        lagged_rate = br_month.get(m - pd.DateOffset(months=4), 0.5)
        season = 1 + 0.12 * np.sin((m.month - 4) / 12 * 2 * np.pi)
        volume_factor = season * _shock(m) * np.exp(-0.085 * lagged_rate)
        months_back = len(months) - 1 - i
        lag_factor = {0: 0.35, 1: 0.65, 2: 0.88}.get(months_back, 1.0)   # registration lag
        years = (m - pd.Timestamp("2018-01-01")).days / 365.25
        growth = 1 + 0.035 * years + 0.06 * max(0, min(years - 2.3, 2.0)) - 0.02 * max(0, years - 5.2)

        for district, (county, base_k, rel_vol, outcodes) in districts:
            n = rng.poisson(120 * rel_vol * volume_factor * lag_factor)
            if n == 0:
                continue
            types = rng.choice(list(TYPE_MIX), size=n, p=[v[0] for v in TYPE_MIX.values()])
            mult = np.array([TYPE_MIX[t][1] for t in types])
            new = rng.random(n) < 0.09
            price = base_k * 1000 * growth * mult * np.where(new, 1.12, 1.0) * rng.lognormal(0, 0.28, n)
            price = np.round(price / 500) * 500
            outlier = rng.random(n) < 0.002
            price[outlier] = rng.choice([1500, 6_500_000], size=outlier.sum())
            days = rng.integers(0, m.days_in_month, n)
            for k in range(n):
                oc = outcodes[rng.integers(0, len(outcodes))][0]
                pc = "" if rng.random() < 0.003 else f"{oc} {rng.integers(1, 9)}{'ABDEFGHJ'[rng.integers(0, 8)]}{'LNPQRSTU'[rng.integers(0, 8)]}"
                t = types[k]
                rows.append([
                    "{" + str(uuid.UUID(int=int(rng.integers(0, 2**63)) << 64 | k)).upper() + "}",
                    int(price[k]), (m + pd.Timedelta(days=int(days[k]))).strftime("%Y-%m-%d 00:00"),
                    pc, t, "Y" if new[k] else "N", "L" if t == "F" else ("L" if rng.random() < 0.08 else "F"),
                    str(rng.integers(1, 200)), "", "DEMO STREET", "", district.title(), district, county,
                    "B" if (t == "O" or rng.random() < 0.06) else "A", "A",
                ])

    df = pd.DataFrame(rows)
    df["year"] = df[2].str.slice(0, 4).astype(int)
    files: dict[str, Path] = {}
    for y, part in df.groupby("year"):
        p = dest / f"pp-{y}.csv"
        part.drop(columns="year").to_csv(p, header=False, index=False)
        files[f"pp-{y}"] = p

    # Monthly update file: a few additions, changes and deletions (CDC test data)
    recent = df[df["year"] == df["year"].max()].sample(60, random_state=seed).drop(columns="year")
    changes = recent.iloc[:20].copy(); changes[1] = (changes[1] * 1.05).round(-2).astype(int); changes[15] = "C"
    deletes = recent.iloc[20:30].copy(); deletes[15] = "D"
    adds = recent.iloc[30:].copy()
    adds[0] = ["{" + str(uuid.uuid4()).upper() + "}" for _ in range(len(adds))]; adds[15] = "A"
    monthly = pd.concat([changes, deletes, adds])
    p = dest / "pp-monthly-update-new-version.csv"
    monthly.to_csv(p, header=False, index=False)
    files["monthly"] = p

    # Bank of England CSV (IADB format): daily bank rate + month-end mortgage rate
    boe = pd.DataFrame({"DATE": br_daily.index, "IUDBEDR": br_daily.values})
    mort = br_daily.resample("ME").last()
    mort = (mort + 1.6 + np.where((mort.index >= "2022-10-01") & (mort.index <= "2022-12-31"), 1.5, 0)).round(2)
    mort = mort[mort.index <= last_month + pd.offsets.MonthEnd(0)]
    boe = boe.merge(pd.DataFrame({"DATE": mort.index, "IUMBV34": mort.values}), on="DATE", how="outer")
    boe = boe.sort_values("DATE")
    boe["DATE"] = boe["DATE"].dt.strftime("%d %b %Y")
    p = dest / "boe.csv"
    boe.to_csv(p, index=False)
    files["boe"] = p

    outcodes = [{"outcode": oc, "latitude": lat, "longitude": lon, "admin_district": d.title(), "lookup_status": "ok"}
                for d, (_, _, _, ocs) in DISTRICTS.items() for oc, lat, lon in ocs]
    p = dest / "outcodes.json"
    p.write_text(json.dumps(outcodes, indent=1))
    files["outcodes"] = p
    return files
