# -*- coding: utf-8 -*-
"""
Generate interactive Excel verification workbook with formula-driven risk decomposition.

Produces 6 sheets where every risk calculation is an Excel formula (SUMPRODUCT,
SQRT, STDEV.P) so users can change weights, trace formulas, and verify the
Python pipeline's math.

Sheets:
  1. Stocks      — Editable input (20 rows): weights, exposures, idio vol formula
  2. Covariance  — 22x22 factor covariance matrix
  3. FactorReturns — ~21 days x 22 factors (Aug 2025)
  4. Residuals   — ~244 dates x 20 stocks (daily residuals)
  5. RiskDecomp  — ALL FORMULAS: factor exposures, Omega*b, risk decomposition
  6. Regression  — Single-day example with predicted/residual formulas

Usage:
    python scripts/generate_verification_excel.py
"""

import importlib.util
import os
import sys

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------------------
# Import helpers from project scripts
# ---------------------------------------------------------------------------
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))


def _import(script, name):
    spec = importlib.util.spec_from_file_location(
        script.replace(".py", ""), os.path.join(SCRIPTS_DIR, script)
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return getattr(mod, name)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
STYLE_FACTORS = [
    "size", "beta", "momentum", "residvol", "nlsize",
    "btop", "liquidity", "earnyild", "growth", "leverage",
]

INDUSTRY_FACTORS = [
    "Communication", "Consumer Discretionary", "Consumer Staples",
    "Energy", "Financials", "Health Care", "Industrials",
    "Information Technology", "Materials", "Real Estate", "Utilities",
]

ALL_FACTORS = ["Country"] + INDUSTRY_FACTORS + STYLE_FACTORS

# 20 stocks: 2 per sector (1 large, 1 small) across 10 sectors
SELECTED_TICKERS = sorted([
    "META", "CCOI",           # Communication
    "AMZN", "ASO",            # Consumer Discretionary
    "WMT", "FIZZ",            # Consumer Staples
    "JPM", "PFS",             # Financials
    "LLY", "TVTX",            # Health Care
    "GE", "MMS",              # Industrials
    "NVDA", "DLB",            # Information Technology
    "LIN", "USLM",           # Materials
    "XOM", "WHD",             # Energy
    "NEE", "AES",             # Utilities
])

DATE_START = "2025-08-01"
DATE_END = "2025-08-31"

OUTPUT_PATH = "data/model/verification_workbook.xlsx"

# Styling
FILL_INPUT = PatternFill(start_color="FFFFF2CC", end_color="FFFFF2CC", fill_type="solid")  # light yellow
FILL_FORMULA = PatternFill(start_color="FFC6EFCE", end_color="FFC6EFCE", fill_type="solid")  # light green
FILL_HEADER = PatternFill(start_color="FFD9E1F2", end_color="FFD9E1F2", fill_type="solid")  # light blue
FONT_HEADER = Font(bold=True)
FONT_SECTION = Font(bold=True, size=12)
THIN_BORDER = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin"),
)
NUM_FMT_6 = "0.000000"
NUM_FMT_4 = "0.0000"
NUM_FMT_2 = "0.00"
NUM_FMT_PCT = "0.00%"
NUM_FMT_8 = "0.00000000"

# Raw sub-descriptors (17 total) — these go on the Universe sheet
RAW_DESCRIPTORS = [
    "size_raw", "beta_raw", "momentum_raw", "btop_raw",
    "dastd_raw", "cmra_raw", "hsigma_raw",
    "stom_raw", "stoq_raw", "stoa_raw",
    "etop_raw", "cetop_raw",
    "egro_raw", "sgro_raw",
    "mlev_raw", "dtoa_raw", "blev_raw",
]

# Sub-descriptors that get z-scored (13 — excludes size/beta/momentum/btop which are direct)
SUB_DESCRIPTORS = [
    "dastd", "cmra", "hsigma",
    "stom", "stoq", "stoa",
    "etop", "cetop",
    "egro", "sgro",
    "mlev", "dtoa", "blev",
]

# Representative date for Universe/ZScoring/WLS sheets
REP_DATE = "2025-08-15"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_data():
    """Load the three main model CSV files."""
    factor_exp = pd.read_csv(
        "data/model/russell3000_factor_exposures_historical.csv",
        parse_dates=["date"],
    )
    factor_ret = pd.read_csv("data/model/barra_factor_returns.csv", index_col=0)
    factor_cov = pd.read_csv("data/model/barra_factor_covariance.csv", index_col=0)
    return factor_exp, factor_ret, factor_cov


def filter_subset(factor_exp):
    """Filter to selected tickers and date range."""
    mask = (
        factor_exp["ticker"].isin(SELECTED_TICKERS)
        & (factor_exp["date"] >= DATE_START)
        & (factor_exp["date"] <= DATE_END)
    )
    return factor_exp[mask].copy()


# ---------------------------------------------------------------------------
# Compute Python reference values
# ---------------------------------------------------------------------------
def compute_python_references(subset, factor_exp_full, factor_ret_df, factor_cov):
    """Compute all Python reference values for comparison with Excel formulas."""
    tickers = sorted(SELECTED_TICKERS)
    n = len(tickers)
    weights = {t: 1.0 / n for t in tickers}

    latest_date = subset["date"].max()
    latest = subset[subset["date"] == latest_date].copy()
    latest = latest[latest["ticker"].isin(tickers)]

    # --- Portfolio factor exposures ---
    all_exposures = {"Country": 1.0}
    for ind in INDUSTRY_FACTORS:
        ind_dummy = (latest["sector"] == ind).astype(float)
        exp = sum(weights[t] * ind_dummy[latest["ticker"] == t].values[0]
                  for t in latest["ticker"] if t in weights)
        all_exposures[ind] = exp
    for sf in STYLE_FACTORS:
        exp = sum(weights[t] * latest.loc[latest["ticker"] == t, sf].values[0]
                  for t in latest["ticker"] if t in weights)
        all_exposures[sf] = exp

    factor_names = factor_cov.columns.tolist()
    b = np.array([all_exposures.get(f, 0) for f in factor_names])
    cov_matrix = factor_cov.values

    # --- Factor variance ---
    factor_var_daily = float(b @ cov_matrix @ b)
    factor_var_annual = factor_var_daily * 252
    factor_vol_annual = np.sqrt(factor_var_annual)

    # --- Omega * b ---
    omega_b = cov_matrix @ b

    # --- Risk contributions ---
    risk_contrib = b * omega_b

    # --- Idiosyncratic volatility (full period, ddof=0) ---
    idio_vols = {}
    for ticker in tickers:
        stock_data = factor_exp_full[factor_exp_full["ticker"] == ticker].copy()
        if len(stock_data) < 20:
            idio_vols[ticker] = np.nan
            continue
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
            idio_vols[ticker] = float(np.std(residuals) * np.sqrt(252))
        else:
            idio_vols[ticker] = np.nan

    w_arr = np.array([weights[t] for t in tickers])
    iv_arr = np.array([idio_vols.get(t, 0) for t in tickers])
    idio_var = float(np.sum(w_arr ** 2 * iv_arr ** 2))
    idio_vol = np.sqrt(idio_var)

    total_var = factor_var_annual + idio_var
    total_vol = np.sqrt(total_var)
    pct_factor = factor_var_annual / total_var * 100 if total_var > 0 else 0
    pct_idio = idio_var / total_var * 100 if total_var > 0 else 0

    return {
        "exposures": {f: all_exposures.get(f, 0) for f in factor_names},
        "omega_b": {f: omega_b[i] for i, f in enumerate(factor_names)},
        "risk_contrib": {f: risk_contrib[i] for i, f in enumerate(factor_names)},
        "factor_var_daily": factor_var_daily,
        "factor_var_annual": factor_var_annual,
        "factor_vol_annual": factor_vol_annual,
        "idio_vols": idio_vols,
        "idio_var": idio_var,
        "idio_vol": idio_vol,
        "total_var": total_var,
        "total_vol": total_vol,
        "pct_factor": pct_factor,
        "pct_idio": pct_idio,
    }


def compute_residuals_full(tickers, factor_exp_full, factor_ret_df):
    """Compute daily residuals for each stock over full history."""
    all_residuals = {}
    all_dates = set()
    for ticker in tickers:
        stock_data = factor_exp_full[factor_exp_full["ticker"] == ticker].copy()
        stock_data = stock_data.sort_values("date")
        resid_dict = {}
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
            resid_dict[date_str] = r_actual - r_predicted
            all_dates.add(date_str)
        all_residuals[ticker] = resid_dict

    dates_sorted = sorted(all_dates)
    resid_df = pd.DataFrame(index=dates_sorted, columns=tickers, dtype=float)
    for ticker in tickers:
        for d, v in all_residuals[ticker].items():
            resid_df.loc[d, ticker] = v
    return resid_df


# ---------------------------------------------------------------------------
# Sheet builders (openpyxl cell-by-cell)
# ---------------------------------------------------------------------------
def write_stocks_sheet(wb, subset, factor_cov, tickers, universe_row_map=None):
    """Sheet 1: Stocks — editable weights, exposures (formula-linked to ZScoring), idio vol formula."""
    ws = wb.create_sheet("Stocks")
    n = len(tickers)

    latest_date = subset["date"].max()
    latest = subset[subset["date"] == latest_date].copy()
    latest = latest.set_index("ticker").loc[tickers].reset_index()

    # ZScoring column for each style factor:
    # Non-orthogonalized → pre-orth z-score columns (U-AD)
    # Orthogonalized → orth columns (AE-AG)
    ZSCORE_COL_MAP = {
        "size": "U",           # col 21: z_pre(size)
        "beta": "V",           # col 22: z_pre(beta)
        "momentum": "W",       # col 23: z_pre(momentum)
        "residvol": "AF",      # col 32: residvol_orth
        "nlsize": "AE",        # col 31: nlsize_orth
        "btop": "Z",           # col 26: z_pre(btop)
        "liquidity": "AG",     # col 33: liq_orth
        "earnyild": "AB",      # col 28: z_pre(earnyild)
        "growth": "AC",        # col 29: z_pre(growth)
        "leverage": "AD",      # col 30: z_pre(leverage)
    }

    # Header row (row 1)
    headers = ["Ticker", "Weight", "Sector", "Market Cap", "Country"]
    headers += INDUSTRY_FACTORS
    headers += STYLE_FACTORS
    headers += ["Idio Vol"]

    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.border = THIN_BORDER

    # Data rows (rows 2-21)
    for i, ticker in enumerate(tickers):
        row = i + 2
        stock = latest[latest["ticker"] == ticker].iloc[0]

        # A: Ticker
        ws.cell(row=row, column=1, value=ticker).fill = FILL_INPUT

        # B: Weight (editable, default = 1/20)
        cell = ws.cell(row=row, column=2, value=1.0 / n)
        cell.fill = FILL_INPUT
        cell.number_format = NUM_FMT_6

        # C: Sector
        ws.cell(row=row, column=3, value=stock["sector"]).fill = FILL_INPUT

        # D: Market Cap
        ws.cell(row=row, column=4, value=float(stock["market_cap"])).fill = FILL_INPUT

        # E: Country (always 1)
        ws.cell(row=row, column=5, value=1).fill = FILL_INPUT

        # F-P: Industry dummies (cols 6-16)
        for j, ind in enumerate(INDUSTRY_FACTORS):
            val = 1 if stock["sector"] == ind else 0
            ws.cell(row=row, column=6 + j, value=val).fill = FILL_INPUT

        # Q-Z: Style z-scores (cols 17-26) — FORMULA if universe mapping available
        u_row = universe_row_map.get(ticker) if universe_row_map else None
        for j, sf in enumerate(STYLE_FACTORS):
            if u_row is not None:
                zs_col = ZSCORE_COL_MAP[sf]
                formula = f"=ZScoring!{zs_col}{u_row}"
                cell = ws.cell(row=row, column=17 + j, value=formula)
                cell.fill = FILL_FORMULA
            else:
                val = float(stock[sf]) if pd.notna(stock[sf]) else 0.0
                cell = ws.cell(row=row, column=17 + j, value=val)
                cell.fill = FILL_INPUT
            cell.number_format = NUM_FMT_4

        # AA (col 27): Idio Vol = STDEVP(Residuals!col)*SQRT(252)
        resid_col = get_column_letter(i + 2)  # Residuals sheet: B=stock1, C=stock2, etc.
        formula = f"=STDEVP(Residuals!{resid_col}2:{resid_col}500)*SQRT(252)"
        cell = ws.cell(row=row, column=27, value=formula)
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_6

    # Set column widths
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 10
    ws.column_dimensions["C"].width = 24
    ws.column_dimensions["D"].width = 14
    for c in range(5, 28):
        ws.column_dimensions[get_column_letter(c)].width = 12


