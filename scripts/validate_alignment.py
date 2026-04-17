# -*- coding: utf-8 -*-
"""
Date alignment deep-dive: 5 tests to confirm returns-exposures alignment.

Tests:
  1. Multi-day shifts (+5, +10, +20)
  2. High-vol day comparison (aligned vs shifted)
  3. Permutation test (shuffle dates)
  4. Spot-check factor returns on a known regime day
  5. Autocorrelation (already done — included for completeness)

Run: py scripts/validate_alignment.py
"""

import os, sys
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime

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


def run_wls_r2(data, industry_cols, sample_dates):
    """Run WLS regressions on sample_dates, return per-date R2."""
    r2_list = []
    for date in sample_dates:
        dd = data[data['date'] == date]
        y = dd['ret'].values
        cap = dd['capital'].values
        if len(y) < 50:
            r2_list.append(np.nan)
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
            r2_list.append(np.nan)
    return r2_list


def shift_returns(data, shift_days):
    """Shift each ticker's returns by shift_days within the panel."""
    shifted = data.copy()
    parts = []
    for ticker, grp in shifted.groupby('stocknames'):
        g = grp.sort_values('date').copy()
        g['ret'] = g['ret'].shift(-shift_days)
        parts.append(g)
    shifted = pd.concat(parts)
    shifted = shifted.dropna(subset=['ret'])
    return shifted


# ------------------------------------------------------------------ #
#  Test 1: Multi-day shifts
# ------------------------------------------------------------------ #

def test_01_multiday_shifts(data, industry_cols):
    print('Test 1: Multi-day shifts (+1, +5, +10, +20)...', flush=True)
    dates = sorted(data['date'].unique())
    sample = dates[::3]  # every 3rd date for speed

    results = []
    for shift in [0, 1, 5, 10, 20]:
        if shift == 0:
            r2s = run_wls_r2(data, industry_cols, sample)
        else:
            shifted = shift_returns(data, shift)
            r2s = run_wls_r2(shifted, industry_cols, sample)
        mean_r2 = np.nanmean(r2s)
        results.append({'shift_days': shift, 'mean_r2': round(mean_r2, 4)})
        print(f'  shift={shift:+3d}d: R2={mean_r2:.4f}', flush=True)

    df = pd.DataFrame(results)
    df.to_csv(os.path.join(REPORT_DIR, 'val_align_01_shifts.csv'), index=False)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(df['shift_days'], df['mean_r2'], 'o-', markersize=8)
    ax.set_xlabel('Return shift (days)')
    ax.set_ylabel('Mean R2')
    ax.set_title('R2 vs return shift — should decay with distance')
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS_DIR, 'val_align_01_shifts.png'), dpi=150)
    plt.close(fig)

    drop_at_20 = results[0]['mean_r2'] - results[-1]['mean_r2']
    print(f'  R2 drop from 0 to +20d: {drop_at_20:.4f}')
    if drop_at_20 < 0.05:
        print('  WARNING: R2 barely decays — exposures may be too persistent or alignment issue')
    else:
        print('  OK: R2 decays meaningfully with shift distance')
    return df


# ------------------------------------------------------------------ #
#  Test 2: High-vol day comparison
# ------------------------------------------------------------------ #

