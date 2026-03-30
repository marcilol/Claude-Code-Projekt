"""Phase 2: Unit tests for the 4 alpha sizing methods.

Tests size_proportional, size_risk_parity, size_mean_variance, size_shrunk_mv
from size_positions.py with known inputs.
"""
import numpy as np
import pytest

from conftest import import_function

size_proportional = import_function("size_positions.py", "size_proportional")
size_risk_parity = import_function("size_positions.py", "size_risk_parity")
size_mean_variance = import_function("size_positions.py", "size_mean_variance")
size_shrunk_mv = import_function("size_positions.py", "size_shrunk_mv")


class TestSizeProportional:
    def test_weights_proportional_to_alpha(self):
        """NMV should be proportional to alpha."""
        alphas = {"A": 0.10, "B": 0.20, "C": 0.30}
        gmv = 100_000
        result = size_proportional(alphas, gmv)

        # A:B:C should be 1:2:3
        assert abs(result["B"] / result["A"] - 2.0) < 1e-10
        assert abs(result["C"] / result["A"] - 3.0) < 1e-10

    def test_sums_to_gmv(self):
        """Total position size should equal target GMV."""
        alphas = {"A": 0.10, "B": 0.20}
        gmv = 50_000
        result = size_proportional(alphas, gmv)
        assert abs(sum(result.values()) - gmv) < 0.01

    def test_negative_alpha_excluded(self):
        """Stocks with negative alpha should get zero allocation."""
        alphas = {"A": 0.10, "B": -0.05, "C": 0.20}
        gmv = 100_000
        result = size_proportional(alphas, gmv)
        assert result["B"] == 0.0
        assert abs(sum(result.values()) - gmv) < 0.01

    def test_all_negative_alphas(self):
        """If all alphas are negative, should equal-weight."""
        alphas = {"A": -0.10, "B": -0.20}
        gmv = 100_000
        result = size_proportional(alphas, gmv)
        assert abs(result["A"] - 50_000) < 0.01
        assert abs(result["B"] - 50_000) < 0.01


class TestSizeRiskParity:
    def test_scales_by_alpha_over_sigma(self):
        """NMV should be proportional to alpha/sigma."""
        alphas = {"A": 0.20, "B": 0.20}
        vols = {"A": 0.40, "B": 0.20}
        gmv = 100_000
        result = size_risk_parity(alphas, vols, gmv)

        # A: 0.20/0.40 = 0.5, B: 0.20/0.20 = 1.0 → B gets 2x A
        assert abs(result["B"] / result["A"] - 2.0) < 1e-6

    def test_sums_to_gmv(self):
        """Total should equal target GMV."""
        alphas = {"A": 0.10, "B": 0.20, "C": 0.30}
        vols = {"A": 0.30, "B": 0.25, "C": 0.40}
        gmv = 200_000
        result = size_risk_parity(alphas, vols, gmv)
        assert abs(sum(result.values()) - gmv) < 0.01

    def test_high_vol_gets_less(self):
        """Higher vol stock with same alpha should get less."""
        alphas = {"A": 0.10, "B": 0.10}
        vols = {"A": 0.20, "B": 0.60}
        gmv = 100_000
        result = size_risk_parity(alphas, vols, gmv)
        assert result["A"] > result["B"]


class TestSizeMeanVariance:
    def test_scales_by_alpha_over_sigma_sq(self):
        """NMV should be proportional to alpha/sigma²."""
        alphas = {"A": 0.20, "B": 0.20}
        vols = {"A": 0.40, "B": 0.20}
        gmv = 100_000
        result = size_mean_variance(alphas, vols, gmv)

        # A: 0.20/0.16 = 1.25, B: 0.20/0.04 = 5.0 → B gets 4x A
        assert abs(result["B"] / result["A"] - 4.0) < 1e-6

    def test_sums_to_gmv(self):
        """Total should equal target GMV."""
        alphas = {"A": 0.10, "B": 0.20}
        vols = {"A": 0.30, "B": 0.25}
        gmv = 150_000
        result = size_mean_variance(alphas, vols, gmv)
        assert abs(sum(result.values()) - gmv) < 0.01

    def test_penalizes_vol_more_than_risk_parity(self):
        """MV should penalize high-vol stocks more aggressively than risk parity."""
        alphas = {"A": 0.20, "B": 0.20}
        vols = {"A": 0.20, "B": 0.60}
        gmv = 100_000

        rp = size_risk_parity(alphas, vols, gmv)
        mv = size_mean_variance(alphas, vols, gmv)

        rp_ratio = rp["A"] / rp["B"]
        mv_ratio = mv["A"] / mv["B"]
        assert mv_ratio > rp_ratio  # MV penalizes B's high vol more


class TestSizeShrunkMV:
    def test_shrinkage_effect(self):
        """With shrinkage, high-vol stock's penalty should be partially offset."""
        alphas = {"A": 0.20, "B": 0.20}
        vols = {"A": 0.20, "B": 0.60}
        sector_vols = {"Tech": 0.30}
        sectors = {"A": "Tech", "B": "Tech"}
        gmv = 100_000

        mv = size_mean_variance(alphas, vols, gmv)
        smv = size_shrunk_mv(alphas, vols, sector_vols, sectors, gmv, shrink=0.75)

        # Shrunk MV should be less extreme than pure MV
        mv_ratio = mv["A"] / mv["B"]
        smv_ratio = smv["A"] / smv["B"]
        assert smv_ratio < mv_ratio  # Shrinkage reduces the penalty on B

    def test_sums_to_gmv(self):
        """Total should equal target GMV."""
        alphas = {"A": 0.10, "B": 0.20, "C": 0.30}
        vols = {"A": 0.30, "B": 0.25, "C": 0.40}
        sector_vols = {"X": 0.30}
        sectors = {"A": "X", "B": "X", "C": "X"}
        gmv = 100_000
        result = size_shrunk_mv(alphas, vols, sector_vols, sectors, gmv)
        assert abs(sum(result.values()) - gmv) < 0.01

    def test_shrink_zero_equals_sector_vol(self):
        """With shrink=0, should use only sector vol (all stocks get same σ²)."""
        alphas = {"A": 0.10, "B": 0.20}
        vols = {"A": 0.50, "B": 0.10}  # Very different
        sector_vols = {"S1": 0.30}
        sectors = {"A": "S1", "B": "S1"}
        gmv = 100_000

        # shrink=0 → denominator = sector_vol² for all → NMV ∝ alpha
        result = size_shrunk_mv(alphas, vols, sector_vols, sectors, gmv, shrink=0.0)
        assert abs(result["B"] / result["A"] - 2.0) < 1e-6

    def test_shrink_one_equals_mv(self):
        """With shrink=1, should equal pure mean-variance."""
        alphas = {"A": 0.10, "B": 0.20}
        vols = {"A": 0.30, "B": 0.25}
        sector_vols = {"S1": 0.30}
        sectors = {"A": "S1", "B": "S1"}
        gmv = 100_000

        mv = size_mean_variance(alphas, vols, gmv)
        smv = size_shrunk_mv(alphas, vols, sector_vols, sectors, gmv, shrink=1.0)

        for k in alphas:
            np.testing.assert_allclose(smv[k], mv[k], rtol=1e-6)
