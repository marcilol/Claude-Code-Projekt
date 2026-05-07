# -*- coding: utf-8 -*-
"""
Per-market EDA & Visualization Report — per spec in data/eda/per_market_eda_report_spec.md

Generates one comprehensive HTML report per market plus a cross-market appendix.

Usage: py scripts/generate_market_report.py
"""

import os
import sys
import sqlite3
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
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


def save_plot(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)


def df_to_html(df, max_rows=50):
    if len(df) > max_rows:
        df = df.head(max_rows)
    return df.to_html(index=False, float_format=lambda x: f'{x:,.4g}', classes='tbl')


def load_market(market):
    m = MARKETS[market]
    files = {}
    for key in ['cs_data', 'factor_returns', 'factor_cov', 'factor_stats', 'r2']:
        path = os.path.join(MODEL_DIR, m[key])
        if not os.path.exists(path):
            return None
        if key == 'cs_data':
            files[key] = pd.read_csv(path)
        elif key == 'r2':
            files[key] = pd.read_csv(path, index_col=0)['R2']
        else:
            files[key] = pd.read_csv(path, index_col=0)
    return files


# ================================================================== #
#  SECTION GENERATORS
# ================================================================== #

def section_universe_coverage(data, industry_cols, plots_dir):
    """1.1 Universe and coverage"""
    dates = sorted(data['date'].unique())
    stocks_per_date = data.groupby('date')['stocknames'].nunique()

    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.plot(range(len(stocks_per_date)), stocks_per_date.values, lw=1, color='steelblue')
    ax.set_title(f'Stocks per date (min={stocks_per_date.min()}, max={stocks_per_date.max()}, mean={stocks_per_date.mean():.0f})')
    ax.set_ylabel('Stocks')
    n_t = min(8, len(dates))
    idx = np.linspace(0, len(dates)-1, n_t, dtype=int)
    ax.set_xticks(idx)
    ax.set_xticklabels([dates[i][:10] for i in idx], rotation=30, fontsize=8)
    save_plot(fig, os.path.join(plots_dir, 'universe_coverage.png'))

    # Industry distribution on latest date
    latest = data[data['date'] == dates[-1]]
    ind_dist = latest[industry_cols].sum().sort_values(ascending=False)

    fig2, ax2 = plt.subplots(figsize=(10, max(4, len(ind_dist)*0.25)))
    ax2.barh(range(len(ind_dist)), ind_dist.values, color='teal')
    ax2.set_yticks(range(len(ind_dist)))
    ax2.set_yticklabels(ind_dist.index, fontsize=8)
    ax2.invert_yaxis()
    ax2.set_title(f'Stocks per industry ({dates[-1]})')
    save_plot(fig2, os.path.join(plots_dir, 'industry_distribution.png'))

    # Size deciles
    latest_cap = latest[['stocknames', 'capital']].dropna()
    if len(latest_cap) > 10:
        latest_cap['decile'] = pd.qcut(latest_cap['capital'].rank(method='first'), 10,
                                       labels=[f'D{i}' for i in range(1, 11)])
        dec_counts = latest_cap.groupby('decile').size()

    # Entries/exits
    first_dates = data.groupby('stocknames')['date'].min()
    last_dates = data.groupby('stocknames')['date'].max()
    entries_per_date = first_dates.value_counts().sort_index()
    exits = last_dates[last_dates < dates[-1]].value_counts().sort_index()

    html = f"""
    <img class="plot" src="plots/universe_coverage.png">
    <img class="plot" src="plots/industry_distribution.png">
    <p>Total unique stocks: {data['stocknames'].nunique()}.
    Entered during panel: {(first_dates > dates[0]).sum()}.
    Exited before end: {(last_dates < dates[-1]).sum()}.</p>
    """
    return 'Universe and Coverage', f'{stocks_per_date.mean():.0f} stocks/date avg, {len(industry_cols)} industries', html