def test_02_highvol_days(data, industry_cols):
    print('\nTest 2: High-vol day aligned vs shifted...', flush=True)
    dates = sorted(data['date'].unique())

    # Find high-dispersion days: largest cross-sectional std of returns
    daily_vol = []
    for d in dates:
        rets = data[data['date'] == d]['ret']
        daily_vol.append({'date': d, 'cs_std': rets.std(), 'cs_mean': rets.mean()})
    vol_df = pd.DataFrame(daily_vol).sort_values('cs_std', ascending=False)

    # Top 10 highest dispersion days
    top_days = vol_df.head(10)['date'].tolist()
    print(f'  Top 10 high-dispersion days: {top_days[:5]}...')

    # Run aligned vs +1 shifted on these specific days
    r2_aligned = run_wls_r2(data, industry_cols, top_days)
    shifted = shift_returns(data, 1)
    r2_shifted = run_wls_r2(shifted, industry_cols, top_days)

    comparison = pd.DataFrame({
        'date': top_days,
        'r2_aligned': [round(r, 4) for r in r2_aligned],
        'r2_shifted_1d': [round(r, 4) for r in r2_shifted],
    })
    comparison['diff'] = comparison['r2_aligned'] - comparison['r2_shifted_1d']
    comparison = comparison.merge(vol_df[['date', 'cs_std']], on='date')
    comparison.to_csv(os.path.join(REPORT_DIR, 'val_align_02_highvol.csv'), index=False)

    mean_diff = comparison['diff'].mean()
    print(f'  Mean R2 diff (aligned - shifted) on high-vol days: {mean_diff:+.4f}')
    print(comparison.to_string(index=False))
    return comparison


# ------------------------------------------------------------------ #
#  Test 3: Permutation test
# ------------------------------------------------------------------ #

def test_03_permutation(data, industry_cols):
    print('\nTest 3: Permutation test (5 random shuffles)...', flush=True)
    dates = sorted(data['date'].unique())
    sample = dates[::5]

    # Baseline
    r2_baseline = np.nanmean(run_wls_r2(data, industry_cols, sample))
    print(f'  Baseline R2: {r2_baseline:.4f}')

    # Shuffle: for each ticker, randomly permute the date assignment of returns
    shuffle_r2s = []
    for seed in range(5):
        np.random.seed(seed)
        shuffled = data.copy()
        # Shuffle return dates globally (break the date-return link)
        all_dates = shuffled['date'].unique()
        date_map = dict(zip(all_dates, np.random.permutation(all_dates)))
        # Remap each row's return to a random date's return
        ret_by_date = shuffled.groupby('date')['ret'].apply(lambda x: x.values).to_dict()
        parts = []
        for d in all_dates:
            dd = shuffled[shuffled['date'] == d].copy()
            source_d = date_map[d]
            source_rets = ret_by_date.get(source_d)
            if source_rets is not None and len(source_rets) == len(dd):
                dd['ret'] = source_rets
                parts.append(dd)
        if parts:
            shuffled = pd.concat(parts)
            r2 = np.nanmean(run_wls_r2(shuffled, industry_cols, sample))
        else:
            r2 = np.nan
        shuffle_r2s.append(r2)
        print(f'  Shuffle {seed}: R2={r2:.4f}')

    mean_shuffle = np.nanmean(shuffle_r2s)
    results = pd.DataFrame({
        'scenario': ['Baseline'] + [f'Shuffle {i}' for i in range(5)],
        'mean_r2': [r2_baseline] + shuffle_r2s,
    })
    results.to_csv(os.path.join(REPORT_DIR, 'val_align_03_permutation.csv'), index=False)

    print(f'  Baseline: {r2_baseline:.4f}, Mean shuffled: {mean_shuffle:.4f}')
    if mean_shuffle > 0.15:
        print(f'  WARNING: Shuffled R2 is {mean_shuffle:.1%} — most explanatory power is structural, not day-specific')
    else:
        print(f'  OK: Shuffled R2 collapses to {mean_shuffle:.1%}')
    return results


# ------------------------------------------------------------------ #
#  Test 4: Spot-check known regime day
# ------------------------------------------------------------------ #

