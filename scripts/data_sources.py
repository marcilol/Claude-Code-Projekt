# -*- coding: utf-8 -*-
"""
Pluggable data source adapters for market data.

Each adapter implements a common interface for fetching prices,
fundamentals, and analyst estimates. Only YFinanceSource is fully
implemented (free). EODHD and FMP are stubs for future paid API support.

Usage:
    from data_sources import YFinanceSource
    src = YFinanceSource()
    prices = src.fetch_daily_prices(['AAPL'], '2024-01-01', '2026-04-14')
"""

import pandas as pd
import numpy as np
import os
from abc import ABC, abstractmethod
from datetime import datetime


class DataSource(ABC):
    """Abstract interface for market data providers."""

    name = 'abstract'

    @abstractmethod
    def fetch_daily_prices(self, tickers, start, end, progress_fn=None):
        """
        Fetch daily OHLCV + shares outstanding.

        Parameters
        ----------
        tickers : list of str
        start : str (YYYY-MM-DD)
        end : str (YYYY-MM-DD)
        progress_fn : callable(ticker, i, total) or None

        Returns
        -------
        pd.DataFrame with columns:
            ticker, date, open, high, low, close, volume, shares_out, source
        """
        ...

    @abstractmethod
    def fetch_fundamentals_quarterly(self, tickers, progress_fn=None):
        """
        Fetch quarterly balance sheet + income statement.

        Returns DataFrame with columns:
            ticker, report_date, book_equity, net_income, depreciation,
            revenue, long_term_debt, total_debt, total_assets,
            preferred_equity, source
        """
        ...

    @abstractmethod
    def fetch_fundamentals_annual(self, tickers, progress_fn=None):
        """
        Fetch annual EPS + revenue (for growth slopes).

        Returns DataFrame with columns:
            ticker, report_date, eps, revenue, source
        """
        ...

    def fetch_analyst_estimates(self, tickers, progress_fn=None):
        """
        Fetch analyst estimates (forward EPS, growth forecasts).
        Optional — only paid APIs provide this.

        Returns DataFrame with columns:
            ticker, as_of_date, forward_eps, growth_ltm, growth_stm, source
        """
        return pd.DataFrame()

    def fetch_risk_free_rate(self, start, end):
        """
        Fetch risk-free rate (13-week T-bill).

        Returns pd.Series with DatetimeIndex and daily rf values.
        """
        return pd.Series(dtype=float)