def section_dispersion(data, plots_dir):
    """1.2 Cross-sectional dispersion"""
    dates = sorted(data['date'].unique())
    ew_disp, cw_disp = [], []
    for d in dates:
        dd = data[data['date'] == d]
        ew_disp.append(dd['ret'].std())
        cap = dd['capital'].values
        if cap.sum() > 0:
            w = cap / cap.sum()
            mu = np.sum(w * dd['ret'].values)
            cw_disp.append(np.sqrt(np.sum(w * (dd['ret'].values - mu)**2)))
        else:
            cw_disp.append(np.nan)

    ew_s = pd.Series(ew_disp, index=dates)
    cw_s = pd.Series(cw_disp, index=dates)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(range(len(dates)), ew_s.values, lw=0.8, alpha=0.7, label='Equal-weighted')
    ax.plot(range(len(dates)), cw_s.values, lw=0.8, alpha=0.7, label='Cap-weighted')
    ax.set_title('Cross-sectional return dispersion over time')
    ax.set_ylabel('Std of daily returns')
    ax.legend()
    n_t = min(8, len(dates))
    idx = np.linspace(0, len(dates)-1, n_t, dtype=int)
    ax.set_xticks(idx)
    ax.set_xticklabels([dates[i][:10] for i in idx], rotation=30, fontsize=8)
    save_plot(fig, os.path.join(plots_dir, 'dispersion.png'))

    # Top/bottom 10
    top10 = ew_s.nlargest(10)
    bot10 = ew_s.nsmallest(10)
    top_html = pd.DataFrame({'date': top10.index, 'ew_dispersion': top10.values}).to_html(index=False, classes='tbl')
    bot_html = pd.DataFrame({'date': bot10.index, 'ew_dispersion': bot10.values}).to_html(index=False, classes='tbl')

    html = f"""
    <img class="plot" src="plots/dispersion.png">
    <p><b>Top 10 highest-dispersion days:</b></p>{top_html}
    <p><b>Bottom 10 lowest-dispersion days:</b></p>{bot_html}
    """
    return 'Cross-Sectional Dispersion', f'EW avg: {ew_s.mean():.5f}, CW avg: {cw_s.mean():.5f}', html


def section_factor_descriptives(fr, stats):
    """1.3 Factor return descriptive statistics"""
    rows = []
    for f in fr.columns:
        s = fr[f].dropna()
        cum = s.cumsum()
        dd = cum - cum.cummax()
        rows.append({
            'Factor': f,
            'Mean (% ann)': round(s.mean() * 252 * 100, 2),
            'Vol (% ann)': round(s.std() * np.sqrt(252) * 100, 2),
            't-stat': round(s.mean() / s.std() * np.sqrt(len(s)), 2) if s.std() > 0 else 0,
            'Skew': round(s.skew(), 2),
            'Kurtosis': round(s.kurtosis(), 2),
            'Min (%)': round(s.min() * 100, 3),
            'Max (%)': round(s.max() * 100, 3),
            '% Positive': round(100 * (s > 0).mean(), 1),
            'Max DD (%)': round(dd.min() * 100, 2),
        })
    df = pd.DataFrame(rows)
    fat_tails = df[df['Kurtosis'] > 5]

    html = df_to_html(df)
    if len(fat_tails) > 0:
        html += f'<p><b>Fat tails (kurtosis > 5):</b> {", ".join(fat_tails["Factor"].tolist())}</p>'
    return 'Factor Return Statistics', f'{len(df)} factors, {len(fat_tails)} with kurtosis > 5', html


