# -*- coding: utf-8 -*-
"""
Phase 5: Excel Verification Tests

Reads values from the generated verification workbook (formula-driven version)
and compares Python Reference columns against independently computed values
to confirm the Excel formulas and Python produce identical results.

Requires: data/model/verification_workbook.xlsx (run generate_verification_excel.py first)
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.conftest import (
    import_function,
    MODEL_DIR,
    STYLE_FACTORS,
    INDUSTRY_FACTORS,
    ALL_FACTORS,
)

WORKBOOK_PATH = os.path.join(MODEL_DIR, "verification_workbook.xlsx")

SELECTED_TICKERS = sorted([
    "META", "CCOI", "AMZN", "ASO", "WMT", "FIZZ", "XOM", "WHD",
    "JPM", "PFS", "LLY", "TVTX", "GE", "MMS", "NVDA", "DLB",
    "LIN", "USLM", "NEE", "AES",
])

DATE_START = "2025-08-01"
DATE_END = "2025-08-31"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def workbook_exists():
    if not os.path.exists(WORKBOOK_PATH):
        pytest.skip("verification_workbook.xlsx not found — run generate_verification_excel.py first")


@pytest.fixture(scope="module")
def factor_exp_df():
    path = os.path.join(MODEL_DIR, "russell3000_factor_exposures_historical.csv")
    if not os.path.exists(path):
        pytest.skip("factor exposures CSV not found")
    return pd.read_csv(path, parse_dates=["date"])


@pytest.fixture(scope="module")
def factor_ret_df():
    path = os.path.join(MODEL_DIR, "barra_factor_returns.csv")
    if not os.path.exists(path):
        pytest.skip("factor returns CSV not found")
    return pd.read_csv(path, index_col=0)


@pytest.fixture(scope="module")
def factor_cov_df():
    path = os.path.join(MODEL_DIR, "barra_factor_covariance.csv")
    if not os.path.exists(path):
        pytest.skip("factor covariance CSV not found")
    return pd.read_csv(path, index_col=0)


@pytest.fixture(scope="module")
def xl_stocks(workbook_exists):
    return pd.read_excel(WORKBOOK_PATH, sheet_name="Stocks")


@pytest.fixture(scope="module")
def xl_covariance(workbook_exists):
    return pd.read_excel(WORKBOOK_PATH, sheet_name="Covariance", index_col=0)


@pytest.fixture(scope="module")
def xl_risk_decomp(workbook_exists):
    """Read RiskDecomp sheet as raw data (formulas not evaluated)."""
    return pd.read_excel(WORKBOOK_PATH, sheet_name="RiskDecomp", header=None)


@pytest.fixture(scope="module")
def xl_regression(workbook_exists):
    return pd.read_excel(WORKBOOK_PATH, sheet_name="Regression", header=None)


# ---------------------------------------------------------------------------
# Helper: extract Python reference values from RiskDecomp sheet
# ---------------------------------------------------------------------------
def _get_risk_decomp_refs(xl_risk_decomp):
    """Extract Python Reference values from column C of the RiskDecomp sheet."""
    df = xl_risk_decomp
    refs = {}

    # Section 1: Portfolio Factor Exposures (rows 4-25, 0-indexed: 3-24)
    # Col C (index 2) has Python reference exposures
    exposures = {}
    for i in range(22):
        row_idx = 3 + i  # 0-indexed row
        factor = df.iloc[row_idx, 0]
        py_val = df.iloc[row_idx, 2]
        if pd.notna(factor) and pd.notna(py_val):
            exposures[str(factor)] = float(py_val)
    refs["exposures"] = exposures

    # Section 2: Omega*b (rows 30-51, 0-indexed: 29-50)
    omega_b = {}
    for i in range(22):
        row_idx = 29 + i
        factor = df.iloc[row_idx, 0]
        py_val = df.iloc[row_idx, 2]
        if pd.notna(factor) and pd.notna(py_val):
            omega_b[str(factor)] = float(py_val)
    refs["omega_b"] = omega_b

    # Section 3: Risk contributions (rows 55-76, 0-indexed: 54-75)
    # Col F (index 5) has Python ref for contributions
    risk_contrib = {}
    for i in range(22):
        row_idx = 54 + i
        factor = df.iloc[row_idx, 0]
        py_val = df.iloc[row_idx, 5]
        if pd.notna(factor) and pd.notna(py_val):
            risk_contrib[str(factor)] = float(py_val)
    refs["risk_contrib"] = risk_contrib

    # Total factor variance (row 77 = 0-indexed 76, col F = index 5)
    refs["factor_var_daily"] = float(df.iloc[76, 5])

    # Section 4: Factor Risk (rows 80-83, 0-indexed 79-82)
    # Col C (index 2) has Python ref
    refs["factor_var_annual"] = float(df.iloc[80, 2])  # row 81
    refs["factor_vol_annual"] = float(df.iloc[81, 2])  # row 82

    # Section 5: Idio risk per stock (rows 88-107, 0-indexed 87-106)
    # Col E (index 4) has Python ref idio vol
    idio_vols = {}
    for i in range(20):
        row_idx = 87 + i
        ticker = df.iloc[row_idx, 0]
        py_val = df.iloc[row_idx, 4]
        if pd.notna(ticker) and pd.notna(py_val) and py_val != "N/A":
            idio_vols[str(ticker)] = float(py_val)
    refs["idio_vols"] = idio_vols

    # Idio variance total (row 108 = 0-indexed 107, col C = index 2)
    refs["idio_var"] = float(df.iloc[107, 2])

    # Section 6: Total Risk (rows 112-116, 0-indexed 111-115)
    refs["total_var"] = float(df.iloc[111, 2])
    refs["total_vol"] = float(df.iloc[112, 2])
    refs["pct_factor"] = float(df.iloc[114, 2])
    refs["pct_idio"] = float(df.iloc[115, 2])

    return refs


def _get_subset(factor_exp_df):
    """Filter factor_exp to selected tickers & date range."""
    mask = (
        factor_exp_df["ticker"].isin(SELECTED_TICKERS)
        & (factor_exp_df["date"] >= DATE_START)
        & (factor_exp_df["date"] <= DATE_END)
    )
    return factor_exp_df[mask].copy()


def _compute_idio_vol(ticker, factor_exp_full, factor_ret_df):
    """Compute idio vol for a single stock using full history."""
    stock_data = factor_exp_full[factor_exp_full["ticker"] == ticker].copy()
    if len(stock_data) < 20:
        return np.nan
    stock_data = stock_data.sort_values("date")
    residuals = []
    for _, row in stock_data.iterrows():
        date_str = str(row["date"].date()) if hasattr(row["date"], "date") else str(row["date"])[:10]
        if date_str not in factor_ret_df.index:
            continue
        r_actual = row["return"]
        f_ret = factor_ret_df.loc[date_str]
        r_predicted = f_ret.get("Country", 0)
        sector = row["sector"]
        if sector in f_ret.index:
            r_predicted += f_ret[sector]
        for sf in STYLE_FACTORS:
            if sf in f_ret.index:
                beta_val = row[sf]
                if pd.notna(beta_val):
                    r_predicted += beta_val * f_ret[sf]
        residuals.append(r_actual - r_predicted)
    if len(residuals) >= 20:
        return float(np.std(residuals) * np.sqrt(252))
    return np.nan


# ===================================================================
# Test 1: Stocks sheet structure
# ===================================================================
class TestStocksSheet:
    """Verify Stocks sheet has correct structure and data."""

    def test_has_20_stocks(self, xl_stocks):
        assert len(xl_stocks) == 20, f"Expected 20 stocks, got {len(xl_stocks)}"

    def test_tickers_sorted_alphabetically(self, xl_stocks):
        tickers = xl_stocks["Ticker"].tolist()
        assert tickers == sorted(tickers), "Tickers not sorted alphabetically"

    def test_weights_sum_to_1(self, xl_stocks):
        total = xl_stocks["Weight"].sum()
        assert abs(total - 1.0) < 1e-10, f"Weights sum to {total}, expected 1.0"

    def test_country_all_ones(self, xl_stocks):
        assert (xl_stocks["Country"] == 1).all(), "Country column should be all 1s"

    def test_industry_dummies_one_hot(self, xl_stocks):
        """Each stock should have exactly one industry dummy = 1."""
        ind_cols = INDUSTRY_FACTORS
        for _, row in xl_stocks.iterrows():
            row_sum = sum(row[ind] for ind in ind_cols)
            assert row_sum == 1, f"Stock {row['Ticker']} has {row_sum} industry flags"


# ===================================================================
# Test 2: Covariance sheet
# ===================================================================
class TestCovarianceSheet:
    """Verify Covariance sheet matches model data."""

    def test_covariance_shape(self, xl_covariance):
        assert xl_covariance.shape == (22, 22), f"Expected 22x22, got {xl_covariance.shape}"

    def test_covariance_matches_model(self, xl_covariance, factor_cov_df):
        diff = (xl_covariance.values - factor_cov_df.values)
        assert np.abs(diff).max() < 1e-12, "Covariance values don't match model"

    def test_covariance_symmetric(self, xl_covariance):
        diff = xl_covariance.values - xl_covariance.values.T
        assert np.abs(diff).max() < 1e-15, "Covariance not symmetric"

    def test_covariance_positive_definite(self, xl_covariance):
        eigvals = np.linalg.eigvalsh(xl_covariance.values)
        assert (eigvals > 0).all(), "Covariance not positive definite"


# ===================================================================
# Test 3: RiskDecomp Python references match independent computation
# ===================================================================
class TestRiskDecompReferences:
    """Verify Python reference values in RiskDecomp are correct."""

    def test_exposure_references_match(
        self, xl_risk_decomp, factor_exp_df, factor_cov_df
    ):
        """Portfolio exposures should match independent computation."""
        refs = _get_risk_decomp_refs(xl_risk_decomp)
        subset = _get_subset(factor_exp_df)
        latest_date = subset["date"].max()
        latest = subset[subset["date"] == latest_date]
        latest = latest[latest["ticker"].isin(SELECTED_TICKERS)]

        n = 20
        weights = {t: 1.0 / n for t in SELECTED_TICKERS}

        for factor in ALL_FACTORS:
            if factor == "Country":
                expected = 1.0
            elif factor in INDUSTRY_FACTORS:
                ind_dummy = (latest["sector"] == factor).astype(float)
                expected = sum(weights[t] * ind_dummy[latest["ticker"] == t].values[0]
                               for t in latest["ticker"] if t in weights)
            else:
                expected = sum(weights[t] * latest.loc[latest["ticker"] == t, factor].values[0]
                               for t in latest["ticker"] if t in weights)

            ref_val = refs["exposures"].get(factor, None)
            assert ref_val is not None, f"Missing exposure reference for {factor}"
            assert abs(ref_val - expected) < 1e-8, (
                f"Exposure mismatch for {factor}: ref={ref_val}, expected={expected}"
            )

    def test_factor_variance_reference(
        self, xl_risk_decomp, factor_exp_df, factor_cov_df
    ):
        """Factor variance b'Ωb should match independent computation."""
        refs = _get_risk_decomp_refs(xl_risk_decomp)

        subset = _get_subset(factor_exp_df)
        latest_date = subset["date"].max()
        latest = subset[subset["date"] == latest_date]
        latest = latest[latest["ticker"].isin(SELECTED_TICKERS)]

        n = 20
        weights = {t: 1.0 / n for t in SELECTED_TICKERS}
        all_exposures = {"Country": 1.0}
        for ind in INDUSTRY_FACTORS:
            ind_dummy = (latest["sector"] == ind).astype(float)
            all_exposures[ind] = sum(weights[t] * ind_dummy[latest["ticker"] == t].values[0]
                                     for t in latest["ticker"] if t in weights)
        for sf in STYLE_FACTORS:
            all_exposures[sf] = sum(weights[t] * latest.loc[latest["ticker"] == t, sf].values[0]
                                    for t in latest["ticker"] if t in weights)

        factor_names = factor_cov_df.columns.tolist()
        b = np.array([all_exposures.get(f, 0) for f in factor_names])
        expected = float(b @ factor_cov_df.values @ b)

        assert abs(refs["factor_var_daily"] - expected) < 1e-12, (
            f"Factor variance mismatch: ref={refs['factor_var_daily']}, expected={expected}"
        )

    def test_risk_contributions_sum_to_variance(self, xl_risk_decomp):
        """Sum of per-factor risk contributions should equal total factor variance."""
        refs = _get_risk_decomp_refs(xl_risk_decomp)
        total_contrib = sum(refs["risk_contrib"].values())
        fvar = refs["factor_var_daily"]
        assert abs(total_contrib - fvar) / max(abs(fvar), 1e-15) < 1e-6, (
            f"Risk contributions don't sum to factor variance: {total_contrib} vs {fvar}"
        )

    def test_idio_vol_references_match(
        self, xl_risk_decomp, factor_exp_df, factor_ret_df
    ):
        """Per-stock idio vol references should match independent computation."""
        refs = _get_risk_decomp_refs(xl_risk_decomp)

        # Spot check 3 stocks
        for ticker in ["NVDA", "JPM", "AES"]:
            ref_val = refs["idio_vols"].get(ticker, None)
            if ref_val is None:
                continue
            expected = _compute_idio_vol(ticker, factor_exp_df, factor_ret_df)
            assert abs(ref_val - expected) < 1e-6, (
                f"Idio vol mismatch for {ticker}: ref={ref_val}, expected={expected}"
            )

    def test_variance_decomposition_adds_up(self, xl_risk_decomp):
        """factor_var_annual + idio_var should equal total_variance."""
        refs = _get_risk_decomp_refs(xl_risk_decomp)
        expected = refs["factor_var_annual"] + refs["idio_var"]
        actual = refs["total_var"]
        rel_diff = abs(actual - expected) / max(abs(actual), 1e-15)
        assert rel_diff < 1e-10, (
            f"Variance doesn't decompose: {expected} vs {actual}"
        )

    def test_pct_decomposition_sums_to_100(self, xl_risk_decomp):
        """pct_factor + pct_idio should sum to 100%."""
        refs = _get_risk_decomp_refs(xl_risk_decomp)
        total_pct = refs["pct_factor"] + refs["pct_idio"]
        assert abs(total_pct - 100.0) < 0.01, (
            f"% decomposition sums to {total_pct}, expected 100"
        )


