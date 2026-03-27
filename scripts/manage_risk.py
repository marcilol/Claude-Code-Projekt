# -*- coding: utf-8 -*-
"""
Factor Risk Management - Chapter 7 Implementation
From "Advanced Portfolio Management" by Giuseppe Paleologo

Produces four output tables:
1. Risk Decomposition - hierarchical %Var/$Exp/$Vol/MCFR by factor group
2. Position Risk - per-stock MCFR + breach flagging
3. Limit Breach Summary - current vs limits
4. Suggested Trades - MCFR-ranked reduction recommendations
"""

import pandas as pd
import numpy as np
import yfinance as yf
import sys
import warnings
import requests
warnings.filterwarnings('ignore')

def download_file_from_github(url, local_filename):
    """Download a file from GitHub release and save it locally."""
    response = requests.get(url, stream=True)
    response.raise_for_status()  # Check if the request was successful
    with open(local_filename, 'wb') as file:
        for chunk in response.iter_content(chunk_size=8192):
            file.write(chunk)
    print(f"Downloaded {local_filename} from {url}")

# URLs of the files in the GitHub release
release_base_url = "https://github.com/marcilol/Claude-Code-Projekt/releases/download/v1/"
russell3000_cross_sectional_data_url = release_base_url + "russell3000_cross_sectional_data.csv"
russell3000_daily_prices_url = release_base_url + "russell3000_daily_prices.csv"
russell3000_factor_exposures_historical_url = release_base_url + "russell3000_factor_exposures_historical.csv"

def load_portfolio(filepath):
    """Load portfolio from CSV file"""
    with open(filepath, 'r') as f:
        first_line = f.readline()
    delimiter = ';' if ';' in first_line else ','

    df = pd.read_csv(filepath, sep=delimiter)
    df.columns = df.columns.str.lower().str.strip()

    ticker_col = next((c for c in df.columns if 'ticker' in c.lower()), None)
    shares_col = next((c for c in df.columns if 'share' in c.lower()), None)

    if ticker_col is None or shares_col is None:
        raise ValueError("Could not find ticker or shares columns")

    df = df.rename(columns={ticker_col: 'ticker', shares_col: 'shares'})
    return df[['ticker', 'shares']]


def get_portfolio_weights(portfolio_df):
    """Calculate portfolio weights and NMV based on current market values"""
    tickers = portfolio_df['ticker'].tolist()
    shares = portfolio_df['shares'].tolist()

    prices = {}
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            price = info.get('currentPrice', info.get('regularMarketPrice', np.nan))
            prices[ticker] = price
        except:
            prices[ticker] = np.nan

    market_values = []
    valid_tickers = []
    valid_shares = []

    for ticker, share in zip(tickers, shares):
        price = prices.get(ticker, np.nan)
        if pd.notna(price) and price > 0:
            market_values.append(price * share)
            valid_tickers.append(ticker)
            valid_shares.append(share)

    total_value = sum(market_values)
    weights = [mv / total_value for mv in market_values]

    return pd.DataFrame({
        'ticker': valid_tickers,
        'shares': valid_shares,
        'market_value': market_values,
        'weight': weights
    }), total_value


def compute_idiosyncratic_volatility(tickers, factor_exp_df, factor_ret_df):
    """
    Compute stock-level idiosyncratic volatility from Barra model residuals.

    epsilon_i,t = r_i,t - sum(beta_i,k * f_k,t)
    sigma_idio = std(epsilon) * sqrt(252)
    """
    style_factors = ['size', 'beta', 'momentum', 'residvol', 'nlsize', 'btop', 'liquidity', 'earnyild', 'growth', 'leverage']
    industry_factors = [c for c in factor_ret_df.columns
                        if c not in style_factors + ['Country']]

    idio_vol = {}

    for ticker in tickers:
        stock_data = factor_exp_df[factor_exp_df['ticker'] == ticker].copy()

        if len(stock_data) < 20:
            idio_vol[ticker] = np.nan
            continue

        stock_data = stock_data.sort_values('date')
        stock_returns = stock_data.set_index('date')['return']
        stock_exposures = stock_data.set_index('date')[style_factors]
        sector = stock_data['sector'].iloc[0]

        residuals = []

        for date in stock_returns.index:
            if date not in factor_ret_df.index:
                continue

            r_actual = stock_returns.loc[date]
            f_ret = factor_ret_df.loc[date]

            r_predicted = f_ret.get('Country', 0)

            if sector in f_ret.index:
                r_predicted += f_ret[sector]

            if date in stock_exposures.index:
                for factor in style_factors:
                    if factor in f_ret.index and factor in stock_exposures.columns:
                        beta = stock_exposures.loc[date, factor]
                        if pd.notna(beta):
                            r_predicted += beta * f_ret[factor]

            residual = r_actual - r_predicted
            residuals.append(residual)

        if len(residuals) >= 20:
            idio_vol[ticker] = np.std(residuals) * np.sqrt(252)
        else:
            idio_vol[ticker] = np.nan

    return idio_vol


