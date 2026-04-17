# -*- coding: utf-8 -*-
"""
Exploratory data analysis for the portfolio-xray market_data.db.

Runs 16 checks grouped into four purposes:
  A. Data accuracy     (checks 1-5)
  B. Descriptive       (checks 6-8)
  C. Model sanity      (checks 9-12)
  D. Insight           (checks 13-16)

Outputs:
  data/eda/eda_report_<date>.html   self-contained HTML report
  data/eda/<NN>_<slug>.csv          raw table behind each check
  data/eda/plots/<NN>_<slug>.png    plots for checks with charts

Run:  py scripts/explore_data.py
"""

import os
import base64
import sqlite3
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
from io import BytesIO
from html import escape

# --------------------------------------------------------------------------- #
#  Config
# --------------------------------------------------------------------------- #

DB_PATH    = os.path.join(os.path.dirname(__file__), '..', 'data', 'db', 'market_data.db')
EDA_DIR    = os.path.join(os.path.dirname(__file__), '..', 'data', 'eda')
PLOTS_DIR  = os.path.join(EDA_DIR, 'plots')
REPORT_FP  = os.path.join(EDA_DIR, f'eda_report_{datetime.now():%Y-%m-%d}.html')

MIN_DATE = '2024-02-09'
MAX_DATE = '2026-04-14'
TODAY    = '2026-04-15'      # added_date marker for newly-added tickers

GICS_SECTORS = [
    'Communication', 'Consumer Discretionary', 'Consumer Staples',
    'Energy', 'Financials', 'Health Care', 'Industrials',
    'Information Technology', 'Materials', 'Real Estate', 'Utilities',
]

# Sections accumulate here; main() writes them out.
_sections = []


def add_section(n, title, headline, body_html='', csv_rel=None, plot_rel=None):
    """Register a section for the HTML report."""
    _sections.append({
        'n': n, 'title': title, 'headline': headline,
        'body': body_html, 'csv': csv_rel, 'plot': plot_rel,
    })


def save_plot(fig, slug):
    path = os.path.join(PLOTS_DIR, f'{slug}.png')
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return os.path.relpath(path, EDA_DIR).replace('\\', '/')


def save_csv(df, slug):
    path = os.path.join(EDA_DIR, f'{slug}.csv')
    df.to_csv(path, index=False)
    return os.path.relpath(path, EDA_DIR).replace('\\', '/')


def df_to_html(df, max_rows=20):
    """Format a DataFrame as a compact HTML table."""
    if len(df) > max_rows:
        df = df.head(max_rows)
    return df.to_html(index=False, float_format=lambda x: f'{x:,.4g}', classes='tbl')


# --------------------------------------------------------------------------- #
#  A. Data accuracy (checks 1-5)
# --------------------------------------------------------------------------- #

def check_01_price_coverage(conn):
    slug = '01_price_coverage'
    q = """
        SELECT p.ticker,
               COUNT(*)          AS days_present,
               MIN(p.date)       AS min_date,
               MAX(p.date)       AS max_date,
               s.sector
        FROM daily_prices p
        LEFT JOIN stocks s ON s.ticker = p.ticker AND s.universe_id = 1
        WHERE s.removed_date IS NULL
        GROUP BY p.ticker
        ORDER BY days_present ASC
    """
    df = pd.read_sql_query(q, conn)
    csv = save_csv(df, slug)

    bins = [0, 50, 100, 200, 300, 400, 500, 600]
    df['band'] = pd.cut(df['days_present'], bins=bins, right=False)
    band_cnt = df['band'].value_counts().sort_index()

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar([str(b) for b in band_cnt.index], band_cnt.values, color='steelblue')
    ax.set_title('Trading days of price history per ticker')
    ax.set_xlabel('Days of data')
    ax.set_ylabel('# tickers')
    for i, v in enumerate(band_cnt.values):
        ax.text(i, v, str(int(v)), ha='center', va='bottom', fontsize=9)
    plot = save_plot(fig, slug)

    short = int((df['days_present'] < 50).sum())
    mid   = int(((df['days_present'] >= 50) & (df['days_present'] < 400)).sum())
    full  = int((df['days_present'] >= 400).sum())

    body = f"""
    <p>Per active ticker, how many trading days of price history we have between {MIN_DATE} and {MAX_DATE}.
    Bimodal = healthy (tickers either have ~500 days or are missing). Tickers in the middle need attention.</p>
    {df_to_html(df.head(15).drop(columns='band'))}
    <p><i>Top 15 shortest histories (potential bad fetches). Full CSV has all {len(df)} active tickers.</i></p>
    """
    add_section(1,
        'Price history coverage per ticker',
        f'{full} tickers have ≥ 400 days, {mid} in 50–399 (investigate), {short} with < 50 days.',
        body, csv_rel=csv, plot_rel=plot)


