# -*- coding: utf-8 -*-
"""
Convert a multi-basket holdings CSV into one share-count portfolio CSV per basket.

Supports three weighting schemes:
  --scheme original  Use the source file's `current_day_weight_pct` column,
                     renormalized over priced names. Active holdings only.
  --scheme cap       Cap-weight by market cap (close * shares_outstanding) on
                     the basket's earliest cost_date. Includes inactives by default.
  --scheme equal     Equal-weight across all included names. Includes inactives by default.

For 'cap' and 'equal' the basket's reference date is the earliest cost_date among
ACTIVE rows; inactive rows (no cost_date) are priced as-of that same date.

Usage:
  py scripts/convert_baskets.py --scheme cap --input "data/input/portfolios/tickers_us_only (1).csv"
  py scripts/convert_baskets.py --scheme equal --input "data/input/portfolios/tickers_us_only (1).csv"
  py scripts/convert_baskets.py --scheme original --input data/input/portfolios/tickers_us_only.csv

Defaults:
  --scheme original  → out-dir = data/input/portfolios/Baskets/analyst_weighted
  --scheme cap       → out-dir = data/input/portfolios/Baskets/cap_weighted
  --scheme equal     → out-dir = data/input/portfolios/Baskets/equal_weighted

shares_i = (weight_i * nominal) / price_i
"""

import argparse
import os
import re
import sqlite3
import sys

import numpy as np
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'db', 'market_data.db')


def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_')


def get_price_shares_on_or_before(conn, ticker: str, date: str):
    """Return (close, shares_outstanding, actual_date) on/before date, or (None, None, None)."""
    row = conn.execute(
        "SELECT close, shares_out, date FROM daily_prices WHERE ticker=? AND date<=? ORDER BY date DESC LIMIT 1",
        (ticker, date),
    ).fetchone()
    if not row:
        return None, None, None
    close, shares, actual_date = row
    return close, shares, actual_date


def is_active_row(row):
    sf = str(row.get('source_file', ''))
    return 'inactive' not in sf.lower()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', default='data/input/portfolios/tickers_us_only.csv')
    p.add_argument('--out-dir', default=None,
                   help='Defaults to data/input/portfolios/Baskets/<scheme>')
    p.add_argument('--nominal', type=float, default=1_000_000)
    p.add_argument('--scheme', choices=['original', 'cap', 'equal'], default='original')
    p.add_argument('--include-inactive', action='store_true',
                   help="Include 'inactive' rows from source. Auto-on for cap/equal.")
    args = p.parse_args()

    if args.scheme in ('cap', 'equal'):
        args.include_inactive = True

    if args.out_dir is None:
        scheme_to_folder = {'original': 'analyst_weighted',
                            'cap': 'cap_weighted',
                            'equal': 'equal_weighted'}
        args.out_dir = os.path.join('data', 'input', 'portfolios',
                                    'Baskets', scheme_to_folder[args.scheme])

    df = pd.read_csv(args.input)
    required = {'ticker', 'cost_date', 'basket_name'}
    if args.scheme == 'original':
        required.add('current_day_weight_pct')
    missing = required - set(df.columns)
    if missing:
        sys.exit(f"input missing columns: {missing}")

    if not args.include_inactive:
        df = df[df.apply(is_active_row, axis=1)].copy()
        print(f"Filtered to active only: {len(df)} rows")

    os.makedirs(args.out_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)

    summary_rows = []
    for basket, g in df.groupby('basket_name', sort=False):
        # Earliest cost_date from ACTIVE rows (coerce to date so mixed str/NaN works);
        # fall back to snapshot_date if no cost_date (e.g. unweighted supply-chain maps).
        active = g[g.apply(is_active_row, axis=1)]
        valid_dates = pd.to_datetime(active['cost_date'], errors='coerce').dropna()
        if len(valid_dates) == 0 and 'snapshot_date' in active.columns:
            valid_dates = pd.to_datetime(active['snapshot_date'], errors='coerce').dropna()
        if len(valid_dates) == 0:
            print(f"  skip '{basket}': no active rows with valid cost_date or snapshot_date")
            continue
        ref_date = valid_dates.min().strftime('%Y-%m-%d')

        # Pass 1: get price + shares_out for each ticker on/before ref_date
        priced = []
        missing_tickers = []
        for _, r in g.iterrows():
            t = str(r['ticker']).strip()
            close, shares_out, actual = get_price_shares_on_or_before(conn, t, ref_date)
            if close is None or close <= 0:
                missing_tickers.append(t)
                continue
            orig_w = float(r['current_day_weight_pct']) if 'current_day_weight_pct' in r and pd.notna(r['current_day_weight_pct']) else 0.0
            mcap = close * shares_out if shares_out and shares_out > 0 else None
            priced.append({'ticker': t, 'price': close, 'shares_out': shares_out,
                           'mcap': mcap, 'orig_w': orig_w})

        if not priced:
            print(f"  skip '{basket}': no priced tickers")
            continue

        # Pass 2: compute weights per scheme
        if args.scheme == 'original':
            total_w = sum(p['orig_w'] for p in priced)
            if total_w <= 0:
                print(f"  skip '{basket}': zero weight total under 'original'")
                continue
            for p_ in priced:
                p_['weight'] = p_['orig_w'] / total_w
        elif args.scheme == 'cap':
            # Drop names with no shares_out
            with_mcap = [p_ for p_ in priced if p_['mcap'] is not None and p_['mcap'] > 0]
            no_mcap = [p_['ticker'] for p_ in priced if p_['mcap'] is None or p_['mcap'] <= 0]
            if no_mcap:
                missing_tickers += [f"{t}(no_shares_out)" for t in no_mcap]
            if not with_mcap:
                print(f"  skip '{basket}': no tickers with shares_out for cap weighting")
                continue
            total_mcap = sum(p_['mcap'] for p_ in with_mcap)
            for p_ in with_mcap:
                p_['weight'] = p_['mcap'] / total_mcap
            priced = with_mcap
        elif args.scheme == 'equal':
            n = len(priced)
            for p_ in priced:
                p_['weight'] = 1.0 / n

        rows = []
        for p_ in priced:
            dollars = args.nominal * p_['weight']
            shares = dollars / p_['price']
            rows.append({'ticker': p_['ticker'], 'shares': round(shares, 6), 'costdate': ref_date})

        slug = slugify(basket)
        out_path = os.path.join(args.out_dir, f"{slug}.csv")
        pd.DataFrame(rows).to_csv(out_path, sep=';', index=False)

        summary_rows.append({
            'basket': basket,
            'file': f"{slug}.csv",
            'n_in': len(g),
            'n_out': len(rows),
            'n_missing': len(missing_tickers),
            'ref_date': ref_date,
            'missing': ','.join(missing_tickers) if missing_tickers else '',
        })

    conn.close()

    if not summary_rows:
        sys.exit("no baskets written")

    summ = pd.DataFrame(summary_rows).sort_values('basket')
    print(summ.drop(columns=['missing']).to_string(index=False))
    print()
    any_missing = summ[summ['n_missing'] > 0]
    if len(any_missing):
        print("Tickers dropped (no price / no shares_out on/before basket cost_date):")
        for _, r in any_missing.iterrows():
            print(f"  {r['basket']}: {r['missing']}")
    print(f"\nWrote {len(summ)} basket files to {args.out_dir} (scheme={args.scheme}, nominal=${args.nominal:,.0f})")


if __name__ == '__main__':
    main()
