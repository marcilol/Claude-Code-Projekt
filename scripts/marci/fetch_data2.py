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
    python scripts/fetch_data.py            # Full fetch + compute
    python scripts/fetch_data.py --compute-only  # Recompute from saved raw data
    python scripts/fetch_data.py --export   # Export raw data to Excel for QC
"""

import yfinance as yf
import pandas as pd
import numpy as np
import pickle
import time
import os
import warnings
import sys
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed

warnings.filterwarnings('ignore')

RAW_DATA_PATH = 'data/model/russell3000_raw_data.pkl'
STYLE_FACTORS = ['size', 'beta', 'momentum', 'residvol', 'nlsize', 'btop',
                 'liquidity', 'earnyild', 'growth', 'leverage']

# Parallelism settings
FETCH_WORKERS   = 32              # parallel yfinance HTTP threads
COMPUTE_WORKERS = os.cpu_count() or 4   # parallel descriptor processes


# =============================================================================
# FETCH LAYER
# =============================================================================

def fetch_risk_free_rate(period='2y'):
    """Fetch 13-week T-bill rate (^IRX) as daily risk-free rate."""
    try:
        irx  = yf.Ticker('^IRX')
        hist = irx.history(period=period)
        if len(hist) > 0:
            rf = hist['Close'] / 100 / 252
            rf.name = 'rf'
            print(f"  Risk-free rate: {len(rf)} days, latest={rf.iloc[-1]*252*100:.2f}% ann.")
            return rf
    except Exception:
        pass
    print("  WARNING: Could not fetch risk-free rate, using 0")
    return None


def _fetch_one(args):
    """Fetch a single ticker — runs in a thread pool (no sleep needed)."""
    ticker, sector, period = args
    try:
        stock = yf.Ticker(ticker)
        hist  = stock.history(period=period)
        if len(hist) < 252:
            return None

        shares = stock.info.get('sharesOutstanding', np.nan)
        q      = {}

        def _get_row(df, labels):
            for label in labels:
                if label in df.index:
                    return df.loc[label].dropna().to_dict()
            return {}

        # Balance sheet
        try:
            bs = stock.quarterly_balance_sheet
            if bs is not None and not bs.empty:
                q['book_equity']      = _get_row(bs, ['Stockholders Equity',
                    'Total Stockholders Equity',
                    'Total Equity Gross Minority Interest', 'Common Stock Equity'])
                q['long_term_debt']   = _get_row(bs, ['Long Term Debt',
                    'Long Term Debt And Capital Lease Obligation'])
                q['total_assets']     = _get_row(bs, ['Total Assets'])
                q['preferred_equity'] = _get_row(bs, ['Preferred Stock', 'Preferred Stock Equity'])
                if 'Total Debt' in bs.index:
                    q['total_debt'] = bs.loc['Total Debt'].dropna().to_dict()
                else:
                    cd  = _get_row(bs, ['Current Debt', 'Current Debt And Capital Lease Obligation'])
                    ltd = q['long_term_debt']
                    q['total_debt'] = ({d: cd.get(d, 0) + ltd.get(d, 0)
                                        for d in set(list(cd) + list(ltd))}
                                       if cd and ltd else {})
            else:
                for k in ['book_equity','long_term_debt','total_debt','total_assets','preferred_equity']:
                    q[k] = {}
        except Exception:
            for k in ['book_equity','long_term_debt','total_debt','total_assets','preferred_equity']:
                q[k] = {}

        # Income statement
        try:
            inc = stock.quarterly_income_stmt
            if inc is not None and not inc.empty:
                q['net_income']   = _get_row(inc, ['Net Income', 'Net Income Common Stockholders'])
                q['depreciation'] = _get_row(inc, [
                    'Depreciation And Amortization In Income Statement',
                    'Depreciation And Amortization', 'Reconciled Depreciation'])
                q['revenue']      = _get_row(inc, ['Total Revenue', 'Operating Revenue'])
            else:
                for k in ['net_income','depreciation','revenue']:
                    q[k] = {}
        except Exception:
            for k in ['net_income','depreciation','revenue']:
                q[k] = {}

        # Annual
        try:
            ann = stock.income_stmt
            if ann is not None and not ann.empty:
                q['annual_eps']     = _get_row(ann, ['Basic EPS', 'Diluted EPS'])
                q['annual_revenue'] = _get_row(ann, ['Total Revenue', 'Operating Revenue'])
            else:
                q['annual_eps'] = q['annual_revenue'] = {}
        except Exception:
            q['annual_eps'] = q['annual_revenue'] = {}

        return {'ticker': ticker, 'sector': sector,
                'history': hist, 'shares_outstanding': shares, 'quarterly': q}
    except Exception:
        return None


def fetch_all_stocks(tickers, sectors, period='2y'):
    """Parallel yfinance fetch — no sleep() required between requests."""
    args  = [(t, sectors.get(t, 'Unknown'), period) for t in tickers]
    total = len(args)
    results, failed = [], []

    print(f"Fetching {total} tickers with {FETCH_WORKERS} threads...")
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as ex:
        futs = {ex.submit(_fetch_one, a): a[0] for a in args}
        done = 0
        for fut in as_completed(futs):
            done  += 1
            ticker = futs[fut]
            data   = fut.result()
            if data:
                results.append(data)
            else:
                failed.append(ticker)
            if done % 100 == 0 or done == total:
                elapsed = time.time() - t0
                rate    = done / elapsed
                eta     = (total - done) / rate / 60 if rate else 0
                print(f"  [{done}/{total}]  ok={len(results)}  fail={len(failed)}"
                      f"  eta≈{eta:.1f} min", flush=True)

    print(f"\nFetch done in {(time.time()-t0)/60:.1f} min — "
          f"{len(results)} ok / {len(failed)} failed")
    return results, failed


# =============================================================================
# FUNDAMENTAL HELPERS  (pre-sorted arrays for O(log n) lookup)
# =============================================================================

def _build_sorted(quarterly_data):
    """Pre-sort a quarterly dict into parallel timestamp / value numpy arrays."""
    if not quarterly_data:
        return np.array([], dtype='datetime64[ns]'), np.array([], dtype=float)
    items = [(pd.Timestamp(d).to_datetime64(), v)
             for d, v in quarterly_data.items() if pd.notna(v)]
    if not items:
        return np.array([], dtype='datetime64[ns]'), np.array([], dtype=float)
    items.sort(key=lambda x: x[0])
    return (np.array([x[0] for x in items], dtype='datetime64[ns]'),
            np.array([x[1] for x in items], dtype=float))


def _last_known(ts64, dates_arr, vals_arr):
    """Binary-search last known value as of ts64 — O(log n)."""
    if len(dates_arr) == 0:
        return np.nan
    idx = np.searchsorted(dates_arr, ts64, side='right') - 1
    return float(vals_arr[idx]) if idx >= 0 else np.nan


def _growth_slope(dates_arr, vals_arr, ts64, n_years=5):
    """Regression-based growth slope using pre-sorted arrays."""
    if len(dates_arr) == 0:
        return np.nan
    idx  = np.searchsorted(dates_arr, ts64, side='right')
    vals = vals_arr[:idx][-n_years:]
    if len(vals) < 3:
        return np.nan
    mean_abs = np.mean(np.abs(vals))
    if mean_abs == 0:
        return np.nan
    x   = np.arange(len(vals), dtype=float)
    x_c = x - x.mean()
    return float(np.sum(x_c * vals) / np.sum(x_c ** 2) / mean_abs)


# =============================================================================
# DESCRIPTOR COMPUTATION  (per stock, parallelised across stocks)
# =============================================================================

def compute_stock_descriptors(stock_data, dates, rf_arr, rf_dates):
    """
    Compute CNE5 descriptors for one stock across all dates.
    rf_arr / rf_dates are numpy arrays for fast binary-search RF lookup.
    """
    hist   = stock_data['history'].copy()
    ticker = stock_data['ticker']
    shares = stock_data['shares_outstanding']
    q      = stock_data.get('quarterly', {})

    # Pre-sort all fundamental series once per stock
    sq = {k: _build_sorted(q.get(k, {})) for k in [
        'book_equity','long_term_debt','total_debt','total_assets',
        'preferred_equity','net_income','depreciation','revenue',
        'annual_eps','annual_revenue']}

    # ── Returns ──────────────────────────────────────────────────────────────
    hist['return']     = hist['Close'].pct_change()
    hist['log_return'] = np.log(hist['Close'] / hist['Close'].shift(1))

    # RF merge (vectorised binary search)
    if rf_arr is not None and len(rf_arr):
        idx_naive = hist.index
        if idx_naive.tzinfo is not None:
            idx_naive = idx_naive.tz_localize(None)
        hist_ts64 = idx_naive.values.astype('datetime64[ns]')
        idxs      = np.searchsorted(rf_dates, hist_ts64, side='right') - 1
        rf_vals   = np.where(idxs >= 0, rf_arr[np.clip(idxs, 0, len(rf_arr)-1)], 0.0)
        hist['rf'] = rf_vals
    else:
        hist['rf'] = 0.0

    hist['excess_return']     = hist['return']     - hist['rf']
    hist['excess_log_return'] = hist['log_return'] - hist['rf']

    # ── Vectorised price-based descriptors ───────────────────────────────────
    hist['dastd'] = hist['excess_return'].ewm(halflife=42,  min_periods=60).std()
    hist['rstr']  = hist['excess_log_return'].shift(21).ewm(halflife=126, min_periods=126).mean()

    # CMRA: cumulative range over 12 monthly windows
    z_cols = [f'_z_{T}' for T in range(1, 13)]
    for T, col in zip(range(1, 13), z_cols):
        hist[col] = hist['excess_log_return'].rolling(
            T * 21, min_periods=max(T * 15, 10)).sum()
    z_mat        = hist[z_cols].values
    hist['cmra'] = (np.log(np.nanmax(z_mat, axis=1).clip(min=-0.99) + 1) -
                    np.log(np.nanmin(z_mat, axis=1).clip(min=-0.99) + 1))
    hist.drop(columns=z_cols, inplace=True)

    # Turnover
    if pd.notna(shares) and shares > 0:
        tv = hist['Volume'] / shares
        hist['stom'] = np.log(tv.rolling(21,  min_periods=15).sum().clip(lower=1e-12))
        hist['stoq'] = np.log((tv.rolling(63,  min_periods=42).sum() / 3).clip(lower=1e-12))
        hist['stoa'] = np.log((tv.rolling(252, min_periods=126).sum() / 12).clip(lower=1e-12))
    else:
        hist['stom'] = hist['stoq'] = hist['stoa'] = np.nan

    # Strip tz for date comparisons
    hist_naive = hist.copy()
    if hist_naive.index.tzinfo is not None:
        hist_naive.index = hist_naive.index.tz_localize(None)

    # ── Per-date sampling + fundamental lookups ───────────────────────────────
    records = []
    for date in dates:
        ts   = pd.Timestamp(date)
        ts64 = np.datetime64(date, 'ns')

        sub = hist_naive[hist_naive.index <= ts]
        if len(sub) < 61:
            continue

        last = sub.iloc[-1]
        prev = sub.iloc[-2]

        daily_return = last['log_return']
        if pd.isna(daily_return):
            continue

        mc    = prev['Close'] * shares if pd.notna(shares) and shares > 0 else np.nan
        mc_ok = pd.notna(mc) and mc > 0

        bv  = _last_known(ts64, *sq['book_equity'])
        ni  = _last_known(ts64, *sq['net_income'])
        dep = _last_known(ts64, *sq['depreciation'])
        ld  = _last_known(ts64, *sq['long_term_debt'])
        td  = _last_known(ts64, *sq['total_debt'])
        ta  = _last_known(ts64, *sq['total_assets'])
        pe  = _last_known(ts64, *sq['preferred_equity'])
        pe  = 0.0 if np.isnan(pe) else pe

        records.append({
            'date':         date,
            'ticker':       ticker,
            'return':       daily_return,
            'rf':           float(prev['rf']),
            'market_cap':   mc,
            'size_raw':     np.log(mc) if mc_ok else np.nan,
            'momentum_raw': float(prev.get('rstr', np.nan)),
            'dastd_raw':    float(prev.get('dastd', np.nan)),
            'cmra_raw':     float(prev.get('cmra',  np.nan)),
            'stom_raw':     float(prev.get('stom',  np.nan)),
            'stoq_raw':     float(prev.get('stoq',  np.nan)),
            'stoa_raw':     float(prev.get('stoa',  np.nan)),
            'btop_raw':     bv / mc  if mc_ok and pd.notna(bv) else np.nan,
            'etop_raw':     (ni * 4) / mc if mc_ok and pd.notna(ni) else np.nan,
            'cetop_raw':    ((ni + dep) * 4) / mc
                            if mc_ok and pd.notna(ni) and pd.notna(dep) else np.nan,
            'egro_raw':     _growth_slope(*sq['annual_eps'],     ts64),
            'sgro_raw':     _growth_slope(*sq['annual_revenue'],  ts64),
            'mlev_raw':     (mc + pe + ld) / mc if mc_ok and pd.notna(ld) else np.nan,
            'dtoa_raw':     td / ta if pd.notna(td) and pd.notna(ta) and ta > 0 else np.nan,
            'blev_raw':     (bv + pe + ld) / bv
                            if pd.notna(bv) and bv > 0 and pd.notna(ld) else np.nan,
        })

    return pd.DataFrame(records)


# Process-pool globals (set once per worker process)
_DATES = _RF_ARR = _RF_DATES = None

def _worker_init(dates_, rf_arr_, rf_dates_):
    global _DATES, _RF_ARR, _RF_DATES
    _DATES, _RF_ARR, _RF_DATES = dates_, rf_arr_, rf_dates_


def _worker_call(stock_data):
    return compute_stock_descriptors(stock_data, _DATES, _RF_ARR, _RF_DATES)


def create_cross_sectional_dataset(all_stock_data, rf_series, target_days=504):
    """Parallel descriptor computation across all stocks."""
    print("\nDetermining common trading dates...")
    all_dates = None
    for sd in all_stock_data:
        idx = pd.DatetimeIndex(sd['history'].index)
        if idx.tzinfo is not None:
            idx = idx.tz_localize(None)
        s = set(idx.strftime('%Y-%m-%d'))
        all_dates = s if all_dates is None else all_dates & s

    all_dates = sorted(all_dates)[-target_days:]
    print(f"  {len(all_dates)} dates  [{all_dates[0]} → {all_dates[-1]}]")

    # Build RF numpy arrays once (shared read-only across processes)
    if rf_series is not None:
        rf_idx = rf_series.index
        if rf_idx.tzinfo is not None:
            rf_idx = rf_idx.tz_localize(None)
        rf_dates = rf_idx.values.astype('datetime64[ns]')
        rf_arr   = rf_series.values.astype(float)
    else:
        rf_dates = rf_arr = None

    ticker_sector = {sd['ticker']: sd['sector'] for sd in all_stock_data}
    n = len(all_stock_data)
    print(f"\nComputing descriptors for {n} stocks using {COMPUTE_WORKERS} processes...")
    t0 = time.time()

    all_records = []
    with ProcessPoolExecutor(
            max_workers=COMPUTE_WORKERS,
            initializer=_worker_init,
            initargs=(all_dates, rf_arr, rf_dates)) as ex:
        futs = {ex.submit(_worker_call, sd): sd['ticker'] for sd in all_stock_data}
        done = 0
        for fut in as_completed(futs):
            done   += 1
            ticker  = futs[fut]
            df_s    = fut.result()
            if df_s is not None and not df_s.empty:
                df_s['sector'] = ticker_sector.get(ticker, 'Unknown')
                all_records.append(df_s)
            if done % 200 == 0 or done == n:
                print(f"  {done}/{n} stocks  ({(time.time()-t0)/60:.1f} min)", flush=True)

    df = pd.concat(all_records, ignore_index=True)
    print(f"\n  {len(df):,} records | {df['date'].nunique()} dates | "
          f"{df['ticker'].nunique()} stocks | "
          f"{(time.time()-t0)/60:.1f} min")
    return df, all_dates


# =============================================================================
# BETA + HSIGMA  (vectorised pivot — no per-ticker Python loop)
# =============================================================================

def add_beta_and_hsigma(df):
    """
    Vectorised EWM beta and HSIGMA via wide pivot.
    Avoids a slow Python loop over 3000 tickers.
    """
    print("\nComputing beta and HSIGMA (vectorised)...")
    t0 = time.time()

    df   = df.copy()
    rf   = df['rf'].fillna(0)
    df['xs'] = df['return'] - rf

    # Cap-weighted market excess return per date
    def cw_ret(g):
        w = g['market_cap'].clip(lower=0)
        s = w.sum()
        return (g['xs'] * w / s).sum() if s > 0 else np.nan

    mkt = df.groupby('date')['xs market_cap'.split()].apply(
        lambda g: (g['xs'] * g['market_cap'].clip(lower=0) /
                   g['market_cap'].clip(lower=0).sum()).sum()
    ).rename('mkt_xs')
    df = df.join(mkt, on='date')

    # Wide matrices: rows=date, cols=ticker
    ret_w = df.pivot(index='date', columns='ticker', values='xs')
    mkt_s = df.groupby('date')['mkt_xs'].first().reindex(ret_w.index)

    ewm_kw     = dict(halflife=63, min_periods=60)
    ewm_var    = mkt_s.ewm(**ewm_kw).var()

    beta_cols   = {}
    hsigma_cols = {}
    for ticker in ret_w.columns:
        s         = ret_w[ticker]
        cov       = s.ewm(**ewm_kw).cov(mkt_s)
        b         = cov / ewm_var
        resid     = s - b * mkt_s
        beta_cols[ticker]   = b
        hsigma_cols[ticker] = resid.ewm(**ewm_kw).std()

    beta_wide   = pd.DataFrame(beta_cols,   index=ret_w.index)
    hsigma_wide = pd.DataFrame(hsigma_cols, index=ret_w.index)

    beta_long   = (beta_wide.reset_index()
                   .melt(id_vars='date', value_name='beta_raw'))
    hsigma_long = (hsigma_wide.reset_index()
                   .melt(id_vars='date', value_name='hsigma_raw'))

    df = (df.merge(beta_long,   on=['date','ticker'], how='left')
            .merge(hsigma_long, on=['date','ticker'], how='left'))
    df.drop(columns=['mkt_xs','xs'], inplace=True)

    print(f"  Beta coverage:   {df['beta_raw'].notna().mean()*100:.1f}%")
    print(f"  HSIGMA coverage: {df['hsigma_raw'].notna().mean()*100:.1f}%")
    print(f"  Beta time: {time.time()-t0:.1f}s")
    return df


# =============================================================================
# CROSS-SECTIONAL Z-SCORE  (fully vectorised — no groupby + concat loop)
# =============================================================================

def _cs_zscore_vec(df, raw_col, cap_col='market_cap'):
    """
    Cap-weighted-mean / EW-std z-score across all dates at once.
    Uses numpy factorize + loop over unique date codes (integers) — much faster
    than pandas groupby + pd.concat on large frames.
    """
    vals      = df[raw_col].values.astype(float)
    caps      = df[cap_col].values.astype(float)
    date_codes, _ = pd.factorize(df['date'], sort=True)

    out = np.full(len(df), np.nan)
    for d in np.unique(date_codes):
        mask = date_codes == d
        v    = vals[mask]
        c    = caps[mask]
        ok   = np.isfinite(v) & np.isfinite(c) & (c > 0)
        if ok.sum() < 10:
            continue
        w       = c[ok] / c[ok].sum()
        mu      = float((w * v[ok]).sum())
        sigma   = float(v[ok].std())
        if sigma == 0:
            continue
        z        = np.full(mask.sum(), np.nan)
        z[ok]    = (v[ok] - mu) / sigma
        out[mask] = z
    return pd.Series(out, index=df.index)


def compute_composites(df):
    """Compute CNE5 composite factors (vectorised z-score of sub-descriptors)."""
    print("\nComputing composite factors...")

    for col in ['dastd','cmra','hsigma','stom','stoq','stoa',
                'etop','cetop','egro','sgro','mlev','dtoa','blev']:
        raw = f'{col}_raw'
        if raw in df.columns:
            df[col] = _cs_zscore_vec(df, raw)

    df['residvol_raw']  = (0.74*df['dastd'].fillna(0) + 0.16*df['cmra'].fillna(0)
                           + 0.10*df['hsigma'].fillna(0))
    df['liquidity_raw'] = (0.35*df['stom'].fillna(0) + 0.35*df['stoq'].fillna(0)
                           + 0.30*df['stoa'].fillna(0))
    df['earnyild_raw']  = (0.656*df['cetop'].fillna(0) + 0.344*df['etop'].fillna(0))
    df['growth_raw']    = (0.338*df['egro'].fillna(0)  + 0.662*df['sgro'].fillna(0))
    df['leverage_raw']  = (0.38*df['mlev'].fillna(0)   + 0.35*df['dtoa'].fillna(0)
                           + 0.27*df['blev'].fillna(0))
    return df


def zscore_by_date(df, columns):
    """Vectorised cross-sectional z-score for a list of factor columns."""
    for col in columns:
        raw_col = f"{col}_raw"
        if raw_col in df.columns:
            df[col] = _cs_zscore_vec(df, raw_col)
    return df


def add_nlsize(df):
    """Non-linear Size: cube of z-scored size, cross-sectionally orthogonalised vs size."""
    print("  Computing non-linear size...")
    df['nlsize_raw'] = df['size'] ** 3

    date_codes, uniq = pd.factorize(df['date'], sort=True)
    nlsize = df['nlsize_raw'].values.copy().astype(float)
    size_v = df['size'].values.astype(float)

    for i in range(len(uniq)):
        mask = date_codes == i
        nl   = nlsize[mask]
        sz   = size_v[mask]
        ok   = np.isfinite(nl) & np.isfinite(sz)
        if ok.sum() > 10:
            X = np.column_stack([np.ones(ok.sum()), sz[ok]])
            y = nl[ok]
            try:
                coef      = np.linalg.lstsq(X, y, rcond=None)[0]
                tmp       = nl.copy()
                tmp[ok]   = y - X @ coef
                nlsize[mask] = tmp
            except Exception:
                pass

    df['nlsize_raw'] = nlsize
    return df


def orthogonalize_factors(df):
    """Vectorised cross-sectional orthogonalisation (no groupby + concat)."""
    print("\nOrthogonalizing factors...")

    date_codes, uniq = pd.factorize(df['date'], sort=True)

    def _orth_col(target, regressors):
        out  = df[target].values.copy().astype(float)
        rvs  = [df[r].values.astype(float) for r in regressors]
        for i in range(len(uniq)):
            mask = date_codes == i
            y    = out[mask]
            ok   = np.isfinite(y)
            for rv in rvs:
                ok &= np.isfinite(rv[mask])
            if ok.sum() <= len(regressors) + 1:
                continue
            X = np.column_stack([np.ones(ok.sum())] + [rv[mask][ok] for rv in rvs])
            ys = y[ok]
            try:
                coef  = np.linalg.lstsq(X, ys, rcond=None)[0]
                resid = ys - X @ coef
                std   = resid.std()
                if std > 0:
                    tmp      = out[mask].copy()
                    tmp[ok]  = (resid - resid.mean()) / std
                    out[mask] = tmp
            except Exception:
                pass
        return out

    df['residvol']  = _orth_col('residvol',  ['beta', 'size'])
    df['liquidity'] = _orth_col('liquidity', ['size'])
    print("  Done: residvol ⊥ (beta, size)  |  liquidity ⊥ size")
    return df


# =============================================================================
# BARRA FORMAT
# =============================================================================

def create_barra_format(df, style_cols):
    sectors = sorted([s for s in df['sector'].dropna().unique()
                      if s not in ['Unknown','Cash and/or Derivatives','Other','']])
    print(f"\nCreating Barra format with {len(sectors)} industries...")

    dummies = pd.get_dummies(df['sector']).reindex(columns=sectors, fill_value=0)
    df      = pd.concat([df, dummies], axis=1)
    df      = df.rename(columns={'ticker':'stocknames','return':'ret','market_cap':'capital'})

    final_cols = [c for c in ['date','stocknames','capital','ret'] + sectors + style_cols
                  if c in df.columns]
    result = df[final_cols].copy()
    for col in style_cols:
        if col in result.columns:
            result[col] = result[col].fillna(0)

    result = result.dropna(subset=['ret','capital'])
    result = result[result['capital'] > 0]
    return result, sectors, style_cols


# =============================================================================
# RAW DATA I/O
# =============================================================================

def save_raw_data(all_stock_data, failed, rf_daily=None):
    with open(RAW_DATA_PATH, 'wb') as f:
        pickle.dump({'stock_data': all_stock_data, 'failed': failed, 'rf_daily': rf_daily}, f)
    mb = os.path.getsize(RAW_DATA_PATH) / (1024*1024)
    print(f"  Saved → {RAW_DATA_PATH} ({mb:.0f} MB)")


def load_raw_data():
    if not os.path.exists(RAW_DATA_PATH):
        raise FileNotFoundError(f"No raw data at {RAW_DATA_PATH}. Run without --compute-only first.")
    with open(RAW_DATA_PATH, 'rb') as f:
        data = pickle.load(f)
    rf = data.get('rf_daily', None)
    print(f"  Loaded: {len(data['stock_data'])} stocks, {len(data['failed'])} failed")
    return data['stock_data'], data['failed'], rf


# =============================================================================
# EXPORT
# =============================================================================

def export_raw_data_to_excel():
    """Export ALL raw pickle data for quality control.

    Outputs:
      - data/model/russell3000_raw_data_qc.xlsx
      - data/model/russell3000_daily_prices.parquet
    """
    print("Loading raw data for export...")
    all_stock_data, failed, rf_daily = load_raw_data()

    export_path = 'data/model/russell3000_raw_data_qc.xlsx'
    prices_path = 'data/model/russell3000_daily_prices.parquet'

    print("  Building daily price history...")
    price_frames = []
    for sd in all_stock_data:
        hist = sd['history'][['Open','High','Low','Close','Volume']].copy()
        hist.index = hist.index.tz_localize(None) if hist.index.tzinfo else hist.index
        hist = hist.reset_index().rename(columns={'index':'date','Date':'date'})
        hist.insert(0, 'ticker', sd['ticker'])
        hist.insert(1, 'sector', sd.get('sector',''))
        hist['shares_outstanding'] = sd['shares_outstanding']
        price_frames.append(hist)

    prices_df = (pd.concat(price_frames, ignore_index=True)
                 .sort_values(['ticker','date']).reset_index(drop=True))
    prices_df.to_parquet(prices_path, index=False)
    prices_mb = os.path.getsize(prices_path) / (1024*1024)
    print(f"  Saved {len(prices_df):,} rows → {prices_path} ({prices_mb:.0f} MB)")

    # Stock summary
    print("  Building stock summary...")
    summary_rows = []
    for sd in all_stock_data:
        hist  = sd['history']
        q     = sd.get('quarterly', {})
        ts64  = np.datetime64(
            (hist.index[-1].tz_localize(None) if hist.index.tzinfo else hist.index[-1])
            .strftime('%Y-%m-%d'), 'ns')
        sq = {k: _build_sorted(q.get(k, {})) for k in
              ['book_equity','net_income','depreciation','revenue',
               'long_term_debt','total_debt','total_assets','preferred_equity',
               'annual_eps','annual_revenue']}
        row = {
            'ticker':            sd['ticker'],
            'sector':            sd.get('sector',''),
            'shares_outstanding': sd['shares_outstanding'],
            'history_start':     hist.index[0].strftime('%Y-%m-%d'),
            'history_end':       hist.index[-1].strftime('%Y-%m-%d'),
            'history_days':      len(hist),
            'latest_close':      hist['Close'].iloc[-1],
            'latest_volume':     hist['Volume'].iloc[-1],
            'market_cap':        (hist['Close'].iloc[-1] * sd['shares_outstanding']
                                  if pd.notna(sd['shares_outstanding']) else np.nan),
        }
        for key in ['book_equity','net_income','depreciation','revenue',
                    'long_term_debt','total_debt','total_assets','preferred_equity']:
            row[f'latest_{key}'] = _last_known(ts64, *sq[key])
        for key in ['annual_eps','annual_revenue']:
            row[f'{key}_years'] = len(sq[key][0])
        summary_rows.append(row)

    summary_df   = pd.DataFrame(summary_rows).sort_values('ticker').reset_index(drop=True)

    # Quarterly fundamentals
    print("  Building quarterly fundamentals...")
    qf_fields = ['book_equity','net_income','depreciation','revenue',
                 'long_term_debt','total_debt','total_assets','preferred_equity']
    qf_rows = []
    for sd in all_stock_data:
        q     = sd.get('quarterly', {})
        all_d = set()
        for field in qf_fields:
            all_d.update(q.get(field, {}).keys())
        for rd in sorted(all_d, key=lambda d: pd.Timestamp(d)):
            row = {'ticker': sd['ticker'], 'report_date': pd.Timestamp(rd).strftime('%Y-%m-%d')}
            for field in qf_fields:
                row[field] = q.get(field, {}).get(rd, np.nan)
            qf_rows.append(row)
    quarterly_df = (pd.DataFrame(qf_rows)
                    .sort_values(['ticker','report_date']).reset_index(drop=True))

    # Annual financials
    print("  Building annual financials...")
    an_rows = []
    for sd in all_stock_data:
        q     = sd.get('quarterly', {})
        all_d = set()
        for f in ['annual_eps','annual_revenue']:
            all_d.update(q.get(f, {}).keys())
        for rd in sorted(all_d, key=lambda d: pd.Timestamp(d)):
            an_rows.append({'ticker': sd['ticker'],
                            'report_date': pd.Timestamp(rd).strftime('%Y-%m-%d'),
                            'eps':     q.get('annual_eps', {}).get(rd, np.nan),
                            'revenue': q.get('annual_revenue', {}).get(rd, np.nan)})
    annual_df = (pd.DataFrame(an_rows)
                 .sort_values(['ticker','report_date']).reset_index(drop=True))

    # RF
    if rf_daily is not None:
        rf_df = rf_daily.reset_index()
        rf_df.columns = ['date','rf_daily']
        if rf_df['date'].dt.tz is not None:
            rf_df['date'] = rf_df['date'].dt.tz_localize(None)
        rf_df['rf_annualized_pct'] = rf_df['rf_daily'] * 252 * 100
    else:
        rf_df = pd.DataFrame({'note': ['No risk-free rate data available']})

    failed_df = pd.DataFrame({'ticker': sorted(failed)})

    cov_rows = []
    for col in ['shares_outstanding','latest_close','market_cap',
                'latest_book_equity','latest_net_income','latest_depreciation',
                'latest_revenue','latest_long_term_debt','latest_total_debt','latest_total_assets']:
        if col in summary_df.columns:
            s = summary_df[col]
            cov_rows.append({'field': col,
                             'count_non_null': int(s.notna().sum()),
                             'count_total': len(s),
                             'coverage_pct': round(s.notna().mean()*100, 1),
                             'min': s.min() if s.notna().any() else np.nan,
                             'median': s.median() if s.notna().any() else np.nan,
                             'max': s.max() if s.notna().any() else np.nan})
    coverage_df = pd.DataFrame(cov_rows)

    print(f"  Writing {export_path}...")
    with pd.ExcelWriter(export_path, engine='openpyxl') as writer:
        summary_df.to_excel(writer,   sheet_name='Stock Summary',          index=False)
        quarterly_df.to_excel(writer, sheet_name='Quarterly Fundamentals', index=False)
        annual_df.to_excel(writer,    sheet_name='Annual Financials',      index=False)
        if rf_daily is not None:
            rf_df.to_excel(writer,    sheet_name='Risk-Free Rate',         index=False)
        failed_df.to_excel(writer,    sheet_name='Failed Tickers',         index=False)
        coverage_df.to_excel(writer,  sheet_name='Coverage Stats',         index=False)

    size_mb = os.path.getsize(export_path) / (1024*1024)
    print(f"\n  Export complete:")
    print(f"    {export_path} ({size_mb:.1f} MB) — {len(summary_df)} stocks")
    print(f"    {prices_path} ({prices_mb:.0f} MB) — {len(prices_df):,} rows")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 70)
    print("Russell 3000 — CNE5-Style Factor Data Pipeline")
    print(f"  fetch_workers={FETCH_WORKERS}  compute_workers={COMPUTE_WORKERS}")
    print("=" * 70)
    print(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    t_total = time.time()

    if '--export' in sys.argv:
        export_raw_data_to_excel()
        return

    compute_only = '--compute-only' in sys.argv

    if not compute_only:
        print("\nLoading Russell constituents...")
        russell_df = pd.read_csv('data/input/russell_constituents.csv', sep=';')
        tickers    = [t.replace('.', '-') if '.' in t else t
                      for t in russell_df['Ticker'].tolist()]
        sectors    = dict(zip(russell_df['Ticker'], russell_df['Sector']))
        print(f"  {len(tickers)} tickers")

        print("\nFetching risk-free rate (^IRX)...")
        rf_daily = fetch_risk_free_rate(period='2y')

        print("\n" + "="*70)
        print("PHASE 1: PARALLEL FETCH")
        print("="*70)
        all_stock_data, failed = fetch_all_stocks(tickers, sectors, period='2y')
        pd.DataFrame({'ticker': failed}).to_parquet(
            'data/model/russell3000_failed_tickers.parquet', index=False)
        save_raw_data(all_stock_data, failed, rf_daily)
    else:
        print("\nCOMPUTE-ONLY: loading saved data...")
        all_stock_data, failed, rf_daily = load_raw_data()

    # Phase 2
    print("\n" + "="*70)
    print("PHASE 2: DESCRIPTOR COMPUTATION")
    print("="*70)
    df, dates = create_cross_sectional_dataset(all_stock_data, rf_daily, target_days=504)
    df        = add_beta_and_hsigma(df)
    df        = compute_composites(df)

    print("\nZ-scoring style factors...")
    df = zscore_by_date(df, STYLE_FACTORS)
    df = add_nlsize(df)
    df = zscore_by_date(df, ['nlsize'])
    df = orthogonalize_factors(df)

    print("\nFactor coverage:")
    for f in STYLE_FACTORS:
        raw = f"{f}_raw"
        if raw in df.columns:
            print(f"  {f:12s}: {df[raw].notna().mean()*100:.1f}%")

    save_cols = ['date','ticker','sector','return','market_cap']
    for f in STYLE_FACTORS:
        save_cols += [f'{f}_raw', f]
    save_cols += ['dastd_raw','cmra_raw','hsigma_raw','stom_raw','stoq_raw','stoa_raw',
                  'etop_raw','cetop_raw','egro_raw','sgro_raw','mlev_raw','dtoa_raw','blev_raw']
    available   = [c for c in save_cols if c in df.columns]
    factor_path = 'data/model/russell3000_factor_exposures_historical.parquet'
    df[available].to_parquet(factor_path, index=False)
    print(f"\nSaved factor exposures → {factor_path}")

    # Phase 3
    print("\n" + "="*70)
    print("PHASE 3: BARRA FORMAT")
    print("="*70)
    barra_df, industry_cols, style_cols = create_barra_format(df.copy(), STYLE_FACTORS)
    barra_path = 'data/model/russell3000_cross_sectional_data.parquet'
    barra_df.to_parquet(barra_path, index=False)
    print(f"Saved → {barra_path}")
    print(f"  Shape: {barra_df.shape} | Dates: {barra_df['date'].nunique()} "
          f"| Industries: {len(industry_cols)}")

    print("\nFactor z-score stats (pooled):")
    for f in STYLE_FACTORS:
        if f in barra_df.columns:
            print(f"  {f:12s}: mean={barra_df[f].mean():+.3f}  std={barra_df[f].std():.3f}")

    total_min = (time.time() - t_total) / 60
    print(f"\n{'='*70}")
    print(f"COMPLETED  {time.strftime('%Y-%m-%d %H:%M:%S')}  total={total_min:.1f} min")
    print("="*70)


if __name__ == '__main__':
    main()