def test_04_regime_day(data, industry_cols):
    print('\nTest 4: Spot-check factor returns on extreme days...', flush=True)
    fr = pd.read_csv(os.path.join(MODEL_DIR, 'barra_factor_returns.csv'), index_col=0)

    # Find biggest up-day and biggest down-day by Country factor
    country = fr['Country']
    best_day = country.idxmax()
    worst_day = country.idxmin()

    print(f'  Biggest up-day:   {best_day} (Country = {country[best_day]:+.4f})')
    print(f'  Biggest down-day: {worst_day} (Country = {country[worst_day]:+.4f})')

    # For each, show all factor returns and check signs make sense
    for label, day in [('Best market day', best_day), ('Worst market day', worst_day)]:
        if day in fr.index:
            row = fr.loc[day]
            print(f'\n  {label}: {day}')
            # Style factors
            for col in STYLE_COLS:
                print(f'    {col:12s}: {row[col]:+.5f}')
            # On up-days: beta should be positive (high-beta outperforms)
            # On down-days: beta should be negative
            beta_ret = row['beta']
            country_ret = row['Country']
            sign_match = (beta_ret > 0 and country_ret > 0) or (beta_ret < 0 and country_ret < 0)
            print(f'    Beta-Country sign match: {"YES" if sign_match else "NO"} '
                  f'(beta={beta_ret:+.5f}, country={country_ret:+.5f})')

    # Also check: on biggest value day, btop should be large positive
    btop = fr['btop']
    best_value_day = btop.idxmax()
    print(f'\n  Biggest value day: {best_value_day} (btop = {btop[best_value_day]:+.5f})')
    row = fr.loc[best_value_day]
    print(f'    Country: {row["Country"]:+.5f}, earnyild: {row["earnyild"]:+.5f}, '
          f'momentum: {row["momentum"]:+.5f}')

    summary = pd.DataFrame({
        'event': ['Best market day', 'Worst market day', 'Best value day'],
        'date': [best_day, worst_day, best_value_day],
        'country_ret': [fr.loc[best_day, 'Country'], fr.loc[worst_day, 'Country'],
                        fr.loc[best_value_day, 'Country']],
        'beta_ret': [fr.loc[best_day, 'beta'], fr.loc[worst_day, 'beta'],
                     fr.loc[best_value_day, 'beta']],
        'btop_ret': [fr.loc[best_day, 'btop'], fr.loc[worst_day, 'btop'],
                     fr.loc[best_value_day, 'btop']],
    })
    summary.to_csv(os.path.join(REPORT_DIR, 'val_align_04_regime.csv'), index=False)
    return summary


# ------------------------------------------------------------------ #
#  Test 5: Autocorrelation (already computed, reprint)
# ------------------------------------------------------------------ #

def test_05_autocorrelation():
    print('\nTest 5: Factor return autocorrelation (from overnight run)...', flush=True)
    ac_path = os.path.join(REPORT_DIR, 'val_06_autocorr.csv')
    if os.path.exists(ac_path):
        ac = pd.read_csv(ac_path)
        high = ac[ac['abs_ac'] > 0.1]
        print(f'  {len(high)} factors with |autocorr| > 0.1:')
        for _, r in high.iterrows():
            print(f'    {r["factor"]:40s}: {r["lag1_autocorr"]:+.3f}')
        if len(high) == 0:
            print('  All factors under 0.1 — no autocorrelation concern')
    else:
        print('  Autocorrelation CSV not found — skipping')


# ------------------------------------------------------------------ #
#  Main
# ------------------------------------------------------------------ #

def main():
    os.makedirs(PLOTS_DIR, exist_ok=True)
    print('=' * 60)
    print('DATE ALIGNMENT VALIDATION')
    print('=' * 60)

    data, industry_cols = load_data()
    print(f'Loaded: {len(data)} rows, {data["date"].nunique()} dates, '
          f'{len(industry_cols)} industries\n')

    test_01_multiday_shifts(data, industry_cols)
    test_02_highvol_days(data, industry_cols)
    test_03_permutation(data, industry_cols)
    test_04_regime_day(data, industry_cols)
    test_05_autocorrelation()

    print('\n' + '=' * 60)
    print('ALIGNMENT VALIDATION COMPLETE')
    print('=' * 60)


if __name__ == '__main__':
    main()
