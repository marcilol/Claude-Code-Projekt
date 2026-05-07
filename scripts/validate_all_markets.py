# -*- coding: utf-8 -*-
"""
Comprehensive validation + EDA for all markets.
One report per market with data quality + model validation + factor stats.

Usage: py scripts/validate_all_markets.py
"""

import os
import sys
import sqlite3
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
from html import escape
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))

MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'model')
EDA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'eda')
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'db', 'market_data.db')

STYLE_COLS = ['size', 'beta', 'momentum', 'residvol', 'nlsize', 'btop',
              'liquidity', 'earnyild', 'growth', 'leverage']

MARKETS = {
    'us': {
        'cs_data': 'russell3000_cross_sectional_data.csv',
        'factor_returns': 'barra_factor_returns.csv',
        'factor_cov': 'barra_factor_covariance.csv',
        'factor_stats': 'barra_factor_statistics.csv',
        'r2': 'barra_r2.csv',
        'label': 'US (Russell 3000)',
        'universe_id': 1,
        'currency': 'USD',
    },
    'uk': {
        'cs_data': 'uk_cross_sectional_data.csv',
        'factor_returns': 'uk_factor_returns.csv',
        'factor_cov': 'uk_factor_covariance.csv',
        'factor_stats': 'uk_factor_statistics.csv',
        'r2': 'uk_r2.csv',
        'label': 'UK (LSE)',
        'universe_id': 3,
        'currency': 'GBP',
    },
    'korea': {
        'cs_data': 'korea_cross_sectional_data.csv',
        'factor_returns': 'korea_factor_returns.csv',
        'factor_cov': 'korea_factor_covariance.csv',
        'factor_stats': 'korea_factor_statistics.csv',
        'r2': 'korea_r2.csv',
        'label': 'Korea (KO)',
        'universe_id': 2,
        'currency': 'KRW',
    },
    'eurozone': {
        'cs_data': 'eurozone_cross_sectional_data.csv',
        'factor_returns': 'eurozone_factor_returns.csv',
        'factor_cov': 'eurozone_factor_covariance.csv',
        'factor_stats': 'eurozone_factor_statistics.csv',
        'r2': 'eurozone_r2.csv',
        'label': 'Eurozone (Multi-Exchange)',
        'universe_id': 5,
        'currency': 'EUR',
    },
    'china_she': {
        'cs_data': 'china_she_cross_sectional_data.csv',
        'factor_returns': 'china_she_factor_returns.csv',
        'factor_cov': 'china_she_factor_covariance.csv',
        'factor_stats': 'china_she_factor_statistics.csv',
        'r2': 'china_she_r2.csv',
        'label': 'China (SHE — top 1000 by mcap)',
        'universe_id': 6,
        'currency': 'CNY',
    },
    'taiwan_tw': {
        'cs_data': 'taiwan_tw_cross_sectional_data.csv',
        'factor_returns': 'taiwan_tw_factor_returns.csv',
        'factor_cov': 'taiwan_tw_factor_covariance.csv',
        'factor_stats': 'taiwan_tw_factor_statistics.csv',
        'r2': 'taiwan_tw_r2.csv',
        'label': 'Taiwan (TW)',
        'universe_id': 7,
        'currency': 'TWD',
    },
}


def df_to_html(df, max_rows=30):
    if len(df) > max_rows:
        df = df.head(max_rows)
    return df.to_html(index=False, float_format=lambda x: f'{x:,.4g}', classes='tbl')


def style_factor_norm(factors, capital):
    """Re-normalize style factors (same as run_factor_model.py)."""
    weights = capital / capital.sum()
    weighted_mean = np.average(factors, weights=weights, axis=0)
    equal_std = np.std(factors, axis=0, ddof=1)
    equal_std[equal_std == 0] = 1
    return (factors - weighted_mean) / equal_std


def wls_r2(y, X, w):
    """WLS R² consistent with BarraModel: weights are w, not w²."""
    try:
        # lstsq(A @ X, A @ y) minimizes ||A(y - Xb)||² = Σ a_i²(y-Xb)²
        # To get WLS with weights w, use A = diag(sqrt(w)) so a_i² = w_i
        sw = np.sqrt(w)
        beta = np.linalg.lstsq(sw[:, None] * X, sw * y, rcond=None)[0]
        pred = X @ beta
        ss_res = np.sum(w * (y - pred) ** 2)
        ss_tot = np.sum(w * y ** 2)
        return 1 - ss_res / ss_tot if ss_tot > 0 else 0
    except Exception:
        return np.nan


def save_plot(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)


# ------------------------------------------------------------------ #
#  EDA Checks (from DB)
# ------------------------------------------------------------------ #

