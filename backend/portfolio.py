"""Portfolio risk decomposition: factor vs idiosyncratic, MCFR matrix, sectors.

Math (Barra-style, daily covariance × 252 for annualization):
  factor_variance   = bᵀ Ω b           where b = Bᵀ w  (Ω in DAILY units)
  factor_var_annual = factor_variance × 252
  idio_variance_i   = σ_idio_i² (annualized; computed from residual std × √252)
  total_var_annual  = factor_var_annual + Σ wᵢ² σ_idio_i²

MCFR (per factor k):
  contribution_k = b_k × (Ω b)_k / sqrt(b' Ω b)        (in factor-vol space)
  MCFR_k_pct     = b_k × (Ω b)_k / (b' Ω b) × 100      (% of factor variance)

Joint stock × factor MCFR:
  M[i,k] = w_i × β_{i,k} × (Ω b)_k / sqrt(b' Ω b)
"""
from __future__ import annotations

import csv
import os
from functools import lru_cache

import numpy as np
import pandas as pd

from db import prices_for_tickers, stock_meta
from factors import load_factor_returns
from theme import STYLE_DISPLAY_NAMES, STYLE_FACTORS

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CROSS_SECTIONAL_CSV = os.path.join(
    PROJECT_ROOT, "data", "model", "russell3000_cross_sectional_data.csv"
)
FACTOR_COV_CSV = os.path.join(
    PROJECT_ROOT, "data", "model", "barra_factor_covariance.csv"
)
DEFAULT_PORTFOLIO = os.path.join(
    PROJECT_ROOT, "data", "input", "portfolios", "own_ibkr_us_mapped.csv"
)


@lru_cache(maxsize=1)
def load_factor_cov() -> pd.DataFrame:
    return pd.read_csv(FACTOR_COV_CSV, index_col=0)


@lru_cache(maxsize=1)
def load_cross_sectional() -> pd.DataFrame:
    """Full Russell 3000 panel: date, stocknames, capital, ret, industries, styles.

    Loaded once and cached (~374 MB → 10-20s on first access).
    """
    df = pd.read_csv(CROSS_SECTIONAL_CSV)
    df["date"] = pd.to_datetime(df["date"])
    return df


def read_portfolio(path: str) -> pd.DataFrame:
    """Auto-detect delimiter; return DataFrame with ticker, shares columns."""
    with open(path, "r", encoding="utf-8-sig") as f:
        sample = f.read(2048)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;")
            sep = dialect.delimiter
        except csv.Error:
            sep = ","
        df = pd.read_csv(f, sep=sep)
    df.columns = [c.strip().lower() for c in df.columns]
    if "ticker" not in df or "shares" not in df:
        raise ValueError(f"{path}: missing ticker/shares columns")
    df["shares"] = pd.to_numeric(df["shares"], errors="coerce")
    df = df.dropna(subset=["ticker", "shares"])
    df["ticker"] = df["ticker"].astype(str).str.strip()
    return df


def latest_close(tickers: list[str]) -> pd.Series:
    """Last available close per ticker. Missing tickers return NaN."""
    prices = prices_for_tickers(tickers)
    if prices.empty:
        return pd.Series(dtype=float, index=tickers)
    last = (
        prices.sort_values(["ticker", "date"])
        .groupby("ticker", as_index=True)["close"]
        .last()
    )
    return last.reindex(tickers)


def _industry_factors(cov: pd.DataFrame) -> list[str]:
    return [c for c in cov.columns if c not in STYLE_FACTORS + ["Country"]]