# ===================================================================
# Test 4: Idio vol values are reasonable
# ===================================================================
class TestIdioVol:
    """Verify idiosyncratic volatility values are reasonable."""

    def test_idio_vol_all_20_stocks(self, xl_risk_decomp):
        refs = _get_risk_decomp_refs(xl_risk_decomp)
        assert len(refs["idio_vols"]) == 20, (
            f"Expected 20 idio vols, got {len(refs['idio_vols'])}"
        )

    def test_idio_vol_reasonable_range(self, xl_risk_decomp):
        """Annualized idio vol should be in 1%-200% range."""
        refs = _get_risk_decomp_refs(xl_risk_decomp)
        for ticker, vol in refs["idio_vols"].items():
            assert 0.01 < vol < 2.0, (
                f"Idio vol for {ticker} = {vol:.4f}, outside reasonable range"
            )

    def test_idio_vol_positive(self, xl_risk_decomp):
        refs = _get_risk_decomp_refs(xl_risk_decomp)
        for ticker, vol in refs["idio_vols"].items():
            assert vol > 0, f"Idio vol for {ticker} should be positive"


# ===================================================================
# Test 5: Total risk end-to-end
# ===================================================================
class TestTotalRisk:
    """Verify total portfolio risk end-to-end."""

    def test_total_vol_reasonable(self, xl_risk_decomp):
        """Total vol should be in a reasonable range (5%-50% annualized)."""
        refs = _get_risk_decomp_refs(xl_risk_decomp)
        total_vol_pct = refs["total_vol"] * 100
        assert 5 < total_vol_pct < 50, f"Total vol {total_vol_pct:.2f}% seems unreasonable"

    def test_factor_vol_less_than_total(self, xl_risk_decomp):
        refs = _get_risk_decomp_refs(xl_risk_decomp)
        assert refs["factor_vol_annual"] < refs["total_vol"], (
            "Factor vol should be less than total vol"
        )

    def test_pct_idio_dominant_for_equal_weight(self, xl_risk_decomp):
        """Equal-weight 20-stock portfolio should have substantial idio risk."""
        refs = _get_risk_decomp_refs(xl_risk_decomp)
        # 20 equal-weight stocks should have meaningful idio contribution
        assert refs["pct_idio"] > 10, (
            f"% idio = {refs['pct_idio']:.1f}%, expected > 10% for 20-stock equal weight"
        )


