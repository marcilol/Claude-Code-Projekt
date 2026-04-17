"""Shared fixtures for portfolio-xray tests."""
import importlib.util
import os
import sys

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helper: import a function from scripts/ (they are standalone, not a package)
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
MODEL_DIR = os.path.join(DATA_DIR, "model")
BASELINES_DIR = os.path.join(os.path.dirname(__file__), "baselines")


def import_function(script_name: str, function_name: str):
    """Import a function from a script in scripts/."""
    spec = importlib.util.spec_from_file_location(
        script_name.replace(".py", ""),
        os.path.join(SCRIPTS_DIR, script_name),
    )
    module = importlib.util.module_from_spec(spec)
    # Prevent scripts from running their __main__ blocks
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return getattr(module, function_name)


# ---------------------------------------------------------------------------
# Path fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def project_root():
    return PROJECT_ROOT


@pytest.fixture
def model_dir():
    return MODEL_DIR


@pytest.fixture
def baselines_dir():
    return BASELINES_DIR


# ---------------------------------------------------------------------------
# Model data fixtures (lazy-loaded, session-scoped)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def factor_returns_df():
    path = os.path.join(MODEL_DIR, "barra_factor_returns.csv")
    if not os.path.exists(path):
        pytest.skip("barra_factor_returns.csv not found")
    return pd.read_csv(path, index_col=0, parse_dates=True)


@pytest.fixture(scope="session")
def factor_cov_df():
    path = os.path.join(MODEL_DIR, "barra_factor_covariance.csv")
    if not os.path.exists(path):
        pytest.skip("barra_factor_covariance.csv not found")
    return pd.read_csv(path, index_col=0)


@pytest.fixture(scope="session")
def factor_stats_df():
    path = os.path.join(MODEL_DIR, "barra_factor_statistics.csv")
    if not os.path.exists(path):
        pytest.skip("barra_factor_statistics.csv not found")
    return pd.read_csv(path, index_col=0)


@pytest.fixture(scope="session")
def r2_df():
    path = os.path.join(MODEL_DIR, "barra_r2.csv")
    if not os.path.exists(path):
        pytest.skip("barra_r2.csv not found")
    return pd.read_csv(path, index_col=0, parse_dates=True)


@pytest.fixture(scope="session")
def factor_exposures_df():
    path = os.path.join(MODEL_DIR, "russell3000_factor_exposures_historical.csv")
    if not os.path.exists(path):
        pytest.skip("russell3000_factor_exposures_historical.csv not found")
    return pd.read_csv(path, parse_dates=["date"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
STYLE_FACTORS = [
    "size", "beta", "momentum", "residvol", "nlsize",
    "btop", "liquidity", "earnyild", "growth", "leverage",
]

INDUSTRY_FACTORS_25 = [
    "Automobiles & Components", "Banks", "Capital Goods",
    "Commercial & Professional Services",
    "Consumer Discretionary Distribution & Retail",
    "Consumer Durables & Apparel", "Consumer Services",
    "Consumer Staples Distribution & Retail", "Energy",
    "Equity Real Estate Investment Trusts (REITs)",
    "Financial Services", "Food, Beverage & Tobacco",
    "Health Care Equipment & Services", "Household & Personal Products",
    "Insurance", "Materials", "Media & Entertainment",
    "Pharmaceuticals, Biotechnology & Life Sciences",
    "Real Estate Management & Development",
    "Semiconductors & Semiconductor Equipment", "Software & Services",
    "Technology Hardware & Equipment", "Telecommunication Services",
    "Transportation", "Utilities",
]

# Legacy alias for old tests
INDUSTRY_FACTORS = INDUSTRY_FACTORS_25

ALL_FACTORS = ["Country"] + INDUSTRY_FACTORS_25 + STYLE_FACTORS
N_FACTORS = len(ALL_FACTORS)  # 36