def write_covariance_sheet(wb, factor_cov):
    """Sheet 2: Covariance — 22x22 matrix."""
    ws = wb.create_sheet("Covariance")
    factor_names = factor_cov.columns.tolist()

    # Header row: B1:W1 = factor names
    for j, f in enumerate(factor_names):
        cell = ws.cell(row=1, column=j + 2, value=f)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.border = THIN_BORDER

    # Row labels: A2:A23 = factor names, data: B2:W23
    for i, fi in enumerate(factor_names):
        cell = ws.cell(row=i + 2, column=1, value=fi)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.border = THIN_BORDER

        for j, fj in enumerate(factor_names):
            val = float(factor_cov.iloc[i, j])
            cell = ws.cell(row=i + 2, column=j + 2, value=val)
            cell.fill = FILL_INPUT
            cell.number_format = "0.00000000E+00"
            cell.border = THIN_BORDER

    ws.column_dimensions["A"].width = 24
    for c in range(2, 24):
        ws.column_dimensions[get_column_letter(c)].width = 14


def write_factor_returns_sheet(wb, factor_ret_df):
    """Sheet 3: FactorReturns — ~21 days x 22 factors."""
    ws = wb.create_sheet("FactorReturns")

    dates = sorted([d for d in factor_ret_df.index if DATE_START <= d <= DATE_END])

    # Header: A1=Date, B1-W1=factor names
    ws.cell(row=1, column=1, value="Date").font = FONT_HEADER
    ws.cell(row=1, column=1).fill = FILL_HEADER
    for j, f in enumerate(ALL_FACTORS):
        cell = ws.cell(row=1, column=j + 2, value=f)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER

    for i, d in enumerate(dates):
        ws.cell(row=i + 2, column=1, value=d).fill = FILL_INPUT
        for j, f in enumerate(ALL_FACTORS):
            val = float(factor_ret_df.loc[d, f])
            cell = ws.cell(row=i + 2, column=j + 2, value=val)
            cell.fill = FILL_INPUT
            cell.number_format = NUM_FMT_6

    ws.column_dimensions["A"].width = 12
    for c in range(2, 24):
        ws.column_dimensions[get_column_letter(c)].width = 14


def write_residuals_sheet(wb, resid_df, tickers):
    """Sheet 4: Residuals — dates x 20 stocks."""
    ws = wb.create_sheet("Residuals")

    # Header: A1=Date, B1-U1=ticker names (alphabetical)
    ws.cell(row=1, column=1, value="Date").font = FONT_HEADER
    ws.cell(row=1, column=1).fill = FILL_HEADER
    for j, t in enumerate(tickers):
        cell = ws.cell(row=1, column=j + 2, value=t)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER

    dates = resid_df.index.tolist()
    for i, d in enumerate(dates):
        ws.cell(row=i + 2, column=1, value=d).fill = FILL_INPUT
        for j, t in enumerate(tickers):
            val = resid_df.loc[d, t]
            if pd.notna(val):
                cell = ws.cell(row=i + 2, column=j + 2, value=float(val))
                cell.number_format = NUM_FMT_6

    # Update Stocks sheet idio vol formulas to use correct last row
    last_row = len(dates) + 1
    stocks_ws = wb["Stocks"]
    for i in range(len(tickers)):
        resid_col = get_column_letter(i + 2)
        formula = f"=STDEVP(Residuals!{resid_col}2:{resid_col}{last_row})*SQRT(252)"
        stocks_ws.cell(row=i + 2, column=27, value=formula).fill = FILL_FORMULA

    ws.column_dimensions["A"].width = 12
    for c in range(2, 22):
        ws.column_dimensions[get_column_letter(c)].width = 12


def write_risk_decomp_sheet(wb, py_ref, tickers):
    """Sheet 5: RiskDecomp — ALL FORMULAS with Python reference values."""
    ws = wb.create_sheet("RiskDecomp")
    n = len(tickers)  # 20

    # Helpers
    def section_header(row, text):
        cell = ws.cell(row=row, column=1, value=text)
        cell.font = FONT_SECTION

    def col_headers(row, labels):
        for c, lbl in enumerate(labels, 1):
            cell = ws.cell(row=row, column=c, value=lbl)
            cell.font = FONT_HEADER
            cell.fill = FILL_HEADER
            cell.border = THIN_BORDER

    # ===================================================================
    # SECTION 1: PORTFOLIO FACTOR EXPOSURES (rows 2-26)
    # ===================================================================
    section_header(1, "PORTFOLIO FACTOR EXPOSURES")
    col_headers(2, ["Factor", "Exposure (formula)", "Python Reference"])
    # Explanation row
    ws.cell(row=3, column=1, value="b_k = SUMPRODUCT(weights, stock_exposures_k)")
    ws.cell(row=3, column=1).font = Font(italic=True)

    # Rows 4-25: one per factor (22 factors)
    for i, factor in enumerate(ALL_FACTORS):
        row = 4 + i
        ws.cell(row=row, column=1, value=factor).border = THIN_BORDER

        # Col B: SUMPRODUCT formula
        # Stocks sheet: weights in B2:B21, factor k in column (5+i) = E,F,...Z
        factor_col = get_column_letter(5 + i)  # E=Country, F=Communication, ...
        formula = f"=SUMPRODUCT(Stocks!$B$2:$B${n+1},Stocks!{factor_col}$2:{factor_col}${n+1})"
        cell = ws.cell(row=row, column=2, value=formula)
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_6
        cell.border = THIN_BORDER

        # Col C: Python reference
        ref_val = py_ref["exposures"].get(factor, 0)
        cell = ws.cell(row=row, column=3, value=ref_val)
        cell.number_format = NUM_FMT_6
        cell.border = THIN_BORDER

    # ===================================================================
    # SECTION 2: Omega x b VECTOR (rows 28-51)
    # ===================================================================
    section_header(27, "COVARIANCE × EXPOSURE VECTOR (Ω × b)")
    col_headers(28, ["Factor", "(Ω×b)_k (formula)", "Python Reference"])
    ws.cell(row=29, column=1, value="(Ω×b)_k = SUMPRODUCT(Covariance row k, exposure vector)")
    ws.cell(row=29, column=1).font = Font(italic=True)

    for i, factor in enumerate(ALL_FACTORS):
        row = 30 + i
        ws.cell(row=row, column=1, value=factor).border = THIN_BORDER

        # Covariance row i is in Covariance!B{i+2}:W{i+2} (a ROW: 1×22)
        # Exposure vector is in RiskDecomp!B4:B25 (a COLUMN: 22×1)
        # Excel SUMPRODUCT requires matching dimensions, so TRANSPOSE the row
        cov_row = i + 2
        formula = f"=SUMPRODUCT(TRANSPOSE(Covariance!B${cov_row}:W${cov_row}),$B$4:$B$25)"
        cell = ws.cell(row=row, column=2, value=formula)
        cell.fill = FILL_FORMULA
        cell.number_format = "0.00000000E+00"
        cell.border = THIN_BORDER

        ref_val = py_ref["omega_b"].get(factor, 0)
        cell = ws.cell(row=row, column=3, value=ref_val)
        cell.number_format = "0.00000000E+00"
        cell.border = THIN_BORDER

    # ===================================================================
    # SECTION 3: RISK CONTRIBUTIONS (rows 53-77)
    # ===================================================================
    section_header(53, "PER-FACTOR RISK CONTRIBUTIONS")
    col_headers(54, ["Factor", "Exposure (b_k)", "(Ω×b)_k", "Contribution (b_k × (Ω×b)_k)", "% of Factor Risk", "Python Ref (contrib)"])

    for i, factor in enumerate(ALL_FACTORS):
        row = 55 + i
        ws.cell(row=row, column=1, value=factor).border = THIN_BORDER

        # B: exposure = reference to Section 1
        exp_row = 4 + i
        cell = ws.cell(row=row, column=2, value=f"=B{exp_row}")
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_6
        cell.border = THIN_BORDER

        # C: Omega*b = reference to Section 2
        ob_row = 30 + i
        cell = ws.cell(row=row, column=3, value=f"=B{ob_row}")
        cell.fill = FILL_FORMULA
        cell.number_format = "0.00000000E+00"
        cell.border = THIN_BORDER

        # D: risk contribution = B * C
        cell = ws.cell(row=row, column=4, value=f"=B{row}*C{row}")
        cell.fill = FILL_FORMULA
        cell.number_format = "0.00000000E+00"
        cell.border = THIN_BORDER

        # E: % of factor risk = D / D_total * 100
        total_row = 55 + len(ALL_FACTORS)  # row 77
        cell = ws.cell(row=row, column=5, value=f"=D{row}/D${total_row}*100")
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_2
        cell.border = THIN_BORDER

        # F: Python reference
        ref_val = py_ref["risk_contrib"].get(factor, 0)
        cell = ws.cell(row=row, column=6, value=ref_val)
        cell.number_format = "0.00000000E+00"
        cell.border = THIN_BORDER

    # TOTAL row
    total_row = 55 + len(ALL_FACTORS)  # row 77
    ws.cell(row=total_row, column=1, value="TOTAL").font = FONT_HEADER
    ws.cell(row=total_row, column=4, value=f"=SUM(D55:D{total_row-1})")
    ws.cell(row=total_row, column=4).fill = FILL_FORMULA
    ws.cell(row=total_row, column=4).font = FONT_HEADER
    ws.cell(row=total_row, column=4).number_format = "0.00000000E+00"
    ws.cell(row=total_row, column=5, value=f"=SUM(E55:E{total_row-1})")
    ws.cell(row=total_row, column=5).fill = FILL_FORMULA
    ws.cell(row=total_row, column=5).number_format = NUM_FMT_2
    ws.cell(row=total_row, column=6, value=py_ref["factor_var_daily"])
    ws.cell(row=total_row, column=6).number_format = "0.00000000E+00"

    # ===================================================================
    # SECTION 4: FACTOR RISK (rows 79-83)
    # ===================================================================
    section_header(79, "FACTOR RISK")
    r = 80
    labels = ["Factor Variance (daily)", "Factor Variance (annual)", "Factor Vol (annual)", "Factor Vol %"]
    formulas = [
        f"=D{total_row}",
        f"=B{r}*252",
        f"=SQRT(B{r+1})",
        f"=B{r+2}*100",
    ]
    py_vals = [
        py_ref["factor_var_daily"],
        py_ref["factor_var_annual"],
        py_ref["factor_vol_annual"],
        py_ref["factor_vol_annual"] * 100,
    ]
    for i, (lbl, fml, pyv) in enumerate(zip(labels, formulas, py_vals)):
        row = r + i
        ws.cell(row=row, column=1, value=lbl)
        cell = ws.cell(row=row, column=2, value=fml)
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_6 if i < 3 else NUM_FMT_2
        ws.cell(row=row, column=3, value=pyv).number_format = NUM_FMT_6 if i < 3 else NUM_FMT_2

    # ===================================================================
    # SECTION 5: IDIOSYNCRATIC RISK (rows 86-110)
    # ===================================================================
    section_header(86, "IDIOSYNCRATIC RISK (per stock)")
    col_headers(87, ["Ticker", "Weight", "Idio Vol (from Stocks)", "w² × σ²", "Python Ref (idio vol)"])

    for i, ticker in enumerate(tickers):
        row = 88 + i
        stock_row = i + 2  # Stocks sheet row

        ws.cell(row=row, column=1, value=ticker).border = THIN_BORDER

        # B: weight from Stocks
        cell = ws.cell(row=row, column=2, value=f"=Stocks!B{stock_row}")
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_6
        cell.border = THIN_BORDER

        # C: idio vol from Stocks!AA
        cell = ws.cell(row=row, column=3, value=f"=Stocks!AA{stock_row}")
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_6
        cell.border = THIN_BORDER

        # D: w^2 * sigma^2
        cell = ws.cell(row=row, column=4, value=f"=B{row}^2*C{row}^2")
        cell.fill = FILL_FORMULA
        cell.number_format = "0.00000000E+00"
        cell.border = THIN_BORDER

        # E: Python reference idio vol
        ref_val = py_ref["idio_vols"].get(ticker, np.nan)
        cell = ws.cell(row=row, column=5, value=ref_val if pd.notna(ref_val) else "N/A")
        cell.number_format = NUM_FMT_6
        cell.border = THIN_BORDER

    # Idio summary rows
    idio_sum_row = 88 + n  # row 108
    ws.cell(row=idio_sum_row, column=1, value="Idio Variance (Σ w²σ²)").font = FONT_HEADER
    cell = ws.cell(row=idio_sum_row, column=2, value=f"=SUM(D88:D{idio_sum_row-1})")
    cell.fill = FILL_FORMULA
    cell.number_format = NUM_FMT_6
    ws.cell(row=idio_sum_row, column=3, value=py_ref["idio_var"]).number_format = NUM_FMT_6

    ws.cell(row=idio_sum_row + 1, column=1, value="Idio Vol %").font = FONT_HEADER
    cell = ws.cell(row=idio_sum_row + 1, column=2, value=f"=SQRT(B{idio_sum_row})*100")
    cell.fill = FILL_FORMULA
    cell.number_format = NUM_FMT_2
    ws.cell(row=idio_sum_row + 1, column=3, value=py_ref["idio_vol"] * 100).number_format = NUM_FMT_2

    # ===================================================================
    # SECTION 6: TOTAL RISK (rows 112-117)
    # ===================================================================
    total_start = idio_sum_row + 3  # row 111
    section_header(total_start, "TOTAL PORTFOLIO RISK")

    labels2 = [
        "Total Variance (annual)",
        "Total Vol (annual)",
        "Total Vol %",
        "% Factor Risk",
        "% Idiosyncratic",
    ]
    # Factor variance annual is in B81, idio variance is in B108
    fvar_cell = f"B{r+1}"   # B81
    ivar_cell = f"B{idio_sum_row}"  # B108
    ts = total_start + 1  # row 112
    formulas2 = [
        f"={fvar_cell}+{ivar_cell}",
        f"=SQRT(B{ts})",
        f"=B{ts+1}*100",
        f"={fvar_cell}/B{ts}*100",
        f"={ivar_cell}/B{ts}*100",
    ]
    py_vals2 = [
        py_ref["total_var"],
        py_ref["total_vol"],
        py_ref["total_vol"] * 100,
        py_ref["pct_factor"],
        py_ref["pct_idio"],
    ]
    for i, (lbl, fml, pyv) in enumerate(zip(labels2, formulas2, py_vals2)):
        row = ts + i
        ws.cell(row=row, column=1, value=lbl)
        cell = ws.cell(row=row, column=2, value=fml)
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_6 if i < 2 else NUM_FMT_2
        ws.cell(row=row, column=3, value=pyv).number_format = NUM_FMT_6 if i < 2 else NUM_FMT_2

    # Column widths
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 20
    ws.column_dimensions["C"].width = 20
    ws.column_dimensions["D"].width = 26
    ws.column_dimensions["E"].width = 18
    ws.column_dimensions["F"].width = 20


