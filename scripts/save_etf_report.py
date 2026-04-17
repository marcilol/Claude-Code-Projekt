# -*- coding: utf-8 -*-
"""Save combined ETF validation report (style + sector ETFs)."""

import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import pandas as pd, numpy as np
from dotenv import load_dotenv; load_dotenv()
from data_sources import EODHDSource
from html import escape

MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'model')
REPORT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'eda')
PLOTS_DIR = os.path.join(REPORT_DIR, 'plots')

STYLE_COLS = ['size', 'beta', 'momentum', 'residvol', 'nlsize', 'btop',
              'liquidity', 'earnyild', 'growth', 'leverage']

ALL_ETFS = {
    'SPY':  ('S&P 500 (Market)', 'market'),
    'IWM':  ('Russell 2000 (Small-Cap)', 'style'),
    'IWB':  ('Russell 1000 (Large-Cap)', 'style'),
    'MTUM': ('Momentum Factor', 'style'),
    'VLUE': ('Value Factor', 'style'),
    'USMV': ('Min Volatility', 'style'),
    'QUAL': ('Quality Factor', 'style'),
    'IWD':  ('Russell 1000 Value', 'style'),
    'IWF':  ('Russell 1000 Growth', 'style'),
    'XLK':  ('Technology Sector', 'sector'),
    'XLF':  ('Financials Sector', 'sector'),
    'XLE':  ('Energy Sector', 'sector'),
    'XLV':  ('Health Care Sector', 'sector'),
    'XLI':  ('Industrials Sector', 'sector'),
    'XLP':  ('Consumer Staples Sector', 'sector'),
    'XLY':  ('Consumer Discretionary Sector', 'sector'),
    'XLU':  ('Utilities Sector', 'sector'),
    'XLRE': ('Real Estate Sector', 'sector'),
    'XLC':  ('Communication Sector', 'sector'),
    'XLB':  ('Materials Sector', 'sector'),
}


def run_regression(ticker, fr, src):
    df = src.fetch_daily_prices([ticker], '2024-04-01', '2026-04-17')
    if df.empty:
        return None
    df = df.sort_values('date')
    prices = df.set_index('date')['close']
    prices.index = pd.to_datetime(prices.index).strftime('%Y-%m-%d')
    ret = np.log(prices / prices.shift(1)).dropna()

    common = sorted(set(ret.index) & set(fr.index))
    if len(common) < 30:
        return None

    y = ret.reindex(common).values
    X = fr.reindex(common).values
    X = np.column_stack([np.ones(len(common)), X])

    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    pred = X @ beta
    ss_res = np.sum((y - pred)**2)
    ss_tot = np.sum((y - y.mean())**2)
    r2 = 1 - ss_res / ss_tot

    n, k = X.shape
    mse = ss_res / (n - k)
    try:
        se = np.sqrt(mse * np.diag(np.linalg.inv(X.T @ X)))
        t_stats = beta / se
    except Exception:
        se = np.full(k, np.nan)
        t_stats = np.full(k, np.nan)

    factor_names = ['alpha'] + list(fr.columns)
    return {
        'n': len(common), 'r2': r2,
        'coefs': dict(zip(factor_names, beta)),
        'tstats': dict(zip(factor_names, t_stats)),
    }


