"""Load Barra factor returns and produce cumulative-return time series."""
from __future__ import annotations

import os
from functools import lru_cache

import numpy as np
import pandas as pd

from theme import STYLE_FACTORS, STYLE_DISPLAY_NAMES

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FACTOR_RETURNS_CSV = os.path.join(
    PROJECT_ROOT, "data", "model", "barra_factor_returns.csv"
)

# Trading-day approximations for timeframe pills
TIMEFRAME_DAYS = {
    "1D": 1,
    "1W": 5,
    "1M": 21,
    "3M": 63,
    "6M": 126,
    "1Y": 252,
}


@lru_cache(maxsize=1)
def load_factor_returns() -> pd.DataFrame:
    df = pd.read_csv(FACTOR_RETURNS_CSV, index_col=0, parse_dates=True)
    df = df.sort_index()
    return df


def style_factor_series(timeframe: str = "1Y") -> dict:
    """Return cumulative-return series for the 10 style factors over a timeframe.

    Cumulative compounding: (1+r).cumprod() - 1, re-anchored at start of window.
    """
    if timeframe not in TIMEFRAME_DAYS:
        raise ValueError(f"Unknown timeframe {timeframe!r}")

    df = load_factor_returns()
    cols = [c for c in STYLE_FACTORS if c in df.columns]
    sub = df[cols].tail(TIMEFRAME_DAYS[timeframe])

    cum = (1.0 + sub).cumprod() - 1.0
    cum.index.name = "date"
    cum = cum.reset_index()
    cum["date"] = cum["date"].dt.strftime("%Y-%m-%d")

    return {
        "timeframe": timeframe,
        "factors": [
            {"key": c, "name": STYLE_DISPLAY_NAMES[c]} for c in cols
        ],
        "rows": cum.to_dict(orient="records"),
    }
