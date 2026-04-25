# -*- coding: utf-8 -*-
"""
Bulk download all EODHD data for a universe into SQLite.

Optimized: fetches classification + quarterly + annual + estimates
in a SINGLE API call per ticker (10 API calls cost instead of 40).

Usage:
    python scripts/bulk_download.py
    python scripts/bulk_download.py --universe russell3000
    python scripts/bulk_download.py --resume   # skip tickers already fetched
"""

import sys
import os
import time
import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from data_manager import MarketDB
from data_sources import EODHDSource, _safe_num

LOG_FILE = 'data/db/bulk_download.log'

# Rate limiting: max requests per second (EODHD allows ~30/sec on paid plans)
REQUEST_DELAY = 0.15  # seconds between requests (~7 req/sec, conservative)
MAX_RETRIES = 3
RETRY_BACKOFF = [10, 30, 60]  # seconds to wait on rate-limit errors


def log(msg, also_print=True):
    """Write to log file and optionally print."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{timestamp}] {msg}"
    if also_print:
        print(line, flush=True)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')


def api_call_with_retry(src, endpoint, params=None):
    """Make an API call with rate limiting and retry on failure."""
    import requests as req_lib

    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(REQUEST_DELAY)
            result = src._get(endpoint, params)
            return result
        except req_lib.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status == 429 or status == 403:
                # Rate limited — back off
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                log(f"    Rate limited (HTTP {status}), waiting {wait}s "
                    f"(attempt {attempt+1}/{MAX_RETRIES})")
                time.sleep(wait)
            elif status == 402:
                # Payment required — API limit exceeded
                log(f"    API limit exceeded (HTTP 402). Waiting 60s...")
                time.sleep(60)
            else:
                raise
        except Exception:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
            else:
                raise
    return None


def parse_quarterly(ticker, data):
    """Parse quarterly balance sheet + income statement into DB rows."""
    bs_data = data.get('Financials::Balance_Sheet::quarterly', {})
    inc_data = data.get('Financials::Income_Statement::quarterly', {})
    shares_stats = data.get('SharesStats', {})
    shares_out = _safe_num(shares_stats.get('SharesOutstanding'))

    all_dates = set()
    if isinstance(bs_data, dict):
        all_dates.update(bs_data.keys())
    if isinstance(inc_data, dict):
        all_dates.update(inc_data.keys())

    rows = []
    for report_date in all_dates:
        bs = bs_data.get(report_date, {}) if isinstance(bs_data, dict) else {}
        inc = inc_data.get(report_date, {}) if isinstance(inc_data, dict) else {}
        if not isinstance(bs, dict):
            bs = {}
        if not isinstance(inc, dict):
            inc = {}

        rows.append({
            'ticker': ticker,
            'report_date': report_date,
            'book_equity': _safe_num(bs.get('totalStockholderEquity')),
            'long_term_debt': _safe_num(bs.get('longTermDebt') or bs.get('longTermDebtTotal')),
            'total_debt': _safe_num(bs.get('shortLongTermDebtTotal')),
            'total_assets': _safe_num(bs.get('totalAssets')),
            'preferred_equity': _safe_num(bs.get('preferredStockTotalEquity')),
            'net_income': _safe_num(inc.get('netIncome')),
            'depreciation': _safe_num(inc.get('depreciationAndAmortization') or
                                      inc.get('reconciledDepreciation')),
            'revenue': _safe_num(inc.get('totalRevenue')),
            'source': 'eodhd',
        })
    return rows, shares_out


def parse_annual(ticker, data):
    """Parse annual income statement + earnings into DB rows."""
    inc_data = data.get('Financials::Income_Statement::yearly', {})
    earn_data = data.get('Earnings::Annual', {})

    all_dates = set()
    if isinstance(inc_data, dict):
        all_dates.update(inc_data.keys())
    if isinstance(earn_data, dict):
        all_dates.update(earn_data.keys())

    rows = []
    for report_date in all_dates:
        inc = inc_data.get(report_date, {}) if isinstance(inc_data, dict) else {}
        earn = earn_data.get(report_date, {}) if isinstance(earn_data, dict) else {}
        if not isinstance(inc, dict):
            inc = {}
        if not isinstance(earn, dict):
            earn = {}

        revenue = _safe_num(inc.get('totalRevenue'))
        eps = _safe_num(earn.get('epsActual'))

        if revenue is not None or eps is not None:
            rows.append({
                'ticker': ticker,
                'report_date': report_date,
                'eps': eps,
                'revenue': revenue,
                'source': 'eodhd',
            })
    return rows


def parse_estimates(ticker, data):
    """Parse analyst estimates from Highlights."""
    highlights = data.get('Highlights', {})
    if not isinstance(highlights, dict):
        return None

    forward_eps = _safe_num(highlights.get('EPSEstimateCurrentYear'))
    growth_ltm = _safe_num(highlights.get('QuarterlyEarningsGrowthYOY'))
    growth_stm = _safe_num(highlights.get('QuarterlyRevenueGrowthYOY'))

    if forward_eps is not None or growth_ltm is not None:
        return {
            'ticker': ticker,
            'as_of_date': datetime.now().strftime('%Y-%m-%d'),
            'forward_eps': forward_eps,
            'growth_ltm': growth_ltm,
            'growth_stm': growth_stm,
            'source': 'eodhd',
        }
    return None


def parse_classification(ticker, data):
    """Parse GICS classification from General."""
    general = data.get('General', {})
    if not isinstance(general, dict):
        return None, None
    return general.get('GicSector'), general.get('GicGroup')


def main():
    parser = argparse.ArgumentParser(description='Bulk download EODHD data')
    parser.add_argument('--universe', default='russell3000')
    parser.add_argument('--resume', action='store_true',
                        help='Skip tickers that already have fundamentals')
    args = parser.parse_args()

    db = MarketDB()
    db.create_tables()
    src = EODHDSource()

    tickers_info = db.get_universe_tickers(args.universe)
    if not tickers_info:
        log(f"ERROR: No tickers in universe '{args.universe}'. Run init first.")
        sys.exit(1)

    tickers = [t[0] for t in tickers_info]
    total = len(tickers)

    log(f"=" * 70)
    log(f"BULK DOWNLOAD: {total} tickers from EODHD")
    log(f"Universe: {args.universe}")
    log(f"Database: {db.db_path}")
    log(f"Log file: {os.path.abspath(LOG_FILE)}")
    log(f"=" * 70)

    # ----------------------------------------------------------------
    # PHASE 1: Prices (1 API call per ticker)
    # ----------------------------------------------------------------
    log(f"\n{'='*70}")
    log(f"PHASE 1/2: DAILY PRICES ({total} tickers)")
    log(f"{'='*70}")

    start = (datetime.now() - timedelta(days=365 * 2 + 60)).strftime('%Y-%m-%d')
    end = datetime.now().strftime('%Y-%m-%d')

    # If resuming, skip tickers that already have EODHD prices
    skip_prices = set()
    if args.resume:
        existing = db.conn.execute(
            "SELECT DISTINCT ticker FROM daily_prices WHERE source='eodhd'"
        ).fetchall()
        skip_prices = {r[0] for r in existing}
        log(f"  Resume mode: skipping {len(skip_prices)} tickers with EODHD prices")

    prices_ok = 0
    prices_fail = 0
    prices_skip = len(skip_prices)
    phase1_start = time.time()

    for i, ticker in enumerate(tickers):
        if ticker in skip_prices:
            continue

        # Progress every 50 tickers
        if i % 50 == 0:
            elapsed = time.time() - phase1_start
            done = prices_ok + prices_fail + prices_skip
            rate = done / elapsed if elapsed > 0 else 1
            remaining = (total - done) / rate / 60 if rate > 0 else 0
            pct = done * 100 // total
            log(f"  PRICES [{done}/{total}] {pct}% | "
                f"{prices_ok} ok, {prices_fail} fail, {prices_skip} skip | "
                f"~{remaining:.0f} min left")

        try:
            price_data = api_call_with_retry(src, f"eod/{src._ticker_symbol(ticker)}", {
                'from': start, 'to': end,
            })
            if price_data:
                records = []
                for row in price_data:
                    records.append((
                        ticker,
                        row['date'],
                        row.get('open'),
                        row.get('high'),
                        row.get('low'),
                        row.get('adjusted_close', row.get('close')),
                        row.get('volume'),
                        None,  # shares_out filled by fundamentals
                        'eodhd'
                    ))
                db.bulk_load_prices(records)
                prices_ok += 1
            else:
                prices_fail += 1
        except Exception as e:
            prices_fail += 1

    phase1_elapsed = time.time() - phase1_start
    log(f"\n  PRICES DONE: {prices_ok} ok, {prices_fail} fail, {prices_skip} skip "
        f"({phase1_elapsed/60:.1f} min)")

    # ----------------------------------------------------------------
    # PHASE 2: Fundamentals + Classification + Estimates (1 combined call)
    # ----------------------------------------------------------------
    log(f"\n{'='*70}")
    log(f"PHASE 2/2: FUNDAMENTALS + GICS + ESTIMATES ({total} tickers)")
    log(f"{'='*70}")

    # If resuming, find tickers we already have fundamentals for
    skip_tickers = set()
    if args.resume:
        existing = db.conn.execute(
            "SELECT DISTINCT ticker FROM fundamentals_quarterly WHERE source='eodhd'"
        ).fetchall()
        skip_tickers = {r[0] for r in existing}
        log(f"  Resume mode: skipping {len(skip_tickers)} already-fetched tickers")

    fund_ok = 0
    fund_fail = 0
    est_count = 0
    gics_count = 0
    phase2_start = time.time()

    for i, ticker in enumerate(tickers):
        if ticker in skip_tickers:
            fund_ok += 1
            continue

        # Progress every 50 tickers
        if i % 50 == 0:
            elapsed = time.time() - phase2_start
            done = fund_ok + fund_fail + len(skip_tickers)
            rate = done / elapsed if elapsed > 0 else 1
            remaining = (total - done) / rate / 60 if rate > 0 else 0
            pct = done * 100 // total
            log(f"  FUND [{done}/{total}] {pct}% | "
                f"{fund_ok} ok, {fund_fail} fail, {est_count} est, {gics_count} gics | "
                f"~{remaining:.0f} min left")

        try:
            data = api_call_with_retry(src,
                f"fundamentals/{src._ticker_symbol(ticker)}",
                {'filter': ','.join([
                    'General',
                    'Financials::Balance_Sheet::quarterly',
                    'Financials::Income_Statement::quarterly',
                    'Financials::Income_Statement::yearly',
                    'Earnings::Annual',
                    'Highlights',
                    'SharesStats',
                ])}
            )
            if not data:
                fund_fail += 1
                continue

            # 1. Quarterly fundamentals
            q_rows, shares_out = parse_quarterly(ticker, data)
            if q_rows:
                df = pd.DataFrame(q_rows)
                db.upsert_fundamentals_q(df)

            # 2. Annual fundamentals
            a_rows = parse_annual(ticker, data)
            if a_rows:
                df = pd.DataFrame(a_rows)
                db.upsert_fundamentals_a(df)

            # 3. Analyst estimates
            est = parse_estimates(ticker, data)
            if est:
                df = pd.DataFrame([est])
                db.upsert_estimates(df)
                est_count += 1

            # 4. GICS classification
            gic_sector, gic_group = parse_classification(ticker, data)
            if gic_sector or gic_group:
                db.update_stock_gics(ticker, args.universe, gic_sector, gic_group)
                gics_count += 1

            # 5. Update shares_out in prices if we got it
            if shares_out:
                db.conn.execute("""
                    UPDATE daily_prices SET shares_out = ?
                    WHERE ticker = ? AND shares_out IS NULL
                """, (shares_out, ticker))
                db.conn.commit()

            fund_ok += 1

        except Exception as e:
            fund_fail += 1

    phase2_elapsed = time.time() - phase2_start
    log(f"\n  FUNDAMENTALS DONE: {fund_ok} ok, {fund_fail} fail "
        f"({phase2_elapsed/60:.1f} min)")
    log(f"  Estimates: {est_count} | GICS classified: {gics_count}")

    # ----------------------------------------------------------------
    # PHASE 3: Risk-free rate
    # ----------------------------------------------------------------
    log(f"\nFetching risk-free rate...")
    try:
        rf = src.fetch_risk_free_rate(start, end)
        if len(rf) > 0:
            n = db.upsert_risk_free_rate(rf)
            log(f"  {n} risk-free rate observations saved")
    except Exception as e:
        log(f"  WARNING: Risk-free rate failed: {e}")

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    total_elapsed = time.time() - phase1_start
    size_mb = os.path.getsize(db.db_path) / (1024 * 1024)

    log(f"\n{'='*70}")
    log(f"BULK DOWNLOAD COMPLETE")
    log(f"{'='*70}")
    log(f"Total time: {total_elapsed/60:.1f} min")
    log(f"Database size: {size_mb:.1f} MB")
    log(f"Prices: {prices_ok} ok, {prices_fail} fail")
    log(f"Fundamentals: {fund_ok} ok, {fund_fail} fail")
    log(f"Estimates: {est_count}")
    log(f"GICS classified: {gics_count}")
    log(f"\nCoverage:")
    coverage = db.coverage_report()
    log(coverage.to_string(index=False))

    # GICS group distribution
    groups = db.conn.execute("""
        SELECT gic_group, COUNT(*) FROM stocks s
        JOIN universes u ON s.universe_id = u.id
        WHERE u.name = ? AND gic_group IS NOT NULL
        GROUP BY gic_group ORDER BY COUNT(*) DESC
    """, (args.universe,)).fetchall()
    if groups:
        log(f"\nGICS Groups ({len(groups)}):")
        for group, count in groups:
            log(f"  {count:4d}  {group}")

    db.close()
    log(f"\nDone. Check {LOG_FILE} for full log.")


if __name__ == '__main__':
    main()
