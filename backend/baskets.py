"""Basket portfolios — load CSVs, compute daily return series."""
from __future__ import annotations

import csv
import os
from functools import lru_cache
from typing import Iterable

import numpy as np
import pandas as pd

from db import prices_for_tickers
from factors import load_factor_returns

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASKET_DIR = os.path.join(
    PROJECT_ROOT, "data", "input", "portfolios", "Baskets", "cap_weighted"
)


# Common acronyms in basket names that .title() would munge
_ACRONYMS = {
    "Ai": "AI", "Eu": "EU", "Us": "US", "Pc": "PC", "Pe": "PE",
    "Tpu": "TPU", "Hbm": "HBM", "Hpc": "HPC", "Uav": "UAV",
    "Glp": "GLP", "Oai": "OAI", "Saas": "SaaS", "Etf": "ETF",
    "Move": "MOVE",
}


def _pretty_name(filename: str) -> str:
    stem = os.path.splitext(filename)[0]
    pretty = stem.replace("_", " ").title()
    return " ".join(_ACRONYMS.get(w, w) for w in pretty.split())


def _read_basket_csv(path: str) -> pd.DataFrame:
    """Auto-detect delimiter and read ticker;shares;costdate."""
    with open(path, "r", encoding="utf-8-sig") as f:
        sample = f.read(2048)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;")
            sep = dialect.delimiter
        except csv.Error:
            sep = ","
        df = pd.read_csv(f, sep=sep)

    df.columns = [c.strip().lower() for c in df.columns]
    if "ticker" not in df or "shares" not in df:
        raise ValueError(f"{path}: missing ticker/shares columns")
    df["shares"] = pd.to_numeric(df["shares"], errors="coerce")
    df = df.dropna(subset=["ticker", "shares"])
    df["ticker"] = df["ticker"].astype(str).str.strip()
    return df


def _basket_returns(basket: pd.DataFrame, prices: pd.DataFrame) -> pd.Series:
    """Constant-share-weight portfolio daily returns.

    Value(t) = Σ shares_i × close_i,t. Then daily return = pct_change of value.
    Tickers without prices are dropped (weights renormalize implicitly).
    """
    if prices.empty:
        return pd.Series(dtype=float)

    wide = prices.pivot(index="date", columns="ticker", values="close").sort_index()
    # Aggregate dup ticker rows (a few baskets list the same name twice)
    shares = basket.groupby("ticker")["shares"].sum()
    shares = shares.reindex(wide.columns).fillna(0.0)

    value = wide.ffill().fillna(0.0).mul(shares, axis=1).sum(axis=1)
    value = value.replace(0.0, np.nan).dropna()
    if value.empty:
        return pd.Series(dtype=float)
    rets = value.pct_change().dropna()
    rets.index = pd.to_datetime(rets.index)
    return rets


@lru_cache(maxsize=1)
def load_all_basket_returns() -> dict:
    """Returns dict: {basket_key: {"name": str, "returns": pd.Series, "coverage": int}}.

    Anchors basket return panel to the same date window as the factor returns
    so the timeframe pills are consistent across charts.
    """
    factor_dates = load_factor_returns().index
    start = factor_dates.min().strftime("%Y-%m-%d")

    if not os.path.isdir(BASKET_DIR):
        return {}

    baskets = {}
    for fname in sorted(os.listdir(BASKET_DIR)):
        if not fname.endswith(".csv"):
            continue
        path = os.path.join(BASKET_DIR, fname)
        try:
            basket = _read_basket_csv(path)
        except Exception as e:
            print(f"[baskets] skip {fname}: {e}")
            continue
        if basket.empty:
            continue

        prices = prices_for_tickers(basket["ticker"].tolist(), start_date=start)
        rets = _basket_returns(basket, prices)
        if rets.empty:
            continue

        # Reindex onto factor dates so the alignment is exact
        rets = rets.reindex(factor_dates).dropna()

        key = os.path.splitext(fname)[0]
        baskets[key] = {
            "name": _pretty_name(fname),
            "returns": rets,
            "coverage": int(prices["ticker"].nunique()),
            "size": int(len(basket)),
        }
    return baskets


# Trading-day approximations for timeframe pills
TIMEFRAME_DAYS = {
    "1D": 1,
    "1W": 5,
    "1M": 21,
    "3M": 63,
    "6M": 126,
    "1Y": 252,
}


def basket_series(timeframe: str, keys: Iterable[str] | None = None) -> dict:
    if timeframe not in TIMEFRAME_DAYS:
        raise ValueError(f"Unknown timeframe {timeframe!r}")

    all_baskets = load_all_basket_returns()
    if keys is None:
        # Default: top 12 baskets by alphabetical key (frontend can override)
        keys = list(all_baskets.keys())[:12]
    else:
        keys = [k for k in keys if k in all_baskets]

    n = TIMEFRAME_DAYS[timeframe]
    rows: dict[str, dict[str, float]] = {}
    meta = []

    for key in keys:
        ret = all_baskets[key]["returns"].tail(n)
        if ret.empty:
            continue
        cum = (1.0 + ret).cumprod() - 1.0
        meta.append({"key": key, "name": all_baskets[key]["name"]})
        for date, v in cum.items():
            d = date.strftime("%Y-%m-%d")
            rows.setdefault(d, {"date": d})
            rows[d][key] = float(v)

    return {
        "timeframe": timeframe,
        "baskets": meta,
        "rows": [rows[d] for d in sorted(rows)],
    }


def list_baskets() -> list[dict]:
    return [
        {"key": k, "name": v["name"], "coverage": v["coverage"], "size": v["size"]}
        for k, v in load_all_basket_returns().items()
    ]
