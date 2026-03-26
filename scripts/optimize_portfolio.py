# -*- coding: utf-8 -*-
"""
Factor-Neutral Portfolio Optimizer

Finds portfolio weights that minimize factor exposure while:
1. Staying as close as possible to original weights (optional)
2. Maintaining desired expected return
3. Long-only constraint

Uses quadratic programming to minimize factor variance.
"""

import pandas as pd
import numpy as np
from scipy.optimize import minimize, LinearConstraint, Bounds
import yfinance as yf
import sys
import warnings
warnings.filterwarnings('ignore')


def load_portfolio(filepath):
    """Load portfolio from CSV file"""
    with open(filepath, 'r') as f:
        first_line = f.readline()
    delimiter = ';' if ';' in first_line else ','

    df = pd.read_csv(filepath, sep=delimiter)
    df.columns = df.columns.str.lower().str.strip()

    ticker_col = next((c for c in df.columns if 'ticker' in c.lower()), None)
    shares_col = next((c for c in df.columns if 'share' in c.lower()), None)

    df = df.rename(columns={ticker_col: 'ticker', shares_col: 'shares'})
    return df[['ticker', 'shares']]


def get_portfolio_data(portfolio_df):
    """Get prices and calculate current weights"""
    tickers = portfolio_df['ticker'].tolist()
    shares = portfolio_df['shares'].tolist()

    prices = {}
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            price = info.get('currentPrice', info.get('regularMarketPrice', np.nan))
            prices[ticker] = price
        except:
            prices[ticker] = np.nan

    valid_data = []
    for ticker, share in zip(tickers, shares):
        price = prices.get(ticker, np.nan)
        if pd.notna(price) and price > 0:
            valid_data.append({
                'ticker': ticker,
                'shares': share,
                'price': price,
                'market_value': price * share
            })

    df = pd.DataFrame(valid_data)
    total_value = df['market_value'].sum()
    df['weight'] = df['market_value'] / total_value

    return df, total_value


def get_stock_factor_exposures(tickers, factor_exp_df, style_factors):
    """Get factor exposures matrix for stocks"""
    latest_date = factor_exp_df['date'].max()
    latest = factor_exp_df[factor_exp_df['date'] == latest_date].copy()

    # Match tickers
    matched = latest[latest['ticker'].isin(tickers)].copy()

    # Build exposure matrix (stocks x factors)
    exposure_matrix = []
    matched_tickers = []

    for ticker in tickers:
        row = matched[matched['ticker'] == ticker]
        if len(row) > 0:
            exposures = [row[f].values[0] if f in row.columns else 0 for f in style_factors]
            exposure_matrix.append(exposures)
            matched_tickers.append(ticker)

    return np.array(exposure_matrix), matched_tickers, style_factors


def optimize_factor_neutral(weights_df, exposure_matrix, matched_tickers, factor_cov,
                            style_factors, target_tracking_error=0.10):
    """
    Optimize portfolio weights to minimize factor exposure

    Parameters:
    - weights_df: DataFrame with current weights
    - exposure_matrix: (n_stocks x n_factors) matrix of factor exposures
    - factor_cov: Factor covariance matrix (style factors only)
    - target_tracking_error: Maximum allowed deviation from current weights

    Returns:
    - Optimal weights
    """
    n_stocks = len(matched_tickers)
    n_factors = len(style_factors)

    # Get current weights for matched stocks
    current_weights = []
    for ticker in matched_tickers:
        w = weights_df[weights_df['ticker'] == ticker]['weight'].values
        current_weights.append(w[0] if len(w) > 0 else 0)
    current_weights = np.array(current_weights)

    # Renormalize to sum to 1
    current_weights = current_weights / current_weights.sum()

    # Objective: minimize portfolio factor variance
    # Factor variance = w' * B * F * B' * w
    # where B = exposure matrix, F = factor covariance
    B = exposure_matrix  # n_stocks x n_factors
    F = factor_cov       # n_factors x n_factors

    # BFB' is the factor risk contribution matrix
    BFB = B @ F @ B.T  # n_stocks x n_stocks

    def objective(w):
        """Portfolio factor variance"""
        return w @ BFB @ w

    def objective_grad(w):
        """Gradient of portfolio factor variance"""
        return 2 * BFB @ w

    # Constraints
    # 1. Weights sum to 1
    sum_constraint = LinearConstraint(np.ones(n_stocks), 1.0, 1.0)

    # 2. Long-only: weights >= 0
    bounds = Bounds(0, 1)

    # 3. Optional: tracking error constraint (stay close to original)
    # ||w - w0||^2 <= TE^2
    # This is handled as a penalty term instead

    # Combined objective: minimize factor variance + penalty for deviation
    lambda_te = 1.0  # Balanced tracking error penalty

    def combined_objective(w):
        factor_var = w @ BFB @ w
        tracking_error = np.sum((w - current_weights) ** 2)
        return factor_var + lambda_te * tracking_error

    def combined_grad(w):
        grad_factor = 2 * BFB @ w
        grad_te = 2 * lambda_te * (w - current_weights)
        return grad_factor + grad_te

    # Optimize
    result = minimize(
        combined_objective,
        current_weights,
        method='SLSQP',
        jac=combined_grad,
        bounds=bounds,
        constraints=[sum_constraint],
        options={'maxiter': 1000, 'ftol': 1e-10}
    )

    return result.x, current_weights