def _portfolio_idio_vols(weights: pd.Series, cs_df: pd.DataFrame, factor_ret: pd.DataFrame) -> pd.Series:
    """Per-stock annualized idio vol = std(residual_daily) × √252.

    residual_t = ret_t - country_t - sector_t - Σ_k z_{i,k,t} × f_{k,t}
    """
    industry_cols = [c for c in factor_ret.columns if c not in STYLE_FACTORS + ["Country"]]
    factor_ret_idx = factor_ret.copy()
    factor_ret_idx.index = pd.to_datetime(factor_ret_idx.index)

    idio_vols: dict[str, float] = {}
    for ticker in weights.index:
        rows = cs_df[cs_df["stocknames"] == ticker]
        if len(rows) < 60:
            idio_vols[ticker] = np.nan
            continue
        rows = rows.sort_values("date").set_index("date")
        common = rows.index.intersection(factor_ret_idx.index)
        if len(common) < 60:
            idio_vols[ticker] = np.nan
            continue

        ret_actual = rows.loc[common, "ret"].astype(float)
        f_ret = factor_ret_idx.loc[common]

        # Find this stock's industry by looking at which industry dummy is 1
        ind_dummy_row = rows.iloc[-1][industry_cols] if industry_cols else None
        industry = None
        if ind_dummy_row is not None:
            non_zero = ind_dummy_row[ind_dummy_row.abs() > 0.5]
            if len(non_zero):
                industry = non_zero.index[0]

        # Predicted return from country + industry + style exposures
        predicted = pd.Series(f_ret.get("Country", 0.0), index=common, dtype=float).values * 0
        if "Country" in f_ret.columns:
            predicted = predicted + f_ret["Country"].values
        if industry and industry in f_ret.columns:
            predicted = predicted + f_ret[industry].values
        for sf in STYLE_FACTORS:
            if sf in rows.columns and sf in f_ret.columns:
                predicted = predicted + rows.loc[common, sf].values * f_ret[sf].values

        residual = ret_actual.values - predicted
        sigma = float(np.std(residual, ddof=1))
        idio_vols[ticker] = sigma * np.sqrt(252.0)

    return pd.Series(idio_vols)


