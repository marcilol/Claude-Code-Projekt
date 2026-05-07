# -*- coding: utf-8 -*-
"""
Build a 10-year US factor model with reduced survivorship bias.

Workflow:
  1. Bulk EOD snapshot for 2016-01-15 (one API call).
  2. Cross-reference with us_common (active + delisted common stocks already
     in DB, with ADRs/funds/SPACs/units pre-filtered) and apply price + dollar-
     volume thresholds.
  3. Add the resulting tickers as a new universe `us_10yr`.
  4. Pull 10yr daily prices + fundamentals for those tickers.
  5. Extend risk-free rate history to 10 years.

After this script finishes, run:
    py scripts/fetch_data.py --from-db --universe us_10yr --years 10
    py scripts/run_factor_model.py --universe us_10yr

Resumable: skips tickers already in DB.

Usage: py scripts/build_us_10yr.py [--snapshot-date 2016-01-15]
                                    [--min-price 5] [--min-dollar-vol 1000000]
                                    [--years 10]
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(__file__))
from data_manager import MarketDB
from data_sources import _safe_num

API_KEY = os.getenv('EODHD_API_KEY') or os.getenv('EODHD_TOKEN')
LOG_FILE = 'data/db/build_us_10yr.log'
REQUEST_DELAY = 0.15
UNIVERSE_NAME = 'us_10yr'


def log(msg, also_print=True):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    if also_print:
        print(line, flush=True)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def get(url, retries=3):
    last = None
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:
            last = e
            wait = 5 * (attempt + 1)
            log(f"    request failed ({type(e).__name__}); retry in {wait}s")
            time.sleep(wait)
    raise last


def snapshot_and_filter(snap_date, min_price, min_dvol, db):
    """Return list of tickers passing filters as-of snap_date."""
    log(f"PHASE 1: Bulk EOD snapshot for {snap_date}")
    url = f'https://eodhd.com/api/eod-bulk-last-day/US?api_token={API_KEY}&date={snap_date}&fmt=json'
    bulk = get(url)
    df = pd.DataFrame(bulk)
    log(f"  Bulk returned {len(df)} US tickers")

    # Cross-reference with us_common (filtered common stocks, no ADRs/funds)
    rows = db.conn.execute(
        "SELECT s.ticker FROM stocks s JOIN universes u ON u.id=s.universe_id WHERE u.name='us_common'"
    ).fetchall()
    us_common = {r[0] for r in rows}
    log(f"  us_common universe has {len(us_common)} tickers")

    # Apply filters
    df['dollar_vol'] = df['close'] * df['volume']
    pre = len(df)
    df = df[df['code'].isin(us_common)]
    log(f"  Cross-ref with us_common: {len(df)}/{pre} survived")
    df = df[df['close'] >= min_price]
    log(f"  After price >= ${min_price}: {len(df)}")
    df = df[df['dollar_vol'] >= min_dvol]
    log(f"  After dollar-vol >= ${min_dvol:,.0f}: {len(df)}")

    # Final list
    tickers = sorted(df['code'].unique().tolist())
    log(f"  FINAL: {len(tickers)} tickers selected")
    return tickers


def create_universe(db, tickers):
    """Create / update us_10yr universe with given tickers, copy GICS from us_common."""
    log(f"PHASE 2: Creating universe '{UNIVERSE_NAME}' with {len(tickers)} tickers")
    # Get sectors from us_common
    rows = db.conn.execute(
        "SELECT s.ticker, s.sector, s.gic_group, s.gic_sector FROM stocks s "
        "JOIN universes u ON u.id=s.universe_id WHERE u.name='us_common'"
    ).fetchall()
    src = {r[0]: (r[1] or 'Unknown', r[2] or 'Unknown', r[3] or 'Unknown') for r in rows}

    tickers_sectors = {t: src.get(t, ('Unknown','Unknown','Unknown'))[1] for t in tickers}
    uid = db.add_universe(UNIVERSE_NAME, tickers_sectors,
                          currency='USD', exchange='US',
                          description=f'10-yr survivorship-bias-reduced US universe '
                                      f'(snapshot {datetime.now().strftime("%Y-%m-%d")})')

    # Set gic_sector / gic_group fields too
    for t in tickers:
        sector, gg, gs = src.get(t, ('Unknown','Unknown','Unknown'))
        db.update_stock_gics(t, UNIVERSE_NAME, gs, gg)

    log(f"  Universe id={uid} created")


def fetch_prices(db, tickers, years, shares_map=None):
    """Pull EOD only. shares_out comes from fundamentals (phase 4) -- don't re-fetch here."""
    log(f"PHASE 3: Pulling {years}yr daily prices for {len(tickers)} tickers")
    start = (datetime.now() - timedelta(days=365 * years + 30)).strftime('%Y-%m-%d')
    end = datetime.now().strftime('%Y-%m-%d')
    n = len(tickers)
    cur = db.conn.cursor()
    shares_map = shares_map or {}
    for i, ticker in enumerate(tickers):
        existing = cur.execute(
            "SELECT COUNT(*) FROM daily_prices WHERE ticker=? AND date>=?",
            (ticker, start)
        ).fetchone()[0]
        if existing > 100:
            continue
        try:
            url = (f'https://eodhd.com/api/eod/{ticker}.US?api_token={API_KEY}'
                   f'&fmt=json&from={start}&to={end}')
            eod = get(url)
        except Exception as e:
            log(f"  prices [{i+1}/{n}] {ticker} ERR {e}")
            continue
        if not isinstance(eod, list) or not eod:
            continue
        shares_out = shares_map.get(ticker)
        rows = []
        for r in eod:
            rows.append({
                'ticker': ticker, 'date': r['date'],
                'open': r.get('open'), 'high': r.get('high'),
                'low': r.get('low'), 'close': r.get('adjusted_close') or r.get('close'),
                'volume': r.get('volume'), 'shares_out': shares_out,
                'source': 'eodhd',
            })
        if rows:
            db.upsert_prices(pd.DataFrame(rows))
        if (i + 1) % 100 == 0:
            log(f"  prices [{i+1}/{n}] last {ticker}: {len(eod)} days")


