# -*- coding: utf-8 -*-
"""
CLI tool for managing the market data database.

Handles initialization, incremental fetching, migration from pickle,
and status reporting.

Usage:
    python scripts/update_data.py init --universe russell3000
    python scripts/update_data.py prices --universe russell3000
    python scripts/update_data.py fundamentals --universe russell3000
    python scripts/update_data.py estimates --universe russell3000 --source eodhd
    python scripts/update_data.py status
    python scripts/update_data.py migrate   # one-time: pickle -> SQLite
"""

import sys
import os
import time
import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Load .env file for API keys
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; keys must be in environment

# Allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from data_manager import MarketDB
from data_sources import get_source, YFinanceSource


# ------------------------------------------------------------------ #
#  Universe definitions
# ------------------------------------------------------------------ #

UNIVERSE_FILES = {
    'russell3000': 'data/input/russell_constituents.csv',
}

# EODHD (Morningstar-style) sector labels -> GICS labels used by the factor model.
# The factor model builds industry dummies from these strings, so keeping GICS
# naming preserves column alignment with the cached factor covariance matrix.
EODHD_TO_GICS_SECTOR = {
    'Financial Services':     'Financials',
    'Technology':             'Information Technology',
    'Consumer Cyclical':      'Consumer Discretionary',
    'Consumer Defensive':     'Consumer Staples',
    'Communication Services': 'Communication',
    'Basic Materials':        'Materials',
    'Healthcare':             'Health Care',
    'Industrials':            'Industrials',
    'Energy':                 'Energy',
    'Utilities':              'Utilities',
    'Real Estate':            'Real Estate',
}

# Which EODHD index symbols compose each universe (union).
UNIVERSE_INDEX_CODES = {
    'russell3000': ['RUI.INDX', 'RUT.INDX'],  # Russell 1000 + Russell 2000
    'russell1000': ['RUI.INDX'],
    'russell2000': ['RUT.INDX'],
    'sp500':       ['GSPC.INDX'],
}


def load_universe_from_eodhd(name):
    """Load universe constituents from EODHD (union of one or more indices)."""
    codes = UNIVERSE_INDEX_CODES.get(name)
    if not codes:
        print(f"ERROR: No EODHD index mapping for universe '{name}'. "
              f"Available: {list(UNIVERSE_INDEX_CODES.keys())}")
        sys.exit(1)

    from data_sources import EODHDSource
    src = EODHDSource()

    tickers_sectors = {}
    for code in codes:
        print(f"  Fetching {code} constituents...")
        rows = src.fetch_index_constituents(code)
        print(f"    {len(rows)} constituents")
        for r in rows:
            t = r['ticker']
            if not t:
                continue
            # Normalize to yfinance convention: BRK.B -> BRK-B
            t = t.replace('.', '-')
            # Map Morningstar sector -> GICS; leave unchanged if unmapped
            sector = EODHD_TO_GICS_SECTOR.get(r.get('sector'), r.get('sector') or 'Unknown')
            # First wins on duplicates (RUI+RUT shouldn't overlap, but be safe)
            tickers_sectors.setdefault(t, sector)

    return tickers_sectors


def load_universe_csv(name):
    """Load tickers and sectors from a universe CSV file."""
    path = UNIVERSE_FILES.get(name)
    if not path:
        # Try data/universes/<name>.csv
        path = f'data/universes/{name}.csv'

    if not os.path.exists(path):
        print(f"ERROR: Universe file not found: {path}")
        print(f"Available built-in universes: {list(UNIVERSE_FILES.keys())}")
        sys.exit(1)

    # Read lines, skipping git merge conflict markers
    with open(path, 'r') as f:
        lines = [line for line in f
                 if not line.startswith(('<<<<<<<', '=======', '>>>>>>>'))]

    sep = ';' if ';' in lines[0] else ','
    from io import StringIO
    df = pd.read_csv(StringIO(''.join(lines)), sep=sep)

    # Drop duplicate rows (from resolved merge conflicts)
    df = df.drop_duplicates()

    # Normalize column names (case-insensitive)
    df.columns = [c.strip().lower() for c in df.columns]

    if 'ticker' not in df.columns:
        print(f"ERROR: CSV must have a 'Ticker' column. Found: {list(df.columns)}")
        sys.exit(1)

    sector_col = None
    for col in ['sector', 'industry', 'gics_sector']:
        if col in df.columns:
            sector_col = col
            break

    tickers_sectors = {}
    for _, row in df.iterrows():
        ticker = str(row['ticker']).strip()
        # yfinance uses - instead of . for tickers like BRK.B -> BRK-B
        ticker = ticker.replace('.', '-')
        sector = row[sector_col] if sector_col else 'Unknown'
        tickers_sectors[ticker] = sector

    return tickers_sectors


