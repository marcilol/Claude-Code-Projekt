"""
Visualizer Module
Creates charts for portfolio analysis.

Required charts:
1. Factor Exposure Bar Chart
2. Performance Attribution Stacked Area Chart
3. Risk Decomposition Pie Chart
4. Cumulative Returns Comparison
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime


# Set style for professional look
plt.style.use('ggplot')
plt.rcParams['figure.figsize'] = (10, 6)
plt.rcParams['font.size'] = 10
plt.rcParams['axes.titlesize'] = 12
plt.rcParams['axes.labelsize'] = 10


def plot_factor_exposures(portfolio_betas: pd.Series,
                          gmv: float = None,
                          save_path: str = None,
                          show: bool = True) -> plt.Figure:
    """
    Create Factor Exposure Bar Chart.

    X-axis: Factor names (Market, Size, Value, Momentum)
    Y-axis: Factor beta (and optionally dollar exposure)
    """
    fig, ax = plt.subplots(figsize=(10, 6))

    factors = portfolio_betas.index.tolist()
    betas = portfolio_betas.values

    # Color code by positive/negative
    colors = ['#2ecc71' if b >= 0 else '#e74c3c' for b in betas]

    bars = ax.bar(factors, betas, color=colors, edgecolor='black', linewidth=0.5)

    # Add value labels on bars
    for bar, beta in zip(bars, betas):
        height = bar.get_height()
        ax.annotate(f'{beta:.2f}',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3 if height >= 0 else -12),
                    textcoords="offset points",
                    ha='center', va='bottom' if height >= 0 else 'top',
                    fontsize=11, fontweight='bold')

    ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    ax.axhline(y=1, color='gray', linestyle='--', linewidth=0.5, alpha=0.5)

    ax.set_xlabel('Factor')
    ax.set_ylabel('Factor Beta')
    ax.set_title('Portfolio Factor Exposures')

    # Add GMV annotation if provided
    if gmv is not None:
        ax.text(0.02, 0.98, f'Portfolio GMV: ${gmv:,.0f}',
                transform=ax.transAxes, fontsize=9,
                verticalalignment='top', style='italic')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {save_path}")

    if show:
        plt.show()

    return fig


def plot_risk_decomposition(pct_idio_var: float,
                            factor_vol: float = None,
                            idio_vol: float = None,
                            save_path: str = None,
                            show: bool = True) -> plt.Figure:
    """
    Create Risk Decomposition Pie Chart.

    Slices: Factor variance %, Idiosyncratic variance %
    """
    fig, ax = plt.subplots(figsize=(8, 8))

    pct_factor = 1 - pct_idio_var
    sizes = [pct_factor * 100, pct_idio_var * 100]
    labels = ['Factor Risk\n(Systematic)', 'Idiosyncratic Risk\n(Stock-Specific)']
    colors = ['#3498db', '#2ecc71']
    explode = (0, 0.05)  # Slightly explode idiosyncratic slice

    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, colors=colors, explode=explode,
        autopct='%1.1f%%', startangle=90, pctdistance=0.6,
        wedgeprops={'edgecolor': 'white', 'linewidth': 2}
    )

    # Style the percentage text
    for autotext in autotexts:
        autotext.set_fontsize(14)
        autotext.set_fontweight('bold')

    ax.set_title('Portfolio Risk Decomposition', fontsize=14, fontweight='bold')

    # Add volatility annotations if provided
    if factor_vol is not None and idio_vol is not None:
        total_vol = np.sqrt(factor_vol**2 + idio_vol**2)
        info_text = (f"Total Vol: {total_vol:.1%}\n"
                     f"Factor Vol: {factor_vol:.1%}\n"
                     f"Idio Vol: {idio_vol:.1%}")
        ax.text(0.5, -0.1, info_text, transform=ax.transAxes,
                fontsize=10, ha='center', style='italic',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    # Interpretation
    if pct_idio_var >= 0.75:
        quality = "EXCELLENT - Pure stock selection"
        quality_color = 'green'
    elif pct_idio_var >= 0.50:
        quality = "MODERATE - Mixed risk sources"
        quality_color = 'orange'
    else:
        quality = "LOW - Heavy factor exposure"
        quality_color = 'red'

    ax.text(0.5, 1.05, quality, transform=ax.transAxes,
            fontsize=11, ha='center', fontweight='bold', color=quality_color)

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {save_path}")

    if show:
        plt.show()

    return fig


def plot_performance_attribution(portfolio_returns: pd.Series,
                                  systematic_returns: pd.Series,
                                  idiosyncratic_returns: pd.Series,
                                  factor_contributions: dict = None,
                                  save_path: str = None,
                                  show: bool = True) -> plt.Figure:
    """
    Create Performance Attribution Stacked Area Chart.

    Shows cumulative contribution from each source over time.
    """
    fig, ax = plt.subplots(figsize=(12, 6))

    # Calculate cumulative returns
    dates = portfolio_returns.index
    total_cum = (1 + portfolio_returns).cumprod() - 1
    sys_cum = (1 + systematic_returns).cumprod() - 1
    idio_cum = (1 + idiosyncratic_returns).cumprod() - 1

    # Plot stacked area
    ax.fill_between(dates, 0, sys_cum * 100, alpha=0.6, label='Factor Returns',
                    color='#3498db')
    ax.fill_between(dates, sys_cum * 100, (sys_cum + idio_cum) * 100, alpha=0.6,
                    label='Idiosyncratic Returns', color='#2ecc71')

    # Plot total as line
    ax.plot(dates, total_cum * 100, color='black', linewidth=2, label='Total Return')

    ax.axhline(y=0, color='gray', linestyle='-', linewidth=0.5)

    ax.set_xlabel('Date')
    ax.set_ylabel('Cumulative Return (%)')
    ax.set_title('Performance Attribution Over Time')
    ax.legend(loc='upper left')

    # Format x-axis dates
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.xticks(rotation=45)

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {save_path}")

    if show:
        plt.show()

    return fig


def plot_cumulative_returns(portfolio_returns: pd.Series,
                            benchmark_returns: pd.Series = None,
                            benchmark_name: str = 'Benchmark',
                            save_path: str = None,
                            show: bool = True) -> plt.Figure:
    """
    Create Cumulative Returns Comparison Chart.

    Portfolio vs Benchmark over time, with drawdown shading.
    """
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), height_ratios=[3, 1])

    dates = portfolio_returns.index
    port_cum = (1 + portfolio_returns).cumprod()

    # Main chart - cumulative returns
    ax1.plot(dates, (port_cum - 1) * 100, color='#2ecc71', linewidth=2,
             label='Portfolio')

    if benchmark_returns is not None:
        # Align benchmark to portfolio dates
        bench_aligned = benchmark_returns.reindex(dates).dropna()
        if len(bench_aligned) > 0:
            bench_cum = (1 + bench_aligned).cumprod()
            ax1.plot(bench_aligned.index, (bench_cum - 1) * 100, color='#3498db',
                     linewidth=2, label=benchmark_name, linestyle='--')

    ax1.axhline(y=0, color='gray', linestyle='-', linewidth=0.5)
    ax1.set_ylabel('Cumulative Return (%)')
    ax1.set_title('Portfolio Performance vs Benchmark')
    ax1.legend(loc='upper left')
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

    # Drawdown chart
    rolling_max = port_cum.expanding().max()
    drawdown = (port_cum / rolling_max - 1) * 100

    ax2.fill_between(dates, 0, drawdown, color='#e74c3c', alpha=0.5)
    ax2.plot(dates, drawdown, color='#e74c3c', linewidth=1)
    ax2.axhline(y=0, color='gray', linestyle='-', linewidth=0.5)
    ax2.set_xlabel('Date')
    ax2.set_ylabel('Drawdown (%)')
    ax2.set_title('Portfolio Drawdown')
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))

    plt.xticks(rotation=45)
    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {save_path}")

    if show:
        plt.show()

    return fig


def plot_position_betas(betas: pd.DataFrame,
                        weights: pd.Series = None,
                        save_path: str = None,
                        show: bool = True) -> plt.Figure:
    """
    Create heatmap of position factor betas.
    """
    fig, ax = plt.subplots(figsize=(10, max(6, len(betas) * 0.4)))

    # Sort by market beta
    betas_sorted = betas.sort_values('Mkt-RF', ascending=True)

    # Create heatmap data
    data = betas_sorted.values
    tickers = betas_sorted.index.tolist()
    factors = betas_sorted.columns.tolist()

    # Plot heatmap
    im = ax.imshow(data, aspect='auto', cmap='RdYlGn', vmin=-2, vmax=2)

    # Set ticks
    ax.set_xticks(range(len(factors)))
    ax.set_xticklabels(factors)
    ax.set_yticks(range(len(tickers)))
    ax.set_yticklabels(tickers)

    # Add value annotations
    for i in range(len(tickers)):
        for j in range(len(factors)):
            val = data[i, j]
            if pd.notna(val):
                text_color = 'white' if abs(val) > 1 else 'black'
                ax.text(j, i, f'{val:.2f}', ha='center', va='center',
                        fontsize=9, color=text_color)

    ax.set_title('Position Factor Betas')
    plt.colorbar(im, ax=ax, label='Beta')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Saved: {save_path}")

    if show:
        plt.show()

    return fig


def generate_all_charts(portfolio, output_dir: str = None, show: bool = True):
    """
    Generate all charts for a portfolio.

    Args:
        portfolio: Portfolio object with completed analysis
        output_dir: Directory to save charts (None = don't save)
        show: Whether to display charts
    """
    import os

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    charts = {}

    # 1. Factor Exposures
    save_path = os.path.join(output_dir, 'factor_exposures.png') if output_dir else None
    charts['factor_exposures'] = plot_factor_exposures(
        portfolio.portfolio_betas,
        gmv=portfolio.gmv,
        save_path=save_path,
        show=show
    )

    # 2. Risk Decomposition
    save_path = os.path.join(output_dir, 'risk_decomposition.png') if output_dir else None
    charts['risk_decomposition'] = plot_risk_decomposition(
        portfolio.metrics['pct_idio_var'],
        factor_vol=portfolio.metrics['factor_vol'],
        idio_vol=portfolio.metrics['idio_vol'],
        save_path=save_path,
        show=show
    )

    # 3. Performance Attribution
    save_path = os.path.join(output_dir, 'performance_attribution.png') if output_dir else None
    charts['performance_attribution'] = plot_performance_attribution(
        portfolio.portfolio_returns,
        portfolio.portfolio_systematic,
        portfolio.portfolio_idiosyncratic,
        save_path=save_path,
        show=show
    )

    # 4. Cumulative Returns
    save_path = os.path.join(output_dir, 'cumulative_returns.png') if output_dir else None
    bench_ret = portfolio.benchmark_returns[portfolio.benchmark] if portfolio.benchmark_returns is not None else None
    charts['cumulative_returns'] = plot_cumulative_returns(
        portfolio.portfolio_returns,
        benchmark_returns=bench_ret,
        benchmark_name=portfolio.benchmark,
        save_path=save_path,
        show=show
    )

    # 5. Position Betas (bonus chart)
    if len(portfolio.factor_loadings['betas']) > 1:
        save_path = os.path.join(output_dir, 'position_betas.png') if output_dir else None
        charts['position_betas'] = plot_position_betas(
            portfolio.factor_loadings['betas'],
            portfolio.weights,
            save_path=save_path,
            show=show
        )

    print(f"\nGenerated {len(charts)} charts")
    return charts


# Quick test
if __name__ == "__main__":
    import numpy as np

    print("Testing visualizer module...")

    # Test with synthetic data
    np.random.seed(42)
    dates = pd.date_range('2024-01-01', periods=252, freq='B')

    # Synthetic portfolio returns
    portfolio_returns = pd.Series(np.random.normal(0.0008, 0.015, 252), index=dates)
    systematic_returns = pd.Series(np.random.normal(0.0005, 0.012, 252), index=dates)
    idiosyncratic_returns = portfolio_returns - systematic_returns

    # Synthetic benchmark
    benchmark_returns = pd.Series(np.random.normal(0.0004, 0.01, 252), index=dates)

    # Synthetic betas
    portfolio_betas = pd.Series({
        'Mkt-RF': 1.15,
        'SMB': -0.25,
        'HML': 0.10,
        'Mom': 0.30
    })

    print("\nGenerating test charts...")

    # Test each chart
    plot_factor_exposures(portfolio_betas, gmv=100000, show=True)
    plot_risk_decomposition(0.35, factor_vol=0.18, idio_vol=0.12, show=True)
    plot_performance_attribution(portfolio_returns, systematic_returns,
                                  idiosyncratic_returns, show=True)
    plot_cumulative_returns(portfolio_returns, benchmark_returns, show=True)

    print("Visualizer tests complete!")
