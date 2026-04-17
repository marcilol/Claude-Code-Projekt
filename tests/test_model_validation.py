"""Model validation tests — derived from the validation checklist and EDA work.

Tests alignment, factor loading sanity, autocorrelation, VIF,
CAPM lift, R² distribution, permutation structural floor,
and ETF loading signs.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

from conftest import MODEL_DIR, STYLE_FACTORS, INDUSTRY_FACTORS_25, N_FACTORS

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def factor_returns():
    path = os.path.join(MODEL_DIR, "barra_factor_returns.csv")
    if not os.path.exists(path):
        pytest.skip("barra_factor_returns.csv not found")
    return pd.read_csv(path, index_col=0)


@pytest.fixture(scope="session")
def cross_sectional_data():
    path = os.path.join(MODEL_DIR, "russell3000_cross_sectional_data.csv")
    if not os.path.exists(path):
        pytest.skip("cross_sectional_data not found")
    return pd.read_csv(path)


@pytest.fixture(scope="session")
def r2_series():
    path = os.path.join(MODEL_DIR, "barra_r2.csv")
    if not os.path.exists(path):
        pytest.skip("barra_r2.csv not found")
    df = pd.read_csv(path, index_col=0)
    return df["R2"]


# ---------------------------------------------------------------------------
# Test 1: Factor return autocorrelation
# ---------------------------------------------------------------------------
class TestAutocorrelation:
    def test_no_high_autocorrelation(self, factor_returns):
        """No factor should have lag-1 autocorrelation > 0.20.

        Values above 0.20 suggest stale data or date misalignment.
        Threshold is deliberately generous; 0.10-0.15 is common
        for industry factors due to bid-ask bounce.
        """
        violations = []
        for col in factor_returns.columns:
            s = factor_returns[col].dropna()
            if len(s) < 30:
                continue
            ac = s.autocorr(lag=1)
            if abs(ac) > 0.20:
                violations.append((col, round(ac, 3)))
        assert len(violations) == 0, (
            f"Factors with |autocorr| > 0.20: {violations}"
        )


# ---------------------------------------------------------------------------
# Test 2: VIF — no severe multicollinearity
# ---------------------------------------------------------------------------
class TestVIF:
    def test_style_factor_vif_under_10(self, cross_sectional_data):
        """No style factor should have VIF > 10 (severe multicollinearity)."""
        latest = cross_sectional_data["date"].max()
        dd = cross_sectional_data[cross_sectional_data["date"] == latest]
        style_data = dd[STYLE_FACTORS].fillna(0).values

        max_vif = 0
        worst = None
        for i, col in enumerate(STYLE_FACTORS):
            y = style_data[:, i]
            X = np.delete(style_data, i, axis=1)
            X = np.column_stack([np.ones(len(X)), X])
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            pred = X @ beta
            ss_res = np.sum((y - pred) ** 2)
            ss_tot = np.sum((y - y.mean()) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            vif = 1 / (1 - r2) if r2 < 1 else np.inf
            if vif > max_vif:
                max_vif = vif
                worst = col

        assert max_vif < 10, f"VIF too high: {worst} = {max_vif:.1f}"


# ---------------------------------------------------------------------------
# Test 3: CAPM benchmark lift
# ---------------------------------------------------------------------------
class TestCAPMBenchmark:
    def test_style_factors_add_explanatory_power(self, cross_sectional_data, r2_series):
        """Full model R² should exceed CAPM-only R² by at least 5pp.

        If the lift is tiny, style + industry factors aren't contributing.
        """
        dates = sorted(cross_sectional_data["date"].unique())
        industry_cols = [c for c in cross_sectional_data.columns
                         if c not in ["date", "stocknames", "capital", "ret"] + STYLE_FACTORS]

        capm_r2s = []
        for d in dates[::10]:  # sample every 10th date for speed
            dd = cross_sectional_data[cross_sectional_data["date"] == d]
            y = dd["ret"].values
            cap = dd["capital"].values
            if len(y) < 50:
                continue
            w = np.sqrt(cap) / np.sqrt(cap).sum()
            X = np.ones((len(y), 1))
            beta = np.linalg.lstsq(np.diag(w) @ X, np.diag(w) @ y, rcond=None)[0]
            pred = X @ beta
            ss_res = np.sum(w * (y - pred) ** 2)
            ss_tot = np.sum(w * y ** 2)
            capm_r2s.append(1 - ss_res / ss_tot if ss_tot > 0 else 0)

        capm_mean = np.mean(capm_r2s)
        full_mean = r2_series.mean()
        lift = full_mean - capm_mean

        assert lift > 0.05, (
            f"Style+industry lift too small: CAPM={capm_mean:.3f}, "
            f"Full={full_mean:.3f}, lift={lift:.3f}"
        )


# ---------------------------------------------------------------------------
# Test 4: R² distribution — not pathologically skewed
# ---------------------------------------------------------------------------
class TestR2Distribution:
    def test_median_r2_above_15pct(self, r2_series):
        """Median daily R² should be above 15%.

        Below 15% median means the model explains very little
        on a typical day.
        """
        median = r2_series.median()
        assert median > 0.15, f"Median R² = {median:.3f}, expected > 0.15"

    def test_r2_iqr_not_too_wide(self, r2_series):
        """IQR of daily R² should be under 40pp.

        An IQR wider than 40pp suggests the model is unstable
        across regimes.
        """
        iqr = r2_series.quantile(0.75) - r2_series.quantile(0.25)
        assert iqr < 0.40, f"R² IQR = {iqr:.3f}, expected < 0.40"


# ---------------------------------------------------------------------------
# Test 5: Known stock loading signs
# ---------------------------------------------------------------------------
class TestKnownStockLoadings:
    """Spot-check that well-known stocks have the right factor loading signs."""

    def _get_loading(self, cross_sectional_data, ticker, factor):
        latest = cross_sectional_data["date"].max()
        dd = cross_sectional_data[cross_sectional_data["date"] == latest]
        row = dd[dd["stocknames"] == ticker]
        if row.empty or factor not in row.columns:
            return None
        val = row[factor].iloc[0]
        return val if pd.notna(val) else None

    def test_aapl_positive_size(self, cross_sectional_data):
        val = self._get_loading(cross_sectional_data, "AAPL", "size")
        if val is None:
            pytest.skip("AAPL not found")
        assert val > 0, f"AAPL size = {val}, expected positive (mega-cap)"

    def test_tsla_positive_beta(self, cross_sectional_data):
        val = self._get_loading(cross_sectional_data, "TSLA", "beta")
        if val is None:
            pytest.skip("TSLA not found")
        assert val > 0, f"TSLA beta = {val}, expected positive (high beta)"

    def test_nvda_positive_size(self, cross_sectional_data):
        val = self._get_loading(cross_sectional_data, "NVDA", "size")
        if val is None:
            pytest.skip("NVDA not found")
        assert val > 0, f"NVDA size = {val}, expected positive (mega-cap)"


# ---------------------------------------------------------------------------
# Test 6: High-vol day alignment
# ---------------------------------------------------------------------------
class TestHighVolDayAlignment:
    """On high-dispersion days, shifting returns by 1 day should
    substantially reduce R²."""

    def test_alignment_on_volatile_days(self, cross_sectional_data):
        dates = sorted(cross_sectional_data["date"].unique())
        industry_cols = [c for c in cross_sectional_data.columns
                         if c not in ["date", "stocknames", "capital", "ret"] + STYLE_FACTORS]

        # Find top 5 high-dispersion days
        daily_std = []
        for d in dates:
            dd = cross_sectional_data[cross_sectional_data["date"] == d]
            daily_std.append((d, dd["ret"].std()))
        daily_std.sort(key=lambda x: -x[1])
        top_days = [d for d, _ in daily_std[:5]]

        def wls_r2(dd):
            y = dd["ret"].values
            cap = dd["capital"].values
            if len(y) < 50:
                return np.nan
            w = np.sqrt(cap) / np.sqrt(cap).sum()
            X = np.hstack([
                np.ones((len(dd), 1)),
                dd[industry_cols].fillna(0).values,
                dd[STYLE_FACTORS].fillna(0).values,
            ])
            beta = np.linalg.lstsq(np.diag(w) @ X, np.diag(w) @ y, rcond=None)[0]
            pred = X @ beta
            ss_res = np.sum(w * (y - pred) ** 2)
            ss_tot = np.sum(w * y ** 2)
            return 1 - ss_res / ss_tot if ss_tot > 0 else 0

        # For each top day, compare aligned vs shifted returns
        total_drop = 0
        n_tested = 0
        for d in top_days:
            idx = dates.index(d)
            if idx + 1 >= len(dates):
                continue
            next_d = dates[idx + 1]

            dd_aligned = cross_sectional_data[cross_sectional_data["date"] == d]
            dd_next = cross_sectional_data[cross_sectional_data["date"] == next_d]

            r2_aligned = wls_r2(dd_aligned)

            # Shift: use next day's returns with today's exposures
            merged = dd_aligned[["stocknames"] + industry_cols + STYLE_FACTORS + ["capital"]].merge(
                dd_next[["stocknames", "ret"]], on="stocknames", how="inner", suffixes=("", "_next")
            )
            if len(merged) < 50:
                continue
            merged_copy = merged.rename(columns={"ret_next": "ret"})
            r2_shifted = wls_r2(merged_copy)

            if not np.isnan(r2_aligned) and not np.isnan(r2_shifted):
                total_drop += r2_aligned - r2_shifted
                n_tested += 1

        if n_tested == 0:
            pytest.skip("Could not test high-vol days")

        avg_drop = total_drop / n_tested
        assert avg_drop > 0.05, (
            f"Average R² drop on high-vol days when shifted: {avg_drop:.3f}. "
            f"Expected > 0.05 — alignment may be wrong."
        )


# ---------------------------------------------------------------------------
# Test 7: Permutation structural floor
# ---------------------------------------------------------------------------
class TestPermutationFloor:
    """Shuffling date-return pairings should collapse R² well below baseline."""

    def test_permuted_r2_below_baseline(self, cross_sectional_data):
        dates = sorted(cross_sectional_data["date"].unique())
        industry_cols = [c for c in cross_sectional_data.columns
                         if c not in ["date", "stocknames", "capital", "ret"] + STYLE_FACTORS]

        # Pre-compute per-date arrays
        date_arrays = {}
        for d in dates[::5]:  # every 5th date for speed
            dd = cross_sectional_data[cross_sectional_data["date"] == d]
            y = dd["ret"].values
            cap = dd["capital"].values
            if len(y) < 50:
                continue
            w = np.sqrt(cap) / np.sqrt(cap).sum()
            X = np.hstack([
                np.ones((len(dd), 1)),
                dd[industry_cols].fillna(0).values,
                dd[STYLE_FACTORS].fillna(0).values,
            ])
            date_arrays[d] = {"y": y, "X": X, "w": w}

        valid_dates = list(date_arrays.keys())
        if len(valid_dates) < 20:
            pytest.skip("Not enough dates for permutation test")

        def compute_r2(y, X, w):
            beta = np.linalg.lstsq(np.diag(w) @ X, np.diag(w) @ y, rcond=None)[0]
            pred = X @ beta
            ss_res = np.sum(w * (y - pred) ** 2)
            ss_tot = np.sum(w * y ** 2)
            return 1 - ss_res / ss_tot if ss_tot > 0 else 0

        # Baseline
        baseline_r2 = np.mean([
            compute_r2(date_arrays[d]["y"], date_arrays[d]["X"], date_arrays[d]["w"])
            for d in valid_dates
        ])

        # 10 permutations (enough for a pass/fail test)
        np.random.seed(42)
        perm_r2s = []
        for _ in range(10):
            perm = np.random.permutation(len(valid_dates))
            r2s = []
            for i, d in enumerate(valid_dates):
                src = valid_dates[perm[i]]
                X = date_arrays[d]["X"]
                w = date_arrays[d]["w"]
                y_shuf = date_arrays[src]["y"]
                n_x, n_y = len(w), len(y_shuf)
                if n_x == n_y:
                    r2s.append(compute_r2(y_shuf, X, w))
                elif n_y >= n_x:
                    idx = np.random.choice(n_y, n_x, replace=False)
                    r2s.append(compute_r2(y_shuf[idx], X, w))
            perm_r2s.append(np.mean(r2s))

        perm_mean = np.mean(perm_r2s)
        lift = baseline_r2 - perm_mean

        assert lift > 0.10, (
            f"Day-specific lift too small: baseline={baseline_r2:.3f}, "
            f"permuted={perm_mean:.3f}, lift={lift:.3f}. Expected > 0.10."
        )


# ---------------------------------------------------------------------------
# Test 8: Beta fillna audit
# ---------------------------------------------------------------------------
class TestBetaFillna:
    def test_beta_zeros_under_20pct(self, cross_sectional_data):
        """Beta zeros from fillna(0) should be under 20% of all rows.

        Above 20% means too many stocks are treated as market-neutral.
        """
        n_zero = (cross_sectional_data["beta"] == 0).sum()
        pct = n_zero / len(cross_sectional_data)
        assert pct < 0.20, (
            f"Beta zero-fill rate = {pct:.1%} ({n_zero} rows). "
            f"Expected < 20%."
        )


# ---------------------------------------------------------------------------
# Test 9: Industry-only R² decomposition
# ---------------------------------------------------------------------------
class TestR2Decomposition:
    def test_industry_adds_value_over_capm(self, cross_sectional_data):
        """Industry factors should add at least 5pp over CAPM-only."""
        dates = sorted(cross_sectional_data["date"].unique())
        industry_cols = [c for c in cross_sectional_data.columns
                         if c not in ["date", "stocknames", "capital", "ret"] + STYLE_FACTORS]

        capm_r2s = []
        ind_r2s = []
        for d in dates[::10]:
            dd = cross_sectional_data[cross_sectional_data["date"] == d]
            y = dd["ret"].values
            cap = dd["capital"].values
            if len(y) < 50:
                continue
            w = np.sqrt(cap) / np.sqrt(cap).sum()
            W = np.diag(w)

            # CAPM
            X_capm = np.ones((len(y), 1))
            b = np.linalg.lstsq(W @ X_capm, W @ y, rcond=None)[0]
            ss_res = np.sum(w * (y - X_capm @ b) ** 2)
            ss_tot = np.sum(w * y ** 2)
            capm_r2s.append(1 - ss_res / ss_tot if ss_tot > 0 else 0)

            # Industry + CAPM
            X_ind = np.hstack([np.ones((len(y), 1)), dd[industry_cols].fillna(0).values])
            b = np.linalg.lstsq(W @ X_ind, W @ y, rcond=None)[0]
            ss_res = np.sum(w * (y - X_ind @ b) ** 2)
            ind_r2s.append(1 - ss_res / ss_tot if ss_tot > 0 else 0)

        lift = np.mean(ind_r2s) - np.mean(capm_r2s)
        assert lift > 0.05, (
            f"Industry lift = {lift:.3f}. Expected > 0.05."
        )
