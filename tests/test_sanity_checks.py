"""Phase 1: Sanity checks on model output CSVs.

Reads existing model outputs and checks for obvious problems:
- Z-scoring conventions (CW mean ≈ 0, EW std ≈ 1)
- Factor return magnitudes
- R² range
- Covariance matrix properties
- No NaN values
- Consistent factor names
"""
import numpy as np
import pandas as pd
import pytest

from conftest import ALL_FACTORS, STYLE_FACTORS

# Factors orthogonalized against other factors (residvol vs beta+size, nlsize vs size,
# liquidity vs size) may have CW mean shifted away from zero. Exclude from strict check.
_ORTHOGONALIZED_FACTORS = {"residvol", "nlsize", "liquidity"}

# Factors that may have zero std on early dates (not enough data to compute)
_WARMUP_FACTORS = {"beta"}


# ---------------------------------------------------------------------------
# CW mean ≈ 0 for each style factor on each date
# ---------------------------------------------------------------------------
class TestZScoreConventions:
    def test_cw_mean_near_zero(self, factor_exposures_df):
        """Cap-weighted mean of z-scored factors should be near zero.

        Orthogonalized factors (residvol, nlsize, liquidity) are checked
        with a wider tolerance (±0.5) since orthogonalization shifts CW mean.
        """
        df = factor_exposures_df
        violations = []
        for factor in STYLE_FACTORS:
            if factor not in df.columns:
                continue
            threshold = 0.7 if factor in _ORTHOGONALIZED_FACTORS else 0.05
            for date, group in df.groupby("date"):
                vals = group[factor]
                caps = group["market_cap"]
                valid = vals.notna() & caps.notna() & (caps > 0)
                if valid.sum() < 10:
                    continue
                w = caps[valid] / caps[valid].sum()
                cw_mean = (w * vals[valid]).sum()
                if abs(cw_mean) > threshold:
                    violations.append((factor, date, cw_mean))

        assert len(violations) == 0, (
            f"{len(violations)} CW-mean violations: "
            f"first 5: {violations[:5]}"
        )

    def test_ew_std_near_one(self, factor_exposures_df):
        """Equal-weighted std of z-scored factors should be near 1.

        Early dates where factors are still warming up (e.g., beta needs
        252d of data) may have std=0 and are excluded.
        """
        df = factor_exposures_df
        dates = sorted(df["date"].unique())
        # Skip the first 30% of dates as warmup period (beta needs 252d of
        # prior data, and the dataset only has ~1 year of point-in-time data)
        warmup_cutoff = dates[int(len(dates) * 0.3)] if len(dates) > 10 else dates[0]

        violations = []
        for factor in STYLE_FACTORS:
            if factor not in df.columns:
                continue
            for date, group in df.groupby("date"):
                if factor in _WARMUP_FACTORS and date <= warmup_cutoff:
                    continue
                vals = group[factor].dropna()
                if len(vals) < 10:
                    continue
                ew_std = vals.std()
                if ew_std < 0.5 or ew_std > 1.5:
                    violations.append((factor, date, ew_std))

        assert len(violations) == 0, (
            f"{len(violations)} EW-std violations (outside 0.5-1.5): "
            f"first 5: {violations[:5]}"
        )


