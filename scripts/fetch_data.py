# -*- coding: utf-8 -*-
"""
Fetch Russell 3000 data and compute CNE5-style factor descriptors.

10 style factors following MSCI Barra CNE5 methodology:
  size, beta, momentum, residvol, nlsize, btop, liquidity, earnyild, growth, leverage

Composite descriptors:
  - Residual Vol = 0.74*DASTD + 0.16*CMRA + 0.10*HSIGMA (orthog vs beta+size)
  - Liquidity = 0.35*STOM + 0.35*STOQ + 0.30*STOA (orthog vs size)
  - Earnings Yield = 0.656*CETOP + 0.344*ETOP (partial, no EPFWD)
  - Growth = 0.338*EGRO + 0.662*SGRO (partial, no analyst forecasts)
  - Leverage = 0.38*MLEV + 0.35*DTOA + 0.27*BLEV
  - Non-linear Size = cube of z(size), orthog vs size

Usage:
    python scripts/fetch_data.py              # Full fetch + compute
    python scripts/fetch_data.py --compute-only  # Recompute from saved raw data
    python scripts/fetch_data.py --from-db       # Compute from SQLite database
    python scripts/fetch_data.py --from-db --universe dax40  # Non-default universe
    python scripts/fetch_data.py --export        # Export raw data to Excel for QC
"""

import yfinance as yf
import pandas as pd
import numpy as np
import pickle
import time
import os
import warnings
import sys
from datetime import datetime, timedelta
warnings.filterwarnings('ignore')

RAW_DATA_PATH = 'data/model/russell3000_raw_data.pkl'
STYLE_FACTORS = ['size', 'beta', 'momentum', 'residvol', 'nlsize', 'btop',
                 'liquidity', 'earnyild', 'growth', 'leverage']


def load_from_db(universe='russell3000', use_sectors=False):
    """
    Load stock data from SQLite database, returning the same format
    as load_raw_data() so the computation pipeline works unchanged.

    If use_sectors=True, uses 11 GICS sectors instead of 25 GICS groups
    for industry classification.

    Returns: (all_stock_data, failed, rf_daily)
    """
    from data_manager import MarketDB

    db = MarketDB()
    tickers_sectors = db.get_universe_tickers(universe)
    if not tickers_sectors:
        raise ValueError(f"No tickers in universe '{universe}'. "
                         f"Run: python scripts/update_data.py init --universe {universe}")

    tickers = [t[0] for t in tickers_sectors]
    if use_sectors:
        # Use gic_sector (11 GICS Sectors) — fallback to sector column
        sectors_map = {t[0]: (t[3] or t[1]) for t in tickers_sectors}
        print(f"  Using 11 GICS sectors for industry classification")
    else:
        # Prefer gic_group (25 GICS Groups) — fallback to gic_sector, then sector
        sectors_map = {t[0]: (t[2] or t[3] or t[1]) for t in tickers_sectors}

    # Currency-aware thresholds for penny stock and volume filters
    currency = db.get_universe_exchange(universe)  # returns exchange code
    currency_info = db.conn.execute(
        "SELECT currency FROM universes WHERE name=?", (universe,)).fetchone()
    curr = currency_info[0] if currency_info else 'USD'
    # LSE prices are in pence (1/100 of GBP)
    penny_threshold = 100.0 if curr == 'GBP' else 1.0
    min_avg_volume = 50000  # minimum average daily volume

    print(f"  Loading from database: {len(tickers)} tickers in '{universe}'"
          f" (currency={curr}, penny_threshold={penny_threshold}, min_vol={min_avg_volume})")

    # Load all prices
    prices_df = db.get_daily_prices(tickers)
    if prices_df.empty:
        raise ValueError("No price data in database. "
                         "Run: python scripts/update_data.py prices --universe " + universe)

    # Load fundamentals
    fund_q_df = db.get_fundamentals_quarterly(tickers)
    fund_a_df = db.get_fundamentals_annual(tickers)

    # Load risk-free rate
    rf_series = db.get_risk_free_rate()
    rf_daily = rf_series if len(rf_series) > 0 else None
    if rf_daily is not None:
        rf_daily.name = 'rf'
        print(f"  Risk-free rate: {len(rf_daily)} days")
    else:
        print("  WARNING: No risk-free rate in database")

    # Group prices by ticker
    prices_grouped = {t: g for t, g in prices_df.groupby('ticker')}

    # Group quarterly fundamentals by ticker
    fund_q_grouped = {}
    if not fund_q_df.empty:
        fund_q_grouped = {t: g for t, g in fund_q_df.groupby('ticker')}

    # Group annual fundamentals by ticker
    fund_a_grouped = {}
    if not fund_a_df.empty:
        fund_a_grouped = {t: g for t, g in fund_a_df.groupby('ticker')}

    all_stock_data = []
    failed = []

    for ticker in tickers:
        if ticker not in prices_grouped:
            failed.append(ticker)
            continue

        pdf = prices_grouped[ticker].sort_values('date')

        # Sanity filter: drop individual rows with absurd close prices.
        # EODHD's symbol-reuse contaminates some delisted US tickers (e.g. MEL.US,
        # WFT, CIN, TEK_old) with $5k-$1M closes from a different company that
        # took over the symbol. No real S&P 500 common stock trades >$5k
        # (BRK.A excluded — sp500_hist uses BRK-B class). Filter is in *price
        # currency units* (USD for sp500_hist, GBP-pence × penny_threshold for
        # UK, etc.) — the same threshold-units as penny_threshold above.
        absurd_close = 5000.0 * penny_threshold  # USD: $5k cap; LSE pence: 500k pence
        pdf = pdf[(pdf['close'] > 0) & (pdf['close'] < absurd_close)]

        if len(pdf) < 252:
            failed.append(ticker)
            continue

        # Skip penny stocks: currency-aware threshold
        recent_close = pdf['close'].tail(60)
        if recent_close.median() < penny_threshold:
            failed.append(ticker)
            continue

        # Skip illiquid stocks: average volume over last 60 days
        recent_vol = pdf['volume'].tail(60)
        if recent_vol.mean() < min_avg_volume:
            failed.append(ticker)
            continue

        # Build history DataFrame (mimic yfinance format)
        hist = pd.DataFrame({
            'Open': pdf['open'].values,
            'High': pdf['high'].values,
            'Low': pdf['low'].values,
            'Close': pdf['close'].values,
            'Volume': pdf['volume'].values,
        }, index=pd.DatetimeIndex(pdf['date']))

        shares_out = pdf['shares_out'].dropna().iloc[-1] if pdf['shares_out'].notna().any() else np.nan

        # Build quarterly dict (same format as yfinance fetcher)
        q = {}
        quarterly_fields = ['book_equity', 'net_income', 'depreciation', 'revenue',
                            'long_term_debt', 'total_debt', 'total_assets', 'preferred_equity']
        if ticker in fund_q_grouped:
            qdf = fund_q_grouped[ticker]
            for field in quarterly_fields:
                if field in qdf.columns:
                    vals = qdf[['report_date', field]].dropna(subset=[field])
                    q[field] = {pd.Timestamp(r['report_date']): r[field]
                                for _, r in vals.iterrows()}
                else:
                    q[field] = {}
        else:
            for field in quarterly_fields:
                q[field] = {}

        # Annual EPS/revenue
        if ticker in fund_a_grouped:
            adf = fund_a_grouped[ticker]
            eps_vals = adf[['report_date', 'eps']].dropna(subset=['eps'])
            q['annual_eps'] = {pd.Timestamp(r['report_date']): r['eps']
                               for _, r in eps_vals.iterrows()}
            rev_vals = adf[['report_date', 'revenue']].dropna(subset=['revenue'])
            q['annual_revenue'] = {pd.Timestamp(r['report_date']): r['revenue']
                                   for _, r in rev_vals.iterrows()}
        else:
            q['annual_eps'] = {}
            q['annual_revenue'] = {}

        all_stock_data.append({
            'ticker': ticker,
            'history': hist,
            'shares_outstanding': shares_out,
            'sector': sectors_map.get(ticker, 'Unknown'),
            'quarterly': q,
        })

    print(f"  Loaded: {len(all_stock_data)} stocks, {len(failed)} failed/insufficient data")
    db.close()
    return all_stock_data, failed, rf_daily


