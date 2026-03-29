# -*- coding: utf-8 -*-
"""
Fetch S&P 500 data for cross-sectional factor model
"""

import yfinance as yf
import pandas as pd
import numpy as np
import time
import warnings
warnings.filterwarnings('ignore')

def get_sp500_tickers():
    """Get S&P 500 tickers - hardcoded list of major components"""
    # Using a representative sample of ~200 large, liquid stocks across sectors
    # This is sufficient for factor model estimation
    tickers = [
        # Technology
        'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'META', 'NVDA', 'AVGO', 'CSCO', 'ADBE', 'CRM',
        'ORCL', 'ACN', 'IBM', 'INTC', 'AMD', 'TXN', 'QCOM', 'NOW', 'INTU', 'AMAT',
        'ADI', 'MU', 'LRCX', 'KLAC', 'SNPS', 'CDNS', 'MCHP', 'APH', 'MSI', 'TEL',
        # Healthcare
        'UNH', 'JNJ', 'LLY', 'PFE', 'ABBV', 'MRK', 'TMO', 'ABT', 'DHR', 'BMY',
        'AMGN', 'MDT', 'GILD', 'CVS', 'ISRG', 'VRTX', 'SYK', 'ZTS', 'BDX', 'CI',
        'BSX', 'HUM', 'ELV', 'REGN', 'MCK', 'HCA', 'MRNA', 'IDXX', 'DXCM', 'EW',
        # Financials
        'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'AXP', 'BLK', 'SCHW',
        'C', 'PGR', 'CB', 'MMC', 'ICE', 'CME', 'AON', 'USB', 'PNC', 'TFC',
        'AIG', 'MET', 'PRU', 'ALL', 'TRV', 'AFL', 'SPGI', 'MCO', 'MSCI', 'COF',
        # Consumer Discretionary
        'AMZN', 'TSLA', 'HD', 'MCD', 'NKE', 'LOW', 'SBUX', 'TJX', 'BKNG', 'MAR',
        'ORLY', 'AZO', 'CMG', 'YUM', 'DHI', 'LEN', 'F', 'GM', 'ROST', 'ULTA',
        'DG', 'DLTR', 'EBAY', 'ETSY', 'BBY', 'GRMN', 'POOL', 'PHM', 'RCL', 'CCL',
        # Consumer Staples
        'PG', 'KO', 'PEP', 'COST', 'WMT', 'PM', 'MO', 'MDLZ', 'CL', 'EL',
        'GIS', 'KMB', 'SYY', 'HSY', 'K', 'STZ', 'KHC', 'KR', 'WBA', 'CLX',
        # Energy
        'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'MPC', 'PSX', 'VLO', 'OXY', 'PXD',
        'WMB', 'KMI', 'HAL', 'DVN', 'HES', 'BKR', 'FANG', 'TRGP', 'OKE', 'CTRA',
        # Industrials
        'UNP', 'RTX', 'HON', 'UPS', 'BA', 'CAT', 'DE', 'LMT', 'GE', 'MMM',
        'ADP', 'ITW', 'EMR', 'ETN', 'FDX', 'NSC', 'CSX', 'WM', 'JCI', 'PH',
        'GD', 'TT', 'PCAR', 'CTAS', 'CARR', 'OTIS', 'ROK', 'FAST', 'AME', 'IR',
        # Materials
        'LIN', 'APD', 'SHW', 'ECL', 'NEM', 'FCX', 'NUE', 'DOW', 'DD', 'PPG',
        'VMC', 'MLM', 'ALB', 'CF', 'MOS', 'CTVA', 'IFF', 'FMC', 'CE', 'EMN',
        # Utilities
        'NEE', 'DUK', 'SO', 'D', 'AEP', 'SRE', 'EXC', 'XEL', 'PEG', 'ED',
        'WEC', 'ES', 'AWK', 'DTE', 'EIX', 'FE', 'PPL', 'AEE', 'CMS', 'CNP',
        # Real Estate
        'PLD', 'AMT', 'EQIX', 'CCI', 'PSA', 'O', 'WELL', 'DLR', 'SPG', 'VICI',
        'AVB', 'EQR', 'VTR', 'ARE', 'MAA', 'UDR', 'ESS', 'PEAK', 'HST', 'KIM',
        # Communication Services
        'GOOG', 'META', 'NFLX', 'DIS', 'CMCSA', 'VZ', 'T', 'TMUS', 'CHTR', 'EA',
        'TTWO', 'WBD', 'OMC', 'IPG', 'LYV', 'MTCH', 'PARA', 'FOXA', 'NWS', 'DISH'
    ]

    # Remove duplicates while preserving order
    seen = set()
    unique_tickers = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            unique_tickers.append(t)

    return unique_tickers

