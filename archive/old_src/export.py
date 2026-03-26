"""
Export Module
Export portfolio analysis results to Excel and other formats.
"""

import pandas as pd
import numpy as np
from datetime import datetime
import os


def export_to_excel(portfolio, metrics: dict, filepath: str):
    """
    Export comprehensive portfolio analysis to multi-sheet Excel workbook.

    Sheets:
    1. Summary - Key metrics table
    2. Holdings - Position-level details
    3. Returns - Time series data
    4. Attribution - Performance breakdown
    """
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else '.', exist_ok=True)

    with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
        # === Sheet 1: Summary ===
        summary_data = {
            'Metric': [
                'Analysis Date',
                'Portfolio GMV',
                'Number of Positions',
                'Effective N',
                '',
                '--- Performance ---',
                'Sharpe Ratio',
                'Information Ratio',
                'Sortino Ratio',
                'Annual Return',
                'Max Drawdown',
                'Hit Rate',
                'Calmar Ratio',
                '',
                '--- Risk ---',
                'Total Volatility',
                'Factor Volatility',
                'Idiosyncratic Volatility',
                '% Idiosyncratic Variance',
                '',
                '--- Factor Exposures ---',
                'Market Beta',
                'Size (SMB) Beta',
                'Value (HML) Beta',
                'Momentum Beta',
                '',
                '--- Benchmark ---',
                f'Beta to {portfolio.benchmark}',
            ],
            'Value': [
                datetime.now().strftime('%Y-%m-%d %H:%M'),
                f"${metrics['gmv']:,.0f}",
                metrics['num_positions'],
                f"{metrics['effective_n']:.1f}",
                '',
                '',
                f"{metrics['sharpe']:.2f}",
                f"{metrics['information_ratio']:.2f}",
                f"{metrics['sortino']:.2f}",
                f"{metrics['annual_return']:.1%}",
                f"{metrics['max_drawdown']:.1%}",
                f"{metrics['hit_rate']:.1%}",
                f"{metrics.get('calmar', 0):.2f}",
                '',
                '',
                f"{metrics['total_vol']:.1%}",
                f"{metrics['factor_vol']:.1%}",
                f"{metrics['idio_vol']:.1%}",
                f"{metrics['pct_idio_var']:.1%}",
                '',
                '',
                f"{portfolio.portfolio_betas.get('Mkt-RF', np.nan):.3f}",
                f"{portfolio.portfolio_betas.get('SMB', np.nan):.3f}",
                f"{portfolio.portfolio_betas.get('HML', np.nan):.3f}",
                f"{portfolio.portfolio_betas.get('Mom', np.nan):.3f}",
                '',
                '',
                f"{metrics.get('portfolio_beta', 'N/A'):.2f}" if metrics.get('portfolio_beta') else 'N/A',
            ]
        }
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name='Summary', index=False)

        # === Sheet 2: Holdings ===
        holdings_df = portfolio.get_position_details()
        holdings_df = holdings_df.reset_index()

        # Format columns
        if 'market_value' in holdings_df.columns:
            holdings_df['market_value'] = holdings_df['market_value'].apply(lambda x: f"${x:,.0f}")
        if 'weight' in holdings_df.columns:
            holdings_df['weight'] = holdings_df['weight'].apply(lambda x: f"{x:.1%}")
        if 'idio_vol' in holdings_df.columns:
            holdings_df['idio_vol'] = holdings_df['idio_vol'].apply(lambda x: f"{x:.1%}" if pd.notna(x) else '')
        if 'r_squared' in holdings_df.columns:
            holdings_df['r_squared'] = holdings_df['r_squared'].apply(lambda x: f"{x:.1%}" if pd.notna(x) else '')

        holdings_df.to_excel(writer, sheet_name='Holdings', index=False)

        # === Sheet 3: Returns ===
        returns_df = pd.DataFrame({
            'Date': portfolio.portfolio_returns.index,
            'Portfolio_Return': portfolio.portfolio_returns.values,
            'Systematic_Return': portfolio.portfolio_systematic.values,
            'Idiosyncratic_Return': portfolio.portfolio_idiosyncratic.values,
        })

        # Add benchmark if available
        if portfolio.benchmark_returns is not None:
            bench = portfolio.benchmark_returns[portfolio.benchmark].reindex(portfolio.portfolio_returns.index)
            returns_df[f'{portfolio.benchmark}_Return'] = bench.values

        # Add cumulative returns
        returns_df['Portfolio_Cumulative'] = (1 + portfolio.portfolio_returns).cumprod() - 1
        returns_df['Systematic_Cumulative'] = (1 + portfolio.portfolio_systematic).cumprod() - 1
        returns_df['Idiosyncratic_Cumulative'] = (1 + portfolio.portfolio_idiosyncratic).cumprod() - 1

        returns_df.to_excel(writer, sheet_name='Returns', index=False)

        # === Sheet 4: Attribution ===
        factors = portfolio.portfolio_betas.index.tolist()
        attribution_data = []

        for factor in factors:
            if factor in portfolio.decomposition['factor_contributions']:
                contrib = portfolio.decomposition['factor_contributions'][factor]
                weighted_contrib = (contrib * portfolio.weights).sum(axis=1)
                total_contrib = weighted_contrib.sum()
                attribution_data.append({
                    'Factor': factor,
                    'Beta': portfolio.portfolio_betas[factor],
                    'Total_Contribution': total_contrib,
                    'Annualized_Contribution': total_contrib * 252 / len(weighted_contrib)
                })

        # Add idiosyncratic
        idio_total = portfolio.portfolio_idiosyncratic.sum()
        attribution_data.append({
            'Factor': 'Idiosyncratic',
            'Beta': '-',
            'Total_Contribution': idio_total,
            'Annualized_Contribution': idio_total * 252 / len(portfolio.portfolio_idiosyncratic)
        })

        attribution_df = pd.DataFrame(attribution_data)
        attribution_df.to_excel(writer, sheet_name='Attribution', index=False)

        # === Sheet 5: Factor Betas (all positions) ===
        betas_df = portfolio.factor_loadings['betas'].copy()
        betas_df['Alpha'] = portfolio.factor_loadings['alphas']
        betas_df['R_Squared'] = portfolio.factor_loadings['r_squared']
        betas_df['Idio_Vol'] = portfolio.factor_loadings['idio_vol']
        betas_df = betas_df.reset_index()
        betas_df.columns = ['Ticker'] + list(betas_df.columns[1:])
        betas_df.to_excel(writer, sheet_name='Factor_Betas', index=False)

    print(f"Exported analysis to: {filepath}")


def export_summary_csv(portfolio, metrics: dict, filepath: str):
    """Export key metrics to CSV."""
    data = {
        'metric': list(metrics.keys()),
        'value': list(metrics.values())
    }
    df = pd.DataFrame(data)
    df.to_csv(filepath, index=False)
    print(f"Exported summary to: {filepath}")


def export_returns_csv(portfolio, filepath: str):
    """Export return series to CSV."""
    df = pd.DataFrame({
        'date': portfolio.portfolio_returns.index,
        'portfolio': portfolio.portfolio_returns.values,
        'systematic': portfolio.portfolio_systematic.values,
        'idiosyncratic': portfolio.portfolio_idiosyncratic.values
    })
    df.to_csv(filepath, index=False)
    print(f"Exported returns to: {filepath}")


# Quick test
if __name__ == "__main__":
    print("Export module loaded successfully")
