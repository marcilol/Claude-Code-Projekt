# -*- coding: utf-8 -*-
"""
Portfolio Risk Decomposition using Barra Factor Model

Decomposes portfolio risk into:
1. Factor risk (systematic) - driven by exposure to style/industry factors
2. Idiosyncratic risk (specific) - stock-specific risk

Uses the estimated factor covariance matrix from run_barra_model.py
"""

import os
import pandas as pd
import numpy as np
import sys
import warnings
warnings.filterwarnings('ignore')


def load_portfolio(filepath):
    """Load portfolio from CSV file"""
    # Read lines, skipping git merge conflict markers
    with open(filepath, 'r') as f:
        lines = [line for line in f
                 if not line.startswith(('<<<<<<<', '=======', '>>>>>>>'))]

    first_line = lines[0] if lines else ''
    delimiter = ';' if ';' in first_line else ','

    from io import StringIO
    df = pd.read_csv(StringIO(''.join(lines)), sep=delimiter)
    df = df.drop_duplicates()

    # Normalize column names
    df.columns = df.columns.str.lower().str.strip()

    # Find ticker column
    ticker_col = next((c for c in df.columns if 'ticker' in c.lower()), None)
    shares_col = next((c for c in df.columns if 'share' in c.lower()), None)

    if ticker_col is None or shares_col is None:
        raise ValueError("Could not find ticker or shares columns")

    df = df.rename(columns={ticker_col: 'ticker', shares_col: 'shares'})

    # Drop rows where ticker is a header repeat or non-string
    df = df[df['ticker'].apply(lambda x: isinstance(x, str) and x.lower() != 'ticker')]
    df['shares'] = pd.to_numeric(df['shares'], errors='coerce')
    df = df.dropna(subset=['shares'])

    return df[['ticker', 'shares']]


def get_portfolio_weights(portfolio_df):
    """Calculate portfolio weights based on current market values from DB"""
    import sqlite3
    db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'db', 'market_data.db')
    conn = sqlite3.connect(db_path)

    tickers = portfolio_df['ticker'].tolist()
    shares = portfolio_df['shares'].tolist()

    prices = {}
    for ticker in tickers:
        row = conn.execute(
            'SELECT close FROM daily_prices WHERE ticker=? ORDER BY date DESC LIMIT 1',
            (ticker,)).fetchone()
        prices[ticker] = row[0] if row else np.nan
    conn.close()

    # Calculate market values
    market_values = []
    valid_tickers = []
    valid_shares = []

    for ticker, share in zip(tickers, shares):
        price = prices.get(ticker, np.nan)
        if pd.notna(price) and price > 0:
            market_values.append(price * share)
            valid_tickers.append(ticker)
            valid_shares.append(share)

    total_value = sum(market_values)
    weights = [mv / total_value for mv in market_values]

    return pd.DataFrame({
        'ticker': valid_tickers,
        'shares': valid_shares,
        'market_value': market_values,
        'weight': weights
    })


def get_factor_exposures(tickers, factor_exposures_df):
    """Get factor exposures for portfolio stocks from the historical data"""
    # Use the most recent date's factor exposures
    latest_date = factor_exposures_df['date'].max()
    latest_exposures = factor_exposures_df[factor_exposures_df['date'] == latest_date].copy()

    # Match tickers
    exposures = latest_exposures[latest_exposures['ticker'].isin(tickers)]

    return exposures


def calculate_portfolio_factor_exposure(weights_df, exposures_df, style_factors, industry_factors):
    """Calculate weighted average factor exposures for the portfolio"""
    # Merge weights with exposures
    merged = weights_df.merge(exposures_df, on='ticker', how='inner')

    if len(merged) == 0:
        return None, None

    # Renormalize weights for matched stocks
    merged['weight'] = merged['weight'] / merged['weight'].sum()

    # Calculate weighted factor exposures
    portfolio_style = {}
    for factor in style_factors:
        if factor in merged.columns:
            portfolio_style[factor] = (merged['weight'] * merged[factor]).sum()
        else:
            portfolio_style[factor] = 0

    portfolio_industry = {}
    for industry in industry_factors:
        portfolio_industry[industry] = merged.loc[merged['sector'] == industry, 'weight'].sum()

    return portfolio_style, portfolio_industry


def calculate_factor_risk(portfolio_exposures, factor_cov, factor_names):
    """Calculate portfolio factor risk contribution"""
    # Build exposure vector in same order as covariance matrix
    exposure_vec = np.array([portfolio_exposures.get(f, 0) for f in factor_names])

    # Portfolio factor variance = x' * Cov * x
    factor_variance = exposure_vec @ factor_cov @ exposure_vec

    # Marginal contribution to risk
    marginal_contrib = factor_cov @ exposure_vec

    # Risk contribution by factor
    risk_contrib = exposure_vec * marginal_contrib

    return factor_variance, risk_contrib, exposure_vec