def analyze_portfolio(path: str = DEFAULT_PORTFOLIO) -> dict:
    """Full portfolio risk decomposition for the frontend."""
    portfolio = read_portfolio(path)
    tickers = portfolio["ticker"].tolist()

    # 1. Current weights
    closes = latest_close(tickers)
    portfolio = portfolio.assign(close=closes.values)
    portfolio["value"] = portfolio["shares"] * portfolio["close"]
    portfolio = portfolio.dropna(subset=["value"])
    total_value = float(portfolio["value"].sum())
    if total_value <= 0:
        raise ValueError("Portfolio total value is zero — no priced positions")
    portfolio["weight"] = portfolio["value"] / total_value

    weights = portfolio.set_index("ticker")["weight"].astype(float)

    # 2. Latest factor exposures from cross-sectional snapshot
    cs_df = load_cross_sectional()
    last_date = cs_df["date"].max()
    snapshot = cs_df[cs_df["date"] == last_date].set_index("stocknames")

    # Filter to tickers present in snapshot (Russell 3000 universe only)
    in_universe = weights.index.intersection(snapshot.index)
    not_in_universe = sorted(set(weights.index) - set(in_universe))
    weights = weights.loc[in_universe]
    weights = weights / weights.sum()  # renormalize over priced + in-universe
    snap = snapshot.loc[weights.index]

    cov = load_factor_cov()
    factor_names = list(cov.columns)
    industry_cols = _industry_factors(cov)

    # Build exposure matrix B (n_stocks × n_factors)
    B = pd.DataFrame(0.0, index=weights.index, columns=factor_names)
    if "Country" in factor_names:
        B["Country"] = 1.0
    for ticker in weights.index:
        # Industry: pick the dummy with value 1 (or closest to 1)
        if industry_cols:
            ind = snap.loc[ticker, industry_cols]
            if len(ind):
                hot = ind.idxmax()
                if abs(ind[hot]) > 0.5:
                    B.loc[ticker, hot] = 1.0
        for sf in STYLE_FACTORS:
            if sf in snap.columns and sf in factor_names:
                B.loc[ticker, sf] = float(snap.loc[ticker, sf])

    # 3. Factor variance (DAILY units), then annualize
    b = (weights.values @ B.values)              # portfolio factor exposure vector
    Omega = cov.values                            # daily
    Omega_b = Omega @ b
    factor_var_daily = float(b @ Omega_b)
    factor_var_annual = factor_var_daily * 252.0
    factor_vol_annual = float(np.sqrt(factor_var_annual))

    # 4. Idio variance — per-stock residual std (annualized) → σ_idio
    factor_ret = load_factor_returns()
    idio_vols = _portfolio_idio_vols(weights, cs_df, factor_ret)
    idio_vols_filled = idio_vols.reindex(weights.index)
    # Stocks without enough history: substitute median of computed
    median_idio = float(np.nanmedian(idio_vols_filled.values))
    idio_vols_filled = idio_vols_filled.fillna(median_idio)
    idio_var_annual = float(((weights.values ** 2) * (idio_vols_filled.values ** 2)).sum())

    total_var_annual = factor_var_annual + idio_var_annual
    total_vol_annual = float(np.sqrt(total_var_annual))
    pct_factor = float(factor_var_annual / total_var_annual * 100.0) if total_var_annual > 0 else 0.0
    pct_idio = float(idio_var_annual / total_var_annual * 100.0) if total_var_annual > 0 else 0.0

    # 5. MCFR per factor (% of factor variance)
    factor_var_safe = factor_var_daily if factor_var_daily > 0 else 1e-12
    mcfr_pct = (b * Omega_b) / factor_var_safe * 100.0
    mcfr_rows = []
    for i, fn in enumerate(factor_names):
        kind = (
            "country" if fn == "Country"
            else "industry" if fn in industry_cols
            else "style"
        )
        mcfr_rows.append({
            "factor": fn,
            "display": STYLE_DISPLAY_NAMES.get(fn, fn),
            "kind": kind,
            "exposure": float(b[i]),
            "mcfr_pct": float(mcfr_pct[i]),
        })
    mcfr_rows.sort(key=lambda r: abs(r["mcfr_pct"]), reverse=True)

    # 6. Stock × factor MCFR matrix (style factors only — most actionable)
    style_idx = [i for i, fn in enumerate(factor_names) if fn in STYLE_FACTORS]
    style_factors_in_cov = [factor_names[i] for i in style_idx]
    Omega_b_style = Omega_b[style_idx]
    factor_vol_daily = np.sqrt(factor_var_safe)
    matrix_rows = []
    for ticker in weights.index:
        beta_row = B.loc[ticker, style_factors_in_cov].values
        contrib = weights[ticker] * beta_row * Omega_b_style / factor_vol_daily
        # Convert to annualized factor-vol contribution units (×√252)
        contrib_annual = contrib * np.sqrt(252.0)
        matrix_rows.append({
            "ticker": ticker,
            "weight": float(weights[ticker]),
            "stock_total": float(contrib_annual.sum()),
            "by_factor": {
                STYLE_DISPLAY_NAMES[style_factors_in_cov[k]]: float(contrib_annual[k])
                for k in range(len(style_factors_in_cov))
            },
        })
    matrix_rows.sort(key=lambda r: abs(r["stock_total"]), reverse=True)

    # 7. Sector exposure pie (GICS sector from stocks table; fall back to "Unknown")
    meta = stock_meta(weights.index.tolist()).set_index("ticker")
    sector_weights: dict[str, float] = {}
    for ticker in weights.index:
        sector = "Unknown"
        if ticker in meta.index:
            s = meta.loc[ticker, "gic_sector"]
            if isinstance(s, str) and s.strip():
                sector = s
        sector_weights[sector] = sector_weights.get(sector, 0.0) + float(weights[ticker])
    sector_pie = sorted(
        [{"sector": k, "weight": v} for k, v in sector_weights.items()],
        key=lambda r: r["weight"], reverse=True,
    )

    return {
        "portfolio_path": os.path.basename(path),
        "as_of": last_date.strftime("%Y-%m-%d"),
        "n_positions": int(len(weights)),
        "skipped_not_in_universe": not_in_universe,
        "total_value": total_value,
        "decomposition": {
            "factor_var_annual": factor_var_annual,
            "idio_var_annual": idio_var_annual,
            "total_var_annual": total_var_annual,
            "factor_vol_annual_pct": factor_vol_annual * 100.0,
            "total_vol_annual_pct": total_vol_annual * 100.0,
            "pct_factor": pct_factor,
            "pct_idio": pct_idio,
        },
        "mcfr": mcfr_rows,
        "mcfr_matrix": {
            "style_factors": [STYLE_DISPLAY_NAMES[f] for f in style_factors_in_cov],
            "rows": matrix_rows,
        },
        "sector_pie": sector_pie,
    }
