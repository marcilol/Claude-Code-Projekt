# -*- coding: utf-8 -*-
"""
Append the stocks DB with tickers from Citrini baskets that aren't currently covered.

Two parallel tasks:
  A. Japanese names: query EODHD search by company name to find the best US/EU
     cross-listing, then fetch its prices+fundamentals and store in DB. Builds
     a jp_crosslisting_map.csv that records original_jp_ticker -> mapped_ticker.
  B. Non-Japanese missing names: directly fetch from EODHD on the appropriate
     exchange, store in a per-market universe (citrini_<country>).

Usage:
  py scripts/append_basket_coverage.py [--input PATH] [--phase A|B] [--limit N]

Output: data/eda/Citrini/jp_crosslisting_map.csv plus DB additions.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
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
LOG_FILE = 'data/db/append_basket_coverage.log'
REQUEST_DELAY = 0.15

BBG_TO_EODHD = {
    'US': 'US', 'LN': 'LSE', 'KS': 'KO', 'KQ': 'KQ',
    'TT': 'TW', 'CH': 'SHE',
    'GR': 'XETRA', 'GY': 'XETRA',
    'FP': 'PA', 'IM': 'MI', 'SM': 'MC', 'SW': 'SW',
    'NA': 'AS', 'NO': 'OL', 'BB': 'BR', 'AV': 'VI',
    'FH': 'HE', 'DC': 'CO', 'PW': 'WAR', 'SS': 'ST',
    'AU': 'AU', 'CN': 'TO', 'MM': 'MX', 'BZ': 'SA',
    'IT': 'TA',  # Israel
}
ALLOWED_CROSSLIST_EXCH = {'US', 'LSE', 'XETRA', 'PA', 'MI', 'MC', 'SW',
                          'AS', 'OL', 'BR', 'VI', 'HE', 'CO', 'ST'}


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
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            last = e
            time.sleep(5 * (attempt + 1))
    raise last


def name_simplify(s):
    """Crude normalization: uppercase, strip suffixes/punctuation."""
    s = (s or '').upper()
    s = re.sub(r'\b(CO|LTD|CORP|INC|LIMITED|HOLDINGS|HLDGS|GROUP|GRP|PLC|AG|SA|NV|SE|KG|OYJ|AB|ASA|S\.A\.|S\.P\.A\.)\b', '', s)
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def name_similarity(a, b):
    """Token-overlap Jaccard similarity, simple but useful."""
    sa, sb = set(name_simplify(a).split()), set(name_simplify(b).split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def search_eodhd(query):
    q = urllib.parse.quote(query)
    url = f'https://eodhd.com/api/search/{q}?api_token={API_KEY}&type=stock&limit=30'
    try:
        return get(url)
    except Exception as e:
        log(f"  search err for '{query}': {e}")
        return []


def find_crosslisting(jp_ticker, jp_name):
    """Search EODHD for jp_name; pick best US/EU match."""
    results = search_eodhd(jp_name)
    if not results:
        return None
    candidates = []
    for r in results:
        ex = r.get('Exchange', '')
        if ex not in ALLOWED_CROSSLIST_EXCH:
            continue
        sim = name_similarity(jp_name, r.get('Name', ''))
        if sim < 0.30:
            continue
        candidates.append({
            'mapped_ticker': r.get('Code'),
            'mapped_exchange': ex,
            'mapped_name': r.get('Name'),
            'currency': r.get('Currency'),
            'country': r.get('Country'),
            'similarity': sim,
            'isin': r.get('ISIN'),
        })
    if not candidates:
        return None
    candidates.sort(key=lambda x: (-x['similarity'], x['mapped_exchange'] != 'US'))
    return candidates[0]


def fetch_eod_and_fundamentals(ticker, exchange, db, universe_name, currency, sector_name='Unknown'):
    """Fetch EOD prices + fundamentals for a single ticker; store in DB."""
    full = f'{ticker}.{exchange}'
    # EOD prices
    start = (datetime.now() - timedelta(days=365 * 4 + 30)).strftime('%Y-%m-%d')
    end = datetime.now().strftime('%Y-%m-%d')
    try:
        eod = get(f'https://eodhd.com/api/eod/{full}?api_token={API_KEY}&fmt=json&from={start}&to={end}')
    except Exception as e:
        log(f"  EOD err {full}: {e}")
        return False, None
    if not isinstance(eod, list) or len(eod) < 50:
        return False, None

    # Fundamentals
    try:
        fund = get(f'https://eodhd.com/api/fundamentals/{full}?api_token={API_KEY}')
    except Exception as e:
        log(f"  fund err {full}: {e}")
        fund = {}

    gen = (fund.get('General') or {}) if isinstance(fund, dict) else {}
    ss = (fund.get('SharesStats') or {}) if isinstance(fund, dict) else {}
    shares_out = _safe_num(ss.get('SharesOutstanding'))
    gic_sector = gen.get('GicSector') or gen.get('Sector') or sector_name
    gic_group = gen.get('GicGroup') or gen.get('Industry') or sector_name

    # Add stock to universe
    db.add_universe(universe_name, {ticker: gic_group}, currency=currency,
                    exchange=exchange, description=f'Citrini extras on {exchange}')
    db.update_stock_gics(ticker, universe_name, gic_sector, gic_group)

    # Insert prices
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

    # Insert quarterly fundamentals
    bs = (fund.get('Financials', {}) or {}).get('Balance_Sheet', {}).get('quarterly', {}) or {}
    inc = (fund.get('Financials', {}) or {}).get('Income_Statement', {}).get('quarterly', {}) or {}
    q_rows = []
    for d in set(bs.keys()) | set(inc.keys()):
        b = bs.get(d, {}) if isinstance(bs.get(d), dict) else {}
        i = inc.get(d, {}) if isinstance(inc.get(d), dict) else {}
        q_rows.append({
            'ticker': ticker, 'report_date': d,
            'book_equity': _safe_num(b.get('totalStockholderEquity')),
            'long_term_debt': _safe_num(b.get('longTermDebt') or b.get('longTermDebtTotal')
                                        or b.get('shortLongTermDebtTotal')),
            'total_debt': _safe_num(b.get('shortLongTermDebtTotal')),
            'total_assets': _safe_num(b.get('totalAssets')),
            'preferred_equity': _safe_num(b.get('preferredStockTotalEquity')),
            'net_income': _safe_num(i.get('netIncome')),
            'depreciation': _safe_num(i.get('depreciationAndAmortization')),
            'revenue': _safe_num(i.get('totalRevenue')),
            'source': 'eodhd',
        })
    if q_rows:
        db.upsert_fundamentals_q(pd.DataFrame(q_rows))

    return True, len(rows)


def db_has_ticker(conn, ticker):
    norm = ticker.replace('.', '-').replace('/', '-')
    n = conn.execute('SELECT COUNT(*) FROM daily_prices WHERE ticker=?', (norm,)).fetchone()[0]
    return n > 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', default='data/eda/Citrini/tickers_combined (1).csv')
    p.add_argument('--phase', choices=['A', 'B'], default=None,
                   help='A=JP cross-listings only; B=non-JP fetch only; default both')
    p.add_argument('--limit', type=int, default=None)
    p.add_argument('--mapping-out', default='data/eda/Citrini/jp_crosslisting_map.csv')
    args = p.parse_args()

    if not API_KEY:
        sys.exit("EODHD_API_KEY not set in .env")

    log("=" * 60)
    log("APPEND BASKET COVERAGE")
    log("=" * 60)

    df = pd.read_csv(args.input, keep_default_na=False, na_values=[''])
    active = df[df['current_day_weight_pct'].apply(
        lambda x: pd.notna(x) and float(x) != 0 if x not in ('', None) else False)]
    pairs = active.drop_duplicates(['ticker', 'country_code']).copy()

    db = MarketDB()
    conn = db.conn

    # Filter to MISSING pairs
    pairs['in_db'] = pairs['ticker'].apply(lambda t: db_has_ticker(conn, str(t)))
    missing = pairs[~pairs['in_db']].copy()
    log(f"Active unique pairs: {len(pairs)}; missing: {len(missing)}")

    # Phase A: Japan
    jp_missing = missing[missing['country_code'].isin(['JP', 'JT'])]
    log(f"Japanese missing: {len(jp_missing)}")

    jp_map = []
    if args.phase in (None, 'A'):
        for i, row in enumerate(jp_missing.itertuples(index=False)):
            if args.limit and i >= args.limit:
                break
            log(f"  [{i+1}/{len(jp_missing)}] JP {row.ticker} '{row.company_name}'")
            match = find_crosslisting(row.ticker, row.company_name)
            entry = {
                'jp_ticker': row.ticker, 'jp_country': row.country_code,
                'jp_name': row.company_name,
                'mapped_ticker': match['mapped_ticker'] if match else None,
                'mapped_exchange': match['mapped_exchange'] if match else None,
                'mapped_name': match['mapped_name'] if match else None,
                'mapped_currency': match['currency'] if match else None,
                'similarity': match['similarity'] if match else None,
                'status': 'no_match',
            }
            if match:
                # Already in DB?
                if db_has_ticker(conn, match['mapped_ticker']):
                    entry['status'] = 'already_in_db'
                else:
                    universe = f"citrini_jp_adrs"
                    ok, n_rows = fetch_eod_and_fundamentals(
                        match['mapped_ticker'], match['mapped_exchange'],
                        db, universe, match['currency'] or 'USD')
                    entry['status'] = 'fetched' if ok else 'fetch_failed'
                    if ok:
                        log(f"    -> mapped to {match['mapped_ticker']}.{match['mapped_exchange']} ({n_rows}d) [{match['similarity']:.2f}]")
            jp_map.append(entry)
        # Write mapping CSV
        if jp_map:
            os.makedirs(os.path.dirname(args.mapping_out), exist_ok=True)
            pd.DataFrame(jp_map).to_csv(args.mapping_out, index=False)
            log(f"Wrote {args.mapping_out}")

    # Phase B: non-Japanese, EODHD-supported missing tickers
    if args.phase in (None, 'B'):
        non_jp = missing[~missing['country_code'].isin(['JP', 'JT', 'HK', 'IN'])]
        log(f"Non-JP/HK/IN missing: {len(non_jp)}")
        n_ok = 0
        n_fail = 0
        for i, row in enumerate(non_jp.itertuples(index=False)):
            if args.limit and i >= args.limit:
                break
            ex = BBG_TO_EODHD.get(row.country_code)
            if not ex:
                log(f"  [{i+1}/{len(non_jp)}] {row.ticker} {row.country_code}: unknown country")
                continue
            ticker = str(row.ticker).replace('.', '-').replace('/', '-')
            universe = f"citrini_{row.country_code.lower()}"
            currency_map = {'XETRA': 'EUR', 'PA': 'EUR', 'MI': 'EUR', 'MC': 'EUR',
                            'AS': 'EUR', 'BR': 'EUR', 'VI': 'EUR', 'HE': 'EUR',
                            'LSE': 'GBP', 'SW': 'CHF', 'OL': 'NOK', 'CO': 'DKK',
                            'ST': 'SEK', 'WAR': 'PLN', 'AU': 'AUD', 'TO': 'CAD',
                            'MX': 'MXN', 'SA': 'BRL', 'KO': 'KRW', 'KQ': 'KRW',
                            'TA': 'ILS', 'TW': 'TWD', 'SHE': 'CNY', 'US': 'USD'}
            currency = currency_map.get(ex, 'USD')
            ok, n_rows = fetch_eod_and_fundamentals(ticker, ex, db, universe, currency,
                                                    sector_name=row.company_name)
            if ok:
                n_ok += 1
                log(f"  [{i+1}/{len(non_jp)}] {ticker}.{ex} OK ({n_rows}d)")
            else:
                n_fail += 1
                log(f"  [{i+1}/{len(non_jp)}] {ticker}.{ex} FAILED")
        log(f"Phase B: {n_ok} fetched, {n_fail} failed")

    db.close()
    log("DONE")


if __name__ == '__main__':
    main()
