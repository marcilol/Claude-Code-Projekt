# -*- coding: utf-8 -*-
"""
Compare Alpha Sizing Methods Across Multiple Portfolios
Creates a chart comparing Sharpe ratios for each method across portfolios.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import sys
import os

# Import functions from size_positions
from size_positions import (
    load_portfolio,
    compute_idiosyncratic_volatility,
    get_sector_volatility,
    get_stock_sectors,
    size_proportional,
    size_risk_parity,
    size_mean_variance,
    size_shrunk_mv,
    compute_weights,
    backtest_weights
)


def analyze_portfolio(portfolio_path, factor_exp_df, factor_ret_df,
                      decision_date='2025-07-01', end_date='2025-12-31',
                      target_gmv=100000, expected_return=0.30, horizon_months=6):
    """
    Run all sizing methods on a portfolio and return results.
    """
    try:
        # Load portfolio
        portfolio_df = load_portfolio(portfolio_path)
        tickers = portfolio_df['ticker'].tolist()

        # Filter to available tickers
        available_tickers = set(factor_exp_df['ticker'].unique())
        valid_tickers = [t for t in tickers if t in available_tickers]

        if len(valid_tickers) < 3:
            print(f"  Skipping - only {len(valid_tickers)} valid tickers")
            return None

        # Compute idiosyncratic volatility
        idio_vols = compute_idiosyncratic_volatility(
            valid_tickers, factor_exp_df, factor_ret_df, decision_date
        )

        # Get sector info
        stock_sectors = get_stock_sectors(valid_tickers, factor_exp_df, decision_date)
        sector_vols = get_sector_volatility(factor_ret_df, decision_date)

        # Compute alphas (uniform)
        annualized_alpha = expected_return * (12 / horizon_months)
        alphas = {t: annualized_alpha for t in valid_tickers}

        # Apply four sizing methods
        methods = {}

        nmv_prop = size_proportional(alphas, target_gmv)
        methods['Proportional'] = compute_weights(nmv_prop)

        nmv_rp = size_risk_parity(alphas, idio_vols, target_gmv)
        methods['Risk Parity'] = compute_weights(nmv_rp)

        nmv_mv = size_mean_variance(alphas, idio_vols, target_gmv)
        methods['Mean-Variance'] = compute_weights(nmv_mv)

        nmv_smv = size_shrunk_mv(alphas, idio_vols, sector_vols, stock_sectors, target_gmv, shrink=0.75)
        methods['Shrunk MV'] = compute_weights(nmv_smv)

        # Backtest each method
        results = {}
        for method_name, weights in methods.items():
            bt_result = backtest_weights(weights, factor_exp_df, decision_date, end_date)
            results[method_name] = bt_result

        return results

    except Exception as e:
        print(f"  Error: {e}")
        return None


def main():
    print("=" * 70)
    print("SIZING METHODS COMPARISON ACROSS PORTFOLIOS")
    print("=" * 70)

    # Portfolios to analyze
    portfolios = {
        'Own Portfolio': 'data/input/portfolios/Own_Portfolio_dated.csv',
        'Dynamic AI': 'data/input/portfolios/Dynamic_AI.csv',
        'Robotics': 'data/input/portfolios/Robotics.csv',
        'Fiscal Primacy': 'data/input/portfolios/Fiscal_Primacy.csv',
        'Small Themes': 'data/input/portfolios/Small_Themes.csv',
    }

    # Load factor data once
    print("\nLoading factor model data...")
    factor_exp_df = pd.read_csv('data/model/russell3000_factor_exposures_historical.csv')
    factor_ret_df = pd.read_csv('data/model/barra_factor_returns.csv', index_col=0)
    print("  Done.")

    # Parameters
    decision_date = '2025-07-01'
    end_date = '2025-12-31'

    # Collect results
    all_results = {}

    print(f"\nAnalyzing portfolios (decision: {decision_date}, end: {end_date})...")
    print("-" * 70)

    for name, path in portfolios.items():
        print(f"\n{name}:")
        results = analyze_portfolio(path, factor_exp_df, factor_ret_df,
                                    decision_date, end_date)
        if results:
            all_results[name] = results
            for method, res in results.items():
                print(f"  {method:<15}: Return={res['total_return']*100:>6.1f}%, Sharpe={res['sharpe']:>5.2f}")

    # Create summary table
    print("\n" + "=" * 70)
    print("SHARPE RATIO SUMMARY")
    print("=" * 70)

    methods = ['Proportional', 'Risk Parity', 'Mean-Variance', 'Shrunk MV']

    print(f"\n{'Portfolio':<20}", end='')
    for m in methods:
        print(f"{m:<15}", end='')
    print()
    print("-" * 80)

    for portfolio_name, results in all_results.items():
        print(f"{portfolio_name:<20}", end='')
        for method in methods:
            if method in results:
                print(f"{results[method]['sharpe']:<15.2f}", end='')
            else:
                print(f"{'N/A':<15}", end='')
        print()

    # Create chart
    print("\n" + "=" * 70)
    print("GENERATING CHART")
    print("=" * 70)

    fig, ax = plt.subplots(figsize=(12, 7))

    portfolio_names = list(all_results.keys())
    x = np.arange(len(portfolio_names))

    colors = ['#2ecc71', '#3498db', '#e74c3c', '#9b59b6']
    markers = ['o', 's', '^', 'D']

    for i, method in enumerate(methods):
        sharpes = []
        for portfolio_name in portfolio_names:
            if method in all_results[portfolio_name]:
                sharpes.append(all_results[portfolio_name][method]['sharpe'])
            else:
                sharpes.append(np.nan)

        ax.plot(x, sharpes, marker=markers[i], markersize=10, linewidth=2,
                color=colors[i], label=method)

    ax.set_xlabel('Portfolio', fontsize=12, fontweight='bold')
    ax.set_ylabel('Sharpe Ratio', fontsize=12, fontweight='bold')
    ax.set_title('Alpha Sizing Methods: Sharpe Ratio Comparison\n(Jul 2025 - Dec 2025, 30% expected return over 6 months)',
                 fontsize=14, fontweight='bold')

    ax.set_xticks(x)
    ax.set_xticklabels(portfolio_names, rotation=15, ha='right')

    ax.legend(loc='best', fontsize=10)
    ax.grid(True, alpha=0.3)

    # Add horizontal line at y=0 for reference
    ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)

    plt.tight_layout()

    # Save chart
    output_path = 'data/model/sizing_methods_comparison.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"\nChart saved to: {output_path}")

    plt.close()

    # Also create a returns comparison chart
    fig, ax = plt.subplots(figsize=(12, 7))

    for i, method in enumerate(methods):
        returns = []
        for portfolio_name in portfolio_names:
            if method in all_results[portfolio_name]:
                returns.append(all_results[portfolio_name][method]['total_return'] * 100)
            else:
                returns.append(np.nan)

        ax.plot(x, returns, marker=markers[i], markersize=10, linewidth=2,
                color=colors[i], label=method)

    ax.set_xlabel('Portfolio', fontsize=12, fontweight='bold')
    ax.set_ylabel('Total Return (%)', fontsize=12, fontweight='bold')
    ax.set_title('Alpha Sizing Methods: Return Comparison\n(Jul 2025 - Dec 2025, 30% expected return over 6 months)',
                 fontsize=14, fontweight='bold')

    ax.set_xticks(x)
    ax.set_xticklabels(portfolio_names, rotation=15, ha='right')

    ax.legend(loc='best', fontsize=10)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()

    output_path2 = 'data/model/sizing_methods_returns.png'
    plt.savefig(output_path2, dpi=150, bbox_inches='tight')
    print(f"Chart saved to: {output_path2}")

    plt.close()

    # Summary statistics
    print("\n" + "=" * 70)
    print("SUMMARY STATISTICS")
    print("=" * 70)

    for method in methods:
        sharpes = [all_results[p][method]['sharpe'] for p in portfolio_names if method in all_results[p]]
        returns = [all_results[p][method]['total_return'] for p in portfolio_names if method in all_results[p]]
        print(f"\n{method}:")
        print(f"  Avg Sharpe: {np.mean(sharpes):.2f}")
        print(f"  Avg Return: {np.mean(returns)*100:.1f}%")
        print(f"  # Wins (best Sharpe): {sum(1 for p in portfolio_names if all_results[p][method]['sharpe'] == max(all_results[p][m]['sharpe'] for m in methods))}")

    print("\n" + "=" * 70)


if __name__ == '__main__':
    main()