def write_regression_sheet(wb, subset, factor_exp_full, factor_ret_df):
    """Sheet 6: Regression — single-day example with formulas."""
    ws = wb.create_sheet("Regression")
    tickers = sorted(SELECTED_TICKERS)

    # Pick representative date (mid-month)
    dates = sorted(subset["date"].unique())
    rep_date = dates[min(10, len(dates) - 1)]
    rep_date_str = str(rep_date.date()) if hasattr(rep_date, "date") else str(rep_date)[:10]

    # Get factor returns for this date
    if rep_date_str not in factor_ret_df.index:
        rep_date_str = factor_ret_df.index[factor_ret_df.index >= DATE_START][0]

    f_ret_day = factor_ret_df.loc[rep_date_str]

    # Section 1: Factor returns for this date
    section_row = 1
    ws.cell(row=section_row, column=1, value=f"SINGLE-DAY REGRESSION: {rep_date_str}")
    ws.cell(row=section_row, column=1).font = FONT_SECTION

    ws.cell(row=3, column=1, value="Factor").font = FONT_HEADER
    ws.cell(row=3, column=1).fill = FILL_HEADER
    ws.cell(row=3, column=2, value="Factor Return (from full-universe WLS)").font = FONT_HEADER
    ws.cell(row=3, column=2).fill = FILL_HEADER

    for i, factor in enumerate(ALL_FACTORS):
        row = 4 + i
        ws.cell(row=row, column=1, value=factor)
        val = float(f_ret_day[factor]) if factor in f_ret_day.index else 0.0
        ws.cell(row=row, column=2, value=val).fill = FILL_INPUT
        ws.cell(row=row, column=2).number_format = NUM_FMT_6

    # Section 2: Per-stock breakdown
    stock_start = 4 + len(ALL_FACTORS) + 2  # row 28
    ws.cell(row=stock_start - 1, column=1, value="PER-STOCK BREAKDOWN").font = FONT_SECTION

    headers = ["Ticker", "Actual Return"]
    headers += [f"Exp: {f}" for f in ALL_FACTORS]
    headers += ["Predicted (formula)", "Residual (formula)", "Python Predicted", "Python Residual"]

    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=stock_start, column=c, value=h)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER

    # Get per-stock data for this date
    day_data = factor_exp_full[factor_exp_full["date"] == rep_date].copy()

    for si, ticker in enumerate(tickers):
        row = stock_start + 1 + si
        stock_row = day_data[day_data["ticker"] == ticker]
        if len(stock_row) == 0:
            ws.cell(row=row, column=1, value=ticker)
            continue

        stock = stock_row.iloc[0]
        ws.cell(row=row, column=1, value=ticker)

        # B: Actual return
        actual = float(stock["return"])
        ws.cell(row=row, column=2, value=actual).fill = FILL_INPUT

        # C-X: Exposures (22 columns: Country=1, industry dummies, style z-scores)
        for fi, factor in enumerate(ALL_FACTORS):
            col = 3 + fi
            if factor == "Country":
                val = 1.0
            elif factor in INDUSTRY_FACTORS:
                val = 1.0 if stock["sector"] == factor else 0.0
            else:
                val = float(stock[factor]) if pd.notna(stock[factor]) else 0.0
            ws.cell(row=row, column=col, value=val).fill = FILL_INPUT

        # Y (col 25): Predicted = SUMPRODUCT(exposures, factor_returns)
        # Exposures are in C{row}:X{row} (a ROW: 1×22)
        # Factor returns in B4:B25 (a COLUMN: 22×1)
        # TRANSPOSE the column to match the row orientation
        exp_start_col = get_column_letter(3)
        exp_end_col = get_column_letter(3 + len(ALL_FACTORS) - 1)
        formula = f"=SUMPRODUCT({exp_start_col}{row}:{exp_end_col}{row},TRANSPOSE($B$4:$B$25))"
        cell = ws.cell(row=row, column=3 + len(ALL_FACTORS), value=formula)
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_6

        # Z (col 26): Residual = Actual - Predicted
        pred_col = get_column_letter(3 + len(ALL_FACTORS))
        formula = f"=B{row}-{pred_col}{row}"
        cell = ws.cell(row=row, column=3 + len(ALL_FACTORS) + 1, value=formula)
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_6

        # Python predicted/residual for comparison
        py_predicted = float(f_ret_day.get("Country", 0))
        if stock["sector"] in f_ret_day.index:
            py_predicted += float(f_ret_day[stock["sector"]])
        for sf in STYLE_FACTORS:
            if sf in f_ret_day.index and pd.notna(stock[sf]):
                py_predicted += float(stock[sf]) * float(f_ret_day[sf])
        py_residual = actual - py_predicted

        ws.cell(row=row, column=3 + len(ALL_FACTORS) + 2, value=py_predicted).number_format = NUM_FMT_6
        ws.cell(row=row, column=3 + len(ALL_FACTORS) + 3, value=py_residual).number_format = NUM_FMT_6

    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 16
    for c in range(3, 30):
        ws.column_dimensions[get_column_letter(c)].width = 14


# ---------------------------------------------------------------------------
# New Sheet: Universe (~2,500 rows for 1 representative date)
# ---------------------------------------------------------------------------
def get_universe_data(factor_exp):
    """Extract full-universe data for the representative date."""
    day = factor_exp[factor_exp["date"] == REP_DATE].copy()
    day = day.sort_values("ticker").reset_index(drop=True)
    return day


def write_universe_sheet(wb, universe_df):
    """Sheet: Universe — raw input data for 1 date with formula columns."""
    ws = wb.create_sheet("Universe")
    N = len(universe_df)

    # Header row
    headers = ["Ticker", "Sector", "Return", "Market Cap",
               "sqrt(mcap)", "mcap_weight", "wls_weight"]
    headers += INDUSTRY_FACTORS  # 11 industry dummies (cols H-R = 8-18)
    headers += [d.replace("_raw", "") for d in RAW_DESCRIPTORS]  # 17 raw descriptors (cols S-AI = 19-35)

    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.border = THIN_BORDER

    # Data rows
    for i, (_, stock) in enumerate(universe_df.iterrows()):
        row = i + 2
        # A: Ticker
        ws.cell(row=row, column=1, value=stock["ticker"]).fill = FILL_INPUT
        # B: Sector
        ws.cell(row=row, column=2, value=stock["sector"]).fill = FILL_INPUT
        # C: Return
        val = float(stock["return"]) if pd.notna(stock["return"]) else ""
        cell = ws.cell(row=row, column=3, value=val)
        cell.fill = FILL_INPUT
        cell.number_format = NUM_FMT_6
        # D: Market Cap
        val = float(stock["market_cap"]) if pd.notna(stock["market_cap"]) else ""
        ws.cell(row=row, column=4, value=val).fill = FILL_INPUT

        # E: sqrt(mcap) — FORMULA
        cell = ws.cell(row=row, column=5, value=f"=SQRT(D{row})")
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_2

        # F: mcap_weight — FORMULA
        cell = ws.cell(row=row, column=6,
                       value=f"=D{row}/SUM($D$2:$D${N+1})")
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_8

        # G: wls_weight — FORMULA
        cell = ws.cell(row=row, column=7,
                       value=f"=E{row}/SUM($E$2:$E${N+1})")
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_8

        # H-R (cols 8-18): Industry dummies
        for j, ind in enumerate(INDUSTRY_FACTORS):
            val = 1 if stock["sector"] == ind else 0
            ws.cell(row=row, column=8 + j, value=val).fill = FILL_INPUT

        # S-AI (cols 19-35): 17 raw descriptors
        for j, desc in enumerate(RAW_DESCRIPTORS):
            val = float(stock[desc]) if (desc in universe_df.columns and pd.notna(stock.get(desc))) else ""
            cell = ws.cell(row=row, column=19 + j, value=val)
            cell.fill = FILL_INPUT
            cell.number_format = NUM_FMT_6

    # Column widths
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 24
    for c in range(3, 36):
        ws.column_dimensions[get_column_letter(c)].width = 14