def main():
    os.makedirs(PLOTS_DIR, exist_ok=True)
    fr = pd.read_csv(os.path.join(MODEL_DIR, 'barra_factor_returns.csv'), index_col=0)
    industry_cols = [c for c in fr.columns if c not in ['Country'] + STYLE_COLS]
    src = EODHDSource()

    all_results = []
    detail_rows = []

    print('Running regressions for all ETFs...')
    for ticker, (desc, group) in ALL_ETFS.items():
        res = run_regression(ticker, fr, src)
        if res is None:
            print(f'  {ticker}: skipped')
            continue
        print(f'  {ticker} ({desc}): R2={res["r2"]:.3f}')
        all_results.append({
            'ETF': ticker, 'Description': desc, 'Group': group,
            'N': res['n'], 'R2': round(res['r2'], 4),
            'alpha_ann_pct': round(res['coefs']['alpha'] * 252 * 100, 2),
            'Country': round(res['coefs']['Country'], 3),
        })
        # All factor coefs for detail CSV
        for fname in fr.columns:
            detail_rows.append({
                'ETF': ticker, 'factor': fname,
                'coef': round(res['coefs'].get(fname, 0), 5),
                't_stat': round(res['tstats'].get(fname, 0), 2),
            })

    summary = pd.DataFrame(all_results)
    detail = pd.DataFrame(detail_rows)
    summary.to_csv(os.path.join(REPORT_DIR, 'val_etf_all_summary.csv'), index=False)
    detail.to_csv(os.path.join(REPORT_DIR, 'val_etf_all_detail.csv'), index=False)

    # Build HTML report
    html_parts = ["""<!DOCTYPE html>
<html><head><meta charset='utf-8'><title>ETF Factor Loading Validation</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       max-width: 1200px; margin: 20px auto; padding: 0 20px; color: #222; }
h1 { border-bottom: 2px solid #333; padding-bottom: 8px; }
h2 { background: #f3f3f3; padding: 8px 12px; border-left: 4px solid #2952a3; margin-top: 30px; }
.tbl { border-collapse: collapse; margin: 10px 0; font-size: 0.85em; }
.tbl th, .tbl td { padding: 4px 8px; border: 1px solid #ccc; }
.tbl th { background: #eee; text-align: left; }
.sig { font-weight: bold; color: #1a5c1a; }
.plot { max-width: 100%; margin: 10px 0; border: 1px solid #ddd; }
.meta { color: #666; font-size: 0.85em; }
td.pos { background: #e8f5e9; }
td.neg { background: #ffebee; }
</style></head><body>
<h1>ETF Factor Loading Validation</h1>
<p class="meta">Barra factor model with 25 GICS industry groups + 10 style factors.<br>
Time-series regressions: ETF daily log returns regressed on daily factor returns.</p>
"""]

    # Summary table
    html_parts.append('<h2>Summary</h2>')
    html_parts.append('<table class="tbl"><tr><th>ETF</th><th>Description</th><th>Type</th>'
                      '<th>N</th><th>R2</th><th>Alpha (% ann)</th><th>Country</th></tr>')
    for _, r in summary.iterrows():
        html_parts.append(f'<tr><td><b>{r["ETF"]}</b></td><td>{r["Description"]}</td>'
                          f'<td>{r["Group"]}</td><td>{r["N"]}</td><td>{r["R2"]:.3f}</td>'
                          f'<td>{r["alpha_ann_pct"]:+.1f}</td><td>{r["Country"]:.3f}</td></tr>')
    html_parts.append('</table>')

    # Per-ETF detail sections
    for _, r in summary.iterrows():
        ticker = r['ETF']
        desc = r['Description']
        etf_detail = detail[detail['ETF'] == ticker].copy()
        etf_detail['abs_t'] = etf_detail['t_stat'].abs()
        etf_detail = etf_detail.sort_values('abs_t', ascending=False)

        # Split into industry and style
        ind_detail = etf_detail[etf_detail['factor'].isin(industry_cols)].head(7)
        style_detail = etf_detail[etf_detail['factor'].isin(STYLE_COLS)]

        html_parts.append(f'<h2>{ticker} — {desc} (R2={r["R2"]:.3f})</h2>')

        # Industry loadings
        html_parts.append('<p><b>Top industry loadings:</b></p>')
        html_parts.append('<table class="tbl"><tr><th>Industry</th><th>Coef</th><th>t-stat</th></tr>')
        for _, row in ind_detail.iterrows():
            sig = ' class="sig"' if abs(row['t_stat']) > 2 else ''
            cls = 'pos' if row['coef'] > 0 else 'neg'
            html_parts.append(f'<tr><td{sig}>{escape(row["factor"])}</td>'
                              f'<td class="{cls}">{row["coef"]:+.4f}</td>'
                              f'<td{sig}>{row["t_stat"]:+.1f}</td></tr>')
        html_parts.append('</table>')

        # Style loadings
        html_parts.append('<p><b>Style factor loadings:</b></p>')
        html_parts.append('<table class="tbl"><tr><th>Factor</th><th>Coef</th><th>t-stat</th></tr>')
        for _, row in style_detail.iterrows():
            sig = ' class="sig"' if abs(row['t_stat']) > 2 else ''
            cls = 'pos' if row['coef'] > 0 else 'neg'
            html_parts.append(f'<tr><td{sig}>{escape(row["factor"])}</td>'
                              f'<td class="{cls}">{row["coef"]:+.4f}</td>'
                              f'<td{sig}>{row["t_stat"]:+.1f}</td></tr>')
        html_parts.append('</table>')

    # Embed heatmap if exists
    heatmap = os.path.join(PLOTS_DIR, 'val_etf_loadings_heatmap.png')
    if os.path.exists(heatmap):
        rel = os.path.relpath(heatmap, REPORT_DIR).replace('\\', '/')
        html_parts.append(f'<h2>Style Factor Heatmap</h2><img class="plot" src="{rel}">')

    html_parts.append('</body></html>')

    report_path = os.path.join(REPORT_DIR, 'etf_validation_report.html')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_parts))

    print(f'\nReport: {report_path}')
    print(f'Summary CSV: {REPORT_DIR}/val_etf_all_summary.csv')
    print(f'Detail CSV: {REPORT_DIR}/val_etf_all_detail.csv')


if __name__ == '__main__':
    main()
