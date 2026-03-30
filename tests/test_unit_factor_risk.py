"""Phase 2: Unit tests for factor risk calculation.

Tests calculate_factor_risk() from analyze_portfolio.py
with a small hand-built 3-factor, 3-stock example.
"""
import numpy as np
import pytest

from conftest import import_function

calculate_factor_risk = import_function("analyze_portfolio.py", "calculate_factor_risk")


class TestCalculateFactorRisk:
    @pytest.fixture
    def setup_3factor(self):
        """3-factor example with known answer.

        Factors: F1, F2, F3
        Portfolio exposures: b = [1.0, 0.5, -0.3]
        Covariance (diagonal for simplicity):
            Ω = diag(0.04, 0.01, 0.02)

        factor_var = b' Ω b = 1²×0.04 + 0.5²×0.01 + (-0.3)²×0.02
                    = 0.04 + 0.0025 + 0.0018 = 0.0443
        """
        factor_names = ["F1", "F2", "F3"]
        exposures = {"F1": 1.0, "F2": 0.5, "F3": -0.3}
        cov = np.diag([0.04, 0.01, 0.02])
        expected_var = 1.0**2 * 0.04 + 0.5**2 * 0.01 + 0.3**2 * 0.02
        return exposures, cov, factor_names, expected_var

    def test_factor_variance(self, setup_3factor):
        """factor_variance = b' Ω b."""
        exposures, cov, factor_names, expected_var = setup_3factor
        factor_var, risk_contrib, exp_vec = calculate_factor_risk(
            exposures, cov, factor_names
        )
        np.testing.assert_allclose(factor_var, expected_var, rtol=1e-10)

    def test_risk_contrib_sums_to_variance(self, setup_3factor):
        """Sum of risk contributions should equal factor variance."""
        exposures, cov, factor_names, _ = setup_3factor
        factor_var, risk_contrib, _ = calculate_factor_risk(
            exposures, cov, factor_names
        )
        np.testing.assert_allclose(risk_contrib.sum(), factor_var, rtol=1e-10)

    def test_exposure_vector_order(self, setup_3factor):
        """Exposure vector should match factor_names order."""
        exposures, cov, factor_names, _ = setup_3factor
        _, _, exp_vec = calculate_factor_risk(exposures, cov, factor_names)
        np.testing.assert_array_equal(exp_vec, [1.0, 0.5, -0.3])

    def test_zero_exposure(self):
        """All-zero exposures should give zero variance."""
        factor_names = ["F1", "F2"]
        exposures = {"F1": 0.0, "F2": 0.0}
        cov = np.diag([0.04, 0.01])

        factor_var, risk_contrib, _ = calculate_factor_risk(
            exposures, cov, factor_names
        )
        assert factor_var == 0.0

    def test_missing_factor_defaults_to_zero(self):
        """Factors not in exposures dict should be treated as zero."""
        factor_names = ["F1", "F2", "F3"]
        exposures = {"F1": 1.0}  # F2, F3 missing
        cov = np.diag([0.04, 0.01, 0.02])

        factor_var, _, exp_vec = calculate_factor_risk(
            exposures, cov, factor_names
        )
        # Only F1 contributes: 1²×0.04 = 0.04
        np.testing.assert_allclose(factor_var, 0.04, rtol=1e-10)
        np.testing.assert_array_equal(exp_vec, [1.0, 0.0, 0.0])

    def test_off_diagonal_covariance(self):
        """Test with non-diagonal covariance to verify full quadratic form."""
        factor_names = ["F1", "F2"]
        exposures = {"F1": 1.0, "F2": 1.0}
        # Ω = [[0.04, 0.01], [0.01, 0.02]]
        cov = np.array([[0.04, 0.01], [0.01, 0.02]])

        # b'Ωb = [1,1] @ [[0.04,0.01],[0.01,0.02]] @ [1,1]
        # = [0.05, 0.03] @ [1,1] = 0.08
        factor_var, _, _ = calculate_factor_risk(exposures, cov, factor_names)
        np.testing.assert_allclose(factor_var, 0.08, rtol=1e-10)
