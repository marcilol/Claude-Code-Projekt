# -*- coding: utf-8 -*-
"""
Build the `sp500_hist` universe — every ticker that was a member of the S&P 500
at any point from 2006-01-01 through today. Survivorship-bias-free by construction:
includes Lehman, Bear Stearns, GM (old), AMR, Sears, etc.

Source of point-in-time membership:
  https://github.com/fja05680/sp500
  S&P 500 Historical Components & Changes.csv (date-indexed lists since 1996)

Resolution to EODHD symbols:
  - Tickers without suffix (e.g. AAPL, MSFT) -> matched against EODHD US active list.
  - Tickers with -YYYYMM suffix (e.g. AAMRQ-201312, LEH-200810) are old/delisted;
    we try `{base}`, `{base}_old`, `{base}_old1..5`, `{base}-OLD` against
    EODHD's US delisted list.

Outputs:
  - data/input/sp500_historical_components.csv  (cached fja05680 CSV)
  - data/db/_sp500_hist_resolved.json   (fja_ticker -> eodhd_ticker, with first/last seen)
  - data/db/_sp500_hist_unresolved.json (fja tickers we couldn't map)
  - DB universe `sp500_hist` populated via MarketDB.add_universe

Usage:
    py scripts/build_sp500_historical.py [--start 2006-01-01]
                                          [--no-network]   # use cached files only
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(__file__))
from data_manager import MarketDB

API_KEY = os.getenv('EODHD_API_KEY') or os.getenv('EODHD_TOKEN')

CSV_URL = ('https://raw.githubusercontent.com/fja05680/sp500/master/'
           'S%26P%20500%20Historical%20Components%20%26%20Changes.csv')
CSV_CACHE = 'data/input/sp500_historical_components.csv'

# Newer CSV (bare tickers, no -YYYYMM suffixes) used to backfill 2019-present additions.
CSV_URL_NEW = ('https://raw.githubusercontent.com/fja05680/sp500/master/'
               'S%26P%20500%20Historical%20Components%20%26%20Changes(01-17-2026).csv')
CSV_CACHE_NEW = 'data/input/sp500_historical_components_2026.csv'
NEW_CSV_CUTOVER = '2019-01-12'  # original CSV ends 2019-01-11; new CSV picks up here
RESOLVED_PATH = 'data/db/_sp500_hist_resolved.json'
UNRESOLVED_PATH = 'data/db/_sp500_hist_unresolved.json'
UNIVERSE_NAME = 'sp500_hist'

# Manual overrides for fja tickers that EODHD's NYSE/NASDAQ symbol list doesn't
# carry directly. Pattern is usually one of:
#   - fja uses post-bankruptcy pink-sheet ticker (e.g. LEHMQ); EODHD only has
#     pre-BK NYSE listing (LEH).
#   - Company renamed (no acquisition); EODHD drops the old symbol on rename.
# Mapping: fja_ticker -> EODHD symbol (must exist in active or delisted list)
MANUAL_OVERRIDES = {
    'LEHMQ-201203': 'LEH',       # Lehman pre-BK NYSE listing
    'ABKFQ-201304': 'ABK',       # Ambac pre-BK
    'MTLQQ-201103': 'GM_old',    # Old GM pre-2009 BK (current GM is post-IPO)
    'RSHCQ-201510': 'RSH',       # RadioShack pre-BK
    'RE':           'EG',        # Everest Re renamed to Everest Group (2023)
    'ATGE':         'DV',        # Adtalem (formerly DeVry) - covers 2006-2017
    # Post-2019 additions / renames not in the old CSV's window:
    'FB':           'META',      # Facebook -> Meta rename (Oct 2021); EODHD's FB ticker
                                  # was reused by another company, so use META directly.
    'CDAY':         'DAY',       # Ceridian -> Dayforce rename (Feb 2024)
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def http_get(url, retries=3, timeout=120):
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def download_csv():
    os.makedirs(os.path.dirname(CSV_CACHE), exist_ok=True)
    log(f"Downloading {CSV_URL}")
    data = http_get(CSV_URL)
    with open(CSV_CACHE, 'wb') as f:
        f.write(data)
    log(f"  saved {len(data):,} bytes -> {CSV_CACHE}")


def parse_csv(start_date, path=None, end_date=None):
    """Return dict {fja_ticker: (first_seen, last_seen)} for all tickers
    appearing in any row with start_date <= date <= end_date (end_date optional)."""
    p = path or CSV_CACHE
    log(f"Parsing {p} (filter: {start_date} <= date" + (f" <= {end_date})" if end_date else ")"))
    seen = {}
    n_rows = 0
    n_kept = 0
    with open(p, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == ['date', 'tickers'], f"unexpected header: {header}"
        for row in reader:
            n_rows += 1
            d = row[0]
            if d < start_date:
                continue
            if end_date and d > end_date:
                continue
            n_kept += 1
            for t in row[1].split(','):
                t = t.strip()
                if not t:
                    continue
                if t not in seen:
                    seen[t] = [d, d]
                else:
                    if d < seen[t][0]:
                        seen[t][0] = d
                    if d > seen[t][1]:
                        seen[t][1] = d
    log(f"  scanned {n_rows:,} rows, kept {n_kept:,}")
    log(f"  unique tickers in window: {len(seen):,}")
    return {t: tuple(v) for t, v in seen.items()}


def fetch_eodhd_symbol_list(delisted=False):
    """Return set of EODHD US symbols (Code field). One API call."""
    flag = '&delisted=1' if delisted else ''
    url = f'https://eodhd.com/api/exchange-symbol-list/US?api_token={API_KEY}{flag}&fmt=json'
    log(f"  fetching EODHD US symbol list (delisted={delisted})")
    raw = http_get(url)
    data = json.loads(raw)
    # Filter to common stock-ish (Type field: Common Stock, Preferred Stock, ETF, Fund...)
    # Keep all for matching breadth; let downstream pipeline reject non-equity.
    codes = {row['Code'] for row in data if row.get('Code')}
    log(f"    {len(codes):,} {'delisted' if delisted else 'active'} symbols")
    return codes


def split_suffix(fja_ticker):
    """Split 'AAMRQ-201312' -> ('AAMRQ', '201312'); 'AAPL' -> ('AAPL', None)."""
    if '-' in fja_ticker:
        # The fja format is BASE-YYYYMM where YYYYMM is exactly 6 digits.
        # But also handles BF.B (no hyphen) and RDS.A (no hyphen).
        base, _, suf = fja_ticker.rpartition('-')
        if len(suf) == 6 and suf.isdigit():
            return base, suf
    return fja_ticker, None


def resolve_ticker(fja_ticker, active_set, delisted_set):
    """Return EODHD symbol or None.

    Strategy:
      - Manual override map (for fja vs EODHD naming mismatches).
      - No YYYYMM suffix: try exact match against active first, then delisted.
      - Has YYYYMM suffix: try {base}, {base}_old, {base}_old1..5, {base}-OLD
        against the delisted set first (most likely there), then active.
    """
    if fja_ticker in MANUAL_OVERRIDES:
        cand = MANUAL_OVERRIDES[fja_ticker]
        if cand in active_set or cand in delisted_set:
            return cand
        # Override declared but not actually in EODHD lists - log and fall through
        return None

    base, suf = split_suffix(fja_ticker)

    if suf is None:
        if fja_ticker in active_set:
            return fja_ticker
        if fja_ticker in delisted_set:
            return fja_ticker
        # Try dot->dash for share classes (BF.B -> BF-B sometimes)
        if '.' in fja_ticker:
            alt = fja_ticker.replace('.', '-')
            if alt in active_set:
                return alt
            if alt in delisted_set:
                return alt
        return None

    # Suffixed (delisted at YYYYMM). When EODHD has both BASE and BASE_old in
    # the delisted list, the symbol was reused — fja's suffix tells us we want
    # the OLDER company, so try the _old variants first.
    old_variants = [
        f"{base}_old",
        f"{base}_old1", f"{base}_old2", f"{base}_old3",
        f"{base}_old4", f"{base}_old5",
        f"{base}-OLD",
    ]
    if '.' in base:
        alt_base = base.replace('.', '-')
        old_variants.extend([
            f"{alt_base}_old", f"{alt_base}_old1", f"{alt_base}_old2",
        ])

    # 1. Prefer _old variants in delisted (handles symbol reuse like BSC -> BSC_old)
    for c in old_variants:
        if c in delisted_set:
            return c
    # 2. Bare BASE in delisted (single delisting, no reuse — e.g. LEH, RSH, ABK)
    if base in delisted_set:
        return base
    if '.' in base:
        alt_base = base.replace('.', '-')
        if alt_base in delisted_set:
            return alt_base
    # 3. Last resort: active (rare for a YYYYMM-suffixed fja entry)
    for c in old_variants + [base]:
        if c in active_set:
            return c
    return None


def write_universe(db, resolved):
    """resolved: dict {eodhd_ticker: (fja_ticker, first_seen, last_seen)}"""
    log(f"Inserting {len(resolved)} tickers into universe '{UNIVERSE_NAME}'")
    tickers_sectors = {t: 'Unknown' for t in resolved}
    uid = db.add_universe(
        UNIVERSE_NAME, tickers_sectors,
        currency='USD', exchange='US',
        description=f'S&P 500 historical members (any time 2006-{datetime.now().year}); '
                    f'survivorship-bias-free; built {datetime.now().strftime("%Y-%m-%d")}'
    )
    log(f"  universe_id={uid}, {len(tickers_sectors)} stocks added")
    return uid


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--start', default='2006-01-01',
                   help='Earliest fja CSV row date to include (default 2006-01-01)')
    p.add_argument('--no-network', action='store_true',
                   help='Use cached CSV and EODHD lists if present')
    args = p.parse_args()

    if not API_KEY and not args.no_network:
        sys.exit("EODHD_API_KEY not set in env or .env")

    if not args.no_network or not os.path.exists(CSV_CACHE):
        download_csv()
    if not args.no_network or not os.path.exists(CSV_CACHE_NEW):
        log(f"Downloading {CSV_URL_NEW}")
        with open(CSV_CACHE_NEW, 'wb') as f:
            f.write(http_get(CSV_URL_NEW))

    # Old CSV: 1996-2019 with -YYYYMM suffixes for delisted (good resolution)
    # New CSV: 1996-2026 with bare tickers; we use ONLY its post-2019 tail to
    # backfill the 7yr gap (TSLA, META, ABNB, COIN, CRWD, ...).
    fja_old = parse_csv(args.start, end_date='2019-01-11')
    fja_new = parse_csv(NEW_CSV_CUTOVER, path=CSV_CACHE_NEW)
    log(f"  union: {len(fja_old)} old + {len(fja_new)} new (post-2019)")
    # Merge: new tickers get appended, but their date range can't overlap
    # the old CSV's tail since we cut at 2019-01-11/2019-01-12.
    fja = dict(fja_old)
    for t, span in fja_new.items():
        # If the NEW bare ticker also exists in the OLD CSV (as bare or suffixed),
        # we trust the OLD resolution (which uses suffix info to disambiguate).
        # Only NEW-only tickers get added here.
        bare_in_old = any(t == ot or (ot.startswith(t + '-') and ot.rsplit('-',1)[1].isdigit())
                          for ot in fja_old)
        if bare_in_old:
            continue
        fja[t] = span
    log(f"  combined unique tickers: {len(fja):,}")

    active_cache = 'data/db/_eodhd_us_active.json'
    delisted_cache = 'data/db/_eodhd_us_delisted.json'

    if args.no_network and os.path.exists(active_cache) and os.path.exists(delisted_cache):
        log("Using cached EODHD symbol lists")
        with open(active_cache) as f: active = set(json.load(f))
        with open(delisted_cache) as f: delisted = set(json.load(f))
    else:
        log("Fetching EODHD US symbol lists (2 API calls)")
        active = fetch_eodhd_symbol_list(delisted=False)
        delisted = fetch_eodhd_symbol_list(delisted=True)
        os.makedirs('data/db', exist_ok=True)
        with open(active_cache, 'w') as f: json.dump(sorted(active), f)
        with open(delisted_cache, 'w') as f: json.dump(sorted(delisted), f)

    log("Resolving fja tickers to EODHD symbols")
    resolved = {}      # eodhd -> (fja, first, last)
    unresolved = {}    # fja -> (first, last)
    collisions = []    # multiple fja tickers mapping to same eodhd
    for fja_t, (first, last) in fja.items():
        eod = resolve_ticker(fja_t, active, delisted)
        if eod is None:
            unresolved[fja_t] = [first, last]
        elif eod in resolved:
            collisions.append((fja_t, eod, resolved[eod][0]))
            # Keep the existing one but log
        else:
            resolved[eod] = [fja_t, first, last]

    pct = 100 * len(resolved) // max(len(fja), 1)
    log(f"Resolution: {len(resolved):,}/{len(fja):,} = {pct}% resolved, "
        f"{len(unresolved):,} unresolved, {len(collisions)} collisions")

    if unresolved:
        log("Sample unresolved (up to 20):")
        for k in sorted(unresolved)[:20]:
            log(f"    {k}  (seen {unresolved[k][0]} - {unresolved[k][1]})")

    if collisions:
        log("Sample collisions (up to 10):")
        for fja_t, eod, prior in collisions[:10]:
            log(f"    {fja_t} -> {eod}  (already mapped from {prior})")

    with open(RESOLVED_PATH, 'w') as f:
        json.dump(resolved, f, indent=2, sort_keys=True)
    with open(UNRESOLVED_PATH, 'w') as f:
        json.dump(unresolved, f, indent=2, sort_keys=True)
    log(f"Wrote {RESOLVED_PATH} and {UNRESOLVED_PATH}")

    db = MarketDB()
    db.create_tables()
    write_universe(db, resolved)
    db.close()
    log("DONE")


if __name__ == '__main__':
    main()