def fetch_stock_data(ticker, period='1y'):
    """Fetch data for a single stock"""
    try:
        stock = yf.Ticker(ticker)

        # Get price history
        hist = stock.history(period=period)
        if len(hist) < 60:  # Need at least 60 days
            return None

        # Get info
        info = stock.info

        # Extract fundamentals
        data = {
            'ticker': ticker,
            'sector': info.get('sector', 'Unknown'),
            'industry': info.get('industry', 'Unknown'),
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
        data['dates'] = hist.index[-60:].strftime('%Y-%m-%d').tolist()

        return data

    except Exception as e:
        print(f"  Error fetching {ticker}: {e}")
        return None

def fetch_all_sp500(batch_size=10, delay=1.0):
    """Fetch data for all S&P 500 stocks"""
    print("Fetching S&P 500 ticker list...")
    tickers = get_sp500_tickers()
    print(f"Found {len(tickers)} tickers")

    all_data = []
    failed = []

    for i, ticker in enumerate(tickers):
        print(f"[{i+1}/{len(tickers)}] Fetching {ticker}...", end=' ', flush=True)

        data = fetch_stock_data(ticker)
        if data:
            all_data.append(data)
            print("OK")
        else:
            failed.append(ticker)
            print("FAILED")

        # Rate limiting
        if (i + 1) % batch_size == 0:
            print(f"  Pausing {delay}s to avoid rate limiting...")
            time.sleep(delay)

    print(f"\nSuccessfully fetched: {len(all_data)}/{len(tickers)}")
    print(f"Failed: {len(failed)} - {failed[:10]}{'...' if len(failed) > 10 else ''}")

    return all_data

def calculate_factor_exposures(all_data):
    """Calculate z-scored factor exposures"""

    # Create DataFrame from fetched data (excluding returns time series)
    records = []
    for d in all_data:
        record = {k: v for k, v in d.items() if k not in ['returns', 'dates']}
        records.append(record)

    df = pd.DataFrame(records)

    # Calculate raw factors
    df['size_raw'] = np.log(df['market_cap'])
    df['momentum_raw'] = df['momentum_60d']
    df['volatility_raw'] = df['volatility_60d']
    df['value_raw'] = 1 / df['price_to_book']  # Book-to-price
    df['quality_raw'] = df['roe']
    df['liquidity_raw'] = np.log(df['avg_volume_60d'])

    # Z-score normalization
    def zscore(series):
        return (series - series.mean()) / series.std()

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
    sectors = df['sector'].unique()

    # Create daily cross-sectional data
    # We'll use the most recent date as our snapshot

    # For proper cross-sectional regression, we need:
    # date, stocknames, capital, ret, [industry dummies], [style factors]

    daily_data = []

    # Get the dates from the first stock with data
    sample_stock = next((d for d in all_data if d.get('returns')), None)
    if not sample_stock:
        raise ValueError("No valid return data found")

    dates = sample_stock['dates']

    for date_idx, date in enumerate(dates):
        for stock_data in all_data:
            if not stock_data.get('returns') or len(stock_data['returns']) <= date_idx:
                continue

            ticker = stock_data['ticker']
            df_row = df[df['ticker'] == ticker]
            if df_row.empty:
                continue

            row = {
                'date': date,
                'stocknames': ticker,
                'capital': df_row['market_cap'].values[0],
                'ret': stock_data['returns'][date_idx] if not np.isnan(stock_data['returns'][date_idx]) else 0
            }

            # Add industry dummies
            stock_sector = df_row['sector'].values[0]
            for sector in sectors:
                row[sector] = 1 if stock_sector == sector else 0

            # Add style factors
            for factor in ['size', 'momentum', 'volatility', 'value', 'quality', 'liquidity']:
                row[factor] = df_row[factor].values[0]

            daily_data.append(row)

    result_df = pd.DataFrame(daily_data)

    # Order columns: date, stocknames, capital, ret, [industries], [styles]
    industry_cols = list(sectors)
    style_cols = ['size', 'momentum', 'volatility', 'value', 'quality', 'liquidity']
    col_order = ['date', 'stocknames', 'capital', 'ret'] + industry_cols + style_cols
    result_df = result_df[col_order]

    return result_df, industry_cols, style_cols


if __name__ == '__main__':
    print("="*60)
    print("S&P 500 Data Fetcher for Cross-Sectional Factor Model")
    print("="*60)

    # Fetch all data
    all_data = fetch_all_sp500(batch_size=10, delay=1.5)

    # Calculate factor exposures
    print("\nCalculating factor exposures...")
    df, all_data = calculate_factor_exposures(all_data)

    # Save raw fundamentals
    raw_cols = ['ticker', 'sector', 'industry', 'market_cap', 'book_value', 'price_to_book',
                'roe', 'trailing_pe', 'forward_pe', 'dividend_yield', 'beta',
                'avg_volume', 'current_price', 'volatility_60d', 'momentum_60d', 'avg_volume_60d']
    available_raw_cols = [c for c in raw_cols if c in df.columns]
    df[available_raw_cols].to_csv('sp500_raw_fundamentals.csv', index=False)
    print(f"Saved raw fundamentals to sp500_raw_fundamentals.csv")

    # Save factor exposures (z-scored)
    factor_cols = ['ticker', 'sector', 'industry', 'market_cap', 'size', 'momentum',
                   'volatility', 'value', 'quality', 'liquidity',
                   'size_raw', 'momentum_raw', 'volatility_raw', 'value_raw', 'quality_raw', 'liquidity_raw']
    available_factor_cols = [c for c in factor_cols if c in df.columns]
    df[available_factor_cols].to_csv('sp500_factor_exposures.csv', index=False)
    print(f"Saved factor exposures to sp500_factor_exposures.csv")

    # Create cross-sectional data for MFM
    print("\nCreating cross-sectional data format...")
    cs_data, industry_cols, style_cols = create_cross_sectional_data(df, all_data)
    cs_data.to_csv('sp500_cross_sectional_data.csv', index=False)
    print(f"Saved cross-sectional data to sp500_cross_sectional_data.csv")
    print(f"  Shape: {cs_data.shape}")
    print(f"  Dates: {cs_data['date'].nunique()}")
    print(f"  Stocks: {cs_data['stocknames'].nunique()}")
    print(f"  Industries: {len(industry_cols)}")
    print(f"  Style factors: {len(style_cols)}")

    print("\nDone!")