def check_02_stale_tickers(conn):
    slug = '02_stale_tickers'
    q = """
        SELECT p.ticker, MAX(p.date) AS max_date, s.sector
        FROM daily_prices p
        LEFT JOIN stocks s ON s.ticker = p.ticker AND s.universe_id = 1
        WHERE s.removed_date IS NULL
        GROUP BY p.ticker
    """
    df = pd.read_sql_query(q, conn)
    df['days_stale'] = (pd.to_datetime(MAX_DATE) - pd.to_datetime(df['max_date'])).dt.days
    df = df.sort_values('days_stale', ascending=False)
    csv = save_csv(df, slug)

    stale = df[df['days_stale'] > 7]
    sector_counts = stale['sector'].value_counts().to_dict()
    body = f"""
    <p>Tickers whose newest price row is more than 7 days behind the panel max date ({MAX_DATE}).
    Most are likely delistings, halts, or illiquid names yfinance stopped updating.</p>
    <p><b>Breakdown by sector:</b> {sector_counts}</p>
    {df_to_html(stale.head(30))}
    """
    add_section(2,
        'Stale tickers (max_date > 7 days behind)',
        f'{len(stale)} active tickers have prices older than 2026-04-07.',
        body, csv_rel=csv)


def check_03_fund_price_join(conn):
    slug = '03_fundamentals_prices_join'
    q = """
        SELECT s.ticker, s.sector,
               (SELECT MAX(date)        FROM daily_prices           WHERE ticker=s.ticker) AS last_price,
               (SELECT MAX(report_date) FROM fundamentals_quarterly WHERE ticker=s.ticker) AS last_fund_q,
               (SELECT MAX(as_of_date)  FROM analyst_estimates      WHERE ticker=s.ticker) AS last_estimate
        FROM stocks s
        WHERE s.universe_id = 1 AND s.removed_date IS NULL
    """
    df = pd.read_sql_query(q, conn)
    ref = pd.to_datetime(MAX_DATE)
    for col in ['last_price', 'last_fund_q', 'last_estimate']:
        df[col + '_age_days'] = (ref - pd.to_datetime(df[col])).dt.days

    has_price   = df['last_price'].notna()
    has_fund    = df['last_fund_q'].notna() & (df['last_fund_q_age_days'] <= 180)
    has_est     = df['last_estimate'].notna()
    full        = has_price & has_fund & has_est

    df['has_price']    = has_price
    df['has_fund_180'] = has_fund
    df['has_estimate'] = has_est
    df['full_coverage'] = full
    csv = save_csv(df, slug)

    summary = pd.DataFrame({
        'check': ['any prices', 'fundamentals within 180d', 'estimates', 'ALL three'],
        'count_yes': [int(has_price.sum()), int(has_fund.sum()),
                      int(has_est.sum()), int(full.sum())],
        'count_no':  [int((~has_price).sum()), int((~has_fund).sum()),
                      int((~has_est).sum()), int((~full).sum())],
    })
    summary['pct_yes'] = 100 * summary['count_yes'] / (summary['count_yes'] + summary['count_no'])

    body = f"""
    <p>For every active universe member, do we have the three main data dimensions needed for the factor model?</p>
    {df_to_html(summary)}
    <p>Tickers missing fundamentals within the last 180d will have book_equity, leverage, and growth descriptors set to NaN,
    dropping them from the cross-sectional regression for those factors (but they can still contribute to Size/Beta/Momentum).</p>
    """
    add_section(3,
        'Fundamentals–prices–estimates join rate',
        f'{int(full.sum())} of {len(df)} active tickers ({100*full.mean():.1f}%) have full coverage.',
        body, csv_rel=csv)


def check_04_sector_taxonomy_sanity(conn):
    slug = '04_sector_taxonomy'
    q = """
        SELECT sector, COUNT(*) AS n
        FROM stocks
        WHERE universe_id = 1 AND removed_date IS NULL
        GROUP BY sector
        ORDER BY n DESC
    """
    df = pd.read_sql_query(q, conn)
    csv = save_csv(df, slug)

    expected = set(GICS_SECTORS) | {'Unknown'}
    unexpected = df[~df['sector'].isin(expected)]
    total = int(df['n'].sum())

    body = f"""
    <p>After the EODHD→GICS mapping, the 11 GICS sector labels should account for essentially all tickers.
    Anything outside the known set is a mapping leak.</p>
    {df_to_html(df)}
    <p><b>Unexpected labels:</b> {'none ✓' if unexpected.empty else df_to_html(unexpected)}</p>
    """
    add_section(4,
        'Sector label taxonomy audit',
        f'{len(df)} distinct labels across {total} tickers; '
        f'{"0 unexpected ✓" if unexpected.empty else str(len(unexpected)) + " unexpected ✗"}.',
        body, csv_rel=csv)


def check_05_ticker_format_collisions(conn):
    slug = '05_ticker_collisions'
    active = pd.read_sql_query(
        "SELECT ticker FROM stocks WHERE universe_id=1 AND removed_date IS NULL", conn
    )['ticker'].tolist()
    active_set = set(active)
    collisions = []
    for t in active:
        if '-' in t:
            alt = t.replace('-', '')
            if alt in active_set:
                collisions.append((t, alt))
    df = pd.DataFrame(collisions, columns=['with_dash', 'without_dash'])
    csv = save_csv(df, slug)

    body = f"""
    <p>Class-share tickers can appear in two formats: <code>BRK-B</code> (yfinance) and <code>BRKB</code>
    (legacy CSV). If both versions exist as active members, we've fragmented a single company's history.</p>
    {df_to_html(df) if not df.empty else '<p>No collisions found ✓</p>'}
    """
    add_section(5,
        'Ticker format collisions (dash vs no-dash)',
        f'{len(df)} potential collisions found.',
        body, csv_rel=csv)