def build_factor_loading_matrix(tickers, factor_exp_df, factor_names):
    """
    Build the B matrix (stocks x factors) from latest factor exposures.

    For style factors: use z-scored exposure values.
    For Country: exposure = 1 for all stocks.
    For industry: one-hot encoded from sector column.
    """
    latest_date = factor_exp_df['date'].max()
    latest = factor_exp_df[factor_exp_df['date'] == latest_date].copy()
    latest = latest[latest['ticker'].isin(tickers)].set_index('ticker')

    style_factors = ['size', 'beta', 'momentum', 'residvol', 'nlsize', 'btop', 'liquidity', 'earnyild', 'growth', 'leverage']
    industry_factors = [f for f in factor_names if f not in style_factors + ['Country']]

    B = pd.DataFrame(0.0, index=tickers, columns=factor_names)

    for ticker in tickers:
        if ticker not in latest.index:
            continue

        row = latest.loc[ticker]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]

        # Country = 1
        B.loc[ticker, 'Country'] = 1.0

        # Style factors
        for f in style_factors:
            if f in row.index and pd.notna(row[f]):
                B.loc[ticker, f] = row[f]

        # Industry dummy
        sector = row.get('sector', '')
        if sector in industry_factors:
            B.loc[ticker, sector] = 1.0

    return B


def compute_mcfr(weights, betas, factor_cov):
    """
    Calculate Marginal Contribution to Factor Risk (MCFR) for each position.

    MCFR_i = [B * Omega_f * b]_i / sqrt(b' * Omega_f * b)

    Where b = B' * w (portfolio factor exposure vector)
    """
    tickers = weights.index.intersection(betas.index)
    w = weights.loc[tickers].values
    B = betas.loc[tickers].values

    factors = betas.columns.tolist()
    Omega_f = factor_cov.loc[factors, factors].values

    # Portfolio factor exposure: b = B' * w
    b = B.T @ w

    # Factor variance: b' * Omega_f * b
    factor_var = b.T @ Omega_f @ b
    factor_vol = np.sqrt(factor_var)

    if factor_vol == 0:
        return pd.Series(0, index=tickers), b, factor_var

    # MCFR_i = (B @ Omega_f @ b)_i / factor_vol
    Omega_f_b = Omega_f @ b
    mcfr = (B @ Omega_f_b) / factor_vol

    return pd.Series(mcfr, index=tickers), b, factor_var