# ===================================================================
# Test 6: Regression sheet
# ===================================================================
class TestRegressionSheet:
    """Verify Regression sheet has correct structure."""

    def test_has_factor_returns(self, xl_regression):
        """Should have 22 factor returns listed."""
        # Factor returns are in rows 4-25 (0-indexed: 3-24), col A
        factors_found = []
        for i in range(3, 25):
            val = xl_regression.iloc[i, 0]
            if pd.notna(val):
                factors_found.append(str(val))
        assert len(factors_found) == 22, f"Expected 22 factors, found {len(factors_found)}"

    def test_has_20_stocks(self, xl_regression):
        """Should have breakdown for 20 stocks."""
        # Stock rows start after factor returns section + gap
        # Look for ticker names in column A
        ticker_count = 0
        for i in range(25, len(xl_regression)):
            val = xl_regression.iloc[i, 0]
            if pd.notna(val) and str(val) in SELECTED_TICKERS:
                ticker_count += 1
        assert ticker_count == 20, f"Expected 20 stock rows, found {ticker_count}"

    def test_python_residuals_reasonable(self, xl_regression):
        """Python residuals should be small relative to actual returns."""
        # Find columns with Python Predicted and Python Residual
        # They are the last 2 data columns per the generator
        for i in range(25, len(xl_regression)):
            val = xl_regression.iloc[i, 0]
            if pd.notna(val) and str(val) in SELECTED_TICKERS:
                # Last column = Python Residual
                n_cols = xl_regression.shape[1]
                py_resid = xl_regression.iloc[i, n_cols - 1]
                if pd.notna(py_resid):
                    assert abs(float(py_resid)) < 0.2, (
                        f"Residual for {val} = {py_resid}, seems too large"
                    )