# --------------------------------------------------------------------------- #
#  B. Descriptive (checks 6-8)
# --------------------------------------------------------------------------- #

def _get_latest_market_cap(conn, date=MAX_DATE, lookback_days=30):
    """Compute market_cap = close * shares_out, using most recent non-null pair per ticker.
       Falls back to the latest available shares_out within `lookback_days`."""
    q = f"""
        SELECT p.ticker, p.date, p.close, p.shares_out
        FROM daily_prices p
        JOIN stocks s ON s.ticker=p.ticker AND s.universe_id=1
        WHERE s.removed_date IS NULL
          AND p.date BETWEEN date('{date}', '-{lookback_days} days') AND '{date}'
        ORDER BY p.ticker, p.date DESC
    """
    df = pd.read_sql_query(q, conn)
    # Latest close per ticker
    latest_close = df.drop_duplicates('ticker', keep='first')[['ticker', 'close']]
    # Latest non-null shares_out per ticker
    so = df.dropna(subset=['shares_out'])
    latest_so = so.drop_duplicates('ticker', keep='first')[['ticker', 'shares_out']]
    mc = latest_close.merge(latest_so, on='ticker', how='left')
    mc['market_cap'] = mc['close'] * mc['shares_out']
    return mc


def check_06_sector_size_distribution(conn):
    slug = '06_sector_size'
    mc = _get_latest_market_cap(conn)
    sectors = pd.read_sql_query(
        "SELECT ticker, sector FROM stocks WHERE universe_id=1 AND removed_date IS NULL", conn
    )
    df = mc.merge(sectors, on='ticker', how='left')
    df = df.dropna(subset=['market_cap', 'sector'])
    df['cap_decile'] = pd.qcut(df['market_cap'].rank(method='first'), 10,
                               labels=[f'D{i+1}' for i in range(10)])
    csv = save_csv(df, slug)

    pivot = df.groupby(['sector', 'cap_decile'], observed=True).size().unstack(fill_value=0)
    pivot = pivot.reindex(GICS_SECTORS, fill_value=0)

    fig, ax = plt.subplots(figsize=(11, 5.5))
    pivot.plot(kind='bar', stacked=True, ax=ax, colormap='viridis')
    ax.set_title(f'Tickers by sector × market-cap decile (latest date {MAX_DATE})')
    ax.set_ylabel('# tickers')
    ax.set_xlabel('')
    ax.legend(title='Cap decile (D1=smallest)', bbox_to_anchor=(1.02, 1), loc='upper left', fontsize=8)
    plt.xticks(rotation=35, ha='right')
    plot = save_plot(fig, slug)

    largest_sector = pivot.sum(axis=1).idxmax()
    largest_count = int(pivot.sum(axis=1).max())

    pivot_html = df_to_html(pivot.reset_index())
    body = f"""
    <p>Distribution of tickers across sectors and market-cap deciles on {MAX_DATE}.
    D10 holds the largest stocks; D1 the smallest.</p>
    {pivot_html}
    """
    add_section(6,
        'Sector × market-cap distribution',
        f'{largest_sector} is the largest sector by count ({largest_count} tickers).',
        body, csv_rel=csv, plot_rel=plot)


def check_07_newly_added(conn):
    slug = '07_newly_added'
    q = f"""
        SELECT s.ticker, s.sector, s.added_date,
               (SELECT MIN(date) FROM daily_prices WHERE ticker=s.ticker) AS first_price,
               (SELECT MAX(date) FROM daily_prices WHERE ticker=s.ticker) AS last_price,
               (SELECT close * shares_out FROM daily_prices
                 WHERE ticker=s.ticker AND shares_out IS NOT NULL
                 ORDER BY date DESC LIMIT 1) AS market_cap_est
        FROM stocks s
        WHERE s.universe_id=1 AND s.added_date = '{TODAY}' AND s.removed_date IS NULL
    """
    df = pd.read_sql_query(q, conn)
    df['has_price']      = df['first_price'].notna()
    df['has_market_cap'] = df['market_cap_est'].notna()
    csv = save_csv(df, slug)

    by_sector = df.groupby('sector').size().sort_values(ascending=False)

    fig, ax = plt.subplots(figsize=(9, 4))
    mc_vals = df['market_cap_est'].dropna()
    if len(mc_vals) > 0:
        ax.hist(np.log10(mc_vals[mc_vals > 0]), bins=30, color='teal')
        ax.set_title(f'Newly-added tickers: market-cap distribution (log10 $)')
        ax.set_xlabel('log10(market cap, $)')
        ax.set_ylabel('# tickers')
    plot = save_plot(fig, slug)

    n_with = int(df['has_market_cap'].sum())
    by_sector_df = by_sector.reset_index()
    by_sector_df.columns = ['sector', 'n']
    by_sector_html = df_to_html(by_sector_df)
    body = f"""
    <p>Tickers added to the universe today ({TODAY}) — the delta from the old iShares-sampled CSV
    to the full Russell 1000+2000 union.</p>
    <p><b>By sector:</b></p>
    {by_sector_html}
    <p><b>Data coverage within new set:</b> {int(df['has_price'].sum())}/{len(df)} have prices,
    {n_with} have computable market cap.</p>
    """
    add_section(7,
        'Newly-added tickers (658 added by EODHD refresh)',
        f'{len(df)} added; median log10 market cap ≈ '
        f'{np.log10(mc_vals.median()):.2f}' if len(mc_vals) > 0 else f'{len(df)} added (no market caps computable).',
        body, csv_rel=csv, plot_rel=plot)


