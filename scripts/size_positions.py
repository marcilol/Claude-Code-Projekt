# -*- coding: utf-8 -*-
"""
Alpha Sizing Tool - Chapter 6 Implementation
From "Advanced Portfolio Management" by Giuseppe Paleologo

Implements four sizing methods:
1. Proportional: NMV = κ × α
2. Risk Parity: NMV = κ × α / σ
3. Mean-Variance: NMV = κ × α / σ²
4. Shrunk Mean-Variance: NMV = κ × α / (p × σ² + (1-p) × σ²_sector)

Includes backtesting to compare method performance.
"""

import pandas as pd
import numpy as np
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

    if ticker_col is None or shares_col is None:
        raise ValueError("Could not find ticker or shares columns")

    df = df.rename(columns={ticker_col: 'ticker', shares_col: 'shares'})
    return df[['ticker', 'shares']]


def compute_idiosyncratic_volatility(tickers, factor_exp_df, factor_ret_df, end_date):
    """
    Compute stock-level idiosyncratic volatility from Barra model residuals.

    ε_i,t = r_i,t - Σ β_i,k × f_k,t
    σ_idio = std(ε) × √252
    """
    # Filter to dates up to end_date for point-in-time calculation
    factor_exp_df = factor_exp_df[factor_exp_df['date'] <= end_date].copy()
    factor_ret_df = factor_ret_df[factor_ret_df.index <= end_date].copy()

    # Style factors used in the model
    style_factors = ['size', 'beta', 'momentum', 'residvol', 'nlsize', 'btop', 'liquidity', 'earnyild', 'growth', 'leverage']

    # Industry factors from factor returns
    industry_factors = [c for c in factor_ret_df.columns
                        if c not in style_factors + ['Country']]

    idio_vol = {}

    for ticker in tickers:
        stock_data = factor_exp_df[factor_exp_df['ticker'] == ticker].copy()

        if len(stock_data) < 20:  # Need minimum history
            idio_vol[ticker] = np.nan
            continue

        stock_data = stock_data.sort_values('date')

        # Get stock returns
        stock_returns = stock_data.set_index('date')['return']

        # Get factor exposures for this stock
        stock_exposures = stock_data.set_index('date')[style_factors]

        # Get sector for industry dummy
        sector = stock_data['sector'].iloc[0]

        # Compute predicted returns from factors
        residuals = []

        for date in stock_returns.index:
            if date not in factor_ret_df.index:
                continue

            r_actual = stock_returns.loc[date]

            # Factor returns for this date
            f_ret = factor_ret_df.loc[date]

            # Predicted return = market + industry + style factors
            r_predicted = f_ret.get('Country', 0)

            # Add industry contribution
            if sector in f_ret.index:
                r_predicted += f_ret[sector]

            # Add style factor contributions
            if date in stock_exposures.index:
                for factor in style_factors:
                    if factor in f_ret.index and factor in stock_exposures.columns:
                        beta = stock_exposures.loc[date, factor]
                        if pd.notna(beta):
                            r_predicted += beta * f_ret[factor]

            residual = r_actual - r_predicted
            residuals.append(residual)

        if len(residuals) >= 20:
            idio_vol[ticker] = np.std(residuals) * np.sqrt(252)
        else:
            idio_vol[ticker] = np.nan

    return idio_vol


def get_sector_volatility(idio_vols, stock_sectors):
    """Get sector-level average idiosyncratic volatility for shrunk mean-variance.

    Computes median idio vol per sector from stock-level estimates.
    This is the correct shrinkage target (stock-specific vol scale, ~20-60%),
    not factor return vol (~1-3%) which would make shrinkage ineffective.
    """
    from collections import defaultdict
    sector_stocks = defaultdict(list)
    for ticker, sector in stock_sectors.items():
        vol = idio_vols.get(ticker)
        if vol is not None and pd.notna(vol) and vol > 0:
            sector_stocks[sector].append(vol)

    sector_vol = {}
    for sector, vols in sector_stocks.items():
        if vols:
            sector_vol[sector] = float(np.median(vols))

    return sector_vol


def get_stock_sectors(tickers, factor_exp_df, as_of_date):
    """Get sector for each stock as of a given date"""
    latest = factor_exp_df[factor_exp_df['date'] <= as_of_date].copy()
    latest = latest.sort_values('date').groupby('ticker').last().reset_index()

    sector_map = dict(zip(latest['ticker'], latest['sector']))
    return {t: sector_map.get(t, 'Unknown') for t in tickers}


