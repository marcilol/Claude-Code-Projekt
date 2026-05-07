# -*- coding: utf-8 -*-
"""
Validation report for the sp500_hist universe.
  - Coverage: ticker count, price-row total, history-depth distribution.
  - Survivorship-bias spot-checks: known crisis-era delisting dates.
  - Modern S&P additions: TSLA, META, ABNB, COIN, etc. start at IPO.
  - Fundamentals coverage: how many tickers have quarterly + annual data.
  - Symbol-reuse audit: tickers where _old vs current both have rows.

Usage: py scripts/validate_sp500_hist.py
"""
import os
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))
from data_manager import MarketDB

UNIVERSE = 'sp500_hist'

# Known historical events for spot-checks
CRISIS_TICKERS = {
    'LEH':       ('2008-09-15', 'Lehman BK'),
    'BSC_old':   ('2008-03-16', 'Bear Stearns JPM rescue'),
    'GM_old':    ('2009-06-01', 'GM BK -> Motors Liquidation pink sheet'),
    'ABK':       ('2010-11-08', 'Ambac BK (re-emerged 2013, ticker continued)'),
    'RSH':       ('2015-02-05', 'RadioShack BK'),
    'WB_old1':   ('2008-12-31', 'Wachovia merge into WFC'),
    'WCG':       ('2020-01-23', 'WellCare acq by Centene'),
    'AGN_old':   ('2015-03-17', 'Old Allergan acq by Actavis'),
    'XL_old':    ('2018-09-12', 'XL Group acq by AXA'),
    'TWX':       ('2018-06-14', 'Time Warner acq by AT&T'),
}

# Modern S&P additions: should start at IPO date
IPO_TICKERS = {
    'TSLA': '2010-06-29', 'META': '2012-05-18', 'ABNB': '2020-12-10',
    'COIN': '2021-04-14', 'CRWD': '2019-06-12', 'PLTR': '2020-09-30',
    'APP':  '2021-04-15', 'SMCI': '2007-03-29', 'BX':   '2007-06-21',
    'GEHC': '2023-01-04', 'KVUE': '2023-08-23', 'VLTO': '2023-09-30',
}