def check_08_removed_tickers(conn):
    slug = '08_removed_tickers'
    q = f"""
        SELECT s.ticker, s.sector, s.removed_date,
               (SELECT MAX(date) FROM daily_prices WHERE ticker=s.ticker) AS last_price,
               (SELECT close FROM daily_prices WHERE ticker=s.ticker ORDER BY date DESC LIMIT 1) AS last_close
        FROM stocks s
        WHERE s.universe_id=1 AND s.removed_date IS NOT NULL
    """
    df = pd.read_sql_query(q, conn)
    df['days_since_last_price'] = (pd.to_datetime(MAX_DATE) - pd.to_datetime(df['last_price'])).dt.days

    # Classify
    def classify(row):
        if pd.isna(row['last_price']):
            return 'never-fetched'
        d = row['days_since_last_price']
        if d <= 2:
            return 'recent-price (maybe reclassified)'
        if d <= 30:
            return 'recent-ish (<30d gap)'
        if d <= 180:
            return 'likely-delisted (<180d)'
        return 'long-delisted (>180d)'
    df['classification'] = df.apply(classify, axis=1)
    csv = save_csv(df, slug)

    summary = df['classification'].value_counts().reset_index()
    summary.columns = ['classification', 'n']
    body = f"""
    <p>The 313 tickers dropped from our universe in today's EODHD refresh, classified by when yfinance
    last had a price for them.</p>
    {df_to_html(summary)}
    """
    add_section(8,
        'Removed tickers — why were they dropped?',
        f'{len(df)} removed; {summary.iloc[0]["n"] if len(summary) else 0} in the largest bucket ({summary.iloc[0]["classification"] if len(summary) else "n/a"}).',
        body, csv_rel=csv)


# --------------------------------------------------------------------------- #
#  C. Model sanity (checks 9-12)
# --------------------------------------------------------------------------- #

def check_09_factor_coverage(conn):
    slug = '09_factor_coverage'
    mc = _get_latest_market_cap(conn)
    active = pd.read_sql_query(
        "SELECT ticker FROM stocks WHERE universe_id=1 AND removed_date IS NULL", conn
    )
    latest_fq = pd.read_sql_query(f"""
        SELECT ticker, book_equity, net_income, total_debt, total_assets
        FROM fundamentals_quarterly
        WHERE report_date = (SELECT MAX(report_date) FROM fundamentals_quarterly f2 WHERE f2.ticker=fundamentals_quarterly.ticker)
    """, conn)
    est = pd.read_sql_query("SELECT ticker, forward_eps, growth_ltm, growth_stm FROM analyst_estimates", conn)

    df = active.merge(mc[['ticker', 'close', 'market_cap']], on='ticker', how='left')
    df = df.merge(latest_fq, on='ticker', how='left')
    df = df.merge(est, on='ticker', how='left')

    checks = {
        'Size (market_cap)':         df['market_cap'].notna(),
        'Book equity (BTOP num)':    df['book_equity'].notna(),
        'Earnings (net_income)':     df['net_income'].notna(),
        'Leverage (total_debt/ta)':  df['total_debt'].notna() & df['total_assets'].notna(),
        'Forward EPS (EPFWD)':       df['forward_eps'].notna(),
        'Growth LTM (EGRLF-proxy)':  df['growth_ltm'].notna(),
        'Growth STM (EGRSF-proxy)':  df['growth_stm'].notna(),
    }
    rows = []
    for name, mask in checks.items():
        rows.append({'descriptor': name, 'coverage_pct': 100 * mask.mean(),
                     'n_with': int(mask.sum()), 'n_without': int((~mask).sum())})
    summary = pd.DataFrame(rows).sort_values('coverage_pct', ascending=False)
    csv = save_csv(summary, slug)

    body = f"""
    <p>For each raw descriptor used by the CNE5-style factor model, what fraction of the active universe
    has a usable value today. &lt; 80% = noisy; &lt; 50% = factor effectively broken.</p>
    {df_to_html(summary)}
    <p><i>Note: beta and momentum are time-series factors; computing them requires running <code>fetch_data.py --from-db</code> first. This check only covers raw cross-sectional descriptors.</i></p>
    """
    worst = summary.iloc[-1]
    add_section(9,
        'Factor descriptor coverage (cross-sectional)',
        f'Best: {summary.iloc[0]["descriptor"]} at {summary.iloc[0]["coverage_pct"]:.1f}%. '
        f'Worst: {worst["descriptor"]} at {worst["coverage_pct"]:.1f}%.',
        body, csv_rel=csv)


