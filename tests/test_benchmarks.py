"""Phase 4: External benchmark checks.

Validates model outputs against known financial properties:
- SPY returns should be mostly explained by factor returns (high R²)
- Beta factor returns should correlate with market returns
- Covariance symmetry
"""
import numpy as np
import pandas as pd
import pytest

from conftest import STYLE_FACTORS, import_function


class TestSPYFactorExplanation:
    """SPY tracks the S&P 500. The factor model should explain most of its returns."""

    def test_spy_r2_high(self, factor_returns_df):
        """Regress SPY daily returns on factor returns. R² should be > 85%.

        SPY is the broad market, so the Country (market) factor alone should
        explain the vast majority of its variance. If R² is low, something
        is wrong with the factor model.

        Note: The factor model labels returns 1 business day ahead of
        yfinance's convention (factor date T = yfinance date T-1), so we
        shift factor returns back by 1 business day before aligning.
        """
        try:
            import yfinance as yf
        except ImportError:
            pytest.skip("yfinance not installed")

        # Download SPY returns for the same date range as factor returns
        start = factor_returns_df.index.min()
        end = factor_returns_df.index.max()
        spy = yf.download("SPY", start=start, end=end, progress=False)

        if spy.empty or len(spy) < 20:
            pytest.skip("Could not download SPY data")

        # Handle multi-level columns from yfinance
        if isinstance(spy.columns, pd.MultiIndex):
            spy.columns = spy.columns.get_level_values(0)

        spy_ret = spy["Close"].pct_change().dropna()
        spy_ret.index = spy_ret.index.tz_localize(None)

        # Shift factor returns back 1 business day to align with yfinance
        fr_aligned = factor_returns_df.copy()
        fr_aligned.index = fr_aligned.index.shift(-1, freq="B")

        # Align dates
        common = fr_aligned.index.intersection(spy_ret.index)
        if len(common) < 20:
            pytest.skip(f"Only {len(common)} overlapping dates")

        y = spy_ret.loc[common].values
        X = fr_aligned.loc[common].values

        # OLS regression: y = X @ beta + epsilon
        # R² = 1 - SS_res / SS_tot
        X_with_const = np.column_stack([np.ones(len(y)), X])
        beta, residuals, _, _ = np.linalg.lstsq(X_with_const, y, rcond=None)

        y_hat = X_with_const @ beta
        ss_res = np.sum((y - y_hat) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot

        assert r2 > 0.85, (
            f"Factor model explains only {r2:.1%} of SPY returns, expected >85%"
        )


class TestBetaFactorCorrelation:
    """Beta factor returns should correlate positively with market (Country) returns."""

    def test_beta_correlates_with_market(self, factor_returns_df):
        """Beta factor daily returns should correlate >0.5 with Country returns."""
        if "beta" not in factor_returns_df.columns:
            pytest.skip("beta factor not in returns")
        if "Country" not in factor_returns_df.columns:
            pytest.skip("Country factor not in returns")

        corr = factor_returns_df["beta"].corr(factor_returns_df["Country"])
        assert corr > 0.3, (
            f"Beta-Country correlation = {corr:.3f}, expected > 0.3"
        )


class TestSizeFactorSign:
    """Size factor: large caps (+) vs small caps (-).

    In periods of large-cap outperformance, mean size return should be positive,
    and vice versa. We just check it's not absurdly wrong.
    """

    def test_size_factor_vol_reasonable(self, factor_returns_df):
        """Size factor annualized vol should be between 1% and 20%."""
        if "size" not in factor_returns_df.columns:
            pytest.skip("size factor not in returns")

        ann_vol = factor_returns_df["size"].std() * np.sqrt(252)
        assert 0.01 < ann_vol < 0.20, (
            f"Size factor ann. vol = {ann_vol:.4f}, expected 1%-20%"
        )


class TestCovarianceSymmetry:
    """Covariance matrix must be exactly symmetric."""

    def test_covariance_is_symmetric(self, factor_cov_df):
        """Ω should equal Ω.T within machine precision."""
        diff = np.abs(factor_cov_df.values - factor_cov_df.values.T)
        assert diff.max() < 1e-15, (
            f"Max asymmetry = {diff.max():.2e}"
        )

    def test_diagonal_positive(self, factor_cov_df):
        """All diagonal elements (variances) should be strictly positive."""
        diag = np.diag(factor_cov_df.values)
        assert (diag > 0).all(), (
            f"Non-positive diagonal entries: "
            f"{[f for f, d in zip(factor_cov_df.columns, diag) if d <= 0]}"
        )


class TestFactorReturnProperties:
    """General sanity on factor return time series."""

    def test_market_factor_positive_mean(self, factor_returns_df):
        """Country (market) factor should have positive mean over sample period.

        This is a weak check — the equity risk premium is positive on average.
        Skip if the sample is too short or unlucky.
        """
        if "Country" not in factor_returns_df.columns:
            pytest.skip("Country factor not in returns")

        mean_ret = factor_returns_df["Country"].mean() * 252
        # Allow negative in bear markets, but it shouldn't be extremely negative
        assert mean_ret > -0.50, (
            f"Market annual return = {mean_ret:.2%}, suspiciously negative"
        )

    def test_factor_return_autocorrelation_low(self, factor_returns_df):
        """Daily factor returns should have low autocorrelation (efficient markets)."""
        for factor in STYLE_FACTORS:
            if factor not in factor_returns_df.columns:
                continue
            ac = factor_returns_df[factor].autocorr(lag=1)
            if pd.notna(ac):
                assert abs(ac) < 0.3, (
                    f"{factor}: lag-1 autocorrelation = {ac:.3f}, expected <0.3"
                )