def build_risk_decomposition_table(b, factor_cov, factor_names, idio_variance, gmv):
    """
    Build hierarchical risk decomposition table (Table 7.1 from Paleologo).

    Row hierarchy:
      TOTAL 100%
      |-- IDIO
      `-- FACTOR
          |-- STYLE (Country + style factors)
          |   |-- Country
          |   |-- momentum, volatility, ...
          `-- INDUSTRY
              |-- Information Technology, ...

    Columns: %Var, $Exp, $Vol, MCFR
    """
    style_factors = ['size', 'beta', 'momentum', 'residvol', 'nlsize', 'btop', 'liquidity', 'earnyild', 'growth', 'leverage']
    # Country is grouped under STYLE per book hierarchy
    style_with_country = ['Country'] + style_factors
    industry_factors = [f for f in factor_names if f not in style_with_country]

    Omega_f = factor_cov.loc[factor_names, factor_names].values
    b_vec = np.array([b[i] for i in range(len(factor_names))])

    factor_var = b_vec.T @ Omega_f @ b_vec
    factor_vol = np.sqrt(factor_var)
    total_var = factor_var * 252 + idio_variance

    if total_var == 0:
        return [], 0

    Omega_b = Omega_f @ b_vec

    # Compute per-factor data
    factor_data = {}
    for k, fname in enumerate(factor_names):
        var_contrib = b_vec[k] * Omega_b[k] * 252
        pct_var = var_contrib / total_var * 100
        dollar_exp = b_vec[k] * gmv
        dollar_vol = abs(b_vec[k]) * np.sqrt(Omega_f[k, k] * 252) * gmv
        mcfr_k = Omega_b[k] / factor_vol if factor_vol > 0 else 0
        factor_data[fname] = {
            'pct_var': pct_var, 'dollar_exp': dollar_exp,
            'dollar_vol': dollar_vol, 'mcfr': mcfr_k
        }

    # Group variances
    pct_idio = idio_variance / total_var * 100
    pct_factor = factor_var * 252 / total_var * 100
    style_var = sum(factor_data[f]['pct_var'] for f in style_with_country)
    industry_var = sum(factor_data[f]['pct_var'] for f in industry_factors)

    total_vol_dollar = np.sqrt(total_var) * gmv
    idio_vol_dollar = np.sqrt(idio_variance) * gmv
    factor_vol_dollar = np.sqrt(factor_var * 252) * gmv

    # Sort factors within groups by |%Var|
    style_sorted = sorted(style_with_country, key=lambda f: abs(factor_data[f]['pct_var']), reverse=True)
    industry_sorted = sorted(industry_factors, key=lambda f: abs(factor_data[f]['pct_var']), reverse=True)
    # Filter industry to non-trivial contributors
    industry_sorted = [f for f in industry_sorted if abs(factor_data[f]['pct_var']) >= 0.05]

    return {
        'pct_idio': pct_idio, 'pct_factor': pct_factor,
        'style_var': style_var, 'industry_var': industry_var,
        'total_vol_dollar': total_vol_dollar,
        'idio_vol_dollar': idio_vol_dollar,
        'factor_vol_dollar': factor_vol_dollar,
        'factor_data': factor_data,
        'style_sorted': style_sorted,
        'industry_sorted': industry_sorted,
    }, pct_idio


def print_risk_decomposition(decomp, gmv):
    """Print risk decomposition in Chapter 7 tree-hierarchy format."""
    fd = decomp['factor_data']

    # Column header
    print(f"  {'Component':<30s} {'%Var':>7s} {'$Exp':>10s} {'$Vol':>10s} {'MCFR':>8s}")
    print("  " + "-" * 67)

    # TOTAL
    print(f"  {'TOTAL':<30s} {'100.0%':>7s} {'':>10s} {'${:,.0f}'.format(decomp['total_vol_dollar']):>10s} {'':>8s}")

    # |-- IDIO
    print(f"  {'|-- IDIO':<30s} {'{:.1f}%'.format(decomp['pct_idio']):>7s} {'':>10s} {'${:,.0f}'.format(decomp['idio_vol_dollar']):>10s} {'':>8s}")

    # `-- FACTOR
    print(f"  {'`-- FACTOR':<30s} {'{:.1f}%'.format(decomp['pct_factor']):>7s} {'':>10s} {'${:,.0f}'.format(decomp['factor_vol_dollar']):>10s} {'':>8s}")

    # STYLE group
    print(f"  {'    |-- STYLE':<30s} {'{:.1f}%'.format(decomp['style_var']):>7s} {'':>10s} {'':>10s} {'':>8s}")

    style_list = decomp['style_sorted']
    for i, fname in enumerate(style_list):
        d = fd[fname]
        is_last = (i == len(style_list) - 1)
        branch = '`--' if is_last else '|--'
        prefix = f"    |   {branch} {fname}"
        exp_str = '${:+,.0f}'.format(d['dollar_exp'])
        vol_str = '${:,.0f}'.format(d['dollar_vol'])
        mcfr_str = '{:+.4f}'.format(d['mcfr'])
        pct_str = '{:+.1f}%'.format(d['pct_var'])
        print(f"  {prefix:<30s} {pct_str:>7s} {exp_str:>10s} {vol_str:>10s} {mcfr_str:>8s}")

    # INDUSTRY group
    industry_list = decomp['industry_sorted']
    print(f"  {'    `-- INDUSTRY':<30s} {'{:.1f}%'.format(decomp['industry_var']):>7s} {'':>10s} {'':>10s} {'':>8s}")

    for i, fname in enumerate(industry_list):
        d = fd[fname]
        is_last = (i == len(industry_list) - 1)
        branch = '`--' if is_last else '|--'
        prefix = f"        {branch} {fname}"
        exp_str = '${:+,.0f}'.format(d['dollar_exp'])
        vol_str = '${:,.0f}'.format(d['dollar_vol'])
        mcfr_str = '{:+.4f}'.format(d['mcfr'])
        pct_str = '{:+.1f}%'.format(d['pct_var'])
        print(f"  {prefix:<30s} {pct_str:>7s} {exp_str:>10s} {vol_str:>10s} {mcfr_str:>8s}")


