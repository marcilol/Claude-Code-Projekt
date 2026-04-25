# -*- coding: utf-8 -*-
"""
Pre-flight check for data fetches.
Run BEFORE any large API operation to verify assumptions.

Usage: py scripts/preflight_check.py --universe <name> --action <prices|fundamentals|classify|all>
"""

import os
import sys
import sqlite3
import requests
import time

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'db', 'market_data.db')


def check_api():
    """Check API key works and how many calls remain."""
    k = os.environ.get('EODHD_API_KEY')
    if not k:
        print('FAIL: EODHD_API_KEY not set')
        return False, 0

    r = requests.get('https://eodhd.com/api/user',
                     params={'api_token': k, 'fmt': 'json'}, timeout=15)
    if r.status_code != 200:
        print(f'FAIL: API user endpoint returned {r.status_code}')
        return False, 0

    d = r.json()
    remaining = d.get('apiRequests', 0)
    print(f'API calls remaining: {remaining:,}')
    print(f'Date: {d.get("apiRequestsDate")}')

    # Actual test call
    r2 = requests.get('https://eodhd.com/api/eod/AAPL.US',
                      params={'api_token': k, 'fmt': 'json', 'from': '2026-04-14'}, timeout=15)
    if r2.status_code == 200:
        print(f'Live test (AAPL.US): OK ({len(r2.json())} rows)')
        return True, remaining
    elif r2.status_code == 402:
        print(f'Live test (AAPL.US): HTTP 402 — limit exhausted despite counter showing {remaining}')
        return False, 0
    else:
        print(f'Live test (AAPL.US): HTTP {r2.status_code}')
        return False, 0


def check_universe(universe_name):
    """Check universe exists and report stats."""
    c = sqlite3.connect(DB_PATH)
    row = c.execute('SELECT id, currency, exchange, description FROM universes WHERE name=?',
                    (universe_name,)).fetchone()
    if not row:
        print(f'FAIL: Universe "{universe_name}" not found in DB')
        c.close()
        return None

    uid = row[0]
    print(f'Universe: {universe_name} (id={uid}, {row[1]}, {row[2]})')
    print(f'Description: {row[3]}')

    active = c.execute('SELECT COUNT(*) FROM stocks WHERE universe_id=? AND removed_date IS NULL',
                       (uid,)).fetchone()[0]
    removed = c.execute('SELECT COUNT(*) FROM stocks WHERE universe_id=? AND removed_date IS NOT NULL',
                        (uid,)).fetchone()[0]
    print(f'Active tickers: {active}, removed: {removed}')

    # Key sanity: are well-known tickers present?
    if row[1] == 'USD':
        check_tickers = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'JPM']
    elif row[1] == 'GBP':
        check_tickers = ['SHEL', 'BP', 'AZN', 'HSBA', 'GSK']
    elif row[1] == 'KRW':
        check_tickers = ['005930', '000660', '035420']
    else:
        check_tickers = []

    if check_tickers:
        print(f'Sanity check — expected tickers:')
        for t in check_tickers:
            found = c.execute('SELECT ticker, removed_date FROM stocks WHERE ticker=? AND universe_id=?',
                              (t, uid)).fetchone()
            if found:
                status = 'active' if found[1] is None else f'REMOVED ({found[1]})'
                print(f'  {t}: {status}')
            else:
                print(f'  {t}: NOT FOUND')

    c.close()
    return uid


