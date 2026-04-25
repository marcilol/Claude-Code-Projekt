# -*- coding: utf-8 -*-
"""
SQLite database manager for market data.

Provides persistent, incremental storage for prices, fundamentals,
and analyst estimates across multiple stock universes.

Usage:
    from data_manager import MarketDB
    db = MarketDB()
    db.create_tables()
    db.add_universe('russell3000', tickers_sectors, 'USD', 'US')
    prices = db.get_daily_prices(['AAPL', 'MSFT'], '2024-01-01', '2026-04-14')
"""

import sqlite3
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


DB_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'db')
DEFAULT_DB_PATH = os.path.join(DB_DIR, 'market_data.db')


class MarketDB:
    """SQLite database manager for market data."""

    def __init__(self, db_path=None):
        if db_path is None:
            db_path = DEFAULT_DB_PATH
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._conn = None

    @property
    def conn(self):
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ------------------------------------------------------------------ #
    #  Schema
    # ------------------------------------------------------------------ #

    def create_tables(self):
        """Create all tables and indexes if they don't exist."""
        c = self.conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS universes (
                id          INTEGER PRIMARY KEY,
                name        TEXT UNIQUE NOT NULL,
                description TEXT,
                currency    TEXT DEFAULT 'USD',
                exchange    TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS stocks (
                ticker       TEXT NOT NULL,
                universe_id  INTEGER NOT NULL REFERENCES universes(id),
                sector       TEXT,
                gic_sector   TEXT,
                gic_group    TEXT,
                added_date   TEXT,
                removed_date TEXT,
                PRIMARY KEY (ticker, universe_id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS daily_prices (
                ticker      TEXT NOT NULL,
                date        TEXT NOT NULL,
                open        REAL,
                high        REAL,
                low         REAL,
                close       REAL,
                volume      REAL,
                shares_out  REAL,
                source      TEXT DEFAULT 'yfinance',
                PRIMARY KEY (ticker, date)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS fundamentals_quarterly (
                ticker           TEXT NOT NULL,
                report_date      TEXT NOT NULL,
                book_equity      REAL,
                net_income       REAL,
                depreciation     REAL,
                revenue          REAL,
                long_term_debt   REAL,
                total_debt       REAL,
                total_assets     REAL,
                preferred_equity REAL,
                source           TEXT DEFAULT 'yfinance',
                PRIMARY KEY (ticker, report_date)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS fundamentals_annual (
                ticker      TEXT NOT NULL,
                report_date TEXT NOT NULL,
                eps         REAL,
                revenue     REAL,
                source      TEXT DEFAULT 'yfinance',
                PRIMARY KEY (ticker, report_date)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS analyst_estimates (
                ticker       TEXT NOT NULL,
                as_of_date   TEXT NOT NULL,
                forward_eps  REAL,
                growth_ltm   REAL,
                growth_stm   REAL,
                source       TEXT,
                PRIMARY KEY (ticker, as_of_date)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS risk_free_rate (
                date     TEXT PRIMARY KEY,
                rf_daily REAL NOT NULL,
                source   TEXT DEFAULT 'yfinance'
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS fetch_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker     TEXT,
                data_type  TEXT NOT NULL,
                source     TEXT NOT NULL,
                last_date  TEXT,
                fetched_at TEXT NOT NULL,
                status     TEXT DEFAULT 'ok',
                rows_added INTEGER DEFAULT 0
            )
        """)

        # Indexes
        for stmt in [
            "CREATE INDEX IF NOT EXISTS idx_prices_date ON daily_prices(date)",
            "CREATE INDEX IF NOT EXISTS idx_prices_ticker ON daily_prices(ticker)",
            "CREATE INDEX IF NOT EXISTS idx_fund_q_ticker ON fundamentals_quarterly(ticker)",
            "CREATE INDEX IF NOT EXISTS idx_fund_a_ticker ON fundamentals_annual(ticker)",
            "CREATE INDEX IF NOT EXISTS idx_estimates_ticker ON analyst_estimates(ticker)",
            "CREATE INDEX IF NOT EXISTS idx_fetch_log_ticker ON fetch_log(ticker, data_type)",
        ]:
            c.execute(stmt)

        # Schema migrations for existing databases
        try:
            c.execute("ALTER TABLE stocks ADD COLUMN gic_sector TEXT")
        except Exception:
            pass  # column already exists
        try:
            c.execute("ALTER TABLE stocks ADD COLUMN gic_group TEXT")
        except Exception:
            pass  # column already exists

        self.conn.commit()

    # ------------------------------------------------------------------ #
    #  Universe management
    # ------------------------------------------------------------------ #

    def add_universe(self, name, tickers_sectors, currency='USD', exchange=None,
                     description=None):
        """
        Add or update a universe.

        Parameters
        ----------
        name : str
            Universe identifier (e.g. 'russell3000').
        tickers_sectors : dict
            {ticker: sector} mapping.
        currency : str
        exchange : str
        description : str
        """
        c = self.conn.cursor()
        c.execute("""
            INSERT INTO universes (name, description, currency, exchange)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description=excluded.description,
                currency=excluded.currency,
                exchange=excluded.exchange
        """, (name, description, currency, exchange))

        uid = c.execute("SELECT id FROM universes WHERE name=?", (name,)).fetchone()[0]
        today = datetime.now().strftime('%Y-%m-%d')

        for ticker, sector in tickers_sectors.items():
            c.execute("""
                INSERT INTO stocks (ticker, universe_id, sector, added_date)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(ticker, universe_id) DO UPDATE SET
                    sector=excluded.sector
            """, (ticker, uid, sector, today))

        self.conn.commit()
        return uid

    def update_stock_gics(self, ticker, universe_name, gic_sector, gic_group):
        """Update GICS classification for a stock."""
        self.conn.execute("""
            UPDATE stocks SET gic_sector=?, gic_group=?
            WHERE ticker=? AND universe_id=(
                SELECT id FROM universes WHERE name=?
            )
        """, (gic_sector, gic_group, ticker, universe_name))
        self.conn.commit()

    def get_universe_tickers(self, universe_name, include_removed=False):
        """Return list of tickers in a universe as (ticker, sector, gic_group, gic_sector).

        If include_removed=True, also returns tickers that were removed from the
        universe (for survivorship-bias-free factor model estimation).
        """
        where = "WHERE u.name = ?" if include_removed else "WHERE u.name = ? AND s.removed_date IS NULL"
        rows = self.conn.execute(f"""
            SELECT s.ticker, s.sector, s.gic_group, s.gic_sector
            FROM stocks s
            JOIN universes u ON s.universe_id = u.id
            {where}
            ORDER BY s.ticker
        """, (universe_name,)).fetchall()
        return [(r[0], r[1], r[2], r[3]) for r in rows]

    def get_universe_exchange(self, universe_name):
        """Return the exchange code for a universe (e.g., 'US', 'LSE')."""
        row = self.conn.execute(
            "SELECT exchange FROM universes WHERE name=?", (universe_name,)
        ).fetchone()
        return row[0] if row else 'US'

    def list_universes(self):
        """Return DataFrame of universes with stock counts."""
        df = pd.read_sql_query("""
            SELECT u.name, u.currency, u.exchange, u.description,
                   COUNT(s.ticker) as n_stocks
            FROM universes u
            LEFT JOIN stocks s ON s.universe_id = u.id AND s.removed_date IS NULL
            GROUP BY u.id
            ORDER BY u.name
        """, self.conn)
        return df

    # ------------------------------------------------------------------ #
    #  Data queries
    # ------------------------------------------------------------------ #

    def get_daily_prices(self, tickers, start=None, end=None):
        """
        Return daily OHLCV + shares_out for given tickers and date range.

        Returns DataFrame with columns:
            ticker, date, open, high, low, close, volume, shares_out
        """
        placeholders = ','.join('?' * len(tickers))
        query = f"""
            SELECT ticker, date, open, high, low, close, volume, shares_out
            FROM daily_prices
            WHERE ticker IN ({placeholders})
        """
        params = list(tickers)
        if start:
            query += " AND date >= ?"
            params.append(start)
        if end:
            query += " AND date <= ?"
            params.append(end)
        query += " ORDER BY ticker, date"

        df = pd.read_sql_query(query, self.conn, params=params)
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
        return df

    def get_fundamentals_quarterly(self, tickers, as_of_date=None):
        """
        Return quarterly fundamentals for given tickers.
        If as_of_date given, only returns reports on or before that date.
        """
        placeholders = ','.join('?' * len(tickers))
        query = f"""
            SELECT ticker, report_date, book_equity, net_income, depreciation,
                   revenue, long_term_debt, total_debt, total_assets, preferred_equity
            FROM fundamentals_quarterly
            WHERE ticker IN ({placeholders})
        """
        params = list(tickers)
        if as_of_date:
            query += " AND report_date <= ?"
            params.append(as_of_date)
        query += " ORDER BY ticker, report_date"
        return pd.read_sql_query(query, self.conn, params=params)

    def get_fundamentals_annual(self, tickers):
        """Return annual EPS and revenue for given tickers."""
        placeholders = ','.join('?' * len(tickers))
        query = f"""
            SELECT ticker, report_date, eps, revenue
            FROM fundamentals_annual
            WHERE ticker IN ({placeholders})
            ORDER BY ticker, report_date
        """.format(placeholders)
        return pd.read_sql_query(query, self.conn, params=list(tickers))

    def get_risk_free_rate(self, start=None, end=None):
        """Return risk-free rate series."""
        query = "SELECT date, rf_daily FROM risk_free_rate WHERE 1=1"
        params = []
        if start:
            query += " AND date >= ?"
            params.append(start)
        if end:
            query += " AND date <= ?"
            params.append(end)
        query += " ORDER BY date"
        df = pd.read_sql_query(query, self.conn, params=params)
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')['rf_daily']
        return df

    def get_analyst_estimates(self, tickers, as_of_date=None):
        """Return analyst estimates (forward EPS, growth forecasts)."""
        placeholders = ','.join('?' * len(tickers))
        query = f"""
            SELECT ticker, as_of_date, forward_eps, growth_ltm, growth_stm, source
            FROM analyst_estimates
            WHERE ticker IN ({placeholders})
        """
        params = list(tickers)
        if as_of_date:
            query += " AND as_of_date <= ?"
            params.append(as_of_date)
        query += " ORDER BY ticker, as_of_date"
        return pd.read_sql_query(query, self.conn, params=params)

    # ------------------------------------------------------------------ #
    #  Update / upsert
    # ------------------------------------------------------------------ #

    def get_last_price_date(self, ticker):
        """Return the latest date we have prices for, or None."""
        row = self.conn.execute(
            "SELECT MAX(date) FROM daily_prices WHERE ticker=?", (ticker,)
        ).fetchone()
        return row[0] if row and row[0] else None

    def needs_update(self, ticker, data_type, max_age_days=1):
        """Check if data needs refreshing based on fetch_log."""
        row = self.conn.execute("""
            SELECT fetched_at FROM fetch_log
            WHERE ticker=? AND data_type=? AND status='ok'
            ORDER BY fetched_at DESC LIMIT 1
        """, (ticker, data_type)).fetchone()
        if not row:
            return True
        last_fetch = datetime.fromisoformat(row[0])
        return (datetime.now() - last_fetch) > timedelta(days=max_age_days)

    def upsert_prices(self, df):
        """
        Insert or replace daily price rows.

        Expects DataFrame with columns:
            ticker, date, open, high, low, close, volume, shares_out
        Optional: source
        """
        if df.empty:
            return 0
        c = self.conn.cursor()
        rows = 0
        source = df['source'].iloc[0] if 'source' in df.columns else 'yfinance'
        for _, row in df.iterrows():
            date_str = (row['date'].strftime('%Y-%m-%d')
                        if isinstance(row['date'], (datetime, pd.Timestamp))
                        else str(row['date']))
            c.execute("""
                INSERT OR REPLACE INTO daily_prices
                    (ticker, date, open, high, low, close, volume, shares_out, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row['ticker'], date_str,
                _safe_float(row.get('open')), _safe_float(row.get('high')),
                _safe_float(row.get('low')), _safe_float(row.get('close')),
                _safe_float(row.get('volume')), _safe_float(row.get('shares_out')),
                source
            ))
            rows += 1
        self.conn.commit()
        return rows

    def upsert_fundamentals_q(self, df):
        """Insert or replace quarterly fundamental rows."""
        if df.empty:
            return 0
        c = self.conn.cursor()
        rows = 0
        source = df['source'].iloc[0] if 'source' in df.columns else 'yfinance'
        for _, row in df.iterrows():
            date_str = (row['report_date'].strftime('%Y-%m-%d')
                        if isinstance(row['report_date'], (datetime, pd.Timestamp))
                        else str(row['report_date']))
            c.execute("""
                INSERT OR REPLACE INTO fundamentals_quarterly
                    (ticker, report_date, book_equity, net_income, depreciation,
                     revenue, long_term_debt, total_debt, total_assets,
                     preferred_equity, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row['ticker'], date_str,
                _safe_float(row.get('book_equity')),
                _safe_float(row.get('net_income')),
                _safe_float(row.get('depreciation')),
                _safe_float(row.get('revenue')),
                _safe_float(row.get('long_term_debt')),
                _safe_float(row.get('total_debt')),
                _safe_float(row.get('total_assets')),
                _safe_float(row.get('preferred_equity')),
                source
            ))
            rows += 1
        self.conn.commit()
        return rows

    def upsert_fundamentals_a(self, df):
        """Insert or replace annual fundamental rows."""
        if df.empty:
            return 0
        c = self.conn.cursor()
        rows = 0
        source = df['source'].iloc[0] if 'source' in df.columns else 'yfinance'
        for _, row in df.iterrows():
            date_str = (row['report_date'].strftime('%Y-%m-%d')
                        if isinstance(row['report_date'], (datetime, pd.Timestamp))
                        else str(row['report_date']))
            c.execute("""
                INSERT OR REPLACE INTO fundamentals_annual
                    (ticker, report_date, eps, revenue, source)
                VALUES (?, ?, ?, ?, ?)
            """, (
                row['ticker'], date_str,
                _safe_float(row.get('eps')),
                _safe_float(row.get('revenue')),
                source
            ))
            rows += 1
        self.conn.commit()
        return rows

    def upsert_risk_free_rate(self, df, source='eodhd'):
        """
        Insert or replace risk-free rate rows.
        Expects DataFrame/Series with date index and rf_daily values.
        """
        if isinstance(df, pd.Series):
            df = df.reset_index()
            df.columns = ['date', 'rf_daily']
        if df.empty:
            return 0
        c = self.conn.cursor()
        rows = 0
        for _, row in df.iterrows():
            date_str = (row['date'].strftime('%Y-%m-%d')
                        if isinstance(row['date'], (datetime, pd.Timestamp))
                        else str(row['date']))
            c.execute("""
                INSERT OR REPLACE INTO risk_free_rate (date, rf_daily, source)
                VALUES (?, ?, ?)
            """, (date_str, float(row['rf_daily']), source))
            rows += 1
        self.conn.commit()
        return rows

    def upsert_estimates(self, df):
        """Insert or replace analyst estimate rows."""
        if df.empty:
            return 0
        c = self.conn.cursor()
        rows = 0
        for _, row in df.iterrows():
            date_str = (row['as_of_date'].strftime('%Y-%m-%d')
                        if isinstance(row['as_of_date'], (datetime, pd.Timestamp))
                        else str(row['as_of_date']))
            c.execute("""
                INSERT OR REPLACE INTO analyst_estimates
                    (ticker, as_of_date, forward_eps, growth_ltm, growth_stm, source)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                row['ticker'], date_str,
                _safe_float(row.get('forward_eps')),
                _safe_float(row.get('growth_ltm')),
                _safe_float(row.get('growth_stm')),
                row.get('source', 'unknown')
            ))
            rows += 1
        self.conn.commit()
        return rows

    def log_fetch(self, ticker, data_type, source, last_date, rows_added,
                  status='ok'):
        """Record a fetch operation."""
        self.conn.execute("""
            INSERT INTO fetch_log (ticker, data_type, source, last_date,
                                   fetched_at, status, rows_added)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (ticker, data_type, source, last_date,
              datetime.now().isoformat(), status, rows_added))
        self.conn.commit()

    # ------------------------------------------------------------------ #
    #  Stats
    # ------------------------------------------------------------------ #

    def coverage_report(self):
        """Return a summary of what's in the database."""
        tables = {
            'daily_prices': 'ticker',
            'fundamentals_quarterly': 'ticker',
            'fundamentals_annual': 'ticker',
            'analyst_estimates': 'ticker',
            'risk_free_rate': None,
        }
        rows = []
        for table, ticker_col in tables.items():
            try:
                total = self.conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                if ticker_col:
                    n_tickers = self.conn.execute(
                        f"SELECT COUNT(DISTINCT {ticker_col}) FROM {table}"
                    ).fetchone()[0]
                    date_col = 'date' if table == 'daily_prices' else (
                        'report_date' if 'fundamentals' in table else 'as_of_date')
                    date_range = self.conn.execute(
                        f"SELECT MIN({date_col}), MAX({date_col}) FROM {table}"
                    ).fetchone()
                else:
                    n_tickers = None
                    date_range = self.conn.execute(
                        "SELECT MIN(date), MAX(date) FROM risk_free_rate"
                    ).fetchone()
                rows.append({
                    'table': table,
                    'total_rows': total,
                    'n_tickers': n_tickers,
                    'min_date': date_range[0],
                    'max_date': date_range[1],
                })
            except Exception:
                rows.append({'table': table, 'total_rows': 0})

        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ #
    #  Bulk loading helpers (for pickle migration)
    # ------------------------------------------------------------------ #

    def bulk_load_prices(self, records):
        """
        Fast bulk insert for price data (used during migration).

        Parameters
        ----------
        records : list of tuples
            (ticker, date, open, high, low, close, volume, shares_out, source)
        """
        c = self.conn.cursor()
        c.executemany("""
            INSERT OR REPLACE INTO daily_prices
                (ticker, date, open, high, low, close, volume, shares_out, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, records)
        self.conn.commit()

    def bulk_load_fundamentals_q(self, records):
        """Fast bulk insert for quarterly fundamentals."""
        c = self.conn.cursor()
        c.executemany("""
            INSERT OR REPLACE INTO fundamentals_quarterly
                (ticker, report_date, book_equity, net_income, depreciation,
                 revenue, long_term_debt, total_debt, total_assets,
                 preferred_equity, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, records)
        self.conn.commit()

    def bulk_load_fundamentals_a(self, records):
        """Fast bulk insert for annual fundamentals."""
        c = self.conn.cursor()
        c.executemany("""
            INSERT OR REPLACE INTO fundamentals_annual
                (ticker, report_date, eps, revenue, source)
            VALUES (?, ?, ?, ?, ?)
        """, records)
        self.conn.commit()

    def bulk_load_risk_free(self, records):
        """Fast bulk insert for risk-free rate."""
        c = self.conn.cursor()
        c.executemany("""
            INSERT OR REPLACE INTO risk_free_rate (date, rf_daily, source)
            VALUES (?, ?, ?)
        """, records)
        self.conn.commit()


def _safe_float(val):
    """Convert to float, returning None for NaN/None."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) else f
    except (ValueError, TypeError):
        return None