def identify_target_factor(decomp):
    """Identify the dominant non-market style factor driving portfolio risk."""
    fd = decomp['factor_data']
    style_factors = ['momentum', 'residvol', 'beta', 'size', 'btop', 'nlsize', 'liquidity', 'earnyild', 'growth', 'leverage']
    best = max(style_factors, key=lambda f: abs(fd[f]['pct_var']))
    return best


def determine_action(mcfr_val, pct_gmv, max_single_stock_pct):
    """
    Determine recommended action per Chapter 7 logic.

    Long-only actions:
    - High positive MCFR → REDUCE (adds to factor risk)
    - Very high MCFR + large position → SELL
    - Small |MCFR| → HOLD
    - Negative MCFR → HOLD (hedging factor risk)
    """
    if mcfr_val > 0.025:
        if pct_gmv > max_single_stock_pct:
            return 'SELL'
        return 'REDUCE'
    elif mcfr_val > 0.010:
        return 'REDUCE'
    elif mcfr_val > 0.005:
        return 'TRIM'
    elif mcfr_val < -0.005:
        return 'HOLD (HEDGING)'
    else:
        return 'HOLD'


def build_position_risk_table(weights_df, mcfr_series, betas, idio_vols, gmv,
                              max_single_stock_pct, target_factor):
    """Build per-stock risk table (Table 7.2 from Paleologo)."""
    rows = []

    for _, pos in weights_df.iterrows():
        ticker = pos['ticker']
        nmv = pos['market_value']
        pct_gmv = pos['weight'] * 100

        mcfr_val = mcfr_series.get(ticker, 0)

        # Get loading on target factor
        factor_loading = 0.0
        if ticker in betas.index:
            factor_loading = betas.loc[ticker, target_factor]
            if pd.isna(factor_loading):
                factor_loading = 0.0

        action = determine_action(mcfr_val, pct_gmv, max_single_stock_pct)

        rows.append({
            'Stock': ticker,
            'NMV': nmv,
            'MCFR': mcfr_val,
            'factor_loading': factor_loading,
            'Action': action,
        })

    rows.sort(key=lambda r: abs(r['MCFR']), reverse=True)
    return rows


def print_position_risk_table(rows, target_factor):
    """Print position risk table in Table 7.2 format."""
    # Format target factor name for column header
    factor_label = target_factor.capitalize()
    if len(factor_label) > 10:
        factor_label = factor_label[:10]

    print(f"  {'Stock':<8s} {'NMV':>10s} {'MCFR':>8s} {factor_label:>10s}  {'Action':<16s}")
    print("  " + "-" * 58)

    for r in rows:
        nmv_str = '${:,.0f}'.format(r['NMV'])
        mcfr_str = '{:+.4f}'.format(r['MCFR'])
        loading_str = '{:+.2f}'.format(r['factor_loading'])
        print(f"  {r['Stock']:<8s} {nmv_str:>10s} {mcfr_str:>8s} {loading_str:>10s}  {r['Action']:<16s}")