# ------------------------------------------------------------------ #
#  Subcommands
# ------------------------------------------------------------------ #

def cmd_init(args):
    """Initialize database and load a universe."""
    db = MarketDB()
    db.create_tables()
    print(f"Database initialized: {db.db_path}")

    if args.universe:
        src_name = getattr(args, 'source', 'csv') or 'csv'
        if src_name == 'eodhd':
            print(f"Loading universe '{args.universe}' from EODHD...")
            tickers_sectors = load_universe_from_eodhd(args.universe)
        else:
            tickers_sectors = load_universe_csv(args.universe)

        # Detect currency/exchange from universe name
        currency = 'USD'
        exchange = 'US'
        if 'dax' in args.universe.lower():
            currency, exchange = 'EUR', 'XETRA'
        elif 'nikkei' in args.universe.lower():
            currency, exchange = 'JPY', 'TSE'
        elif 'ftse' in args.universe.lower():
            currency, exchange = 'GBP', 'LSE'

        # Snapshot current members so we can mark removals after reload.
        existing = db.get_universe_tickers(args.universe)
        existing_tickers = {t[0] for t in existing}
        new_tickers = set(tickers_sectors.keys())

        uid = db.add_universe(args.universe, tickers_sectors, currency, exchange,
                              description=f"{len(tickers_sectors)} stocks")
        print(f"Universe '{args.universe}': {len(tickers_sectors)} tickers loaded (id={uid})")

        added = new_tickers - existing_tickers
        removed = existing_tickers - new_tickers
        print(f"  {len(added)} new, {len(removed)} dropped vs previous membership")

        if removed:
            today = datetime.now().strftime('%Y-%m-%d')
            cur = db.conn.cursor()
            cur.executemany("""
                UPDATE stocks SET removed_date = ?
                WHERE ticker = ? AND universe_id = ? AND removed_date IS NULL
            """, [(today, t, uid) for t in removed])
            # Un-mark any ticker that's back (removed_date was set, now in universe)
            cur.executemany("""
                UPDATE stocks SET removed_date = NULL
                WHERE ticker = ? AND universe_id = ?
            """, [(t, uid) for t in new_tickers])
            db.conn.commit()
            print(f"  Marked {len(removed)} stale tickers as removed (historical data preserved)")
    else:
        print("No universe specified. Use --universe to load one.")
        print("\nExisting universes:")
        print(db.list_universes().to_string(index=False))

    db.close()


