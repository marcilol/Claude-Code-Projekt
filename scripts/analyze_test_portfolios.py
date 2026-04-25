# -*- coding: utf-8 -*-
"""
Comprehensive portfolio analysis for test portfolios.
Computes and visualizes: factor exposures, risk decomposition, MCFR, idio vol.

Usage: py scripts/analyze_test_portfolios.py
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

sys.path.insert(0, os.path.dirname(__file__))

MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'model')
EDA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'eda')
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'db', 'market_data.db')
PORTFOLIOS_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'input', 'portfolios', 'test')

STYLE_COLS = ['size', 'beta', 'momentum', 'residvol', 'nlsize', 'btop',
              'liquidity', 'earnyild', 'growth', 'leverage']


def save_plot(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)


def load_portfolio(filepath):
    with open(filepath, 'r') as f:
        lines = [l for l in f if not l.startswith(('<<<<<<<', '=======', '>>>>>>>'))]
    first = lines[0] if lines else ''
    sep = ';' if ';' in first else ','
    from io import StringIO
    df = pd.read_csv(StringIO(''.join(lines)), sep=sep)
    df.columns = df.columns.str.lower().str.strip()
    df = df[df['ticker'].apply(lambda x: isinstance(x, str) and x.lower() != 'ticker')]
    df['shares'] = pd.to_numeric(df['shares'], errors='coerce')
    df = df.dropna(subset=['shares'])
    return df


def get_weights(portfolio_df):
    conn = sqlite3.connect(DB_PATH)
    tickers = portfolio_df['ticker'].tolist()
    shares = portfolio_df['shares'].tolist()

    prices = {}
    for t in tickers:
        row = conn.execute('SELECT close FROM daily_prices WHERE ticker=? ORDER BY date DESC LIMIT 1', (t,)).fetchone()
        prices[t] = row[0] if row else np.nan
    conn.close()

    mv = []
    valid_t = []
    valid_s = []
    for t, s in zip(tickers, shares):
        p = prices.get(t, np.nan)
        if pd.notna(p) and p > 0:
            mv.append(p * s)
            valid_t.append(t)
            valid_s.append(s)

    total = sum(mv)
    weights = [m / total for m in mv]
    return pd.DataFrame({
        'ticker': valid_t,
        'shares': valid_s,
        'price': [prices[t] for t in valid_t],
        'market_value': mv,
        'weight': weights,
    })


def analyze_portfolio(name, weights_df, factor_exp_df, factor_ret_df, factor_cov_df):
    """Full portfolio analysis. Returns dict of results."""
    tickers = weights_df['ticker'].tolist()
    weights = weights_df['weight'].values

    latest_date = factor_exp_df['date'].max()
    latest = factor_exp_df[factor_exp_df['date'] == latest_date]

    # Match tickers
    matched = latest[latest['ticker'].isin(tickers)]
    matched_tickers = matched['ticker'].tolist()
    matched_weights = []
    for t in matched_tickers:
        idx = tickers.index(t)
        matched_weights.append(weights[idx])
    # Renormalize
    w_sum = sum(matched_weights)
    matched_weights = [w / w_sum for w in matched_weights]
    w = np.array(matched_weights)

    results = {
        'name': name,
        'n_positions': len(weights_df),
        'n_matched': len(matched),
        'total_value': weights_df['market_value'].sum(),
    }

    # --- Style factor exposures ---
    style_exp = {}
    for f in STYLE_COLS:
        if f in matched.columns:
            vals = matched.set_index('ticker').loc[matched_tickers, f].values
            style_exp[f] = float(np.sum(w * vals))
    results['style_exposures'] = style_exp

    # --- Industry exposures ---
    factor_names = factor_cov_df.columns.tolist()
    industry_factors = [f for f in factor_names if f not in ['Country'] + STYLE_COLS]

    industry_exp = {}
    if 'sector' in matched.columns:
        for ind in industry_factors:
            mask = matched.set_index('ticker').loc[matched_tickers, 'sector'] == ind
            industry_exp[ind] = float(w[mask.values].sum()) if mask.any() else 0.0
    results['industry_exposures'] = industry_exp

    # --- Factor variance b'Ωb ---
    b = np.zeros(len(factor_names))
    for i, f in enumerate(factor_names):
        if f == 'Country':
            b[i] = 1.0  # all stocks have exposure 1 to Country
        elif f in style_exp:
            b[i] = style_exp[f]
        elif f in industry_exp:
            b[i] = industry_exp[f]

    omega = factor_cov_df.values
    factor_var_daily = float(b @ omega @ b)
    factor_var_ann = factor_var_daily * 252
    factor_vol_ann = np.sqrt(factor_var_ann)
    results['factor_var_ann'] = factor_var_ann
    results['factor_vol_ann'] = factor_vol_ann

    # --- Per-factor risk contribution ---
    omega_b = omega @ b
    per_factor_var = b * omega_b * 252  # annualized
    results['per_factor_var'] = dict(zip(factor_names, per_factor_var))

    # --- MCFR ---
    factor_vol_daily = np.sqrt(factor_var_daily) if factor_var_daily > 0 else 1e-10
    # MCFR per stock: (B @ Omega @ b) / sqrt(b'Omega b)
    # B is (n_stocks x n_factors) loading matrix
    n_stocks = len(matched_tickers)
    B = np.zeros((n_stocks, len(factor_names)))
    for j, f in enumerate(factor_names):
        if f == 'Country':
            B[:, j] = 1.0
        elif f in STYLE_COLS and f in matched.columns:
            B[:, j] = matched.set_index('ticker').loc[matched_tickers, f].values
        elif f in industry_factors and 'sector' in matched.columns:
            B[:, j] = (matched.set_index('ticker').loc[matched_tickers, 'sector'] == f).astype(float).values

    mcfr_raw = (B @ omega @ b) / factor_vol_daily  # per-stock MCFR (daily units)
    mcfr_contrib = w * mcfr_raw  # weighted MCFR
    results['mcfr'] = dict(zip(matched_tickers, mcfr_contrib))

    # --- Idiosyncratic volatility ---
    idio_vols = {}
    dates = sorted(factor_exp_df['date'].unique())
    factor_dates = set(factor_ret_df.index)

    for i, t in enumerate(matched_tickers):
        stock_data = factor_exp_df[factor_exp_df['ticker'] == t].sort_values('date')
        if len(stock_data) < 60:
            continue
        residuals = []
        for _, row in stock_data.iterrows():
            d = row['date']
            if d not in factor_dates:
                continue
            fr = factor_ret_df.loc[d]
            predicted = fr.get('Country', 0)
            sector = row.get('sector', '')
            if sector in fr.index:
                predicted += fr[sector]
            for sf in STYLE_COLS:
                if sf in row.index and sf in fr.index:
                    predicted += row[sf] * fr[sf]
            residuals.append(row['return'] - predicted)
        if len(residuals) > 30:
            idio_vols[t] = float(np.std(residuals) * np.sqrt(252))

    results['idio_vols'] = idio_vols

    # Total idio variance = sum(w_i^2 * sigma_i^2)
    idio_var = sum(w[i]**2 * idio_vols.get(t, 0.3)**2
                   for i, t in enumerate(matched_tickers))
    idio_vol = np.sqrt(idio_var)
    results['idio_var'] = idio_var
    results['idio_vol'] = idio_vol

    # Total risk
    total_var = factor_var_ann + idio_var
    total_vol = np.sqrt(total_var)
    results['total_var'] = total_var
    results['total_vol'] = total_vol
    results['pct_factor'] = 100 * factor_var_ann / total_var if total_var > 0 else 0
    results['pct_idio'] = 100 * idio_var / total_var if total_var > 0 else 0

    return results


def build_report(all_results, plots_dir, out_path):
    """Build HTML report for all portfolios."""

    factor_names_all = list(all_results[0]['per_factor_var'].keys()) if all_results else []

    # --- PLOT 1: Style factor exposure comparison ---
    fig, ax = plt.subplots(figsize=(12, 5))
    n_port = len(all_results)
    x = np.arange(len(STYLE_COLS))
    width = 0.15
    for i, r in enumerate(all_results):
        vals = [r['style_exposures'].get(f, 0) for f in STYLE_COLS]
        ax.bar(x + i * width, vals, width, label=r['name'])
    ax.set_xticks(x + width * (n_port - 1) / 2)
    ax.set_xticklabels(STYLE_COLS, rotation=35, ha='right')
    ax.axhline(0, color='k', lw=0.5)
    ax.set_ylabel('Z-score exposure')
    ax.set_title('Style Factor Exposures')
    ax.legend(fontsize=8)
    save_plot(fig, os.path.join(plots_dir, 'style_exposures.png'))

    # --- PLOT 2: Risk decomposition bars ---
    fig, ax = plt.subplots(figsize=(10, 5))
    names = [r['name'] for r in all_results]
    factor_pcts = [r['pct_factor'] for r in all_results]
    idio_pcts = [r['pct_idio'] for r in all_results]
    x = range(len(names))
    ax.bar(x, factor_pcts, label='Factor (systematic)', color='#2952a3')
    ax.bar(x, idio_pcts, bottom=factor_pcts, label='Idiosyncratic (specific)', color='#a8d8a8')
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=20, ha='right')
    ax.set_ylabel('% of total variance')
    ax.set_title('Risk Decomposition')
    ax.legend()
    for i in x:
        ax.text(i, 50, f'{all_results[i]["total_vol"]*100:.0f}% vol', ha='center', fontsize=9)
    save_plot(fig, os.path.join(plots_dir, 'risk_decomposition.png'))

    # --- PLOT 3: Per-factor risk contribution (top 10) ---
    fig, axes = plt.subplots(1, n_port, figsize=(4 * n_port, 5), sharey=True)
    if n_port == 1:
        axes = [axes]
    for i, r in enumerate(all_results):
        pfv = r['per_factor_var']
        sorted_f = sorted(pfv.items(), key=lambda x: abs(x[1]), reverse=True)[:10]
        fnames = [f[0][:20] for f in sorted_f]
        vals = [f[1] / r['total_var'] * 100 if r['total_var'] > 0 else 0 for f in sorted_f]
        colors = ['#2d8a2d' if v > 0 else '#cc3333' for v in vals]
        axes[i].barh(range(len(fnames)), vals, color=colors)
        axes[i].set_yticks(range(len(fnames)))
        axes[i].set_yticklabels(fnames, fontsize=7)
        axes[i].invert_yaxis()
        axes[i].set_title(r['name'], fontsize=9)
        axes[i].axvline(0, color='k', lw=0.5)
    axes[0].set_xlabel('% of total variance')
    fig.suptitle('Top 10 Factor Risk Contributors', fontsize=11)
    save_plot(fig, os.path.join(plots_dir, 'factor_risk_contrib.png'))

    # --- PLOT 4: MCFR for each portfolio ---
    fig, axes = plt.subplots(1, n_port, figsize=(4 * n_port, 5), sharey=False)
    if n_port == 1:
        axes = [axes]
    for i, r in enumerate(all_results):
        mcfr = r['mcfr']
        sorted_m = sorted(mcfr.items(), key=lambda x: abs(x[1]), reverse=True)[:12]
        tks = [m[0] for m in sorted_m]
        vals = [m[1] * np.sqrt(252) * 100 for m in sorted_m]  # annualize
        colors = ['#cc3333' if v > 0 else '#2d8a2d' for v in vals]
        axes[i].barh(range(len(tks)), vals, color=colors)
        axes[i].set_yticks(range(len(tks)))
        axes[i].set_yticklabels(tks, fontsize=8)
        axes[i].invert_yaxis()
        axes[i].set_title(r['name'], fontsize=9)
        axes[i].axvline(0, color='k', lw=0.5)
    axes[0].set_xlabel('MCFR (annualized, % contrib)')
    fig.suptitle('Marginal Contribution to Factor Risk (top 12 stocks)', fontsize=11)
    save_plot(fig, os.path.join(plots_dir, 'mcfr.png'))

    # --- PLOT 5: Idiosyncratic vol distribution per portfolio ---
    fig, axes = plt.subplots(1, n_port, figsize=(3.5 * n_port, 4), sharey=True)
    if n_port == 1:
        axes = [axes]
    for i, r in enumerate(all_results):
        vols = list(r['idio_vols'].values())
        if vols:
            axes[i].hist([v * 100 for v in vols], bins=15, color='steelblue', edgecolor='white')
            axes[i].axvline(np.median(vols) * 100, color='red', ls='--',
                           label=f'Median {np.median(vols)*100:.0f}%')
            axes[i].legend(fontsize=7)
        axes[i].set_title(r['name'], fontsize=9)
        axes[i].set_xlabel('Annualized idio vol (%)')
    fig.suptitle('Per-Stock Idiosyncratic Volatility', fontsize=11)
    save_plot(fig, os.path.join(plots_dir, 'idio_vol_dist.png'))

    # --- PLOT 6: Industry concentration ---
    fig, axes = plt.subplots(1, n_port, figsize=(4 * n_port, 5), sharey=True)
    if n_port == 1:
        axes = [axes]
    for i, r in enumerate(all_results):
        ie = {k: v for k, v in r['industry_exposures'].items() if v > 0.01}
        ie = dict(sorted(ie.items(), key=lambda x: -x[1]))
        if ie:
            axes[i].barh(range(len(ie)), [v * 100 for v in ie.values()], color='teal')
            axes[i].set_yticks(range(len(ie)))
            axes[i].set_yticklabels([k[:25] for k in ie.keys()], fontsize=7)
            axes[i].invert_yaxis()
        axes[i].set_title(r['name'], fontsize=9)
    axes[0].set_xlabel('% of portfolio')
    fig.suptitle('Industry Allocation', fontsize=11)
    save_plot(fig, os.path.join(plots_dir, 'industry_allocation.png'))

    # --- BUILD HTML ---
    html = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'><title>Portfolio Analysis Report</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 1200px; margin: 20px auto; padding: 0 20px; }}
h1 {{ border-bottom: 2px solid #333; padding-bottom: 8px; }}
h2 {{ background: #f3f3f3; padding: 8px 12px; border-left: 4px solid #2952a3; margin-top: 30px; }}
.tbl {{ border-collapse: collapse; margin: 10px 0; font-size: 0.85em; }}
.tbl th, .tbl td {{ padding: 4px 8px; border: 1px solid #ccc; }}
.tbl th {{ background: #eee; text-align: left; }}
.plot {{ max-width: 100%; margin: 10px 0; border: 1px solid #ddd; }}
.meta {{ color: #666; font-size: 0.85em; }}
</style></head><body>
<h1>Portfolio Analysis Report — 5 Test Portfolios</h1>
<p class="meta">Generated {datetime.now():%Y-%m-%d %H:%M}</p>

<h2>Summary</h2>
<table class="tbl">
<tr><th>Portfolio</th><th>Positions</th><th>Matched</th><th>Value</th>
<th>Factor Vol</th><th>Idio Vol</th><th>Total Vol</th><th>% Factor</th><th>% Idio</th></tr>
"""
    for r in all_results:
        html += f"""<tr>
<td><b>{r['name']}</b></td><td>{r['n_positions']}</td><td>{r['n_matched']}</td>
<td>${r['total_value']:,.0f}</td>
<td>{r['factor_vol_ann']*100:.1f}%</td><td>{r['idio_vol']*100:.1f}%</td>
<td>{r['total_vol']*100:.1f}%</td>
<td>{r['pct_factor']:.0f}%</td><td>{r['pct_idio']:.0f}%</td></tr>
"""
    html += "</table>"

    html += '<h2>Style Factor Exposures</h2><img class="plot" src="plots/style_exposures.png">'
    html += '<h2>Risk Decomposition</h2><img class="plot" src="plots/risk_decomposition.png">'
    html += '<h2>Factor Risk Contributors</h2><img class="plot" src="plots/factor_risk_contrib.png">'
    html += '<h2>Marginal Contribution to Factor Risk</h2><img class="plot" src="plots/mcfr.png">'
    html += '<h2>Idiosyncratic Volatility Distribution</h2><img class="plot" src="plots/idio_vol_dist.png">'
    html += '<h2>Industry Allocation</h2><img class="plot" src="plots/industry_allocation.png">'

    # Per-portfolio detail tables
    for r in all_results:
        html += f'<h2>{r["name"]} — Detail</h2>'

        # Style exposures table
        html += '<p><b>Style Exposures:</b></p><table class="tbl"><tr><th>Factor</th><th>Exposure</th><th>Interpretation</th></tr>'
        for f in STYLE_COLS:
            v = r['style_exposures'].get(f, 0)
            interp = ''
            if f == 'size': interp = 'large cap' if v > 0.5 else ('small cap' if v < -0.5 else 'mid cap')
            elif f == 'beta': interp = 'high beta' if v > 0.5 else ('low beta' if v < -0.5 else 'market-like')
            elif f == 'momentum': interp = 'winners' if v > 0.5 else ('losers' if v < -0.5 else 'neutral')
            elif f == 'btop': interp = 'value' if v > 0.5 else ('growth' if v < -0.5 else 'blend')
            html += f'<tr><td>{f}</td><td>{v:+.2f}</td><td>{interp}</td></tr>'
        html += '</table>'

        # Top MCFR stocks
        mcfr = r['mcfr']
        sorted_m = sorted(mcfr.items(), key=lambda x: x[1], reverse=True)
        html += '<p><b>MCFR (top risk adders → top risk hedgers):</b></p>'
        html += '<table class="tbl"><tr><th>Ticker</th><th>MCFR (ann %)</th><th>Role</th></tr>'
        for t, v in sorted_m[:5]:
            role = 'adds factor risk' if v > 0 else 'hedges factor risk'
            html += f'<tr><td>{t}</td><td>{v*np.sqrt(252)*100:+.2f}%</td><td>{role}</td></tr>'
        html += '<tr><td colspan="3">...</td></tr>'
        for t, v in sorted_m[-3:]:
            role = 'adds factor risk' if v > 0 else 'hedges factor risk'
            html += f'<tr><td>{t}</td><td>{v*np.sqrt(252)*100:+.2f}%</td><td>{role}</td></tr>'
        html += '</table>'

    html += '</body></html>'

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return out_path