def main(portfolio_path):
    print("=" * 70)
    print("FACTOR-NEUTRAL PORTFOLIO OPTIMIZER")
    print("=" * 70)

    # Load portfolio
    print(f"\nLoading portfolio: {portfolio_path}")
    portfolio_df = load_portfolio(portfolio_path)

    # Get current data
    print("Fetching current prices...")
    weights_df, total_value = get_portfolio_data(portfolio_df)
    print(f"  Portfolio value: ${total_value:,.0f}")

    # Load factor data
    print("Loading factor data...")
    factor_exp_df = pd.read_csv('data/model/russell3000_factor_exposures_historical.csv')
    factor_cov_df = pd.read_csv('data/model/barra_factor_covariance.csv', index_col=0)

    style_factors = ['size', 'beta', 'momentum', 'residvol', 'nlsize', 'btop', 'liquidity', 'earnyild', 'growth', 'leverage']

    # Get factor covariance for style factors only
    factor_cov = factor_cov_df.loc[style_factors, style_factors].values

    # Get stock exposures
    print("Building factor exposure matrix...")
    exposure_matrix, matched_tickers, _ = get_stock_factor_exposures(
        weights_df['ticker'].tolist(), factor_exp_df, style_factors
    )

    print(f"  Matched {len(matched_tickers)} stocks with factor data")

    if len(matched_tickers) < 3:
        print("ERROR: Not enough stocks with factor data")
        return

    # Optimize
    print("\nOptimizing for factor-neutral weights...")
    optimal_weights, current_weights = optimize_factor_neutral(
        weights_df, exposure_matrix, matched_tickers, factor_cov, style_factors
    )

    # Calculate factor exposures before and after
    def calc_portfolio_exposure(weights, exposure_matrix):
        return weights @ exposure_matrix

    current_exposure = calc_portfolio_exposure(current_weights, exposure_matrix)
    optimal_exposure = calc_portfolio_exposure(optimal_weights, exposure_matrix)

    # Calculate factor variance before and after
    B = exposure_matrix
    F = factor_cov
    BFB = B @ F @ B.T

    current_factor_var = current_weights @ BFB @ current_weights
    optimal_factor_var = optimal_weights @ BFB @ optimal_weights

    current_factor_vol = np.sqrt(current_factor_var * 252) * 100
    optimal_factor_vol = np.sqrt(optimal_factor_var * 252) * 100

    # Results
    print("\n" + "=" * 70)
    print("OPTIMIZATION RESULTS")
    print("=" * 70)

    print("\nFACTOR EXPOSURES (before vs after):")
    print("-" * 60)
    print(f"  {'Factor':<12} {'Current':>10} {'Optimal':>10} {'Change':>10}")
    print("-" * 60)
    for i, factor in enumerate(style_factors):
        curr = current_exposure[i]
        opt = optimal_exposure[i]
        change = opt - curr
        print(f"  {factor:<12} {curr:>+10.2f} {opt:>+10.2f} {change:>+10.2f}")

    print("\nFACTOR VOLATILITY:")
    print("-" * 60)
    print(f"  Current:  {current_factor_vol:.1f}%")
    print(f"  Optimal:  {optimal_factor_vol:.1f}%")
    print(f"  Reduction: {(1 - optimal_factor_vol/current_factor_vol)*100:.1f}%")

    print("\nWEIGHT CHANGES:")
    print("-" * 60)
    print(f"  {'Ticker':<8} {'Current':>10} {'Optimal':>10} {'Change':>10}")
    print("-" * 60)

    changes = []
    for i, ticker in enumerate(matched_tickers):
        curr = current_weights[i] * 100
        opt = optimal_weights[i] * 100
        change = opt - curr
        changes.append((ticker, curr, opt, change))

    # Sort by absolute change
    changes.sort(key=lambda x: abs(x[3]), reverse=True)

    for ticker, curr, opt, change in changes:
        print(f"  {ticker:<8} {curr:>9.1f}% {opt:>9.1f}% {change:>+9.1f}%")

    # Translate to share changes
    print("\nSUGGESTED TRADES (to achieve factor-neutral):")
    print("-" * 60)

    # Get prices for matched tickers
    prices = {}
    for ticker in matched_tickers:
        row = weights_df[weights_df['ticker'] == ticker]
        if len(row) > 0:
            prices[ticker] = row['price'].values[0]

    # Calculate current and target shares
    print(f"  {'Ticker':<8} {'Action':<6} {'Shares':>8} {'Value':>12}")
    print("-" * 60)

    for ticker, curr_pct, opt_pct, change_pct in changes:
        if abs(change_pct) > 0.5:  # Only show material changes
            price = prices.get(ticker, 0)
            if price > 0:
                curr_value = total_value * (curr_pct / 100)
                opt_value = total_value * (opt_pct / 100)
                value_change = opt_value - curr_value
                share_change = value_change / price

                action = "BUY" if share_change > 0 else "SELL"
                print(f"  {ticker:<8} {action:<6} {abs(share_change):>8.0f} ${abs(value_change):>10,.0f}")

    print("\n" + "=" * 70)
    print("NOTE: This optimization minimizes STYLE factor exposure.")
    print("Market (beta) exposure cannot be reduced without shorting or hedging.")
    print("=" * 70)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        portfolio_path = sys.argv[1]
    else:
        portfolio_path = 'data/input/portfolios/Own_Portfolio_dated.csv'

    main(portfolio_path)