def section_factor_stability(data, plots_dir):
    """1.4 Factor stability — cross-sectional correlation of exposures from t to t+1"""
    dates = sorted(data['date'].unique())
    stability = {}

    for f in STYLE_COLS:
        corrs = []
        for i in range(len(dates) - 1):
            d1 = data[data['date'] == dates[i]][['stocknames', f]].dropna()
            d2 = data[data['date'] == dates[i+1]][['stocknames', f]].dropna()
            merged = d1.merge(d2, on='stocknames', suffixes=('_t', '_t1'))
            if len(merged) > 30:
                corrs.append(merged[f'{f}_t'].corr(merged[f'{f}_t1']))
        stability[f] = np.mean(corrs) if corrs else np.nan

    df = pd.DataFrame({'Factor': list(stability.keys()), 'Avg t-to-t+1 corr': list(stability.values())})
    df['Status'] = df['Avg t-to-t+1 corr'].apply(
        lambda x: 'Desirable (>0.90)' if x > 0.90 else ('Acceptable (0.80-0.90)' if x > 0.80 else 'UNSTABLE (<0.80)'))
    df = df.sort_values('Avg t-to-t+1 corr', ascending=False)

    unstable = df[df['Avg t-to-t+1 corr'] < 0.80]
    html = df_to_html(df)
    if len(unstable) > 0:
        html += f'<p style="color:red"><b>Unstable factors:</b> {", ".join(unstable["Factor"].tolist())}</p>'

    return 'Factor Stability (USE4 eq 2.1)', f'Avg stability: {df["Avg t-to-t+1 corr"].mean():.3f}. {len(unstable)} unstable.', html