def size_proportional(alphas, target_gmv):
    """
    Method 1 - Proportional (RECOMMENDED):
    NMV_i = κ × α_i

    Simple and robust. Empirically best Sharpe ratio.
    """
    # Only positive alphas for long-only
    alphas_positive = {k: max(v, 0) for k, v in alphas.items() if pd.notna(v)}

    if sum(alphas_positive.values()) == 0:
        return {k: target_gmv / len(alphas_positive) for k in alphas_positive}

    # Scale factor κ so sum of NMV = target_gmv
    total_alpha = sum(alphas_positive.values())
    kappa = target_gmv / total_alpha

    return {k: kappa * v for k, v in alphas_positive.items()}


def size_risk_parity(alphas, idio_vols, target_gmv):
    """
    Method 2 - Risk Parity:
    NMV_i = κ × α_i / σ_i

    Scales down high-volatility positions.
    """
    nmv = {}
    for ticker, alpha in alphas.items():
        if pd.notna(alpha) and alpha > 0 and pd.notna(idio_vols.get(ticker)):
            sigma = idio_vols[ticker]
            if sigma > 0:
                nmv[ticker] = alpha / sigma
            else:
                nmv[ticker] = 0
        else:
            nmv[ticker] = 0

    # Scale to target GMV
    total = sum(nmv.values())
    if total > 0:
        kappa = target_gmv / total
        return {k: v * kappa for k, v in nmv.items()}
    else:
        return {k: target_gmv / len(nmv) for k in nmv}


def size_mean_variance(alphas, idio_vols, target_gmv):
    """
    Method 3 - Mean-Variance:
    NMV_i = κ × α_i / σ_i²

    Classic Markowitz. Heavily penalizes high volatility.
    Often WORSE than simpler methods due to estimation error.
    """
    nmv = {}
    for ticker, alpha in alphas.items():
        if pd.notna(alpha) and alpha > 0 and pd.notna(idio_vols.get(ticker)):
            sigma = idio_vols[ticker]
            if sigma > 0:
                nmv[ticker] = alpha / (sigma ** 2)
            else:
                nmv[ticker] = 0
        else:
            nmv[ticker] = 0

    # Scale to target GMV
    total = sum(nmv.values())
    if total > 0:
        kappa = target_gmv / total
        return {k: v * kappa for k, v in nmv.items()}
    else:
        return {k: target_gmv / len(nmv) for k in nmv}


def size_shrunk_mv(alphas, idio_vols, sector_vols, stock_sectors, target_gmv, shrink=0.75):
    """
    Method 4 - Shrinked Mean-Variance:
    NMV_i = κ × α_i / (p × σ_i² + (1-p) × σ²_sector)

    Shrinks individual volatility toward sector average.
    Reduces estimation error impact.
    """
    nmv = {}
    for ticker, alpha in alphas.items():
        if pd.notna(alpha) and alpha > 0 and pd.notna(idio_vols.get(ticker)):
            sigma = idio_vols[ticker]
            sector = stock_sectors.get(ticker, 'Unknown')
            sigma_sector = sector_vols.get(sector, sigma)  # Fall back to stock vol

            if sigma > 0:
                # Shrunk variance
                shrunk_var = shrink * (sigma ** 2) + (1 - shrink) * (sigma_sector ** 2)
                nmv[ticker] = alpha / shrunk_var
            else:
                nmv[ticker] = 0
        else:
            nmv[ticker] = 0

    # Scale to target GMV
    total = sum(nmv.values())
    if total > 0:
        kappa = target_gmv / total
        return {k: v * kappa for k, v in nmv.items()}
    else:
        return {k: target_gmv / len(nmv) for k in nmv}


def compute_weights(nmv_dict):
    """Convert NMV to weights"""
    total = sum(nmv_dict.values())
    if total > 0:
        return {k: v / total for k, v in nmv_dict.items()}
    else:
        n = len(nmv_dict)
        return {k: 1/n for k in nmv_dict}