# ===================================================================
# Test 7: Universe sheet
# ===================================================================
@pytest.fixture(scope="module")
def xl_universe(workbook_exists):
    return pd.read_excel(WORKBOOK_PATH, sheet_name="Universe")


class TestUniverseSheet:
    """Verify Universe sheet has correct structure and data."""

    def test_has_full_universe(self, xl_universe):
        """Should have ~2,500 stocks."""
        assert len(xl_universe) > 2000, f"Expected >2000 stocks, got {len(xl_universe)}"

    def test_has_all_columns(self, xl_universe):
        expected = ["Ticker", "Sector", "Return", "Market Cap"]
        for col in expected:
            assert col in xl_universe.columns, f"Missing column: {col}"

    def test_tickers_sorted(self, xl_universe):
        tickers = xl_universe["Ticker"].tolist()
        assert tickers == sorted(tickers), "Tickers not sorted"

    def test_market_caps_mostly_positive(self, xl_universe):
        caps = xl_universe["Market Cap"].dropna()
        assert (caps > 0).all(), "Non-null market caps should be positive"
        assert caps.notna().sum() > 2500, "Most stocks should have market caps"

    def test_industry_dummies_mostly_one_hot(self, xl_universe):
        """Most stocks should have exactly one industry dummy = 1."""
        ind_cols = [c for c in xl_universe.columns if c in INDUSTRY_FACTORS]
        assert len(ind_cols) == 11, f"Expected 11 industry cols, got {len(ind_cols)}"
        valid = 0
        for _, row in xl_universe.iterrows():
            row_sum = sum(row[ind] for ind in ind_cols)
            if row_sum == 1:
                valid += 1
        # Allow a few stocks with sector "Other" to have sum=0
        pct = valid / len(xl_universe)
        assert pct > 0.95, f"Only {pct*100:.1f}% of stocks have valid one-hot industry"

    def test_raw_descriptors_present(self, xl_universe):
        """Should have 17 raw descriptor columns."""
        raw_names = ["size", "beta", "momentum", "btop",
                     "dastd", "cmra", "hsigma", "stom", "stoq", "stoa",
                     "etop", "cetop", "egro", "sgro", "mlev", "dtoa", "blev"]
        for name in raw_names:
            assert name in xl_universe.columns, f"Missing raw descriptor: {name}"


