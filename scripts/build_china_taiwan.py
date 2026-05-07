# -*- coding: utf-8 -*-
"""
End-to-end build of china_she + taiwan_tw universes.

Workflow:
  1. Pull common-stock list from SHE and TW exchanges.
  2. For each ticker, pull fundamentals (1 API call) -> store quarterly/annual
     to DB and capture market cap + GICS classification.
  3. Rank SHE by market cap, take top 1,000. Keep all 1,102 TW.
  4. Add universes to DB via MarketDB.add_universe.
  5. Pull EOD daily prices for active members.

Logs progress to data/db/build_china_taiwan.log.
Resumable: skips tickers already in DB.

Usage: py scripts/build_china_taiwan.py [--dry-run] [--phase 1|2|3]
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
from data_manager import MarketDB, _safe_float
from data_sources import _safe_num

API_KEY = os.getenv('EODHD_API_KEY') or os.getenv('EODHD_TOKEN')
LOG_FILE = 'data/db/build_china_taiwan.log'
REQUEST_DELAY = 0.15
TARGET_SHE = 1000

EXCHANGES = [
    {'code': 'SHE', 'universe': 'china_she', 'currency': 'CNY', 'country': 'China',
     'target': TARGET_SHE},
    {'code': 'TW',  'universe': 'taiwan_tw', 'currency': 'TWD', 'country': 'Taiwan',
     'target': None},   # keep all
]


def log(msg, also_print=True):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    if also_print:
        print(line, flush=True)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def get(url, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            time.sleep(REQUEST_DELAY)
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            last_err = e
            wait = 5 * (attempt + 1)
            log(f"    request failed ({e}); retry in {wait}s")
            time.sleep(wait)
    raise last_err


def fetch_common_stocks(exchange):
    url = f'https://eodhd.com/api/exchange-symbol-list/{exchange}?api_token={API_KEY}&fmt=json'
    syms = get(url)
    return [s for s in syms if s.get('Type', '').lower() == 'common stock']


def parse_quarterly(ticker, data):
    bs = data.get('Financials', {}).get('Balance_Sheet', {}).get('quarterly', {}) or {}
    inc = data.get('Financials', {}).get('Income_Statement', {}).get('quarterly', {}) or {}
    cf = data.get('Financials', {}).get('Cash_Flow', {}).get('quarterly', {}) or {}
    all_dates = set(bs.keys()) | set(inc.keys()) | set(cf.keys())

    rows = []
    for d in all_dates:
        b = bs.get(d, {}) if isinstance(bs.get(d), dict) else {}
        i = inc.get(d, {}) if isinstance(inc.get(d), dict) else {}
        c = cf.get(d, {}) if isinstance(cf.get(d), dict) else {}
        rows.append({
            'ticker': ticker, 'report_date': d,
            'book_equity': _safe_num(b.get('totalStockholderEquity')),
            'long_term_debt': _safe_num(b.get('longTermDebt') or b.get('longTermDebtTotal')
                                        or b.get('shortLongTermDebtTotal')),
            'total_debt': _safe_num(b.get('shortLongTermDebtTotal') or b.get('longTermDebtTotal')),
            'total_assets': _safe_num(b.get('totalAssets')),
            'preferred_equity': _safe_num(b.get('preferredStockTotalEquity')),
            'net_income': _safe_num(i.get('netIncome')),
            'depreciation': _safe_num(i.get('depreciationAndAmortization')),
            'revenue': _safe_num(i.get('totalRevenue')),
            'source': 'eodhd',
        })
    return rows


def parse_annual(ticker, data):
    inc = data.get('Financials', {}).get('Income_Statement', {}).get('yearly', {}) or {}
    earn = data.get('Earnings', {}).get('Annual', {}) or {}
    all_dates = set(inc.keys()) | set(earn.keys())
    rows = []
    for d in all_dates:
        i = inc.get(d, {}) if isinstance(inc.get(d), dict) else {}
        e = earn.get(d, {}) if isinstance(earn.get(d), dict) else {}
        rev = _safe_num(i.get('totalRevenue'))
        eps = _safe_num(e.get('epsActual'))
        if rev is not None or eps is not None:
            rows.append({'ticker': ticker, 'report_date': d, 'eps': eps,
                         'revenue': rev, 'source': 'eodhd'})
    return rows


def fetch_fundamentals_and_store(db, exchange_code, syms, output_meta):
    """Pull fundamentals per ticker; store to DB; collect (ticker, mcap, sector, group)."""
    n = len(syms)
    for i, s in enumerate(syms):
        code = s['Code']
        ticker = code  # store without exchange suffix (matches existing convention)
        full = f'{code}.{exchange_code}'

        # Skip if we already have fundamentals for this ticker
        c = db.conn.cursor()
        existing = c.execute("SELECT COUNT(*) FROM fundamentals_quarterly WHERE ticker=? AND source='eodhd'",
                             (ticker,)).fetchone()[0]
        if existing > 0 and ticker in output_meta:
            continue

        try:
            data = get(f'https://eodhd.com/api/fundamentals/{full}?api_token={API_KEY}')
        except Exception as e:
            log(f"  [{i+1}/{n}] {full}: FETCH ERR {e}")
            continue

        # Store quarterly + annual
        q_rows = parse_quarterly(ticker, data)
        a_rows = parse_annual(ticker, data)
        if q_rows:
            db.upsert_fundamentals_q(pd.DataFrame(q_rows))
        if a_rows:
            db.upsert_fundamentals_a(pd.DataFrame(a_rows))

        # Capture metadata for ranking
        gen = data.get('General', {}) or {}
        high = data.get('Highlights', {}) or {}
        ss = data.get('SharesStats', {}) or {}
        mcap = _safe_num(high.get('MarketCapitalization')) or 0
        gic_sector = gen.get('GicSector') or gen.get('Sector') or 'Unknown'
        gic_group = gen.get('GicGroup') or gen.get('Industry') or 'Unknown'
        shares_out = _safe_num(ss.get('SharesOutstanding'))
        company = gen.get('Name') or s.get('Name', '')

        output_meta[ticker] = {
            'ticker': ticker, 'name': company, 'mcap': mcap or 0,
            'gic_sector': gic_sector, 'gic_group': gic_group,
            'shares_out': shares_out,
        }

        if (i + 1) % 100 == 0:
            log(f"  [{i+1}/{n}] processed; latest {full} mcap={mcap}")

    return output_meta


def fetch_prices_and_store(db, exchange_code, tickers, shares_out_map, years=4):
    """Pull EOD prices per ticker, store to DB. shares_out_map: ticker -> shares_outstanding from cached meta."""
    start = (datetime.now() - timedelta(days=365 * years + 30)).strftime('%Y-%m-%d')
    end = datetime.now().strftime('%Y-%m-%d')
    n = len(tickers)
    for i, ticker in enumerate(tickers):
        full = f'{ticker}.{exchange_code}'
        try:
            url = (f'https://eodhd.com/api/eod/{full}?api_token={API_KEY}'
                   f'&fmt=json&from={start}&to={end}')
            eod = get(url)
        except Exception as e:
            log(f"  [{i+1}/{n}] {full}: FETCH ERR {e}")
            continue
        if not isinstance(eod, list):
            continue

        shares_out = shares_out_map.get(ticker)  # from phase-1 cached meta; no extra API call

        rows = []
        for row in eod:
            rows.append({
                'ticker': ticker, 'date': row['date'],
                'open': row.get('open'), 'high': row.get('high'),
                'low': row.get('low'), 'close': row.get('adjusted_close') or row.get('close'),
                'volume': row.get('volume'), 'shares_out': shares_out,
                'source': 'eodhd',
            })
        if rows:
            df = pd.DataFrame(rows)
            db.upsert_prices(df)

        if (i + 1) % 50 == 0:
            log(f"  prices [{i+1}/{n}] last {full}: {len(eod)} days")


def phase_1_fetch_fundamentals(db, exchanges):
    """Pull fundamentals for all common stocks per exchange."""
    all_meta = {}
    for ex in exchanges:
        log(f"PHASE 1: Fetching common-stock list for {ex['code']}")
        syms = fetch_common_stocks(ex['code'])
        log(f"  {ex['code']}: {len(syms)} common stocks")
        log(f"PHASE 1: Pulling fundamentals for {len(syms)} {ex['code']} stocks")
        meta = {}
        fetch_fundamentals_and_store(db, ex['code'], syms, meta)
        log(f"  {ex['code']}: fundamentals captured for {len(meta)} tickers")
        all_meta[ex['code']] = meta
    return all_meta


def phase_2_init_universes(db, exchanges, all_meta):
    """Rank, filter, and add universes."""
    selections = {}
    for ex in exchanges:
        meta = all_meta.get(ex['code'], {})
        df = pd.DataFrame(list(meta.values()))
        df = df[df['mcap'] > 0].copy()
        df = df.sort_values('mcap', ascending=False)

        if ex['target'] and len(df) > ex['target']:
            df = df.head(ex['target'])
        log(f"PHASE 2: {ex['universe']}: selected {len(df)} tickers "
            f"(mcap range {df['mcap'].min():,.0f} -- {df['mcap'].max():,.0f} {ex['currency']})")

        # Build ticker -> sector dict (use GicGroup for 25-group classification)
        tickers_sectors = {row['ticker']: row['gic_group'] for _, row in df.iterrows()}
        uid = db.add_universe(ex['universe'], tickers_sectors,
                              currency=ex['currency'], exchange=ex['code'],
                              description=f"Top {len(df)} common stocks on {ex['code']} by market cap")
        log(f"  added universe '{ex['universe']}' (id={uid}) with {len(tickers_sectors)} stocks")

        # Also store gic_sector via update_stock_gics
        for _, row in df.iterrows():
            db.update_stock_gics(row['ticker'], ex['universe'],
                                 row['gic_sector'], row['gic_group'])

        selections[ex['universe']] = list(tickers_sectors.keys())
    return selections


def phase_3_fetch_prices(db, exchanges, selections, all_meta):
    for ex in exchanges:
        tickers = selections[ex['universe']]
        # Build shares_out map from cached phase-1 meta
        meta_for_ex = all_meta.get(ex['code'], {})
        shares_out_map = {t: m['shares_out'] for t, m in meta_for_ex.items()
                          if m.get('shares_out')}
        log(f"PHASE 3: pulling EOD prices for {len(tickers)} tickers in {ex['universe']} "
            f"(shares_out from cached meta for {len(shares_out_map)} tickers)")
        fetch_prices_and_store(db, ex['code'], tickers, shares_out_map)
        log(f"  {ex['universe']}: prices fetched")


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--phase', type=int, choices=[1, 2, 3], default=None,
                   help='Run only one phase. Default: all phases.')
    p.add_argument('--dry-run', action='store_true', help='List ticker counts only.')
    args = p.parse_args()

    if not API_KEY:
        sys.exit("EODHD_API_KEY not set in .env")

    log("=" * 60)
    log("BUILD CHINA + TAIWAN UNIVERSES")
    log("=" * 60)

    if args.dry_run:
        for ex in EXCHANGES:
            syms = fetch_common_stocks(ex['code'])
            log(f"{ex['code']}: {len(syms)} common stocks")
        return

    db = MarketDB()
    db.create_tables()

    if args.phase in (None, 1):
        all_meta = phase_1_fetch_fundamentals(db, EXCHANGES)
        # Cache meta to disk so we can resume from phase 2
        with open('data/db/_china_taiwan_meta.json', 'w') as f:
            json.dump({k: list(v.values()) for k, v in all_meta.items()}, f)
    else:
        with open('data/db/_china_taiwan_meta.json') as f:
            cached = json.load(f)
            all_meta = {k: {x['ticker']: x for x in v} for k, v in cached.items()}

    if args.phase in (None, 2):
        selections = phase_2_init_universes(db, EXCHANGES, all_meta)
        with open('data/db/_china_taiwan_selections.json', 'w') as f:
            json.dump(selections, f)
    else:
        with open('data/db/_china_taiwan_selections.json') as f:
            selections = json.load(f)

    if args.phase in (None, 3):
        # Reload meta if needed (e.g. when resuming with --phase 3)
        if 'all_meta' not in locals():
            with open('data/db/_china_taiwan_meta.json') as f:
                cached = json.load(f)
                all_meta = {k: {x['ticker']: x for x in v} for k, v in cached.items()}
        phase_3_fetch_prices(db, EXCHANGES, selections, all_meta)

    log("=" * 60)
    log("DONE")
    db.close()


if __name__ == '__main__':
    main()