def check_limits(pct_idio_var, weights_df, min_pct_idio_var, max_single_stock_pct):
    """Check portfolio against risk limits."""
    rows = []

    # % Idio Variance limit
    idio_status = 'OK' if pct_idio_var >= min_pct_idio_var else 'BREACH'
    rows.append({
        'Limit Type': '% Idio Variance (min)',
        'Current': f"{pct_idio_var:.1f}%",
        'Limit': f"{min_pct_idio_var:.1f}%",
        'Status': idio_status
    })

    # Max single stock
    max_pos = weights_df['weight'].max() * 100
    max_ticker = weights_df.loc[weights_df['weight'].idxmax(), 'ticker']
    pos_status = 'OK' if max_pos <= max_single_stock_pct else 'BREACH'
    rows.append({
        'Limit Type': f'Max Single Stock ({max_ticker})',
        'Current': f"{max_pos:.1f}%",
        'Limit': f"{max_single_stock_pct:.1f}%",
        'Status': pos_status
    })

    # HHI concentration
    hhi = (weights_df['weight'] ** 2).sum()
    n_stocks = len(weights_df)
    # Max HHI limit: 2x equal-weight HHI
    hhi_limit = 2.0 / n_stocks
    hhi_status = 'OK' if hhi <= hhi_limit else 'BREACH'
    rows.append({
        'Limit Type': 'HHI Concentration',
        'Current': f"{hhi:.4f}",
        'Limit': f"{hhi_limit:.4f}",
        'Status': hhi_status
    })

    return rows


def suggest_trades(weights_df, mcfr_series, idio_vols, pct_idio_var,
                   factor_var_ann, idio_variance, gmv, max_single_stock_pct):
    """
    Suggest trades to reduce factor risk, ranked by MCFR.

    For positions that breach limits or have highest |MCFR|, suggest reducing
    toward target weight and estimate impact on %idio variance.
    """
    rows = []

    for _, pos in weights_df.iterrows():
        ticker = pos['ticker']
        pct_gmv = pos['weight'] * 100
        nmv = pos['market_value']
        mcfr_val = mcfr_series.get(ticker, 0)

        # Flag if position breaches single-stock limit or has high MCFR
        needs_trade = (pct_gmv > max_single_stock_pct) or (abs(mcfr_val) > 0.01)
        if not needs_trade:
            continue

        # Suggest reduction: bring toward limit or reduce by 20% if MCFR-driven
        if pct_gmv > max_single_stock_pct:
            target_pct = max_single_stock_pct
            suggested_nmv = target_pct / 100 * gmv
            delta = suggested_nmv - nmv
        else:
            # Reduce by 20% of current position
            delta = -0.20 * nmv
            suggested_nmv = nmv + delta

        # Estimate impact on idio variance
        idio_vol_stock = idio_vols.get(ticker, 0.30)
        if pd.isna(idio_vol_stock):
            idio_vol_stock = 0.30

        old_w = pos['weight']
        new_w = suggested_nmv / gmv
        total_var = factor_var_ann + idio_variance
        old_idio_contrib = old_w ** 2 * idio_vol_stock ** 2
        new_idio_contrib = new_w ** 2 * idio_vol_stock ** 2
        delta_idio_var = new_idio_contrib - old_idio_contrib
        new_total_var = total_var + delta_idio_var
        new_pct_idio = (idio_variance + delta_idio_var) / new_total_var * 100 if new_total_var > 0 else 0
        delta_pct_idio = new_pct_idio - pct_idio_var

        rows.append({
            'Ticker': ticker,
            'Current NMV': f"${nmv:,.0f}",
            'Suggested': f"${delta:+,.0f}",
            'New NMV': f"${suggested_nmv:,.0f}",
            'MCFR': mcfr_val,
            'Impact %Idio': f"{delta_pct_idio:+.2f}%"
        })

    # Sort by absolute MCFR descending (biggest risk contributors first)
    rows.sort(key=lambda r: abs(r['MCFR']), reverse=True)

    # Format MCFR for display after sorting
    for r in rows:
        r['MCFR'] = f"{r['MCFR']:+.3f}"

    return rows[:10]  # Top 10 suggestions


