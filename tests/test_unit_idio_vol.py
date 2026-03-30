"""Phase 2: Unit tests for idiosyncratic volatility computation.

Tests compute_idiosyncratic_volatility() from analyze_portfolio.py
with synthetic factor returns and stock data.
"""
import numpy as np
import pandas as pd
import pytest

from conftest import import_function

compute_idiosyncratic_volatility = import_function(
    "analyze_portfolio.py", "compute_idiosyncratic_volatility"
)


class TestIdiosyncraticVolatility:
    @pytest.fixture
    def synthetic_data(self):
        """Create synthetic data where residuals are known.

        Setup:
        - 1 stock "TEST" in sector "Financials"
        - 60 trading days
        - Factor returns: Country=0.001/day, Financials=0.0005/day, all style=0
        - Stock has beta exposure = 0 for all style factors
        - Stock actual return = predicted + epsilon
        - epsilon ~ known std (we'll use fixed values)
        """
        np.random.seed(42)
        n_days = 60
        dates = pd.bdate_range("2025-01-01", periods=n_days)

        style_factors = [
            "size", "beta", "momentum", "residvol", "nlsize",
            "btop", "liquidity", "earnyild", "growth", "leverage",
        ]

        # Factor returns: Country and Financials have positive returns
        factor_ret_data = {
            "Country": np.full(n_days, 0.001),
            "Financials": np.full(n_days, 0.0005),
        }
        # Other industry factors
        for ind in ["Communication", "Consumer Discretionary", "Consumer Staples",
                     "Energy", "Health Care", "Industrials",
                     "Information Technology", "Materials", "Real Estate", "Utilities"]:
            factor_ret_data[ind] = np.zeros(n_days)
        # Style factor returns = 0
        for sf in style_factors:
            factor_ret_data[sf] = np.zeros(n_days)

        factor_ret_df = pd.DataFrame(factor_ret_data, index=dates)

        # Known residuals with known std
        known_residuals = np.random.normal(0, 0.02, n_days)  # daily std ≈ 0.02
        actual_std = np.std(known_residuals)

        # Stock returns = Country + Financials + residual
        stock_returns = 0.001 + 0.0005 + known_residuals

        # Factor exposures DataFrame (style factor betas all = 0)
        exp_data = {
            "date": dates,
            "ticker": ["TEST"] * n_days,
            "sector": ["Financials"] * n_days,
            "return": stock_returns,
            "market_cap": [1e9] * n_days,
        }
        for sf in style_factors:
            exp_data[sf] = np.zeros(n_days)

        factor_exp_df = pd.DataFrame(exp_data)

        expected_idio_vol = actual_std * np.sqrt(252)

        return ["TEST"], factor_exp_df, factor_ret_df, expected_idio_vol

    def test_idio_vol_matches_known_residuals(self, synthetic_data):
        """Idio vol should match std(known residuals) × √252."""
        tickers, exp_df, ret_df, expected = synthetic_data
        result = compute_idiosyncratic_volatility(tickers, exp_df, ret_df)

        assert "TEST" in result
        np.testing.assert_allclose(result["TEST"], expected, rtol=0.01)

    def test_pure_factor_stock_has_zero_idio(self):
        """A stock whose returns are purely factor-driven should have ~0 idio vol."""
        n_days = 60
        dates = pd.bdate_range("2025-01-01", periods=n_days)
        style_factors = [
            "size", "beta", "momentum", "residvol", "nlsize",
            "btop", "liquidity", "earnyild", "growth", "leverage",
        ]

        # Factor returns
        factor_ret_data = {"Country": np.full(n_days, 0.001)}
        for ind in ["Communication", "Consumer Discretionary", "Consumer Staples",
                     "Energy", "Financials", "Health Care", "Industrials",
                     "Information Technology", "Materials", "Real Estate", "Utilities"]:
            factor_ret_data[ind] = np.zeros(n_days)
        for sf in style_factors:
            factor_ret_data[sf] = np.zeros(n_days)
        factor_ret_df = pd.DataFrame(factor_ret_data, index=dates)

        # Stock return = exactly Country + Energy (no residual)
        factor_ret_data_energy = np.full(n_days, 0.0003)
        factor_ret_df["Energy"] = factor_ret_data_energy

        stock_returns = 0.001 + factor_ret_data_energy  # exact match

        exp_data = {
            "date": dates,
            "ticker": ["PURE"] * n_days,
            "sector": ["Energy"] * n_days,
            "return": stock_returns,
            "market_cap": [1e9] * n_days,
        }
        for sf in style_factors:
            exp_data[sf] = np.zeros(n_days)

        factor_exp_df = pd.DataFrame(exp_data)

        result = compute_idiosyncratic_volatility(["PURE"], factor_exp_df, factor_ret_df)
        assert result["PURE"] < 0.01  # Should be nearly zero

    def test_insufficient_data_returns_nan(self):
        """Stocks with fewer than 20 observations should return NaN."""
        dates = pd.bdate_range("2025-01-01", periods=10)
        style_factors = [
            "size", "beta", "momentum", "residvol", "nlsize",
            "btop", "liquidity", "earnyild", "growth", "leverage",
        ]

        factor_ret_data = {"Country": np.zeros(10)}
        for ind in ["Communication", "Consumer Discretionary", "Consumer Staples",
                     "Energy", "Financials", "Health Care", "Industrials",
                     "Information Technology", "Materials", "Real Estate", "Utilities"]:
            factor_ret_data[ind] = np.zeros(10)
        for sf in style_factors:
            factor_ret_data[sf] = np.zeros(10)
        factor_ret_df = pd.DataFrame(factor_ret_data, index=dates)

        exp_data = {
            "date": dates,
            "ticker": ["SHORT"] * 10,
            "sector": ["Energy"] * 10,
            "return": np.zeros(10),
            "market_cap": [1e9] * 10,
        }
        for sf in style_factors:
            exp_data[sf] = np.zeros(10)
        factor_exp_df = pd.DataFrame(exp_data)

        result = compute_idiosyncratic_volatility(["SHORT"], factor_exp_df, factor_ret_df)
        assert pd.isna(result["SHORT"])