# ---------------------------------------------------------------------------
# New Sheet: ZScoring — full z-score pipeline as formulas
# ---------------------------------------------------------------------------
def compute_zscore_references(universe_df):
    """Compute Python reference values for the z-score pipeline."""
    N = len(universe_df)
    caps = universe_df["market_cap"].values.astype(float)
    cap_w = caps / caps.sum()

    refs = {}

    # 1) Sub-descriptor z-score stats (13 sub-descriptors)
    for sd in SUB_DESCRIPTORS:
        raw_col = f"{sd}_raw"
        if raw_col not in universe_df.columns:
            continue
        vals = universe_df[raw_col].values.astype(float)
        valid = ~np.isnan(vals) & ~np.isnan(caps) & (caps > 0)
        w = caps[valid] / caps[valid].sum()
        cw_mean = float(np.sum(w * vals[valid]))
        ew_std = float(np.std(vals[valid], ddof=1))  # pandas default
        refs[f"{sd}_cw_mean"] = cw_mean
        refs[f"{sd}_ew_std"] = ew_std

    # 2) Direct factors z-score stats (size, beta, momentum, btop)
    for sf in ["size", "beta", "momentum", "btop"]:
        raw_col = f"{sf}_raw"
        if raw_col not in universe_df.columns:
            continue
        vals = universe_df[raw_col].values.astype(float)
        valid = ~np.isnan(vals) & ~np.isnan(caps) & (caps > 0)
        w = caps[valid] / caps[valid].sum()
        cw_mean = float(np.sum(w * vals[valid]))
        ew_std = float(np.std(vals[valid], ddof=1))
        refs[f"{sf}_cw_mean"] = cw_mean
        refs[f"{sf}_ew_std"] = ew_std

    # 3) Composite raw values — compute from z-scored sub-descriptors
    # First z-score sub-descriptors
    zscored_subs = {}
    for sd in SUB_DESCRIPTORS:
        raw_col = f"{sd}_raw"
        if raw_col not in universe_df.columns:
            continue
        vals = universe_df[raw_col].values.astype(float).copy()
        valid = ~np.isnan(vals)
        cw_mean = refs[f"{sd}_cw_mean"]
        ew_std = refs[f"{sd}_ew_std"]
        z = np.full(N, np.nan)
        z[valid] = (vals[valid] - cw_mean) / ew_std
        zscored_subs[sd] = np.nan_to_num(z, nan=0.0)

    # Composites
    refs["composites"] = {}
    residvol_raw = (0.74 * zscored_subs["dastd"] + 0.16 * zscored_subs["cmra"]
                    + 0.10 * zscored_subs["hsigma"])
    liquidity_raw = (0.35 * zscored_subs["stom"] + 0.35 * zscored_subs["stoq"]
                     + 0.30 * zscored_subs["stoa"])
    earnyild_raw = 0.656 * zscored_subs["cetop"] + 0.344 * zscored_subs["etop"]
    growth_raw = 0.338 * zscored_subs["egro"] + 0.662 * zscored_subs["sgro"]
    leverage_raw = (0.38 * zscored_subs["mlev"] + 0.35 * zscored_subs["dtoa"]
                    + 0.27 * zscored_subs["blev"])

    composite_raws = {
        "residvol": residvol_raw, "liquidity": liquidity_raw,
        "earnyild": earnyild_raw, "growth": growth_raw, "leverage": leverage_raw,
    }

    # 4) Final z-score stats for all 10 factors (pre-orthogonalization)
    # Direct factors use _raw column; composites use computed above
    final_raws = {}
    for sf in STYLE_FACTORS:
        if sf in composite_raws:
            final_raws[sf] = composite_raws[sf]
        elif sf == "nlsize":
            # nlsize_raw = z(size)^3, then orthogonalized vs size
            size_raw = universe_df["size_raw"].values.astype(float)
            valid = ~np.isnan(size_raw) & (caps > 0)
            w = caps[valid] / caps[valid].sum()
            sz_cw = float(np.sum(w * size_raw[valid]))
            sz_ew = float(np.std(size_raw[valid], ddof=1))
            z_size = np.full(N, np.nan)
            z_size[valid] = (size_raw[valid] - sz_cw) / sz_ew
            nlsize_raw = np.where(np.isnan(z_size), np.nan, z_size ** 3)
            # Orthogonalize vs size
            both_valid = ~np.isnan(nlsize_raw) & ~np.isnan(z_size)
            X = np.column_stack([np.ones(both_valid.sum()), z_size[both_valid]])
            y = nlsize_raw[both_valid]
            coef = np.linalg.lstsq(X, y, rcond=None)[0]
            resid = y - X @ coef
            nlsize_orth = np.full(N, np.nan)
            nlsize_orth[both_valid] = resid
            final_raws[sf] = nlsize_orth
            refs["nlsize_orth_intercept"] = float(coef[0])
            refs["nlsize_orth_slope"] = float(coef[1])
        else:
            raw_col = f"{sf}_raw"
            final_raws[sf] = universe_df[raw_col].values.astype(float)

    # Z-score stats for final factors
    for sf in STYLE_FACTORS:
        vals = final_raws[sf]
        valid = ~np.isnan(vals) & (caps > 0)
        w = caps[valid] / caps[valid].sum()
        cw_mean = float(np.sum(w * vals[valid]))
        ew_std = float(np.std(vals[valid], ddof=1))
        refs[f"final_{sf}_cw_mean"] = cw_mean
        refs[f"final_{sf}_ew_std"] = ew_std

    # 5) Orthogonalization coefficients
    # First compute z-scored final factors
    zscored_finals = {}
    for sf in STYLE_FACTORS:
        vals = final_raws[sf]
        valid = ~np.isnan(vals) & (caps > 0)
        cw_mean = refs[f"final_{sf}_cw_mean"]
        ew_std = refs[f"final_{sf}_ew_std"]
        z = np.full(N, np.nan)
        z[valid] = (vals[valid] - cw_mean) / ew_std
        zscored_finals[sf] = z

    # residvol orth vs (beta, size)
    rv = zscored_finals["residvol"]
    bt = zscored_finals["beta"]
    sz = zscored_finals["size"]
    mask = ~np.isnan(rv) & ~np.isnan(bt) & ~np.isnan(sz)
    X = np.column_stack([np.ones(mask.sum()), bt[mask], sz[mask]])
    y = rv[mask]
    coef_rv = np.linalg.lstsq(X, y, rcond=None)[0]
    resid_rv = y - X @ coef_rv
    refs["residvol_orth_intercept"] = float(coef_rv[0])
    refs["residvol_orth_beta_coef"] = float(coef_rv[1])
    refs["residvol_orth_size_coef"] = float(coef_rv[2])
    refs["residvol_orth_resid_mean"] = float(resid_rv.mean())
    refs["residvol_orth_resid_std"] = float(resid_rv.std(ddof=0))

    # liquidity orth vs size
    lq = zscored_finals["liquidity"]
    mask2 = ~np.isnan(lq) & ~np.isnan(sz)
    X2 = np.column_stack([np.ones(mask2.sum()), sz[mask2]])
    y2 = lq[mask2]
    coef_lq = np.linalg.lstsq(X2, y2, rcond=None)[0]
    resid_lq = y2 - X2 @ coef_lq
    refs["liquidity_orth_intercept"] = float(coef_lq[0])
    refs["liquidity_orth_size_coef"] = float(coef_lq[1])
    refs["liquidity_orth_resid_mean"] = float(resid_lq.mean())
    refs["liquidity_orth_resid_std"] = float(resid_lq.std(ddof=0))

    # Python final z-scores (the ones in the exposures CSV)
    refs["python_zscores"] = {}
    for sf in STYLE_FACTORS:
        vals = universe_df[sf].values.astype(float) if sf in universe_df.columns else np.zeros(N)
        refs["python_zscores"][sf] = vals

    return refs


