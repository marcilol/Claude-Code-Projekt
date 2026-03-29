<<<<<<< HEAD
"""
Factor Model Module
Implements Fama-French factor model estimation and return decomposition.

Based on the master equation: r = α + B*f + ε
Where:
- r: stock returns
- α: expected returns (alpha)
- B: factor loadings (betas)
- f: factor returns
- ε: idiosyncratic returns
"""

import pandas as pd
import numpy as np
from scipy import stats


def estimate_factor_loadings(stock_returns: pd.DataFrame,
                              factor_returns: pd.DataFrame,
                              window: int = 252) -> dict:
    """
    Estimate factor loadings (betas) for each stock using rolling regression.

    Uses OLS regression: r_stock - rf = α + β_mkt*(Mkt-RF) + β_smb*SMB + β_hml*HML + β_mom*Mom + ε

    Args:
        stock_returns: DataFrame of stock returns (dates x tickers)
        factor_returns: DataFrame of factor returns (must include Mkt-RF, SMB, HML, Mom, RF)
        window: Rolling window size in days (default 252 = 1 year)

    Returns:
        Dictionary containing:
        - 'betas': DataFrame of factor loadings (tickers x factors)
        - 'alphas': Series of alpha estimates per stock
        - 'r_squared': Series of R² values per stock
        - 'idio_vol': Series of idiosyncratic volatility per stock
    """
    # Ensure we have the required factor columns
    required_factors = ['Mkt-RF', 'SMB', 'HML']
    available_factors = [f for f in required_factors if f in factor_returns.columns]

    if 'Mom' in factor_returns.columns:
        available_factors.append('Mom')

    if not available_factors:
        raise ValueError("Factor data must include at least Mkt-RF, SMB, HML")

    # Get risk-free rate (default to 0 if not available)
    rf = factor_returns['RF'] if 'RF' in factor_returns.columns else 0

    # Prepare results storage
    tickers = stock_returns.columns.tolist()
    betas = pd.DataFrame(index=tickers, columns=available_factors, dtype=float)
    alphas = pd.Series(index=tickers, dtype=float)
    r_squared = pd.Series(index=tickers, dtype=float)
    idio_vol = pd.Series(index=tickers, dtype=float)

    print(f"Estimating factor loadings for {len(tickers)} stocks...")
    print(f"Using factors: {available_factors}")
    print(f"Window: {window} days")

    # Run regression for each stock
    for ticker in tickers:
        try:
            # Get excess returns (stock return - risk-free rate)
            stock_excess = stock_returns[ticker] - rf

            # Align data
            combined = pd.concat([stock_excess, factor_returns[available_factors]], axis=1).dropna()

            if len(combined) < window:
                print(f"  {ticker}: Insufficient data ({len(combined)} days), using all available")
                data = combined
            else:
                # Use most recent 'window' days
                data = combined.iloc[-window:]

            y = data.iloc[:, 0].values  # Excess returns
            X = data.iloc[:, 1:].values  # Factor returns

            # Add constant for alpha
            X_with_const = np.column_stack([np.ones(len(X)), X])

            # OLS regression
            coeffs, residuals, rank, s = np.linalg.lstsq(X_with_const, y, rcond=None)

            # Extract results
            alpha = coeffs[0]  # Intercept
            beta_values = coeffs[1:]  # Factor loadings

            # Calculate R-squared
            y_pred = X_with_const @ coeffs
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

            # Calculate idiosyncratic volatility (annualized)
            residual = y - y_pred
            idio_vol_daily = np.std(residual)
            idio_vol_annual = idio_vol_daily * np.sqrt(252)

            # Store results
            alphas[ticker] = alpha * 252  # Annualize alpha
            for i, factor in enumerate(available_factors):
                betas.loc[ticker, factor] = beta_values[i]
            r_squared[ticker] = r2
            idio_vol[ticker] = idio_vol_annual

            print(f"  {ticker}: beta_mkt={betas.loc[ticker, 'Mkt-RF']:.2f}, "
                  f"R2={r2:.2%}, idio_vol={idio_vol_annual:.1%}")

        except Exception as e:
            print(f"  {ticker}: Error - {e}")
            alphas[ticker] = np.nan
            for factor in available_factors:
                betas.loc[ticker, factor] = np.nan
            r_squared[ticker] = np.nan
            idio_vol[ticker] = np.nan

    return {
        'betas': betas.astype(float),
        'alphas': alphas,
        'r_squared': r_squared,
        'idio_vol': idio_vol
    }


