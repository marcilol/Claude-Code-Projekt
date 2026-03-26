"""
Portfolio Module
Main Portfolio class implementing risk decomposition and analysis.

Based on Giuseppe Paleologo's "Advanced Portfolio Management" book.
Key concept: Decompose portfolio risk into factor (systematic) and idiosyncratic components.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from .data_loader import (
    load_portfolio_csv,
    fetch_stock_prices,
    fetch_fama_french_factors,
    calculate_returns,
    align_data,
    get_current_prices
)
from .factors import (
    estimate_factor_loadings,
    decompose_returns,
    calculate_factor_covariance,
    calculate_idiosyncratic_covariance,
    get_factor_interpretation
)


class Portfolio:
    """
    Portfolio analysis class implementing factor-based risk decomposition.

    Usage:
        pf = Portfolio('my_holdings.csv', benchmark='SPY')
        pf.load_data()
        pf.calculate_factor_exposures()
        pf.decompose_returns()
        results = pf.calculate_metrics()
    """

    def __init__(self, csv_path: str, start_date: str = None, end_date: str = None,
                 benchmark: str = 'SPY'):
        """
        Initialize Portfolio.

        Args:
            csv_path: Path to CSV file with holdings (Ticker, Shares, BuyDate, [SellDate])
            start_date: Analysis start date (default: earliest BuyDate - 1 year)
            end_date: Analysis end date (default: today)
            benchmark: Benchmark ticker for comparison (default: SPY)
        """
        self.csv_path = csv_path
        self.start_date = start_date
        self.end_date = end_date or datetime.now().strftime('%Y-%m-%d')
        self.benchmark = benchmark

        # Data storage
        self.holdings = None
        self.prices = None
        self.returns = None
        self.factor_returns = None
        self.benchmark_returns = None

        # Analysis results
        self.factor_loadings = None
        self.decomposition = None
        self.metrics = None
        self.weights = None

    def load_data(self):
        """Load portfolio and fetch all required data."""
        print("=" * 50)
        print("LOADING PORTFOLIO DATA")
        print("=" * 50)

        # Load holdings from CSV
        self.holdings = load_portfolio_csv(self.csv_path)

        # Determine date range
        earliest_buy = self.holdings['buy_date'].min()
        if self.start_date is None:
            # Start 1 year before earliest buy for factor estimation
            self.start_date = (earliest_buy - timedelta(days=365)).strftime('%Y-%m-%d')

        print(f"\nDate range: {self.start_date} to {self.end_date}")

        # Get unique tickers (include benchmark)
        tickers = self.holdings['ticker'].unique().tolist()
        all_tickers = tickers + [self.benchmark]

        # Fetch price data
        self.prices = fetch_stock_prices(all_tickers, self.start_date, self.end_date)

        # Separate benchmark
        if self.benchmark in self.prices.columns:
            benchmark_prices = self.prices[[self.benchmark]]
            self.prices = self.prices.drop(columns=[self.benchmark])
            self.benchmark_returns = calculate_returns(benchmark_prices)
        else:
            print(f"WARNING: Benchmark {self.benchmark} not found")
            self.benchmark_returns = None

        # Calculate returns
        self.returns = calculate_returns(self.prices)

        # Fetch factor data
        self.factor_returns = fetch_fama_french_factors(self.start_date, self.end_date)

        # Align all data
        self.returns, self.factor_returns = align_data(self.returns, self.factor_returns)

        # Calculate current weights
        self._calculate_weights()

        print(f"\nLoaded {len(self.holdings)} positions")
        print(f"Portfolio GMV: ${self.gmv:,.2f}")

        return self

    def _calculate_weights(self):
        """Calculate portfolio weights based on current market values."""
        # Get current prices
        current_prices = self.prices.iloc[-1]

        # Aggregate holdings by ticker (sum shares across multiple buys)
        holdings_agg = self.holdings.groupby('ticker')['shares'].sum()

        # Calculate market values
        market_values = {}
        for ticker in holdings_agg.index:
            if ticker in current_prices.index:
                mv = holdings_agg[ticker] * current_prices[ticker]
                market_values[ticker] = mv
            else:
                print(f"WARNING: No price for {ticker}, excluding from weights")

        self.market_values = pd.Series(market_values)
        self.gmv = self.market_values.sum()  # Gross Market Value
        self.weights = self.market_values / self.gmv

        print(f"\nPortfolio Weights:")
        for ticker, weight in self.weights.sort_values(ascending=False).items():
            print(f"  {ticker}: {weight:.1%} (${self.market_values[ticker]:,.0f})")

    def calculate_factor_exposures(self, window: int = 252):
        """
        Calculate factor loadings (betas) for each position.

        Args:
            window: Rolling window for regression (default: 252 days = 1 year)
        """
        print("\n" + "=" * 50)
        print("CALCULATING FACTOR EXPOSURES")
        print("=" * 50)

        # Only use tickers we have returns for
        available_tickers = [t for t in self.weights.index if t in self.returns.columns]
        returns_subset = self.returns[available_tickers]

        # Estimate factor loadings
        self.factor_loadings = estimate_factor_loadings(
            returns_subset,
            self.factor_returns,
            window=window
        )

        # Calculate portfolio-level factor exposures (weighted sum of betas)
        betas = self.factor_loadings['betas']
        weights_aligned = self.weights.reindex(betas.index).fillna(0)

        self.portfolio_betas = (betas.T * weights_aligned).T.sum()

        print(f"\n=== Portfolio Factor Exposures ===")
        for factor, beta in self.portfolio_betas.items():
            print(f"  {factor}: {beta:.3f}")

        return self

    def decompose_returns(self):
        """Decompose returns into systematic and idiosyncratic components."""
        print("\n" + "=" * 50)
        print("DECOMPOSING RETURNS")
        print("=" * 50)

        available_tickers = [t for t in self.weights.index if t in self.returns.columns]
        returns_subset = self.returns[available_tickers]

        self.decomposition = decompose_returns(
            returns_subset,
            self.factor_returns,
            self.factor_loadings['betas']
        )

        # Calculate portfolio-level decomposition
        weights_aligned = self.weights.reindex(available_tickers).fillna(0)

        # Portfolio systematic returns
        self.portfolio_systematic = (self.decomposition['systematic'] * weights_aligned).sum(axis=1)

        # Portfolio idiosyncratic returns
        self.portfolio_idiosyncratic = (self.decomposition['idiosyncratic'] * weights_aligned).sum(axis=1)

        # Portfolio total returns
        self.portfolio_returns = (returns_subset * weights_aligned).sum(axis=1)

        print(f"Systematic return (annualized): {self.portfolio_systematic.mean() * 252:.2%}")
        print(f"Idiosyncratic return (annualized): {self.portfolio_idiosyncratic.mean() * 252:.2%}")

        return self

    def calculate_metrics(self) -> dict:
        """
        Calculate all portfolio metrics.

        Returns dict with:
        - sharpe: Sharpe Ratio (annualized)
        - information_ratio: Information Ratio (idiosyncratic Sharpe)
        - total_vol: Total portfolio volatility
        - factor_vol: Factor (systematic) volatility
        - idio_vol: Idiosyncratic volatility
        - pct_idio_var: Percentage idiosyncratic variance (portfolio "purity")
        - factor_exposures: Dollar and percentage exposures to each factor
        """
        print("\n" + "=" * 50)
        print("CALCULATING METRICS")
        print("=" * 50)

        # Get risk-free rate
        rf_daily = self.factor_returns['RF'].mean() if 'RF' in self.factor_returns.columns else 0

        # === Sharpe Ratio ===
        excess_returns = self.portfolio_returns - rf_daily
        sharpe_daily = excess_returns.mean() / excess_returns.std()
        sharpe_annual = sharpe_daily * np.sqrt(252)

        # === Information Ratio (idiosyncratic Sharpe) ===
        ir_daily = self.portfolio_idiosyncratic.mean() / self.portfolio_idiosyncratic.std()
        ir_annual = ir_daily * np.sqrt(252)

        # === Volatility Decomposition ===
        total_vol = self.portfolio_returns.std() * np.sqrt(252)
        factor_vol = self.portfolio_systematic.std() * np.sqrt(252)
        idio_vol = self.portfolio_idiosyncratic.std() * np.sqrt(252)

        # === Percentage Idiosyncratic Variance ===
        # Formula: (idio_variance) / (total_variance)
        total_var = self.portfolio_returns.var()
        idio_var = self.portfolio_idiosyncratic.var()
        pct_idio_var = idio_var / total_var if total_var > 0 else 0

        # === Factor Exposures (dollar and percentage) ===
        factor_exposures = {}
        for factor in self.portfolio_betas.index:
            dollar_exposure = self.portfolio_betas[factor] * self.gmv
            pct_exposure = self.portfolio_betas[factor]
            factor_exposures[factor] = {
                'beta': self.portfolio_betas[factor],
                'dollar': dollar_exposure,
                'pct_gmv': pct_exposure
            }

        # === Benchmark Comparison ===
        if self.benchmark_returns is not None:
            bench_ret = self.benchmark_returns[self.benchmark].reindex(self.portfolio_returns.index).dropna()
            portfolio_beta_to_benchmark = (
                self.portfolio_returns.cov(bench_ret) / bench_ret.var()
            )
            excess_vs_benchmark = self.portfolio_returns.mean() - bench_ret.mean()
        else:
            portfolio_beta_to_benchmark = None
            excess_vs_benchmark = None

        self.metrics = {
            'sharpe': sharpe_annual,
            'information_ratio': ir_annual,
            'total_vol': total_vol,
            'factor_vol': factor_vol,
            'idio_vol': idio_vol,
            'pct_idio_var': pct_idio_var,
            'factor_exposures': factor_exposures,
            'portfolio_beta': portfolio_beta_to_benchmark,
            'excess_return': excess_vs_benchmark,
            'gmv': self.gmv,
            'num_positions': len(self.weights)
        }

        # Print summary
        print(f"\n=== PORTFOLIO SUMMARY ===")
        print(f"Positions: {len(self.weights)}")
        print(f"GMV: ${self.gmv:,.0f}")
        print(f"\n--- Risk Metrics ---")
        print(f"Total Volatility: {total_vol:.1%}")
        print(f"Factor Volatility: {factor_vol:.1%}")
        print(f"Idio Volatility: {idio_vol:.1%}")
        print(f"% Idiosyncratic Variance: {pct_idio_var:.1%}")
        print(f"\n--- Performance ---")
        print(f"Sharpe Ratio: {sharpe_annual:.2f}")
        print(f"Information Ratio: {ir_annual:.2f}")
        if portfolio_beta_to_benchmark is not None:
            print(f"Beta to {self.benchmark}: {portfolio_beta_to_benchmark:.2f}")

        # Interpret idiosyncratic variance
        if pct_idio_var >= 0.75:
            print(f"\n[GOOD] High idiosyncratic variance ({pct_idio_var:.0%}) - "
                  "portfolio driven by stock selection, not factors")
        elif pct_idio_var >= 0.50:
            print(f"\n[MODERATE] Moderate idiosyncratic variance ({pct_idio_var:.0%}) - "
                  "mixed factor and stock-specific risk")
        else:
            print(f"\n[LOW] Low idiosyncratic variance ({pct_idio_var:.0%}) - "
                  "portfolio heavily exposed to factor risk")

        return self.metrics

    def get_position_details(self) -> pd.DataFrame:
        """Get detailed analysis for each position."""
        betas = self.factor_loadings['betas']
        details = []

        for ticker in self.weights.index:
            if ticker not in betas.index:
                continue

            detail = {
                'ticker': ticker,
                'shares': self.holdings[self.holdings['ticker'] == ticker]['shares'].sum(),
                'market_value': self.market_values.get(ticker, 0),
                'weight': self.weights.get(ticker, 0),
                'beta_mkt': betas.loc[ticker, 'Mkt-RF'] if 'Mkt-RF' in betas.columns else np.nan,
                'beta_smb': betas.loc[ticker, 'SMB'] if 'SMB' in betas.columns else np.nan,
                'beta_hml': betas.loc[ticker, 'HML'] if 'HML' in betas.columns else np.nan,
                'beta_mom': betas.loc[ticker, 'Mom'] if 'Mom' in betas.columns else np.nan,
                'r_squared': self.factor_loadings['r_squared'].get(ticker, np.nan),
                'idio_vol': self.factor_loadings['idio_vol'].get(ticker, np.nan),
            }
            details.append(detail)

        return pd.DataFrame(details).set_index('ticker')

    def run_full_analysis(self):
        """Run complete portfolio analysis pipeline."""
        self.load_data()
        self.calculate_factor_exposures()
        self.decompose_returns()
        self.calculate_metrics()
        return self


# Quick test
if __name__ == "__main__":
    # Create a test portfolio CSV
    import os

    test_csv = "test_portfolio.csv"
    test_data = """Ticker,Shares,BuyDate
AAPL,100,2024-01-15
MSFT,50,2024-02-20
GOOGL,30,2024-03-01
NVDA,25,2024-01-10
"""
    with open(test_csv, 'w') as f:
        f.write(test_data)

    # Run analysis
    pf = Portfolio(test_csv, benchmark='SPY')
    pf.run_full_analysis()

    # Show position details
    print("\n=== POSITION DETAILS ===")
    print(pf.get_position_details())

    # Cleanup
    os.remove(test_csv)
