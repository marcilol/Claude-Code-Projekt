# -*- coding: utf-8 -*-
"""
Barra-style Multi-Factor Model for Russell 3000
Following MSCI best practices as implemented in barra-master

Key methodology:
1. Cross-sectional WLS regression (sqrt market cap weights)
2. Industry neutrality constraint (handles multicollinearity)
3. Newey-West adjustment for autocorrelation (q=2, halflife=252)
4. Eigenfactor Risk Adjustment (Monte Carlo, scale=1.4)
5. Volatility Regime Adjustment (halflife=42)
"""

import pandas as pd
import numpy as np
from functools import reduce
import warnings
warnings.filterwarnings('ignore')


def style_factor_norm(factors, capital):
    """
    Normalize style factors using market-cap weighted mean and equal-weighted std
    This is the Barra standard approach
    """
    weights = capital / capital.sum()
    weighted_mean = np.average(factors, weights=weights, axis=0)
    equal_std = np.std(factors, axis=0)
    equal_std[equal_std == 0] = 1  # Avoid division by zero
    return (factors - weighted_mean) / equal_std


class CrossSection:
    """
    Cross-sectional regression for a single date
    Implements pure factor portfolio methodology with industry neutrality constraint
    """

    def __init__(self, base_data, style_factors, industry_factors):
        self.date = base_data['date'].iloc[0]
        self.stocknames = base_data['stocknames'].tolist()
        self.capital = base_data['capital'].values.astype(float)
        self.ret = base_data['ret'].values.astype(float)

        self.N = len(base_data)  # Number of stocks
        self.Q = style_factors.shape[1]  # Number of style factors
        self.P = industry_factors.shape[1]  # Number of industries

        # Normalize style factors (market-cap weighted mean, equal-weighted std)
        self.style_factors = style_factor_norm(style_factors.values, self.capital)
        self.industry_factors = industry_factors.values
        self.country_factors = np.ones((self.N, 1))  # Country/market factor

        # WLS weights: sqrt of market cap, normalized
        self.W = np.sqrt(self.capital) / np.sqrt(self.capital).sum()

    def reg(self):
        """
        Solve multi-factor model with industry neutrality constraint
        Returns: factor_returns, specific_returns, pure_factor_exposures, R2
        """
        W = np.diag(self.W)

        if self.P > 0:
            # Industry market caps for neutrality constraint
            industry_capital = np.array([
                np.sum(self.industry_factors[:, i] * self.capital)
                for i in range(self.P)
            ])

            # Transformation matrix R for industry neutrality
            # This handles the multicollinearity between country factor and industries
            R = np.eye(1 + self.P + self.Q)
            R[self.P, 1:(1 + self.P)] = -industry_capital / industry_capital[-1]
            R = np.delete(R, self.P, axis=1)

            # Construct factor matrix
            factors = np.hstack([self.country_factors, self.industry_factors, self.style_factors])
            factors_tran = factors @ R

            # Pure factor portfolio weights
            try:
                pure_factor_weight = R @ np.linalg.inv(factors_tran.T @ W @ factors_tran) @ factors_tran.T @ W
            except np.linalg.LinAlgError:
                pure_factor_weight = R @ np.linalg.pinv(factors_tran.T @ W @ factors_tran) @ factors_tran.T @ W
        else:
            factors = np.hstack([self.country_factors, self.style_factors])
            try:
                pure_factor_weight = np.linalg.inv(factors.T @ W @ factors) @ factors.T @ W
            except np.linalg.LinAlgError:
                pure_factor_weight = np.linalg.pinv(factors.T @ W @ factors) @ factors.T @ W

        # Factor returns = pure factor portfolio weights × stock returns
        factor_ret = pure_factor_weight @ self.ret

        # Specific (idiosyncratic) returns
        specific_ret = self.ret - factors @ factor_ret if self.P > 0 else self.ret - factors @ factor_ret

        # R-squared
        R2 = 1 - np.var(specific_ret) / np.var(self.ret) if np.var(self.ret) > 0 else 0

        # Pure factor exposures
        pure_factor_exposure = pure_factor_weight @ factors

        return factor_ret, specific_ret, pure_factor_exposure, R2