def decompose_returns(stock_returns: pd.DataFrame,
                      factor_returns: pd.DataFrame,
                      betas: pd.DataFrame) -> dict:
    """
    Decompose stock returns into systematic and idiosyncratic components.

    Master equation: r = α + B*f + ε
    - Systematic return: B*f (factor-driven)
    - Idiosyncratic return: ε (stock-specific)

    Args:
        stock_returns: DataFrame of stock returns
        factor_returns: DataFrame of factor returns
        betas: DataFrame of factor loadings from estimate_factor_loadings()

    Returns:
        Dictionary containing:
        - 'systematic': DataFrame of systematic returns (dates x tickers)
        - 'idiosyncratic': DataFrame of idiosyncratic returns (dates x tickers)
        - 'factor_contributions': Dict of DataFrames, one per factor
    """
    tickers = stock_returns.columns.tolist()
    factors = betas.columns.tolist()

    # Ensure alignment
    common_dates = stock_returns.index.intersection(factor_returns.index)
    stock_ret = stock_returns.loc[common_dates]
    factor_ret = factor_returns.loc[common_dates, factors]

    # Calculate systematic returns (B * f)
    systematic = pd.DataFrame(index=common_dates, columns=tickers, dtype=float)
    factor_contributions = {f: pd.DataFrame(index=common_dates, columns=tickers, dtype=float)
                           for f in factors}

    for ticker in tickers:
        ticker_betas = betas.loc[ticker]
        systematic_return = pd.Series(0.0, index=common_dates)

        for factor in factors:
            if pd.notna(ticker_betas[factor]):
                contribution = ticker_betas[factor] * factor_ret[factor]
                factor_contributions[factor][ticker] = contribution
                systematic_return += contribution

        systematic[ticker] = systematic_return

    # Calculate idiosyncratic returns (r - systematic)
    idiosyncratic = stock_ret - systematic

    print(f"Decomposed returns for {len(common_dates)} days")

    return {
        'systematic': systematic,
        'idiosyncratic': idiosyncratic,
        'factor_contributions': factor_contributions
    }