def check_10_epfwd_distribution(conn):
    slug = '10_epfwd'
    mc = _get_latest_market_cap(conn)
    est = pd.read_sql_query(
        "SELECT ticker, forward_eps FROM analyst_estimates WHERE forward_eps IS NOT NULL", conn
    )
    df = mc.merge(est, on='ticker', how='inner')
    df['epfwd'] = df['forward_eps'] / df['close']
    df = df.dropna(subset=['epfwd'])
    df = df[np.isfinite(df['epfwd'])]
    csv = save_csv(df, slug)

    q = df['epfwd'].quantile([0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])

    fig, ax = plt.subplots(figsize=(9, 4))
    clip = df['epfwd'].clip(-0.1, 0.25)
    ax.hist(clip, bins=80, color='darkorange')
    ax.axvline(q[0.5], color='k', linestyle='--', label=f'median={q[0.5]:.3f}')
    ax.set_title('EPFWD = forward_eps / last_close  (clipped to [-0.1, 0.25])')
    ax.set_xlabel('Forward earnings yield')
    ax.set_ylabel('# tickers')
    ax.legend()
    plot = save_plot(fig, slug)

    in_range = df[(df['epfwd'] >= 0.02) & (df['epfwd'] <= 0.08)]
    outliers_hi = df[df['epfwd'] > 0.25]
    outliers_lo = df[df['epfwd'] < 0]
    body = f"""
    <p>Forward earnings yield = forward_eps / last_close. Sensible values cluster 2–8%.</p>
    <p><b>Quantiles:</b> {dict(q.round(4))}</p>
    <p><b>Classification:</b> {len(in_range)} in 2-8% range, {len(outliers_hi)} > 25% (likely bad data or distressed equity),
    {len(outliers_lo)} negative (loss-making guidance).</p>
    """
    add_section(10,
        'EPFWD (forward earnings yield) distribution',
        f'Median EPFWD = {q[0.5]:.3f}; {len(in_range)} tickers in the sensible 2-8% band.',
        body, csv_rel=csv, plot_rel=plot)


def check_11_growth_estimate_sanity(conn):
    slug = '11_growth_sanity'
    # Realized YoY quarterly net income growth
    fq = pd.read_sql_query("""
        SELECT ticker, report_date, net_income
        FROM fundamentals_quarterly
        WHERE net_income IS NOT NULL
        ORDER BY ticker, report_date
    """, conn)
    fq['lag4_ni'] = fq.groupby('ticker')['net_income'].shift(4)
    fq = fq.dropna(subset=['lag4_ni'])
    # Guard: skip if lag4_ni <= 0 (growth ratio ill-defined); use abs for denominator
    fq['realized_yoy'] = (fq['net_income'] - fq['lag4_ni']) / fq['lag4_ni'].abs()
    # Latest realized YoY per ticker
    latest = fq.sort_values('report_date').drop_duplicates('ticker', keep='last')[['ticker', 'realized_yoy']]

    est = pd.read_sql_query(
        "SELECT ticker, growth_ltm FROM analyst_estimates WHERE growth_ltm IS NOT NULL", conn
    )
    df = latest.merge(est, on='ticker', how='inner')
    df = df[np.isfinite(df['realized_yoy']) & np.isfinite(df['growth_ltm'])]
    # Clip extreme values for correlation to avoid leverage points
    c_df = df[(df['realized_yoy'].abs() < 5) & (df['growth_ltm'].abs() < 5)]
    csv = save_csv(df, slug)

    corr = c_df[['realized_yoy', 'growth_ltm']].corr().iloc[0, 1] if len(c_df) > 2 else np.nan

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(c_df['realized_yoy'], c_df['growth_ltm'], s=5, alpha=0.4)
    ax.set_xlim(-2, 2); ax.set_ylim(-2, 2)
    ax.axhline(0, color='grey', lw=0.5); ax.axvline(0, color='grey', lw=0.5)
    ax.plot([-2, 2], [-2, 2], 'k--', lw=0.5, label='y=x')
    ax.set_xlabel('Realized YoY quarterly NI growth')
    ax.set_ylabel("EODHD growth_ltm (QuarterlyEarningsGrowthYOY)")
    ax.set_title(f'Analyst estimate vs realized YoY (ρ = {corr:.3f})')
    ax.legend()
    plot = save_plot(fig, slug)

    body = f"""
    <p>EODHD's <code>growth_ltm</code> is labeled as QuarterlyEarningsGrowthYOY. We compare it against the
    YoY quarterly net-income growth we compute from <code>fundamentals_quarterly</code>. Positive correlation
    is expected; a strong correlation (&gt; 0.5) with slope near 1 means EODHD returns essentially the realized
    (not forward) number — useful but relabel in documentation.</p>
    <p><b>Sample size:</b> {len(c_df)} tickers after outlier trim.</p>
    <p><b>Correlation:</b> {corr:.3f}</p>
    """
    add_section(11,
        'Growth estimate vs realized YoY growth',
        f'ρ(growth_ltm, realized_yoy) = {corr:.3f} on {len(c_df)} tickers.',
        body, csv_rel=csv, plot_rel=plot)


