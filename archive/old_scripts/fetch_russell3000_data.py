# -*- coding: utf-8 -*-
"""
Fetch Russell 3000 fundamental data for cross-sectional factor model
"""

import yfinance as yf
import pandas as pd
import numpy as np
import time
import warnings
import sys
warnings.filterwarnings('ignore')

def fetch_stock_data(ticker, period='3mo'):
    """Fetch data for a single stock"""
    try:
        stock = yf.Ticker(ticker)

        # Get price history
        hist = stock.history(period=period)
        if len(hist) < 20:  # Need at least 20 days
            return None

        # Get info
        info = stock.info

        # Extract fundamentals
        data = {
            'ticker': ticker,
            'market_cap': info.get('marketCap', np.nan),
            'book_value': info.get('bookValue', np.nan),
            'price_to_book': info.get('priceToBook', np.nan),
            'roe': info.get('returnOnEquity', np.nan),
            'trailing_pe': info.get('trailingPE', np.nan),
            'forward_pe': info.get('forwardPE', np.nan),
            'dividend_yield': info.get('dividendYield', np.nan),
            'beta': info.get('beta', np.nan),
            'avg_volume': info.get('averageVolume', np.nan),
            'current_price': info.get('currentPrice', info.get('regularMarketPrice', np.nan)),
        }

        # Calculate returns and volatility from history
        hist['return'] = hist['Close'].pct_change()
        data['volatility_60d'] = hist['return'].std() * np.sqrt(252)
        data['momentum_60d'] = (hist['Close'].iloc[-1] / hist['Close'].iloc[0]) - 1
        data['avg_volume_60d'] = hist['Volume'].mean()

        # Get latest 60 days of returns for time series
        returns = hist['return'].dropna().tail(60).tolist()
        data['returns'] = returns
        data['dates'] = hist.index[-len(returns):].strftime('%Y-%m-%d').tolist()

        return data

    except Exception as e:
        return None


def fetch_all_russell(tickers, sectors, batch_size=10, delay=1.0):
    """Fetch data for all Russell 3000 stocks"""
    all_data = []
    failed = []

    total = len(tickers)
    start_time = time.time()

    for i, ticker in enumerate(tickers):
        # Progress update every 50 stocks
        if i % 50 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            remaining = (total - i) / rate / 60 if rate > 0 else 0
            print(f"[{i+1}/{total}] {i*100//total}% complete, ~{remaining:.0f} min remaining", flush=True)

        data = fetch_stock_data(ticker)
        if data:
            data['sector'] = sectors.get(ticker, 'Unknown')
            all_data.append(data)
            status = "OK"
        else:
            failed.append(ticker)
            status = "FAIL"

        # Brief status every 10 stocks
        if (i + 1) % 10 == 0:
            print(f"  ...{ticker}: {status} ({len(all_data)} success, {len(failed)} failed)", flush=True)

        # Rate limiting
        if (i + 1) % batch_size == 0:
            time.sleep(delay)

    print(f"\n{'='*60}")
    print(f"COMPLETED: {len(all_data)}/{total} successful ({len(all_data)*100//total}%)")
    print(f"Failed: {len(failed)}")
    if len(failed) <= 20:
        print(f"Failed tickers: {failed}")
    else:
        print(f"First 20 failed: {failed[:20]}...")

    return all_data, failed


def calculate_factor_exposures(all_data):
    """Calculate z-scored factor exposures"""

    # Create DataFrame from fetched data (excluding returns time series)
    records = []
    for d in all_data:
        record = {k: v for k, v in d.items() if k not in ['returns', 'dates']}
        records.append(record)

    df = pd.DataFrame(records)

    # Calculate raw factors
    df['size_raw'] = np.log(df['market_cap'].replace(0, np.nan))
    df['momentum_raw'] = df['momentum_60d']
    df['volatility_raw'] = df['volatility_60d']
    df['value_raw'] = 1 / df['price_to_book'].replace(0, np.nan)  # Book-to-price
    df['quality_raw'] = df['roe']
    df['liquidity_raw'] = np.log(df['avg_volume_60d'].replace(0, np.nan))

    # Z-score normalization (handle NaN by excluding from mean/std calculation)
    def zscore(series):
        mean = series.mean()
        std = series.std()
        if std == 0 or pd.isna(std):
            return series * 0  # Return zeros if no variation
        return (series - mean) / std

    df['size'] = zscore(df['size_raw'])
    df['momentum'] = zscore(df['momentum_raw'])
    df['volatility'] = zscore(df['volatility_raw'])
    df['value'] = zscore(df['value_raw'])
    df['quality'] = zscore(df['quality_raw'])
    df['liquidity'] = zscore(df['liquidity_raw'])

    return df, all_data