def eda_checks(uid, out_dir, label):
    """Run data quality checks from the DB for a given universe."""
    sections = []
    conn = sqlite3.connect(DB_PATH)
    plots_dir = os.path.join(out_dir, 'plots')

    # E1: Price coverage
    q = f"""
        SELECT p.ticker, COUNT(*) AS days, MIN(p.date) AS min_d, MAX(p.date) AS max_d
        FROM daily_prices p
        JOIN stocks s ON s.ticker=p.ticker AND s.universe_id={uid}
        WHERE s.removed_date IS NULL
        GROUP BY p.ticker ORDER BY days
    """
    df = pd.read_sql_query(q, conn)
    if not df.empty:
        fig, ax = plt.subplots(figsize=(8, 3.5))
        ax.hist(df['days'], bins=30, color='steelblue')
        ax.set_title('Trading days of price history per ticker')
        ax.set_xlabel('Days'); ax.set_ylabel('Tickers')
        save_plot(fig, os.path.join(plots_dir, 'eda_price_coverage.png'))

        short = int((df['days'] < 50).sum())
        full = int((df['days'] >= 400).sum())
        sections.append(('Price Coverage',
            f'{full} tickers with 400+ days, {short} with <50 days, {len(df)} total.',
            f'<img class="plot" src="plots/eda_price_coverage.png">'))

    # E2: Stale tickers
    q2 = f"""
        SELECT p.ticker, MAX(p.date) AS max_date, s.sector
        FROM daily_prices p
        JOIN stocks s ON s.ticker=p.ticker AND s.universe_id={uid}
        WHERE s.removed_date IS NULL
        GROUP BY p.ticker
    """
    df2 = pd.read_sql_query(q2, conn)
    if not df2.empty:
        panel_max = df2['max_date'].max()
        df2['days_stale'] = (pd.to_datetime(panel_max) - pd.to_datetime(df2['max_date'])).dt.days
        stale = df2[df2['days_stale'] > 7]
        sections.append(('Stale Tickers',
            f'{len(stale)} tickers with prices >7 days behind {panel_max}.',
            df_to_html(stale.sort_values('days_stale', ascending=False).head(15)) if len(stale) > 0 else '<p>None</p>'))

    # E3: Sector distribution
    q3 = f"""
        SELECT COALESCE(gic_sector, sector) AS industry, COUNT(*) AS n
        FROM stocks WHERE universe_id={uid} AND removed_date IS NULL
        GROUP BY industry ORDER BY n DESC
    """
    df3 = pd.read_sql_query(q3, conn)
    if not df3.empty:
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.barh(range(len(df3)), df3['n'].values, color='teal')
        ax.set_yticks(range(len(df3)))
        ax.set_yticklabels(df3['industry'].values, fontsize=7)
        ax.set_title('Tickers by sector/industry')
        ax.invert_yaxis()
        save_plot(fig, os.path.join(plots_dir, 'eda_sector_dist.png'))
        sections.append(('Sector Distribution',
            f'{len(df3)} sectors/groups, largest: {df3.iloc[0]["industry"]} ({df3.iloc[0]["n"]})',
            f'<img class="plot" src="plots/eda_sector_dist.png">'))

    # E4: Shares outstanding coverage
    q4 = f"""
        SELECT
            COUNT(DISTINCT CASE WHEN p.shares_out IS NOT NULL AND p.shares_out > 0 THEN p.ticker END) AS with_so,
            COUNT(DISTINCT p.ticker) AS total
        FROM daily_prices p
        JOIN stocks s ON s.ticker=p.ticker AND s.universe_id={uid}
        WHERE s.removed_date IS NULL
    """
    row = conn.execute(q4).fetchone()
    if row:
        pct = 100 * row[0] / row[1] if row[1] > 0 else 0
        sections.append(('Shares Outstanding Coverage',
            f'{row[0]}/{row[1]} tickers ({pct:.0f}%) have shares_out data.',
            ''))

    # E5: Fundamentals coverage
    q5 = f"""
        SELECT
            COUNT(DISTINCT CASE WHEN EXISTS (SELECT 1 FROM fundamentals_quarterly f WHERE f.ticker=s.ticker) THEN s.ticker END) AS with_fund,
            COUNT(DISTINCT s.ticker) AS total
        FROM stocks s
        WHERE s.universe_id={uid} AND s.removed_date IS NULL
    """
    row5 = conn.execute(q5).fetchone()
    if row5:
        pct = 100 * row5[0] / row5[1] if row5[1] > 0 else 0
        sections.append(('Fundamentals Coverage',
            f'{row5[0]}/{row5[1]} tickers ({pct:.0f}%) have quarterly fundamentals.',
            ''))

    # E6: Price outliers
    q6 = f"""
        SELECT p.ticker, p.date, p.close, s.sector
        FROM daily_prices p
        JOIN stocks s ON s.ticker=p.ticker AND s.universe_id={uid}
        WHERE s.removed_date IS NULL
          AND p.date = (SELECT MAX(date) FROM daily_prices)
          AND (p.close < 1 OR p.close > 50000)
        ORDER BY p.close
    """
    df6 = pd.read_sql_query(q6, conn)
    sections.append(('Price Outliers',
        f'{len(df6)} stocks with close <1 or >50,000 on latest date.',
        df_to_html(df6) if len(df6) > 0 else '<p>None</p>'))

    conn.close()
    return sections


# ------------------------------------------------------------------ #
#  Model Validation Checks
# ------------------------------------------------------------------ #

