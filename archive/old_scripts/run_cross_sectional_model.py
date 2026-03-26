# -*- coding: utf-8 -*-
"""
Run cross-sectional factor model on S&P 500 data
Estimates factor returns using Barra-style methodology
"""

import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

def run_cross_sectional_regression(data, industry_cols, style_cols):
    """
    Run cross-sectional regression for each date
    Returns: factor returns, specific returns, R-squared

    Uses constrained regression: industry factor returns are relative to
    cap-weighted average (market return absorbed into industry factors)
    """
    dates = data['date'].unique()

    factor_returns = []
    r2_values = []

    # Drop one industry to avoid multicollinearity (use as reference)
    # We'll use the largest sector as reference
    ref_industry = industry_cols[0]  # Technology
    active_industries = [c for c in industry_cols if c != ref_industry]

    print(f"Running cross-sectional regression for {len(dates)} dates...")
    print(f"Industries: {len(active_industries)} (reference: {ref_industry})")
    print(f"Style factors: {len(style_cols)}")

    for date in dates:
        # Get data for this date
        df_t = data[data['date'] == date].copy()

        # Stock returns (dependent variable)
        y = df_t['ret'].values

        # Market cap for weighting
        weights = df_t['capital'].values
        weights = weights / weights.sum()  # Normalize

        # Factor exposures (independent variables)
        # Intercept + Industries (minus reference) + Styles
        X_intercept = np.ones((len(df_t), 1))
        X_industry = df_t[active_industries].values
        X_style = df_t[style_cols].values

        # Combine: [intercept, industries, styles]
        X = np.hstack([X_intercept, X_industry, X_style])

        # Weighted least squares using pseudo-inverse for numerical stability
        try:
            # Weight the observations
            W = np.diag(np.sqrt(weights))
            Xw = W @ X
            yw = W @ y

            # Solve using pseudo-inverse
            factor_ret = np.linalg.pinv(Xw) @ yw

            # Calculate R-squared
            y_pred = X @ factor_ret
            ss_res = np.sum(weights * (y - y_pred)**2)
            ss_tot = np.sum(weights * (y - np.average(y, weights=weights))**2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

            factor_returns.append(factor_ret)
            r2_values.append(r2)

        except Exception as e:
            print(f"  Error on {date}: {e}")
            factor_returns.append(np.full(X.shape[1], np.nan))
            r2_values.append(np.nan)

    # Create DataFrame with factor returns
    factor_names = ['Market'] + active_industries + style_cols
    factor_ret_df = pd.DataFrame(factor_returns, columns=factor_names, index=dates)
    r2_df = pd.DataFrame(r2_values, columns=['R2'], index=dates)

    return factor_ret_df, r2_df, ref_industry


def calculate_factor_covariance(factor_returns, halflife=252):
    """
    Calculate factor covariance matrix with exponential weighting
    """
    T = len(factor_returns)

    # Exponential weights
    weights = np.array([0.5 ** ((T - 1 - t) / halflife) for t in range(T)])
    weights = weights / weights.sum()

    # Weighted mean
    mean = np.average(factor_returns.values, axis=0, weights=weights)

    # Weighted covariance
    demeaned = factor_returns.values - mean
    cov = np.zeros((len(factor_returns.columns), len(factor_returns.columns)))

    for t in range(T):
        cov += weights[t] * np.outer(demeaned[t], demeaned[t])

    # Annualize
    cov = cov * 252

    return pd.DataFrame(cov, index=factor_returns.columns, columns=factor_returns.columns)


def main():
    print("="*60)
    print("Cross-Sectional Factor Model")
    print("="*60)

    # Load data
    print("\nLoading data...")
    data = pd.read_csv('sp500_cross_sectional_data.csv')
    print(f"  Shape (raw): {data.shape}")

    # Fill NaN in style factors with 0 (neutral exposure)
    style_cols = ['size', 'momentum', 'volatility', 'value', 'quality', 'liquidity']
    for col in style_cols:
        nan_count = data[col].isna().sum()
        if nan_count > 0:
            print(f"  Filling {nan_count} NaN values in {col} with 0")
            data[col] = data[col].fillna(0)

    # Drop rows with NaN in returns
    data = data.dropna(subset=['ret'])

    print(f"  Shape (clean): {data.shape}")
    print(f"  Dates: {data['date'].nunique()}")
    print(f"  Stocks: {data['stocknames'].nunique()}")

    # Identify columns
    industry_cols = ['Technology', 'Communication Services', 'Healthcare',
                     'Financial Services', 'Consumer Cyclical', 'Consumer Defensive',
                     'Industrials', 'Energy', 'Basic Materials', 'Utilities', 'Real Estate']
    style_cols = ['size', 'momentum', 'volatility', 'value', 'quality', 'liquidity']

    # Run cross-sectional regression
    print("\n" + "="*60)
    factor_returns, r2, ref_industry = run_cross_sectional_regression(data, industry_cols, style_cols)
    print(f"Reference industry: {ref_industry}")

    print(f"\nCross-sectional regression results:")
    print(f"  Average R-squared: {r2['R2'].mean():.4f}")
    print(f"  Min R-squared: {r2['R2'].min():.4f}")
    print(f"  Max R-squared: {r2['R2'].max():.4f}")

    # Factor return statistics (annualized)
    print("\n" + "="*60)
    print("Factor Return Statistics (annualized)")
    print("="*60)

    stats = pd.DataFrame({
        'Mean (%)': factor_returns.mean() * 252 * 100,
        'Std (%)': factor_returns.std() * np.sqrt(252) * 100,
        't-stat': (factor_returns.mean() / factor_returns.std()) * np.sqrt(len(factor_returns))
    })
    print(stats.round(2))

    # Calculate factor covariance matrix
    print("\n" + "="*60)
    print("Factor Covariance Matrix (annualized, style factors only)")
    print("="*60)

    style_returns = factor_returns[style_cols]
    factor_cov = calculate_factor_covariance(style_returns, halflife=252)

    # Show correlation matrix instead (easier to interpret)
    std = np.sqrt(np.diag(factor_cov))
    factor_corr = factor_cov / np.outer(std, std)
    print("\nFactor Correlations:")
    print(factor_corr.round(2))

    print("\nFactor Volatilities (annualized %):")
    print((np.sqrt(np.diag(factor_cov)) * 100).round(2))

    # Save results
    print("\n" + "="*60)
    print("Saving results...")
    print("="*60)

    factor_returns.to_csv('estimated_factor_returns.csv')
    print("  Saved factor returns to estimated_factor_returns.csv")

    factor_cov.to_csv('factor_covariance_matrix.csv')
    print("  Saved factor covariance matrix to factor_covariance_matrix.csv")

    # Summary statistics
    stats.to_csv('factor_return_statistics.csv')
    print("  Saved factor statistics to factor_return_statistics.csv")

    print("\n" + "="*60)
    print("Done!")
    print("="*60)

    return factor_returns, factor_cov, stats


if __name__ == '__main__':
    factor_returns, factor_cov, stats = main()