def fetch_fundamentals(db, tickers):
    """Pull fundamentals + classification + return shares_out map for use in phase 3."""
    log(f"PHASE 4: Pulling fundamentals for {len(tickers)} tickers")
    n = len(tickers)
    cur = db.conn.cursor()
    shares_map = {}
    for i, ticker in enumerate(tickers):
        existing = cur.execute(
            "SELECT COUNT(*) FROM fundamentals_quarterly WHERE ticker=? AND source='eodhd'",
            (ticker,)
        ).fetchone()[0]
        # Always pull SharesStats even on skip so we can populate shares_map for phase 3
        if existing > 8:
            # Read shares_out from latest fundamentals row instead of re-API
            row = cur.execute(
                "SELECT shares_out FROM daily_prices WHERE ticker=? AND shares_out IS NOT NULL LIMIT 1",
                (ticker,)
            ).fetchone()
            if row and row[0]:
                shares_map[ticker] = row[0]
            continue

        try:
            data = get(f'https://eodhd.com/api/fundamentals/{ticker}.US?api_token={API_KEY}')
        except Exception as e:
            log(f"  fund [{i+1}/{n}] {ticker} ERR {e}")
            continue

        bs = (data.get('Financials', {}) or {}).get('Balance_Sheet', {}).get('quarterly', {}) or {}
        inc = (data.get('Financials', {}) or {}).get('Income_Statement', {}).get('quarterly', {}) or {}
        ss = data.get('SharesStats', {}) or {}
        shares_out = _safe_num(ss.get('SharesOutstanding'))
        if shares_out:
            shares_map[ticker] = shares_out

        all_dates = set(bs.keys()) | set(inc.keys())
        q_rows = []
        for d in all_dates:
            b = bs.get(d, {}) if isinstance(bs.get(d), dict) else {}
            ii = inc.get(d, {}) if isinstance(inc.get(d), dict) else {}
            q_rows.append({
                'ticker': ticker, 'report_date': d,
                'book_equity': _safe_num(b.get('totalStockholderEquity')),
                'long_term_debt': _safe_num(b.get('longTermDebt') or b.get('longTermDebtTotal')
                                             or b.get('shortLongTermDebtTotal')),
                'total_debt': _safe_num(b.get('shortLongTermDebtTotal')),
                'total_assets': _safe_num(b.get('totalAssets')),
                'preferred_equity': _safe_num(b.get('preferredStockTotalEquity')),
                'net_income': _safe_num(ii.get('netIncome')),
                'depreciation': _safe_num(ii.get('depreciationAndAmortization')),
                'revenue': _safe_num(ii.get('totalRevenue')),
                'source': 'eodhd',
            })
        if q_rows:
            db.upsert_fundamentals_q(pd.DataFrame(q_rows))

        # Annual
        inc_y = (data.get('Financials', {}) or {}).get('Income_Statement', {}).get('yearly', {}) or {}
        earn = (data.get('Earnings', {}) or {}).get('Annual', {}) or {}
        a_rows = []
        for d in set(inc_y.keys()) | set(earn.keys()):
            ii = inc_y.get(d, {}) if isinstance(inc_y.get(d), dict) else {}
            ee = earn.get(d, {}) if isinstance(earn.get(d), dict) else {}
            rev = _safe_num(ii.get('totalRevenue'))
            eps = _safe_num(ee.get('epsActual'))
            if rev is not None or eps is not None:
                a_rows.append({'ticker': ticker, 'report_date': d, 'eps': eps,
                               'revenue': rev, 'source': 'eodhd'})
        if a_rows:
            db.upsert_fundamentals_a(pd.DataFrame(a_rows))

        if (i + 1) % 100 == 0:
            log(f"  fund [{i+1}/{n}] {ticker}: {len(q_rows)} quarterly, {len(a_rows)} annual")
    # Persist shares map for resume / phase 3
    with open('data/db/_us_10yr_shares.json', 'w') as f:
        json.dump(shares_map, f)
    return shares_map


