"""
Metrics Module
Performance metrics calculations: Sharpe Ratio, Information Ratio, Attribution, etc.
"""

import pandas as pd
import numpy as np


def calculate_sharpe_ratio(returns: pd.Series, rf: float = 0.0, annualize: bool = True) -> float:
    """
    Calculate Sharpe Ratio.

    Sharpe = (mean(returns) - rf) / std(returns)

    Args:
        returns: Series of returns (daily)
        rf: Risk-free rate (daily)
        annualize: Whether to annualize the result

    Returns:
        Sharpe Ratio
    """
    excess_returns = returns - rf
    if excess_returns.std() == 0:
        return 0.0

    sharpe = excess_returns.mean() / excess_returns.std()

    if annualize:
        sharpe *= np.sqrt(252)

    return sharpe


def calculate_information_ratio(idio_returns: pd.Series, annualize: bool = True) -> float:
    """
    Calculate Information Ratio (idiosyncratic Sharpe Ratio).

    IR = mean(idio_returns) / std(idio_returns)

    This measures skill independent of factor exposures.

    Args:
        idio_returns: Series of idiosyncratic returns
        annualize: Whether to annualize the result

    Returns:
        Information Ratio
    """
    if idio_returns.std() == 0:
        return 0.0

    ir = idio_returns.mean() / idio_returns.std()

    if annualize:
        ir *= np.sqrt(252)

    return ir


def calculate_sortino_ratio(returns: pd.Series, rf: float = 0.0,
                            annualize: bool = True) -> float:
    """
    Calculate Sortino Ratio (downside risk adjusted).

    Sortino = (mean(returns) - rf) / downside_std

    Args:
        returns: Series of returns
        rf: Risk-free rate (daily)
        annualize: Whether to annualize

    Returns:
        Sortino Ratio
    """
    excess_returns = returns - rf
    downside_returns = excess_returns[excess_returns < 0]

    if len(downside_returns) == 0 or downside_returns.std() == 0:
        return np.inf

    sortino = excess_returns.mean() / downside_returns.std()

    if annualize:
        sortino *= np.sqrt(252)

    return sortino


def calculate_max_drawdown(returns: pd.Series) -> dict:
    """
    Calculate maximum drawdown.

    Returns:
        Dict with 'max_drawdown', 'peak_date', 'trough_date'
    """
    cumulative = (1 + returns).cumprod()
    rolling_max = cumulative.expanding().max()
    drawdown = cumulative / rolling_max - 1

    max_dd = drawdown.min()
    trough_idx = drawdown.idxmin()

    # Find peak before trough
    peak_idx = cumulative[:trough_idx].idxmax()

    return {
        'max_drawdown': max_dd,
        'peak_date': peak_idx,
        'trough_date': trough_idx
    }


def calculate_performance_attribution(portfolio_returns: pd.Series,
                                       factor_contributions: dict,
                                       idio_returns: pd.Series,
                                       weights: pd.Series) -> dict:
    """
    Calculate performance attribution by factor.

    Decomposes total PnL into:
    - Market PnL
    - Size PnL
    - Value PnL
    - Momentum PnL
    - Idiosyncratic PnL

    Args:
        portfolio_returns: Total portfolio returns
        factor_contributions: Dict of DataFrames from decompose_returns()
        idio_returns: DataFrame of idiosyncratic returns
        weights: Portfolio weights

    Returns:
        Dict with attribution breakdown
    """
    attribution = {}

    # Factor contributions (weighted sum across positions)
    for factor, contrib_df in factor_contributions.items():
        # Weight and sum across positions
        weighted = (contrib_df * weights).sum(axis=1)
        attribution[f'{factor}_pnl'] = weighted.sum()
        attribution[f'{factor}_cumulative'] = (1 + weighted).cumprod() - 1

    # Idiosyncratic contribution
    idio_weighted = (idio_returns * weights).sum(axis=1)
    attribution['idio_pnl'] = idio_weighted.sum()
    attribution['idio_cumulative'] = (1 + idio_weighted).cumprod() - 1

    # Total
    attribution['total_pnl'] = portfolio_returns.sum()
    attribution['total_cumulative'] = (1 + portfolio_returns).cumprod() - 1

    return attribution