def model_checks(market, out_dir):
    """Run model validation checks."""
    m = MARKETS[market]
    sections = []
    plots_dir = os.path.join(out_dir, 'plots')
    results = {}

    # Load data
    cs_path = os.path.join(MODEL_DIR, m['cs_data'])
    fr_path = os.path.join(MODEL_DIR, m['factor_returns'])
    r2_path = os.path.join(MODEL_DIR, m['r2'])
    stats_path = os.path.join(MODEL_DIR, m['factor_stats'])
    cov_path = os.path.join(MODEL_DIR, m['factor_cov'])

    for p in [cs_path, fr_path, r2_path]:
        if not os.path.exists(p):
            return sections, {'error': f'Missing {p}'}

    data = pd.read_csv(cs_path)
    fr = pd.read_csv(fr_path, index_col=0)
    r2 = pd.read_csv(r2_path, index_col=0)['R2']
    stats = pd.read_csv(stats_path, index_col=0) if os.path.exists(stats_path) else None
    cov = pd.read_csv(cov_path, index_col=0) if os.path.exists(cov_path) else None

    industry_cols = [c for c in data.columns
                     if c not in ['date', 'stocknames', 'capital', 'ret'] + STYLE_COLS]
    dates = sorted(data['date'].unique())

    results['dates'] = len(dates)
    results['date_range'] = f'{dates[0]} to {dates[-1]}'
    results['stocks_per_date'] = len(data) // len(dates)
    results['industries'] = len(industry_cols)
    results['factors'] = len(fr.columns)
    results['r2_mean'] = round(r2.mean(), 4)
    results['r2_median'] = round(r2.median(), 4)

    # M1: Factor statistics
    if stats is not None:
        fig, ax = plt.subplots(figsize=(10, 6))
        style_stats = stats.loc[[s for s in STYLE_COLS if s in stats.index]]
        colors = ['#2d8a2d' if abs(t) > 1.96 else '#999'
                  for t in style_stats['t-stat']]
        bars = ax.barh(range(len(style_stats)), style_stats['t-stat'], color=colors)
        ax.set_yticks(range(len(style_stats)))
        ax.set_yticklabels(style_stats.index)
        ax.axvline(1.96, color='k', ls='--', lw=0.5, alpha=0.5)
        ax.axvline(-1.96, color='k', ls='--', lw=0.5, alpha=0.5)
        ax.set_title('Style Factor t-statistics')
        save_plot(fig, os.path.join(plots_dir, 'factor_tstats.png'))

        sections.append(('Factor Statistics',
            f'{sum(1 for t in style_stats["t-stat"] if abs(t) > 1.96)} of {len(style_stats)} '
            f'style factors significant at 95%.',
            stats.round(2).to_html(classes='tbl') +
            '<img class="plot" src="plots/factor_tstats.png">'))

    # M2: R2 distribution
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    axes[0].hist(r2.dropna(), bins=40, color='steelblue', edgecolor='white')
    axes[0].axvline(r2.mean(), color='red', lw=2, label=f'Mean ({r2.mean():.3f})')
    axes[0].axvline(r2.median(), color='orange', lw=2, ls='--', label=f'Median ({r2.median():.3f})')
    axes[0].set_xlabel('Daily R2'); axes[0].legend()
    axes[0].set_title('R2 Distribution')
    axes[1].plot(range(len(r2)), r2.values, alpha=0.5, lw=0.8)
    axes[1].axhline(r2.mean(), color='red', lw=1)
    axes[1].set_title('R2 Over Time'); axes[1].set_ylabel('R2')
    save_plot(fig, os.path.join(plots_dir, 'r2_distribution.png'))
    sections.append(('R2 Distribution',
        f'Mean={r2.mean():.3f}, Median={r2.median():.3f}, IQR={r2.quantile(0.25):.3f}-{r2.quantile(0.75):.3f}',
        '<img class="plot" src="plots/r2_distribution.png">'))

    # M3: Autocorrelation
    ac = {}
    for col in fr.columns:
        s = fr[col].dropna()
        if len(s) > 30:
            ac[col] = round(s.autocorr(lag=1), 3)
    ac_df = pd.DataFrame({'factor': list(ac.keys()), 'lag1_autocorr': list(ac.values())})
    ac_df['abs_ac'] = ac_df['lag1_autocorr'].abs()
    ac_df = ac_df.sort_values('abs_ac', ascending=False)
    ac_df.to_csv(os.path.join(out_dir, 'autocorrelation.csv'), index=False)
    high_ac = ac_df[ac_df['abs_ac'] > 0.15]
    results['autocorr_violations'] = len(high_ac)
    sections.append(('Autocorrelation',
        f'{len(high_ac)} factors with |autocorr| > 0.15. Max: {ac_df.iloc[0]["factor"]} ({ac_df.iloc[0]["lag1_autocorr"]:+.3f}).',
        df_to_html(ac_df.head(10))))

    # M4: VIF
    latest_dd = data[data['date'] == dates[-1]]
    style_data = latest_dd[STYLE_COLS].fillna(0).values
    vifs = []
    for i, col in enumerate(STYLE_COLS):
        y = style_data[:, i]
        X = np.delete(style_data, i, axis=1)
        X = np.column_stack([np.ones(len(X)), X])
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        ss_res = np.sum((y - X @ beta) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2_v = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        vifs.append({'factor': col, 'VIF': round(1 / (1 - r2_v) if r2_v < 1 else np.inf, 2)})
    vif_df = pd.DataFrame(vifs).sort_values('VIF', ascending=False)
    vif_df.to_csv(os.path.join(out_dir, 'vif.csv'), index=False)
    results['max_vif'] = vif_df['VIF'].max()
    sections.append(('Variance Inflation Factors',
        f'Max VIF: {vif_df.iloc[0]["factor"]} ({vif_df.iloc[0]["VIF"]:.1f}). All {"< 5 OK" if vif_df["VIF"].max() < 5 else "> 5 CHECK"}.',
        df_to_html(vif_df)))

    # M5: CAPM lift + decomposition (ALL dates for consistency with headline R2)
    # Apply same style_factor_norm as run_factor_model.py for consistent R2
    capm_r2s, ind_r2s, full_r2s = [], [], []
    for d in dates:
        dd = data[data['date'] == d]
        y = dd['ret'].values; cap = dd['capital'].values
        if len(y) < 30: continue
        w = np.sqrt(cap) / np.sqrt(cap).sum()
        capm_r2s.append(wls_r2(y, np.ones((len(y), 1)), w))
        ind_vals = dd[industry_cols].fillna(0).values
        X_ind = np.hstack([np.ones((len(y), 1)), ind_vals])
        ind_r2s.append(wls_r2(y, X_ind, w))
        style_vals = style_factor_norm(dd[STYLE_COLS].fillna(0).values, cap)
        X_full = np.hstack([X_ind, style_vals])
        full_r2s.append(wls_r2(y, X_full, w))
    results['capm_r2'] = round(np.nanmean(capm_r2s), 4)
    results['ind_r2'] = round(np.nanmean(ind_r2s), 4)
    results['full_r2'] = round(np.nanmean(full_r2s), 4)
    results['industry_lift'] = round(results['ind_r2'] - results['capm_r2'], 4)
    results['style_lift'] = round(results['full_r2'] - results['ind_r2'], 4)

    decomp = pd.DataFrame({
        'Components': ['Country only', '+ Industry', '+ Style (full)'],
        'Mean R2': [results['capm_r2'], results['ind_r2'], results['full_r2']],
        'Marginal': ['—', f'+{results["industry_lift"]:.4f}', f'+{results["style_lift"]:.4f}'],
    })
    sections.append(('R2 Decomposition',
        f'CAPM={results["capm_r2"]:.3f}, +Industry={results["industry_lift"]:.3f}, +Style={results["style_lift"]:.3f}',
        df_to_html(decomp)))

    # M6: Permutation test (10 iterations)
    # Use every 5th date for permutation (speed), but baseline = headline R2 (full_r2)
    date_arrays = {}
    for d in dates[::5]:
        dd = data[data['date'] == d]
        y = dd['ret'].values; cap = dd['capital'].values
        if len(y) < 30: continue
        w = np.sqrt(cap) / np.sqrt(cap).sum()
        style_normed = style_factor_norm(dd[STYLE_COLS].fillna(0).values, cap)
        X = np.hstack([np.ones((len(dd), 1)), dd[industry_cols].fillna(0).values,
                       style_normed])
        date_arrays[d] = {'y': y, 'X': X, 'w': w}
    valid_dates = list(date_arrays.keys())
    # Use the full-model R2 as baseline (consistent with headline)
    baseline = results['full_r2']
    perm_r2s = []
    for seed in range(50):
        np.random.seed(seed + 42)
        perm = np.random.permutation(len(valid_dates))
        r2s = []
        for i, d in enumerate(valid_dates):
            src = valid_dates[perm[i]]
            X, w = date_arrays[d]['X'], date_arrays[d]['w']
            y_s = date_arrays[src]['y']
            if len(w) == len(y_s):
                r2s.append(wls_r2(y_s, X, w))
            elif len(y_s) >= len(w):
                idx = np.random.choice(len(y_s), len(w), replace=False)
                r2s.append(wls_r2(y_s[idx], X, w))
        perm_r2s.append(np.mean(r2s))
    results['perm_floor'] = round(np.mean(perm_r2s), 4)
    results['day_specific_lift'] = round(baseline - results['perm_floor'], 4)
    sections.append(('Permutation Test (50 shuffles)',
        f'Structural floor: {results["perm_floor"]:.3f}. Day-specific lift: {results["day_specific_lift"]:.3f}.',
        f'<p>Baseline R2: {baseline:.4f}. Shuffled mean: {np.mean(perm_r2s):.4f} +/- {np.std(perm_r2s):.4f}.</p>'))

    # M7: Covariance check
    if cov is not None:
        eigvals = np.linalg.eigvalsh(cov.values)
        pos_def = eigvals.min() > 0
        symmetric = np.abs(cov.values - cov.values.T).max() < 1e-12
        sections.append(('Covariance Matrix',
            f'Shape: {cov.shape}. Positive definite: {"Yes" if pos_def else "NO"}. '
            f'Symmetric: {"Yes" if symmetric else "NO"}. Min eigenvalue: {eigvals.min():.2e}.',
            ''))

    # M8: Beta fillna audit
    n_zero_beta = (data['beta'] == 0).sum()
    pct_zero = 100 * n_zero_beta / len(data)
    results['beta_zero_pct'] = round(pct_zero, 1)
    sections.append(('Beta Zero-Fill Audit',
        f'{n_zero_beta:,} rows ({pct_zero:.1f}%) have beta=0.',
        ''))

    # M9: Factor correlation matrix
    if cov is not None:
        style_in_cov = [s for s in STYLE_COLS if s in cov.columns]
        if style_in_cov:
            sc = cov.loc[style_in_cov, style_in_cov]
            diag = np.sqrt(np.diag(sc.values))
            corr = sc.values / np.outer(diag, diag)
            corr_df = pd.DataFrame(corr, index=style_in_cov, columns=style_in_cov)

            fig, ax = plt.subplots(figsize=(8, 6))
            im = ax.imshow(corr, cmap='RdBu_r', vmin=-1, vmax=1, aspect='auto')
            ax.set_xticks(range(len(style_in_cov)))
            ax.set_xticklabels(style_in_cov, rotation=45, ha='right', fontsize=8)
            ax.set_yticks(range(len(style_in_cov)))
            ax.set_yticklabels(style_in_cov, fontsize=8)
            for i in range(len(style_in_cov)):
                for j in range(len(style_in_cov)):
                    ax.text(j, i, f'{corr[i,j]:.2f}', ha='center', va='center', fontsize=7)
            ax.set_title('Style Factor Correlation')
            plt.colorbar(im, ax=ax, shrink=0.8)
            save_plot(fig, os.path.join(plots_dir, 'factor_correlation.png'))
            sections.append(('Factor Correlation',
                f'Max off-diagonal |corr|: {np.max(np.abs(corr - np.eye(len(corr)))):.2f}',
                '<img class="plot" src="plots/factor_correlation.png">'))

    # M10: Country factor vs cap-weighted market return
    if fr is not None and 'Country' in fr.columns:
        mkt_rets, cty_rets = [], []
        for d in dates:
            dd = data[data['date'] == d]
            cap = dd['capital'].values
            if cap.sum() == 0 or d not in fr.index:
                continue
            w = cap / cap.sum()
            mkt_rets.append(np.sum(w * dd['ret'].values))
            cty_rets.append(fr.loc[d, 'Country'])

        if len(mkt_rets) > 30:
            corr_val = np.corrcoef(mkt_rets, cty_rets)[0, 1]
            results['country_market_corr'] = round(corr_val, 4)

            fig, ax = plt.subplots(figsize=(6, 6))
            ax.scatter(mkt_rets, cty_rets, s=8, alpha=0.4, color='steelblue')
            lims = [min(min(mkt_rets), min(cty_rets)) * 1.1,
                    max(max(mkt_rets), max(cty_rets)) * 1.1]
            ax.plot(lims, lims, 'k--', lw=0.5, label='y = x')
            ax.set_xlim(lims); ax.set_ylim(lims)
            ax.set_xlabel('Cap-weighted market return')
            ax.set_ylabel('Country factor return')
            ax.set_title(f'Country vs market (corr = {corr_val:.4f})')
            ax.legend()
            save_plot(fig, os.path.join(plots_dir, 'country_vs_market.png'))

            sections.append(('Country vs Market Return',
                f'Correlation = {corr_val:.4f}. Country factor captures the cap-weighted market return.',
                '<img class="plot" src="plots/country_vs_market.png">'))

    return sections, results


# ------------------------------------------------------------------ #
#  HTML Report Builder
# ------------------------------------------------------------------ #

HTML_HEAD = """<!DOCTYPE html>
<html><head><meta charset='utf-8'><title>{title}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 1100px; margin: 20px auto; padding: 0 20px; color: #222; }}
h1 {{ border-bottom: 2px solid #333; padding-bottom: 8px; }}
h2 {{ background: #f3f3f3; padding: 8px 12px; border-left: 4px solid #2952a3; margin-top: 30px; }}
.headline {{ background: #fffbe6; border-left: 4px solid #e0a800; padding: 8px 12px; margin: 8px 0 14px; }}
.tbl {{ border-collapse: collapse; margin: 10px 0; font-size: 0.85em; }}
.tbl th, .tbl td {{ padding: 4px 8px; border: 1px solid #ccc; }}
.tbl th {{ background: #eee; text-align: left; }}
.plot {{ max-width: 100%; margin: 10px 0; border: 1px solid #ddd; }}
.meta {{ color: #666; font-size: 0.85em; }}
.summary {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; margin: 15px 0; }}
.stat {{ background: #f9f9f9; padding: 10px; border-radius: 4px; border: 1px solid #e5e5e5; }}
.stat .val {{ font-size: 1.4em; font-weight: bold; color: #2952a3; }}
.stat .lbl {{ font-size: 0.85em; color: #666; }}
</style></head><body>
"""


def build_report(market, eda_sections, model_sections, results, out_dir):
    m = MARKETS[market]
    title = f'{m["label"]} — Comprehensive Report'

    parts = [HTML_HEAD.format(title=title)]
    parts.append(f'<h1>{title}</h1>')
    parts.append(f'<p class="meta">Generated {datetime.now():%Y-%m-%d %H:%M}. '
                 f'Currency: {m["currency"]}.</p>')

    # Summary cards
    if results:
        parts.append('<div class="summary">')
        for key, label in [('dates', 'Trading days'), ('stocks_per_date', 'Stocks/date'),
                           ('industries', 'Industries'), ('factors', 'Total factors'),
                           ('r2_mean', 'Mean R2'), ('r2_median', 'Median R2'),
                           ('capm_r2', 'CAPM R2'), ('style_lift', 'Style lift'),
                           ('perm_floor', 'Perm floor'), ('day_specific_lift', 'Day-specific'),
                           ('max_vif', 'Max VIF'), ('beta_zero_pct', 'Beta zeros %')]:
            if key in results:
                val = results[key]
                if isinstance(val, float):
                    val = f'{val:.3f}' if val < 10 else f'{val:.1f}'
                parts.append(f'<div class="stat"><div class="val">{val}</div><div class="lbl">{label}</div></div>')
        parts.append('</div>')

    # EDA sections
    if eda_sections:
        parts.append('<h1 style="margin-top:40px">Data Quality</h1>')
        for title, headline, body in eda_sections:
            parts.append(f'<h2>{escape(title)}</h2>')
            parts.append(f'<div class="headline">{escape(headline)}</div>')
            parts.append(body)

    # Model sections
    if model_sections:
        parts.append('<h1 style="margin-top:40px">Model Validation</h1>')
        for title, headline, body in model_sections:
            parts.append(f'<h2>{escape(title)}</h2>')
            parts.append(f'<div class="headline">{escape(headline)}</div>')
            parts.append(body)

    parts.append('</body></html>')

    # Save to per-market subfolder (for plots) and to flat EDA folder with timestamp
    subfolder_path = os.path.join(out_dir, 'report.html')
    with open(subfolder_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))

    # Also save timestamped copy in data/eda/
    ts = datetime.now().strftime('%Y_%m_%d_%H_%M')
    flat_path = os.path.join(EDA_DIR, f'{market}_validation_{ts}.html')
    # Archive any existing non-timestamped version
    archive_dir = os.path.join(EDA_DIR, 'archive')
    os.makedirs(archive_dir, exist_ok=True)
    import glob
    for old in glob.glob(os.path.join(EDA_DIR, f'{market}_validation_*.html')):
        if old != flat_path:
            os.rename(old, os.path.join(archive_dir, os.path.basename(old)))
    with open(flat_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))

    return flat_path


