import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nwhousing.config import load_config  # noqa: E402
from nwhousing.extract.land_registry import PPD_COLUMNS  # noqa: E402


def ppd_row(tid, price=200000, date="2024-03-15 00:00", postcode="L18 1AB", ptype="S",
            new="N", dur="F", district="LIVERPOOL", county="MERSEYSIDE", cat="A", status="A"):
    return ["{" + tid + "}", str(price), date, postcode, ptype, new, dur, "12", "", "ALLERTON ROAD",
            "", "LIVERPOOL", district, county, cat, status]


@pytest.fixture
def raw_ppd():
    rows = [
        ppd_row("A1"),
        ppd_row("A2", price=95000, ptype="T", dur="F"),
        ppd_row("A3", price=150000, ptype="F", dur="L", new="Y", postcode=""),
        ppd_row("A4", price=6_500_000, ptype="D"),                      # price outlier
        ppd_row("A5", ptype="O", cat="B"),                               # non-standard
        ppd_row("A6", district="LEEDS", county="WEST YORKSHIRE"),        # outside region
    ]
    return pd.DataFrame(rows, columns=PPD_COLUMNS)


@pytest.fixture
def cfg(tmp_path):
    return load_config(data_dir=str(tmp_path / "data"))