def Newey_West(ret, q=2, tao=252):
    """
    Newey-West covariance adjustment for autocorrelation

    Parameters:
    - ret: DataFrame of factor returns (rows=time, cols=factors)
    - q: Assume factor returns follow MA(q) process
    - tao: Half-life for exponential weighting
    """
    T, K = ret.shape
    if T <= q or T <= K:
        raise ValueError(f"Insufficient data: T={T}, q={q}, K={K}")

    names = ret.columns

    # Exponential decay weights
    weights = 0.5 ** (np.arange(T-1, -1, -1) / tao)
    weights = weights / weights.sum()

    # Demean with weighted mean
    weighted_mean = np.average(ret.values, weights=weights, axis=0)
    ret_dm = ret.values - weighted_mean

    # Gamma_0: contemporaneous covariance
    Gamma0 = sum(weights[t] * np.outer(ret_dm[t], ret_dm[t]) for t in range(T))

    # Add lagged autocovariances with Newey-West weights
    V = Gamma0.copy()
    for i in range(1, q + 1):
        Gamma_i = sum(weights[i + t] * np.outer(ret_dm[t], ret_dm[i + t]) for t in range(T - i))
        V = V + (1 - i / (1 + q)) * (Gamma_i + Gamma_i.T)

    return pd.DataFrame(V, columns=names, index=names)


def eigen_risk_adj(covmat, T=1000, M=100, scale_coef=1.4):
    """
    Eigenfactor Risk Adjustment via Monte Carlo simulation

    This corrects for sampling error in the estimated covariance matrix,
    which tends to underestimate risk for extreme eigenfactor portfolios.

    Parameters:
    - covmat: Factor covariance matrix
    - T: Assumed sample size for simulation
    - M: Number of Monte Carlo simulations
    - scale_coef: Scaling coefficient for bias adjustment (MSCI uses 1.4)
    """
    F0 = covmat.values
    K = F0.shape[0]
    names = covmat.columns

    # Eigendecomposition
    D0, U0 = np.linalg.eigh(F0)  # Use eigh for symmetric matrices
    D0 = np.maximum(D0, 1e-10)  # Ensure positive definiteness

    # Monte Carlo simulation to estimate bias
    v = []
    for m in range(M):
        np.random.seed(m + 1)
        # Simulate factor returns from eigenfactor distribution
        bm = np.random.multivariate_normal(mean=np.zeros(K), cov=np.diag(D0), size=T).T
        fm = U0 @ bm  # Transform back to factor space
        Fm = np.cov(fm)  # Simulated covariance

        # Eigendecomposition of simulated covariance
        Dm, Um = np.linalg.eigh(Fm)
        Dm = np.maximum(Dm, 1e-10)

        # Compare to true covariance in eigenfactor space
        Dm_hat = np.diag(Um.T @ F0 @ Um)
        v.append(Dm_hat / Dm)

    # Average bias across simulations
    v = np.sqrt(np.mean(np.array(v), axis=0))
    v = scale_coef * (v - 1) + 1  # Scale adjustment

    # Adjust eigenvalues
    D0_hat = np.diag(v ** 2) * np.diag(D0)
    F0_hat = U0 @ D0_hat @ U0.T

    return pd.DataFrame(F0_hat, columns=names, index=names)


def vol_regime_adj(cov_list, factor_ret, tao=42):
    """
    Volatility Regime Adjustment

    Adjusts covariance matrix for current volatility regime,
    using exponentially weighted cross-sectional bias statistic.

    Parameters:
    - cov_list: List of covariance matrices over time
    - factor_ret: DataFrame of factor returns
    - tao: Half-life for exponential weighting
    """
    T = len(cov_list)
    K = cov_list[-1].shape[0] if len(cov_list[-1]) > 0 else 0

    # Extract factor variances over time
    factor_var = []
    for t in range(T):
        if len(cov_list[t]) > 0:
            factor_var.append(np.diag(cov_list[t].values))
        else:
            factor_var.append(np.full(K, np.nan))
    factor_var = np.array(factor_var)

    # Cross-sectional bias statistic
    with np.errstate(divide='ignore', invalid='ignore'):
        B = np.sqrt(np.nanmean(factor_ret.values ** 2 / factor_var, axis=1))

    # Exponential decay weights
    weights = 0.5 ** (np.arange(T - 1, -1, -1) / tao)

    vol_adj_cov = []
    lambdas = []

    for t in range(T):
        # Use only valid observations up to time t
        valid_idx = ~np.isnan(B[:t+1])
        if valid_idx.sum() == 0:
            vol_adj_cov.append(cov_list[t])
            lambdas.append(1.0)
            continue

        w_valid = weights[:t+1][valid_idx]
        w_valid = w_valid / w_valid.sum()
        B_valid = B[:t+1][valid_idx]

        # Factor volatility multiplier
        fvm = np.sqrt(np.sum(w_valid * B_valid ** 2))
        fvm = np.clip(fvm, 0.5, 2.0)  # Bound the adjustment

        lambdas.append(fvm)
        if len(cov_list[t]) > 0:
            vol_adj_cov.append(cov_list[t] * fvm ** 2)
        else:
            vol_adj_cov.append(cov_list[t])

    return vol_adj_cov, lambdas


