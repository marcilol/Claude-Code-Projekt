# -*- coding: utf-8 -*-
"""
Build the expanded US common stock universe from EODHD.

Union of:
  1. Active common stocks (exchange-symbol-list/US without delisted param)
  2. Delisted common stocks (exchange-symbol-list/US with delisted=1)
  3. Russell 3000 tickers already in DB (to ensure no gaps)

Filters applied:
  - NYSE / NASDAQ / NYSE MKT only
  - No ADRs, funds, units, warrants, rights, preferreds, SPACs (by name)
  - One share class per company (ISIN dedup)
  - Ticker pattern cleanup

Verification steps:
  - Checks AAPL, MSFT, NVDA are in final list
  - Reports overlap with Russell 3000
  - Estimates API calls needed

Usage: py scripts/build_us_universe.py [--dry-run]
"""

import os
import sys
import re
import sqlite3
import requests
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'db', 'market_data.db')


def fetch_ticker_list(delisted=False):
    """Fetch US common stock list from EODHD."""
    k = os.environ.get('EODHD_API_KEY')
    params = {'api_token': k, 'fmt': 'json', 'type': 'common_stock'}
    if delisted:
        params['delisted'] = 1

    r = requests.get('https://eodhd.com/api/exchange-symbol-list/US',
                     params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def is_excluded_by_name(name):
    if not name:
        return True
    n = name.upper()
    for term in ['ADR', 'AMERICAN DEPOSITARY', 'ADS ',
                 'CLOSED END', 'CLOSED-END', 'FUND ', ' FUND', 'ETF ', ' ETF',
                 'TRUST ', 'CAPITAL TRUST', 'INVESTMENT TRUST',
                 ' UNIT', ' UNITS', 'WARRANT', ' WTS', ' WT ',
                 ' RIGHT', ' RIGHTS', 'PREFERRED', ' PFD', 'PRF ',
                 'ACQUISITION CORP', 'BLANK CHECK', 'SPAC ', 'MERGER CORP', 'MERGER SUB']:
        if term in n:
            return True
    return False


def filter_and_dedup(stocks):
    """Apply all filters and dedup by ISIN."""
    # Exchange filter
    major = [d for d in stocks if d.get('Exchange') in ('NYSE', 'NASDAQ', 'NYSE MKT')]

    # Name filter
    filtered = [d for d in major if not is_excluded_by_name(d.get('Name', ''))]

    # ISIN dedup
    isin_groups = defaultdict(list)
    no_isin = []
    for d in filtered:
        isin = d.get('Isin')
        if isin and isin != 'None':
            isin_groups[isin[:11]].append(d)
        else:
            no_isin.append(d)
    deduped = []
    for group in isin_groups.values():
        group.sort(key=lambda x: (len(x['Code']), x['Code']))
        deduped.append(group[0])
    deduped.extend(no_isin)

    # Ticker pattern cleanup
    clean = []
    for d in deduped:
        code = d['Code']
        if re.search(r'[W]$', code) and len(code) > 4:
            continue
        if code.endswith('U') and len(code) > 4:
            continue
        clean.append(d)

    return clean


def main():
    dry_run = '--dry-run' in sys.argv

    print('=' * 60)
    print('  BUILD US EXPANDED UNIVERSE')
    print('=' * 60)

    # Step 1: Fetch both lists
    print('\nFetching active US common stocks...')
    active = fetch_ticker_list(delisted=False)
    print(f'  Active: {len(active)}')

    print('Fetching delisted US common stocks...')
    delisted = fetch_ticker_list(delisted=True)
    print(f'  Delisted: {len(delisted)}')

    # Step 2: Union
    seen = {}
    for d in active:
        seen[d['Code']] = d
    for d in delisted:
        if d['Code'] not in seen:
            seen[d['Code']] = d
    combined = list(seen.values())
    print(f'  Union: {len(combined)}')

    # Step 3: Filter
    print('\nApplying filters...')
    clean = filter_and_dedup(combined)
    print(f'  After filters: {len(clean)}')

    # Step 4: Add R3K tickers that might be missing
    c = sqlite3.connect(DB_PATH)
    r3k = {r[0] for r in c.execute('SELECT ticker FROM stocks WHERE universe_id=1')}
    clean_codes = {d['Code'].replace('.', '-') for d in clean}
    r3k_missing = r3k - clean_codes
    print(f'  R3K tickers not in filtered list: {len(r3k_missing)}')
    # Add them
    for t in r3k_missing:
        clean.append({'Code': t, 'Name': 'From Russell 3000', 'Exchange': 'US',
                      'Isin': None, 'Currency': 'USD', 'Type': 'Common Stock', 'Country': 'USA'})
    print(f'  Final count: {len(clean)}')

    # Step 5: VERIFY
    print('\n--- VERIFICATION ---')
    final_codes = {d['Code'].replace('.', '-') for d in clean}
    must_have = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'JPM', 'BRK-B', 'TSLA', 'META', 'V']
    all_present = True
    for t in must_have:
        present = t in final_codes
        print(f'  {t}: {"OK" if present else "MISSING"}')
        if not present:
            all_present = False

    if not all_present:
        print('\nFAIL: Key tickers missing. Aborting.')
        sys.exit(1)

    # R3K overlap
    r3k_overlap = r3k & final_codes
    print(f'\n  R3K overlap: {len(r3k_overlap)}/{len(r3k)} ({100*len(r3k_overlap)/len(r3k):.0f}%)')

    # How many already have price data?
    with_prices = c.execute('SELECT COUNT(DISTINCT ticker) FROM daily_prices').fetchone()[0]
    already_have = len({d['Code'].replace('.', '-') for d in clean} &
                       {r[0] for r in c.execute('SELECT DISTINCT ticker FROM daily_prices')})
    need_fetch = len(clean) - already_have
    print(f'  Already have prices: {already_have}')
    print(f'  Need fetching: {need_fetch}')
    print(f'  Estimated API calls (prices): ~{need_fetch * 2:,}')
    print(f'  Estimated API calls (classify): ~{need_fetch:,}')
    print(f'  Estimated API calls (fundamentals): ~{need_fetch * 2:,}')
    print(f'  Total: ~{need_fetch * 5:,}')

    if dry_run:
        print('\n  DRY RUN — not saving to DB')
        c.close()
        return

    # Step 6: Save to DB
    print('\nSaving to DB...')
    from data_manager import MarketDB
    db = MarketDB()
    db.create_tables()

    # Delete old us_common if exists
    old_uid = c.execute('SELECT id FROM universes WHERE name="us_common"').fetchone()
    if old_uid:
        c.execute('DELETE FROM stocks WHERE universe_id=?', (old_uid[0],))
        c.execute('DELETE FROM universes WHERE id=?', (old_uid[0],))
        c.commit()
        print(f'  Deleted old us_common universe (id={old_uid[0]})')

    tickers_sectors = {}
    for d in clean:
        code = d['Code'].replace('.', '-')
        tickers_sectors[code] = d.get('Name', 'Unknown')

    uid = db.add_universe('us_common', tickers_sectors, currency='USD', exchange='US',
                          description=f'{len(tickers_sectors)} stocks (active+delisted)')
    print(f'  Created us_common: {len(tickers_sectors)} tickers (id={uid})')
    db.close()
    c.close()

    print('\nNext steps:')
    print(f'  1. py scripts/preflight_check.py --universe us_common')
    print(f'  2. py scripts/update_data.py classify --universe us_common --source eodhd')
    print(f'  3. py scripts/update_data.py prices --universe us_common --source eodhd --full --years 4')
    print(f'  4. py scripts/update_data.py fundamentals --universe us_common --source eodhd --full')


if __name__ == '__main__':
    main()
