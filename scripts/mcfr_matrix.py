# -*- coding: utf-8 -*-
"""
Joint Stock x Factor MCFR matrix.

Shows, for each stock in your portfolio, its dollar-weighted contribution
to each individual factor's risk. Sums:
    sum over factors k for one stock = stock's total contribution to portfolio factor vol
    sum over stocks i for one factor = factor's MCFR (matches manage_risk.py Table 1)
    sum over both = total portfolio factor vol

Decomposition:
    M[i, k] = w_i * beta_{i,k} * (Omega_f @ b)_k / factor_vol

where b = B' w is the portfolio's factor exposure vector.

Usage: py scripts/mcfr_matrix.py <portfolio.csv> [--top N]
"""
import argparse
import os
import sys
import sqlite3
import numpy as np
import pandas as pd
import warnings

warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(__file__))


def load_portfolio(filepath):
    with open(filepath, 'r') as f:
        lines = [l for l in f if not l.startswith(('<<<<<<<', '=======', '>>>>>>>'))]
    delim = ';' if ';' in lines[0] else ','
    from io import StringIO
    df = pd.read_csv(StringIO(''.join(lines)), sep=delim)
    df.columns = df.columns.str.lower().str.strip()
    tcol = next(c for c in df.columns if 'ticker' in c.lower())
    scol = next(c for c in df.columns if 'share' in c.lower())
    df = df.rename(columns={tcol: 'ticker', scol: 'shares'})
    df = df[df['ticker'].apply(lambda x: isinstance(x, str) and x.lower() != 'ticker')]
    df['shares'] = pd.to_numeric(df['shares'], errors='coerce')
    return df.dropna(subset=['shares'])[['ticker', 'shares']]


