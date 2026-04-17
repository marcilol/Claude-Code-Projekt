# -*- coding: utf-8 -*-
"""
Alignment validation v2 — fixes from checklist feedback.

Three tests:
  1. Fixed permutation test (50 iterations, shuffle return vectors across dates)
  2. Industry-only regression baseline (no style factors)
  3. R² distribution histogram

Run: py scripts/validate_alignment_v2.py
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


def load_data():
    path = os.path.join(MODEL_DIR, 'russell3000_cross_sectional_data.csv')
    data = pd.read_csv(path)
    industry_cols = [c for c in data.columns
                     if c not in ['date', 'stocknames', 'capital', 'ret'] + STYLE_COLS]
    return data, industry_cols


def wls_r2_single(y, X, w):
    """WLS R² for a single cross-section."""
    W = np.diag(w)
    try:
        beta = np.linalg.lstsq(W @ X, W @ y, rcond=None)[0]
        pred = X @ beta
        ss_res = np.sum(w * (y - pred)**2)
        ss_tot = np.sum(w * y**2)
        return 1 - ss_res / ss_tot if ss_tot > 0 else 0
    except Exception:
        return np.nan


# ------------------------------------------------------------------ #
#  Test 1: Fixed permutation test (50 iterations)
# ------------------------------------------------------------------ #

def test_01_permutation(data, industry_cols):
    print('Test 1: Permutation test (50 iterations)...', flush=True)
    dates = sorted(data['date'].unique())

    # Pre-compute per-date arrays
    date_arrays = {}
    for d in dates:
        dd = data[data['date'] == d]
        y = dd['ret'].values
        cap = dd['capital'].values
        if len(y) < 50 or np.all(cap == 0):
            continue
        w = np.sqrt(cap) / np.sqrt(cap).sum()
        country = np.ones((len(dd), 1))
        ind = dd[industry_cols].fillna(0).values
        style = dd[STYLE_COLS].fillna(0).values
        X_full = np.hstack([country, ind, style])
        date_arrays[d] = {'y': y, 'X': X_full, 'w': w}

    valid_dates = list(date_arrays.keys())
    n_dates = len(valid_dates)
    print(f'  {n_dates} valid dates')

    # Baseline R² per date
    baseline_r2 = []
    for d in valid_dates:
        a = date_arrays[d]
        baseline_r2.append(wls_r2_single(a['y'], a['X'], a['w']))
    baseline_mean = np.nanmean(baseline_r2)
    print(f'  Baseline mean R2: {baseline_mean:.4f}')

    # Permutation: keep exposures fixed per date, shuffle which return vector
    # gets paired with each date. Return vectors stay intact (preserving
    # cross-sectional structure within a day), only their date assignment changes.
    n_perms = 50
    perm_means = []
    for p in range(n_perms):
        np.random.seed(p + 42)
        # Random permutation of date indices
        perm_idx = np.random.permutation(n_dates)
        r2s = []
        for i, d in enumerate(valid_dates):
            # Exposures from date d, returns from date valid_dates[perm_idx[i]]
            source_d = valid_dates[perm_idx[i]]
            X = date_arrays[d]['X']
            w = date_arrays[d]['w']
            y_shuffled = date_arrays[source_d]['y']
            # Sizes must match — both dates have different N stocks
            # So we can only pair dates with same N, or resample.
            # Simpler: use the return vector's own weights but truncate/pad to match.
            n_exp = len(w)
            n_ret = len(y_shuffled)
            if n_exp == n_ret:
                r2s.append(wls_r2_single(y_shuffled, X, w))
            else:
                # Resample return vector to match exposure count
                if n_ret >= n_exp:
                    idx = np.random.choice(n_ret, n_exp, replace=False)
                    r2s.append(wls_r2_single(y_shuffled[idx], X, w))
                else:
                    idx = np.random.choice(n_ret, n_exp, replace=True)
                    r2s.append(wls_r2_single(y_shuffled[idx], X, w))

        perm_mean = np.nanmean(r2s)
        perm_means.append(perm_mean)
        if (p + 1) % 10 == 0:
            print(f'  Permutation {p+1}/50: mean R2={perm_mean:.4f}', flush=True)

    perm_avg = np.mean(perm_means)
    perm_std = np.std(perm_means)
    perm_ci = (perm_avg - 1.96 * perm_std, perm_avg + 1.96 * perm_std)

    print(f'\n  RESULTS:')
    print(f'  Baseline mean R2:    {baseline_mean:.4f}')
    print(f'  Permuted mean R2:    {perm_avg:.4f} +/- {perm_std:.4f}')
    print(f'  95% CI:              ({perm_ci[0]:.4f}, {perm_ci[1]:.4f})')
    print(f'  Day-specific lift:   {baseline_mean - perm_avg:.4f}')

    # Save
    results = pd.DataFrame({
        'permutation': ['baseline'] + [f'perm_{i}' for i in range(n_perms)],
        'mean_r2': [baseline_mean] + perm_means,
    })
    results.to_csv(os.path.join(REPORT_DIR, 'val_align2_01_permutation.csv'), index=False)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(perm_means, bins=20, color='steelblue', alpha=0.7, label='Permuted R2')
    ax.axvline(baseline_mean, color='red', lw=2, label=f'Baseline ({baseline_mean:.4f})')
    ax.axvline(perm_avg, color='orange', lw=2, ls='--', label=f'Perm mean ({perm_avg:.4f})')
    ax.set_xlabel('Mean R2')
    ax.set_ylabel('Count')
    ax.set_title('Permutation test: baseline vs shuffled date-return pairings (N=50)')
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS_DIR, 'val_align2_01_permutation.png'), dpi=150)
    plt.close(fig)

    return baseline_mean, perm_avg, perm_std


# ------------------------------------------------------------------ #
#  Test 2: Industry-only regression baseline
# ------------------------------------------------------------------ #

def test_02_industry_only(data, industry_cols):
    print('\nTest 2: Industry-only regression (no style factors)...', flush=True)
    dates = sorted(data['date'].unique())

    r2_full = []
    r2_ind_only = []
    r2_country_only = []

    for d in dates:
        dd = data[data['date'] == d]
        y = dd['ret'].values
        cap = dd['capital'].values
        if len(y) < 50 or np.all(cap == 0):
            r2_full.append(np.nan)
            r2_ind_only.append(np.nan)
            r2_country_only.append(np.nan)
            continue
        w = np.sqrt(cap) / np.sqrt(cap).sum()
        country = np.ones((len(dd), 1))
        ind = dd[industry_cols].fillna(0).values
        style = dd[STYLE_COLS].fillna(0).values

        # Full model
        X_full = np.hstack([country, ind, style])
        r2_full.append(wls_r2_single(y, X_full, w))

        # Industry + country only
        X_ind = np.hstack([country, ind])
        r2_ind_only.append(wls_r2_single(y, X_ind, w))

        # Country only (CAPM)
        r2_country_only.append(wls_r2_single(y, country, w))

    results = pd.DataFrame({
        'date': dates,
        'r2_country_only': r2_country_only,
        'r2_industry_only': r2_ind_only,
        'r2_full': r2_full,
    })
    results['style_lift'] = results['r2_full'] - results['r2_industry_only']
    results['industry_lift'] = results['r2_industry_only'] - results['r2_country_only']
    results.to_csv(os.path.join(REPORT_DIR, 'val_align2_02_decomposition.csv'), index=False)

    mean_country = np.nanmean(r2_country_only)
    mean_ind = np.nanmean(r2_ind_only)
    mean_full = np.nanmean(r2_full)

    print(f'  Country only (CAPM):     {mean_country:.4f}')
    print(f'  Country + Industry:      {mean_ind:.4f}  (industry adds {mean_ind - mean_country:.4f})')
    print(f'  Full model:              {mean_full:.4f}  (style adds {mean_full - mean_ind:.4f})')

    fig, ax = plt.subplots(figsize=(10, 4))
    x = range(len(dates))
    ax.fill_between(x, 0, results['r2_country_only'], alpha=0.3, label=f'Country ({mean_country:.3f})')
    ax.fill_between(x, results['r2_country_only'], results['r2_industry_only'], alpha=0.3,
                    label=f'+ Industry ({mean_ind - mean_country:.3f})')
    ax.fill_between(x, results['r2_industry_only'], results['r2_full'], alpha=0.3,
                    label=f'+ Style ({mean_full - mean_ind:.3f})')
    ax.set_ylabel('R2')
    ax.set_title('R2 decomposition: Country vs Industry vs Style')
    ax.legend(loc='upper left')
    n_ticks = min(8, len(dates))
    tick_idx = np.linspace(0, len(dates)-1, n_ticks, dtype=int)
    ax.set_xticks(tick_idx)
    ax.set_xticklabels([dates[i][:10] for i in tick_idx], rotation=30)
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS_DIR, 'val_align2_02_decomposition.png'), dpi=150)
    plt.close(fig)

    return mean_country, mean_ind, mean_full


# ------------------------------------------------------------------ #
#  Test 3: R² distribution histogram
# ------------------------------------------------------------------ #

def test_03_r2_distribution(data, industry_cols):
    print('\nTest 3: R2 distribution across dates...', flush=True)
    r2_file = os.path.join(MODEL_DIR, 'barra_r2.csv')
    r2 = pd.read_csv(r2_file, index_col=0)

    vals = r2['R2'].dropna()
    print(f'  N dates: {len(vals)}')
    print(f'  Mean:   {vals.mean():.4f}')
    print(f'  Median: {vals.median():.4f}')
    print(f'  Std:    {vals.std():.4f}')
    print(f'  Min:    {vals.min():.4f}')
    print(f'  Max:    {vals.max():.4f}')
    print(f'  IQR:    {vals.quantile(0.25):.4f} – {vals.quantile(0.75):.4f}')

    pct_below_20 = (vals < 0.20).mean() * 100
    pct_above_50 = (vals > 0.50).mean() * 100
    print(f'  % days below 20%: {pct_below_20:.1f}%')
    print(f'  % days above 50%: {pct_above_50:.1f}%')

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))

    # Histogram
    axes[0].hist(vals, bins=40, color='steelblue', edgecolor='white')
    axes[0].axvline(vals.mean(), color='red', lw=2, label=f'Mean ({vals.mean():.3f})')
    axes[0].axvline(vals.median(), color='orange', lw=2, ls='--', label=f'Median ({vals.median():.3f})')
    axes[0].set_xlabel('Daily R2')
    axes[0].set_ylabel('Count')
    axes[0].set_title('Distribution of daily cross-sectional R2')
    axes[0].legend()

    # Time series
    axes[1].plot(range(len(vals)), vals.values, alpha=0.5, lw=0.8)
    axes[1].axhline(vals.mean(), color='red', lw=1)
    axes[1].set_ylabel('R2')
    axes[1].set_title('Daily R2 over time')
    n_ticks = 6
    tick_idx = np.linspace(0, len(vals)-1, n_ticks, dtype=int)
    axes[1].set_xticks(tick_idx)
    axes[1].set_xticklabels([vals.index[i][:10] for i in tick_idx], rotation=30, fontsize=8)

    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS_DIR, 'val_align2_03_r2_dist.png'), dpi=150)
    plt.close(fig)

    stats = pd.DataFrame({
        'stat': ['mean', 'median', 'std', 'min', 'p25', 'p75', 'max',
                 'pct_below_20', 'pct_above_50'],
        'value': [vals.mean(), vals.median(), vals.std(), vals.min(),
                  vals.quantile(0.25), vals.quantile(0.75), vals.max(),
                  pct_below_20 / 100, pct_above_50 / 100],
    })
    stats.to_csv(os.path.join(REPORT_DIR, 'val_align2_03_r2_dist.csv'), index=False)
    return vals


# ------------------------------------------------------------------ #
#  Main
# ------------------------------------------------------------------ #

def main():
    os.makedirs(PLOTS_DIR, exist_ok=True)
    print('=' * 60)
    print('ALIGNMENT VALIDATION V2')
    print('=' * 60)

    data, industry_cols = load_data()
    print(f'Loaded: {len(data)} rows, {data["date"].nunique()} dates\n')

    baseline, perm_avg, perm_std = test_01_permutation(data, industry_cols)
    mean_country, mean_ind, mean_full = test_02_industry_only(data, industry_cols)
    r2_vals = test_03_r2_distribution(data, industry_cols)

    print('\n' + '=' * 60)
    print('SUMMARY')
    print('=' * 60)
    print(f'Permutation structural floor:  {perm_avg:.4f} +/- {perm_std:.4f}')
    print(f'Industry-only R2:              {mean_ind:.4f}')
    print(f'Full model R2:                 {mean_full:.4f}')
    print(f'Style factor lift:             {mean_full - mean_ind:.4f}')
    print(f'Day-specific lift (vs perm):   {baseline - perm_avg:.4f}')
    print(f'R2 median:                     {r2_vals.median():.4f}')
    print(f'R2 IQR:                        {r2_vals.quantile(0.25):.4f} – {r2_vals.quantile(0.75):.4f}')


if __name__ == '__main__':
    main()