def fetch_risk_free_rate(db, years):
    log(f"PHASE 5: Pulling {years}yr risk-free rate (^TNX or 13W T-bill)")
    start = (datetime.now() - timedelta(days=365 * years + 30)).strftime('%Y-%m-%d')
    end = datetime.now().strftime('%Y-%m-%d')
    try:
        url = f'https://eodhd.com/api/eod/^IRX.INDX?api_token={API_KEY}&fmt=json&from={start}&to={end}'
        eod = get(url)
        if not isinstance(eod, list):
            log(f"  ^IRX returned non-list, trying ^TNX")
            url = f'https://eodhd.com/api/eod/^TNX.INDX?api_token={API_KEY}&fmt=json&from={start}&to={end}'
            eod = get(url)
        if isinstance(eod, list) and eod:
            df = pd.DataFrame(eod)
            df['rate'] = df['close'].astype(float) / 100.0  # annualized decimal
            df = df.rename(columns={'date': 'date'})
            df['source'] = 'eodhd'
            db.upsert_risk_free_rate(df[['date', 'rate', 'source']], source='eodhd')
            log(f"  Stored {len(df)} risk-free rate rows ({df['date'].min()} to {df['date'].max()})")
    except Exception as e:
        log(f"  Risk-free rate fetch failed: {e}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--snapshot-date', default='2016-01-15')
    p.add_argument('--min-price', type=float, default=5.0)
    p.add_argument('--min-dollar-vol', type=float, default=1_000_000)
    p.add_argument('--years', type=int, default=10)
    p.add_argument('--phase', type=int, choices=[1, 2, 3, 4, 5], default=None)
    args = p.parse_args()

    if not API_KEY:
        sys.exit("EODHD_API_KEY not set")

    log("=" * 60)
    log(f"BUILD US 10-YEAR UNIVERSE (snap={args.snapshot_date}, "
        f"min_price=${args.min_price}, min_dvol=${args.min_dollar_vol:,.0f}, "
        f"years={args.years})")
    log("=" * 60)

    db = MarketDB()
    db.create_tables()

    if args.phase in (None, 1, 2):
        tickers = snapshot_and_filter(args.snapshot_date, args.min_price,
                                       args.min_dollar_vol, db)
        # Save list to disk for resume
        os.makedirs('data/db', exist_ok=True)
        with open('data/db/_us_10yr_tickers.json', 'w') as f:
            json.dump(tickers, f)
        if args.phase in (None, 2):
            create_universe(db, tickers)
    else:
        with open('data/db/_us_10yr_tickers.json') as f:
            tickers = json.load(f)
        log(f"Loaded {len(tickers)} tickers from cache")

    # Phase 4 runs BEFORE phase 3 so shares_out map is ready for the price ingest
    shares_map = {}
    if args.phase in (None, 4):
        shares_map = fetch_fundamentals(db, tickers)
    elif args.phase == 3:
        try:
            with open('data/db/_us_10yr_shares.json') as f:
                shares_map = json.load(f)
            log(f"Loaded shares_out for {len(shares_map)} tickers from cache")
        except FileNotFoundError:
            log("No cached shares_map; phase 3 will write null shares_out")

    if args.phase in (None, 3):
        fetch_prices(db, tickers, args.years, shares_map)

    if args.phase in (None, 5):
        fetch_risk_free_rate(db, args.years)

    log("=" * 60)
    log("BUILD US 10YR DONE")
    log("=" * 60)
    db.close()


if __name__ == '__main__':
    main()