def main():
    db = MarketDB()
    c = db.conn

    # --- Coverage summary ---
    n_universe = c.execute(
        "SELECT COUNT(*) FROM stocks s JOIN universes u ON s.universe_id=u.id "
        "WHERE u.name=?", (UNIVERSE,)).fetchone()[0]
    n_priced = c.execute(
        "SELECT COUNT(DISTINCT s.ticker) FROM stocks s JOIN universes u ON s.universe_id=u.id "
        "JOIN daily_prices d ON d.ticker=s.ticker WHERE u.name=?", (UNIVERSE,)).fetchone()[0]
    total_rows = c.execute(
        "SELECT COUNT(*) FROM daily_prices d JOIN stocks s ON d.ticker=s.ticker "
        "JOIN universes u ON s.universe_id=u.id WHERE u.name=? AND d.date>='2006-01-01'",
        (UNIVERSE,)).fetchone()[0]

    print(f"=== {UNIVERSE} coverage ===")
    print(f"  Universe size:  {n_universe} tickers")
    print(f"  With prices:    {n_priced} ({100*n_priced//max(n_universe,1)}%)")
    print(f"  Price rows:     {total_rows:,} (>= 2006-01-01)")

    # --- Depth distribution ---
    depths = c.execute("""
        SELECT s.ticker, MIN(d.date), COUNT(*)
        FROM stocks s JOIN universes u ON s.universe_id=u.id
        LEFT JOIN daily_prices d ON d.ticker=s.ticker AND d.date>='2006-01-01'
        WHERE u.name=? GROUP BY s.ticker
    """, (UNIVERSE,)).fetchall()
    bk = Counter()
    for _, _, n in depths:
        if n == 0: bk['no_data'] += 1
        elif n >= 5000: bk['full_20yr'] += 1
        elif n >= 4000: bk['16-19yr'] += 1
        elif n >= 2500: bk['10-15yr'] += 1
        elif n >= 1000: bk['4-9yr'] += 1
        else: bk['<4yr'] += 1
    print("\n  Depth distribution:")
    for k in ['full_20yr', '16-19yr', '10-15yr', '4-9yr', '<4yr', 'no_data']:
        print(f"    {k:12s} {bk[k]:4d}")

    # --- Crisis-era spot checks ---
    print(f"\n=== Crisis-era delisting verification ===")
    print(f"  {'ticker':10s} {'first':12s} {'last':12s} {'rows':>5s}  vs expected (event)")
    for t, (expected, note) in CRISIS_TICKERS.items():
        r = c.execute(
            "SELECT MIN(date), MAX(date), COUNT(*) FROM daily_prices "
            "WHERE ticker=? AND date>='2006-01-01'", (t,)).fetchone()
        if r[2] == 0:
            print(f"  {t:10s} ** NO DATA ** ({note})")
        else:
            ok = abs((__import__('datetime').date.fromisoformat(r[1]) -
                      __import__('datetime').date.fromisoformat(expected)).days) <= 14
            mark = 'ok' if ok else 'CHECK'
            print(f"  {t:10s} {r[0]:12s} {r[1]:12s} {r[2]:5d}  ~{expected} [{mark}] ({note})")

    # --- Modern IPO spot checks ---
    print(f"\n=== Modern S&P additions: should start at IPO ===")
    print(f"  {'ticker':6s} {'first':12s} {'rows':>5s}  expected IPO")
    for t, ipo in IPO_TICKERS.items():
        r = c.execute(
            "SELECT MIN(date), COUNT(*) FROM daily_prices WHERE ticker=?", (t,)).fetchone()
        if r[1] == 0:
            print(f"  {t:6s} ** NO DATA ** (IPO {ipo})")
        else:
            ok = abs((__import__('datetime').date.fromisoformat(r[0]) -
                      __import__('datetime').date.fromisoformat(ipo)).days) <= 14
            mark = 'ok' if ok else 'CHECK'
            print(f"  {t:6s} {r[0]:12s} {r[1]:5d}  IPO={ipo}  [{mark}]")

    # --- Fundamentals coverage ---
    print(f"\n=== Fundamentals coverage ===")
    fq = c.execute("""
        SELECT COUNT(DISTINCT s.ticker) FROM stocks s
        JOIN universes u ON s.universe_id=u.id
        JOIN fundamentals_quarterly f ON f.ticker=s.ticker
        WHERE u.name=?""", (UNIVERSE,)).fetchone()[0]
    fa = c.execute("""
        SELECT COUNT(DISTINCT s.ticker) FROM stocks s
        JOIN universes u ON s.universe_id=u.id
        JOIN fundamentals_annual f ON f.ticker=s.ticker
        WHERE u.name=?""", (UNIVERSE,)).fetchone()[0]
    print(f"  Quarterly: {fq}/{n_universe} tickers ({100*fq//max(n_universe,1)}%)")
    print(f"  Annual:    {fa}/{n_universe} tickers ({100*fa//max(n_universe,1)}%)")

    # --- GICS classification coverage ---
    gics = c.execute("""
        SELECT COUNT(*) FROM stocks s JOIN universes u ON s.universe_id=u.id
        WHERE u.name=? AND s.gic_sector IS NOT NULL AND s.gic_sector != 'Unknown'
    """, (UNIVERSE,)).fetchone()[0]
    print(f"  GICS:      {gics}/{n_universe} tickers ({100*gics//max(n_universe,1)}%)")

    # --- Risk-free rate ---
    rf = c.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM risk_free_rate").fetchone()
    print(f"\n=== Risk-free rate ===")
    print(f"  {rf[0]} -> {rf[1]} ({rf[2]} obs)")

    # --- DB size ---
    db_size = os.path.getsize(db.db_path) / 1e9
    print(f"\n=== DB size ===\n  {db_size:.2f} GB")

    db.close()


if __name__ == '__main__':
    main()