def cmd_prices(args):
    """Fetch/update daily prices."""
    db = MarketDB()
    universe = args.universe
    exchange = db.get_universe_exchange(universe)
    source = get_source(args.source, exchange=exchange)

    tickers_sectors = db.get_universe_tickers(universe)
    if not tickers_sectors:
        print(f"ERROR: No tickers found for universe '{universe}'. Run 'init' first.")
        db.close()
        sys.exit(1)

    tickers = [t[0] for t in tickers_sectors]
    total = len(tickers)
    print(f"Updating prices for {total} tickers in '{universe}' (source: {source.name})")

    # Determine date range
    years = getattr(args, 'years', 4)
    explicit_start = getattr(args, 'start_date', None)
    if explicit_start:
        # Force-fetch [start_date, today] for every ticker; UPSERT dedups.
        start = explicit_start
    elif args.full:
        start = (datetime.now() - timedelta(days=365 * years + 30)).strftime('%Y-%m-%d')
    else:
        start = None  # will be set per-ticker

    end = datetime.now().strftime('%Y-%m-%d')
    default_start = (explicit_start
                     or (datetime.now() - timedelta(days=365 * years + 30)).strftime('%Y-%m-%d'))

    updated = 0
    skipped = 0
    failed = 0
    start_time = time.time()

    # Fetch risk-free rate first
    print("\nFetching risk-free rate...")
    try:
        rf = source.fetch_risk_free_rate(default_start, end)
        if len(rf) > 0:
            n = db.upsert_risk_free_rate(rf)
            db.log_fetch(None, 'rf', source.name, end, n)
            print(f"  {n} risk-free rate observations saved")
        else:
            print("  WARNING: Could not fetch risk-free rate")
    except Exception as e:
        print(f"  WARNING: Risk-free rate fetch failed: {e}")

    # Fetch prices per ticker
    print(f"\nFetching prices...")
    for i, ticker in enumerate(tickers):
        if (i + 1) % 50 == 0 or i == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            remaining = (total - i) / rate / 60 if rate > 0 else 0
            print(f"[{i+1}/{total}] {(i+1)*100//total}% complete, "
                  f"~{remaining:.0f} min remaining "
                  f"({updated} updated, {skipped} skipped, {failed} failed)",
                  flush=True)

        # Determine start date for this ticker
        if explicit_start:
            # --start-date overrides incremental logic; always fetch full range
            ticker_start = explicit_start
        elif args.full:
            ticker_start = default_start
        else:
            last_date = db.get_last_price_date(ticker)
            if last_date and last_date >= end:
                skipped += 1
                continue
            elif last_date:
                # Fetch from day after last known date
                ticker_start = (pd.Timestamp(last_date) + timedelta(days=1)).strftime('%Y-%m-%d')
            else:
                ticker_start = default_start

        try:
            prices_df = source.fetch_daily_prices([ticker], ticker_start, end)
            if not prices_df.empty:
                n = db.upsert_prices(prices_df)
                db.log_fetch(ticker, 'prices', source.name,
                             prices_df['date'].max().strftime('%Y-%m-%d')
                             if hasattr(prices_df['date'].max(), 'strftime')
                             else str(prices_df['date'].max()),
                             n)
                updated += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            db.log_fetch(ticker, 'prices', source.name, None, 0, status='failed')

        if (i + 1) % 50 == 0:
            time.sleep(0.2)  # Light rate limiting

    elapsed = time.time() - start_time
    print(f"\nDone in {elapsed/60:.1f} min: {updated} updated, {skipped} skipped, {failed} failed")
    db.close()


def cmd_fundamentals(args):
    """Fetch/update quarterly and annual fundamentals."""
    db = MarketDB()
    universe = args.universe
    exchange = db.get_universe_exchange(universe)
    source = get_source(args.source, exchange=exchange)

    tickers_sectors = db.get_universe_tickers(universe)
    if not tickers_sectors:
        print(f"ERROR: No tickers found for universe '{universe}'. Run 'init' first.")
        db.close()
        sys.exit(1)

    tickers = [t[0] for t in tickers_sectors]
    total = len(tickers)
    print(f"Updating fundamentals for {total} tickers in '{universe}' (source: {source.name})")

    updated_q = 0
    updated_a = 0
    failed = 0
    start_time = time.time()

    for i, ticker in enumerate(tickers):
        if (i + 1) % 50 == 0 or i == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            remaining = (total - i) / rate / 60 if rate > 0 else 0
            print(f"[{i+1}/{total}] {(i+1)*100//total}% complete, "
                  f"~{remaining:.0f} min remaining", flush=True)

        # Skip if recently fetched (unless --full)
        if not args.full:
            if not db.needs_update(ticker, 'fundamentals_q', max_age_days=7):
                continue

        try:
            # Quarterly
            q_df = source.fetch_fundamentals_quarterly([ticker])
            if not q_df.empty:
                n = db.upsert_fundamentals_q(q_df)
                db.log_fetch(ticker, 'fundamentals_q', source.name,
                             str(q_df['report_date'].max()), n)
                updated_q += 1

            # Annual
            a_df = source.fetch_fundamentals_annual([ticker])
            if not a_df.empty:
                n = db.upsert_fundamentals_a(a_df)
                db.log_fetch(ticker, 'fundamentals_a', source.name,
                             str(a_df['report_date'].max()), n)
                updated_a += 1

        except Exception:
            failed += 1

        if (i + 1) % 10 == 0:
            time.sleep(0.5)

    elapsed = time.time() - start_time
    print(f"\nDone in {elapsed/60:.1f} min: {updated_q} quarterly, {updated_a} annual, "
          f"{failed} failed")
    db.close()