def write_zscoring_sheet(wb, universe_df, zscore_refs):
    """Sheet: ZScoring — full z-score pipeline as Excel formulas."""
    ws = wb.create_sheet("ZScoring")
    N = len(universe_df)
    last = N + 1  # last data row

    # =====================================================================
    # SUMMARY BLOCK at bottom (rows N+3 onwards) — needed by per-stock formulas
    # =====================================================================
    sum_start = N + 3  # first summary row

    # --- Sub-descriptor stats (13 sub-descriptors) ---
    ws.cell(row=sum_start, column=1, value="SUB-DESCRIPTOR STATS").font = FONT_SECTION
    ws.cell(row=sum_start + 1, column=1, value="Descriptor").font = FONT_HEADER
    ws.cell(row=sum_start + 1, column=1).fill = FILL_HEADER
    ws.cell(row=sum_start + 1, column=2, value="CW Mean (formula)").font = FONT_HEADER
    ws.cell(row=sum_start + 1, column=2).fill = FILL_HEADER
    ws.cell(row=sum_start + 1, column=3, value="EW Std (formula)").font = FONT_HEADER
    ws.cell(row=sum_start + 1, column=3).fill = FILL_HEADER
    ws.cell(row=sum_start + 1, column=4, value="Python CW Mean").font = FONT_HEADER
    ws.cell(row=sum_start + 1, column=4).fill = FILL_HEADER
    ws.cell(row=sum_start + 1, column=5, value="Python EW Std").font = FONT_HEADER
    ws.cell(row=sum_start + 1, column=5).fill = FILL_HEADER

    # Sub-descriptor column mapping in Universe sheet: cols 19-35 (S-AI)
    # But we need the per-sub-descriptor Universe column index
    sub_desc_univ_col = {}  # descriptor name -> Universe column letter
    for j, desc in enumerate(RAW_DESCRIPTORS):
        col_idx = 19 + j
        sub_desc_univ_col[desc.replace("_raw", "")] = get_column_letter(col_idx)

    sub_stat_row = {}  # descriptor -> summary row (for reference by per-stock formulas)
    for k, sd in enumerate(SUB_DESCRIPTORS):
        r = sum_start + 2 + k
        sub_stat_row[sd] = r
        ws.cell(row=r, column=1, value=sd)
        ucol = sub_desc_univ_col[sd]
        # CW Mean = SUMPRODUCT(Universe mcap_weight, Universe raw_col)
        formula_mean = f"=SUMPRODUCT(Universe!$F$2:$F${last},Universe!{ucol}$2:{ucol}${last})"
        cell = ws.cell(row=r, column=2, value=formula_mean)
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_6
        # EW Std = STDEV(Universe raw_col) — ddof=1 matches pandas
        formula_std = f"=STDEV(Universe!{ucol}$2:{ucol}${last})"
        cell = ws.cell(row=r, column=3, value=formula_std)
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_6
        # Python refs
        ws.cell(row=r, column=4, value=zscore_refs.get(f"{sd}_cw_mean", "")).number_format = NUM_FMT_6
        ws.cell(row=r, column=5, value=zscore_refs.get(f"{sd}_ew_std", "")).number_format = NUM_FMT_6

    # --- Direct factor stats (size, beta, momentum, btop) ---
    direct_factors = ["size", "beta", "momentum", "btop"]
    direct_start = sum_start + 2 + len(SUB_DESCRIPTORS) + 1
    ws.cell(row=direct_start, column=1, value="DIRECT FACTOR STATS").font = FONT_SECTION
    direct_stat_row = {}
    for k, sf in enumerate(direct_factors):
        r = direct_start + 1 + k
        direct_stat_row[sf] = r
        ws.cell(row=r, column=1, value=sf)
        ucol = sub_desc_univ_col.get(sf)
        if ucol is None:
            continue
        formula_mean = f"=SUMPRODUCT(Universe!$F$2:$F${last},Universe!{ucol}$2:{ucol}${last})"
        cell = ws.cell(row=r, column=2, value=formula_mean)
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_6
        formula_std = f"=STDEV(Universe!{ucol}$2:{ucol}${last})"
        cell = ws.cell(row=r, column=3, value=formula_std)
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_6
        ws.cell(row=r, column=4, value=zscore_refs.get(f"{sf}_cw_mean", "")).number_format = NUM_FMT_6
        ws.cell(row=r, column=5, value=zscore_refs.get(f"{sf}_ew_std", "")).number_format = NUM_FMT_6

    # --- Composite z-score stats (residvol, liquidity, earnyild, growth, leverage raw composites) ---
    comp_start = direct_start + 1 + len(direct_factors) + 1
    ws.cell(row=comp_start, column=1, value="COMPOSITE RAW STATS (after combining)").font = FONT_SECTION
    comp_stat_row = {}
    composite_factors = ["residvol", "liquidity", "earnyild", "growth", "leverage"]
    # Composite raw columns on ZScoring sheet: O-S (cols 15-19) — defined below
    comp_col_idx = {}  # factor -> ZScoring column index for composite raw
    for ci, cf in enumerate(composite_factors):
        comp_col_idx[cf] = 15 + ci  # O=15, P=16, Q=17, R=18, S=19
    # nlsize raw is col T=20
    comp_col_idx["nlsize"] = 20

    for k, cf in enumerate(composite_factors + ["nlsize"]):
        r = comp_start + 1 + k
        comp_stat_row[cf] = r
        ws.cell(row=r, column=1, value=cf)
        ccol = get_column_letter(comp_col_idx[cf])
        formula_mean = f"=SUMPRODUCT(Universe!$F$2:$F${last},{ccol}$2:{ccol}${last})"
        cell = ws.cell(row=r, column=2, value=formula_mean)
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_6
        formula_std = f"=STDEV({ccol}$2:{ccol}${last})"
        cell = ws.cell(row=r, column=3, value=formula_std)
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_6
        ws.cell(row=r, column=4, value=zscore_refs.get(f"final_{cf}_cw_mean", "")).number_format = NUM_FMT_6
        ws.cell(row=r, column=5, value=zscore_refs.get(f"final_{cf}_ew_std", "")).number_format = NUM_FMT_6

    # --- Orthogonalization coefficients ---
    orth_start = comp_start + 1 + len(composite_factors) + 1 + 2
    ws.cell(row=orth_start, column=1, value="ORTHOGONALIZATION COEFFICIENTS").font = FONT_SECTION

    # nlsize orth vs size
    nlsize_orth_row = orth_start + 1
    ws.cell(row=nlsize_orth_row, column=1, value="nlsize orth (intercept, slope vs size)")
    ws.cell(row=nlsize_orth_row, column=2, value=zscore_refs.get("nlsize_orth_intercept", "")).number_format = NUM_FMT_6
    ws.cell(row=nlsize_orth_row, column=3, value=zscore_refs.get("nlsize_orth_slope", "")).number_format = NUM_FMT_6

    # residvol orth vs (beta, size)
    rv_orth_row = orth_start + 2
    ws.cell(row=rv_orth_row, column=1, value="residvol orth (intercept, beta_coef, size_coef)")
    ws.cell(row=rv_orth_row, column=2, value=zscore_refs.get("residvol_orth_intercept", "")).number_format = NUM_FMT_6
    ws.cell(row=rv_orth_row, column=3, value=zscore_refs.get("residvol_orth_beta_coef", "")).number_format = NUM_FMT_6
    ws.cell(row=rv_orth_row, column=4, value=zscore_refs.get("residvol_orth_size_coef", "")).number_format = NUM_FMT_6

    # residvol orth resid stats
    rv_stats_row = orth_start + 3
    ws.cell(row=rv_stats_row, column=1, value="residvol orth resid (mean, std)")
    ws.cell(row=rv_stats_row, column=2, value=zscore_refs.get("residvol_orth_resid_mean", "")).number_format = NUM_FMT_8
    ws.cell(row=rv_stats_row, column=3, value=zscore_refs.get("residvol_orth_resid_std", "")).number_format = NUM_FMT_6

    # liquidity orth vs size
    lq_orth_row = orth_start + 4
    ws.cell(row=lq_orth_row, column=1, value="liquidity orth (intercept, slope vs size)")
    ws.cell(row=lq_orth_row, column=2, value=zscore_refs.get("liquidity_orth_intercept", "")).number_format = NUM_FMT_6
    ws.cell(row=lq_orth_row, column=3, value=zscore_refs.get("liquidity_orth_size_coef", "")).number_format = NUM_FMT_6

    lq_stats_row = orth_start + 5
    ws.cell(row=lq_stats_row, column=1, value="liquidity orth resid (mean, std)")
    ws.cell(row=lq_stats_row, column=2, value=zscore_refs.get("liquidity_orth_resid_mean", "")).number_format = NUM_FMT_8
    ws.cell(row=lq_stats_row, column=3, value=zscore_refs.get("liquidity_orth_resid_std", "")).number_format = NUM_FMT_6

    # =====================================================================
    # PER-STOCK COLUMNS (rows 2 to N+1)
    # =====================================================================
    # Column layout:
    # A: Ticker ref (=Universe!A2)
    # B-N (2-14): Sub-descriptor z-scores (13 cols)
    # O-S (15-19): Composite raws (5 cols: residvol, liquidity, earnyild, growth, leverage)
    # T (20): nlsize_raw (z(size)^3)
    # U-AD (21-30): Final z-scores (10 style factors, pre-orthogonalization)
    # AE-AG (31-33): Orthogonalized (nlsize, residvol, liquidity)
    # AH-AQ (34-43): Python reference z-scores (10 factors)

    # Headers
    headers = ["Ticker"]
    headers += [f"z({sd})" for sd in SUB_DESCRIPTORS]  # B-N
    headers += ["residvol_comp", "liq_comp", "earnyild_comp", "growth_comp", "leverage_comp"]  # O-S
    headers += ["nlsize_raw"]  # T
    headers += [f"z_pre({sf})" for sf in STYLE_FACTORS]  # U-AD
    headers += ["nlsize_orth", "residvol_orth", "liq_orth"]  # AE-AG
    headers += [f"py_{sf}" for sf in STYLE_FACTORS]  # AH-AQ

    for c, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.border = THIN_BORDER

    # Per-stock formulas
    py_zscores = zscore_refs["python_zscores"]
    for i in range(N):
        row = i + 2

        # A: Ticker
        cell = ws.cell(row=row, column=1, value=f"=Universe!A{row}")
        cell.fill = FILL_FORMULA

        # B-N: Sub-descriptor z-scores (13 cols)
        for j, sd in enumerate(SUB_DESCRIPTORS):
            col = 2 + j
            ucol = sub_desc_univ_col[sd]
            sr = sub_stat_row[sd]
            # =(Universe!raw - CW_mean) / EW_std, with NaN handling
            formula = (f'=IF(Universe!{ucol}{row}="","",('
                       f"Universe!{ucol}{row}-$B${sr})/$C${sr})")
            cell = ws.cell(row=row, column=col, value=formula)
            cell.fill = FILL_FORMULA
            cell.number_format = NUM_FMT_4

        # O-S: Composite raws
        # residvol = 0.74*z(dastd) + 0.16*z(cmra) + 0.10*z(hsigma)
        # Cols: dastd=B, cmra=C, hsigma=D (offset 2,3,4)
        dastd_c = get_column_letter(2 + SUB_DESCRIPTORS.index("dastd"))
        cmra_c = get_column_letter(2 + SUB_DESCRIPTORS.index("cmra"))
        hsigma_c = get_column_letter(2 + SUB_DESCRIPTORS.index("hsigma"))
        formula = f'=0.74*IF({dastd_c}{row}="",0,{dastd_c}{row})+0.16*IF({cmra_c}{row}="",0,{cmra_c}{row})+0.1*IF({hsigma_c}{row}="",0,{hsigma_c}{row})'
        ws.cell(row=row, column=15, value=formula).fill = FILL_FORMULA
        ws.cell(row=row, column=15).number_format = NUM_FMT_4

        # liquidity = 0.35*z(stom) + 0.35*z(stoq) + 0.30*z(stoa)
        stom_c = get_column_letter(2 + SUB_DESCRIPTORS.index("stom"))
        stoq_c = get_column_letter(2 + SUB_DESCRIPTORS.index("stoq"))
        stoa_c = get_column_letter(2 + SUB_DESCRIPTORS.index("stoa"))
        formula = f'=0.35*IF({stom_c}{row}="",0,{stom_c}{row})+0.35*IF({stoq_c}{row}="",0,{stoq_c}{row})+0.3*IF({stoa_c}{row}="",0,{stoa_c}{row})'
        ws.cell(row=row, column=16, value=formula).fill = FILL_FORMULA
        ws.cell(row=row, column=16).number_format = NUM_FMT_4

        # earnyild = 0.656*z(cetop) + 0.344*z(etop)
        cetop_c = get_column_letter(2 + SUB_DESCRIPTORS.index("cetop"))
        etop_c = get_column_letter(2 + SUB_DESCRIPTORS.index("etop"))
        formula = f'=0.656*IF({cetop_c}{row}="",0,{cetop_c}{row})+0.344*IF({etop_c}{row}="",0,{etop_c}{row})'
        ws.cell(row=row, column=17, value=formula).fill = FILL_FORMULA
        ws.cell(row=row, column=17).number_format = NUM_FMT_4

        # growth = 0.338*z(egro) + 0.662*z(sgro)
        egro_c = get_column_letter(2 + SUB_DESCRIPTORS.index("egro"))
        sgro_c = get_column_letter(2 + SUB_DESCRIPTORS.index("sgro"))
        formula = f'=0.338*IF({egro_c}{row}="",0,{egro_c}{row})+0.662*IF({sgro_c}{row}="",0,{sgro_c}{row})'
        ws.cell(row=row, column=18, value=formula).fill = FILL_FORMULA
        ws.cell(row=row, column=18).number_format = NUM_FMT_4

        # leverage = 0.38*z(mlev) + 0.35*z(dtoa) + 0.27*z(blev)
        mlev_c = get_column_letter(2 + SUB_DESCRIPTORS.index("mlev"))
        dtoa_c = get_column_letter(2 + SUB_DESCRIPTORS.index("dtoa"))
        blev_c = get_column_letter(2 + SUB_DESCRIPTORS.index("blev"))
        formula = f'=0.38*IF({mlev_c}{row}="",0,{mlev_c}{row})+0.35*IF({dtoa_c}{row}="",0,{dtoa_c}{row})+0.27*IF({blev_c}{row}="",0,{blev_c}{row})'
        ws.cell(row=row, column=19, value=formula).fill = FILL_FORMULA
        ws.cell(row=row, column=19).number_format = NUM_FMT_4

        # T (col 20): nlsize_raw = z(size)^3
        # z(size) is the direct z-score — need to compute from Universe size_raw
        size_ucol = sub_desc_univ_col["size"]
        sz_sr = direct_stat_row["size"]
        formula = (f'=IF(Universe!{size_ucol}{row}="","",('
                   f"(Universe!{size_ucol}{row}-$B${sz_sr})/$C${sz_sr})^3)")
        ws.cell(row=row, column=20, value=formula).fill = FILL_FORMULA
        ws.cell(row=row, column=20).number_format = NUM_FMT_4

        # U-AD (cols 21-30): Final z-scores for 10 style factors
        for j, sf in enumerate(STYLE_FACTORS):
            col = 21 + j
            if sf in composite_factors:
                # Use composite raw column (O-S)
                src_col = get_column_letter(comp_col_idx[sf])
                sr = comp_stat_row[sf]
            elif sf == "nlsize":
                # Use nlsize_raw column T
                src_col = "T"
                sr = comp_stat_row["nlsize"]
            else:
                # Direct factor: use Universe raw column
                src_col = f"Universe!{sub_desc_univ_col[sf]}"
                sr = direct_stat_row[sf]
                formula = (f'=IF({src_col}{row}="","",('
                           f"{src_col}{row}-$B${sr})/$C${sr})")
                cell = ws.cell(row=row, column=col, value=formula)
                cell.fill = FILL_FORMULA
                cell.number_format = NUM_FMT_4
                continue
            # For composites/nlsize — source is on this sheet
            formula = (f'=IF({src_col}{row}="","",('
                       f"{src_col}{row}-$B${sr})/$C${sr})")
            cell = ws.cell(row=row, column=col, value=formula)
            cell.fill = FILL_FORMULA
            cell.number_format = NUM_FMT_4

        # AE (col 31): nlsize orthogonalized
        # nlsize_orth = nlsize_pre - (intercept + slope * size_pre), then re-standardized
        # Using hardcoded Python coefficients since LINEST needs array formulas
        nlsize_pre_col = get_column_letter(21 + STYLE_FACTORS.index("nlsize"))
        size_pre_col = get_column_letter(21 + STYLE_FACTORS.index("size"))
        nl_int = zscore_refs.get("nlsize_orth_intercept", 0)
        nl_slope = zscore_refs.get("nlsize_orth_slope", 0)
        formula = (f'=IF({nlsize_pre_col}{row}="","",'
                   f'{nlsize_pre_col}{row}-({nl_int}+{nl_slope}*{size_pre_col}{row}))')
        ws.cell(row=row, column=31, value=formula).fill = FILL_FORMULA
        ws.cell(row=row, column=31).number_format = NUM_FMT_4

        # AF (col 32): residvol orthogonalized
        rv_pre_col = get_column_letter(21 + STYLE_FACTORS.index("residvol"))
        bt_pre_col = get_column_letter(21 + STYLE_FACTORS.index("beta"))
        rv_int = zscore_refs.get("residvol_orth_intercept", 0)
        rv_bc = zscore_refs.get("residvol_orth_beta_coef", 0)
        rv_sc = zscore_refs.get("residvol_orth_size_coef", 0)
        rv_mean = zscore_refs.get("residvol_orth_resid_mean", 0)
        rv_std = zscore_refs.get("residvol_orth_resid_std", 1)
        formula = (f'=IF({rv_pre_col}{row}="","",('
                   f'{rv_pre_col}{row}-({rv_int}+{rv_bc}*{bt_pre_col}{row}+{rv_sc}*{size_pre_col}{row})'
                   f'-{rv_mean})/{rv_std})')
        ws.cell(row=row, column=32, value=formula).fill = FILL_FORMULA
        ws.cell(row=row, column=32).number_format = NUM_FMT_4

        # AG (col 33): liquidity orthogonalized
        lq_pre_col = get_column_letter(21 + STYLE_FACTORS.index("liquidity"))
        lq_int = zscore_refs.get("liquidity_orth_intercept", 0)
        lq_sc = zscore_refs.get("liquidity_orth_size_coef", 0)
        lq_mean = zscore_refs.get("liquidity_orth_resid_mean", 0)
        lq_std = zscore_refs.get("liquidity_orth_resid_std", 1)
        formula = (f'=IF({lq_pre_col}{row}="","",('
                   f'{lq_pre_col}{row}-({lq_int}+{lq_sc}*{size_pre_col}{row})'
                   f'-{lq_mean})/{lq_std})')
        ws.cell(row=row, column=33, value=formula).fill = FILL_FORMULA
        ws.cell(row=row, column=33).number_format = NUM_FMT_4

        # AH-AQ (cols 34-43): Python reference z-scores
        for j, sf in enumerate(STYLE_FACTORS):
            val = float(py_zscores[sf][i]) if not np.isnan(py_zscores[sf][i]) else ""
            cell = ws.cell(row=row, column=34 + j, value=val)
            cell.number_format = NUM_FMT_4

    # Column widths
    ws.column_dimensions["A"].width = 8
    for c in range(2, 44):
        ws.column_dimensions[get_column_letter(c)].width = 12