def calculate_marginal_contribution_to_risk(weights: pd.Series,
                                            betas: pd.DataFrame,
                                            factor_cov: pd.DataFrame) -> pd.Series:
    """
    Calculate Marginal Contribution to Factor Risk (MCFR) for each position.

    MCFR_i = [B * Omega_f * b]_i / sqrt(b' * Omega_f * b)

    Where b = B' * w (portfolio factor exposure)

    This identifies which positions contribute most to factor risk.

    Args:
        weights: Portfolio weights
        betas: Factor loadings matrix (stocks x factors)
        factor_cov: Factor covariance matrix

    Returns:
        Series of MCFR per position
    """
    # Ensure alignment
    tickers = weights.index.intersection(betas.index)
    w = weights.loc[tickers].values
    B = betas.loc[tickers].values

    factors = betas.columns.tolist()
    Omega_f = factor_cov.loc[factors, factors].values

    # Portfolio factor exposure: b = B' * w
    b = B.T @ w

    # Factor variance: b' * Omega_f * b
    factor_var = b.T @ Omega_f @ b
    factor_vol = np.sqrt(factor_var)

    if factor_vol == 0:
        return pd.Series(0, index=tickers)

    # MCFR for each position
    # MCFR_i = sum_k (B_ik * (Omega_f @ b)_k) / factor_vol
    Omega_f_b = Omega_f @ b
    mcfr = (B @ Omega_f_b) / factor_vol

    return pd.Series(mcfr, index=tickers)


def calculate_effective_n(weights: pd.Series) -> float:
    """
    Calculate effective number of stocks (N_eff).

    N_eff = ||w||_1^2 / ||w||_2^2

    This measures portfolio concentration.
    - N_eff = N means equal-weighted
    - N_eff = 1 means single stock

    Paleologo recommends N_eff of 50-200 for optimal diversification.
    """
    w = weights.values
    l1_norm = np.sum(np.abs(w))
    l2_norm_sq = np.sum(w ** 2)

    if l2_norm_sq == 0:
        return 0

    n_eff = (l1_norm ** 2) / l2_norm_sq
    return n_eff


def calculate_hit_rate(returns: pd.Series) -> float:
    """
    Calculate hit rate (percentage of positive return days).
    """
    positive_days = (returns > 0).sum()
    total_days = len(returns)

    if total_days == 0:
        return 0

    return positive_days / total_days


def calculate_win_loss_ratio(returns: pd.Series) -> float:
    """
    Calculate win/loss ratio (average win / average loss).
    """
    wins = returns[returns > 0]
    losses = returns[returns < 0]

    if len(losses) == 0 or losses.mean() == 0:
        return np.inf

    return abs(wins.mean() / losses.mean())


def calculate_calmar_ratio(returns: pd.Series, annualize: bool = True) -> float:
    """
    Calculate Calmar Ratio (return / max drawdown).
    """
    dd_info = calculate_max_drawdown(returns)
    max_dd = abs(dd_info['max_drawdown'])

    if max_dd == 0:
        return np.inf

    ann_return = returns.mean() * 252 if annualize else returns.mean()

    return ann_return / max_dd


def generate_metrics_summary(portfolio) -> dict:
    """
    Generate comprehensive metrics summary from a Portfolio object.

    Args:
        portfolio: Portfolio object with completed analysis

    Returns:
        Dict of all metrics
    """
    metrics = portfolio.metrics.copy()

    # Add additional metrics
    metrics['sortino'] = calculate_sortino_ratio(portfolio.portfolio_returns)

    dd_info = calculate_max_drawdown(portfolio.portfolio_returns)
    metrics['max_drawdown'] = dd_info['max_drawdown']
    metrics['drawdown_peak'] = dd_info['peak_date']
    metrics['drawdown_trough'] = dd_info['trough_date']

    metrics['effective_n'] = calculate_effective_n(portfolio.weights)
    metrics['hit_rate'] = calculate_hit_rate(portfolio.portfolio_returns)
    metrics['win_loss_ratio'] = calculate_win_loss_ratio(portfolio.portfolio_returns)
    metrics['calmar'] = calculate_calmar_ratio(portfolio.portfolio_returns)

    # Annualized return
    metrics['annual_return'] = portfolio.portfolio_returns.mean() * 252

    return metrics


# Quick test
if __name__ == "__main__":
    # Test with synthetic data
    np.random.seed(42)
    returns = pd.Series(np.random.normal(0.0005, 0.02, 252))

    print("=== Metrics Tests ===")
    print(f"Sharpe Ratio: {calculate_sharpe_ratio(returns):.2f}")
    print(f"Sortino Ratio: {calculate_sortino_ratio(returns):.2f}")

    dd = calculate_max_drawdown(returns)
    print(f"Max Drawdown: {dd['max_drawdown']:.2%}")

    print(f"Hit Rate: {calculate_hit_rate(returns):.1%}")
    print(f"Win/Loss Ratio: {calculate_win_loss_ratio(returns):.2f}")

    # Test effective N
    weights = pd.Series([0.5, 0.3, 0.2], index=['A', 'B', 'C'])
    print(f"Effective N (3 stocks): {calculate_effective_n(weights):.1f}")

    weights_equal = pd.Series([0.25, 0.25, 0.25, 0.25], index=['A', 'B', 'C', 'D'])
    print(f"Effective N (4 equal): {calculate_effective_n(weights_equal):.1f}")