def print_table(title, rows, columns):
    """Print a formatted table to console."""
    if not rows:
        print(f"\n{title}")
        print("  No data available.")
        return

    # Compute column widths
    widths = {}
    for col in columns:
        widths[col] = max(len(col), max(len(str(r.get(col, ''))) for r in rows))

    # Header
    print(f"\n{title}")
    print("-" * (sum(widths.values()) + 3 * (len(columns) - 1) + 4))

    header = '  '.join(f"{col:>{widths[col]}}" if col != columns[0]
                       else f"  {col:<{widths[col]}}" for col in columns)
    print(header)
    print("-" * (sum(widths.values()) + 3 * (len(columns) - 1) + 4))

    # Rows
    for row in rows:
        line = '  '.join(
            f"{str(row.get(col, '')):>{widths[col]}}" if col != columns[0]
            else f"  {str(row.get(col, '')):<{widths[col]}}"
            for col in columns
        )
        print(line)


def main(portfolio_path, check_limits_flag=False,
         min_pct_idio_var=75.0, max_single_stock_pct=10.0):
    print("=" * 70)
    print("FACTOR RISK MANAGEMENT - Chapter 7")
    print("=" * 70)

    # Download the files from release
    download_file_from_github(russell3000_cross_sectional_data_url, 'data/model/russell3000_cross_sectional_data.csv')
    download_file_from_github(russell3000_daily_prices_url, 'data/model/russell3000_daily_prices.csv')
    download_file_from_github(russell3000_factor_exposures_historical_url, 'data/model/russell3000_factor_exposures_historical.csv')

    # Load portfolio
    print(f"\nLoading portfolio: {portfolio_path}")
    portfolio_df = load_portfolio(portfolio_path)
    print(f"  Found {len(portfolio_df)} positions")

    # Get current weights
    print("\nFetching current prices...")
    weights_df, gmv = get_portfolio_weights(portfolio_df)
    print(f"  Priced {len(weights_df)} positions")
    print(f"  Gross Market Value: ${gmv:,.0f}")

    # Load model data
    print("\nLoading factor model data...")
    factor_exp_df = pd.read_csv('data/model/russell3000_factor_exposures_historical.csv')
    factor_cov_df = pd.read_csv('data/model/barra_factor_covariance.csv', index_col=0)
    factor_ret_df = pd.read_csv('data/model/barra_factor_returns.csv', index_col=0)

    factor_names = factor_cov_df.columns.tolist()

    # Build factor loading matrix B
    matched_tickers = [t for t in weights_df['ticker'] if t in factor_exp_df['ticker'].unique()]
    missing_tickers = set(weights_df['ticker']) - set(matched_tickers)
    print(f"  Matched {len(matched_tickers)} stocks with factor data")
    if missing_tickers:
        print(f"  Missing: {missing_tickers}")

    B = build_factor_loading_matrix(matched_tickers, factor_exp_df, factor_names)

    # Compute idiosyncratic volatility
    print("  Computing idiosyncratic volatility...")
    idio_vols = compute_idiosyncratic_volatility(matched_tickers, factor_exp_df, factor_ret_df)
    n_computed = sum(1 for v in idio_vols.values() if pd.notna(v))
    print(f"  Computed idio vol for {n_computed}/{len(matched_tickers)} stocks")

    # Build NMV-dollar weight vector (for MCFR computation, use portfolio weights)
    w = weights_df.set_index('ticker')['weight']
    w = w.reindex(matched_tickers).fillna(0)

    # Compute MCFR
    mcfr_series, b_vec, factor_var = compute_mcfr(w, B, factor_cov_df)

    # Compute idiosyncratic variance
    median_idio = np.nanmedian(list(idio_vols.values()))
    idio_variance = 0
    for ticker in matched_tickers:
        wt = w.get(ticker, 0)
        sigma = idio_vols.get(ticker, median_idio)
        if pd.isna(sigma):
            sigma = median_idio
        idio_variance += wt ** 2 * sigma ** 2

    factor_var_ann = factor_var * 252
    total_var = factor_var_ann + idio_variance
    pct_idio = idio_variance / total_var * 100 if total_var > 0 else 0

    # ================================================================
    # TABLE 1: Risk Decomposition (Table 7.1 format)
    # ================================================================
    decomp, pct_idio_var = build_risk_decomposition_table(
        b_vec, factor_cov_df, factor_names, idio_variance, gmv
    )

    print("\n" + "=" * 70)
    print("TABLE 1: RISK DECOMPOSITION")
    print("=" * 70)
    print()
    print_risk_decomposition(decomp, gmv)

    # ================================================================
    # TABLE 2: Position Risk (Table 7.2 format)
    # ================================================================
    target_factor = identify_target_factor(decomp)

    print("\n" + "=" * 70)
    print(f"TABLE 2: POSITION RISK (target factor: {target_factor})")
    print("=" * 70)
    print()

    pos_rows = build_position_risk_table(
        weights_df, mcfr_series, B, idio_vols, gmv,
        max_single_stock_pct, target_factor
    )
    print_position_risk_table(pos_rows, target_factor)

    # ================================================================
    # TABLE 3: Limit Breach Summary
    # ================================================================
    if check_limits_flag:
        print("\n" + "=" * 70)
        print("TABLE 3: LIMIT BREACH SUMMARY")
        print("=" * 70)

        limit_rows = check_limits(pct_idio_var, weights_df,
                                  min_pct_idio_var, max_single_stock_pct)
        print_table(
            "",
            limit_rows,
            ['Limit Type', 'Current', 'Limit', 'Status']
        )

        any_breach = any(r['Status'] == 'BREACH' for r in limit_rows)

        # ================================================================
        # TABLE 4: Suggested Trades (only if breaches exist)
        # ================================================================
        if any_breach:
            print("\n" + "=" * 70)
            print("TABLE 4: SUGGESTED TRADES (ranked by |MCFR|)")
            print("=" * 70)

            trade_rows = suggest_trades(
                weights_df, mcfr_series, idio_vols, pct_idio_var,
                factor_var_ann, idio_variance, gmv, max_single_stock_pct
            )
            print_table(
                "",
                trade_rows,
                ['Ticker', 'Current NMV', 'Suggested', 'New NMV', 'MCFR', 'Impact %Idio']
            )
        else:
            print("\n  All limits OK - no trades suggested.")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\n  Gross Market Value:     ${gmv:,.0f}")
    print(f"  # Positions:            {len(weights_df)}")
    print(f"  Factor Volatility:      {np.sqrt(factor_var_ann) * 100:.1f}%")
    print(f"  Idiosyncratic Vol:      {np.sqrt(idio_variance) * 100:.1f}%")
    print(f"  Total Volatility:       {np.sqrt(total_var) * 100:.1f}%")
    print(f"  % Idiosyncratic Var:    {pct_idio_var:.1f}%")

    top_mcfr = mcfr_series.abs().nlargest(3)
    print(f"\n  Top 3 MCFR contributors:")
    for ticker, val in top_mcfr.items():
        print(f"    {ticker:8s}: {mcfr_series[ticker]:+.4f}")

    print("\n  Chapter 7 Insight:")
    print("  Factor risk management focuses on controlling SYSTEMATIC risk.")
    print("  High %idio variance (>50%) means stock-picking dominates -")
    print("  reduce concentration to diversify idiosyncratic risk.")
    print("  Low %idio variance means factor tilts dominate -")
    print("  consider hedging or reducing factor exposures.")

    print("\n" + "=" * 70)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        portfolio_path = sys.argv[1]
    else:
        portfolio_path = 'data/input/portfolios/Own_Portfolio_dated.csv'

    check_limits_flag = '--limits' in sys.argv

    # Parse optional limit overrides
    min_pct_idio = 75.0
    max_single = 10.0

    for arg in sys.argv[2:]:
        if arg.startswith('--min-idio='):
            min_pct_idio = float(arg.split('=')[1])
        elif arg.startswith('--max-stock='):
            max_single = float(arg.split('=')[1])

    main(portfolio_path, check_limits_flag, min_pct_idio, max_single)