# ===================================================================
# Test 8: ZScoring sheet
# ===================================================================
@pytest.fixture(scope="module")
def xl_zscoring(workbook_exists):
    return pd.read_excel(WORKBOOK_PATH, sheet_name="ZScoring", header=None)


class TestZScoringSheet:
    """Verify ZScoring sheet has correct structure."""

    def test_has_data_rows(self, xl_zscoring):
        """Should have ~2,500+ rows (data + summary)."""
        # Row count includes header + ~2545 data + summary block
        assert len(xl_zscoring) > 2500, f"Expected >2500 rows, got {len(xl_zscoring)}"

    def test_python_zscores_present(self, xl_zscoring):
        """Python reference z-scores should be in right-side columns."""
        # Header row (0-indexed: 0) should have py_size, py_beta, etc.
        headers = [str(xl_zscoring.iloc[0, c]) for c in range(xl_zscoring.shape[1])]
        py_cols = [h for h in headers if h.startswith("py_")]
        assert len(py_cols) == 10, f"Expected 10 Python ref columns, got {len(py_cols)}: {py_cols}"

    def test_python_zscores_reasonable(self, xl_zscoring):
        """Python z-scores should mostly be in [-5, 5] range."""
        # Find py_size column
        headers = [str(xl_zscoring.iloc[0, c]) for c in range(xl_zscoring.shape[1])]
        py_size_idx = None
        for c, h in enumerate(headers):
            if h == "py_size":
                py_size_idx = c
                break
        if py_size_idx is None:
            pytest.skip("py_size column not found")
        vals = xl_zscoring.iloc[1:2546, py_size_idx].dropna()
        vals = pd.to_numeric(vals, errors="coerce").dropna()
        assert len(vals) > 2000, f"Expected >2000 py_size values, got {len(vals)}"
        pct_in_range = ((vals > -5) & (vals < 5)).mean()
        assert pct_in_range > 0.95, f"Only {pct_in_range*100:.1f}% of z-scores in [-5,5]"


