from datetime import date

import pandas as pd

from nwhousing.extract import boe, postcodes
from nwhousing.extract.land_registry import filter_region


def test_filter_region_streams_and_filters(raw_ppd, tmp_path):
    p = tmp_path / "pp.csv"
    raw_ppd.to_csv(p, header=False, index=False)
    df, rows_read = filter_region(p, ["MERSEYSIDE"], chunk_rows=2)   # small chunks exercise streaming
    assert rows_read == 6
    assert len(df) == 5
    assert set(df["county"]) == {"MERSEYSIDE"}


def test_filter_region_handles_15_column_files(raw_ppd, tmp_path):
    p = tmp_path / "pp15.csv"
    raw_ppd.iloc[:, :15].to_csv(p, header=False, index=False)
    df, _ = filter_region(p, ["MERSEYSIDE"], chunk_rows=100)
    assert (df["record_status"] == "A").all()


def test_boe_params_format():
    params = boe.build_params(["IUDBEDR"], date(2018, 1, 1), date(2026, 10, 8))
    assert params["Datefrom"] == "01/Jan/2018"
    assert params["Dateto"] == "08/Oct/2026"
    assert params["SeriesCodes"] == "IUDBEDR"


def test_boe_parse_csv():
    text = "DATE,IUDBEDR,IUMBV34\n02 Jan 2024,5.25,\n31 Jan 2024,5.25,5.4\n"
    df = boe.parse_iadb_csv(text, {"IUDBEDR": "bank_rate", "IUMBV34": "mortgage_2y_fixed_75ltv"})
    assert len(df) == 3                                     # blank mortgage cell dropped
    assert set(df["series_name"]) == {"bank_rate", "mortgage_2y_fixed_75ltv"}
    assert df["date"].min() == pd.Timestamp("2024-01-02")


def test_outcode_lookup_ok_and_not_found(cfg, requests_mock):
    base = cfg["postcodes"]["base_url"]
    requests_mock.get(f"{base}/outcodes/L18", json={"result": {
        "latitude": 53.37, "longitude": -2.91, "admin_district": ["Liverpool"]}})
    requests_mock.get(f"{base}/outcodes/ZZ9", status_code=404, json={"error": "not found"})
    cfg["postcodes"]["pause_seconds"] = 0
    out = postcodes.extract_outcodes(cfg, ["L18", "ZZ9", None])
    df = pd.read_parquet(out).set_index("outcode")
    assert df.loc["L18", "admin_district"] == "Liverpool"
    assert df.loc["ZZ9", "lookup_status"] == "not_found"

    # second call uses the cache: no new requests
    calls = requests_mock.call_count
    postcodes.extract_outcodes(cfg, ["L18", "ZZ9"])
    assert requests_mock.call_count == calls


def test_boe_retries_when_html_returned(requests_mock):
    from nwhousing.http import make_session
    url = "https://example.test/iadb"
    requests_mock.get(url, [{"text": "<html>busy</html>"}, {"text": "DATE,IUDBEDR\n02 Jan 2024,5.25\n"}])
    text = boe.fetch_series_csv(url, {"SeriesCodes": "IUDBEDR"}, make_session(), attempts=3, wait=0)
    assert text.startswith("DATE")
    assert requests_mock.call_count == 2


def test_boe_gives_up_with_clear_error(requests_mock):
    import pytest
    from nwhousing.http import make_session
    url = "https://example.test/iadb"
    requests_mock.get(url, text="<html>blocked</html>")
    with pytest.raises(boe.BoEUnavailable):
        boe.fetch_series_csv(url, {"SeriesCodes": "IUDBEDR"}, make_session(), attempts=2, wait=0)