def cmd_estimates(args):
    """Fetch analyst estimates (requires paid API)."""
    db = MarketDB()
    exchange = db.get_universe_exchange(args.universe)
    try:
        source = get_source(args.source, exchange=exchange)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    tickers_sectors = db.get_universe_tickers(args.universe)
    if not tickers_sectors:
        print(f"ERROR: No tickers found for universe '{args.universe}'.")
        db.close()
        sys.exit(1)

    tickers = [t[0] for t in tickers_sectors]
    print(f"Fetching analyst estimates for {len(tickers)} tickers (source: {source.name})")

    try:
        est_df = source.fetch_analyst_estimates(tickers)
        if not est_df.empty:
            n = db.upsert_estimates(est_df)
            print(f"  {n} estimates saved")
        else:
            print("  No estimates returned")
    except NotImplementedError as e:
        print(f"ERROR: {e}")

    db.close()


def cmd_classify(args):
    """Fetch GICS classification (sector, group) from EODHD and store in stocks table."""
    db_tmp = MarketDB()
    exchange = db_tmp.get_universe_exchange(args.universe)
    db_tmp.close()
    source = get_source(args.source, exchange=exchange)
    if not hasattr(source, 'fetch_classifications'):
        print(f"ERROR: Source '{args.source}' does not support GICS classification fetching.")
        sys.exit(1)

    db = MarketDB()
    tickers_sectors = db.get_universe_tickers(args.universe)
    if not tickers_sectors:
        print(f"ERROR: No tickers found for universe '{args.universe}'.")
        db.close()
        sys.exit(1)

    tickers = [t[0] for t in tickers_sectors]
    print(f"Fetching GICS classification for {len(tickers)} tickers (source: {source.name})")

    start_time = time.time()
    updated = 0

    def progress(ticker, i, total, error=None):
        if (i + 1) % 100 == 0 or i == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            remaining = (total - i) / rate / 60 if rate > 0 else 0
            print(f"  [{i+1}/{total}] ~{remaining:.0f} min remaining, "
                  f"{updated} classified", flush=True)

    results = source.fetch_classifications(tickers, progress_fn=progress)

    for r in results:
        db.update_stock_gics(r['ticker'], args.universe,
                             r.get('gic_sector'), r.get('gic_group'))
        updated += 1

    elapsed = time.time() - start_time
    print(f"\nDone in {elapsed/60:.1f} min: {updated}/{len(tickers)} tickers classified")

    # Show distribution
    groups = db.conn.execute("""
        SELECT gic_group, COUNT(*) FROM stocks s
        JOIN universes u ON s.universe_id = u.id
        WHERE u.name = ? AND gic_group IS NOT NULL
        GROUP BY gic_group ORDER BY COUNT(*) DESC
    """, (args.universe,)).fetchall()
    if groups:
        print(f"\nGICS Group distribution ({len(groups)} groups):")
        for group, count in groups:
            print(f"  {count:4d}  {group}")

    db.close()


