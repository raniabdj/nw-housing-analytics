import pandas as pd
import pytest

from nwhousing.quality import DataQualityError, enforce, run_checks
from nwhousing.transform.sales import clean_price_paid


def _rates():
    return pd.DataFrame({"month": pd.date_range("2018-01-01", periods=3, freq="MS"), "bank_rate": [0.5, 0.5, 0.75]})


def test_clean_region_data_passes(raw_ppd, cfg):
    sales = clean_price_paid(raw_ppd[raw_ppd.county == "MERSEYSIDE"])
    results = run_checks(sales, _rates(), cfg)
    enforce(results)                                        # no exception
    assert results[results.severity == "error"].passed.all()


def test_duplicate_ids_block_the_pipeline(raw_ppd, cfg):
    sales = clean_price_paid(raw_ppd[raw_ppd.county == "MERSEYSIDE"])
    sales = pd.concat([sales, sales.head(1)])
    with pytest.raises(DataQualityError, match="transaction_id_unique"):
        enforce(run_checks(sales, _rates(), cfg))


def test_out_of_region_rows_block_the_pipeline(raw_ppd, cfg):
    sales = clean_price_paid(raw_ppd)                      # includes the LEEDS row
    with pytest.raises(DataQualityError, match="county_in_region"):
        enforce(run_checks(sales, _rates(), cfg))


def test_impossible_bank_rate_blocks_the_pipeline(raw_ppd, cfg):
    sales = clean_price_paid(raw_ppd[raw_ppd.county == "MERSEYSIDE"])
    rates = _rates()
    rates.loc[1, "bank_rate"] = 55
    with pytest.raises(DataQualityError, match="bank_rate_range"):
        enforce(run_checks(sales, rates, cfg))
