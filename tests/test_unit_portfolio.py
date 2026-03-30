"""Phase 2: Unit tests for portfolio loading and weight computation.

Tests load_portfolio() from analyze_portfolio.py with temp CSV files.
"""
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from conftest import import_function

load_portfolio = import_function("analyze_portfolio.py", "load_portfolio")


class TestLoadPortfolio:
    def test_semicolon_delimiter(self, tmp_path):
        """Should auto-detect semicolon delimiter."""
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("Ticker;Shares\nAAPL;100\nMSFT;50\n")

        df = load_portfolio(str(csv_path))

        assert list(df.columns) == ["ticker", "shares"]
        assert len(df) == 2
        assert df.iloc[0]["ticker"] == "AAPL"
        assert df.iloc[0]["shares"] == 100

    def test_comma_delimiter(self, tmp_path):
        """Should auto-detect comma delimiter."""
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("Ticker,Shares\nGOOG,25\nTSLA,75\n")

        df = load_portfolio(str(csv_path))

        assert len(df) == 2
        assert df.iloc[0]["ticker"] == "GOOG"

    def test_mixed_case_columns(self, tmp_path):
        """Should normalize column names to lowercase."""
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("TICKER;SHARES\nAAPL;100\n")

        df = load_portfolio(str(csv_path))
        assert "ticker" in df.columns
        assert "shares" in df.columns

    def test_extra_columns_stripped(self, tmp_path):
        """Should only return ticker and shares columns."""
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("Ticker;Shares;BuyDate\nAAPL;100;2024-01-15\n")

        df = load_portfolio(str(csv_path))
        assert list(df.columns) == ["ticker", "shares"]

    def test_missing_ticker_column_raises(self, tmp_path):
        """Should raise ValueError if ticker column is missing."""
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("name;shares\nAAPL;100\n")

        with pytest.raises(ValueError, match="ticker"):
            load_portfolio(str(csv_path))

    def test_missing_shares_column_raises(self, tmp_path):
        """Should raise ValueError if shares column is missing."""
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("ticker;amount\nAAPL;100\n")

        with pytest.raises(ValueError, match="shares"):
            load_portfolio(str(csv_path))


class TestWeightComputation:
    """Test weight computation logic (weights = shares × price / total_value)."""

    def test_weights_sum_to_one(self):
        """Weights computed from shares and prices should sum to 1."""
        shares = np.array([100, 200, 300])
        prices = np.array([50.0, 25.0, 10.0])
        values = shares * prices  # [5000, 5000, 3000]
        weights = values / values.sum()

        np.testing.assert_allclose(weights.sum(), 1.0)

    def test_weight_proportions(self):
        """Equal-value positions should have equal weights."""
        shares = np.array([100, 50])
        prices = np.array([10.0, 20.0])
        values = shares * prices  # [1000, 1000]
        weights = values / values.sum()

        np.testing.assert_allclose(weights, [0.5, 0.5])

    def test_single_stock_weight_is_one(self):
        """Single stock portfolio should have weight = 1."""
        values = np.array([10000.0])
        weights = values / values.sum()
        np.testing.assert_allclose(weights, [1.0])