def backtest_weights(weights, factor_exp_df, start_date, end_date):
    """
    Compute actual portfolio return from start_date to end_date
    using the given weights.

    Returns:
    - total_return: cumulative portfolio return
    - daily_returns: series of daily portfolio returns
    """
    # Filter data to the backtest period
    bt_data = factor_exp_df[
        (factor_exp_df['date'] > start_date) &
        (factor_exp_df['date'] <= end_date)
    ].copy()

    dates = sorted(bt_data['date'].unique())

    portfolio_returns = []

    for date in dates:
        day_data = bt_data[bt_data['date'] == date]

        daily_return = 0
        total_weight = 0

        for ticker, weight in weights.items():
            stock_ret = day_data[day_data['ticker'] == ticker]['return']
            if len(stock_ret) > 0:
                daily_return += weight * stock_ret.iloc[0]
                total_weight += weight

        # Normalize if some stocks missing; skip day if no coverage
        if total_weight > 0:
            daily_return = daily_return / total_weight
            portfolio_returns.append({'date': date, 'return': daily_return})

    returns_df = pd.DataFrame(portfolio_returns)

    if len(returns_df) > 0:
        # Cumulative return
        cumulative = (1 + returns_df['return']).prod() - 1

        # Annualized volatility
        vol = returns_df['return'].std() * np.sqrt(252)

        # Sharpe (assuming 0 risk-free rate for simplicity)
        mean_ret = returns_df['return'].mean() * 252
        sharpe = mean_ret / vol if vol > 0 else 0

        return {
            'total_return': cumulative,
            'annualized_return': mean_ret,
            'volatility': vol,
            'sharpe': sharpe,
            'n_days': len(returns_df)
        }
    else:
        return {
            'total_return': 0,
            'annualized_return': 0,
            'volatility': 0,
            'sharpe': 0,
            'n_days': 0
        }