def main():
    print('Loading model data...')
    factor_exp_df = pd.read_csv(os.path.join(MODEL_DIR, 'russell3000_factor_exposures_historical.csv'))
    factor_ret_df = pd.read_csv(os.path.join(MODEL_DIR, 'barra_factor_returns.csv'), index_col=0)
    factor_cov_df = pd.read_csv(os.path.join(MODEL_DIR, 'barra_factor_covariance.csv'), index_col=0)

    plots_dir = os.path.join(EDA_DIR, 'portfolio_plots')
    os.makedirs(plots_dir, exist_ok=True)

    portfolios = sorted([f for f in os.listdir(PORTFOLIOS_DIR) if f.endswith('.csv')])
    print(f'Found {len(portfolios)} test portfolios')

    all_results = []
    for pfile in portfolios:
        name = pfile.replace('.csv', '').replace('_', ' ').title()
        path = os.path.join(PORTFOLIOS_DIR, pfile)
        print(f'\n  Analyzing: {name}...', flush=True)

        pdf = load_portfolio(path)
        wdf = get_weights(pdf)
        if len(wdf) < 3:
            print(f'    SKIP: only {len(wdf)} priced positions')
            continue

        r = analyze_portfolio(name, wdf, factor_exp_df, factor_ret_df, factor_cov_df)
        all_results.append(r)
        print(f'    {r["n_matched"]} matched, vol={r["total_vol"]*100:.1f}%, '
              f'factor={r["pct_factor"]:.0f}%/idio={r["pct_idio"]:.0f}%')

    ts = datetime.now().strftime('%Y_%m_%d_%H_%M')
    out_path = os.path.join(EDA_DIR, f'portfolio_analysis_{ts}.html')
    build_report(all_results, plots_dir, out_path)
    print(f'\nReport: {out_path}')


if __name__ == '__main__':
    main()