def cmd_status(args):
    """Show database status."""
    db = MarketDB()

    # Check if DB exists and has tables
    try:
        universes = db.list_universes()
    except Exception:
        print(f"Database not found or empty: {db.db_path}")
        print("Run 'python scripts/update_data.py init --universe russell3000' first.")
        db.close()
        return

    print(f"Database: {db.db_path}")
    size_mb = os.path.getsize(db.db_path) / (1024 * 1024) if os.path.exists(db.db_path) else 0
    print(f"Size: {size_mb:.1f} MB\n")

    print("Universes:")
    if universes.empty:
        print("  (none)")
    else:
        print(universes.to_string(index=False))

    print("\nData coverage:")
    coverage = db.coverage_report()
    print(coverage.to_string(index=False))

    db.close()


def cmd_migrate(args):
    """
    Migrate existing data into SQLite database.

    Reads from CSV + Excel exports (version-independent) rather than pickle
    (which has pandas version compatibility issues).

    Sources:
      - data/model/russell3000_daily_prices.csv  (prices + shares_outstanding)
      - data/model/russell3000_raw_data_qc.xlsx  (quarterly/annual fundamentals, risk-free rate)
    """
    prices_path = 'data/model/russell3000_daily_prices.csv'
    excel_path = 'data/model/russell3000_raw_data_qc.xlsx'

    missing = []
    if not os.path.exists(prices_path):
        missing.append(prices_path)
    if not os.path.exists(excel_path):
        missing.append(excel_path)
    if missing:
        print(f"ERROR: Required file(s) not found:")
        for m in missing:
            print(f"  {m}")
        print("\nGenerate them first:")
        print("  python scripts/fetch_data.py --export")
        sys.exit(1)

    # Init DB
    db = MarketDB()
    db.create_tables()
    print(f"Database: {db.db_path}")

    # Load universe
    print("\nLoading universe...")
    tickers_sectors = load_universe_csv('russell3000')
    db.add_universe('russell3000', tickers_sectors, 'USD', 'US',
                    description=f"{len(tickers_sectors)} stocks")
    print(f"  Universe 'russell3000': {len(tickers_sectors)} tickers")

    # --- Migrate daily prices from CSV ---
    print(f"\nMigrating daily prices from {prices_path}...")
    start_time = time.time()
    price_records = []
    chunk_size = 50000
    for chunk in pd.read_csv(prices_path, chunksize=chunk_size):
        for _, row in chunk.iterrows():
            price_records.append((
                row['ticker'],
                str(row['date'])[:10],
                _sf(row.get('Open')),
                _sf(row.get('High')),
                _sf(row.get('Low')),
                _sf(row.get('Close')),
                _sf(row.get('Volume')),
                _sf(row.get('shares_outstanding')),
                'yfinance'
            ))
        if len(price_records) % 200000 == 0:
            print(f"  Read {len(price_records):,} rows...", flush=True)

    db.bulk_load_prices(price_records)
    elapsed = time.time() - start_time
    print(f"  {len(price_records):,} price rows loaded ({elapsed:.0f}s)")

    # --- Migrate fundamentals from Excel ---
    print(f"\nMigrating fundamentals from {excel_path}...")

    # Quarterly fundamentals
    print("  Loading quarterly fundamentals...")
    q_df = pd.read_excel(excel_path, sheet_name='Quarterly Fundamentals')
    q_records = []
    for _, row in q_df.iterrows():
        q_records.append((
            row['ticker'],
            str(row['report_date'])[:10],
            _sf(row.get('book_equity')),
            _sf(row.get('net_income')),
            _sf(row.get('depreciation')),
            _sf(row.get('revenue')),
            _sf(row.get('long_term_debt')),
            _sf(row.get('total_debt')),
            _sf(row.get('total_assets')),
            _sf(row.get('preferred_equity')),
            'yfinance'
        ))
    db.bulk_load_fundamentals_q(q_records)
    print(f"    {len(q_records):,} quarterly rows loaded")

    # Annual financials
    print("  Loading annual financials...")
    a_df = pd.read_excel(excel_path, sheet_name='Annual Financials')
    a_records = []
    for _, row in a_df.iterrows():
        a_records.append((
            row['ticker'],
            str(row['report_date'])[:10],
            _sf(row.get('eps')),
            _sf(row.get('revenue')),
            'yfinance'
        ))
    db.bulk_load_fundamentals_a(a_records)
    print(f"    {len(a_records):,} annual rows loaded")

    # Risk-free rate
    print("  Loading risk-free rate...")
    try:
        rf_df = pd.read_excel(excel_path, sheet_name='Risk-Free Rate')
        rf_records = []
        for _, row in rf_df.iterrows():
            if pd.notna(row.get('rf_daily')):
                rf_records.append((
                    str(row['date'])[:10],
                    float(row['rf_daily']),
                    'yfinance'
                ))
        db.bulk_load_risk_free(rf_records)
        print(f"    {len(rf_records)} risk-free rate rows loaded")
    except Exception as e:
        print(f"    WARNING: Could not load risk-free rate: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("Migration complete!")
    size_mb = os.path.getsize(db.db_path) / (1024 * 1024)
    print(f"Database size: {size_mb:.1f} MB")
    print("\nCoverage:")
    print(db.coverage_report().to_string(index=False))

    db.close()


def _sf(val):
    """Safe float conversion for bulk loading."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) else f
    except (ValueError, TypeError):
        return None


# ------------------------------------------------------------------ #
#  CLI parser
# ------------------------------------------------------------------ #

def main():
    parser = argparse.ArgumentParser(
        description='Market data database manager',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/update_data.py init --universe russell3000
  python scripts/update_data.py prices --universe russell3000
  python scripts/update_data.py fundamentals --universe russell3000
  python scripts/update_data.py estimates --universe russell3000 --source eodhd
  python scripts/update_data.py status
  python scripts/update_data.py migrate
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # init
    p_init = subparsers.add_parser('init', help='Initialize DB and load universe')
    p_init.add_argument('--universe', type=str, help='Universe name (e.g. russell3000)')
    p_init.add_argument('--source', type=str, default='csv',
                        choices=['csv', 'eodhd'],
                        help='Universe source: csv (local file) or eodhd (live index)')

    # prices
    p_prices = subparsers.add_parser('prices', help='Fetch/update daily prices')
    p_prices.add_argument('--universe', type=str, required=True)
    p_prices.add_argument('--source', type=str, default='yfinance',
                          choices=['yfinance', 'eodhd'])
    p_prices.add_argument('--full', action='store_true',
                          help='Full re-fetch (ignore existing data)')
    p_prices.add_argument('--years', type=int, default=4,
                          help='Years of history for full fetch (default: 4)')
    p_prices.add_argument('--start-date', dest='start_date', type=str, default=None,
                          help='Explicit YYYY-MM-DD start; forces full-range fetch '
                               'for every ticker (overrides incremental logic).')

    # fundamentals
    p_fund = subparsers.add_parser('fundamentals', help='Fetch/update fundamentals')
    p_fund.add_argument('--universe', type=str, required=True)
    p_fund.add_argument('--source', type=str, default='yfinance',
                         choices=['yfinance', 'eodhd'])
    p_fund.add_argument('--full', action='store_true')

    # estimates
    p_est = subparsers.add_parser('estimates', help='Fetch analyst estimates (paid API)')
    p_est.add_argument('--universe', type=str, required=True)
    p_est.add_argument('--source', type=str, required=True,
                        choices=['eodhd', 'fmp'])

    # classify
    p_cls = subparsers.add_parser('classify', help='Fetch GICS classification from EODHD')
    p_cls.add_argument('--universe', type=str, required=True)
    p_cls.add_argument('--source', type=str, default='eodhd',
                        choices=['eodhd'])

    # status
    subparsers.add_parser('status', help='Show database status')

    # migrate
    subparsers.add_parser('migrate', help='Migrate CSV/Excel data to SQLite')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        'init': cmd_init,
        'prices': cmd_prices,
        'fundamentals': cmd_fundamentals,
        'estimates': cmd_estimates,
        'classify': cmd_classify,
        'status': cmd_status,
        'migrate': cmd_migrate,
    }
    commands[args.command](args)


if __name__ == '__main__':
    main()
