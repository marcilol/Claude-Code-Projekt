"""Period returns + z-scores for factors and baskets.

Z-score definition: standardize the latest daily return against the trailing
window's daily-return distribution.  z = (r_today - mean_window) / std_window.
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from baskets import load_all_basket_returns
from factors import load_factor_returns
from theme import STYLE_FACTORS, STYLE_DISPLAY_NAMES

ZScoreWindow = Literal[63, 126, 252, 504]
ZSCORE_WINDOWS: tuple[int, ...] = (63, 126, 252, 504)

PERIOD_DAYS = {
    "1D": 1,
    "5D": 5,
    "21D": 21,
}


def _period_return(series: pd.Series, n: int) -> float:
    """Compounded return over the last n trading days."""
    s = series.dropna()
    if len(s) < n:
        return float("nan")
    return float((1.0 + s.tail(n)).prod() - 1.0)


def _zscore_latest(series: pd.Series, window: int) -> float:
    s = series.dropna().tail(window + 1)
    if len(s) < max(20, window // 4):
        return float("nan")
    history = s.iloc[:-1]
    today = s.iloc[-1]
    sigma = history.std()
    if sigma == 0 or np.isnan(sigma):
        return float("nan")
    return float((today - history.mean()) / sigma)


def _sparkline(series: pd.Series, n: int = 21) -> list[float]:
    s = series.dropna().tail(n)
    if s.empty:
        return []
    cum = (1.0 + s).cumprod() - 1.0
    return [float(v) for v in cum.values]


def factor_table(window: int = 252) -> list[dict]:
    df = load_factor_returns()
    out = []
    for f in STYLE_FACTORS:
        if f not in df.columns:
            continue
        s = df[f]
        out.append({
            "key": f,
            "name": STYLE_DISPLAY_NAMES[f],
            "kind": "factor",
            "ret_1d": _period_return(s, 1),
            "ret_5d": _period_return(s, 5),
            "ret_21d": _period_return(s, 21),
            "zscore": _zscore_latest(s, window),
            "sparkline": _sparkline(s),
        })
    return out


def basket_table(window: int = 252) -> list[dict]:
    baskets = load_all_basket_returns()
    out = []
    for key, info in baskets.items():
        s = info["returns"]
        out.append({
            "key": key,
            "name": info["name"],
            "kind": "basket",
            "ret_1d": _period_return(s, 1),
            "ret_5d": _period_return(s, 5),
            "ret_21d": _period_return(s, 21),
            "zscore": _zscore_latest(s, window),
            "sparkline": _sparkline(s),
        })
    return out


def combined_table(window: int = 252) -> dict:
    if window not in ZSCORE_WINDOWS:
        raise ValueError(f"window must be one of {ZSCORE_WINDOWS}, got {window}")
    return {
        "window": window,
        "factors": factor_table(window),
        "baskets": basket_table(window),
    }


def quadrant_data(kind: Literal["factor", "basket"] = "factor") -> dict:
    """5D return (x) vs 21D return (y), for the rotation-quadrant scatter."""
    if kind == "factor":
        rows = factor_table(window=252)
    elif kind == "basket":
        rows = basket_table(window=252)
    else:
        raise ValueError("kind must be 'factor' or 'basket'")

    points = []
    for r in rows:
        x = r["ret_5d"]
        y = r["ret_21d"]
        if not (np.isfinite(x) and np.isfinite(y)):
            continue
        if x >= 0 and y >= 0:
            quadrant = "leaders"
        elif x < 0 and y >= 0:
            quadrant = "fading"
        elif x >= 0 and y < 0:
            quadrant = "recovering"
        else:
            quadrant = "laggards"
        points.append({
            "key": r["key"],
            "name": r["name"],
            "x": x,
            "y": y,
            "quadrant": quadrant,
        })
    return {"kind": kind, "points": points}
