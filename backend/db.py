"""SQLite helpers for market_data.db."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterable

import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(PROJECT_ROOT, "data", "db", "market_data.db")


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    try:
        yield c
    finally:
        c.close()


def prices_for_tickers(tickers: Iterable[str], start_date: str | None = None) -> pd.DataFrame:
    """Return long-format daily close prices for the given tickers.

    Columns: ticker, date (str), close. Rows with non-positive close dropped.
    """
    tickers = list(set(tickers))
    if not tickers:
        return pd.DataFrame(columns=["ticker", "date", "close"])

    placeholders = ",".join("?" for _ in tickers)
    sql = f"""
        SELECT ticker, date, close
        FROM daily_prices
        WHERE ticker IN ({placeholders})
          AND close > 0
    """
    params = list(tickers)
    if start_date:
        sql += " AND date >= ?"
        params.append(start_date)
    sql += " ORDER BY ticker, date"

    with conn() as c:
        return pd.read_sql_query(sql, c, params=params)


def stock_meta(tickers: Iterable[str]) -> pd.DataFrame:
    """Return ticker -> gic_sector / gic_group from stocks table.

    Picks one row per ticker (preferring rows with a non-null gic_sector).
    """
    tickers = list(set(tickers))
    if not tickers:
        return pd.DataFrame(columns=["ticker", "gic_sector", "gic_group"])

    placeholders = ",".join("?" for _ in tickers)
    sql = f"""
        SELECT ticker, gic_sector, gic_group
        FROM stocks
        WHERE ticker IN ({placeholders})
    """
    with conn() as c:
        df = pd.read_sql_query(sql, c, params=list(tickers))
    df = df.sort_values("gic_sector", na_position="last").drop_duplicates("ticker")
    return df.reset_index(drop=True)