def get_weights(portfolio_df):
    db = sqlite3.connect(os.path.join(os.path.dirname(__file__), '..', 'data', 'db', 'market_data.db'))
    rows = []
    for _, r in portfolio_df.iterrows():
        p = db.execute('SELECT close FROM daily_prices WHERE ticker=? ORDER BY date DESC LIMIT 1',
                       (r['ticker'],)).fetchone()
        if p and p[0] > 0:
            rows.append({'ticker': r['ticker'], 'shares': r['shares'],
                         'price': p[0], 'value': r['shares'] * p[0]})
    db.close()
    df = pd.DataFrame(rows)
    df['weight'] = df['value'] / df['value'].sum()
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('portfolio')
    ap.add_argument('--exposures', default='data/model/russell3000_factor_exposures_historical.csv')
    ap.add_argument('--cov',       default='data/model/barra_factor_covariance.csv')
    ap.add_argument('--top', type=int, default=None,
                    help='Show only the top-N (stock, factor) cells by |M|')
    args = ap.parse_args()

    print(f"Loading portfolio: {args.portfolio}")
    portfolio = load_portfolio(args.portfolio)
    weights_df = get_weights(portfolio)
    print(f"  {len(weights_df)} priced positions, GMV = ${weights_df['value'].sum():,.0f}")

    print(f"Loading factor exposures: {args.exposures}")
    exp_df = pd.read_csv(args.exposures)
    latest = exp_df['date'].max()
    exp_latest = exp_df[exp_df['date'] == latest]
    print(f"  Using snapshot date: {latest}")

    print(f"Loading factor covariance: {args.cov}")
    cov = pd.read_csv(args.cov, index_col=0)
    factors = cov.columns.tolist()
    style_factors = ['size', 'beta', 'momentum', 'residvol', 'nlsize',
                     'btop', 'liquidity', 'earnyild', 'growth', 'leverage']
    industry_factors = [f for f in factors if f not in style_factors + ['Country']]

    # Build B matrix (rows = stocks, cols = factors), with Country=1, industry one-hot, styles z-scored
    tickers = weights_df['ticker'].tolist()
    B = pd.DataFrame(0.0, index=tickers, columns=factors)
    matched = []
    for t in tickers:
        row = exp_latest[exp_latest['ticker'] == t]
        if row.empty:
            continue
        row = row.iloc[0]
        B.loc[t, 'Country'] = 1.0
        sector = row.get('sector')
        if sector in industry_factors:
            B.loc[t, sector] = 1.0
        for f in style_factors:
            if f in row.index and pd.notna(row[f]):
                B.loc[t, f] = float(row[f])
        matched.append(t)

    print(f"  Matched {len(matched)}/{len(tickers)} stocks; missing {set(tickers)-set(matched)}")
    B = B.loc[matched]
    w = weights_df.set_index('ticker').loc[matched, 'weight'].values

    # Renormalize weights for matched stocks (so they sum to 1)
    w = w / w.sum()
    weights_df = weights_df.set_index('ticker').loc[matched]
    weights_df['weight_renorm'] = w

    # Compute MCFR matrix.
    # NOTE: the saved factor covariance is in DAILY units. Multiply by 252 to annualize variance.
    PERIODS_PER_YEAR = 252
    Omega = cov.values * PERIODS_PER_YEAR       # annualized factor covariance
    b = B.values.T @ w                          # portfolio factor exposure vector (K,)
    factor_var = b @ Omega @ b                  # annualized factor variance
    factor_vol = np.sqrt(factor_var)            # annualized factor vol
    Omega_b = Omega @ b                         # marginal-risk vector per unit factor exposure

    # M[i,k] = w_i * beta_{i,k} * (Omega @ b)_k / factor_vol
    # In bps of portfolio factor vol
    M = (np.diag(w) @ B.values) * Omega_b[None, :] / factor_vol  # (N, K)
    M_bps = pd.DataFrame(M * 10000, index=B.index, columns=B.columns)  # x10000 -> bps of factor vol

    # Print summary
    print(f"\n  Portfolio factor variance: {factor_var:.6f}")
    print(f"  Portfolio factor vol (annualized assumed):  {factor_vol*100:.2f}%")
    print(f"  Sum of all M cells (sanity, should = factor_vol*10000): {M_bps.values.sum():.0f} bps")

    # Print the matrix (compact)
    pd.set_option('display.width', 220)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.float_format', '{:+.1f}'.format)

    # Order stocks by GMV (descending)
    stock_order = weights_df['value'].sort_values(ascending=False).index
    M_bps = M_bps.loc[stock_order]

    # Order columns: Country, then styles, then industries
    col_order = ['Country'] + style_factors + sorted(industry_factors)
    col_order = [c for c in col_order if c in M_bps.columns]
    M_bps = M_bps[col_order]

    # Drop industry columns where all values are ~0 (clutter reduction)
    used_cols = [c for c in M_bps.columns
                 if c in ['Country'] + style_factors or M_bps[c].abs().max() > 0.5]
    M_bps_show = M_bps[used_cols]

    print(f"\n=== Joint MCFR matrix (units: bps of portfolio factor vol; only non-zero industries shown) ===")
    print(M_bps_show.round(1).to_string())

    print(f"\n=== Per-stock totals (= sum across factors, matches manage_risk.py per-stock MCFR style) ===")
    per_stock = M_bps.sum(axis=1).sort_values(ascending=False)
    for t, v in per_stock.items():
        wt = weights_df.loc[t, 'weight_renorm'] * 100
        print(f"  {t:8s}: {v:+7.1f} bps   (weight = {wt:5.1f}%)")

    print(f"\n=== Per-factor totals (= sum across stocks, matches manage_risk.py Table 1) ===")
    per_factor = M_bps.sum(axis=0).sort_values(key=lambda s: s.abs(), ascending=False)
    for f, v in per_factor.items():
        if abs(v) < 0.5: continue
        print(f"  {f:35s}: {v:+7.1f} bps")

    if args.top:
        print(f"\n=== Top-{args.top} (stock, factor) cells by absolute risk contribution ===")
        cells = []
        for i in M_bps.index:
            for c in M_bps.columns:
                cells.append((i, c, M_bps.loc[i, c]))
        cells.sort(key=lambda x: abs(x[2]), reverse=True)
        for i, c, v in cells[:args.top]:
            print(f"  {i:8s} x {c:40s}: {v:+7.1f} bps")


if __name__ == '__main__':
    main()