def create_cross_sectional_data(df, all_data):
    """Create data format compatible with Barra MFM code"""

    # Get unique sectors for industry dummies
    sectors = df['sector'].dropna().unique()
    sectors = [s for s in sectors if s != 'Unknown' and s != 'Cash and/or Derivatives' and s != 'Other']

    # Create daily cross-sectional data
    daily_data = []

    # Get the dates from the first stock with data
    sample_stock = next((d for d in all_data if d.get('returns') and len(d['returns']) > 0), None)
    if not sample_stock:
        raise ValueError("No valid return data found")

    dates = sample_stock['dates']

    print(f"Creating cross-sectional data for {len(dates)} dates...")

    for date_idx, date in enumerate(dates):
        for stock_data in all_data:
            if not stock_data.get('returns') or len(stock_data['returns']) <= date_idx:
                continue

            ticker = stock_data['ticker']
            df_row = df[df['ticker'] == ticker]
            if df_row.empty:
                continue

            ret_val = stock_data['returns'][date_idx]
            if pd.isna(ret_val):
                continue

            row = {
                'date': date,
                'stocknames': ticker,
                'capital': df_row['market_cap'].values[0],
                'ret': ret_val
            }

            # Add industry dummies
            stock_sector = df_row['sector'].values[0]
            for sector in sectors:
                row[sector] = 1 if stock_sector == sector else 0

            # Add style factors
            for factor in ['size', 'momentum', 'volatility', 'value', 'quality', 'liquidity']:
                val = df_row[factor].values[0]
                row[factor] = val if not pd.isna(val) else 0

            daily_data.append(row)

    result_df = pd.DataFrame(daily_data)

    # Order columns: date, stocknames, capital, ret, [industries], [styles]
    industry_cols = list(sectors)
    style_cols = ['size', 'momentum', 'volatility', 'value', 'quality', 'liquidity']
    col_order = ['date', 'stocknames', 'capital', 'ret'] + industry_cols + style_cols

    # Only keep columns that exist
    col_order = [c for c in col_order if c in result_df.columns]
    result_df = result_df[col_order]

    return result_df, industry_cols, style_cols


if __name__ == '__main__':
    print("="*60)
    print("Russell 3000 Data Fetcher for Cross-Sectional Factor Model")
    print("="*60)
    print(f"Started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Load Russell constituents
    print("Loading Russell constituents...")
    russell_df = pd.read_csv('Russel constituents.csv', sep=';')
    tickers = russell_df['Ticker'].tolist()

    # Fix common ticker issues for yfinance
    tickers = [t.replace('.', '-') if '.' in t else t for t in tickers]

    # Create sector lookup
    sectors = dict(zip(russell_df['Ticker'].tolist(), russell_df['Sector'].tolist()))

    print(f"Found {len(tickers)} tickers")
    print()

    # Fetch all data
    print("="*60)
    print("FETCHING DATA FROM YFINANCE")
    print("="*60)
    all_data, failed = fetch_all_russell(tickers, sectors, batch_size=10, delay=1.0)

    # Save failed tickers
    pd.DataFrame({'ticker': failed}).to_csv('russell3000_failed_tickers.csv', index=False)

    # Calculate factor exposures
    print("\n" + "="*60)
    print("CALCULATING FACTOR EXPOSURES")
    print("="*60)
    df, all_data = calculate_factor_exposures(all_data)

    # Save raw fundamentals
    raw_cols = ['ticker', 'sector', 'market_cap', 'book_value', 'price_to_book',
                'roe', 'trailing_pe', 'forward_pe', 'dividend_yield', 'beta',
                'avg_volume', 'current_price', 'volatility_60d', 'momentum_60d', 'avg_volume_60d']
    available_raw_cols = [c for c in raw_cols if c in df.columns]
    df[available_raw_cols].to_csv('russell3000_raw_fundamentals.csv', index=False)
    print(f"Saved raw fundamentals to russell3000_raw_fundamentals.csv")

    # Save factor exposures (z-scored)
    factor_cols = ['ticker', 'sector', 'market_cap',
                   'size', 'momentum', 'volatility', 'value', 'quality', 'liquidity',
                   'size_raw', 'momentum_raw', 'volatility_raw', 'value_raw', 'quality_raw', 'liquidity_raw']
    available_factor_cols = [c for c in factor_cols if c in df.columns]
    df[available_factor_cols].to_csv('russell3000_factor_exposures.csv', index=False)
    print(f"Saved factor exposures to russell3000_factor_exposures.csv")

    # Create cross-sectional data for MFM
    print("\n" + "="*60)
    print("CREATING CROSS-SECTIONAL DATA")
    print("="*60)
    try:
        cs_data, industry_cols, style_cols = create_cross_sectional_data(df, all_data)
        cs_data.to_csv('russell3000_cross_sectional_data.csv', index=False)
        print(f"Saved cross-sectional data to russell3000_cross_sectional_data.csv")
        print(f"  Shape: {cs_data.shape}")
        print(f"  Dates: {cs_data['date'].nunique()}")
        print(f"  Stocks: {cs_data['stocknames'].nunique()}")
        print(f"  Industries: {len(industry_cols)}")
        print(f"  Style factors: {len(style_cols)}")
    except Exception as e:
        print(f"Error creating cross-sectional data: {e}")

    print("\n" + "="*60)
    print(f"COMPLETED at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
