# -*- coding: utf-8 -*-
"""
Aggregate a daily Barra-format cross-sectional panel to month-end.

Input:  data/model/{universe}_cross_sectional_data.csv  (daily)
Output: data/model/{universe}_monthly_cross_sectional_data.csv  (monthly)

Aggregation logic per (ticker, calendar-month):
  - Keep the LAST trading day of the month for industry dummies and z-scored
    style factor exposures (size, beta, momentum, residvol, nlsize, btop,
    liquidity, earnyild, growth, leverage). Industries and z-scores are
    slow-moving; end-of-month snapshot is standard practice.
  - Compute the monthly return by compounding daily simple returns over
    that month: r_m = product(1 + r_d) - 1.
  - Capital = end-of-month market cap (from the last day's row).
  - Date = last trading day of the month.

Usage:
    py scripts/aggregate_panel_monthly.py --universe sp500_hist
"""
import argparse
import os
import sys
import time
import pandas as pd
import numpy as np


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--universe', required=True)
    args = p.parse_args()

    in_path = f'data/model/{args.universe}_cross_sectional_data.csv'
    out_path = f'data/model/{args.universe}_monthly_cross_sectional_data.csv'
    if not os.path.exists(in_path):
        sys.exit(f"ERROR: {in_path} not found. Run fetch_data.py first.")

    print(f"Loading {in_path}...")
    t0 = time.time()
    df = pd.read_csv(in_path)
    print(f"  Loaded: {len(df):,} rows × {len(df.columns)} cols in {time.time()-t0:.1f}s")

    df['date'] = pd.to_datetime(df['date'])
    df['ym'] = df['date'].dt.to_period('M')

    # Identify column groups
    id_cols = ['date', 'stocknames', 'ym']
    return_col = 'ret'
    capital_col = 'capital'
    factor_cols = [c for c in df.columns if c not in id_cols + [return_col, capital_col]]
    print(f"  Factor cols: {len(factor_cols)} ({factor_cols[:3]} ... {factor_cols[-3:]})")

    # Per (ticker, ym): take last day's row for everything, then replace ret with monthly compound
    print("\nAggregating to month-end (this is the slow part)...")
    t0 = time.time()
    df = df.sort_values(['stocknames', 'date'])

    # Monthly compound return: product(1 + r) - 1, per (ticker, ym)
    monthly_ret = (df.groupby(['stocknames', 'ym'])[return_col]
                     .apply(lambda s: (1.0 + s.dropna()).prod() - 1.0 if s.notna().any() else np.nan)
                     .reset_index()
                     .rename(columns={return_col: 'monthly_ret'}))

    # End-of-month snapshot rows (last trading day per ticker per ym)
    me = df.groupby(['stocknames', 'ym']).tail(1).copy()
    me = me.merge(monthly_ret, on=['stocknames', 'ym'], how='left')
    me[return_col] = me['monthly_ret']
    me = me.drop(columns=['monthly_ret', 'ym'])

    # Drop rows where monthly return couldn't be computed
    before = len(me)
    me = me.dropna(subset=[return_col])
    print(f"  Dropped {before - len(me):,} rows with missing monthly return")
    print(f"  Aggregation took {time.time()-t0:.1f}s")

    # Sort by date, ticker for predictable output
    me = me.sort_values(['date', 'stocknames']).reset_index(drop=True)

    # Coverage report
    me['date'] = pd.to_datetime(me['date'])
    n_dates = me['date'].nunique()
    n_tickers = me['stocknames'].nunique()
    n_per_date = len(me) // max(n_dates, 1)
    date_min = me['date'].min().date()
    date_max = me['date'].max().date()
    print(f"\n=== Output ===")
    print(f"  Rows: {len(me):,}")
    print(f"  Months: {n_dates}  ({date_min} -> {date_max})")
    print(f"  Tickers: {n_tickers}")
    print(f"  Avg tickers/month: {n_per_date}")
    print(f"  Monthly return stats: mean={me[return_col].mean()*100:+.2f}%, "
          f"std={me[return_col].std()*100:.2f}%, "
          f"min={me[return_col].min()*100:+.1f}%, "
          f"max={me[return_col].max()*100:+.1f}%")

    me.to_csv(out_path, index=False)
    print(f"\n  Saved: {out_path} ({os.path.getsize(out_path)/1e6:.1f} MB)")


if __name__ == '__main__':
    main()