def compute_idiosyncratic_volatility(tickers, factor_exp_df, factor_ret_df):
    """
    Compute stock-level idiosyncratic volatility from Barra model residuals.

    ε_i,t = r_i,t - Σ β_i,k × f_k,t
    σ_idio = std(ε) × √252
    """
    style_factors = ['size', 'beta', 'momentum', 'residvol', 'nlsize', 'btop', 'liquidity', 'earnyild', 'growth', 'leverage']
    industry_factors = [c for c in factor_ret_df.columns
                        if c not in style_factors + ['Country']]

    idio_vol = {}

    for ticker in tickers:
        stock_data = factor_exp_df[factor_exp_df['ticker'] == ticker].copy()

        if len(stock_data) < 20:
            idio_vol[ticker] = np.nan
            continue

        stock_data = stock_data.sort_values('date')
        stock_returns = stock_data.set_index('date')['return']
        stock_exposures = stock_data.set_index('date')[style_factors]
        sector = stock_data['sector'].iloc[0]

        residuals = []

        for date in stock_returns.index:
            if date not in factor_ret_df.index:
                continue

            r_actual = stock_returns.loc[date]
            f_ret = factor_ret_df.loc[date]

            r_predicted = f_ret.get('Country', 0)

            if sector in f_ret.index:
                r_predicted += f_ret[sector]

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