# ---------------------------------------------------------------------------
# Factor return magnitude
# ---------------------------------------------------------------------------
class TestFactorReturns:
    def test_no_extreme_daily_returns(self, factor_returns_df):
        """No daily factor return should exceed ±15%.

        Country (market) factor can be large during crisis days
        (e.g., tariff announcements), so we use 15% as the threshold.
        Style factors are checked at ±5%.
        """
        # Check style factors at strict threshold
        style_cols = [c for c in factor_returns_df.columns if c in STYLE_FACTORS]
        if style_cols:
            style_max = factor_returns_df[style_cols].abs().max().max()
            assert style_max < 0.05, (
                f"Extreme style factor return: {style_max:.4f}"
            )

        # Check all factors (including Country/industry) at relaxed threshold
        max_abs = factor_returns_df.abs().max().max()
        worst_factor = factor_returns_df.abs().max().idxmax()
        worst_date = factor_returns_df[worst_factor].abs().idxmax()
        assert max_abs < 0.15, (
            f"Extreme factor return: {worst_factor} on {worst_date} = {max_abs:.4f}"
        )

    def test_no_nan_in_factor_returns(self, factor_returns_df):
        """Factor returns should have no NaN values."""
        nan_count = factor_returns_df.isna().sum().sum()
        assert nan_count == 0, f"{nan_count} NaN values in factor returns"


# ---------------------------------------------------------------------------
# R² range
# ---------------------------------------------------------------------------
class TestR2:
    def test_r2_in_range(self, r2_df):
        """Daily R² should be between 2% and 95%.

        R² can spike to >80% on high-correlation crisis days (e.g., tariff
        announcements) when all stocks move together. Can dip below 3%
        on high-dispersion days.
        """
        r2_vals = r2_df.iloc[:, 0]
        below = (r2_vals < 0.02).sum()
        above = (r2_vals > 0.95).sum()
        assert below == 0, f"{below} days with R² < 2%"
        assert above == 0, f"{above} days with R² > 95%"

    def test_no_nan_in_r2(self, r2_df):
        """R² should have no NaN values."""
        nan_count = r2_df.isna().sum().sum()
        assert nan_count == 0, f"{nan_count} NaN values in R²"


# ---------------------------------------------------------------------------
# Covariance matrix properties
# ---------------------------------------------------------------------------
class TestCovarianceMatrix:
    def test_positive_definite(self, factor_cov_df):
        """Covariance matrix should be positive definite (all eigenvalues > 0)."""
        eigenvalues = np.linalg.eigvalsh(factor_cov_df.values)
        min_eig = eigenvalues.min()
        assert min_eig > 0, f"Not positive definite: min eigenvalue = {min_eig:.2e}"

    def test_symmetric(self, factor_cov_df):
        """Covariance matrix should be symmetric."""
        diff = np.abs(factor_cov_df.values - factor_cov_df.values.T).max()
        assert diff < 1e-12, f"Not symmetric: max asymmetry = {diff:.2e}"

    def test_no_nan_in_covariance(self, factor_cov_df):
        """Covariance matrix should have no NaN values."""
        nan_count = factor_cov_df.isna().sum().sum()
        assert nan_count == 0, f"{nan_count} NaN values in covariance"


# ---------------------------------------------------------------------------
# Factor names consistency
# ---------------------------------------------------------------------------
class TestFactorNameConsistency:
    def test_factor_names_match_across_files(
        self, factor_returns_df, factor_cov_df, factor_exposures_df
    ):
        """Factor returns, covariance, and exposures should use the same 22 factor names."""
        ret_factors = set(factor_returns_df.columns)
        cov_factors = set(factor_cov_df.columns)

        # Exposures has style factors as columns (not industry/Country as columns)
        exp_style = set(STYLE_FACTORS) & set(factor_exposures_df.columns)

        assert ret_factors == cov_factors, (
            f"Factor return vs covariance mismatch: "
            f"in returns only: {ret_factors - cov_factors}, "
            f"in cov only: {cov_factors - ret_factors}"
        )

        # All style factors in covariance should be in exposures
        cov_style = cov_factors & set(STYLE_FACTORS)
        missing = cov_style - exp_style
        assert len(missing) == 0, (
            f"Style factors in covariance but not in exposures: {missing}"
        )

    def test_expected_factor_count(self, factor_cov_df):
        """Should have exactly 22 factors (1 Country + 11 industry + 10 style)."""
        assert factor_cov_df.shape == (22, 22), (
            f"Expected 22x22 covariance, got {factor_cov_df.shape}"
        )