class BarraModel:
    """
    Full Barra Multi-Factor Model implementation
    """

    def __init__(self, data, industry_cols, style_cols):
        self.data = data
        self.industry_cols = industry_cols
        self.style_cols = style_cols
        self.P = len(industry_cols)  # Number of industries
        self.Q = len(style_cols)  # Number of style factors

        self.dates = sorted(data['date'].unique())
        self.T = len(self.dates)

        # Results
        self.factor_ret = None
        self.specific_ret = None
        self.R2 = None
        self.Newey_West_cov = None
        self.eigen_risk_adj_cov = None
        self.vol_regime_adj_cov = None

    def run_cross_sectional_regression(self):
        """Step 1: Run cross-sectional regression for each date"""
        print("=" * 60)
        print("Step 1: Cross-Sectional Regression")
        print("=" * 60)

        factor_names = ['Country'] + self.industry_cols + self.style_cols  # All factors
        factor_returns = []
        r2_values = []
        specific_returns = []

        for i, date in enumerate(self.dates):
            if i % 10 == 0:
                print(f"  Processing date {i+1}/{self.T}: {date}", flush=True)

            # Get data for this date
            df_t = self.data[self.data['date'] == date].copy()

            # Prepare inputs for CrossSection
            base_data = df_t[['date', 'stocknames', 'capital', 'ret']].reset_index(drop=True)
            style_factors = df_t[self.style_cols].reset_index(drop=True)
            industry_factors = df_t[self.industry_cols].reset_index(drop=True)

            try:
                cs = CrossSection(base_data, style_factors, industry_factors)
                factor_ret, specific_ret, _, r2 = cs.reg()

                factor_returns.append(factor_ret)
                r2_values.append(r2)
                specific_returns.append({
                    'date': date,
                    'stocks': cs.stocknames,
                    'specific_ret': specific_ret
                })
            except Exception as e:
                print(f"    Error on {date}: {e}")
                factor_returns.append(np.full(1 + self.P - 1 + self.Q, np.nan))
                r2_values.append(np.nan)

        self.factor_ret = pd.DataFrame(factor_returns, columns=factor_names, index=self.dates)
        self.R2 = pd.DataFrame(r2_values, columns=['R2'], index=self.dates)
        self.specific_ret = specific_returns

        print(f"\n  Average R²: {self.R2['R2'].mean():.4f}")
        return self.factor_ret, self.R2

    def run_newey_west(self, q=2, tao=252):
        """Step 2: Newey-West covariance adjustment"""
        print("\n" + "=" * 60)
        print("Step 2: Newey-West Covariance Adjustment")
        print(f"  Parameters: q={q} (MA order), tao={tao} (half-life)")
        print("=" * 60)

        if self.factor_ret is None:
            raise ValueError("Run cross-sectional regression first")

        nw_cov = []
        for t in range(1, self.T + 1):
            if t % 10 == 0:
                print(f"  Processing period {t}/{self.T}", flush=True)

            try:
                cov = Newey_West(self.factor_ret.iloc[:t], q=q, tao=tao)
                nw_cov.append(cov)
            except Exception as e:
                nw_cov.append(pd.DataFrame())

        self.Newey_West_cov = nw_cov
        print("  Done.")
        return nw_cov

    def run_eigenfactor_adjustment(self, M=100, scale_coef=1.4):
        """Step 3: Eigenfactor Risk Adjustment"""
        print("\n" + "=" * 60)
        print("Step 3: Eigenfactor Risk Adjustment")
        print(f"  Parameters: M={M} simulations, scale={scale_coef}")
        print("=" * 60)

        if self.Newey_West_cov is None:
            raise ValueError("Run Newey-West adjustment first")

        eigen_cov = []
        for t in range(self.T):
            if t % 10 == 0:
                print(f"  Processing period {t+1}/{self.T}", flush=True)

            try:
                if len(self.Newey_West_cov[t]) > 0:
                    cov = eigen_risk_adj(self.Newey_West_cov[t], T=self.T, M=M, scale_coef=scale_coef)
                    eigen_cov.append(cov)
                else:
                    eigen_cov.append(pd.DataFrame())
            except Exception as e:
                eigen_cov.append(pd.DataFrame())

        self.eigen_risk_adj_cov = eigen_cov
        print("  Done.")
        return eigen_cov

    def run_volatility_regime_adjustment(self, tao=42):
        """Step 4: Volatility Regime Adjustment"""
        print("\n" + "=" * 60)
        print("Step 4: Volatility Regime Adjustment")
        print(f"  Parameters: tao={tao} (half-life)")
        print("=" * 60)

        if self.eigen_risk_adj_cov is None:
            raise ValueError("Run eigenfactor adjustment first")

        vol_cov, lambdas = vol_regime_adj(self.eigen_risk_adj_cov, self.factor_ret, tao=tao)
        self.vol_regime_adj_cov = vol_cov

        print(f"  Final volatility multiplier: {lambdas[-1]:.3f}")
        print("  Done.")
        return vol_cov, lambdas

    def get_final_covariance(self):
        """Get the final adjusted factor covariance matrix"""
        if self.vol_regime_adj_cov is not None:
            return self.vol_regime_adj_cov[-1]
        elif self.eigen_risk_adj_cov is not None:
            return self.eigen_risk_adj_cov[-1]
        elif self.Newey_West_cov is not None:
            return self.Newey_West_cov[-1]
        else:
            raise ValueError("No covariance matrix computed yet")


