"""Test isolation: temp DB + synthetic parquet cache when none exists."""
import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="pdt-test-"), "app.db")

import numpy as np
import pandas as pd

import data

INCEPTION = {
    "SPY": "1993-02-01", "VOO": "2010-09-09", "SPX": "1927-12-30",
    "AGG": "2003-09-29", "TLT": "2002-07-30", "GLD": "2004-11-18",
    "VTI": "2001-06-15", "VXUS": "2011-01-28", "QQQ": "1999-03-10",
    "NDX": "1985-10-01", "IEF": "2002-07-30", "VNQ": "2004-09-29",
    "BIL": "2007-05-30",
}


def pytest_configure(config):
    end = pd.Timestamp.today().normalize()
    for ticker, start in INCEPTION.items():
        cache_file = data.CACHE_DIR / f"{ticker}.parquet"
        if cache_file.exists():
            continue
        dates = pd.bdate_range(start=start, end=end)
        rng = np.random.default_rng(abs(hash(ticker)) % 2**32)
        daily = rng.normal(0.0003, 0.01, len(dates))
        prices = 100 * np.exp(np.cumsum(daily))
        pd.DataFrame({ticker: prices}, index=dates).to_parquet(cache_file)