def check_12_price_outliers(conn):
    slug = '12_price_outliers'
    q = f"""
        SELECT p.ticker, p.date, p.close, p.volume, s.sector
        FROM daily_prices p
        JOIN stocks s ON s.ticker=p.ticker AND s.universe_id=1
        WHERE s.removed_date IS NULL AND p.date='{MAX_DATE}'
          AND (p.close < 1 OR p.close > 10000)
        ORDER BY p.close
    """
    df = pd.read_sql_query(q, conn)
    csv = save_csv(df, slug)

    body = f"""
    <p>Tickers with latest close &lt; $1 (penny stocks / distressed) or &gt; $10,000 (likely unadjusted split data).
    These often distort cross-sectional z-scoring even after winsorization.</p>
    {df_to_html(df) if not df.empty else '<p>None ✓</p>'}
    """
    add_section(12,
        'Price outliers (< $1 or > $10,000)',
        f'{len(df)} outliers on {MAX_DATE}.',
        body, csv_rel=csv)


# --------------------------------------------------------------------------- #
#  D. Insight (checks 13-16)
# --------------------------------------------------------------------------- #

def _daily_returns_panel(conn):
    """Build a (date x ticker) daily close panel and returns for the active universe."""
    q = """
        SELECT p.ticker, p.date, p.close
        FROM daily_prices p
        JOIN stocks s ON s.ticker=p.ticker AND s.universe_id=1
        WHERE s.removed_date IS NULL
    """
    df = pd.read_sql_query(q, conn, parse_dates=['date'])
    panel = df.pivot(index='date', columns='ticker', values='close').sort_index()
    rets = np.log(panel / panel.shift(1))
    return panel, rets


def check_13_sector_dispersion(conn):
    slug = '13_sector_dispersion'
    panel, rets = _daily_returns_panel(conn)
    sectors = pd.read_sql_query(
        "SELECT ticker, sector FROM stocks WHERE universe_id=1 AND removed_date IS NULL", conn
    )
    sec_map = dict(zip(sectors['ticker'], sectors['sector']))

    # Cumulative return over full window per ticker
    cum = (panel.iloc[-1] / panel.iloc[0]).apply(lambda x: np.log(x) if pd.notna(x) and x > 0 else np.nan)
    by_sector = pd.DataFrame({
        'ticker': cum.index,
        'cum_log_ret': cum.values,
        'sector': [sec_map.get(t, 'Unknown') for t in cum.index],
    }).dropna()
    agg = by_sector.groupby('sector')['cum_log_ret'].agg(['mean', 'std', 'count']).sort_values('std', ascending=False)
    csv = save_csv(agg.reset_index(), slug)

    fig, ax = plt.subplots(figsize=(10, 5))
    agg['std'].plot(kind='bar', ax=ax, color='darkgreen')
    ax.set_title(f'Within-sector dispersion of cumulative log returns ({MIN_DATE} → {MAX_DATE})')
    ax.set_ylabel('Std of log cumulative return')
    plt.xticks(rotation=35, ha='right')
    plot = save_plot(fig, slug)

    body = f"""
    <p>For each sector, the standard deviation of cumulative log returns across its constituents over
    the sample window. High dispersion = more stock-picking alpha available.
    Low dispersion = returns dominated by the factor, not stock selection.</p>
    {df_to_html(agg.reset_index())}
    """
    add_section(13,
        'Sector return dispersion',
        f'Most dispersed: {agg.index[0]} (σ={agg.iloc[0]["std"]:.2f}). Least: {agg.index[-1]} (σ={agg.iloc[-1]["std"]:.2f}).',
        body, csv_rel=csv, plot_rel=plot)