# ===================================================================
# Test 9: WLSRegression sheet
# ===================================================================
@pytest.fixture(scope="module")
def xl_wls(workbook_exists):
    return pd.read_excel(WORKBOOK_PATH, sheet_name="WLSRegression", header=None)


class TestWLSRegressionSheet:
    """Verify WLSRegression sheet has correct structure and references."""

    def test_has_renorm_stats(self, xl_wls):
        """Should have re-normalization stats for 10 style factors."""
        # Look for style factor names in first column rows 3-12
        style_count = 0
        for i in range(2, 20):
            val = xl_wls.iloc[i, 0]
            if pd.notna(val) and str(val) in STYLE_FACTORS:
                style_count += 1
        assert style_count == 10, f"Expected 10 style factors in renorm stats, got {style_count}"

    def test_factor_returns_section(self, xl_wls):
        """Should have FACTOR RETURNS section with 22 factors."""
        # Search for "FACTOR RETURNS" label
        found = False
        fr_row = None
        for i in range(len(xl_wls)):
            val = xl_wls.iloc[i, 0]
            if pd.notna(val) and "FACTOR RETURNS" in str(val):
                found = True
                fr_row = i
                break
        assert found, "FACTOR RETURNS section not found"

        # Count factor rows after the header
        factor_count = 0
        for i in range(fr_row + 2, fr_row + 30):
            if i >= len(xl_wls):
                break
            val = xl_wls.iloc[i, 0]
            if pd.notna(val) and str(val) in ALL_FACTORS:
                factor_count += 1
        assert factor_count == 22, f"Expected 22 factor returns, got {factor_count}"

    def test_python_model_values_present(self, xl_wls):
        """Python Model column should have non-zero values."""
        # Find FACTOR RETURNS section and check Python Model column (col C)
        for i in range(len(xl_wls)):
            val = xl_wls.iloc[i, 0]
            if pd.notna(val) and "FACTOR RETURNS" in str(val):
                # Data starts 2 rows after section header
                vals = []
                for j in range(i + 2, i + 24):
                    if j >= len(xl_wls):
                        break
                    py_val = xl_wls.iloc[j, 2]  # col C = Python Model
                    if pd.notna(py_val):
                        vals.append(float(py_val))
                assert len(vals) >= 20, f"Expected >=20 Python model values, got {len(vals)}"
                assert any(abs(v) > 1e-6 for v in vals), "All Python model values are zero"
                return
        pytest.fail("FACTOR RETURNS section not found")

    def test_wls_factor_returns_match_model(self, xl_wls, factor_ret_df):
        """WLS-computed factor returns should match the model's stored values."""
        # The WLS sheet has Python Model values — verify they match factor_ret CSV
        rep_date = "2025-08-15"
        if rep_date not in factor_ret_df.index:
            pytest.skip("Representative date not in factor returns")
        for i in range(len(xl_wls)):
            val = xl_wls.iloc[i, 0]
            if pd.notna(val) and "FACTOR RETURNS" in str(val):
                for j in range(i + 2, i + 24):
                    if j >= len(xl_wls):
                        break
                    factor = xl_wls.iloc[j, 0]
                    py_val = xl_wls.iloc[j, 2]
                    if pd.notna(factor) and pd.notna(py_val) and str(factor) in ALL_FACTORS:
                        expected = factor_ret_df.loc[rep_date, str(factor)]
                        assert abs(float(py_val) - expected) < 1e-10, (
                            f"Factor return mismatch for {factor}: {py_val} vs {expected}"
                        )
                return


