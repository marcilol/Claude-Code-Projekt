"""Phase 3: Regression tests — compare current outputs against saved baselines.

First run: saves current outputs as JSON baselines to tests/baselines/.
Subsequent runs: loads baselines, compares against current output.
Tolerance: 1% relative deviation.
"""
import json
import os

import numpy as np
import pandas as pd
import pytest

from conftest import BASELINES_DIR, MODEL_DIR, STYLE_FACTORS


def _load_or_save_baseline(name, current_value):
    """Load baseline if it exists, otherwise save current value as baseline.

    Returns (baseline_value, is_new) tuple.
    """
    path = os.path.join(BASELINES_DIR, f"{name}.json")

    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f), False
    else:
        os.makedirs(BASELINES_DIR, exist_ok=True)
        with open(path, "w") as f:
            json.dump(current_value, f, indent=2)
        return current_value, True


class TestFactorReturnBaselines:
    def test_factor_return_means(self, factor_returns_df):
        """Mean factor returns should match baseline within 1%."""
        current = factor_returns_df.mean().to_dict()
        # Convert numpy types to native Python for JSON serialization
        current = {k: float(v) for k, v in current.items()}

        baseline, is_new = _load_or_save_baseline("factor_return_means", current)

        if is_new:
            pytest.skip("Baseline created — run again to compare")

        for factor in current:
            if factor not in baseline:
                continue
            cur = current[factor]
            base = baseline[factor]
            if abs(base) < 1e-8:
                # For near-zero means, use absolute tolerance
                assert abs(cur - base) < 1e-6, (
                    f"{factor}: current={cur:.6e}, baseline={base:.6e}"
                )
            else:
                rel_diff = abs(cur - base) / abs(base)
                assert rel_diff < 0.01, (
                    f"{factor}: current={cur:.6e}, baseline={base:.6e}, "
                    f"rel_diff={rel_diff:.4f}"
                )


class TestCovarianceBaselines:
    def test_covariance_diagonal(self, factor_cov_df):
        """Covariance diagonal should match baseline within 1%."""
        current = {k: float(v) for k, v in zip(
            factor_cov_df.columns, np.diag(factor_cov_df.values)
        )}

        baseline, is_new = _load_or_save_baseline("covariance_diagonal", current)

        if is_new:
            pytest.skip("Baseline created — run again to compare")

        for factor in current:
            if factor not in baseline:
                continue
            cur = current[factor]
            base = baseline[factor]
            if abs(base) < 1e-12:
                assert abs(cur - base) < 1e-12
            else:
                rel_diff = abs(cur - base) / abs(base)
                assert rel_diff < 0.01, (
                    f"{factor}: current={cur:.6e}, baseline={base:.6e}"
                )


class TestR2Baselines:
    def test_r2_mean(self, r2_df):
        """Mean R² should match baseline within 1%."""
        current = {"mean_r2": float(r2_df.iloc[:, 0].mean())}

        baseline, is_new = _load_or_save_baseline("r2_stats", current)

        if is_new:
            pytest.skip("Baseline created — run again to compare")

        cur = current["mean_r2"]
        base = baseline["mean_r2"]
        rel_diff = abs(cur - base) / abs(base)
        assert rel_diff < 0.01, (
            f"R² mean: current={cur:.6f}, baseline={base:.6f}"
        )


class TestFactorStatisticsBaselines:
    def test_factor_statistics(self, factor_stats_df):
        """Factor statistics should match baseline within 1%."""
        current = {}
        for factor in factor_stats_df.index:
            for col in factor_stats_df.columns:
                key = f"{factor}__{col}"
                current[key] = float(factor_stats_df.loc[factor, col])

        baseline, is_new = _load_or_save_baseline("factor_statistics", current)

        if is_new:
            pytest.skip("Baseline created — run again to compare")

        for key in current:
            if key not in baseline:
                continue
            cur = current[key]
            base = baseline[key]
            if abs(base) < 1e-6:
                assert abs(cur - base) < 1e-6, (
                    f"{key}: current={cur:.6e}, baseline={base:.6e}"
                )
            else:
                rel_diff = abs(cur - base) / abs(base)
                assert rel_diff < 0.01, (
                    f"{key}: current={cur:.6e}, baseline={base:.6e}"
                )