def check_14_beta_return_correlation(conn):
    slug = '14_beta_return_corr'
    panel, rets = _daily_returns_panel(conn)

    # Proxy market: equal-weighted mean daily return across universe
    mkt = rets.mean(axis=1)

    # 60-day rolling beta: cov(ret_i, mkt) / var(mkt), updated daily
    var_mkt = mkt.rolling(60, min_periods=30).var()
    cov_im  = rets.rolling(60, min_periods=30).cov(mkt)
    beta = cov_im.div(var_mkt, axis=0)

    # For each date, cross-sectional correlation between today's return and today's beta
    common_idx = beta.index.intersection(rets.index)
    rets_a  = rets.reindex(common_idx)
    beta_a  = beta.reindex(common_idx)

    corrs = []
    mkt_rets = []
    for d in common_idx:
        r = rets_a.loc[d]
        b = beta_a.loc[d]
        mask = r.notna() & b.notna()
        if mask.sum() < 100:
            continue
        corrs.append(r[mask].corr(b[mask]))
        mkt_rets.append(mkt.loc[d])

    out = pd.DataFrame({'market_ret': mkt_rets, 'cs_corr_ret_beta': corrs})
    out.index = common_idx[:len(corrs)]
    csv = save_csv(out.reset_index().rename(columns={'index': 'date'}), slug)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(out['market_ret'], out['cs_corr_ret_beta'], s=6, alpha=0.45)
    ax.axhline(0, color='grey', lw=0.5)
    ax.axvline(0, color='grey', lw=0.5)
    ax.set_title('Daily cross-sectional corr(return, beta) vs market return')
    ax.set_xlabel('Market return (EW avg)')
    ax.set_ylabel('cs corr(return, beta)')
    plot = save_plot(fig, slug)

    # Slope of corr vs market return (should be positive)
    if len(out) > 10:
        slope = np.polyfit(out['market_ret'], out['cs_corr_ret_beta'], 1)[0]
    else:
        slope = np.nan

    body = f"""
    <p>On up-market days, high-beta stocks should outperform; on down-market days, underperform. So cross-sectional
    corr(daily_return, beta) should scale linearly with the market return. The regression slope below should be large and positive.</p>
    <p><b>Slope of cs-corr vs mkt return:</b> {slope:.2f}</p>
    <p><b>Average cs-corr:</b> {out['cs_corr_ret_beta'].mean():.3f}</p>
    <p>Data points: {len(out)} trading days.</p>
    """
    add_section(14,
        'Cross-sectional return × beta correlation per date',
        f'slope = {slope:.2f} — {"positive ✓ (expected)" if slope > 0 else "non-positive ✗ (investigate)"}',
        body, csv_rel=csv, plot_rel=plot)


def check_15_sector_growth_bullishness(conn):
    slug = '15_sector_growth'
    est = pd.read_sql_query(
        "SELECT ticker, growth_ltm, growth_stm FROM analyst_estimates", conn
    )
    sec = pd.read_sql_query(
        "SELECT ticker, sector FROM stocks WHERE universe_id=1 AND removed_date IS NULL", conn
    )
    df = est.merge(sec, on='ticker', how='inner')
    # Median (robust to outliers)
    agg = df.groupby('sector').agg(
        n=('ticker', 'count'),
        median_ltm=('growth_ltm', 'median'),
        median_stm=('growth_stm', 'median'),
    ).sort_values('median_ltm', ascending=False)
    csv = save_csv(agg.reset_index(), slug)

    fig, ax = plt.subplots(figsize=(10, 5))
    agg[['median_ltm', 'median_stm']].plot(kind='bar', ax=ax)
    ax.set_title('Analyst-estimated YoY growth by sector (medians)')
    ax.set_ylabel('Median YoY growth')
    ax.axhline(0, color='k', lw=0.5)
    plt.xticks(rotation=35, ha='right')
    plot = save_plot(fig, slug)

    body = f"""
    <p>Sector medians of EODHD's <code>growth_ltm</code> (earnings YoY proxy) and <code>growth_stm</code>
    (revenue YoY proxy). Read as "which sectors are analysts most bullish on today." Sanity-check against
    current narratives before trusting as signal.</p>
    {df_to_html(agg.reset_index())}
    """
    add_section(15,
        'Analyst-estimated growth by sector',
        f'Most bullish (earnings): {agg.index[0]} ({agg.iloc[0]["median_ltm"]:.2%}). '
        f'Least: {agg.index[-1]} ({agg.iloc[-1]["median_ltm"]:.2%}).',
        body, csv_rel=csv, plot_rel=plot)


def check_16_missingness_by_size(conn):
    slug = '16_missingness_by_size'
    mc = _get_latest_market_cap(conn)
    fund = pd.read_sql_query(
        "SELECT DISTINCT ticker FROM fundamentals_quarterly", conn
    )['ticker'].tolist()
    est = pd.read_sql_query(
        "SELECT DISTINCT ticker FROM analyst_estimates", conn
    )['ticker'].tolist()

    df = mc.copy()
    df['has_fund'] = df['ticker'].isin(fund)
    df['has_est']  = df['ticker'].isin(est)
    df = df.dropna(subset=['market_cap'])
    df['cap_decile'] = pd.qcut(df['market_cap'].rank(method='first'), 10,
                               labels=[f'D{i+1}' for i in range(10)])
    by_dec = df.groupby('cap_decile', observed=True).agg(
        n=('ticker', 'count'),
        pct_with_fund=('has_fund', 'mean'),
        pct_with_est=('has_est', 'mean'),
    )
    by_dec['pct_with_fund'] = 100 * by_dec['pct_with_fund']
    by_dec['pct_with_est']  = 100 * by_dec['pct_with_est']
    csv = save_csv(by_dec.reset_index(), slug)

    fig, ax = plt.subplots(figsize=(10, 4.5))
    by_dec[['pct_with_fund', 'pct_with_est']].plot(kind='bar', ax=ax)
    ax.set_title('Data-coverage rates by market-cap decile')
    ax.set_ylabel('% of tickers with data')
    ax.set_ylim(0, 105)
    plt.xticks(rotation=0)
    plot = save_plot(fig, slug)

    bottom_dec = by_dec.iloc[0]
    top_dec    = by_dec.iloc[-1]
    body = f"""
    <p>If fetch-failures are concentrated in small-caps, that's expected attrition (yfinance lacks data
    on some micro-caps). If failures are uniform across deciles, that's a systematic fetcher bug.</p>
    {df_to_html(by_dec.reset_index())}
    """
    add_section(16,
        'Missingness by market-cap decile',
        f'Smallest decile (D1): {bottom_dec["pct_with_fund"]:.0f}% have fundamentals. '
        f'Largest (D10): {top_dec["pct_with_fund"]:.0f}%.',
        body, csv_rel=csv, plot_rel=plot)