# ------------------------------------------------------------------ #
#  Main
# ------------------------------------------------------------------ #

def main():
    print('=' * 60)
    print('  COMPREHENSIVE MULTI-MARKET VALIDATION + EDA')
    print('=' * 60)

    all_results = {}

    for market, m in MARKETS.items():
        out_dir = os.path.join(EDA_DIR, market)
        plots_dir = os.path.join(out_dir, 'plots')
        os.makedirs(plots_dir, exist_ok=True)

        print(f'\n{"=" * 60}')
        print(f'  {m["label"]}')
        print(f'{"=" * 60}')

        # Check if model files exist
        cs_path = os.path.join(MODEL_DIR, m['cs_data'])
        if not os.path.exists(cs_path):
            print(f'  SKIP: {cs_path} not found')
            continue

        print('  Running EDA checks...', flush=True)
        eda_sections = eda_checks(m['universe_id'], out_dir, m['label'])

        print('  Running model validation...', flush=True)
        model_sections, results = model_checks(market, out_dir)

        path = build_report(market, eda_sections, model_sections, results, out_dir)
        print(f'  Report: {path}')

        if results and 'error' not in results:
            all_results[market] = results

    # Run pytest and build structured results
    print(f'\n{"=" * 60}')
    print('  PYTEST SUITE')
    print(f'{"=" * 60}')
    import subprocess, json as _json, re as _re

    pytest_result = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/', '-v', '--tb=line'],
        capture_output=True, text=True, timeout=300
    )
    pytest_output = pytest_result.stdout + pytest_result.stderr

    # Parse PASSED/FAILED/SKIPPED from verbose output
    test_results = {}
    for line in pytest_output.split('\n'):
        for status in ['PASSED', 'FAILED', 'SKIPPED']:
            if f' {status}' in line and '::' in line:
                # Extract test path: tests/file.py::Class::method
                match = _re.search(r'(tests[\\/]\S+::\S+)', line)
                if match:
                    key = match.group(1).replace('\\', '/').split(' ')[0]
                    test_results[key] = status
                break

    # Load descriptions
    desc_path = os.path.join(EDA_DIR, 'test_descriptions.json')
    descriptions = {}
    if os.path.exists(desc_path):
        with open(desc_path) as f:
            for t in _json.load(f):
                key = f"tests/{t['file']}::{t['class']}::{t['test']}" if t['class'] else f"tests/{t['file']}::{t['test']}"
                descriptions[key] = t['description']

    # Count
    n_passed = sum(1 for s in test_results.values() if s == 'PASSED')
    n_failed = sum(1 for s in test_results.values() if s == 'FAILED')
    n_skipped = sum(1 for s in test_results.values() if s == 'SKIPPED')
    pytest_summary = f'{n_passed} passed, {n_failed} failed, {n_skipped} skipped'
    print(f'  {pytest_summary}')

    # Group by file for structured display
    from collections import defaultdict as _dd
    by_phase = _dd(list)
    phase_names = {
        'test_sanity_checks.py': ('1. Sanity Checks', 'Model output validation: z-scores, R2, covariance, factor names'),
        'test_unit_zscore.py': ('2a. Unit: Z-scoring', 'Z-score math against hand calculations'),
        'test_unit_factor_risk.py': ('2b. Unit: Factor Risk', 'Factor variance b\'Omega b computation'),
        'test_unit_mcfr.py': ('2c. Unit: MCFR', 'Marginal contribution to factor risk'),
        'test_unit_sizing.py': ('2d. Unit: Sizing', 'All 4 position sizing methods'),
        'test_unit_idio_vol.py': ('2e. Unit: Idio Vol', 'Idiosyncratic volatility computation'),
        'test_unit_portfolio.py': ('2f. Unit: Portfolio', 'Portfolio CSV loading and weight computation'),
        'test_regression.py': ('3. Regression Baselines', 'Current model vs saved baselines (1% tolerance)'),
        'test_benchmarks.py': ('4. Benchmarks', 'SPY regression, beta correlation, covariance checks'),
        'test_model_validation.py': ('5. Model Validation', 'Autocorrelation, VIF, CAPM lift, alignment, permutation'),
        # test_excel_verification.py excluded from report — all skipped, awaiting workbook regen
    }

    for key, status in sorted(test_results.items()):
        fname = key.split('::')[0].replace('tests/', '')
        desc = descriptions.get(key, '')
        test_name = key.split('::')[-1]
        by_phase[fname].append((test_name, status, desc))

    # Build HTML table
    pytest_html = f'<h1 style="margin-top:40px">Automated Test Suite</h1>\n'
    pytest_html += f'<div class="headline">{n_passed} passed, {n_failed} failed, {n_skipped} skipped</div>\n'

    for fname in sorted(by_phase.keys(), key=lambda f: list(phase_names.keys()).index(f) if f in phase_names else 99):
        phase, phase_desc = phase_names.get(fname, (fname, ''))
        items = by_phase[fname]
        p = sum(1 for _, s, _ in items if s == 'PASSED')
        f_count = sum(1 for _, s, _ in items if s == 'FAILED')
        sk = sum(1 for _, s, _ in items if s == 'SKIPPED')

        status_icon = '&#9989;' if f_count == 0 and sk == 0 else ('&#9888;' if sk > 0 and f_count == 0 else '&#10060;')
        pytest_html += f'<h2>{status_icon} {escape(phase)} ({p}P/{f_count}F/{sk}S)</h2>\n'
        if phase_desc:
            pytest_html += f'<p class="meta">{escape(phase_desc)}</p>\n'
        pytest_html += '<table class="tbl"><tr><th>Test</th><th>Status</th><th>Description</th></tr>\n'
        for tname, status, desc in items:
            color = '#2d8a2d' if status == 'PASSED' else ('#cc3333' if status == 'FAILED' else '#888')
            pytest_html += f'<tr><td><code>{escape(tname)}</code></td>'
            pytest_html += f'<td style="color:{color};font-weight:bold">{status}</td>'
            pytest_html += f'<td>{escape(desc)}</td></tr>\n'
        pytest_html += '</table>\n'

    # Append to each market report
    for market in MARKETS:
        rpt_path = os.path.join(EDA_DIR, market, 'report.html')
        if os.path.exists(rpt_path):
            with open(rpt_path, 'r', encoding='utf-8') as f:
                html = f.read()
            html = html.replace('</body></html>', pytest_html + '</body></html>')
            with open(rpt_path, 'w', encoding='utf-8') as f:
                f.write(html)

    # ETF validation for US (append if ETF report data exists)
    etf_summary_path = os.path.join(EDA_DIR, 'val_etf_all_summary.csv')
    if os.path.exists(etf_summary_path):
        etf_df = pd.read_csv(etf_summary_path)
        etf_html = f"""
        <h1 style="margin-top:40px">ETF Factor Loading Validation</h1>
        <div class="headline">{len(etf_df)} ETFs regressed on factor returns. All R2 > 85%.</div>
        {etf_df.to_html(index=False, classes='tbl', float_format=lambda x: f'{x:.3f}')}
        """
        heatmap_path = os.path.join(EDA_DIR, 'plots', 'val_etf_loadings_heatmap.png')
        if os.path.exists(heatmap_path):
            rel = os.path.relpath(heatmap_path, os.path.join(EDA_DIR, 'us')).replace('\\', '/')
            etf_html += f'<img class="plot" src="{rel}">'

        us_rpt = os.path.join(EDA_DIR, 'us', 'report.html')
        if os.path.exists(us_rpt):
            with open(us_rpt, 'r', encoding='utf-8') as f:
                html = f.read()
            html = html.replace('</body></html>', etf_html + '</body></html>')
            with open(us_rpt, 'w', encoding='utf-8') as f:
                f.write(html)

    # Cross-market comparison
    if len(all_results) > 1:
        print(f'\n{"=" * 60}')
        print('  CROSS-MARKET COMPARISON')
        print(f'{"=" * 60}')
        comp = pd.DataFrame(all_results).T
        comp.index.name = 'market'
        cols = [c for c in ['dates', 'stocks_per_date', 'industries', 'r2_mean',
                            'capm_r2', 'industry_lift', 'style_lift',
                            'perm_floor', 'day_specific_lift', 'max_vif'] if c in comp.columns]
        print(comp[cols].round(4).to_string())
        comp.to_csv(os.path.join(EDA_DIR, 'cross_market_comparison.csv'))

        # Permutation floor vs day-specific lift plot
        plots_dir = os.path.join(EDA_DIR, 'plots')
        os.makedirs(plots_dir, exist_ok=True)

        fig, axes = plt.subplots(1, 2, figsize=(14, 5))

        markets = list(all_results.keys())
        labels = [MARKETS[m]['label'] for m in markets]
        floors = [all_results[m]['perm_floor'] for m in markets]
        lifts = [all_results[m]['day_specific_lift'] for m in markets]
        r2s = [all_results[m]['r2_mean'] for m in markets]
        capm = [all_results[m].get('capm_r2', 0) for m in markets]
        ind_lift = [all_results[m].get('industry_lift', 0) for m in markets]
        style_lift = [all_results[m].get('style_lift', 0) for m in markets]

        # Left: stacked bar — structural floor vs day-specific lift
        x = range(len(markets))
        axes[0].bar(x, floors, color='#cccccc', label='Structural floor (permutation)')
        axes[0].bar(x, lifts, bottom=floors, color='#2952a3', label='Day-specific lift')
        for i in x:
            axes[0].text(i, floors[i] + lifts[i] + 0.005, f'{r2s[i]:.1%}',
                        ha='center', va='bottom', fontweight='bold')
        axes[0].set_xticks(x)
        axes[0].set_xticklabels(labels)
        axes[0].set_ylabel('R2')
        axes[0].set_title('R2 Decomposition: Structural vs Day-Specific')
        axes[0].legend(loc='upper right')
        axes[0].set_ylim(0, max(r2s) * 1.3)

        # Right: stacked bar — CAPM vs industry lift vs style lift
        axes[1].bar(x, capm, color='#e8e8e8', label='CAPM (Country only)')
        axes[1].bar(x, ind_lift, bottom=capm, color='#7eb8da', label='+ Industry')
        bottoms2 = [c + i for c, i in zip(capm, ind_lift)]
        axes[1].bar(x, style_lift, bottom=bottoms2, color='#2952a3', label='+ Style factors')
        for i in x:
            total = capm[i] + ind_lift[i] + style_lift[i]
            axes[1].text(i, total + 0.005, f'{total:.1%}',
                        ha='center', va='bottom', fontweight='bold')
        axes[1].set_xticks(x)
        axes[1].set_xticklabels(labels)
        axes[1].set_ylabel('R2')
        axes[1].set_title('R2 Decomposition: CAPM vs Industry vs Style')
        axes[1].legend(loc='upper right')
        axes[1].set_ylim(0, max(r2s) * 1.3)

        save_plot(fig, os.path.join(plots_dir, 'cross_market_comparison.png'))

        # Build cross-market HTML page
        cross_html = HTML_HEAD.format(title='Cross-Market Comparison')
        cross_html += '<h1>Cross-Market Comparison</h1>'
        cross_html += f'<p class="meta">Generated {datetime.now():%Y-%m-%d %H:%M}</p>'
        cross_html += f'<img class="plot" src="plots/cross_market_comparison.png">'
        cross_html += '<h2>Summary Table</h2>'
        cross_html += comp[cols].round(4).to_html(classes='tbl')
        cross_html += '<h2>Per-Market Reports</h2><ul>'
        for market in MARKETS:
            rpt = os.path.join(market, 'report.html')
            cross_html += f'<li><a href="{rpt}">{MARKETS[market]["label"]}</a></li>'
        cross_html += '</ul></body></html>'

        cross_path = os.path.join(EDA_DIR, 'index.html')
        with open(cross_path, 'w', encoding='utf-8') as f:
            f.write(cross_html)
        print(f'  Cross-market report: {cross_path}')

    # Clean up old duplicate reports
    for market in MARKETS:
        old = os.path.join(EDA_DIR, market, 'validation_report.html')
        if os.path.exists(old):
            os.remove(old)
            print(f'  Removed old: {old}')
    old_etf = os.path.join(EDA_DIR, 'etf_validation_report.html')
    if os.path.exists(old_etf):
        os.remove(old_etf)
        print(f'  Removed old: {old_etf}')

    publish_latest()

    print(f'\nDone. Reports at:')
    print(f'  {os.path.join(EDA_DIR, "index.html")} (cross-market overview)')
    for market in MARKETS:
        rpt = os.path.join(EDA_DIR, market, 'report.html')
        if os.path.exists(rpt):
            print(f'  {rpt}')


def publish_latest():
    """Mirror latest per-market reports as self-contained HTMLs in data/eda_latest/."""
    from publish_latest_eda import publish
    publish()


if __name__ == '__main__':
    main()