# ---------------------------------------------------------------------------
# New Sheet: WLSRegression — full constrained WLS as formulas
# ---------------------------------------------------------------------------
def compute_wls_references(universe_df, factor_ret_df):
    """Compute Python WLS reference values for the representative date."""
    N = len(universe_df)
    caps = universe_df["market_cap"].values.astype(float)
    rets = universe_df["return"].values.astype(float)

    # Get Python z-scores (post-orthogonalization) for the 10 style factors
    style_vals = np.zeros((N, 10))
    for j, sf in enumerate(STYLE_FACTORS):
        style_vals[:, j] = universe_df[sf].fillna(0).values.astype(float)

    # Re-normalization (what CrossSection.__init__ does: style_factor_norm)
    cap_w = caps / caps.sum()
    cw_means = np.average(style_vals, weights=cap_w, axis=0)
    ew_stds = np.std(style_vals, axis=0)  # ddof=0 = numpy default
    ew_stds[ew_stds == 0] = 1
    renorm_styles = (style_vals - cw_means) / ew_stds

    # Build industry dummies
    ind_dummies = np.zeros((N, 11))
    for j, ind in enumerate(INDUSTRY_FACTORS):
        ind_dummies[:, j] = (universe_df["sector"] == ind).astype(float).values

    # Build factor matrix X: [Country(1s) | Industries | Renorm_Styles]
    country = np.ones((N, 1))
    X = np.hstack([country, ind_dummies, renorm_styles])

    # WLS weights
    sqrt_cap = np.sqrt(caps)
    W = sqrt_cap / sqrt_cap.sum()
    W_diag = np.diag(W)

    # Industry capitals
    ind_caps = np.array([np.sum(ind_dummies[:, i] * caps) for i in range(11)])

    # R transformation matrix (22×21)
    P = 11  # number of industries
    Q = 10  # number of style factors
    R = np.eye(1 + P + Q)
    R[P, 1:(1 + P)] = -ind_caps / ind_caps[-1]
    R = np.delete(R, P, axis=1)  # delete column 11 -> 22×21

    # X_tran = X @ R
    X_tran = X @ R

    # X'WX
    XWX = X.T @ W_diag @ X

    # X'Wy
    XWy = X.T @ W_diag @ rets

    # R' X'WX
    Rt_XWX = R.T @ XWX

    # R'X'WXR
    Rt_XWX_R = Rt_XWX @ R

    # Inverse
    inv_mat = np.linalg.inv(Rt_XWX_R)

    # R'X'Wy
    Rt_XWy = R.T @ XWy

    # Beta_tran
    beta_tran = inv_mat @ Rt_XWy

    # Factor returns = R @ beta_tran
    factor_returns = R @ beta_tran

    # R²
    predicted = X @ factor_returns
    residuals = rets - predicted
    wssr = np.sum(W * residuals ** 2)
    wssr_total = np.sum(W * rets ** 2)
    r2 = 1 - wssr / wssr_total if wssr_total > 0 else 0

    # Get Python model factor returns for this date for comparison
    rep_date_str = REP_DATE
    py_factor_ret = {}
    if rep_date_str in factor_ret_df.index:
        for f in ALL_FACTORS:
            py_factor_ret[f] = float(factor_ret_df.loc[rep_date_str, f])

    return {
        "cw_means": cw_means,
        "ew_stds": ew_stds,
        "renorm_styles": renorm_styles,
        "ind_caps": ind_caps,
        "R_matrix": R,
        "XWX": XWX,
        "XWy": XWy,
        "inv_mat": inv_mat,
        "beta_tran": beta_tran,
        "factor_returns": factor_returns,
        "py_factor_ret": py_factor_ret,
        "r2": r2,
        "N": N,
    }