def fetch_risk_free_rate(period='2y'):
    """Fetch 13-week T-bill rate (^IRX) as daily risk-free rate."""
    try:
        irx = yf.Ticker('^IRX')
        hist = irx.history(period=period)
        if len(hist) > 0:
            rf = hist['Close'] / 100 / 252  # annualized % -> daily decimal
            rf.name = 'rf'
            print(f"  Risk-free rate: {len(rf)} days, latest={rf.iloc[-1]*252*100:.2f}% ann.")
            return rf
    except:
        pass
    print("  WARNING: Could not fetch risk-free rate, using 0")
    return None


def fetch_stock_history(ticker, period='2y'):
    """Fetch price history and fundamentals for CNE5 factor computation."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        if len(hist) < 252:
            return None

        info = stock.info
        shares_outstanding = info.get('sharesOutstanding', np.nan)

        q = {}  # quarterly data dict

        # --- Quarterly balance sheet ---
        try:
            bs = stock.quarterly_balance_sheet
            if bs is not None and not bs.empty:
                def _get_row(df, labels):
                    for label in labels:
                        if label in df.index:
                            return df.loc[label].dropna().to_dict()
                    return {}

                q['book_equity'] = _get_row(bs, [
                    'Stockholders Equity', 'Total Stockholders Equity',
                    'Total Equity Gross Minority Interest', 'Common Stock Equity'])
                q['long_term_debt'] = _get_row(bs, [
                    'Long Term Debt', 'Long Term Debt And Capital Lease Obligation'])
                q['total_assets'] = _get_row(bs, ['Total Assets'])
                q['preferred_equity'] = _get_row(bs, ['Preferred Stock', 'Preferred Stock Equity'])

                # Total debt
                if 'Total Debt' in bs.index:
                    q['total_debt'] = bs.loc['Total Debt'].dropna().to_dict()
                else:
                    # Try current debt + long-term debt
                    cd = _get_row(bs, ['Current Debt', 'Current Debt And Capital Lease Obligation'])
                    ltd = q['long_term_debt']
                    if cd and ltd:
                        combined = {}
                        for d in set(list(cd.keys()) + list(ltd.keys())):
                            if d in cd and d in ltd:
                                combined[d] = cd[d] + ltd[d]
                        q['total_debt'] = combined
                    else:
                        q['total_debt'] = {}
            else:
                for k in ['book_equity', 'long_term_debt', 'total_debt', 'total_assets', 'preferred_equity']:
                    q[k] = {}
        except:
            for k in ['book_equity', 'long_term_debt', 'total_debt', 'total_assets', 'preferred_equity']:
                q[k] = {}

        # --- Quarterly income statement ---
        try:
            inc = stock.quarterly_income_stmt
            if inc is not None and not inc.empty:
                def _get_row(df, labels):
                    for label in labels:
                        if label in df.index:
                            return df.loc[label].dropna().to_dict()
                    return {}

                q['net_income'] = _get_row(inc, ['Net Income', 'Net Income Common Stockholders'])
                q['depreciation'] = _get_row(inc, [
                    'Depreciation And Amortization In Income Statement',
                    'Depreciation And Amortization', 'Reconciled Depreciation'])
                q['revenue'] = _get_row(inc, ['Total Revenue', 'Operating Revenue'])
            else:
                for k in ['net_income', 'depreciation', 'revenue']:
                    q[k] = {}
        except:
            for k in ['net_income', 'depreciation', 'revenue']:
                q[k] = {}

        # --- Annual financials (for EGRO, SGRO) ---
        try:
            ann_inc = stock.income_stmt
            if ann_inc is not None and not ann_inc.empty:
                def _get_row(df, labels):
                    for label in labels:
                        if label in df.index:
                            return df.loc[label].dropna().to_dict()
                    return {}

                q['annual_eps'] = _get_row(ann_inc, ['Basic EPS', 'Diluted EPS'])
                q['annual_revenue'] = _get_row(ann_inc, ['Total Revenue', 'Operating Revenue'])
            else:
                q['annual_eps'] = {}
                q['annual_revenue'] = {}
        except:
            q['annual_eps'] = {}
            q['annual_revenue'] = {}

        return {
            'ticker': ticker,
            'history': hist,
            'shares_outstanding': shares_outstanding,
            'quarterly': q,
        }

    except Exception as e:
        return None


def save_raw_data(all_stock_data, failed, rf_daily=None):
    """Save raw data to pickle for re-computation without re-fetching."""
    with open(RAW_DATA_PATH, 'wb') as f:
        pickle.dump({'stock_data': all_stock_data, 'failed': failed, 'rf_daily': rf_daily}, f)
    size_mb = os.path.getsize(RAW_DATA_PATH) / (1024 * 1024)
    print(f"  Saved raw data to {RAW_DATA_PATH} ({size_mb:.0f} MB)")


def load_raw_data():
    """Load previously fetched raw data from pickle."""
    if not os.path.exists(RAW_DATA_PATH):
        raise FileNotFoundError(f"No raw data found at {RAW_DATA_PATH}. Run without --compute-only first.")
    with open(RAW_DATA_PATH, 'rb') as f:
        data = pickle.load(f)
    rf = data.get('rf_daily', None)
    print(f"  Loaded raw data: {len(data['stock_data'])} stocks, {len(data['failed'])} failed")
    if rf is not None:
        print(f"  Risk-free rate: {len(rf)} days")
    else:
        print("  WARNING: No risk-free rate in saved data")
    return data['stock_data'], data['failed'], rf


def get_last_known_value(date, quarterly_data):
    """Get last known quarterly value as of date (no look-ahead bias)."""
    if not quarterly_data:
        return np.nan
    date = pd.Timestamp(date)
    valid = [d for d in quarterly_data.keys() if pd.Timestamp(d) <= date]
    if not valid:
        return np.nan
    most_recent = max(valid, key=lambda x: pd.Timestamp(x))
    return quarterly_data[most_recent]


def get_trailing_annual_values(date, annual_data, n_years=5):
    """Get up to n_years of annual values ending before date."""
    if not annual_data:
        return []
    date = pd.Timestamp(date)
    items = [(pd.Timestamp(d), v) for d, v in annual_data.items()
             if pd.Timestamp(d) <= date and pd.notna(v)]
    items.sort(key=lambda x: x[0], reverse=True)
    return items[:n_years]


def compute_growth_slope(values):
    """Regress values against time, return slope / mean(|values|) as growth rate."""
    if len(values) < 3:
        return np.nan
    vals = np.array([v for _, v in sorted(values, key=lambda x: x[0])])
    mean_abs = np.mean(np.abs(vals))
    if mean_abs == 0:
        return np.nan
    x = np.arange(len(vals), dtype=float)
    x_c = x - x.mean()
    slope = np.sum(x_c * vals) / np.sum(x_c ** 2)
    return slope / mean_abs


def fetch_all_stocks(tickers, sectors, period='2y', batch_size=10, delay=1.0):
    """Fetch historical data for all stocks."""
    all_stock_data = []
    failed = []
    total = len(tickers)
    start_time = time.time()

    for i, ticker in enumerate(tickers):
        if i % 50 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            remaining = (total - i) / rate / 60 if rate > 0 else 0
            print(f"[{i+1}/{total}] {i*100//total}% complete, ~{remaining:.0f} min remaining", flush=True)

        data = fetch_stock_history(ticker, period=period)
        if data:
            data['sector'] = sectors.get(ticker, 'Unknown')
            all_stock_data.append(data)
            status = "OK"
        else:
            failed.append(ticker)
            status = "FAIL"

        if (i + 1) % 10 == 0:
            print(f"  ...{ticker}: {status} ({len(all_stock_data)} success, {len(failed)} failed)", flush=True)
        if (i + 1) % batch_size == 0:
            time.sleep(delay)

    print(f"\n{'='*60}")
    print(f"COMPLETED: {len(all_stock_data)}/{total} successful ({len(all_stock_data)*100//total}%)")
    print(f"Failed: {len(failed)}")
    if len(failed) <= 20:
        print(f"Failed tickers: {failed}")
    return all_stock_data, failed


def compute_stock_descriptors(stock_data, dates, rf_series):
    """
    Compute CNE5-style descriptors for one stock across all dates.
    Price-based descriptors are vectorized; fundamental descriptors use per-date lookups.
    """
    hist = stock_data['history'].copy()
    ticker = stock_data['ticker']
    shares = stock_data['shares_outstanding']
    q = stock_data.get('quarterly', {})
    # Backward compat with old pickle format
    if not q and 'quarterly_book_value' in stock_data:
        q = {
            'book_equity': stock_data.get('quarterly_book_value', {}),
            'net_income': stock_data.get('quarterly_net_income', {}),
        }

    # --- Filter zero/negative prices ---
    hist = hist[hist['Close'] > 0].copy()
    if len(hist) < 61:
        return pd.DataFrame()

    # --- Basic returns ---
    hist['return'] = hist['Close'].pct_change()
    hist['log_return'] = np.log(hist['Close'] / hist['Close'].shift(1))
    # Winsorize extreme daily returns (cap at ±25% log return)
    hist['log_return'] = hist['log_return'].clip(-0.25, 0.25)

    # Merge risk-free rate
    if rf_series is not None:
        rf_df = rf_series.to_frame('rf')
        if hist.index.tzinfo is not None and rf_df.index.tzinfo is None:
            rf_df.index = rf_df.index.tz_localize(hist.index.tzinfo)
        elif hist.index.tzinfo is None and rf_df.index.tzinfo is not None:
            rf_df.index = rf_df.index.tz_localize(None)
        hist = hist.merge(rf_df, left_index=True, right_index=True, how='left')
        hist['rf'] = hist['rf'].ffill().fillna(0)
    else:
        hist['rf'] = 0.0

    hist['excess_return'] = hist['return'] - hist['rf']
    hist['excess_log_return'] = hist['log_return'] - hist['rf']

    # --- Vectorized price-based descriptors ---

    # DASTD: EWM std of daily excess returns (halflife=42)
    hist['dastd'] = hist['excess_return'].ewm(halflife=42, min_periods=60).std()

    # RSTR (Momentum): EWM of lagged excess log returns (skip 21d, halflife=126)
    hist['rstr'] = hist['excess_log_return'].shift(21).ewm(halflife=126, min_periods=126).mean()

    # CMRA: cumulative range over 12 monthly intervals
    z_cols = []
    for T in range(1, 13):
        col = f'_z_{T}'
        hist[col] = hist['excess_log_return'].rolling(T * 21, min_periods=max(T * 15, 10)).sum()
        z_cols.append(col)
    hist['_z_max'] = hist[z_cols].max(axis=1)
    hist['_z_min'] = hist[z_cols].min(axis=1)
    # Clip to avoid log of negative
    hist['cmra'] = np.log((1 + hist['_z_max']).clip(lower=0.01)) - np.log((1 + hist['_z_min']).clip(lower=0.01))
    hist = hist.drop(columns=z_cols + ['_z_max', '_z_min'])

    # Turnover-based liquidity (STOM, STOQ, STOA)
    if pd.notna(shares) and shares > 0:
        turnover = hist['Volume'] / shares
        t_21 = turnover.rolling(21, min_periods=15).sum()
        t_63 = turnover.rolling(63, min_periods=42).sum()
        t_252 = turnover.rolling(252, min_periods=126).sum()
        hist['stom'] = np.log(t_21.clip(lower=1e-12))
        hist['stoq'] = np.log((t_63 / 3).clip(lower=1e-12))
        hist['stoa'] = np.log((t_252 / 12).clip(lower=1e-12))
    else:
        hist['stom'] = np.nan
        hist['stoq'] = np.nan
        hist['stoa'] = np.nan

    # --- Sample at required dates + fundamental lookups ---
    records = []
    for date in dates:
        date_ts = pd.Timestamp(date)
        if date_ts.tzinfo is None and hist.index.tzinfo is not None:
            date_ts = date_ts.tz_localize(hist.index.tzinfo)
        elif date_ts.tzinfo is not None and hist.index.tzinfo is None:
            date_ts = date_ts.tz_localize(None)

        hist_to_date = hist[hist.index <= date_ts]
        if len(hist_to_date) < 61:
            continue

        last = hist_to_date.iloc[-1]   # day t (return only)
        # Skip if this stock's latest price is stale (>3 calendar days behind)
        last_date = hist_to_date.index[-1]
        if hasattr(last_date, 'tz_localize'):
            gap = (date_ts - last_date).days if hasattr(date_ts - last_date, 'days') else 0
        else:
            gap = 0
        if gap > 5:
            continue

        prev = hist_to_date.iloc[-2]   # day t-1 (all factor exposures)
        daily_return = last['log_return']
        if pd.isna(daily_return):
            continue

        current_price = prev['Close']  # t-1 close: no look-ahead bias

        # SIZE: LNCAP
        market_cap = current_price * shares if pd.notna(shares) and shares > 0 else np.nan
        size_raw = np.log(market_cap) if pd.notna(market_cap) and market_cap > 0 else np.nan

        # BTOP: Book-to-Price
        bv = get_last_known_value(date, q.get('book_equity', {}))
        btop_raw = bv / market_cap if pd.notna(bv) and pd.notna(market_cap) and market_cap > 0 else np.nan

        # ETOP: Trailing earnings-to-price (annualized quarterly)
        ni = get_last_known_value(date, q.get('net_income', {}))
        etop_raw = (ni * 4) / market_cap if pd.notna(ni) and pd.notna(market_cap) and market_cap > 0 else np.nan

        # CETOP: Cash earnings-to-price
        dep = get_last_known_value(date, q.get('depreciation', {}))
        if pd.notna(ni) and pd.notna(dep) and pd.notna(market_cap) and market_cap > 0:
            cetop_raw = ((ni + dep) * 4) / market_cap
        else:
            cetop_raw = np.nan

        # EGRO: Earnings growth (slope regression)
        annual_eps = get_trailing_annual_values(date, q.get('annual_eps', {}), n_years=5)
        egro_raw = compute_growth_slope(annual_eps)

        # SGRO: Sales growth (slope regression)
        annual_rev = get_trailing_annual_values(date, q.get('annual_revenue', {}), n_years=5)
        sgro_raw = compute_growth_slope(annual_rev)

        # Leverage components
        me = market_cap
        be = bv if pd.notna(bv) else np.nan
        pe = get_last_known_value(date, q.get('preferred_equity', {}))
        pe = pe if pd.notna(pe) else 0
        ld = get_last_known_value(date, q.get('long_term_debt', {}))
        td = get_last_known_value(date, q.get('total_debt', {}))
        ta = get_last_known_value(date, q.get('total_assets', {}))

        mlev_raw = (me + pe + ld) / me if pd.notna(me) and me > 0 and pd.notna(ld) else np.nan
        dtoa_raw = td / ta if pd.notna(td) and pd.notna(ta) and ta > 0 else np.nan
        blev_raw = (be + pe + ld) / be if pd.notna(be) and be > 0 and pd.notna(ld) else np.nan

        records.append({
            'date': date,
            'ticker': ticker,
            'return': daily_return,
            'rf': prev['rf'] if 'rf' in hist.columns else 0.0,
            'market_cap': market_cap,
            'size_raw': size_raw,
            'momentum_raw': prev['rstr'] if 'rstr' in hist.columns else np.nan,
            'dastd_raw': prev['dastd'] if 'dastd' in hist.columns else np.nan,
            'cmra_raw': prev['cmra'] if 'cmra' in hist.columns else np.nan,
            'stom_raw': prev['stom'] if 'stom' in hist.columns else np.nan,
            'stoq_raw': prev['stoq'] if 'stoq' in hist.columns else np.nan,
            'stoa_raw': prev['stoa'] if 'stoa' in hist.columns else np.nan,
            'btop_raw': btop_raw,
            'etop_raw': etop_raw,
            'cetop_raw': cetop_raw,
            'egro_raw': egro_raw,
            'sgro_raw': sgro_raw,
            'mlev_raw': mlev_raw,
            'dtoa_raw': dtoa_raw,
            'blev_raw': blev_raw,
        })

    return pd.DataFrame(records)


def create_cross_sectional_dataset(all_stock_data, rf_series, target_days=504,
                                   min_coverage=0.80):
    """Create dataset with all CNE5 descriptors for all stocks."""
    print(f"\nDetermining trading dates (>={min_coverage:.0%} stock coverage)...")
    from collections import Counter
    date_counts = Counter()
    for sd in all_stock_data:
        for d in sd['history'].index.strftime('%Y-%m-%d'):
            date_counts[d] += 1

    n_stocks = len(all_stock_data)
    threshold = int(n_stocks * min_coverage)
    all_dates = sorted([d for d, cnt in date_counts.items() if cnt >= threshold])
    all_dates = all_dates[-target_days:]
    print(f"  Found {len(all_dates)} dates with >={min_coverage:.0%} coverage "
          f"(threshold: {threshold}/{n_stocks} stocks)")
    print(f"  Date range: {all_dates[0]} to {all_dates[-1]}")

    print(f"\nComputing CNE5 descriptors for {len(all_stock_data)} stocks...")
    all_records = []
    for i, sd in enumerate(all_stock_data):
        if (i + 1) % 100 == 0:
            print(f"  Processing stock {i+1}/{len(all_stock_data)}...", flush=True)
        sf = compute_stock_descriptors(sd, all_dates, rf_series)
        if not sf.empty:
            sf['sector'] = sd['sector']
            all_records.append(sf)

    print(f"\nCombining data...")
    df = pd.concat(all_records, ignore_index=True)
    print(f"  Total records: {len(df)}")
    print(f"  Unique dates: {df['date'].nunique()}")
    print(f"  Unique stocks: {df['ticker'].nunique()}")
    return df, all_dates


def add_beta_and_hsigma(df):
    """
    Compute beta (EWM halflife=63) and HSIGMA (std of regression residuals).
    Uses cap-weighted excess market return per CNE5: r_t - r_ft = α + β * R_t + e_t
    """
    print("\nComputing beta and HSIGMA (using excess returns per CNE5)...")

    def cap_wt_mean(g):
        valid = g[['return', 'market_cap']].dropna()
        if len(valid) == 0 or valid['market_cap'].sum() == 0:
            return np.nan
        w = valid['market_cap'] / valid['market_cap'].sum()
        return (w * valid['return']).sum()

    mkt = df.groupby('date').apply(cap_wt_mean)
    mkt.name = 'market_return'
    df = df.merge(mkt, left_on='date', right_index=True, how='left')

    # Compute excess returns (stock and market)
    rf = df['rf'].fillna(0)
    df['excess_return'] = df['return'] - rf
    df['excess_market_return'] = df['market_return'] - rf

    n_stocks = df['ticker'].nunique()
    processed = 0
    results = []

    for ticker, group in df.groupby('ticker'):
        processed += 1
        if processed % 200 == 0:
            print(f"  Beta: {processed}/{n_stocks} stocks...", flush=True)

        g = group.sort_values('date').copy()
        s = g['excess_return']
        m = g['excess_market_return']

        # EWM beta (halflife=63, per CNE5)
        ewm_cov = s.ewm(halflife=63, min_periods=60).cov(m)
        ewm_var = m.ewm(halflife=63, min_periods=60).var()
        g['beta_raw'] = ewm_cov / ewm_var

        # HSIGMA: EWM std of regression residuals (from excess return regression)
        residual = s - g['beta_raw'] * m
        g['hsigma_raw'] = residual.ewm(halflife=63, min_periods=60).std()

        results.append(g)

    df = pd.concat(results, ignore_index=True)
    df = df.drop(columns=['market_return', 'excess_return', 'excess_market_return'])
    print(f"  Beta coverage: {df['beta_raw'].notna().mean()*100:.1f}%")
    print(f"  HSIGMA coverage: {df['hsigma_raw'].notna().mean()*100:.1f}%")
    return df


def compute_composites(df):
    """
    Compute CNE5 composite factors from z-scored sub-descriptors.
    Z-score sub-descriptors first, then combine with CNE5 weights.
    """
    print("\nComputing composite factors...")

    # Z-score sub-descriptors within each date (cap-weighted mean=0, EW std=1)
    sub_descriptors = ['dastd', 'cmra', 'hsigma', 'stom', 'stoq', 'stoa',
                       'etop', 'cetop', 'egro', 'sgro', 'mlev', 'dtoa', 'blev']
    for col in sub_descriptors:
        raw = f'{col}_raw'
        if raw not in df.columns:
            continue
        results = []
        for date, group in df.groupby('date'):
            vals = group[raw]
            caps = group['market_cap']
            valid = vals.notna() & caps.notna() & (caps > 0)
            if valid.sum() < 10:
                results.append(pd.Series(0.0, index=group.index))
                continue
            w = caps[valid] / caps[valid].sum()
            raw_mean = vals[valid].mean()
            raw_std = vals[valid].std()
            if raw_std == 0:
                results.append(pd.Series(0.0, index=group.index))
                continue
            clipped = vals[valid].clip(raw_mean - 3.5 * raw_std,
                                       raw_mean + 3.5 * raw_std)
            cw_mean = (w * clipped).sum()
            ew_std = clipped.std()
            if ew_std == 0:
                results.append(pd.Series(0.0, index=group.index))
                continue
            zscored = pd.Series(np.nan, index=group.index)
            zscored[valid] = (clipped - cw_mean) / ew_std
            results.append(zscored)
        df[col] = pd.concat(results)

    # Residual Volatility: 0.74*DASTD + 0.16*CMRA + 0.10*HSIGMA
    df['residvol_raw'] = (0.74 * df['dastd'].fillna(0)
                          + 0.16 * df['cmra'].fillna(0)
                          + 0.10 * df['hsigma'].fillna(0))

    # Liquidity: 0.35*STOM + 0.35*STOQ + 0.30*STOA
    df['liquidity_raw'] = (0.35 * df['stom'].fillna(0)
                           + 0.35 * df['stoq'].fillna(0)
                           + 0.30 * df['stoa'].fillna(0))

    # Earnings Yield (partial, no EPFWD): renormalized CETOP + ETOP
    # Original: 0.68*EPFWD + 0.21*CETOP + 0.11*ETOP -> renorm: 0.656*CETOP + 0.344*ETOP
    df['earnyild_raw'] = (0.656 * df['cetop'].fillna(0)
                          + 0.344 * df['etop'].fillna(0))

    # Growth (partial, no analyst forecasts): renormalized EGRO + SGRO
    # Original: 0.18*EGRLF + 0.11*EGRSF + 0.24*EGRO + 0.47*SGRO -> renorm: 0.338*EGRO + 0.662*SGRO
    df['growth_raw'] = (0.338 * df['egro'].fillna(0)
                        + 0.662 * df['sgro'].fillna(0))

    # Leverage: 0.38*MLEV + 0.35*DTOA + 0.27*BLEV
    df['leverage_raw'] = (0.38 * df['mlev'].fillna(0)
                          + 0.35 * df['dtoa'].fillna(0)
                          + 0.27 * df['blev'].fillna(0))

    return df


def zscore_by_date(df, columns):
    """
    Z-score: cap-weighted mean = 0, equal-weighted std = 1 (CNE5 convention).
    """
    for col in columns:
        raw_col = f"{col}_raw"
        if raw_col not in df.columns:
            continue

        results = []
        for date, group in df.groupby('date'):
            vals = group[raw_col]
            caps = group['market_cap']
            valid = vals.notna() & caps.notna() & (caps > 0)
            if valid.sum() < 10:
                results.append(pd.Series(0.0, index=group.index))
                continue
            w = caps[valid] / caps[valid].sum()
            # Step 1: Winsorize raw values at ±3.5σ BEFORE z-scoring.
            # Prevents extreme outliers from inflating std and compressing
            # all normal values to near-zero z-scores.
            raw_mean = vals[valid].mean()
            raw_std = vals[valid].std()
            if raw_std == 0:
                results.append(pd.Series(0.0, index=group.index))
                continue
            clipped = vals[valid].clip(raw_mean - 3.5 * raw_std,
                                       raw_mean + 3.5 * raw_std)
            # Step 2: Z-score the winsorized values (CW mean=0, EW std=1)
            cw_mean = (w * clipped).sum()
            ew_std = clipped.std()
            if ew_std == 0:
                results.append(pd.Series(0.0, index=group.index))
                continue
            zscored = pd.Series(np.nan, index=group.index)
            zscored[valid] = (clipped - cw_mean) / ew_std
            results.append(zscored)

        df[col] = pd.concat(results)
    return df


def add_nlsize(df):
    """Non-linear Size: cube of z-scored size, orthogonalized vs size."""
    print("  Computing non-linear size...")
    df['nlsize_raw'] = df['size'] ** 3

    results = []
    for date, group in df.groupby('date'):
        g = group.copy()
        mask = g[['nlsize_raw', 'size']].notna().all(axis=1)
        if mask.sum() > 10:
            X = np.column_stack([np.ones(mask.sum()), g.loc[mask, 'size'].values])
            y = g.loc[mask, 'nlsize_raw'].values
            try:
                coef = np.linalg.lstsq(X, y, rcond=None)[0]
                g.loc[mask, 'nlsize_raw'] = y - X @ coef
            except:
                pass
        results.append(g)
    df = pd.concat(results, ignore_index=True)
    return df


def orthogonalize_factors(df):
    """
    Cross-sectional orthogonalization (CNE5):
    - Residual Volatility vs (beta, size)
    - Liquidity vs size
    """
    print("\nOrthogonalizing factors...")

    def _orth(g, target, regressors):
        mask = g[[target] + regressors].notna().all(axis=1)
        if mask.sum() > 10:
            X = np.column_stack([np.ones(mask.sum())] +
                                [g.loc[mask, r].values for r in regressors])
            y = g.loc[mask, target].values
            try:
                coef = np.linalg.lstsq(X, y, rcond=None)[0]
                resid = y - X @ coef
                std = resid.std()
                if std > 0:
                    g.loc[mask, target] = (resid - resid.mean()) / std
            except:
                pass
        return g

    results = []
    for date, group in df.groupby('date'):
        g = _orth(group.copy(), 'residvol', ['beta', 'size'])
        g = _orth(g, 'liquidity', ['size'])
        results.append(g)
    df = pd.concat(results, ignore_index=True)
    print("  Orthogonalized: residvol vs (beta, size), liquidity vs size")
    return df


def create_barra_format(df, style_cols):
    """Convert to Barra MFM format with industry dummies."""
    sectors = df['sector'].dropna().unique()
    sectors = [s for s in sectors if s not in ['Unknown', 'Cash and/or Derivatives', 'Other', '']]
    sectors = sorted(sectors)

    print(f"\nCreating Barra format with {len(sectors)} industries...")
    for sector in sectors:
        df[sector] = (df['sector'] == sector).astype(int)

    df = df.rename(columns={'ticker': 'stocknames', 'return': 'ret', 'market_cap': 'capital'})
    base_cols = ['date', 'stocknames', 'capital', 'ret']
    final_cols = base_cols + sectors + style_cols
    available_cols = [c for c in final_cols if c in df.columns]
    result = df[available_cols].copy()

    # Drop rows missing core (un-fillable) factors — these stocks lack enough
    # history for a meaningful regression. Composite factors with zero
    # sub-descriptors (residvol/liquidity/etc) can legitimately be 0, but
    # missing beta/size/momentum should NOT be zero-filled (creates phantom
    # zero-exposure rows that bias the cross-sectional regression).
    core_required = [c for c in ('size', 'beta', 'momentum') if c in result.columns]
    if core_required:
        before = len(result)
        result = result.dropna(subset=core_required)
        dropped = before - len(result)
        if dropped > 0:
            print(f"  Dropped {dropped} rows with NaN in core factors {core_required}")

    # Other style cols may legitimately have zeros (composites where some
    # sub-descriptor is missing); fill those for the regression.
    other_style_cols = [c for c in style_cols if c not in core_required]
    for col in other_style_cols:
        if col in result.columns:
            result[col] = result[col].fillna(0)

    result = result.dropna(subset=['ret', 'capital'])
    result = result[result['capital'] > 0]
    return result, sectors, style_cols


def export_raw_data_to_excel():
    """Export ALL raw pickle data for quality control.

    Outputs:
      - data/model/russell3000_raw_data_export.xlsx
          Sheet 1: Stock Summary (one row per stock, metadata + latest values)
          Sheet 2: Quarterly Fundamentals (full time series per stock)
          Sheet 3: Annual Financials (EPS + revenue per stock, up to 5 years)
          Sheet 4: Risk-Free Rate (daily series)
          Sheet 5: Failed Tickers
          Sheet 6: Coverage Stats
      - data/model/russell3000_daily_prices.csv
          Full daily price/volume history (~1.27M rows, exceeds Excel limit)
    """
    print("Loading raw data for export...")
    all_stock_data, failed, rf_daily = load_raw_data()

    export_path = 'data/model/russell3000_raw_data_qc.xlsx'
    prices_path = 'data/model/russell3000_daily_prices.csv'

    # --- Daily Prices (CSV — too large for Excel) ---
    print("  Building daily price history...")
    price_frames = []
    for sd in all_stock_data:
        hist = sd['history'][['Open', 'High', 'Low', 'Close', 'Volume']].copy()
        hist.index = hist.index.tz_localize(None) if hist.index.tzinfo is not None else hist.index
        hist = hist.reset_index().rename(columns={'index': 'date', 'Date': 'date'})
        hist.insert(0, 'ticker', sd['ticker'])
        hist.insert(1, 'sector', sd.get('sector', ''))
        hist['shares_outstanding'] = sd['shares_outstanding']
        price_frames.append(hist)
    prices_df = pd.concat(price_frames, ignore_index=True)
    prices_df = prices_df.sort_values(['ticker', 'date']).reset_index(drop=True)
    prices_df.to_csv(prices_path, index=False)
    prices_mb = os.path.getsize(prices_path) / (1024 * 1024)
    print(f"    Saved {len(prices_df):,} rows to {prices_path} ({prices_mb:.0f} MB)")

    # --- Sheet 1: Stock Summary ---
    print("  Building stock summary...")
    summary_rows = []
    for sd in all_stock_data:
        hist = sd['history']
        q = sd.get('quarterly', {})
        latest_date = hist.index[-1].tz_localize(None) if hist.index.tzinfo is not None else hist.index[-1]

        row = {
            'ticker': sd['ticker'],
            'sector': sd.get('sector', ''),
            'shares_outstanding': sd['shares_outstanding'],
            'history_start': hist.index[0].strftime('%Y-%m-%d'),
            'history_end': hist.index[-1].strftime('%Y-%m-%d'),
            'history_days': len(hist),
            'latest_close': hist['Close'].iloc[-1],
            'latest_volume': hist['Volume'].iloc[-1],
            'market_cap': (hist['Close'].iloc[-1] * sd['shares_outstanding']
                           if pd.notna(sd['shares_outstanding']) else np.nan),
        }

        for key in ['book_equity', 'net_income', 'depreciation', 'revenue',
                    'long_term_debt', 'total_debt', 'total_assets', 'preferred_equity']:
            val = get_last_known_value(latest_date, q.get(key, {}))
            row[f'latest_{key}'] = val

        for key in ['annual_eps', 'annual_revenue']:
            data = q.get(key, {})
            row[f'{key}_years'] = len(data) if data else 0

        summary_rows.append(row)

    summary_df = pd.DataFrame(summary_rows)
    summary_df = summary_df.sort_values('ticker').reset_index(drop=True)

    # --- Sheet 2: Quarterly Fundamentals (full time series) ---
    print("  Building quarterly fundamentals...")
    quarterly_fields = ['book_equity', 'net_income', 'depreciation', 'revenue',
                        'long_term_debt', 'total_debt', 'total_assets', 'preferred_equity']
    quarterly_rows = []
    for sd in all_stock_data:
        q = sd.get('quarterly', {})
        # Collect all report dates across all fields
        all_dates = set()
        for field in quarterly_fields:
            all_dates.update(q.get(field, {}).keys())

        for report_date in sorted(all_dates, key=lambda d: pd.Timestamp(d)):
            row = {'ticker': sd['ticker'], 'report_date': pd.Timestamp(report_date).strftime('%Y-%m-%d')}
            for field in quarterly_fields:
                val = q.get(field, {}).get(report_date, np.nan)
                row[field] = val
            quarterly_rows.append(row)

    quarterly_df = pd.DataFrame(quarterly_rows)
    quarterly_df = quarterly_df.sort_values(['ticker', 'report_date']).reset_index(drop=True)
    print(f"    {len(quarterly_df):,} rows across {quarterly_df['ticker'].nunique()} stocks")

    # --- Sheet 3: Annual Financials (EPS + Revenue for growth) ---
    print("  Building annual financials...")
    annual_rows = []
    for sd in all_stock_data:
        q = sd.get('quarterly', {})
        all_dates = set()
        for field in ['annual_eps', 'annual_revenue']:
            all_dates.update(q.get(field, {}).keys())

        for report_date in sorted(all_dates, key=lambda d: pd.Timestamp(d)):
            row = {
                'ticker': sd['ticker'],
                'report_date': pd.Timestamp(report_date).strftime('%Y-%m-%d'),
                'eps': q.get('annual_eps', {}).get(report_date, np.nan),
                'revenue': q.get('annual_revenue', {}).get(report_date, np.nan),
            }
            annual_rows.append(row)

    annual_df = pd.DataFrame(annual_rows)
    annual_df = annual_df.sort_values(['ticker', 'report_date']).reset_index(drop=True)
    print(f"    {len(annual_df):,} rows across {annual_df['ticker'].nunique()} stocks")

    # --- Sheet 4: Risk-Free Rate ---
    if rf_daily is not None:
        rf_df = rf_daily.reset_index()
        rf_df.columns = ['date', 'rf_daily']
        rf_df['date'] = rf_df['date'].dt.tz_localize(None) if rf_df['date'].dt.tz is not None else rf_df['date']
        rf_df['rf_annualized_pct'] = rf_df['rf_daily'] * 252 * 100
    else:
        rf_df = pd.DataFrame({'note': ['No risk-free rate data available']})

    # --- Sheet 5: Failed Tickers ---
    failed_df = pd.DataFrame({'ticker': sorted(failed)})

    # --- Sheet 6: Coverage Statistics ---
    print("  Computing coverage statistics...")
    coverage_rows = []
    for col in ['shares_outstanding', 'latest_close', 'market_cap',
                'latest_book_equity', 'latest_net_income', 'latest_depreciation',
                'latest_revenue', 'latest_long_term_debt', 'latest_total_debt',
                'latest_total_assets']:
        if col in summary_df.columns:
            series = summary_df[col]
            coverage_rows.append({
                'field': col,
                'count_non_null': int(series.notna().sum()),
                'count_total': len(series),
                'coverage_pct': round(series.notna().mean() * 100, 1),
                'min': series.min() if series.notna().any() else np.nan,
                'median': series.median() if series.notna().any() else np.nan,
                'max': series.max() if series.notna().any() else np.nan,
            })
    coverage_df = pd.DataFrame(coverage_rows)

    # --- Write Excel ---
    print(f"  Writing to {export_path}...")
    with pd.ExcelWriter(export_path, engine='openpyxl') as writer:
        summary_df.to_excel(writer, sheet_name='Stock Summary', index=False)
        quarterly_df.to_excel(writer, sheet_name='Quarterly Fundamentals', index=False)
        annual_df.to_excel(writer, sheet_name='Annual Financials', index=False)
        if rf_daily is not None:
            rf_df.to_excel(writer, sheet_name='Risk-Free Rate', index=False)
        failed_df.to_excel(writer, sheet_name='Failed Tickers', index=False)
        coverage_df.to_excel(writer, sheet_name='Coverage Stats', index=False)

    size_mb = os.path.getsize(export_path) / (1024 * 1024)
    print(f"\n  Export complete:")
    print(f"    {export_path} ({size_mb:.1f} MB)")
    print(f"      - Stock Summary: {len(summary_df)} stocks")
    print(f"      - Quarterly Fundamentals: {len(quarterly_df):,} rows")
    print(f"      - Annual Financials: {len(annual_df):,} rows")
    print(f"      - Risk-Free Rate: {len(rf_df)} days")
    print(f"      - Failed Tickers: {len(failed_df)}")
    print(f"      - Coverage Stats")
    print(f"    {prices_path} ({prices_mb:.0f} MB)")
    print(f"      - Daily Prices: {len(prices_df):,} rows")


def main():
    print("=" * 70)
    print("Russell 3000 — CNE5-Style Factor Data Pipeline")
    print("10 Style Factors: size, beta, momentum, residvol, nlsize,")
    print("  btop, liquidity, earnyild, growth, leverage")
    print("=" * 70)
    print(f"Started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    if '--export' in sys.argv:
        export_raw_data_to_excel()
        return

    compute_only = '--compute-only' in sys.argv
    from_db = '--from-db' in sys.argv
    use_sectors = '--sectors' in sys.argv

    # Parse --universe / --target-days / --min-coverage flags
    universe = 'russell3000'
    target_days = 504    # default: ~2 years (matches russell3000 4-yr fetch + 2-yr regression window)
    min_coverage = 0.80  # default: 80% of universe must have data on a date
    for i, arg in enumerate(sys.argv):
        if arg == '--target-days' and i + 1 < len(sys.argv):
            target_days = int(sys.argv[i + 1])
        elif arg == '--min-coverage' and i + 1 < len(sys.argv):
            min_coverage = float(sys.argv[i + 1])
    for i, arg in enumerate(sys.argv):
        if arg == '--universe' and i + 1 < len(sys.argv):
            universe = sys.argv[i + 1]

    if from_db:
        print(f"\nFROM-DB MODE: Loading data from SQLite (universe: {universe})...")
        all_stock_data, failed, rf_daily = load_from_db(universe, use_sectors=use_sectors)
    elif not compute_only:
        print("\nLoading Russell constituents...")
        russell_df = pd.read_csv('data/input/russell_constituents.csv', sep=';')
        tickers = russell_df['Ticker'].tolist()
        tickers = [t.replace('.', '-') if '.' in t else t for t in tickers]
        sectors = dict(zip([t.replace('.', '-') if '.' in t else t for t in russell_df['Ticker'].tolist()],
                           russell_df['Sector'].tolist()))
        print(f"Found {len(tickers)} tickers\n")

        print("Fetching risk-free rate (^IRX)...")
        rf_daily = fetch_risk_free_rate(period='2y')

        print("\n" + "=" * 70)
        print("PHASE 1: FETCHING 2 YEARS OF HISTORICAL DATA")
        print("=" * 70)
        all_stock_data, failed = fetch_all_stocks(tickers, sectors, period='2y')

        pd.DataFrame({'ticker': failed}).to_csv('data/model/russell3000_failed_tickers.csv', index=False)

        print("\nSaving raw data...")
        save_raw_data(all_stock_data, failed, rf_daily)
    else:
        print("\nCOMPUTE-ONLY MODE: Loading previously fetched raw data...")
        all_stock_data, failed, rf_daily = load_raw_data()

    # Phase 2: Compute descriptors
    print("\n" + "=" * 70)
    print("PHASE 2: COMPUTING CNE5 DESCRIPTORS")
    print("=" * 70)

    # Request extra 80 dates beyond target for beta/HSIGMA warmup (EWM needs ~60)
    BETA_WARMUP = 80
    df, dates_extended = create_cross_sectional_dataset(
        all_stock_data, rf_daily,
        target_days=target_days + BETA_WARMUP,
        min_coverage=min_coverage)

    # Phase 2b: Beta + HSIGMA (computed on extended panel so warmup is available)
    df = add_beta_and_hsigma(df)

    # Trim warmup dates — keep only the last `target_days`
    dates_to_keep = sorted(df['date'].unique())[-target_days:]
    df = df[df['date'].isin(dates_to_keep)]
    dates_extended = dates_to_keep
    print(f"  Trimmed beta warmup: {len(dates_to_keep)} dates retained")

    # Phase 2c: Composites from z-scored sub-descriptors
    df = compute_composites(df)

    # Phase 2d: Z-score all main factors
    print("\nZ-scoring factors (cap-weighted mean=0, EW std=1)...")
    df = zscore_by_date(df, STYLE_FACTORS)

    # Phase 2e: Non-linear size (needs z-scored size first)
    df = add_nlsize(df)
    df = zscore_by_date(df, ['nlsize'])  # re-zscore after orthog

    # Phase 2f: Orthogonalize
    df = orthogonalize_factors(df)

    # Coverage report
    print("\nFactor coverage (% non-null):")
    for f in STYLE_FACTORS:
        raw = f"{f}_raw"
        if raw in df.columns:
            cov = df[raw].notna().mean() * 100
            print(f"  {f}: {cov:.1f}%")

    # Save factor exposures
    save_cols = ['date', 'ticker', 'sector', 'return', 'market_cap']
    for f in STYLE_FACTORS:
        save_cols.extend([f'{f}_raw', f])
    subs = ['dastd_raw', 'cmra_raw', 'hsigma_raw', 'stom_raw', 'stoq_raw', 'stoa_raw',
            'etop_raw', 'cetop_raw', 'egro_raw', 'sgro_raw', 'mlev_raw', 'dtoa_raw', 'blev_raw']
    save_cols.extend(subs)
    available = [c for c in save_cols if c in df.columns]
    exp_path = f'data/model/{universe}_factor_exposures_historical.csv'
    df[available].to_csv(exp_path, index=False)
    print(f"\nSaved factor exposures: {exp_path}")

    # Phase 3: Barra format
    print("\n" + "=" * 70)
    print("PHASE 3: CREATING BARRA-FORMAT DATA")
    print("=" * 70)

    barra_df, industry_cols, style_cols = create_barra_format(df.copy(), STYLE_FACTORS)
    cs_path = f'data/model/{universe}_cross_sectional_data.csv'
    barra_df.to_csv(cs_path, index=False)
    print(f"Saved: {cs_path}")
    print(f"  Shape: {barra_df.shape}")
    print(f"  Dates: {barra_df['date'].nunique()}")
    print(f"  Stocks per date: ~{len(barra_df) // max(1, barra_df['date'].nunique())}")
    print(f"  Industries: {len(industry_cols)}")
    print(f"  Style factors: {len(style_cols)}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("\nFactor z-score stats (pooled):")
    for f in STYLE_FACTORS:
        if f in barra_df.columns:
            print(f"  {f:12s}: mean={barra_df[f].mean():+.3f}, std={barra_df[f].std():.3f}")

    print(f"\n{'='*70}")
    print(f"COMPLETED at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)


if __name__ == '__main__':
    main()