def section_per_stock_r2(data, fr, industry_cols, plots_dir):
    """1.5 Per-stock R² distribution"""
    dates = sorted(data['date'].unique())

    # For each stock, compute time-series R² of actual vs predicted returns
    stock_r2 = {}
    for ticker, grp in data.groupby('stocknames'):
        if len(grp) < 30:
            continue
        grp = grp.sort_values('date')
        actual = grp['ret'].values

        # Predicted = sum of (exposure × factor return) for each date
        predicted = []
        for _, row in grp.iterrows():
            d = row['date']
            if d not in fr.index:
                predicted.append(np.nan)
                continue
            pred = fr.loc[d, 'Country']  # country exposure = 1
            for ind in industry_cols:
                if row.get(ind, 0) == 1 and ind in fr.columns:
                    pred += fr.loc[d, ind]
            for sf in STYLE_COLS:
                if sf in fr.columns and sf in row.index:
                    pred += row[sf] * fr.loc[d, sf]
            predicted.append(pred)

        predicted = np.array(predicted)
        valid = ~np.isnan(predicted) & ~np.isnan(actual)
        if valid.sum() < 20:
            continue
        ss_res = np.sum((actual[valid] - predicted[valid])**2)
        ss_tot = np.sum((actual[valid] - actual[valid].mean())**2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        stock_r2[ticker] = r2

    r2_series = pd.Series(stock_r2)

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.hist(r2_series.dropna(), bins=50, color='steelblue', edgecolor='white')
    ax.axvline(r2_series.median(), color='red', lw=2, label=f'Median ({r2_series.median():.3f})')
    ax.set_title(f'Per-stock time-series R² ({len(r2_series)} stocks)')
    ax.set_xlabel('R²')
    ax.legend()
    save_plot(fig, os.path.join(plots_dir, 'per_stock_r2.png'))

    top20 = r2_series.nlargest(20).reset_index()
    top20.columns = ['Ticker', 'R2']
    bot20 = r2_series.nsmallest(20).reset_index()
    bot20.columns = ['Ticker', 'R2']

    html = f"""
    <img class="plot" src="plots/per_stock_r2.png">
    <p>Median per-stock R²: {r2_series.median():.3f}, Mean: {r2_series.mean():.3f}</p>
    <p><b>Top 20 best-explained:</b></p>{df_to_html(top20)}
    <p><b>Bottom 20 worst-explained:</b></p>{df_to_html(bot20)}
    """
    return 'Per-Stock R² Distribution', f'Median={r2_series.median():.3f}, {len(r2_series)} stocks', html


def section_country_vs_market(data, fr, plots_dir):
    """2.1 Country factor vs market return"""
    dates = sorted(data['date'].unique())
    mkt, cty = [], []
    for d in dates:
        dd = data[data['date'] == d]
        cap = dd['capital'].values
        if cap.sum() == 0 or d not in fr.index:
            continue
        w = cap / cap.sum()
        mkt.append(np.sum(w * dd['ret'].values))
        cty.append(fr.loc[d, 'Country'])

    corr = np.corrcoef(mkt, cty)[0, 1] if len(mkt) > 10 else np.nan
    cum_mkt = np.cumsum(mkt) * 100
    cum_cty = np.cumsum(cty) * 100

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    # Cumulative
    axes[0].plot(cum_mkt, label='Cap-weighted market', lw=1.5)
    axes[0].plot(cum_cty, label='Country factor', lw=1.5, ls='--')
    axes[0].set_title(f'Cumulative returns (corr = {corr:.4f})')
    axes[0].set_ylabel('Cumulative return (%)')
    axes[0].legend()
    # Scatter
    axes[1].scatter(mkt, cty, s=8, alpha=0.4, color='steelblue')
    lims = [min(min(mkt), min(cty))*1.1, max(max(mkt), max(cty))*1.1]
    axes[1].plot(lims, lims, 'k--', lw=0.5)
    axes[1].set_xlabel('Market return')
    axes[1].set_ylabel('Country return')
    axes[1].set_title(f'Daily scatter (corr = {corr:.4f})')
    save_plot(fig, os.path.join(plots_dir, 'country_vs_market.png'))

    html = f'<img class="plot" src="plots/country_vs_market.png">'
    return 'Country Factor vs Market Return', f'Correlation = {corr:.4f}', html


def section_cumulative_style(fr, plots_dir):
    """2.2 Cumulative style factor returns"""
    style_fr = fr[[c for c in STYLE_COLS if c in fr.columns]]
    cum = (style_fr.cumsum() * 100)

    fig, ax = plt.subplots(figsize=(12, 5))
    for col in cum.columns:
        ax.plot(range(len(cum)), cum[col].values, lw=1.2, label=col)
    ax.set_title('Cumulative style factor returns')
    ax.set_ylabel('Cumulative return (%)')
    ax.legend(bbox_to_anchor=(1.02, 1), loc='upper left', fontsize=8)
    ax.axhline(0, color='k', lw=0.5)
    n_t = min(8, len(cum))
    idx = np.linspace(0, len(cum)-1, n_t, dtype=int)
    ax.set_xticks(idx)
    ax.set_xticklabels([fr.index[i][:10] for i in idx], rotation=30, fontsize=8)
    save_plot(fig, os.path.join(plots_dir, 'cumulative_style.png'))

    html = f'<img class="plot" src="plots/cumulative_style.png">'
    return 'Cumulative Style Factor Returns', '', html


def section_cumulative_industry(fr, industry_cols, plots_dir):
    """2.3 Cumulative industry factor returns"""
    ind_fr = fr[[c for c in industry_cols if c in fr.columns]]
    cum = (ind_fr.cumsum() * 100)

    fig, ax = plt.subplots(figsize=(12, 6))
    for col in cum.columns:
        ax.plot(range(len(cum)), cum[col].values, lw=1, alpha=0.8, label=col)
    ax.set_title('Cumulative industry factor returns')
    ax.set_ylabel('Cumulative return (%)')
    ax.legend(bbox_to_anchor=(1.02, 1), loc='upper left', fontsize=7)
    ax.axhline(0, color='k', lw=0.5)
    n_t = min(8, len(cum))
    idx = np.linspace(0, len(cum)-1, n_t, dtype=int)
    ax.set_xticks(idx)
    ax.set_xticklabels([fr.index[i][:10] for i in idx], rotation=30, fontsize=8)
    save_plot(fig, os.path.join(plots_dir, 'cumulative_industry.png'))

    html = f'<img class="plot" src="plots/cumulative_industry.png">'
    return 'Cumulative Industry Factor Returns', '', html


def section_dispersion_r2_overlay(data, r2, plots_dir):
    """2.4 Dispersion with R² overlay"""
    dates = sorted(data['date'].unique())
    disp = data.groupby('date')['ret'].std()
    disp_smooth = disp.rolling(21, min_periods=5).mean()

    fig, ax1 = plt.subplots(figsize=(10, 4))
    ax1.plot(range(len(disp_smooth)), disp_smooth.values, color='steelblue', lw=1, label='CS dispersion (21d MA)')
    ax1.set_ylabel('Dispersion', color='steelblue')

    ax2 = ax1.twinx()
    r2_aligned = r2.reindex(dates)
    r2_smooth = r2_aligned.rolling(21, min_periods=5).mean()
    ax2.plot(range(len(r2_smooth)), r2_smooth.values, color='orange', lw=1, label='R² (21d MA)')
    ax2.set_ylabel('R²', color='orange')

    ax1.set_title('Cross-sectional dispersion vs R²')
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper right')
    save_plot(fig, os.path.join(plots_dir, 'dispersion_r2.png'))

    html = f'<img class="plot" src="plots/dispersion_r2.png">'
    return 'Dispersion with R² Overlay', 'High-dispersion days produce higher R²', html


def section_style_heatmap(fr, plots_dir):
    """2.5 Style factor monthly heatmap"""
    style_fr = fr[[c for c in STYLE_COLS if c in fr.columns]].copy()
    style_fr.index = pd.to_datetime(style_fr.index)
    monthly = style_fr.resample('ME').sum() * 100

    fig, ax = plt.subplots(figsize=(14, 5))
    im = ax.imshow(monthly.T.values, aspect='auto', cmap='RdYlGn', vmin=-5, vmax=5)
    ax.set_yticks(range(len(monthly.columns)))
    ax.set_yticklabels(monthly.columns, fontsize=8)
    ax.set_xticks(range(len(monthly)))
    ax.set_xticklabels([d.strftime('%Y-%m') for d in monthly.index], rotation=45, ha='right', fontsize=7)
    ax.set_title('Monthly style factor returns (%)')
    plt.colorbar(im, ax=ax, shrink=0.8)
    save_plot(fig, os.path.join(plots_dir, 'style_heatmap.png'))

    html = f'<img class="plot" src="plots/style_heatmap.png">'
    return 'Style Factor Heatmap', '', html


def section_factor_correlation_ts(fr, plots_dir):
    """2.6 Factor correlation heatmap (time-series)"""
    corr = fr.corr()

    fig, ax = plt.subplots(figsize=(12, 10))
    im = ax.imshow(corr.values, cmap='RdBu_r', vmin=-1, vmax=1, aspect='auto')
    ax.set_xticks(range(len(corr)))
    ax.set_xticklabels(corr.columns, rotation=90, fontsize=6)
    ax.set_yticks(range(len(corr)))
    ax.set_yticklabels(corr.columns, fontsize=6)
    ax.set_title('Factor return time-series correlation')
    plt.colorbar(im, ax=ax, shrink=0.7)
    save_plot(fig, os.path.join(plots_dir, 'factor_corr_ts.png'))

    html = f'<img class="plot" src="plots/factor_corr_ts.png">'
    return 'Factor Correlation (Time-Series)', f'Country-Beta corr: {corr.loc["Country","beta"]:.3f}' if 'beta' in corr.columns else '', html


def section_exposure_histograms(data, plots_dir):
    """2.7 Exposure distribution histograms"""
    latest = data[data['date'] == data['date'].max()]

    fig, axes = plt.subplots(2, 5, figsize=(16, 6))
    for i, f in enumerate(STYLE_COLS):
        ax = axes[i // 5][i % 5]
        vals = latest[f].dropna()
        if len(vals) > 0:
            ax.hist(vals, bins=40, color='steelblue', edgecolor='white')
            ax.axvline(0, color='red', lw=0.5)
            ax.set_title(f, fontsize=9)
        ax.tick_params(labelsize=7)
    fig.suptitle('Style factor z-score distributions (latest date)', fontsize=11)
    save_plot(fig, os.path.join(plots_dir, 'exposure_histograms.png'))

    html = f'<img class="plot" src="plots/exposure_histograms.png">'
    return 'Exposure Distributions', '', html


def section_rolling_r2(r2, plots_dir):
    """2.8 Rolling R²"""
    r60 = r2.rolling(60, min_periods=30).mean()

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(range(len(r2)), r2.values, alpha=0.3, lw=0.5, color='grey', label='Daily')
    ax.plot(range(len(r60)), r60.values, lw=1.5, color='steelblue', label='60-day MA')
    ax.set_title('Rolling R²')
    ax.set_ylabel('R²')
    ax.legend()
    n_t = min(8, len(r2))
    idx = np.linspace(0, len(r2)-1, n_t, dtype=int)
    ax.set_xticks(idx)
    ax.set_xticklabels([r2.index[i][:10] for i in idx], rotation=30, fontsize=8)
    save_plot(fig, os.path.join(plots_dir, 'rolling_r2.png'))

    html = f'<img class="plot" src="plots/rolling_r2.png">'
    return 'Rolling R²', f'60d MA range: {r60.dropna().min():.3f} to {r60.dropna().max():.3f}', html


def section_risk_decomposition(data, fr, industry_cols, cov, plots_dir):
    """2.10 Risk decomposition for equal-weighted portfolio"""
    latest_date = data['date'].max()
    dd = data[data['date'] == latest_date]
    n = len(dd)
    if n == 0:
        return 'Risk Decomposition', 'No data', ''

    w = np.ones(n) / n  # equal weight

    # Portfolio exposures
    country_exp = 1.0
    ind_exp = {}
    for ind in industry_cols:
        if ind in dd.columns and ind in cov.columns:
            ind_exp[ind] = (w * dd[ind].values).sum()
    style_exp = {}
    for sf in STYLE_COLS:
        if sf in dd.columns and sf in cov.columns:
            style_exp[sf] = (w * dd[sf].values).sum()

    # Factor variance = b' Omega b
    factor_names = list(cov.columns)
    b = np.zeros(len(factor_names))
    for i, f in enumerate(factor_names):
        if f == 'Country':
            b[i] = country_exp
        elif f in ind_exp:
            b[i] = ind_exp[f]
        elif f in style_exp:
            b[i] = style_exp[f]

    factor_var = b @ cov.values @ b * 252  # annualize

    # Decompose: country, industry, style contributions
    omega_b = cov.values @ b
    contrib = b * omega_b * 252

    country_var = contrib[factor_names.index('Country')] if 'Country' in factor_names else 0
    industry_var = sum(contrib[i] for i, f in enumerate(factor_names) if f in ind_exp)
    style_var = sum(contrib[i] for i, f in enumerate(factor_names) if f in style_exp)

    # Specific variance (approximate)
    # Use last 60 days of specific returns
    dates = sorted(data['date'].unique())[-60:]
    resids = []
    for d in dates:
        dd_d = data[data['date'] == d]
        if d not in fr.index:
            continue
        for _, row in dd_d.iterrows():
            pred = fr.loc[d, 'Country']
            for ind in industry_cols:
                if row.get(ind, 0) == 1 and ind in fr.columns:
                    pred += fr.loc[d, ind]
            for sf in STYLE_COLS:
                if sf in fr.columns:
                    pred += row[sf] * fr.loc[d, sf]
            resids.append(row['ret'] - pred)
    spec_var = np.var(resids) * 252 if resids else 0
    total_var = factor_var + spec_var

    pcts = {
        'Country': 100 * country_var / total_var if total_var > 0 else 0,
        'Industries': 100 * industry_var / total_var if total_var > 0 else 0,
        'Styles': 100 * style_var / total_var if total_var > 0 else 0,
        'Specific': 100 * spec_var / total_var if total_var > 0 else 0,
    }

    fig, ax = plt.subplots(figsize=(8, 5))
    names = list(pcts.keys())
    vals = list(pcts.values())
    colors = ['#2952a3', '#7eb8da', '#a8d8a8', '#e8e8e8']
    # Use bar chart instead of pie — handles negative values
    bars = ax.barh(range(len(names)), vals, color=colors)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names)
    ax.set_xlabel('% of total variance')
    ax.axvline(0, color='k', lw=0.5)
    for i, v in enumerate(vals):
        ax.text(max(v, 0) + 1, i, f'{v:.1f}%', va='center', fontsize=9)
    ax.set_title(f'Risk decomposition (equal-weight portfolio)\nTotal vol: {np.sqrt(max(total_var, 0))*100:.1f}% ann')
    save_plot(fig, os.path.join(plots_dir, 'risk_decomposition.png'))

    html = f'<img class="plot" src="plots/risk_decomposition.png">'
    return 'Risk Decomposition (Equal-Weight)', f'Factor: {100-pcts["Specific"]:.1f}%, Specific: {pcts["Specific"]:.1f}%', html


# ================================================================== #
#  EXECUTIVE SUMMARY
# ================================================================== #

def make_executive_summary(data, fr, r2, industry_cols, stats):
    dates = sorted(data['date'].unique())
    n_stocks = data.groupby('date')['stocknames'].nunique().mean()
    r2_mean = r2.mean()
    n_sig = sum(1 for f in STYLE_COLS if f in stats.index and abs(stats.loc[f, 't-stat']) > 1.96)
    country_ret = stats.loc['Country', 'Mean (%)'] if 'Country' in stats.index else 0
    country_t = stats.loc['Country', 't-stat'] if 'Country' in stats.index else 0

    bullets = [
        f'{len(dates)} trading days ({dates[0]} to {dates[-1]}), ~{n_stocks:.0f} stocks/date',
        f'{len(industry_cols)} industries + 10 style factors',
        f'Mean R² = {r2_mean:.1%} (median {r2.median():.1%})',
        f'Country factor: {country_ret:+.1f}% ann (t={country_t:.2f})',
        f'{n_sig} of 10 style factors significant at 95%',
    ]

    # Top significant factors
    sig = [(f, stats.loc[f, 't-stat']) for f in STYLE_COLS if f in stats.index and abs(stats.loc[f, 't-stat']) > 1.96]
    sig.sort(key=lambda x: abs(x[1]), reverse=True)
    if sig:
        bullets.append(f'Strongest: {", ".join(f"{f} (t={t:.1f})" for f, t in sig[:3])}')

    html = '<ul>' + ''.join(f'<li>{b}</li>' for b in bullets) + '</ul>'
    return html


# ================================================================== #
#  HTML BUILDER
# ================================================================== #

HTML_HEAD = """<!DOCTYPE html>
<html><head><meta charset='utf-8'><title>{title}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 1200px; margin: 20px auto; padding: 0 20px; color: #222; }}
h1 {{ border-bottom: 2px solid #333; padding-bottom: 8px; }}
h2 {{ background: #f3f3f3; padding: 8px 12px; border-left: 4px solid #2952a3; margin-top: 30px; }}
.headline {{ background: #fffbe6; border-left: 4px solid #e0a800; padding: 8px 12px; margin: 8px 0 14px; }}
.tbl {{ border-collapse: collapse; margin: 10px 0; font-size: 0.82em; }}
.tbl th, .tbl td {{ padding: 4px 8px; border: 1px solid #ccc; }}
.tbl th {{ background: #eee; text-align: left; }}
.plot {{ max-width: 100%; margin: 10px 0; border: 1px solid #ddd; }}
.meta {{ color: #666; font-size: 0.85em; }}
</style></head><body>
"""


def build_market_report(market, sections, summary_html, out_dir):
    m = MARKETS[market]
    title = f'{m["label"]} — EDA & Visualization Report'

    parts = [HTML_HEAD.format(title=title)]
    parts.append(f'<h1>{title}</h1>')
    parts.append(f'<p class="meta">Generated {datetime.now():%Y-%m-%d %H:%M}. Currency: {m["currency"]}.</p>')

    parts.append('<h2>Executive Summary</h2>')
    parts.append(summary_html)

    for sec_title, headline, body in sections:
        parts.append(f'<h2>{escape(sec_title)}</h2>')
        if headline:
            parts.append(f'<div class="headline">{escape(headline)}</div>')
        parts.append(body)

    parts.append('</body></html>')

    # Save to subfolder (for plot references)
    subfolder_path = os.path.join(out_dir, 'eda_visualization_report.html')
    with open(subfolder_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))

    # Also save timestamped copy in data/eda/
    ts = datetime.now().strftime('%Y_%m_%d_%H_%M')
    eda_dir = os.path.join(os.path.dirname(out_dir))
    flat_path = os.path.join(eda_dir, f'{market}_eda_visualization_{ts}.html')
    archive_dir = os.path.join(eda_dir, 'archive')
    os.makedirs(archive_dir, exist_ok=True)
    import glob
    for old in glob.glob(os.path.join(eda_dir, f'{market}_eda_visualization_*.html')):
        if old != flat_path:
            os.rename(old, os.path.join(archive_dir, os.path.basename(old)))
    with open(flat_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))

    return flat_path