def estimate_calls(universe_name, action):
    """Estimate API calls needed for an action."""
    c = sqlite3.connect(DB_PATH)
    uid = c.execute('SELECT id FROM universes WHERE name=?', (universe_name,)).fetchone()
    if not uid:
        return 0
    uid = uid[0]

    active = c.execute('SELECT COUNT(*) FROM stocks WHERE universe_id=? AND removed_date IS NULL',
                       (uid,)).fetchone()[0]

    # How many already have data?
    with_prices = c.execute('''SELECT COUNT(DISTINCT s.ticker) FROM stocks s
        JOIN daily_prices p ON p.ticker=s.ticker
        WHERE s.universe_id=? AND s.removed_date IS NULL''', (uid,)).fetchone()[0]
    with_fund = c.execute('''SELECT COUNT(DISTINCT s.ticker) FROM stocks s
        JOIN fundamentals_quarterly f ON f.ticker=s.ticker
        WHERE s.universe_id=? AND s.removed_date IS NULL''', (uid,)).fetchone()[0]
    classified = c.execute('''SELECT COUNT(*) FROM stocks
        WHERE universe_id=? AND removed_date IS NULL AND gic_sector IS NOT NULL''',
        (uid,)).fetchone()[0]
    c.close()

    print(f'\nExisting data:')
    print(f'  With prices: {with_prices}/{active}')
    print(f'  With fundamentals: {with_fund}/{active}')
    print(f'  Classified: {classified}/{active}')

    if action in ('prices', 'all'):
        # 1 call for eod, 1 for SharesStats (but only if eod succeeds after our fix)
        # Incremental: skip tickers with up-to-date prices
        need_prices = active - with_prices  # rough estimate, incremental logic may skip more
        calls_prices = need_prices * 2  # worst case: 2 per ticker
        print(f'\nPrices: ~{need_prices} tickers need fetch, ~{calls_prices} API calls')

    if action in ('fundamentals', 'all'):
        need_fund = active  # fundamentals checks needs_update per ticker
        calls_fund = need_fund * 2  # quarterly + annual
        print(f'Fundamentals: ~{need_fund} tickers to check, ~{calls_fund} API calls max')

    if action in ('classify', 'all'):
        need_class = active - classified
        calls_class = need_class
        print(f'Classify: ~{need_class} tickers need classification, ~{need_class} API calls')

    total = 0
    if action in ('prices', 'all'):
        total += calls_prices
    if action in ('fundamentals', 'all'):
        total += calls_fund
    if action in ('classify', 'all'):
        total += calls_class

    print(f'\nEstimated total API calls: ~{total:,}')
    return total


def smoke_test(universe_name):
    """Test fetch on 3 tickers before launching full run."""
    c = sqlite3.connect(DB_PATH)
    uid = c.execute('SELECT id, exchange FROM universes WHERE name=?', (universe_name,)).fetchone()
    if not uid:
        return False
    exchange = uid[1] or 'US'
    uid = uid[0]

    tickers = [r[0] for r in c.execute(
        'SELECT ticker FROM stocks WHERE universe_id=? AND removed_date IS NULL LIMIT 3',
        (uid,))]
    c.close()

    if not tickers:
        print('FAIL: No tickers to test')
        return False

    k = os.environ.get('EODHD_API_KEY')
    print(f'\nSmoke test — 3 tickers on {exchange}:')
    ok = 0
    for t in tickers:
        sym = f'{t}.{exchange}'
        r = requests.get(f'https://eodhd.com/api/eod/{sym}',
                        params={'api_token': k, 'fmt': 'json', 'from': '2026-04-01'}, timeout=15)
        rows = len(r.json()) if r.status_code == 200 and r.text.startswith('[') else 0
        status = f'{rows} rows' if rows > 0 else f'HTTP {r.status_code}'
        print(f'  {sym}: {status}')
        if rows > 0:
            ok += 1

    if ok == 0:
        print('FAIL: All 3 smoke test tickers returned no data')
        return False
    print(f'Smoke test: {ok}/3 OK')
    return True


def main():
    universe = None
    action = 'all'
    for i, arg in enumerate(sys.argv):
        if arg == '--universe' and i + 1 < len(sys.argv):
            universe = sys.argv[i + 1]
        if arg == '--action' and i + 1 < len(sys.argv):
            action = sys.argv[i + 1]

    if not universe:
        print('Usage: py scripts/preflight_check.py --universe <name> [--action <prices|fundamentals|classify|all>]')
        sys.exit(1)

    print('=' * 50)
    print(f'  PRE-FLIGHT CHECK: {universe}')
    print('=' * 50)

    # 1. API
    print('\n--- API Status ---')
    api_ok, remaining = check_api()
    if not api_ok:
        print('\nABORT: API not available')
        sys.exit(1)

    # 2. Universe
    print('\n--- Universe ---')
    uid = check_universe(universe)
    if uid is None:
        sys.exit(1)

    # 3. Estimate
    print('\n--- Cost Estimate ---')
    est_calls = estimate_calls(universe, action)
    if est_calls > remaining:
        print(f'\nWARNING: Need ~{est_calls:,} calls but only {remaining:,} available')

    # 4. Smoke test
    print('\n--- Smoke Test ---')
    smoke_ok = smoke_test(universe)

    # Summary
    print('\n' + '=' * 50)
    print(f'  RESULT: {"GO" if api_ok and uid and smoke_ok else "NO-GO"}')
    print('=' * 50)
    if not smoke_ok:
        print('Fix smoke test failures before launching.')


if __name__ == '__main__':
    main()
