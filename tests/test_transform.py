import pandas as pd

from conftest import ppd_row
from nwhousing.extract.land_registry import PPD_COLUMNS
from nwhousing.transform.rates import to_monthly
from nwhousing.transform.sales import apply_changes, clean_price_paid


def test_clean_types_and_labels(raw_ppd):
    df = clean_price_paid(raw_ppd)
    row = df.set_index("transaction_id").loc["A1"]
    assert row.price == 200000
    assert row.sale_date == pd.Timestamp("2024-03-15")
    assert row.sale_month == pd.Timestamp("2024-03-01")
    assert row.outcode == "L18"
    assert row.property_type == "Semi-detached"
    assert row.tenure == "Freehold"
    assert row.town_city == "Liverpool"


def test_flags(raw_ppd):
    df = clean_price_paid(raw_ppd).set_index("transaction_id")
    assert bool(df.loc["A4", "is_price_outlier"])
    assert not bool(df.loc["A5", "is_standard"])          # category B / type O
    assert bool(df.loc["A3", "is_new_build"])
    assert pd.isna(df.loc["A3", "postcode"]) and pd.isna(df.loc["A3", "outcode"])


def test_unparseable_rows_dropped(raw_ppd):
    bad = raw_ppd.copy()
    bad.loc[0, "price"] = "not-a-number"
    assert "A1" not in set(clean_price_paid(bad)["transaction_id"])


def test_cdc_add_change_delete(raw_ppd):
    current = clean_price_paid(raw_ppd)
    changes = pd.DataFrame([
        ppd_row("A1", price=210000, status="C"),     # correction
        ppd_row("A2", status="D"),                   # deletion
        ppd_row("NEW1", price=300000, status="A"),   # addition
    ], columns=PPD_COLUMNS)
    merged = apply_changes(current, changes).set_index("transaction_id")
    assert merged.loc["A1", "price"] == 210000
    assert "A2" not in merged.index
    assert merged.loc["NEW1", "price"] == 300000
    assert merged.index.is_unique
    assert len(merged) == len(current)               # +1 added, -1 deleted


def test_cdc_is_idempotent(raw_ppd):
    current = clean_price_paid(raw_ppd)
    changes = pd.DataFrame([ppd_row("NEW1", status="A")], columns=PPD_COLUMNS)
    once = apply_changes(current, changes)
    twice = apply_changes(once, changes)
    assert len(once) == len(twice)


def test_rates_monthly_forward_fill_inside_only():
    long = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-05", "2024-01-20", "2024-04-02", "2024-02-29"]),
        "series_code": ["IUDBEDR", "IUDBEDR", "IUDBEDR", "IUMBV34"],
        "series_name": ["bank_rate", "bank_rate", "bank_rate", "mortgage_2y_fixed_75ltv"],
        "value": [5.0, 5.25, 5.25, 5.9],
    })
    m = to_monthly(long).set_index("month")
    assert m.loc["2024-01-01", "bank_rate_month_end"] == 5.25
    assert m.loc["2024-03-01", "bank_rate"] == 5.125            # gap filled from January's mean
    assert pd.isna(m.loc["2024-04-01", "mortgage_2y_fixed_75ltv"])  # not extrapolated past last value
