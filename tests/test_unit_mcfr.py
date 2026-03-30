"""Phase 2: Unit tests for MCFR (Marginal Contribution to Factor Risk).

Tests compute_mcfr() from manage_risk.py with synthetic data.
"""
import numpy as np
import pandas as pd
import pytest

from conftest import import_function

compute_mcfr = import_function("manage_risk.py", "compute_mcfr")


class TestComputeMCFR:
    @pytest.fixture
    def setup_3stock_3factor(self):
        """3 stocks, 3 factors with known answer.

        weights = [0.5, 0.3, 0.2]
        B (3 stocks × 3 factors):
            Stock0: [1.0,  0.0, 0.5]
            Stock1: [0.0,  1.0, -0.5]
            Stock2: [-1.0, 0.5, 0.0]

        Ω_f = diag(0.04, 0.01, 0.02) (3×3 diagonal)

        b = B' @ w = [1*0.5 + 0*0.3 + (-1)*0.2,
                       0*0.5 + 1*0.3 + 0.5*0.2,
                       0.5*0.5 + (-0.5)*0.3 + 0*0.2]
                   = [0.3, 0.4, 0.1]

        factor_var = b' Ω b = 0.3²×0.04 + 0.4²×0.01 + 0.1²×0.02
                    = 0.0036 + 0.0016 + 0.0002 = 0.0054

        factor_vol = sqrt(0.0054) = 0.07348...

        Ω_f @ b = [0.3×0.04, 0.4×0.01, 0.1×0.02] = [0.012, 0.004, 0.002]

        B @ (Ω_f @ b) = [1*0.012 + 0*0.004 + 0.5*0.002,
                          0*0.012 + 1*0.004 + (-0.5)*0.002,
                          (-1)*0.012 + 0.5*0.004 + 0*0.002]
                       = [0.013, 0.003, -0.010]

        MCFR = B @ Ω_f @ b / factor_vol
        """
        tickers = ["S0", "S1", "S2"]
        factors = ["F1", "F2", "F3"]

        weights = pd.Series([0.5, 0.3, 0.2], index=tickers)
        betas = pd.DataFrame(
            [[1.0, 0.0, 0.5], [0.0, 1.0, -0.5], [-1.0, 0.5, 0.0]],
            index=tickers, columns=factors,
        )
        factor_cov = pd.DataFrame(
            np.diag([0.04, 0.01, 0.02]),
            index=factors, columns=factors,
        )

        # Pre-computed expected values
        b = np.array([0.3, 0.4, 0.1])
        factor_var = 0.3**2 * 0.04 + 0.4**2 * 0.01 + 0.1**2 * 0.02
        factor_vol = np.sqrt(factor_var)
        omega_b = np.array([0.012, 0.004, 0.002])
        B_omega_b = np.array([0.013, 0.003, -0.010])
        expected_mcfr = B_omega_b / factor_vol

        return weights, betas, factor_cov, b, factor_var, expected_mcfr

    def test_portfolio_exposure(self, setup_3stock_3factor):
        """b = B' @ w should be correct."""
        weights, betas, factor_cov, b_expected, _, _ = setup_3stock_3factor
        _, b, _ = compute_mcfr(weights, betas, factor_cov)
        np.testing.assert_allclose(b, b_expected, atol=1e-10)

    def test_factor_variance(self, setup_3stock_3factor):
        """factor_var = b' Ω b should be correct."""
        weights, betas, factor_cov, _, fvar_expected, _ = setup_3stock_3factor
        _, _, factor_var = compute_mcfr(weights, betas, factor_cov)
        np.testing.assert_allclose(factor_var, fvar_expected, rtol=1e-10)

    def test_mcfr_values(self, setup_3stock_3factor):
        """MCFR for each stock should match hand calculation."""
        weights, betas, factor_cov, _, _, mcfr_expected = setup_3stock_3factor
        mcfr, _, _ = compute_mcfr(weights, betas, factor_cov)
        np.testing.assert_allclose(mcfr.values, mcfr_expected, rtol=1e-6)

    def test_mcfr_sums_to_factor_vol(self, setup_3stock_3factor):
        """Weighted MCFR should sum to factor vol: w' @ MCFR = factor_vol."""
        weights, betas, factor_cov, _, fvar_expected, _ = setup_3stock_3factor
        mcfr, _, _ = compute_mcfr(weights, betas, factor_cov)
        factor_vol = np.sqrt(fvar_expected)
        weighted_sum = (weights * mcfr).sum()
        np.testing.assert_allclose(weighted_sum, factor_vol, rtol=1e-6)

    def test_zero_weights(self):
        """All-zero weights should give zero MCFR."""
        tickers = ["S0", "S1"]
        factors = ["F1"]
        weights = pd.Series([0.0, 0.0], index=tickers)
        betas = pd.DataFrame([[1.0], [0.5]], index=tickers, columns=factors)
        factor_cov = pd.DataFrame([[0.04]], index=factors, columns=factors)

        mcfr, b, fvar = compute_mcfr(weights, betas, factor_cov)
        assert fvar == 0.0
        assert (mcfr == 0).all()

    def test_single_stock(self):
        """Single stock portfolio: MCFR should equal factor vol."""
        tickers = ["S0"]
        factors = ["F1", "F2"]
        weights = pd.Series([1.0], index=tickers)
        betas = pd.DataFrame([[2.0, -1.0]], index=tickers, columns=factors)
        factor_cov = pd.DataFrame(
            np.diag([0.04, 0.01]), index=factors, columns=factors,
        )

        mcfr, b, fvar = compute_mcfr(weights, betas, factor_cov)
        factor_vol = np.sqrt(fvar)
        # Single stock with weight=1: w @ MCFR = factor_vol
        np.testing.assert_allclose(mcfr.values[0], factor_vol, rtol=1e-10)