def main(portfolio_path, decision_date='2025-07-01', end_date='2025-12-31',
         target_gmv=100000, expected_return=0.30, horizon_months=6):
    """
    Main function to run alpha sizing and backtesting.

    Parameters:
    - portfolio_path: Path to portfolio CSV
    - decision_date: Date to make sizing decision
    - end_date: End date for backtest
    - target_gmv: Target gross market value
    - expected_return: Assumed expected return for all stocks
    - horizon_months: Investment horizon in months
    """
    print("=" * 70)
    print("ALPHA SIZING - Chapter 6 Implementation")
    print("=" * 70)

    # Load portfolio
    print(f"\nLoading portfolio: {portfolio_path}")
    portfolio_df = load_portfolio(portfolio_path)
    tickers = portfolio_df['ticker'].tolist()
    print(f"  Found {len(tickers)} positions")

    # Load factor data
    print("\nLoading factor model data...")
    factor_exp_df = pd.read_csv('data/model/russell3000_factor_exposures_historical.csv')
    factor_ret_df = pd.read_csv('data/model/barra_factor_returns.csv', index_col=0)

    # Filter to tickers in portfolio that exist in our data
    available_tickers = set(factor_exp_df['ticker'].unique())
    valid_tickers = [t for t in tickers if t in available_tickers]
    missing_tickers = [t for t in tickers if t not in available_tickers]

    print(f"  Matched {len(valid_tickers)} stocks with factor data")
    if missing_tickers:
        print(f"  Missing: {missing_tickers}")

    # Compute idiosyncratic volatility as of decision date
    print(f"\nComputing idiosyncratic volatility (as of {decision_date})...")
    idio_vols = compute_idiosyncratic_volatility(
        valid_tickers, factor_exp_df, factor_ret_df, decision_date
    )

    valid_idio = {k: v for k, v in idio_vols.items() if pd.notna(v)}
    print(f"  Computed idio_vol for {len(valid_idio)} stocks")

    # Get sector info
    stock_sectors = get_stock_sectors(valid_tickers, factor_exp_df, decision_date)
    sector_vols = get_sector_volatility(idio_vols, stock_sectors)

    # Compute alphas (uniform expected return for now)
    # Convert 6-month return to annualized
    annualized_alpha = expected_return * (12 / horizon_months)
    alphas = {t: annualized_alpha for t in valid_tickers}

    print(f"\nSizing parameters:")
    print(f"  Expected return: {expected_return*100:.0f}% over {horizon_months} months")
    print(f"  Annualized alpha: {annualized_alpha*100:.0f}%")
    print(f"  Target GMV: ${target_gmv:,.0f}")
    print(f"  Decision date: {decision_date}")
    print(f"  Backtest end: {end_date}")

    # Apply four sizing methods
    print("\n" + "=" * 70)
    print("SIZING METHODS")
    print("=" * 70)

    methods = {}

    # Method 1: Proportional
    nmv_prop = size_proportional(alphas, target_gmv)
    methods['Proportional'] = compute_weights(nmv_prop)

    # Method 2: Risk Parity
    nmv_rp = size_risk_parity(alphas, idio_vols, target_gmv)
    methods['Risk Parity'] = compute_weights(nmv_rp)

    # Method 3: Mean-Variance
    nmv_mv = size_mean_variance(alphas, idio_vols, target_gmv)
    methods['Mean-Variance'] = compute_weights(nmv_mv)

    # Method 4: Shrunk MV (75% shrinkage)
    nmv_smv = size_shrunk_mv(alphas, idio_vols, sector_vols, stock_sectors, target_gmv, shrink=0.75)
    methods['Shrunk MV'] = compute_weights(nmv_smv)

    # Display weights comparison
    print("\nWEIGHTS BY METHOD:")
    print("-" * 70)

    # Build comparison table
    weight_data = []
    for ticker in sorted(valid_tickers):
        row = {
            'Ticker': ticker,
            'Idio Vol': f"{idio_vols.get(ticker, np.nan)*100:.1f}%" if pd.notna(idio_vols.get(ticker)) else "N/A",
            'Sector': stock_sectors.get(ticker, 'Unknown')[:12],
        }
        for method_name, weights in methods.items():
            row[method_name[:8]] = f"{weights.get(ticker, 0)*100:.1f}%"
        weight_data.append(row)

    weight_df = pd.DataFrame(weight_data)
    print(weight_df.to_string(index=False))

    # Show concentration metrics
    print("\n\nCONCENTRATION METRICS:")
    print("-" * 70)
    print(f"{'Method':<20} {'Top 5 Wt':<12} {'HHI':<12} {'# Positions':<12}")
    print("-" * 70)

    for method_name, weights in methods.items():
        sorted_weights = sorted(weights.values(), reverse=True)
        top5 = sum(sorted_weights[:5])
        hhi = sum(w**2 for w in weights.values())
        n_pos = sum(1 for w in weights.values() if w > 0.001)
        print(f"{method_name:<20} {top5*100:>8.1f}%    {hhi:>8.4f}      {n_pos:>6}")

    # Backtest each method
    print("\n" + "=" * 70)
    print("BACKTEST RESULTS")
    print(f"Period: {decision_date} to {end_date}")
    print("=" * 70)

    results = {}
    for method_name, weights in methods.items():
        bt_result = backtest_weights(weights, factor_exp_df, decision_date, end_date)
        results[method_name] = bt_result

    print(f"\n{'Method':<20} {'Return':<12} {'Ann. Vol':<12} {'Sharpe':<12} {'Days':<8}")
    print("-" * 70)

    for method_name, res in results.items():
        print(f"{method_name:<20} {res['total_return']*100:>8.2f}%    "
              f"{res['volatility']*100:>8.2f}%    {res['sharpe']:>8.2f}      {res['n_days']:>6}")

    # Determine winner
    best_method = max(results.items(), key=lambda x: x[1]['total_return'])
    best_sharpe = max(results.items(), key=lambda x: x[1]['sharpe'])

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\n  Best Return: {best_method[0]} ({best_method[1]['total_return']*100:.2f}%)")
    print(f"  Best Sharpe: {best_sharpe[0]} ({best_sharpe[1]['sharpe']:.2f})")

    # Interpretation
    print("\n  Chapter 6 Insight:")
    print("  Paleologo found Proportional sizing (NMV ~ alpha) empirically outperforms")
    print("  complex methods because estimation error in volatility hurts MV-based")
    print("  approaches. With uniform alphas, methods differ only by volatility weighting.")

    print("\n" + "=" * 70)

    return methods, results


if __name__ == '__main__':
    if len(sys.argv) > 1:
        portfolio_path = sys.argv[1]
    else:
        portfolio_path = 'data/input/portfolios/Own_Portfolio_dated.csv'

    # Parse optional arguments
    decision_date = '2025-07-01'
    end_date = '2025-12-31'
    target_gmv = 100000

    for arg in sys.argv[2:]:
        if arg.startswith('--decision='):
            decision_date = arg.split('=')[1]
        elif arg.startswith('--end='):
            end_date = arg.split('=')[1]
        elif arg.startswith('--gmv='):
            target_gmv = float(arg.split('=')[1])

    main(portfolio_path, decision_date, end_date, target_gmv)