# ===================================================================
# Test 10: SimpleCov sheet
# ===================================================================
@pytest.fixture(scope="module")
def xl_simplecov(workbook_exists):
    return pd.read_excel(WORKBOOK_PATH, sheet_name="SimpleCov", header=None)


class TestSimpleCovSheet:
    """Verify SimpleCov sheet structure."""

    def test_has_sample_covariance_section(self, xl_simplecov):
        """Should have SIMPLE SAMPLE COVARIANCE section."""
        found = False
        for i in range(len(xl_simplecov)):
            val = xl_simplecov.iloc[i, 0]
            if pd.notna(val) and "SIMPLE SAMPLE COVARIANCE" in str(val):
                found = True
                break
        assert found, "SIMPLE SAMPLE COVARIANCE section not found"

    def test_has_adjusted_covariance_section(self, xl_simplecov):
        """Should have ADJUSTED COVARIANCE section."""
        found = False
        for i in range(len(xl_simplecov)):
            val = xl_simplecov.iloc[i, 0]
            if pd.notna(val) and "ADJUSTED COVARIANCE" in str(val):
                found = True
                break
        assert found, "ADJUSTED COVARIANCE section not found"

    def test_has_ratio_section(self, xl_simplecov):
        """Should have RATIO section."""
        found = False
        for i in range(len(xl_simplecov)):
            val = xl_simplecov.iloc[i, 0]
            if pd.notna(val) and "RATIO" in str(val):
                found = True
                break
        assert found, "RATIO section not found"

    def test_has_demeaned_returns(self, xl_simplecov):
        """Should have ~21 rows of demeaned returns (formula rows between sections)."""
        # Find DEMEANED and SIMPLE SAMPLE sections, count rows between them
        dm_row = None
        sc_row = None
        for i in range(len(xl_simplecov)):
            val = xl_simplecov.iloc[i, 0]
            if pd.notna(val) and "DEMEANED" in str(val):
                dm_row = i
            if pd.notna(val) and "SIMPLE SAMPLE" in str(val):
                sc_row = i
        assert dm_row is not None, "DEMEANED section not found"
        assert sc_row is not None, "SIMPLE SAMPLE section not found"
        # Rows between DEMEANED header+header row and SIMPLE SAMPLE section
        data_rows = sc_row - dm_row - 3  # subtract section header, col header, gap
        assert data_rows >= 20, f"Expected >=20 demeaned return rows, got {data_rows}"