class YFinanceSource(DataSource):
    """Free data source via Yahoo Finance. Covers global markets."""

    name = 'yfinance'

    def __init__(self, delay=0.5, exchange=None):
        self.delay = delay

    def fetch_daily_prices(self, tickers, start, end, progress_fn=None):
        import yfinance as yf
        import time

        all_rows = []
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            if progress_fn:
                progress_fn(ticker, i, total)

            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(start=start, end=end)
                if hist.empty:
                    continue

                shares_out = stock.info.get('sharesOutstanding', np.nan)
                hist.index = hist.index.tz_localize(None) if hist.index.tzinfo else hist.index

                for date, row in hist.iterrows():
                    all_rows.append({
                        'ticker': ticker,
                        'date': date,
                        'open': row.get('Open'),
                        'high': row.get('High'),
                        'low': row.get('Low'),
                        'close': row.get('Close'),
                        'volume': row.get('Volume'),
                        'shares_out': shares_out,
                        'source': 'yfinance',
                    })
            except Exception as e:
                if progress_fn:
                    progress_fn(ticker, i, total, error=str(e))
                continue

            if (i + 1) % 10 == 0:
                time.sleep(self.delay)

        return pd.DataFrame(all_rows) if all_rows else pd.DataFrame(
            columns=['ticker', 'date', 'open', 'high', 'low', 'close',
                     'volume', 'shares_out', 'source']
        )

    def fetch_fundamentals_quarterly(self, tickers, progress_fn=None):
        import yfinance as yf
        import time

        all_rows = []
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            if progress_fn:
                progress_fn(ticker, i, total)

            try:
                stock = yf.Ticker(ticker)

                # Balance sheet
                bs = stock.quarterly_balance_sheet
                inc = stock.quarterly_income_stmt

                # Collect all report dates
                dates = set()
                if bs is not None and not bs.empty:
                    dates.update(bs.columns)
                if inc is not None and not inc.empty:
                    dates.update(inc.columns)

                for report_date in dates:
                    row = {'ticker': ticker, 'report_date': report_date, 'source': 'yfinance'}

                    if bs is not None and not bs.empty and report_date in bs.columns:
                        col = bs[report_date]
                        row['book_equity'] = _get_item(col, [
                            'Stockholders Equity', 'Total Stockholders Equity',
                            'Total Equity Gross Minority Interest', 'Common Stock Equity'])
                        row['long_term_debt'] = _get_item(col, [
                            'Long Term Debt', 'Long Term Debt And Capital Lease Obligation'])
                        row['total_debt'] = _get_item(col, ['Total Debt'])
                        row['total_assets'] = _get_item(col, ['Total Assets'])
                        row['preferred_equity'] = _get_item(col, [
                            'Preferred Stock', 'Preferred Stock Equity'])

                        # Fallback: total_debt = current_debt + long_term_debt
                        if pd.isna(row.get('total_debt')):
                            cd = _get_item(col, ['Current Debt',
                                                  'Current Debt And Capital Lease Obligation'])
                            ltd = row.get('long_term_debt')
                            if pd.notna(cd) and pd.notna(ltd):
                                row['total_debt'] = cd + ltd

                    if inc is not None and not inc.empty and report_date in inc.columns:
                        col = inc[report_date]
                        row['net_income'] = _get_item(col, [
                            'Net Income', 'Net Income Common Stockholders'])
                        row['depreciation'] = _get_item(col, [
                            'Depreciation And Amortization In Income Statement',
                            'Depreciation And Amortization', 'Reconciled Depreciation'])
                        row['revenue'] = _get_item(col, ['Total Revenue', 'Operating Revenue'])

                    all_rows.append(row)

            except Exception:
                continue

            if (i + 1) % 10 == 0:
                time.sleep(self.delay)

        return pd.DataFrame(all_rows) if all_rows else pd.DataFrame(
            columns=['ticker', 'report_date', 'book_equity', 'net_income',
                     'depreciation', 'revenue', 'long_term_debt', 'total_debt',
                     'total_assets', 'preferred_equity', 'source']
        )

    def fetch_fundamentals_annual(self, tickers, progress_fn=None):
        import yfinance as yf
        import time

        all_rows = []
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            if progress_fn:
                progress_fn(ticker, i, total)

            try:
                stock = yf.Ticker(ticker)
                ann_inc = stock.income_stmt
                if ann_inc is None or ann_inc.empty:
                    continue

                for report_date in ann_inc.columns:
                    col = ann_inc[report_date]
                    eps = _get_item(col, ['Basic EPS', 'Diluted EPS'])
                    rev = _get_item(col, ['Total Revenue', 'Operating Revenue'])
                    all_rows.append({
                        'ticker': ticker,
                        'report_date': report_date,
                        'eps': eps,
                        'revenue': rev,
                        'source': 'yfinance',
                    })

            except Exception:
                continue

            if (i + 1) % 10 == 0:
                time.sleep(self.delay)

        return pd.DataFrame(all_rows) if all_rows else pd.DataFrame(
            columns=['ticker', 'report_date', 'eps', 'revenue', 'source']
        )

    def fetch_risk_free_rate(self, start, end):
        import yfinance as yf

        try:
            irx = yf.Ticker('^IRX')
            hist = irx.history(start=start, end=end)
            if len(hist) > 0:
                hist.index = (hist.index.tz_localize(None)
                              if hist.index.tzinfo else hist.index)
                rf = hist['Close'] / 100 / 252  # annualized % -> daily decimal
                rf.name = 'rf_daily'
                return rf
        except Exception:
            pass
        return pd.Series(dtype=float, name='rf_daily')


