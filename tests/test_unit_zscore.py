"""Phase 2: Unit tests for z-scoring (zscore_by_date from fetch_data.py).

Creates synthetic data with known market caps and values,
verifies CW mean=0 and EW std=1 after z-scoring.

Note: zscore_by_date requires at least 10 valid stocks per date.
"""
import numpy as np
import pandas as pd
import pytest

from conftest import import_function

zscore_by_date = import_function("fetch_data.py", "zscore_by_date")


class TestZscoreByDate:
    def _make_df(self, values, market_caps, date="2025-01-01"):
        """Helper: build a DataFrame matching zscore_by_date's expected format."""
        n = len(values)
        return pd.DataFrame({
            "date": [date] * n,
            "ticker": [f"S{i}" for i in range(n)],
            "market_cap": market_caps,
            "test_raw": values,
        })

    def _make_10_stock_df(self, date="2025-01-01"):
        """10 stocks with known values and equal caps."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        caps = [1.0] * 10
        return self._make_df(values, caps, date), values, caps

    def test_cw_mean_zero(self):
        """After z-scoring, cap-weighted mean should be zero."""
        values = list(range(1, 16))  # 15 stocks
        caps = list(range(100, 1600, 100))  # different caps
        df = self._make_df(values, caps)

        result = zscore_by_date(df, ["test"])

        vals = result["test"]
        w = np.array(caps) / sum(caps)
        cw_mean = (w * vals.values).sum()
        assert abs(cw_mean) < 1e-10, f"CW mean = {cw_mean}"

    def test_ew_std_one(self):
        """After z-scoring, equal-weighted std should be one."""
        values = list(range(1, 16))
        caps = list(range(100, 1600, 100))
        df = self._make_df(values, caps)

        result = zscore_by_date(df, ["test"])

        ew_std = result["test"].std()
        assert abs(ew_std - 1.0) < 1e-10, f"EW std = {ew_std}"

    def test_hand_calculated_equal_caps(self):
        """With equal caps, z-score = (val - mean) / std."""
        df, values, caps = self._make_10_stock_df()
        result = zscore_by_date(df, ["test"])
        zscores = result["test"].values

        # Equal caps → CW mean = simple mean = 5.5
        # EW std = std([1..10], ddof=1) = 3.02765...
        arr = np.array(values)
        expected = (arr - arr.mean()) / arr.std(ddof=1)
        np.testing.assert_allclose(zscores, expected, atol=1e-10)

    def test_unequal_caps(self):
        """With unequal caps, CW mean != simple mean."""
        # 10 stocks: values 1-10, caps heavily weighted toward stock 0
        values = list(range(1, 11))
        caps = [1000.0] + [1.0] * 9  # Stock 0 dominates cap weight
        df = self._make_df(values, caps)

        result = zscore_by_date(df, ["test"])
        z = result["test"].values

        arr = np.array(values, dtype=float)
        cap_arr = np.array(caps)
        w = cap_arr / cap_arr.sum()
        cw_mean = (w * arr).sum()  # ≈ 1.0 (dominated by stock 0)
        ew_std = arr.std(ddof=1)
        expected = (arr - cw_mean) / ew_std
        np.testing.assert_allclose(z, expected, atol=1e-10)

        # Verify CW mean of z-scores is zero
        cw_mean_z = (w * z).sum()
        assert abs(cw_mean_z) < 1e-10

    def test_nan_handling(self):
        """NaN values should remain NaN after z-scoring."""
        # 12 stocks, one with NaN
        values = [1.0, np.nan, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0]
        caps = [1.0] * 12
        df = self._make_df(values, caps)

        result = zscore_by_date(df, ["test"])

        assert pd.isna(result["test"].iloc[1]), "NaN should be preserved"
        assert result["test"].notna().sum() == 11

    def test_multiple_dates(self):
        """Z-scoring should be independent per date."""
        n = 10
        df = pd.DataFrame({
            "date": ["2025-01-01"] * n + ["2025-01-02"] * n,
            "ticker": [f"S{i}" for i in range(n)] * 2,
            "market_cap": [1.0] * (2 * n),
            "test_raw": list(range(1, n + 1)) + list(range(101, 101 + n)),
        })

        result = zscore_by_date(df, ["test"])

        d1 = result[result["date"] == "2025-01-01"]["test"].values
        d2 = result[result["date"] == "2025-01-02"]["test"].values

        # Equal caps → standard z-scores within each date
        arr1 = np.arange(1.0, n + 1)
        arr2 = np.arange(101.0, 101 + n)
        exp1 = (arr1 - arr1.mean()) / arr1.std(ddof=1)
        exp2 = (arr2 - arr2.mean()) / arr2.std(ddof=1)
        np.testing.assert_allclose(d1, exp1, atol=1e-10)
        np.testing.assert_allclose(d2, exp2, atol=1e-10)

    def test_fewer_than_10_returns_zeros(self):
        """With fewer than 10 valid stocks, should return all zeros."""
        values = [1.0, 2.0, 3.0]
        caps = [1.0, 1.0, 1.0]
        df = self._make_df(values, caps)

        result = zscore_by_date(df, ["test"])

        assert (result["test"] == 0.0).all()