def main(portfolio_path):
    print("=" * 70)
    print("PORTFOLIO RISK DECOMPOSITION - BARRA FACTOR MODEL")
    print("=" * 70)

    # Load portfolio
    print(f"\nLoading portfolio: {portfolio_path}")
    portfolio_df = load_portfolio(portfolio_path)
    print(f"  Found {len(portfolio_df)} positions")

    # Get current weights
    print("\nFetching current prices and calculating weights...")
    weights_df = get_portfolio_weights(portfolio_df)
    print(f"  Successfully priced {len(weights_df)} positions")
    print(f"  Total portfolio value: ${weights_df['market_value'].sum():,.0f}")

    # Load factor exposures
    print("\nLoading factor exposures...")
    factor_exp_df = pd.read_csv('data/model/russell3000_factor_exposures_historical.csv')

    # Load factor covariance
    print("Loading factor covariance matrix...")
    factor_cov_df = pd.read_csv('data/model/barra_factor_covariance.csv', index_col=0)

    # Load factor returns for context
    factor_ret_df = pd.read_csv('data/model/barra_factor_returns.csv', index_col=0)

    # Define factors
    style_factors = ['size', 'beta', 'momentum', 'residvol', 'nlsize', 'btop', 'liquidity', 'earnyild', 'growth', 'leverage']

    # Get industry factors from covariance matrix
    all_factors = factor_cov_df.columns.tolist()
    industry_factors = [f for f in all_factors if f not in style_factors + ['Country']]

    # Get exposures for portfolio stocks
    exposures_df = get_factor_exposures(weights_df['ticker'].tolist(), factor_exp_df)

    matched_tickers = set(exposures_df['ticker'].tolist())
    missing_tickers = set(weights_df['ticker'].tolist()) - matched_tickers

    print(f"\n  Matched {len(matched_tickers)} stocks with factor data")
    if missing_tickers:
        print(f"  Missing factor data for: {missing_tickers}")

    # Calculate portfolio factor exposures
    print("\nCalculating portfolio factor exposures...")
    style_exp, industry_exp = calculate_portfolio_factor_exposure(
        weights_df, exposures_df, style_factors, industry_factors
    )

    if style_exp is None:
        print("ERROR: No matching stocks found in factor database")
        return

    # Combine all exposures
    all_exposures = {'Country': 1.0}  # Market exposure = 1
    all_exposures.update({f: industry_exp.get(f, 0) for f in industry_factors})
    all_exposures.update(style_exp)

    # Calculate factor risk
    print("\nCalculating factor risk decomposition...")
    factor_names = factor_cov_df.columns.tolist()
    factor_cov = factor_cov_df.values

    factor_variance, risk_contrib, exposure_vec = calculate_factor_risk(
        all_exposures, factor_cov, factor_names
    )

    # Annualize (assuming daily data)
    factor_vol = np.sqrt(factor_variance) * np.sqrt(252) * 100

    # Results
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)

    # Top holdings
    print("\nTOP 10 HOLDINGS:")
    print("-" * 50)
    top_holdings = weights_df.nlargest(10, 'weight')
    for _, row in top_holdings.iterrows():
        print(f"  {row['ticker']:8s}  {row['weight']*100:5.1f}%  ${row['market_value']:,.0f}")

    # Style factor exposures
    print("\nSTYLE FACTOR EXPOSURES (z-scores):")
    print("-" * 50)
    for factor in style_factors:
        exp = style_exp.get(factor, 0)
        interpretation = ""
        interp_map = {
            'size': ("(large cap)", "(small cap)"),
            'beta': ("(high beta)", "(low beta)"),
            'momentum': ("(winners)", "(losers)"),
            'residvol': ("(high resid vol)", "(low resid vol)"),
            'nlsize': ("(mid cap tilt)", "(large/small tilt)"),
            'btop': ("(value)", "(growth)"),
            'liquidity': ("(liquid)", "(illiquid)"),
            'earnyild': ("(high yield)", "(low yield)"),
            'growth': ("(high growth)", "(low growth)"),
            'leverage': ("(high leverage)", "(low leverage)"),
        }
        if factor in interp_map:
            pos, neg = interp_map[factor]
            interpretation = pos if exp > 0 else neg

        print(f"  {factor:12s}: {exp:+.2f}  {interpretation}")

    # Industry exposures
    print("\nINDUSTRY EXPOSURES:")
    print("-" * 50)
    sorted_industries = sorted(industry_exp.items(), key=lambda x: abs(x[1]), reverse=True)
    for industry, exp in sorted_industries:
        if abs(exp) > 0.01:
            print(f"  {industry:30s}: {exp*100:+5.1f}%")

    # Factor risk contribution
    print("\nFACTOR RISK CONTRIBUTION:")
    print("-" * 50)
    risk_contrib_pct = risk_contrib / factor_variance * 100 if factor_variance > 0 else risk_contrib * 0

    # Sort by absolute contribution
    factor_risk_df = pd.DataFrame({
        'Factor': factor_names,
        'Exposure': exposure_vec,
        'Risk Contrib (%)': risk_contrib_pct
    }).sort_values('Risk Contrib (%)', key=abs, ascending=False)

    print("\n  Top risk contributors:")
    for _, row in factor_risk_df.head(10).iterrows():
        print(f"    {row['Factor']:25s}: {row['Risk Contrib (%)']:+6.1f}%")

    # Summary risk metrics
    print("\n" + "=" * 70)
    print("RISK SUMMARY")
    print("=" * 70)
    print(f"\n  Factor Volatility (annualized):  {factor_vol:.1f}%")

    # Compute actual idiosyncratic volatility from Barra residuals
    print("\n  Computing per-stock idiosyncratic volatility...")
    matched_tickers = weights_df[weights_df['ticker'].isin(exposures_df['ticker'].unique())]['ticker'].tolist()
    idio_vols = compute_idiosyncratic_volatility(matched_tickers, factor_exp_df, factor_ret_df)

    # Merge idio vol into weights and compute portfolio idio variance
    weights_with_idio = weights_df.copy()
    weights_with_idio['idio_vol'] = weights_with_idio['ticker'].map(idio_vols)

    # Fill missing with cross-sectional median
    median_idio = weights_with_idio['idio_vol'].median()
    weights_with_idio['idio_vol'] = weights_with_idio['idio_vol'].fillna(median_idio)

    idio_variance = (weights_with_idio['weight'] ** 2 * weights_with_idio['idio_vol'] ** 2).sum()
    idio_vol = np.sqrt(idio_variance) * 100

    total_variance = factor_variance * 252 + idio_variance
    total_vol = np.sqrt(total_variance) * 100

    pct_factor = (factor_variance * 252) / total_variance * 100 if total_variance > 0 else 0
    pct_idio = idio_variance / total_variance * 100 if total_variance > 0 else 0

    n_computed = weights_with_idio['ticker'].map(idio_vols).notna().sum()
    print(f"  Computed idio vol for {n_computed}/{len(weights_with_idio)} stocks")

    print(f"\n  Idiosyncratic Volatility:        {idio_vol:.1f}%")
    print(f"  Total Volatility:                {total_vol:.1f}%")
    print(f"\n  Risk Decomposition:")
    print(f"    Factor (systematic):           {pct_factor:.1f}%")
    print(f"    Idiosyncratic (specific):      {pct_idio:.1f}%")

    # Interpretation
    print("\n" + "=" * 70)
    print("INTERPRETATION")
    print("=" * 70)

    if pct_idio > 50:
        print("\n  Your portfolio has HIGH idiosyncratic risk (>50%).")
        print("  This is GOOD for a stock-picker - most risk is from stock selection,")
        print("  not from factor exposure. Your returns are driven by individual")
        print("  stock performance rather than market/style factors.")
    else:
        print("\n  Your portfolio has HIGH factor exposure.")
        print("  Most of your risk comes from exposure to market factors like")
        print("  size, momentum, or industries rather than individual stock picks.")

    # Dominant exposures
    dominant_style = max(style_exp.items(), key=lambda x: abs(x[1]))
    if abs(dominant_style[1]) > 0.3:
        print(f"\n  Dominant style tilt: {dominant_style[0]} ({dominant_style[1]:+.2f})")

    print("\n" + "=" * 70)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        portfolio_path = sys.argv[1]
    else:
        portfolio_path = 'data/input/portfolios/Own_Portfolio_dated.csv'

    main(portfolio_path)