def write_wls_regression_sheet(wb, universe_df, wls_refs):
    """Sheet: WLSRegression — full constrained WLS as Excel formulas."""
    ws = wb.create_sheet("WLSRegression")
    N = wls_refs["N"]
    last = N + 1  # last data row on Universe sheet
    n_factors = 22
    n_tran = 21  # after removing one column for constraint

    # =====================================================================
    # HELPER DATA AREA (rows 260+): 22 factor columns + wls_weight + return
    # =====================================================================
    HELP_START = 260
    help_header_row = HELP_START - 1

    # Header row for helper area
    ws.cell(row=help_header_row, column=1, value="HELPER: Factor matrix & weights").font = FONT_SECTION
    help_headers = ["wls_wt", "Country"] + INDUSTRY_FACTORS + STYLE_FACTORS + ["return"]
    for c, h in enumerate(help_headers, 1):
        cell = ws.cell(row=HELP_START, column=c, value=h)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER

    # Column mapping for helper area
    # Col 1: wls_weight, Col 2: Country, Cols 3-13: industries, Cols 14-23: styles, Col 24: return
    help_wls_col = 1
    help_country_col = 2
    help_ind_start = 3   # cols 3-13
    help_style_start = 14  # cols 14-23
    help_ret_col = 24

    # Re-normalization stats (Section 1, rows 2-5)
    ws.cell(row=1, column=1, value="RE-NORMALIZATION STATS (for WLS)").font = FONT_SECTION
    ws.cell(row=2, column=1, value="Style Factor").font = FONT_HEADER
    ws.cell(row=2, column=1).fill = FILL_HEADER
    ws.cell(row=2, column=2, value="CW Mean").font = FONT_HEADER
    ws.cell(row=2, column=2).fill = FILL_HEADER
    ws.cell(row=2, column=3, value="EW Std (pop)").font = FONT_HEADER
    ws.cell(row=2, column=3).fill = FILL_HEADER
    ws.cell(row=2, column=4, value="Python CW Mean").font = FONT_HEADER
    ws.cell(row=2, column=4).fill = FILL_HEADER
    ws.cell(row=2, column=5, value="Python EW Std").font = FONT_HEADER
    ws.cell(row=2, column=5).fill = FILL_HEADER

    renorm_stat_rows = {}  # style factor -> row number
    for j, sf in enumerate(STYLE_FACTORS):
        r = 3 + j
        renorm_stat_rows[sf] = r
        ws.cell(row=r, column=1, value=sf)
        # ZScoring Python z-scores are in cols AH-AQ (34-43), rows 2 to N+1
        zs_col = get_column_letter(34 + j)
        # CW Mean = SUMPRODUCT(Universe!F, ZScoring!py_col)
        formula_mean = f"=SUMPRODUCT(Universe!$F$2:$F${last},ZScoring!{zs_col}$2:{zs_col}${last})"
        cell = ws.cell(row=r, column=2, value=formula_mean)
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_8
        # EW Std (population, ddof=0) = STDEVP
        formula_std = f"=STDEVP(ZScoring!{zs_col}$2:{zs_col}${last})"
        cell = ws.cell(row=r, column=3, value=formula_std)
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_8
        # Python refs
        ws.cell(row=r, column=4, value=float(wls_refs["cw_means"][j])).number_format = NUM_FMT_8
        ws.cell(row=r, column=5, value=float(wls_refs["ew_stds"][j])).number_format = NUM_FMT_8

    # Write helper data rows
    for i in range(N):
        row = HELP_START + 1 + i
        urow = i + 2  # Universe row

        # Col 1: wls_weight
        cell = ws.cell(row=row, column=help_wls_col, value=f"=Universe!G{urow}")
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_8

        # Col 2: Country = 1
        ws.cell(row=row, column=help_country_col, value=1).fill = FILL_INPUT

        # Cols 3-13: industry dummies from Universe
        for j in range(11):
            ucol = get_column_letter(8 + j)  # Universe H-R
            cell = ws.cell(row=row, column=help_ind_start + j,
                           value=f"=Universe!{ucol}{urow}")
            cell.fill = FILL_FORMULA

        # Cols 14-23: re-normalized style z-scores
        for j, sf in enumerate(STYLE_FACTORS):
            zs_col = get_column_letter(34 + j)  # ZScoring AH-AQ
            sr = renorm_stat_rows[sf]
            formula = f'=IF(ZScoring!{zs_col}{urow}="",0,(ZScoring!{zs_col}{urow}-$B${sr})/$C${sr})'
            cell = ws.cell(row=row, column=help_style_start + j, value=formula)
            cell.fill = FILL_FORMULA
            cell.number_format = NUM_FMT_6

        # Col 24: return
        cell = ws.cell(row=row, column=help_ret_col, value=f"=Universe!C{urow}")
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_6

    help_first = HELP_START + 1
    help_last = HELP_START + N

    # Helper: get column letter for a factor in the helper area
    def _factor_col(fi):
        """Return helper column index (1-based) for factor index fi (0=Country, 1-11=industries, 12-21=styles)."""
        if fi == 0:
            return help_country_col
        elif fi <= 11:
            return help_ind_start + (fi - 1)
        else:
            return help_style_start + (fi - 12)

    def _factor_col_letter(fi):
        return get_column_letter(_factor_col(fi))

    wls_col_letter = get_column_letter(help_wls_col)
    ret_col_letter = get_column_letter(help_ret_col)

    # =====================================================================
    # SECTION 2: X'WX (22×22) — rows 15-39
    # =====================================================================
    xwx_start = 15
    ws.cell(row=xwx_start - 1, column=1, value="X'WX MATRIX (22×22)").font = FONT_SECTION
    # Column headers (B-W)
    for j, f in enumerate(ALL_FACTORS):
        cell = ws.cell(row=xwx_start, column=j + 2, value=f)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
    xwx_rows = {}  # factor index -> Excel row
    for i, fi_name in enumerate(ALL_FACTORS):
        r = xwx_start + 1 + i
        xwx_rows[i] = r
        ws.cell(row=r, column=1, value=fi_name).font = FONT_HEADER
        ws.cell(row=r, column=1).fill = FILL_HEADER
        for j in range(n_factors):
            fc_i = _factor_col_letter(i)
            fc_j = _factor_col_letter(j)
            formula = (f"=SUMPRODUCT(${wls_col_letter}${help_first}:${wls_col_letter}${help_last},"
                       f"${fc_i}${help_first}:${fc_i}${help_last},"
                       f"${fc_j}${help_first}:${fc_j}${help_last})")
            cell = ws.cell(row=r, column=j + 2, value=formula)
            cell.fill = FILL_FORMULA
            cell.number_format = "0.000000E+00"

    # =====================================================================
    # SECTION 3: X'Wy (22×1) — rows 41-64
    # =====================================================================
    xwy_start = xwx_start + 1 + n_factors + 2
    ws.cell(row=xwy_start - 1, column=1, value="X'Wy VECTOR (22×1)").font = FONT_SECTION
    ws.cell(row=xwy_start, column=1, value="Factor").font = FONT_HEADER
    ws.cell(row=xwy_start, column=1).fill = FILL_HEADER
    ws.cell(row=xwy_start, column=2, value="X'Wy").font = FONT_HEADER
    ws.cell(row=xwy_start, column=2).fill = FILL_HEADER

    xwy_rows = {}
    for i, fi_name in enumerate(ALL_FACTORS):
        r = xwy_start + 1 + i
        xwy_rows[i] = r
        ws.cell(row=r, column=1, value=fi_name)
        fc_i = _factor_col_letter(i)
        formula = (f"=SUMPRODUCT(${wls_col_letter}${help_first}:${wls_col_letter}${help_last},"
                   f"${fc_i}${help_first}:${fc_i}${help_last},"
                   f"${ret_col_letter}${help_first}:${ret_col_letter}${help_last})")
        cell = ws.cell(row=r, column=2, value=formula)
        cell.fill = FILL_FORMULA
        cell.number_format = "0.000000E+00"

    # =====================================================================
    # SECTION 4: Industry capitals (11×1)
    # =====================================================================
    ic_start = xwy_start + 1 + n_factors + 2
    ws.cell(row=ic_start - 1, column=1, value="INDUSTRY CAPITALS").font = FONT_SECTION
    ws.cell(row=ic_start, column=1, value="Industry").font = FONT_HEADER
    ws.cell(row=ic_start, column=1).fill = FILL_HEADER
    ws.cell(row=ic_start, column=2, value="Market Cap Sum").font = FONT_HEADER
    ws.cell(row=ic_start, column=2).fill = FILL_HEADER

    ic_rows = {}
    for i, ind in enumerate(INDUSTRY_FACTORS):
        r = ic_start + 1 + i
        ic_rows[i] = r
        ws.cell(row=r, column=1, value=ind)
        ucol = get_column_letter(8 + i)  # Universe industry dummy cols
        formula = f"=SUMPRODUCT(Universe!{ucol}$2:{ucol}${last},Universe!$D$2:$D${last})"
        cell = ws.cell(row=r, column=2, value=formula)
        cell.fill = FILL_FORMULA
        cell.number_format = "#,##0"

    # =====================================================================
    # SECTION 5: R transformation matrix (22×21)
    # =====================================================================
    r_start = ic_start + 1 + 11 + 2
    ws.cell(row=r_start - 1, column=1, value="R TRANSFORMATION MATRIX (22×21)").font = FONT_SECTION
    # R = I(22), set R[11, 1:12] = -ind_cap/ind_cap_last, delete col 11
    # Row labels
    for i, f in enumerate(ALL_FACTORS):
        ws.cell(row=r_start + 1 + i, column=1, value=f).font = FONT_HEADER
        ws.cell(row=r_start + 1 + i, column=1).fill = FILL_HEADER

    # Column headers: 21 columns (skip the deleted column 11)
    # After deletion, columns are: 0(Country), 1-10(first 10 industries), 11-20(styles)
    # Original col indices: 0,1,2,...,10,12,13,...,21
    tran_col_labels = [ALL_FACTORS[0]]  # Country
    tran_col_labels += INDUSTRY_FACTORS[:10]  # first 10 industries (skip last = Utilities)
    tran_col_labels += STYLE_FACTORS
    for j, lbl in enumerate(tran_col_labels):
        cell = ws.cell(row=r_start, column=j + 2, value=lbl)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER

    r_mat_rows = {}  # row index (0-21) -> Excel row
    last_ind_cap_row = ic_rows[10]  # Utilities = last industry
    for i in range(n_factors):
        r = r_start + 1 + i
        r_mat_rows[i] = r
        for j in range(n_tran):
            # Map tran col j to original col index
            orig_j = j if j < 11 else j + 1
            # R[i, orig_j] logic:
            # - Identity part: 1 if i == orig_j
            # - Constraint row (i=11, last industry): R[11, 1:12] = -cap[j]/cap[last]
            if i == 11 and 1 <= orig_j <= 11:
                # -ind_cap[orig_j-1] / ind_cap[10]
                cap_row = ic_rows[orig_j - 1]
                formula = f"=-B{cap_row}/B{last_ind_cap_row}"
                cell = ws.cell(row=r, column=j + 2, value=formula)
                cell.fill = FILL_FORMULA
                cell.number_format = NUM_FMT_6
            elif i == orig_j:
                ws.cell(row=r, column=j + 2, value=1).fill = FILL_INPUT
            else:
                ws.cell(row=r, column=j + 2, value=0).fill = FILL_INPUT

    # =====================================================================
    # SECTION 6: R'X'WX (21×22)
    # =====================================================================
    rx_start = r_start + 1 + n_factors + 2
    ws.cell(row=rx_start - 1, column=1, value="R'X'WX (21×22)").font = FONT_SECTION
    # R' is 21×22, X'WX is 22×22 → result is 21×22
    for j, f in enumerate(ALL_FACTORS):
        cell = ws.cell(row=rx_start, column=j + 2, value=f)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER

    rx_rows = {}
    for i in range(n_tran):
        r = rx_start + 1 + i
        rx_rows[i] = r
        ws.cell(row=r, column=1, value=tran_col_labels[i]).font = FONT_HEADER
        ws.cell(row=r, column=1).fill = FILL_HEADER
        for j in range(n_factors):
            # R'[i, :] dot XWX[:, j]
            # R'[i, k] = R[k, i] for k=0..21
            # R is in rows r_mat_rows[0..21], col (i+2)
            r_col_letter = get_column_letter(i + 2)
            # XWX[:, j] is in rows xwx_rows[0..21], col (j+2)
            xwx_col_letter = get_column_letter(j + 2)
            formula = (f"=SUMPRODUCT("
                       f"${r_col_letter}${r_mat_rows[0]}:${r_col_letter}${r_mat_rows[21]},"
                       f"${xwx_col_letter}${xwx_rows[0]}:${xwx_col_letter}${xwx_rows[21]})")
            cell = ws.cell(row=r, column=j + 2, value=formula)
            cell.fill = FILL_FORMULA
            cell.number_format = "0.000000E+00"

    # =====================================================================
    # SECTION 7: R'X'WXR (21×21)
    # =====================================================================
    rxr_start = rx_start + 1 + n_tran + 2
    ws.cell(row=rxr_start - 1, column=1, value="R'X'WXR (21×21)").font = FONT_SECTION
    for j, lbl in enumerate(tran_col_labels):
        cell = ws.cell(row=rxr_start, column=j + 2, value=lbl)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER

    rxr_rows = {}
    for i in range(n_tran):
        r = rxr_start + 1 + i
        rxr_rows[i] = r
        ws.cell(row=r, column=1, value=tran_col_labels[i]).font = FONT_HEADER
        ws.cell(row=r, column=1).fill = FILL_HEADER
        for j in range(n_tran):
            # R'X'WX[i, :] dot R[:, j]
            # R'X'WX row i spans cols B-W of rx_rows[i]
            # R col j spans rows r_mat_rows[0..21] at col (j+2)
            r_col_letter = get_column_letter(j + 2)
            # R'X'WX row i: cols B(2) to W(23)
            formula = (f"=SUMPRODUCT("
                       f"$B${rx_rows[i]}:$W${rx_rows[i]},"
                       f"TRANSPOSE(${r_col_letter}${r_mat_rows[0]}:${r_col_letter}${r_mat_rows[21]}))")
            cell = ws.cell(row=r, column=j + 2, value=formula)
            cell.fill = FILL_FORMULA
            cell.number_format = "0.000000E+00"

    # =====================================================================
    # SECTION 8: (R'X'WXR)^-1 (21×21) — HARDCODED from Python
    # =====================================================================
    inv_start = rxr_start + 1 + n_tran + 2
    ws.cell(row=inv_start - 1, column=1, value="(R'X'WXR)^-1  [hardcoded — verify with MINVERSE]").font = FONT_SECTION
    for j, lbl in enumerate(tran_col_labels):
        cell = ws.cell(row=inv_start, column=j + 2, value=lbl)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER

    inv_mat = wls_refs["inv_mat"]
    inv_rows = {}
    for i in range(n_tran):
        r = inv_start + 1 + i
        inv_rows[i] = r
        ws.cell(row=r, column=1, value=tran_col_labels[i]).font = FONT_HEADER
        ws.cell(row=r, column=1).fill = FILL_HEADER
        for j in range(n_tran):
            cell = ws.cell(row=r, column=j + 2, value=float(inv_mat[i, j]))
            cell.fill = FILL_INPUT
            cell.number_format = "0.000000E+00"

    # =====================================================================
    # SECTION 9: R'X'Wy (21×1)
    # =====================================================================
    rwy_start = inv_start + 1 + n_tran + 2
    ws.cell(row=rwy_start - 1, column=1, value="R'X'Wy (21×1)").font = FONT_SECTION
    ws.cell(row=rwy_start, column=1, value="Factor").font = FONT_HEADER
    ws.cell(row=rwy_start, column=1).fill = FILL_HEADER
    ws.cell(row=rwy_start, column=2, value="R'X'Wy").font = FONT_HEADER
    ws.cell(row=rwy_start, column=2).fill = FILL_HEADER

    rwy_rows = {}
    for i in range(n_tran):
        r = rwy_start + 1 + i
        rwy_rows[i] = r
        ws.cell(row=r, column=1, value=tran_col_labels[i])
        # R'[i, :] dot X'Wy
        r_col_letter = get_column_letter(i + 2)
        formula = (f"=SUMPRODUCT("
                   f"${r_col_letter}${r_mat_rows[0]}:${r_col_letter}${r_mat_rows[21]},"
                   f"$B${xwy_rows[0]}:$B${xwy_rows[21]})")
        cell = ws.cell(row=r, column=2, value=formula)
        cell.fill = FILL_FORMULA
        cell.number_format = "0.000000E+00"

    # =====================================================================
    # SECTION 10: β_tran = inv × R'X'Wy (21×1)
    # =====================================================================
    bt_start = rwy_start + 1 + n_tran + 2
    ws.cell(row=bt_start - 1, column=1, value="β_tran = (R'X'WXR)^-1 × R'X'Wy (21×1)").font = FONT_SECTION
    ws.cell(row=bt_start, column=1, value="Factor").font = FONT_HEADER
    ws.cell(row=bt_start, column=1).fill = FILL_HEADER
    ws.cell(row=bt_start, column=2, value="β_tran").font = FONT_HEADER
    ws.cell(row=bt_start, column=2).fill = FILL_HEADER

    bt_rows = {}
    for i in range(n_tran):
        r = bt_start + 1 + i
        bt_rows[i] = r
        ws.cell(row=r, column=1, value=tran_col_labels[i])
        # inv[i, :] dot R'X'Wy
        formula = (f"=SUMPRODUCT("
                   f"$B${inv_rows[i]}:$V${inv_rows[i]},"
                   f"TRANSPOSE($B${rwy_rows[0]}:$B${rwy_rows[20]}))")
        cell = ws.cell(row=r, column=2, value=formula)
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_8

    # =====================================================================
    # SECTION 11: Factor Returns = R × β_tran (22×1)
    # =====================================================================
    fr_start = bt_start + 1 + n_tran + 2
    ws.cell(row=fr_start - 1, column=1, value="FACTOR RETURNS = R × β_tran (22×1)").font = FONT_SECTION
    ws.cell(row=fr_start, column=1, value="Factor").font = FONT_HEADER
    ws.cell(row=fr_start, column=1).fill = FILL_HEADER
    ws.cell(row=fr_start, column=2, value="WLS Result").font = FONT_HEADER
    ws.cell(row=fr_start, column=2).fill = FILL_HEADER
    ws.cell(row=fr_start, column=3, value="Python Model").font = FONT_HEADER
    ws.cell(row=fr_start, column=3).fill = FILL_HEADER
    ws.cell(row=fr_start, column=4, value="Difference").font = FONT_HEADER
    ws.cell(row=fr_start, column=4).fill = FILL_HEADER

    fr_rows = {}
    for i, f in enumerate(ALL_FACTORS):
        r = fr_start + 1 + i
        fr_rows[i] = r
        ws.cell(row=r, column=1, value=f)
        # R[i, :] dot β_tran
        # R row i: cols B-V at r_mat_rows[i]
        formula = (f"=SUMPRODUCT("
                   f"$B${r_mat_rows[i]}:$V${r_mat_rows[i]},"
                   f"TRANSPOSE($B${bt_rows[0]}:$B${bt_rows[20]}))")
        cell = ws.cell(row=r, column=2, value=formula)
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_8

        # Python model value
        py_val = wls_refs["py_factor_ret"].get(f, "")
        ws.cell(row=r, column=3, value=py_val).number_format = NUM_FMT_8

        # Difference
        formula_diff = f"=B{r}-C{r}"
        cell = ws.cell(row=r, column=4, value=formula_diff)
        cell.fill = FILL_FORMULA
        cell.number_format = "0.00E+00"

    # =====================================================================
    # SECTION 12: R²
    # =====================================================================
    r2_start = fr_start + 1 + n_factors + 2
    ws.cell(row=r2_start - 1, column=1, value="R² CALCULATION").font = FONT_SECTION
    ws.cell(row=r2_start, column=1, value="R² (Python)")
    ws.cell(row=r2_start, column=2, value=wls_refs["r2"]).number_format = NUM_FMT_6

    # Column widths
    ws.column_dimensions["A"].width = 28
    for c in range(2, 25):
        ws.column_dimensions[get_column_letter(c)].width = 16