class EODHDSource(DataSource):
    """
    EODHD.com data source.

    Provides global coverage, faster bulk downloads, and analyst estimates
    (forward EPS, growth forecasts) that yfinance can't provide.

    Set EODHD_API_KEY in .env or environment.

    API docs: https://eodhd.com/financial-apis/
    """

    name = 'eodhd'
    BASE_URL = 'https://eodhd.com/api'

    def __init__(self, api_key=None, exchange='US'):
        # Try .env file first
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

        self.api_key = api_key or os.environ.get('EODHD_API_KEY')
        if not self.api_key:
            raise ValueError(
                "EODHD API key required. Set EODHD_API_KEY in .env file "
                "or environment. Subscribe at https://eodhd.com"
            )
        self.exchange = exchange

    def _get(self, endpoint, params=None):
        """Make authenticated GET request."""
        import requests
        if params is None:
            params = {}
        params['api_token'] = self.api_key
        params['fmt'] = 'json'
        url = f"{self.BASE_URL}/{endpoint}"
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _ticker_symbol(self, ticker):
        """Convert ticker to EODHD format: AAPL -> AAPL.US"""
        if '.' in ticker:
            return ticker  # already has exchange suffix
        return f"{ticker}.{self.exchange}"

    def fetch_daily_prices(self, tickers, start, end, progress_fn=None):
        """
        Fetch daily OHLCV + shares_out. Uses two endpoints per ticker:
        /eod for prices, /fundamentals?filter=SharesStats for shares outstanding.
        Shares_out is a single snapshot (today's value) applied to every row.
        """
        all_rows = []
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            if progress_fn:
                progress_fn(ticker, i, total)

            try:
                sym = self._ticker_symbol(ticker)
                # Prices first — skip SharesStats if no price data exists
                data = self._get(f"eod/{sym}", {'from': start, 'to': end})
                if not data:
                    continue

                # Shares outstanding only for tickers with price data
                try:
                    shares_data = self._get(f"fundamentals/{sym}", {'filter': 'SharesStats'})
                    shares_out = _safe_num(shares_data.get('SharesOutstanding')) if shares_data else np.nan
                except Exception:
                    shares_out = np.nan

                for row in data:
                    all_rows.append({
                        'ticker': ticker,
                        'date': pd.Timestamp(row['date']),
                        'open': row.get('open'),
                        'high': row.get('high'),
                        'low': row.get('low'),
                        'close': row.get('adjusted_close', row.get('close')),
                        'volume': row.get('volume'),
                        'shares_out': shares_out,
                        'source': 'eodhd',
                    })
            except Exception as e:
                if progress_fn:
                    progress_fn(ticker, i, total, error=str(e))
                continue

        return pd.DataFrame(all_rows) if all_rows else pd.DataFrame(
            columns=['ticker', 'date', 'open', 'high', 'low', 'close',
                     'volume', 'shares_out', 'source']
        )

    def fetch_bulk_eod(self, date=None):
        """
        Fetch all tickers on the exchange for a single date.
        100 API calls per request. Returns DataFrame.
        """
        params = {}
        if date:
            params['date'] = date
        data = self._get(f"eod-bulk-last-day/{self.exchange}", params)
        if not data:
            return pd.DataFrame()

        rows = []
        for row in data:
            rows.append({
                'ticker': row.get('code', ''),
                'date': pd.Timestamp(row['date']),
                'open': row.get('open'),
                'high': row.get('high'),
                'low': row.get('low'),
                'close': row.get('adjusted_close', row.get('close')),
                'volume': row.get('volume'),
                'shares_out': np.nan,
                'source': 'eodhd',
            })
        return pd.DataFrame(rows)

    def fetch_fundamentals_quarterly(self, tickers, progress_fn=None):
        """
        Fetch quarterly balance sheet + income statement.
        10 API calls per ticker.
        """
        all_rows = []
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            if progress_fn:
                progress_fn(ticker, i, total)

            try:
                data = self._get(f"fundamentals/{self._ticker_symbol(ticker)}", {
                    'filter': 'Financials::Balance_Sheet::quarterly,Financials::Income_Statement::quarterly,SharesStats',
                })
                if not data:
                    continue

                # Parse balance sheet
                bs_data = (data.get('Financials::Balance_Sheet::quarterly') or
                           data.get('Financials', {}).get('Balance_Sheet', {}).get('quarterly', {}))
                inc_data = (data.get('Financials::Income_Statement::quarterly') or
                            data.get('Financials', {}).get('Income_Statement', {}).get('quarterly', {}))
                shares_stats = data.get('SharesStats', {})
                shares_out = _safe_num(shares_stats.get('SharesOutstanding'))

                # Collect all report dates
                all_dates = set()
                if isinstance(bs_data, dict):
                    all_dates.update(bs_data.keys())
                if isinstance(inc_data, dict):
                    all_dates.update(inc_data.keys())

                for report_date in all_dates:
                    row = {
                        'ticker': ticker,
                        'report_date': report_date,
                        'source': 'eodhd',
                    }

                    bs = bs_data.get(report_date, {}) if isinstance(bs_data, dict) else {}
                    inc = inc_data.get(report_date, {}) if isinstance(inc_data, dict) else {}

                    row['book_equity'] = _safe_num(bs.get('totalStockholderEquity'))
                    row['long_term_debt'] = _safe_num(bs.get('longTermDebt') or bs.get('longTermDebtTotal'))
                    row['total_debt'] = _safe_num(bs.get('shortLongTermDebtTotal'))
                    row['total_assets'] = _safe_num(bs.get('totalAssets'))
                    row['preferred_equity'] = _safe_num(bs.get('preferredStockTotalEquity'))

                    row['net_income'] = _safe_num(inc.get('netIncome'))
                    row['depreciation'] = _safe_num(
                        inc.get('depreciationAndAmortization') or
                        inc.get('reconciledDepreciation'))
                    row['revenue'] = _safe_num(inc.get('totalRevenue'))

                    # Store shares_out from SharesStats (latest snapshot)
                    row['shares_out'] = shares_out

                    all_rows.append(row)

            except Exception as e:
                if progress_fn:
                    progress_fn(ticker, i, total, error=str(e))
                continue

        return pd.DataFrame(all_rows) if all_rows else pd.DataFrame(
            columns=['ticker', 'report_date', 'book_equity', 'net_income',
                     'depreciation', 'revenue', 'long_term_debt', 'total_debt',
                     'total_assets', 'preferred_equity', 'source']
        )

    def fetch_fundamentals_annual(self, tickers, progress_fn=None):
        """
        Fetch annual EPS + revenue. 10 API calls per ticker.
        Uses Earnings::Annual for EPS and Income_Statement::yearly for revenue.
        """
        all_rows = []
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            if progress_fn:
                progress_fn(ticker, i, total)

            try:
                data = self._get(f"fundamentals/{self._ticker_symbol(ticker)}", {
                    'filter': 'Financials::Income_Statement::yearly,Earnings::Annual',
                })
                if not data or not isinstance(data, dict):
                    continue

                # Income statement: keyed by date, has totalRevenue
                inc_data = data.get('Financials::Income_Statement::yearly', {})
                # Earnings: keyed by date, has epsActual
                earn_data = data.get('Earnings::Annual', {})

                # Merge by date
                all_dates = set()
                if isinstance(inc_data, dict):
                    all_dates.update(inc_data.keys())
                if isinstance(earn_data, dict):
                    all_dates.update(earn_data.keys())

                for report_date in all_dates:
                    inc = inc_data.get(report_date, {}) if isinstance(inc_data, dict) else {}
                    earn = earn_data.get(report_date, {}) if isinstance(earn_data, dict) else {}

                    if not isinstance(inc, dict):
                        inc = {}
                    if not isinstance(earn, dict):
                        earn = {}

                    revenue = _safe_num(inc.get('totalRevenue'))
                    eps = _safe_num(earn.get('epsActual'))

                    if revenue is not None or eps is not None:
                        all_rows.append({
                            'ticker': ticker,
                            'report_date': report_date,
                            'eps': eps,
                            'revenue': revenue,
                            'source': 'eodhd',
                        })

            except Exception as e:
                if progress_fn:
                    progress_fn(ticker, i, total, error=str(e))
                continue

        return pd.DataFrame(all_rows) if all_rows else pd.DataFrame(
            columns=['ticker', 'report_date', 'eps', 'revenue', 'source']
        )

    def fetch_analyst_estimates(self, tickers, progress_fn=None):
        """
        Fetch forward EPS and growth estimates from Highlights section.
        These provide EPFWD, EGRLF, EGRSF for full CNE5 factor weights.
        10 API calls per ticker.
        """
        all_rows = []
        total = len(tickers)
        today = datetime.now().strftime('%Y-%m-%d')

        for i, ticker in enumerate(tickers):
            if progress_fn:
                progress_fn(ticker, i, total)

            try:
                data = self._get(f"fundamentals/{self._ticker_symbol(ticker)}", {
                    'filter': 'Highlights',
                })
                if not data:
                    continue

                highlights = data.get('Highlights', data) if 'Highlights' in data else data

                forward_eps = _safe_num(highlights.get('EPSEstimateCurrentYear'))
                # Growth estimates: use YOY earnings and revenue growth as proxies
                growth_ltm = _safe_num(highlights.get('QuarterlyEarningsGrowthYOY'))
                growth_stm = _safe_num(highlights.get('QuarterlyRevenueGrowthYOY'))

                if forward_eps is not None or growth_ltm is not None:
                    all_rows.append({
                        'ticker': ticker,
                        'as_of_date': today,
                        'forward_eps': forward_eps,
                        'growth_ltm': growth_ltm,
                        'growth_stm': growth_stm,
                        'source': 'eodhd',
                    })

            except Exception as e:
                if progress_fn:
                    progress_fn(ticker, i, total, error=str(e))
                continue

        return pd.DataFrame(all_rows) if all_rows else pd.DataFrame(
            columns=['ticker', 'as_of_date', 'forward_eps', 'growth_ltm',
                     'growth_stm', 'source']
        )

    def fetch_classifications(self, tickers, progress_fn=None):
        """
        Fetch GICS classification (sector, group) for each ticker.
        10 API calls per ticker.

        Returns list of dicts: [{'ticker': 'AAPL', 'gic_sector': '...', 'gic_group': '...'}, ...]
        """
        results = []
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            if progress_fn:
                progress_fn(ticker, i, total)
            try:
                data = self._get(f"fundamentals/{self._ticker_symbol(ticker)}", {
                    'filter': 'General',
                })
                if not data:
                    continue
                general = data.get('General', data) if 'General' in data else data
                gic_sector = general.get('GicSector')
                gic_group = general.get('GicGroup')
                if gic_sector or gic_group:
                    results.append({
                        'ticker': ticker,
                        'gic_sector': gic_sector,
                        'gic_group': gic_group,
                    })
            except Exception:
                continue
        return results

    def fetch_risk_free_rate(self, start, end):
        """Fetch 13-week T-bill rate from EODHD."""
        try:
            data = self._get("eod/IRX.INDX", {'from': start, 'to': end})
            if data:
                dates = [pd.Timestamp(r['date']) for r in data]
                values = [r['close'] / 100 / 252 for r in data]  # annualized % -> daily
                return pd.Series(values, index=dates, name='rf_daily')
        except Exception:
            pass
        return pd.Series(dtype=float, name='rf_daily')

    def fetch_index_constituents(self, index_code):
        """
        Fetch current constituents for an index (e.g. 'RUI.INDX', 'RUT.INDX').

        Returns list of dicts: [{'ticker', 'name', 'sector', 'industry', 'exchange'}, ...]
        """
        data = self._get(f"fundamentals/{index_code}")
        comps = data.get('Components', {}) if isinstance(data, dict) else {}
        rows = []
        for v in comps.values():
            code = v.get('Code')
            if not code:
                continue
            rows.append({
                'ticker': code,
                'name': v.get('Name'),
                'sector': v.get('Sector'),
                'industry': v.get('Industry'),
                'exchange': v.get('Exchange'),
            })
        return rows


