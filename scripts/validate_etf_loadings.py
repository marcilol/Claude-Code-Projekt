# -*- coding: utf-8 -*-
"""
Regress ETF returns on Barra factor returns to check factor loadings.

Expected results:
  SPY  → Country ~1.0, style loadings ~0
  IWM  → Country ~1.0, size strongly negative (small-cap)
  IWF  → Country ~1.0, btop negative (growth)
  IWD  → Country ~1.0, btop positive (value)
  MTUM → momentum positive
  VLUE → btop positive, earnyild positive
  USMV → beta negative, residvol negative
  XLK  → Tech Hardware / Software / Semis industry loadings
  XLF  → Banks / Insurance / Financial Services loadings
  XLE  → Energy loading

Run: py scripts/validate_etf_loadings.py
"""

import os, sys
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(__file__))

MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'model')
REPORT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'eda')
PLOTS_DIR = os.path.join(REPORT_DIR, 'plots')

STYLE_COLS = ['size', 'beta', 'momentum', 'residvol', 'nlsize', 'btop',
              'liquidity', 'earnyild', 'growth', 'leverage']

ETFS = {
    'SPY':  'S&P 500 (Market)',
    'IWM':  'Russell 2000 (Small-Cap)',
    'IWB':  'Russell 1000 (Large-Cap)',
    'MTUM': 'Momentum Factor',
    'VLUE': 'Value Factor',
    'USMV': 'Min Volatility',
    'QUAL': 'Quality Factor',
    'IWD':  'Russell 1000 Value',
    'IWF':  'Russell 1000 Growth',
    'XLK':  'Technology Sector',
    'XLF':  'Financials Sector',
    'XLE':  'Energy Sector',
}