def main():
    print("=" * 70)
    print("BARRA MULTI-FACTOR MODEL - Russell 3000")
    print("Following MSCI Best Practices")
    print("=" * 70)

    # Load data
    print("\nLoading data...")
    data = pd.read_csv('data/model/russell3000_cross_sectional_data.csv')

    # Handle NaN values
    style_cols = ['size', 'beta', 'momentum', 'residvol', 'nlsize', 'btop', 'liquidity', 'earnyild', 'growth', 'leverage']
    for col in style_cols:
        data[col] = data[col].fillna(0)
    data = data.dropna(subset=['ret', 'capital'])
    data = data[data['capital'] > 0]

    print(f"  Shape: {data.shape}")
    print(f"  Dates: {data['date'].nunique()}")
    print(f"  Stocks per date: ~{len(data) // data['date'].nunique()}")

    # Identify industry columns
    industry_cols = [c for c in data.columns if c not in
                     ['date', 'stocknames', 'capital', 'ret'] + style_cols]

    print(f"  Industries: {len(industry_cols)}")
    print(f"  Style factors: {len(style_cols)}")

    # Initialize and run model
    model = BarraModel(data, industry_cols, style_cols)

    # Step 1: Cross-sectional regression
    factor_ret, r2 = model.run_cross_sectional_regression()

    # Step 2: Newey-West adjustment
    nw_cov = model.run_newey_west(q=2, tao=252)

    # Step 3: Eigenfactor Risk Adjustment
    eigen_cov = model.run_eigenfactor_adjustment(M=100, scale_coef=1.4)

    # Step 4: Volatility Regime Adjustment
    vol_cov, lambdas = model.run_volatility_regime_adjustment(tao=42)

    # Results summary
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)

    # Factor return statistics
    print("\nFactor Return Statistics (annualized):")
    stats = pd.DataFrame({
        'Mean (%)': model.factor_ret.mean() * 252 * 100,
        'Vol (%)': model.factor_ret.std() * np.sqrt(252) * 100,
        't-stat': (model.factor_ret.mean() / model.factor_ret.std()) * np.sqrt(len(model.factor_ret))
    })
    print(stats.round(2).to_string())

    # Final covariance matrix (style factors only)
    print("\nFactor Correlation Matrix (style factors):")
    final_cov = model.get_final_covariance()
    style_cov = final_cov.loc[style_cols, style_cols]
    style_std = np.sqrt(np.diag(style_cov))
    style_corr = style_cov / np.outer(style_std, style_std)
    print(style_corr.round(2).to_string())

    print("\nFactor Volatilities (annualized %):")
    print((np.sqrt(np.diag(style_cov)) * np.sqrt(252) * 100).round(2))

    # Save results
    print("\n" + "=" * 70)
    print("SAVING RESULTS")
    print("=" * 70)

    model.factor_ret.to_csv('data/model/barra_factor_returns.csv')
    print("  Saved: data/model/barra_factor_returns.csv")

    final_cov.to_csv('data/model/barra_factor_covariance.csv')
    print("  Saved: data/model/barra_factor_covariance.csv")

    stats.to_csv('data/model/barra_factor_statistics.csv')
    print("  Saved: data/model/barra_factor_statistics.csv")

    model.R2.to_csv('data/model/barra_r2.csv')
    print("  Saved: data/model/barra_r2.csv")

    print("\n" + "=" * 70)
    print("COMPLETED")
    print("=" * 70)

    return model


if __name__ == '__main__':
    model = main()