def calculate_factor_covariance(factor_returns: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate the factor covariance matrix (Ω_f).

    Used for portfolio risk decomposition.
    """
    factors = ['Mkt-RF', 'SMB', 'HML']
    if 'Mom' in factor_returns.columns:
        factors.append('Mom')

    available = [f for f in factors if f in factor_returns.columns]
    cov_matrix = factor_returns[available].cov() * 252  # Annualize

    return cov_matrix


def calculate_idiosyncratic_covariance(idio_returns: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate the idiosyncratic covariance matrix (Ω_ε).

    This is typically diagonal (stocks' idiosyncratic risks are uncorrelated).
    """
    # Use diagonal matrix with idiosyncratic variances
    idio_var = idio_returns.var() * 252  # Annualize
    cov_matrix = pd.DataFrame(
        np.diag(idio_var),
        index=idio_returns.columns,
        columns=idio_returns.columns
    )

    return cov_matrix


def get_factor_interpretation(betas: pd.DataFrame) -> pd.DataFrame:
    """
    Provide human-readable interpretation of factor exposures.

    Returns DataFrame with interpretation for each stock.
    """
    interpretations = []

    for ticker in betas.index:
        interp = {'ticker': ticker}

        # Market beta interpretation
        mkt_beta = betas.loc[ticker, 'Mkt-RF']
        if pd.notna(mkt_beta):
            if mkt_beta > 1.2:
                interp['market'] = f"High market sensitivity ({mkt_beta:.2f})"
            elif mkt_beta < 0.8:
                interp['market'] = f"Defensive ({mkt_beta:.2f})"
            else:
                interp['market'] = f"Market-like ({mkt_beta:.2f})"

        # Size (SMB) interpretation
        if 'SMB' in betas.columns:
            smb_beta = betas.loc[ticker, 'SMB']
            if pd.notna(smb_beta):
                if smb_beta > 0.3:
                    interp['size'] = f"Small-cap tilt ({smb_beta:.2f})"
                elif smb_beta < -0.3:
                    interp['size'] = f"Large-cap tilt ({smb_beta:.2f})"
                else:
                    interp['size'] = f"Size-neutral ({smb_beta:.2f})"

        # Value (HML) interpretation
        if 'HML' in betas.columns:
            hml_beta = betas.loc[ticker, 'HML']
            if pd.notna(hml_beta):
                if hml_beta > 0.3:
                    interp['value'] = f"Value stock ({hml_beta:.2f})"
                elif hml_beta < -0.3:
                    interp['value'] = f"Growth stock ({hml_beta:.2f})"
                else:
                    interp['value'] = f"Blend ({hml_beta:.2f})"

        # Momentum interpretation
        if 'Mom' in betas.columns:
            mom_beta = betas.loc[ticker, 'Mom']
            if pd.notna(mom_beta):
                if mom_beta > 0.3:
                    interp['momentum'] = f"Momentum winner ({mom_beta:.2f})"
                elif mom_beta < -0.3:
                    interp['momentum'] = f"Momentum loser ({mom_beta:.2f})"
                else:
                    interp['momentum'] = f"Momentum-neutral ({mom_beta:.2f})"

        interpretations.append(interp)

    return pd.DataFrame(interpretations).set_index('ticker')


# Quick test when run directly
if __name__ == "__main__":
    from data_loader import fetch_stock_prices, fetch_fama_french_factors, calculate_returns, align_data

    print("Testing factors module...")

    # Get test data
    tickers = ['AAPL', 'MSFT', 'GOOGL']
    prices = fetch_stock_prices(tickers, '2023-01-01')
    returns = calculate_returns(prices)
    factors = fetch_fama_french_factors('2023-01-01')

    aligned_ret, aligned_fac = align_data(returns, factors)

    # Estimate factor loadings
    results = estimate_factor_loadings(aligned_ret, aligned_fac)

    print("\n=== Factor Loadings (Betas) ===")
    print(results['betas'])

    print("\n=== Annualized Alphas ===")
    print(results['alphas'])

    print("\n=== R-Squared ===")
    print(results['r_squared'])

    # Decompose returns
    decomp = decompose_returns(aligned_ret, aligned_fac, results['betas'])

    print("\n=== Return Decomposition (last 5 days) ===")
    print("Systematic:")
    print(decomp['systematic'].tail())
    print("\nIdiosyncratic:")
    print(decomp['idiosyncratic'].tail())

    # Interpretations
    print("\n=== Factor Interpretations ===")
    print(get_factor_interpretation(results['betas']))
=======
"""
Factor Model Module
Implements Fama-French factor model estimation and return decomposition.

Based on the master equation: r = α + B*f + ε
Where:
- r: stock returns
- α: expected returns (alpha)
- B: factor loadings (betas)
- f: factor returns
- ε: idiosyncratic returns
"""

import pandas as pd
import numpy as np
from scipy import stats


def estimate_factor_loadings(stock_returns: pd.DataFrame,
                              factor_returns: pd.DataFrame,
                              window: int = 252) -> dict:
    """
    Estimate factor loadings (betas) for each stock using rolling regression.

    Uses OLS regression: r_stock - rf = α + β_mkt*(Mkt-RF) + β_smb*SMB + β_hml*HML + β_mom*Mom + ε

    Args:
        stock_returns: DataFrame of stock returns (dates x tickers)
        factor_returns: DataFrame of factor returns (must include Mkt-RF, SMB, HML, Mom, RF)
        window: Rolling window size in days (default 252 = 1 year)

    Returns:
        Dictionary containing:
        - 'betas': DataFrame of factor loadings (tickers x factors)
        - 'alphas': Series of alpha estimates per stock
        - 'r_squared': Series of R² values per stock
        - 'idio_vol': Series of idiosyncratic volatility per stock
    """
    # Ensure we have the required factor columns
    required_factors = ['Mkt-RF', 'SMB', 'HML']
    available_factors = [f for f in required_factors if f in factor_returns.columns]

    if 'Mom' in factor_returns.columns:
        available_factors.append('Mom')

    if not available_factors:
        raise ValueError("Factor data must include at least Mkt-RF, SMB, HML")

    # Get risk-free rate (default to 0 if not available)
    rf = factor_returns['RF'] if 'RF' in factor_returns.columns else 0

    # Prepare results storage
    tickers = stock_returns.columns.tolist()
    betas = pd.DataFrame(index=tickers, columns=available_factors, dtype=float)
    alphas = pd.Series(index=tickers, dtype=float)
    r_squared = pd.Series(index=tickers, dtype=float)
    idio_vol = pd.Series(index=tickers, dtype=float)

    print(f"Estimating factor loadings for {len(tickers)} stocks...")
    print(f"Using factors: {available_factors}")
    print(f"Window: {window} days")

    # Run regression for each stock
    for ticker in tickers:
        try:
            # Get excess returns (stock return - risk-free rate)
            stock_excess = stock_returns[ticker] - rf

            # Align data
            combined = pd.concat([stock_excess, factor_returns[available_factors]], axis=1).dropna()

            if len(combined) < window:
                print(f"  {ticker}: Insufficient data ({len(combined)} days), using all available")
                data = combined
            else:
                # Use most recent 'window' days
                data = combined.iloc[-window:]

            y = data.iloc[:, 0].values  # Excess returns
            X = data.iloc[:, 1:].values  # Factor returns

            # Add constant for alpha
            X_with_const = np.column_stack([np.ones(len(X)), X])

            # OLS regression
            coeffs, residuals, rank, s = np.linalg.lstsq(X_with_const, y, rcond=None)

            # Extract results
            alpha = coeffs[0]  # Intercept
            beta_values = coeffs[1:]  # Factor loadings

            # Calculate R-squared
            y_pred = X_with_const @ coeffs
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

            # Calculate idiosyncratic volatility (annualized)
            residual = y - y_pred
            idio_vol_daily = np.std(residual)
            idio_vol_annual = idio_vol_daily * np.sqrt(252)

            # Store results
            alphas[ticker] = alpha * 252  # Annualize alpha
            for i, factor in enumerate(available_factors):
                betas.loc[ticker, factor] = beta_values[i]
            r_squared[ticker] = r2
            idio_vol[ticker] = idio_vol_annual

            print(f"  {ticker}: beta_mkt={betas.loc[ticker, 'Mkt-RF']:.2f}, "
                  f"R2={r2:.2%}, idio_vol={idio_vol_annual:.1%}")

        except Exception as e:
            print(f"  {ticker}: Error - {e}")
            alphas[ticker] = np.nan
            for factor in available_factors:
                betas.loc[ticker, factor] = np.nan
            r_squared[ticker] = np.nan
            idio_vol[ticker] = np.nan

    return {
        'betas': betas.astype(float),
        'alphas': alphas,
        'r_squared': r_squared,
        'idio_vol': idio_vol
    }


def decompose_returns(stock_returns: pd.DataFrame,
                      factor_returns: pd.DataFrame,
                      betas: pd.DataFrame) -> dict:
    """
    Decompose stock returns into systematic and idiosyncratic components.

    Master equation: r = α + B*f + ε
    - Systematic return: B*f (factor-driven)
    - Idiosyncratic return: ε (stock-specific)

    Args:
        stock_returns: DataFrame of stock returns
        factor_returns: DataFrame of factor returns
        betas: DataFrame of factor loadings from estimate_factor_loadings()

    Returns:
        Dictionary containing:
        - 'systematic': DataFrame of systematic returns (dates x tickers)
        - 'idiosyncratic': DataFrame of idiosyncratic returns (dates x tickers)
        - 'factor_contributions': Dict of DataFrames, one per factor
    """
    tickers = stock_returns.columns.tolist()
    factors = betas.columns.tolist()

    # Ensure alignment
    common_dates = stock_returns.index.intersection(factor_returns.index)
    stock_ret = stock_returns.loc[common_dates]
    factor_ret = factor_returns.loc[common_dates, factors]

    # Calculate systematic returns (B * f)
    systematic = pd.DataFrame(index=common_dates, columns=tickers, dtype=float)
    factor_contributions = {f: pd.DataFrame(index=common_dates, columns=tickers, dtype=float)
                           for f in factors}

    for ticker in tickers:
        ticker_betas = betas.loc[ticker]
        systematic_return = pd.Series(0.0, index=common_dates)

        for factor in factors:
            if pd.notna(ticker_betas[factor]):
                contribution = ticker_betas[factor] * factor_ret[factor]
                factor_contributions[factor][ticker] = contribution
                systematic_return += contribution

        systematic[ticker] = systematic_return

    # Calculate idiosyncratic returns (r - systematic)
    idiosyncratic = stock_ret - systematic

    print(f"Decomposed returns for {len(common_dates)} days")

    return {
        'systematic': systematic,
        'idiosyncratic': idiosyncratic,
        'factor_contributions': factor_contributions
    }


def calculate_factor_covariance(factor_returns: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate the factor covariance matrix (Ω_f).

    Used for portfolio risk decomposition.
    """
    factors = ['Mkt-RF', 'SMB', 'HML']
    if 'Mom' in factor_returns.columns:
        factors.append('Mom')

    available = [f for f in factors if f in factor_returns.columns]
    cov_matrix = factor_returns[available].cov() * 252  # Annualize

    return cov_matrix


def calculate_idiosyncratic_covariance(idio_returns: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate the idiosyncratic covariance matrix (Ω_ε).

    This is typically diagonal (stocks' idiosyncratic risks are uncorrelated).
    """
    # Use diagonal matrix with idiosyncratic variances
    idio_var = idio_returns.var() * 252  # Annualize
    cov_matrix = pd.DataFrame(
        np.diag(idio_var),
        index=idio_returns.columns,
        columns=idio_returns.columns
    )

    return cov_matrix


def get_factor_interpretation(betas: pd.DataFrame) -> pd.DataFrame:
    """
    Provide human-readable interpretation of factor exposures.

    Returns DataFrame with interpretation for each stock.
    """
    interpretations = []

    for ticker in betas.index:
        interp = {'ticker': ticker}

        # Market beta interpretation
        mkt_beta = betas.loc[ticker, 'Mkt-RF']
        if pd.notna(mkt_beta):
            if mkt_beta > 1.2:
                interp['market'] = f"High market sensitivity ({mkt_beta:.2f})"
            elif mkt_beta < 0.8:
                interp['market'] = f"Defensive ({mkt_beta:.2f})"
            else:
                interp['market'] = f"Market-like ({mkt_beta:.2f})"

        # Size (SMB) interpretation
        if 'SMB' in betas.columns:
            smb_beta = betas.loc[ticker, 'SMB']
            if pd.notna(smb_beta):
                if smb_beta > 0.3:
                    interp['size'] = f"Small-cap tilt ({smb_beta:.2f})"
                elif smb_beta < -0.3:
                    interp['size'] = f"Large-cap tilt ({smb_beta:.2f})"
                else:
                    interp['size'] = f"Size-neutral ({smb_beta:.2f})"

        # Value (HML) interpretation
        if 'HML' in betas.columns:
            hml_beta = betas.loc[ticker, 'HML']
            if pd.notna(hml_beta):
                if hml_beta > 0.3:
                    interp['value'] = f"Value stock ({hml_beta:.2f})"
                elif hml_beta < -0.3:
                    interp['value'] = f"Growth stock ({hml_beta:.2f})"
                else:
                    interp['value'] = f"Blend ({hml_beta:.2f})"

        # Momentum interpretation
        if 'Mom' in betas.columns:
            mom_beta = betas.loc[ticker, 'Mom']
            if pd.notna(mom_beta):
                if mom_beta > 0.3:
                    interp['momentum'] = f"Momentum winner ({mom_beta:.2f})"
                elif mom_beta < -0.3:
                    interp['momentum'] = f"Momentum loser ({mom_beta:.2f})"
                else:
                    interp['momentum'] = f"Momentum-neutral ({mom_beta:.2f})"

        interpretations.append(interp)

    return pd.DataFrame(interpretations).set_index('ticker')


# Quick test when run directly
if __name__ == "__main__":
    from data_loader import fetch_stock_prices, fetch_fama_french_factors, calculate_returns, align_data

    print("Testing factors module...")

    # Get test data
    tickers = ['AAPL', 'MSFT', 'GOOGL']
    prices = fetch_stock_prices(tickers, '2023-01-01')
    returns = calculate_returns(prices)
    factors = fetch_fama_french_factors('2023-01-01')

    aligned_ret, aligned_fac = align_data(returns, factors)

    # Estimate factor loadings
    results = estimate_factor_loadings(aligned_ret, aligned_fac)

    print("\n=== Factor Loadings (Betas) ===")
    print(results['betas'])

    print("\n=== Annualized Alphas ===")
    print(results['alphas'])

    print("\n=== R-Squared ===")
    print(results['r_squared'])

    # Decompose returns
    decomp = decompose_returns(aligned_ret, aligned_fac, results['betas'])

    print("\n=== Return Decomposition (last 5 days) ===")
    print("Systematic:")
    print(decomp['systematic'].tail())
    print("\nIdiosyncratic:")
    print(decomp['idiosyncratic'].tail())

    # Interpretations
    print("\n=== Factor Interpretations ===")
    print(get_factor_interpretation(results['betas']))
>>>>>>> 19dde37b83c378e4960c4ec0d65165e18eb451c1