class FMPSource(DataSource):
    """
    Financial Modeling Prep data source ($20-99/month).

    Primarily used for analyst estimates (EPFWD, EGRLF, EGRSF).
    NOT YET IMPLEMENTED — requires API subscription.

    Set FMP_API_KEY in .env or environment.
    """

    name = 'fmp'

    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get('FMP_API_KEY')
        if not self.api_key:
            raise ValueError(
                "FMP API key required. Set FMP_API_KEY environment variable "
                "or pass api_key parameter. Subscribe at https://financialmodelingprep.com"
            )

    def fetch_daily_prices(self, tickers, start, end, progress_fn=None):
        raise NotImplementedError("FMP adapter not yet implemented. Coming in Phase 2.")

    def fetch_fundamentals_quarterly(self, tickers, progress_fn=None):
        raise NotImplementedError("FMP adapter not yet implemented. Coming in Phase 2.")

    def fetch_fundamentals_annual(self, tickers, progress_fn=None):
        raise NotImplementedError("FMP adapter not yet implemented. Coming in Phase 2.")

    def fetch_analyst_estimates(self, tickers, progress_fn=None):
        raise NotImplementedError("FMP adapter not yet implemented. Coming in Phase 2.")


def get_source(name, **kwargs):
    """Factory function to create a DataSource by name."""
    sources = {
        'yfinance': YFinanceSource,
        'eodhd': EODHDSource,
        'fmp': FMPSource,
    }
    if name not in sources:
        raise ValueError(f"Unknown data source: {name}. Available: {list(sources.keys())}")
    return sources[name](**kwargs)


def _get_item(series, labels):
    """Get first available item from a pandas Series by label list."""
    for label in labels:
        if label in series.index:
            val = series[label]
            if pd.notna(val):
                return val
    return np.nan


def _safe_num(val):
    """Convert EODHD string/number value to float, handling None/null."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) else f
    except (ValueError, TypeError):
        return None