def main():
    os.makedirs(PLOTS_DIR, exist_ok=True)
    from dotenv import load_dotenv; load_dotenv()
    from data_sources import EODHDSource

    # Load factor returns
    fr = pd.read_csv(os.path.join(MODEL_DIR, 'barra_factor_returns.csv'),
                     index_col=0)
    print(f'Factor returns: {len(fr)} dates, {len(fr.columns)} factors')
    print(f'  Range: {fr.index[0]} to {fr.index[-1]}')

    # Fetch ETF prices
    src = EODHDSource()
    etf_returns = {}

    print('\nFetching ETF returns...')
    for ticker in ETFS:
        df = src.fetch_daily_prices([ticker], '2024-04-01', '2026-04-17')
        if df.empty:
            print(f'  {ticker}: no data')
            continue
        df = df.sort_values('date')
        prices = df.set_index('date')['close']
        prices.index = pd.to_datetime(prices.index)
        log_ret = np.log(prices / prices.shift(1)).dropna()
        log_ret.name = ticker
        etf_returns[ticker] = log_ret
        print(f'  {ticker}: {len(log_ret)} returns')

    # Align dates with factor returns
    factor_dates = set(fr.index)

    all_results = []
    detailed = {}

    print('\n' + '=' * 70)
    print('TIME-SERIES REGRESSIONS: ETF returns ~ Factor returns')
    print('=' * 70)

    for ticker, desc in ETFS.items():
        if ticker not in etf_returns:
            continue

        ret = etf_returns[ticker]
        ret.index = ret.index.strftime('%Y-%m-%d')

        # Align
        common = sorted(set(ret.index) & set(fr.index))
        if len(common) < 30:
            print(f'\n{ticker}: only {len(common)} common dates, skipping')
            continue

        y = ret.reindex(common).values
        X = fr.reindex(common).values
        X = np.column_stack([np.ones(len(common)), X])  # add intercept (alpha)

        # OLS regression
        try:
            beta, residuals, rank, sv = np.linalg.lstsq(X, y, rcond=None)
        except Exception as e:
            print(f'\n{ticker}: regression failed: {e}')
            continue

        pred = X @ beta
        ss_res = np.sum((y - pred)**2)
        ss_tot = np.sum((y - y.mean())**2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        # Standard errors
        n, k = X.shape
        mse = ss_res / (n - k)
        try:
            var_beta = mse * np.diag(np.linalg.inv(X.T @ X))
            se = np.sqrt(var_beta)
            t_stats = beta / se
        except Exception:
            se = np.full(k, np.nan)
            t_stats = np.full(k, np.nan)

        # Build results
        factor_names = ['alpha'] + list(fr.columns)
        coefs = pd.DataFrame({
            'factor': factor_names,
            'coef': beta,
            'se': se,
            't_stat': t_stats,
        })
        detailed[ticker] = coefs

        # Extract key loadings for summary
        coef_dict = dict(zip(factor_names, beta))
        t_dict = dict(zip(factor_names, t_stats))

        row = {
            'ETF': ticker,
            'Description': desc,
            'N': len(common),
            'R2': round(r2, 4),
            'alpha_ann_%': round(coef_dict.get('alpha', 0) * 252 * 100, 2),
            'Country': round(coef_dict.get('Country', 0), 3),
        }
        for sc in STYLE_COLS:
            row[sc] = round(coef_dict.get(sc, 0), 3)
            row[f'{sc}_t'] = round(t_dict.get(sc, 0), 2)
        all_results.append(row)

        # Print summary
        print(f'\n{ticker} ({desc}) — R2={r2:.3f}, N={len(common)}, '
              f'alpha={coef_dict["alpha"]*252*100:+.1f}% ann')
        print(f'  Country: {coef_dict["Country"]:+.3f}')
        # Top 3 style loadings by |t-stat|
        style_t = [(sc, coef_dict.get(sc, 0), t_dict.get(sc, 0)) for sc in STYLE_COLS]
        style_t.sort(key=lambda x: abs(x[2]), reverse=True)
        for name, coef, t in style_t[:5]:
            sig = '*' if abs(t) > 2 else ''
            print(f'  {name:12s}: {coef:+.4f} (t={t:+.2f}){sig}')

    # Save summary
    summary = pd.DataFrame(all_results)
    summary.to_csv(os.path.join(REPORT_DIR, 'val_etf_loadings_summary.csv'), index=False)

    # Save detailed per-ETF
    for ticker, coefs in detailed.items():
        coefs.to_csv(os.path.join(REPORT_DIR, f'val_etf_{ticker}_coefs.csv'), index=False)

    # Heatmap of style loadings
    if all_results:
        fig, ax = plt.subplots(figsize=(12, 6))
        heat_data = summary.set_index('ETF')[STYLE_COLS]
        im = ax.imshow(heat_data.values, aspect='auto', cmap='RdBu_r', vmin=-0.5, vmax=0.5)
        ax.set_xticks(range(len(STYLE_COLS)))
        ax.set_xticklabels(STYLE_COLS, rotation=45, ha='right')
        ax.set_yticks(range(len(heat_data)))
        ax.set_yticklabels([f'{t} ({ETFS[t]})' for t in heat_data.index], fontsize=9)
        for i in range(len(heat_data)):
            for j in range(len(STYLE_COLS)):
                v = heat_data.values[i, j]
                ax.text(j, i, f'{v:+.2f}', ha='center', va='center', fontsize=7,
                        color='white' if abs(v) > 0.3 else 'black')
        ax.set_title('ETF Style Factor Loadings (Barra regression)')
        plt.colorbar(im, ax=ax, shrink=0.8)
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS_DIR, 'val_etf_loadings_heatmap.png'), dpi=150)
        plt.close(fig)
        print(f'\nHeatmap saved: {PLOTS_DIR}/val_etf_loadings_heatmap.png')

    # R2 bar chart
    if all_results:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.bar(range(len(summary)), summary['R2'], color='steelblue')
        ax.set_xticks(range(len(summary)))
        ax.set_xticklabels(summary['ETF'], rotation=45, ha='right')
        ax.set_ylabel('R2')
        ax.set_title('ETF Time-Series R2 (explained by Barra factor returns)')
        ax.axhline(0.9, color='g', ls='--', alpha=0.5, label='90% benchmark')
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS_DIR, 'val_etf_r2_bar.png'), dpi=150)
        plt.close(fig)

    print('\n' + '=' * 70)
    print('ETF VALIDATION COMPLETE')
    print('=' * 70)
    print(f'Summary: {REPORT_DIR}/val_etf_loadings_summary.csv')
    print(f'Heatmap: {PLOTS_DIR}/val_etf_loadings_heatmap.png')


if __name__ == '__main__':
    main()