# --------------------------------------------------------------------------- #
#  HTML report builder
# --------------------------------------------------------------------------- #

HTML_HEAD = """<!DOCTYPE html>
<html><head><meta charset='utf-8'><title>Portfolio X-Ray EDA Report</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       max-width: 1100px; margin: 20px auto; padding: 0 20px; color: #222; }
h1 { border-bottom: 2px solid #333; padding-bottom: 8px; }
h2 { background: #f3f3f3; padding: 8px 12px; border-left: 4px solid #2952a3; margin-top: 40px; }
.headline { background: #fffbe6; border-left: 4px solid #e0a800; padding: 8px 12px; margin: 8px 0 14px; font-weight: 500; }
.tbl { border-collapse: collapse; margin: 10px 0; font-size: 0.9em; }
.tbl th, .tbl td { padding: 4px 8px; border: 1px solid #ccc; }
.tbl th { background: #eee; text-align: left; }
.plot { max-width: 100%; margin: 10px 0; border: 1px solid #ddd; }
.meta { color: #666; font-size: 0.85em; }
.toc a { display: block; padding: 2px 0; }
nav { background: #fafafa; padding: 12px; border: 1px solid #e5e5e5; border-radius: 4px; margin: 20px 0; }
a { color: #2952a3; text-decoration: none; }
a:hover { text-decoration: underline; }
code { background: #f5f5f5; padding: 1px 4px; border-radius: 3px; }
</style></head><body>
"""


def build_html_report(sections, path):
    toc = '\n'.join(
        f'<a href="#s{s["n"]}">{s["n"]:02d}. {escape(s["title"])}</a>'
        for s in sections
    )
    body_parts = []
    for s in sections:
        parts = [f'<h2 id="s{s["n"]}">{s["n"]:02d}. {escape(s["title"])}</h2>']
        parts.append(f'<div class="headline">{escape(s["headline"])}</div>')
        parts.append(s['body'])
        if s['plot']:
            parts.append(f'<img class="plot" src="{s["plot"]}" alt="plot">')
        if s['csv']:
            parts.append(f'<p class="meta">Full data: <a href="{s["csv"]}">{s["csv"]}</a></p>')
        body_parts.append('\n'.join(parts))

    html = (HTML_HEAD
        + f'<h1>Portfolio X-Ray — EDA Report</h1>'
        + f'<p class="meta">Generated {datetime.now():%Y-%m-%d %H:%M} from '
          f'<code>data/db/market_data.db</code>. '
          f'16 checks across 4 purposes (accuracy · descriptive · model sanity · insight).</p>'
        + f'<nav class="toc"><b>Contents</b><br>{toc}</nav>'
        + '\n'.join(body_parts)
        + '</body></html>'
    )
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #

def main():
    os.makedirs(EDA_DIR,   exist_ok=True)
    os.makedirs(PLOTS_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)

    checks = [
        ('01 price coverage',           check_01_price_coverage),
        ('02 stale tickers',            check_02_stale_tickers),
        ('03 fund/price join',          check_03_fund_price_join),
        ('04 sector taxonomy',          check_04_sector_taxonomy_sanity),
        ('05 ticker collisions',        check_05_ticker_format_collisions),
        ('06 sector × size',            check_06_sector_size_distribution),
        ('07 newly-added',              check_07_newly_added),
        ('08 removed',                  check_08_removed_tickers),
        ('09 factor coverage',          check_09_factor_coverage),
        ('10 EPFWD distribution',       check_10_epfwd_distribution),
        ('11 growth-estimate sanity',   check_11_growth_estimate_sanity),
        ('12 price outliers',           check_12_price_outliers),
        ('13 sector dispersion',        check_13_sector_dispersion),
        ('14 beta × return corr',       check_14_beta_return_correlation),
        ('15 sector growth',            check_15_sector_growth_bullishness),
        ('16 missingness by size',      check_16_missingness_by_size),
    ]
    for label, fn in checks:
        print(f'  Running {label} ...', flush=True)
        try:
            fn(conn)
        except Exception as e:
            print(f'    ERROR in {label}: {e}')
            import traceback; traceback.print_exc()

    conn.close()

    build_html_report(_sections, REPORT_FP)
    print(f'\nWrote report: {REPORT_FP}')
    print(f'Artifacts under:  {EDA_DIR}/')


if __name__ == '__main__':
    main()