# ---------------------------------------------------------------------------
# New Sheet: SimpleCov — sample covariance from factor returns
# ---------------------------------------------------------------------------
def write_simple_cov_sheet(wb, factor_ret_df, factor_cov):
    """Sheet: SimpleCov — sample covariance from FactorReturns with formulas."""
    ws = wb.create_sheet("SimpleCov")

    # Get dates in the FactorReturns sheet
    dates = sorted([d for d in factor_ret_df.index if DATE_START <= d <= DATE_END])
    T = len(dates)
    n_factors = len(ALL_FACTORS)

    # =====================================================================
    # SECTION 1: Factor return means (row 3)
    # =====================================================================
    ws.cell(row=1, column=1, value="SAMPLE COVARIANCE FROM FACTOR RETURNS").font = FONT_SECTION
    ws.cell(row=2, column=1, value=f"Using {T} days from FactorReturns ({DATE_START} to {DATE_END})").font = Font(italic=True)

    ws.cell(row=3, column=1, value="Factor Means").font = FONT_HEADER
    ws.cell(row=3, column=1).fill = FILL_HEADER
    mean_row = 3
    for j, f in enumerate(ALL_FACTORS):
        col = j + 2
        cell = ws.cell(row=mean_row, column=col, value=f)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER

    mean_data_row = 4
    for j in range(n_factors):
        fr_col = get_column_letter(j + 2)  # FactorReturns col
        formula = f"=AVERAGE(FactorReturns!{fr_col}$2:{fr_col}${T+1})"
        cell = ws.cell(row=mean_data_row, column=j + 2, value=formula)
        cell.fill = FILL_FORMULA
        cell.number_format = NUM_FMT_8

    # =====================================================================
    # SECTION 2: Demeaned returns (rows 6 to 6+T-1)
    # =====================================================================
    dm_start = 6
    ws.cell(row=dm_start - 1, column=1, value="DEMEANED FACTOR RETURNS").font = FONT_SECTION
    # Headers
    ws.cell(row=dm_start, column=1, value="Date").font = FONT_HEADER
    ws.cell(row=dm_start, column=1).fill = FILL_HEADER
    for j, f in enumerate(ALL_FACTORS):
        cell = ws.cell(row=dm_start, column=j + 2, value=f)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER

    for i in range(T):
        r = dm_start + 1 + i
        # Date from FactorReturns
        ws.cell(row=r, column=1, value=f"=FactorReturns!A{i+2}").fill = FILL_FORMULA
        for j in range(n_factors):
            fr_col = get_column_letter(j + 2)
            mean_cell = f"${fr_col}${mean_data_row}"
            formula = f"=FactorReturns!{fr_col}{i+2}-{mean_cell}"
            cell = ws.cell(row=r, column=j + 2, value=formula)
            cell.fill = FILL_FORMULA
            cell.number_format = NUM_FMT_8

    dm_first = dm_start + 1
    dm_last = dm_start + T

    # =====================================================================
    # SECTION 3: Simple covariance (22×22)
    # =====================================================================
    sc_start = dm_last + 2
    ws.cell(row=sc_start, column=1, value="SIMPLE SAMPLE COVARIANCE (22×22)").font = FONT_SECTION
    sc_header = sc_start + 1
    for j, f in enumerate(ALL_FACTORS):
        cell = ws.cell(row=sc_header, column=j + 2, value=f)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER

    sc_data_start = sc_header + 1
    for i, fi in enumerate(ALL_FACTORS):
        r = sc_data_start + i
        ws.cell(row=r, column=1, value=fi).font = FONT_HEADER
        ws.cell(row=r, column=1).fill = FILL_HEADER
        for j in range(n_factors):
            ci = get_column_letter(i + 2)
            cj = get_column_letter(j + 2)
            formula = f"=SUMPRODUCT({ci}${dm_first}:{ci}${dm_last},{cj}${dm_first}:{cj}${dm_last})/({T}-1)"
            cell = ws.cell(row=r, column=j + 2, value=formula)
            cell.fill = FILL_FORMULA
            cell.number_format = "0.000000E+00"

    # =====================================================================
    # SECTION 4: Adjusted covariance (reference to Covariance sheet)
    # =====================================================================
    ac_start = sc_data_start + n_factors + 1
    ws.cell(row=ac_start, column=1, value="ADJUSTED COVARIANCE (from Covariance sheet)").font = FONT_SECTION
    ac_header = ac_start + 1
    for j, f in enumerate(ALL_FACTORS):
        cell = ws.cell(row=ac_header, column=j + 2, value=f)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER

    ac_data_start = ac_header + 1
    for i, fi in enumerate(ALL_FACTORS):
        r = ac_data_start + i
        ws.cell(row=r, column=1, value=fi).font = FONT_HEADER
        ws.cell(row=r, column=1).fill = FILL_HEADER
        for j in range(n_factors):
            cov_col = get_column_letter(j + 2)
            formula = f"=Covariance!{cov_col}{i+2}"
            cell = ws.cell(row=r, column=j + 2, value=formula)
            cell.fill = FILL_FORMULA
            cell.number_format = "0.000000E+00"

    # =====================================================================
    # SECTION 5: Ratio adjusted/simple (22×22)
    # =====================================================================
    ratio_start = ac_data_start + n_factors + 1
    ws.cell(row=ratio_start, column=1, value="RATIO: ADJUSTED / SIMPLE").font = FONT_SECTION
    ratio_header = ratio_start + 1
    for j, f in enumerate(ALL_FACTORS):
        cell = ws.cell(row=ratio_header, column=j + 2, value=f)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER

    ratio_data_start = ratio_header + 1
    for i, fi in enumerate(ALL_FACTORS):
        r = ratio_data_start + i
        ws.cell(row=r, column=1, value=fi).font = FONT_HEADER
        ws.cell(row=r, column=1).fill = FILL_HEADER
        for j in range(n_factors):
            col_l = get_column_letter(j + 2)
            sc_r = sc_data_start + i
            ac_r = ac_data_start + i
            formula = f"=IF({col_l}{sc_r}=0,\"\",{col_l}{ac_r}/{col_l}{sc_r})"
            cell = ws.cell(row=r, column=j + 2, value=formula)
            cell.fill = FILL_FORMULA
            cell.number_format = NUM_FMT_4

    # =====================================================================
    # SECTION 6: Summary stats
    # =====================================================================
    ss_start = ratio_data_start + n_factors + 2
    ws.cell(row=ss_start, column=1, value="SUMMARY STATISTICS").font = FONT_SECTION

    # Average diagonal ratio
    diag_refs = []
    for i in range(n_factors):
        col_l = get_column_letter(i + 2)
        diag_refs.append(f"{col_l}{ratio_data_start + i}")
    ws.cell(row=ss_start + 1, column=1, value="Avg diagonal ratio (variance)")
    formula = "=AVERAGE(" + ",".join(diag_refs) + ")"
    cell = ws.cell(row=ss_start + 1, column=2, value=formula)
    cell.fill = FILL_FORMULA
    cell.number_format = NUM_FMT_4

    ws.cell(row=ss_start + 2, column=1, value="Interpretation")
    ws.cell(row=ss_start + 2, column=2,
            value="Ratio > 1 = adjustments increase risk estimates")

    # Column widths
    ws.column_dimensions["A"].width = 36
    for c in range(2, 24):
        ws.column_dimensions[get_column_letter(c)].width = 14


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 70)
    print("INTERACTIVE VERIFICATION WORKBOOK GENERATOR")
    print("=" * 70)

    print("\nLoading model data...")
    factor_exp, factor_ret, factor_cov = load_data()

    tickers = sorted(SELECTED_TICKERS)
    print(f"Selected {len(tickers)} stocks (alphabetical): {tickers[:5]}...{tickers[-2:]}")

    print(f"Filtering to {DATE_START} — {DATE_END}...")
    subset = filter_subset(factor_exp)
    n_dates = subset["date"].nunique()
    print(f"  {len(subset)} rows, {n_dates} dates")

    print("\nComputing Python reference values...")
    py_ref = compute_python_references(subset, factor_exp, factor_ret, factor_cov)
    print(f"  Factor vol: {py_ref['factor_vol_annual']*100:.2f}%")
    print(f"  Idio vol:   {py_ref['idio_vol']*100:.2f}%")
    print(f"  Total vol:  {py_ref['total_vol']*100:.2f}%")
    print(f"  % Factor:   {py_ref['pct_factor']:.1f}%  |  % Idio: {py_ref['pct_idio']:.1f}%")

    print("\nComputing full-period residuals for all 20 stocks...")
    resid_df = compute_residuals_full(tickers, factor_exp, factor_ret)
    print(f"  {len(resid_df)} dates × {len(resid_df.columns)} stocks")

    # Prepare universe data early (needed for Stocks -> ZScoring linkage)
    print("\nPreparing universe data for representative date...")
    universe_df = get_universe_data(factor_exp)
    print(f"  {len(universe_df)} stocks on {REP_DATE}")

    # Build ticker -> ZScoring row mapping (Universe is sorted alphabetically)
    universe_tickers = universe_df["ticker"].tolist()
    universe_row_map = {}  # ticker -> Excel row in ZScoring sheet (1-indexed, row 2 = first data)
    for idx, t in enumerate(universe_tickers):
        universe_row_map[t] = idx + 2  # header is row 1

    # Create workbook
    wb = Workbook()
    wb.remove(wb.active)  # remove default sheet

    print("\nWriting Sheet 1: Stocks (z-scores linked to ZScoring)...")
    write_stocks_sheet(wb, subset, factor_cov, tickers, universe_row_map)

    print("Writing Sheet 2: Covariance...")
    write_covariance_sheet(wb, factor_cov)

    print("Writing Sheet 3: FactorReturns...")
    write_factor_returns_sheet(wb, factor_ret)

    print("Writing Sheet 4: Residuals...")
    write_residuals_sheet(wb, resid_df, tickers)

    print("Writing Sheet 5: RiskDecomp (all formulas)...")
    write_risk_decomp_sheet(wb, py_ref, tickers)

    print("Writing Sheet 6: Regression...")
    write_regression_sheet(wb, subset, factor_exp, factor_ret)

    print("Writing Sheet 7: Universe...")
    write_universe_sheet(wb, universe_df)

    print("Computing z-score references...")
    zscore_refs = compute_zscore_references(universe_df)

    print("Writing Sheet 8: ZScoring...")
    write_zscoring_sheet(wb, universe_df, zscore_refs)

    print("Computing WLS references...")
    wls_refs = compute_wls_references(universe_df, factor_ret)

    print("Writing Sheet 9: WLSRegression...")
    write_wls_regression_sheet(wb, universe_df, wls_refs)

    print("Writing Sheet 10: SimpleCov...")
    write_simple_cov_sheet(wb, factor_ret, factor_cov)

    print(f"\nSaving to {OUTPUT_PATH}...")
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    wb.save(OUTPUT_PATH)
    size_mb = os.path.getsize(OUTPUT_PATH) / (1024 * 1024)
    print(f"Done! {OUTPUT_PATH} ({size_mb:.1f} MB)")
    print(f"  10 sheets")
    print("\nOpen the .xlsx -> change a weight in Stocks!B2 -> RiskDecomp updates live!")


if __name__ == "__main__":
    main()
