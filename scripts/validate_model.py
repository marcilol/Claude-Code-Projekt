# -*- coding: utf-8 -*-
"""
Barra Factor Model Validation — overnight checks.

Runs 8 validation checks from the model validation checklist:
  1. .fillna(0) audit on style factors
  2. Single-day deep-dive report
  3. CAPM benchmark R² comparison
  4. Rolling R² (60-day window)
  5. Factor loading sanity on known stocks
  6. Residual autocorrelation test
  7. Lookahead test (shift dates ±1)
  8. VIF per factor

Outputs:
  data/eda/validation_report_<date>.html
  data/eda/validation_*.csv / *.png

Run: py scripts/validate_model.py
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
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(__file__))

REPORT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'eda')
PLOTS_DIR = os.path.join(REPORT_DIR, 'plots')
MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'model')
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'db', 'market_data.db')

STYLE_COLS = ['size', 'beta', 'momentum', 'residvol', 'nlsize', 'btop',
              'liquidity', 'earnyild', 'growth', 'leverage']

_sections = []


def add_section(n, title, headline, body='', csv_rel=None, plot_rel=None):
    _sections.append({
        'n': n, 'title': title, 'headline': headline,
        'body': body, 'csv': csv_rel, 'plot': plot_rel,
    })


def save_plot(fig, slug):
    path = os.path.join(PLOTS_DIR, f'{slug}.png')
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return os.path.relpath(path, REPORT_DIR).replace('\\', '/')


def save_csv(df, slug):
    path = os.path.join(REPORT_DIR, f'{slug}.csv')
    df.to_csv(path, index=False)
    return os.path.relpath(path, REPORT_DIR).replace('\\', '/')


def df_to_html(df, max_rows=30):
    if len(df) > max_rows:
        df = df.head(max_rows)
    return df.to_html(index=False, float_format=lambda x: f'{x:,.4g}', classes='tbl')


def load_cross_sectional_data():
    path = os.path.join(MODEL_DIR, 'russell3000_cross_sectional_data.csv')
    return pd.read_csv(path)


def load_factor_returns():
    path = os.path.join(MODEL_DIR, 'barra_factor_returns.csv')
    return pd.read_csv(path, index_col=0)


def load_r2():
    path = os.path.join(MODEL_DIR, 'barra_r2.csv')
    return pd.read_csv(path, index_col=0)


# ------------------------------------------------------------------ #
#  Check 1: .fillna(0) audit
# ------------------------------------------------------------------ #

def check_01_fillna_audit():
    print('  Running check 1: fillna(0) audit...', flush=True)
    data = load_cross_sectional_data()
    results = []
    for col in STYLE_COLS:
        total = len(data)
        n_zero = (data[col] == 0).sum()
        n_nan = data[col].isna().sum()
        pct_zero = 100 * n_zero / total
        results.append({
            'factor': col, 'total_rows': total,
            'n_zero': int(n_zero), 'pct_zero': round(pct_zero, 2),
            'n_nan': int(n_nan),
        })
    df = pd.DataFrame(results)
    csv = save_csv(df, 'val_01_fillna')

    suspicious = df[df['pct_zero'] > 5]
    body = f"""
    <p>The regression code does <code>.fillna(0)</code> on style factors before regression.
    A zero z-score means "average stock" — applying it to genuinely missing data corrupts the regression.
    Factors with &gt;5% zeros are suspicious (some zeros are legitimate — stocks near the cross-sectional mean).</p>
    {df_to_html(df)}
    """
    add_section(1, 'fillna(0) audit on style factors',
        f'{len(suspicious)} factors have >5% zero values.',
        body, csv_rel=csv)


# ------------------------------------------------------------------ #
#  Check 2: Single-day deep-dive
# ------------------------------------------------------------------ #

def check_02_single_day_deep_dive():
    print('  Running check 2: single-day deep-dive...', flush=True)
    data = load_cross_sectional_data()
    fr = load_factor_returns()
    r2 = load_r2()

    # Pick a mid-sample date
    dates = sorted(data['date'].unique())
    mid_date = dates[len(dates) // 2]

    dd = data[data['date'] == mid_date].copy()
    day_fr = fr.loc[mid_date] if mid_date in fr.index else pd.Series(dtype=float)
    day_r2 = r2.loc[mid_date, 'R2'] if mid_date in r2.index else np.nan

    # Known tickers
    known = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'JPM', 'XOM', 'JNJ', 'BRK-B', 'META', 'TSLA']
    exposure_df = dd[dd['stocknames'].isin(known)][['stocknames'] + STYLE_COLS].copy()
    exposure_df = exposure_df.set_index('stocknames').reindex(known).reset_index()

    # Top 5 residuals (largest absolute specific return)
    industry_cols = [c for c in dd.columns if c not in ['date', 'stocknames', 'capital', 'ret'] + STYLE_COLS]
    if not day_fr.empty:
        X = dd[['stocknames']].copy()
        exposures = dd[industry_cols + STYLE_COLS].fillna(0).values
        country = np.ones((len(dd), 1))
        full_X = np.hstack([country, exposures])
        predicted = full_X @ day_fr.values
        X['actual_ret'] = dd['ret'].values
        X['predicted_ret'] = predicted
        X['residual'] = X['actual_ret'] - X['predicted_ret']
        top_resid = X.reindex(X['residual'].abs().nlargest(5).index)
    else:
        top_resid = pd.DataFrame()

    csv1 = save_csv(exposure_df, 'val_02_exposures')
    csv2 = save_csv(top_resid if not top_resid.empty else pd.DataFrame(), 'val_02_residuals')

    # Factor returns for that day
    fr_day = day_fr.reset_index()
    fr_day.columns = ['factor', 'return']
    csv3 = save_csv(fr_day, 'val_02_factor_returns')

    body = f"""
    <p><b>Date:</b> {mid_date} | <b>R2:</b> {day_r2:.4f} | <b>Stocks:</b> {len(dd)}</p>
    <h3>Exposures for known stocks</h3>
    {df_to_html(exposure_df)}
    <h3>Factor returns</h3>
    {df_to_html(fr_day)}
    <h3>Top 5 residuals (largest absolute specific return)</h3>
    {df_to_html(top_resid) if not top_resid.empty else '<p>Could not compute</p>'}
    """
    add_section(2, f'Single-day deep-dive ({mid_date})',
        f'R2 = {day_r2:.4f} on {len(dd)} stocks. Exposures for {len(exposure_df.dropna())} known tickers shown.',
        body, csv_rel=csv1)


# ------------------------------------------------------------------ #
#  Check 3: CAPM benchmark R²
# ------------------------------------------------------------------ #

def check_03_capm_benchmark():
    print('  Running check 3: CAPM benchmark R2...', flush=True)
    data = load_cross_sectional_data()

    dates = sorted(data['date'].unique())
    r2_full = load_r2()

    capm_r2 = []
    for date in dates:
        dd = data[data['date'] == date]
        y = dd['ret'].values
        cap = dd['capital'].values
        if len(y) < 50 or np.all(cap == 0):
            capm_r2.append(np.nan)
            continue
        w = np.sqrt(cap) / np.sqrt(cap).sum()
        # CAPM: just an intercept (country factor = column of ones)
        X = np.ones((len(y), 1))
        W = np.diag(w)
        try:
            beta = np.linalg.lstsq(W @ X, W @ y, rcond=None)[0]
            pred = X @ beta
            ss_res = np.sum(w * (y - pred)**2)
            ss_tot = np.sum(w * y**2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            capm_r2.append(r2)
        except Exception:
            capm_r2.append(np.nan)

    capm_df = pd.DataFrame({'date': dates, 'capm_r2': capm_r2})
    capm_df['full_r2'] = r2_full.reindex(dates)['R2'].values
    capm_df['style_lift'] = capm_df['full_r2'] - capm_df['capm_r2']
    csv = save_csv(capm_df, 'val_03_capm')

    mean_capm = capm_df['capm_r2'].mean()
    mean_full = capm_df['full_r2'].mean()
    mean_lift = capm_df['style_lift'].mean()

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(range(len(dates)), capm_df['capm_r2'], label=f'CAPM only (avg {mean_capm:.3f})', alpha=0.7)
    ax.plot(range(len(dates)), capm_df['full_r2'], label=f'Full model (avg {mean_full:.3f})', alpha=0.7)
    ax.set_title('CAPM vs Full Model R2 per date')
    ax.set_ylabel('R2')
    ax.legend()
    plot = save_plot(fig, 'val_03_capm')

    body = f"""
    <p>If CAPM gives ~{mean_capm:.1%} and the full model gives ~{mean_full:.1%}, the style+industry factors
    add {mean_lift:.1%} of explanatory power. If the lift is tiny, the factors may be miscomputed.</p>
    <p><b>CAPM avg R2:</b> {mean_capm:.4f} | <b>Full avg R2:</b> {mean_full:.4f} | <b>Lift:</b> {mean_lift:.4f}</p>
    """
    add_section(3, 'CAPM benchmark R2 comparison',
        f'CAPM R2 = {mean_capm:.3f}, Full = {mean_full:.3f}, lift = {mean_lift:.3f}.',
        body, csv_rel=csv, plot_rel=plot)


# ------------------------------------------------------------------ #
#  Check 4: Rolling R²
# ------------------------------------------------------------------ #

def check_04_rolling_r2():
    print('  Running check 4: rolling R2...', flush=True)
    r2 = load_r2()
    r2['rolling_60'] = r2['R2'].rolling(60, min_periods=30).mean()
    r2['rolling_120'] = r2['R2'].rolling(120, min_periods=60).mean()
    csv = save_csv(r2.reset_index(), 'val_04_rolling_r2')

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(range(len(r2)), r2['R2'], alpha=0.3, label='Daily R2')
    ax.plot(range(len(r2)), r2['rolling_60'], label='60-day MA', linewidth=2)
    ax.plot(range(len(r2)), r2['rolling_120'], label='120-day MA', linewidth=2)
    ax.set_title('Rolling R2')
    ax.set_ylabel('R2')
    ax.legend()
    n_ticks = min(8, len(r2))
    tick_idx = np.linspace(0, len(r2)-1, n_ticks, dtype=int)
    ax.set_xticks(tick_idx)
    ax.set_xticklabels([r2.index[i][:10] for i in tick_idx], rotation=30)
    plot = save_plot(fig, 'val_04_rolling_r2')

    r2_range = r2['rolling_60'].dropna()
    body = f"""
    <p>If rolling R2 swings wildly (e.g., 10% to 60%), the model is unstable or missing a regime factor.</p>
    <p><b>60-day rolling R2 range:</b> {r2_range.min():.3f} to {r2_range.max():.3f}</p>
    """
    add_section(4, 'Rolling R2 (60-day and 120-day)',
        f'60d rolling R2 range: {r2_range.min():.3f} to {r2_range.max():.3f}.',
        body, csv_rel=csv, plot_rel=plot)


# ------------------------------------------------------------------ #
#  Check 5: Factor loading sanity on known stocks
# ------------------------------------------------------------------ #

def check_05_known_stock_loadings():
    print('  Running check 5: known stock loadings...', flush=True)
    data = load_cross_sectional_data()
    latest_date = data['date'].max()
    dd = data[data['date'] == latest_date]

    checks = {
        'AAPL':  {'size': 'positive (mega-cap)', 'momentum': 'any', 'beta': 'near zero or slightly positive'},
        'BRK-B': {'btop': 'positive (value)', 'size': 'positive (mega-cap)'},
        'NVDA':  {'momentum': 'any', 'residvol': 'positive (volatile)', 'size': 'positive'},
        'XOM':   {'btop': 'positive (value)', 'leverage': 'positive'},
        'TSLA':  {'residvol': 'positive (volatile)', 'beta': 'positive (high beta)'},
    }

    rows = []
    for ticker, expectations in checks.items():
        stock = dd[dd['stocknames'] == ticker]
        if stock.empty:
            rows.append({'ticker': ticker, 'found': False})
            continue
        row = {'ticker': ticker, 'found': True}
        for factor in STYLE_COLS:
            val = stock[factor].iloc[0]
            row[factor] = round(val, 3) if pd.notna(val) else np.nan
        row['expected'] = str(expectations)
        rows.append(row)

    df = pd.DataFrame(rows)
    csv = save_csv(df, 'val_05_known_loadings')

    body = f"""
    <p>On the latest date ({latest_date}), check that well-known stocks have loadings matching intuition.</p>
    {df_to_html(df)}
    <p><b>Key checks:</b> AAPL should have positive size (mega-cap). BRK-B should have positive btop (value).
    TSLA should have positive residvol (volatile) and positive beta. XOM should have positive btop and leverage.</p>
    """

    n_found = df['found'].sum()
    add_section(5, 'Factor loading sanity on known stocks',
        f'{n_found}/{len(checks)} known tickers found on {latest_date}.',
        body, csv_rel=csv)


# ------------------------------------------------------------------ #
#  Check 6: Residual autocorrelation
# ------------------------------------------------------------------ #

def check_06_residual_autocorrelation():
    print('  Running check 6: factor return autocorrelation...', flush=True)
    fr = load_factor_returns()

    # Lag-1 autocorrelation per factor
    ac = {}
    for col in fr.columns:
        s = fr[col].dropna()
        if len(s) > 10:
            ac[col] = s.autocorr(lag=1)

    ac_df = pd.DataFrame({'factor': list(ac.keys()), 'lag1_autocorr': list(ac.values())})
    ac_df['abs_ac'] = ac_df['lag1_autocorr'].abs()
    ac_df = ac_df.sort_values('abs_ac', ascending=False)
    csv = save_csv(ac_df, 'val_06_autocorr')

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.barh(range(len(ac_df)), ac_df['lag1_autocorr'].values, color='steelblue')
    ax.set_yticks(range(len(ac_df)))
    ax.set_yticklabels(ac_df['factor'].values, fontsize=7)
    ax.axvline(0, color='k', lw=0.5)
    ax.axvline(0.1, color='r', lw=0.5, ls='--', label='|0.1| threshold')
    ax.axvline(-0.1, color='r', lw=0.5, ls='--')
    ax.set_title('Factor return lag-1 autocorrelation')
    ax.legend()
    plot = save_plot(fig, 'val_06_autocorr')

    high_ac = ac_df[ac_df['abs_ac'] > 0.1]
    body = f"""
    <p>Barra factor returns should have near-zero autocorrelation at lag 1. Meaningful autocorrelation
    (&gt;0.1) suggests stale data or a lookahead-adjacent bug.</p>
    {df_to_html(ac_df)}
    """
    add_section(6, 'Factor return lag-1 autocorrelation',
        f'{len(high_ac)} factors with |autocorr| > 0.1.',
        body, csv_rel=csv, plot_rel=plot)


# ------------------------------------------------------------------ #
#  Check 7: Lookahead test (shift dates ±1)
# ------------------------------------------------------------------ #

def check_07_lookahead_test():
    print('  Running check 7: lookahead test (this takes a few minutes)...', flush=True)
    data = load_cross_sectional_data()
    industry_cols = [c for c in data.columns
                     if c not in ['date', 'stocknames', 'capital', 'ret'] + STYLE_COLS]

    dates = sorted(data['date'].unique())

    def run_regressions(df, sample_dates):
        """Run WLS cross-sectional regressions, return mean R2."""
        r2_list = []
        for date in sample_dates:
            dd = df[df['date'] == date]
            y = dd['ret'].values
            cap = dd['capital'].values
            if len(y) < 50:
                continue
            w = np.sqrt(cap) / np.sqrt(cap).sum()
            W = np.diag(w)
            country = np.ones((len(dd), 1))
            ind = dd[industry_cols].fillna(0).values
            style = dd[STYLE_COLS].fillna(0).values
            X = np.hstack([country, ind, style])
            try:
                beta = np.linalg.lstsq(W @ X, W @ y, rcond=None)[0]
                pred = X @ beta
                ss_res = np.sum(w * (y - pred)**2)
                ss_tot = np.sum(w * y**2)
                r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
                r2_list.append(r2)
            except Exception:
                continue
        return np.mean(r2_list) if r2_list else np.nan

    # Use a subsample for speed (every 5th date)
    sample_dates = dates[::5]

    # Baseline
    r2_baseline = run_regressions(data, sample_dates)

    # Shift returns forward by 1 day (returns from t+1 paired with exposures from t)
    shifted_fwd = data.copy()
    ret_by_ticker = {}
    for ticker, grp in shifted_fwd.groupby('stocknames'):
        grp = grp.sort_values('date')
        ret_by_ticker[ticker] = grp['ret'].shift(-1)
    shifted_fwd['ret'] = pd.concat(ret_by_ticker.values())
    shifted_fwd = shifted_fwd.dropna(subset=['ret'])
    r2_fwd = run_regressions(shifted_fwd, sample_dates)

    # Shift returns backward by 1 day (returns from t-1 paired with exposures from t)
    shifted_bwd = data.copy()
    ret_by_ticker = {}
    for ticker, grp in shifted_bwd.groupby('stocknames'):
        grp = grp.sort_values('date')
        ret_by_ticker[ticker] = grp['ret'].shift(1)
    shifted_bwd['ret'] = pd.concat(ret_by_ticker.values())
    shifted_bwd = shifted_bwd.dropna(subset=['ret'])
    r2_bwd = run_regressions(shifted_bwd, sample_dates)

    results = pd.DataFrame({
        'scenario': ['Baseline (t)', 'Shifted +1 (t+1 returns)', 'Shifted -1 (t-1 returns)'],
        'mean_r2': [r2_baseline, r2_fwd, r2_bwd],
    })
    csv = save_csv(results, 'val_07_lookahead')

    body = f"""
    <p>If R2 stays the same or increases when returns are shifted, there's a date alignment bug or lookahead bias.
    R2 should <b>drop substantially</b> when returns are misaligned by even 1 day.</p>
    {df_to_html(results)}
    <p><b>Interpretation:</b> Baseline={r2_baseline:.4f}. If shifted R2 is similar, dates may be misaligned.
    If shifted R2 drops to near zero, alignment is correct.</p>
    """
    passed = r2_baseline > r2_fwd and r2_baseline > r2_bwd
    add_section(7, 'Lookahead test (shift returns +/-1 day)',
        f'Baseline R2={r2_baseline:.4f}, +1 shift={r2_fwd:.4f}, -1 shift={r2_bwd:.4f}. '
        f'{"PASS" if passed else "INVESTIGATE"} — R2 {"drops" if passed else "does NOT drop"} with misalignment.',
        body, csv_rel=csv)


# ------------------------------------------------------------------ #
#  Check 8: VIF per factor
# ------------------------------------------------------------------ #

def check_08_vif():
    print('  Running check 8: VIF computation...', flush=True)
    data = load_cross_sectional_data()
    latest_date = data['date'].max()
    dd = data[data['date'] == latest_date]

    style_data = dd[STYLE_COLS].fillna(0).values

    vifs = []
    for i, col in enumerate(STYLE_COLS):
        y = style_data[:, i]
        X = np.delete(style_data, i, axis=1)
        X = np.column_stack([np.ones(len(X)), X])
        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            pred = X @ beta
            ss_res = np.sum((y - pred)**2)
            ss_tot = np.sum((y - y.mean())**2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            vif = 1 / (1 - r2) if r2 < 1 else np.inf
        except Exception:
            vif = np.nan
        vifs.append({'factor': col, 'VIF': round(vif, 2), 'R2_vs_others': round(r2, 4)})

    vif_df = pd.DataFrame(vifs).sort_values('VIF', ascending=False)
    csv = save_csv(vif_df, 'val_08_vif')

    high_vif = vif_df[vif_df['VIF'] > 5]
    body = f"""
    <p>VIF &gt; 5 suggests concerning multicollinearity; VIF &gt; 10 is severe.
    Computed on the latest date ({latest_date}) cross-section.</p>
    {df_to_html(vif_df)}
    """
    add_section(8, 'Variance Inflation Factors (style factors)',
        f'{len(high_vif)} factors with VIF > 5. Max VIF = {vif_df["VIF"].max():.1f}.',
        body, csv_rel=csv)


# ------------------------------------------------------------------ #
#  HTML report
# ------------------------------------------------------------------ #

HTML_HEAD = """<!DOCTYPE html>
<html><head><meta charset='utf-8'><title>Factor Model Validation</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       max-width: 1100px; margin: 20px auto; padding: 0 20px; color: #222; }
h1 { border-bottom: 2px solid #333; padding-bottom: 8px; }
h2 { background: #f3f3f3; padding: 8px 12px; border-left: 4px solid #2952a3; margin-top: 40px; }
h3 { margin-top: 20px; }
.headline { background: #fffbe6; border-left: 4px solid #e0a800; padding: 8px 12px; margin: 8px 0 14px; font-weight: 500; }
.pass { background: #e6ffe6; border-left: 4px solid #2d8a2d; }
.fail { background: #ffe6e6; border-left: 4px solid #cc3333; }
.tbl { border-collapse: collapse; margin: 10px 0; font-size: 0.9em; }
.tbl th, .tbl td { padding: 4px 8px; border: 1px solid #ccc; }
.tbl th { background: #eee; text-align: left; }
.plot { max-width: 100%; margin: 10px 0; border: 1px solid #ddd; }
.meta { color: #666; font-size: 0.85em; }
nav { background: #fafafa; padding: 12px; border: 1px solid #e5e5e5; border-radius: 4px; margin: 20px 0; }
a { color: #2952a3; text-decoration: none; }
code { background: #f5f5f5; padding: 1px 4px; border-radius: 3px; }
</style></head><body>
"""


def build_report():
    from html import escape
    toc = '\n'.join(
        f'<a href="#s{s["n"]}">{s["n"]}. {escape(s["title"])}</a><br>'
        for s in _sections
    )
    parts = []
    for s in _sections:
        cls = 'pass' if 'PASS' in s['headline'] else ('fail' if 'INVESTIGATE' in s['headline'] or 'FAIL' in s['headline'] else '')
        parts.append(f'<h2 id="s{s["n"]}">{s["n"]}. {escape(s["title"])}</h2>')
        parts.append(f'<div class="headline {cls}">{escape(s["headline"])}</div>')
        parts.append(s['body'])
        if s['plot']:
            parts.append(f'<img class="plot" src="{s["plot"]}" alt="plot">')
        if s['csv']:
            parts.append(f'<p class="meta">Data: <a href="{s["csv"]}">{s["csv"]}</a></p>')

    report_path = os.path.join(REPORT_DIR, f'validation_report_{datetime.now():%Y-%m-%d}.html')
    html = (HTML_HEAD
        + f'<h1>Barra Factor Model — Validation Report</h1>'
        + f'<p class="meta">Generated {datetime.now():%Y-%m-%d %H:%M}. '
        + f'8 checks from the model validation checklist.</p>'
        + f'<nav>{toc}</nav>'
        + '\n'.join(parts)
        + '</body></html>')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'\nValidation report: {report_path}')


# ------------------------------------------------------------------ #
#  Main
# ------------------------------------------------------------------ #

def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    os.makedirs(PLOTS_DIR, exist_ok=True)

    checks = [
        check_01_fillna_audit,
        check_02_single_day_deep_dive,
        check_03_capm_benchmark,
        check_04_rolling_r2,
        check_05_known_stock_loadings,
        check_06_residual_autocorrelation,
        check_07_lookahead_test,
        check_08_vif,
    ]
    for fn in checks:
        try:
            fn()
        except Exception as e:
            print(f'  ERROR in {fn.__name__}: {e}')
            import traceback; traceback.print_exc()

    build_report()
    print('Done.')


if __name__ == '__main__':
    main()