# ================================================================== #
#  MAIN
# ================================================================== #

def main():
    print('=' * 60)
    print('  PER-MARKET EDA & VISUALIZATION REPORT')
    print('=' * 60)

    all_country_cum = {}

    for market, m in MARKETS.items():
        out_dir = os.path.join(EDA_DIR, market)
        plots_dir = os.path.join(out_dir, 'plots')
        os.makedirs(plots_dir, exist_ok=True)

        print(f'\n  {m["label"]}...', flush=True)

        files = load_market(market)
        if files is None:
            print(f'    SKIP: model files not found')
            continue

        data = files['cs_data']
        fr = files['factor_returns']
        r2 = files['r2']
        stats = files['factor_stats']
        cov = files['factor_cov']
        industry_cols = [c for c in data.columns
                         if c not in ['date', 'stocknames', 'capital', 'ret'] + STYLE_COLS]

        sections = []

        # Part 1: Exploratory statistics
        print('    1.1 Universe...', flush=True)
        sections.append(section_universe_coverage(data, industry_cols, plots_dir))
        print('    1.2 Dispersion...', flush=True)
        sections.append(section_dispersion(data, plots_dir))
        print('    1.3 Factor descriptives...', flush=True)
        sections.append(section_factor_descriptives(fr, stats))
        print('    1.4 Factor stability...', flush=True)
        sections.append(section_factor_stability(data, plots_dir))
        print('    1.5 Per-stock R²...', flush=True)
        sections.append(section_per_stock_r2(data, fr, industry_cols, plots_dir))

        # Part 2: Visualizations
        print('    2.1 Country vs market...', flush=True)
        sections.append(section_country_vs_market(data, fr, plots_dir))
        print('    2.2 Cumulative style...', flush=True)
        sections.append(section_cumulative_style(fr, plots_dir))
        print('    2.3 Cumulative industry...', flush=True)
        sections.append(section_cumulative_industry(fr, industry_cols, plots_dir))
        print('    2.4 Dispersion + R²...', flush=True)
        sections.append(section_dispersion_r2_overlay(data, r2, plots_dir))
        print('    2.5 Style heatmap...', flush=True)
        sections.append(section_style_heatmap(fr, plots_dir))
        print('    2.6 Factor correlation...', flush=True)
        sections.append(section_factor_correlation_ts(fr, plots_dir))
        print('    2.7 Exposure histograms...', flush=True)
        sections.append(section_exposure_histograms(data, plots_dir))
        print('    2.8 Rolling R²...', flush=True)
        sections.append(section_rolling_r2(r2, plots_dir))
        print('    2.10 Risk decomposition...', flush=True)
        sections.append(section_risk_decomposition(data, fr, industry_cols, cov, plots_dir))

        summary = make_executive_summary(data, fr, r2, industry_cols, stats)
        path = build_market_report(market, sections, summary, out_dir)
        print(f'    Report: {path}')

        # Save cumulative country for cross-market
        all_country_cum[market] = fr['Country'].cumsum() * 100

    # Cross-market appendix: cumulative Country
    if len(all_country_cum) > 1:
        plots_dir = os.path.join(EDA_DIR, 'plots')
        os.makedirs(plots_dir, exist_ok=True)

        fig, ax = plt.subplots(figsize=(10, 5))
        for mkt, cum in all_country_cum.items():
            ax.plot(range(len(cum)), cum.values, lw=1.5, label=MARKETS[mkt]['label'])
        ax.set_title('Cumulative Country Factor Return — All Markets')
        ax.set_ylabel('Cumulative return (%)')
        ax.legend()
        ax.axhline(0, color='k', lw=0.5)
        save_plot(fig, os.path.join(plots_dir, 'cross_market_country.png'))

    publish_latest()
    print(f'\nDone.')


def publish_latest():
    """Mirror latest per-market reports as self-contained HTMLs in data/eda_latest/."""
    from publish_latest_eda import publish
    publish()


if __name__ == '__main__':
    main()
