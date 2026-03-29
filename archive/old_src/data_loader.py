<<<<<<< HEAD
"""
Data Loader Module
Handles CSV parsing, price fetching from Yahoo Finance, and Fama-French factor data.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from io import StringIO, BytesIO
import requests
import zipfile
import warnings

warnings.filterwarnings('ignore')


def load_portfolio_csv(csv_path: str) -> pd.DataFrame:
    """
    Load portfolio holdings from CSV file.

    Expected columns: Ticker, Shares, BuyDate, [SellDate]
    SellDate is optional - if blank, position is assumed still held.

    Returns DataFrame with columns: ticker, shares, buy_date, sell_date
    """
    # Auto-detect delimiter (comma or semicolon)
    with open(csv_path, 'r') as f:
        first_line = f.readline()
    delimiter = ';' if ';' in first_line else ','

    df = pd.read_csv(csv_path, delimiter=delimiter)

    # Normalize column names (handle various formats)
    df.columns = df.columns.str.strip().str.lower()

    # Map common column name variations
    column_mapping = {
        'symbol': 'ticker',
        'stock': 'ticker',
        'quantity': 'shares',
        'units': 'shares',
        'buydate': 'buy_date',
        'buy_date': 'buy_date',
        'purchasedate': 'buy_date',
        'purchase_date': 'buy_date',
        'costdate': 'buy_date',
        'selldate': 'sell_date',
        'sell_date': 'sell_date',
        'solddate': 'sell_date',
    }

    df = df.rename(columns=column_mapping)

    # Validate required columns
    required = ['ticker', 'shares', 'buy_date']
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Parse dates
    df['buy_date'] = pd.to_datetime(df['buy_date'])

    if 'sell_date' in df.columns:
        df['sell_date'] = pd.to_datetime(df['sell_date'], errors='coerce')
    else:
        df['sell_date'] = pd.NaT

    # Clean ticker symbols
    df['ticker'] = df['ticker'].str.strip().str.upper()

    # Ensure shares is numeric
    df['shares'] = pd.to_numeric(df['shares'], errors='coerce')

    print(f"Loaded {len(df)} positions from {csv_path}")
    print(f"Tickers: {', '.join(df['ticker'].unique())}")

    return df[['ticker', 'shares', 'buy_date', 'sell_date']]


def fetch_stock_prices(tickers: list, start_date: str, end_date: str = None) -> pd.DataFrame:
    """
    Fetch historical adjusted close prices from Yahoo Finance.

    Args:
        tickers: List of stock ticker symbols
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD), defaults to today

    Returns:
        DataFrame with dates as index and tickers as columns (adjusted close prices)
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    print(f"Fetching price data for {len(tickers)} tickers...")

    # Download all tickers at once for efficiency
    data = yf.download(
        tickers=tickers,
        start=start_date,
        end=end_date,
        progress=False,
        auto_adjust=True  # Use adjusted prices
    )

    # Handle single ticker case (yfinance returns different format)
    if len(tickers) == 1:
        if isinstance(data['Close'], pd.Series):
            prices = data['Close'].to_frame(name=tickers[0])
        else:
            prices = data['Close']
            if prices.columns.nlevels > 1:
                prices.columns = prices.columns.droplevel(0)
    else:
        prices = data['Close']
        if prices.columns.nlevels > 1:
            prices.columns = prices.columns.droplevel(0)

    # Report data quality
    for ticker in tickers:
        if ticker in prices.columns:
            valid_days = prices[ticker].notna().sum()
            print(f"  {ticker}: {valid_days} trading days")
        else:
            print(f"  {ticker}: NO DATA FOUND")

    # Drop columns with no data
    prices = prices.dropna(axis=1, how='all')

    failed_tickers = set(tickers) - set(prices.columns)
    if failed_tickers:
        print(f"WARNING: Could not fetch data for: {failed_tickers}")

    return prices


def calculate_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate daily returns from price data.

    Returns percentage returns (not log returns) for compatibility with factor data.
    """
    returns = prices.pct_change().dropna()
    return returns


def fetch_fama_french_factors(start_date: str, end_date: str = None) -> pd.DataFrame:
    """
    Fetch Fama-French 3 factors + Momentum from Kenneth French's data library.

    Returns DataFrame with columns: Mkt-RF, SMB, HML, Mom, RF
    Values are in decimal form (not percentage).
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    print("Fetching Fama-French factors...")

    # URLs for the factor data (daily)
    ff3_url = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip"
    mom_url = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_CSV.zip"

    try:
        # Download and parse FF3 factors
        ff3_data = _download_french_data(ff3_url)
        mom_data = _download_french_data(mom_url)

        # Merge factors
        factors = ff3_data.join(mom_data, how='inner')

        # Filter date range
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        factors = factors[(factors.index >= start) & (factors.index <= end)]

        # Convert from percentage to decimal
        factors = factors / 100

        print(f"  Loaded {len(factors)} days of factor data")
        print(f"  Factors: {', '.join(factors.columns)}")

        return factors

    except Exception as e:
        print(f"Error fetching Fama-French data: {e}")
        print("Falling back to ETF proxy construction...")
        return _construct_factor_proxies(start_date, end_date)


def _download_french_data(url: str) -> pd.DataFrame:
    """Download and parse data from Kenneth French's website."""
    response = requests.get(url)
    response.raise_for_status()

    # Extract CSV from zip (use BytesIO for binary data)
    with zipfile.ZipFile(BytesIO(response.content)) as z:
        # Get the CSV filename (first file in zip)
        csv_name = [n for n in z.namelist() if n.endswith('.CSV') or n.endswith('.csv')][0]
        with z.open(csv_name) as f:
            content = f.read().decode('latin-1')

    # Parse the CSV - find daily data section
    lines = content.split('\n')
    data_lines = []
    in_data = False

    for line in lines:
        line = line.strip()
        if not line:
            if in_data:
                break  # End of data section
            continue

        parts = line.split(',')
        # Check if first field is a valid date (YYYYMMDD)
        if len(parts) >= 2 and len(parts[0].strip()) == 8:
            try:
                int(parts[0].strip())
                data_lines.append(line)
                in_data = True
            except ValueError:
                if in_data:
                    break

    if not data_lines:
        raise ValueError("Could not find daily data in French data file")

    # Parse collected data
    df = pd.read_csv(StringIO('\n'.join(data_lines)), header=None)

    # First column is date (YYYYMMDD format as integer)
    df[0] = df[0].astype(str).str.strip()
    df[0] = pd.to_datetime(df[0], format='%Y%m%d')
    df = df.set_index(0)

    # Name columns based on file type
    if len(df.columns) == 4:  # FF3 + RF
        df.columns = ['Mkt-RF', 'SMB', 'HML', 'RF']
    elif len(df.columns) == 1:  # Momentum
        df.columns = ['Mom']

    df.index.name = 'Date'
    return df


def _construct_factor_proxies(start_date: str, end_date: str) -> pd.DataFrame:
    """
    Construct factor proxies from ETFs when French data unavailable.

    Market: SPY
    Size (SMB): IWM - SPY
    Value (HML): IWD - VUG (Value - Growth)
    Momentum: Calculated from universe (simplified)
    """
    etfs = ['SPY', 'IWM', 'IWD', 'VUG']
    prices = fetch_stock_prices(etfs, start_date, end_date)
    returns = calculate_returns(prices)

    factors = pd.DataFrame(index=returns.index)
    factors['Mkt-RF'] = returns['SPY']  # Simplified (ignoring RF)
    factors['SMB'] = returns['IWM'] - returns['SPY']  # Small - Large
    factors['HML'] = returns['IWD'] - returns['VUG']  # Value - Growth
    factors['Mom'] = returns['SPY'].rolling(21).mean()  # Simplified momentum proxy
    factors['RF'] = 0.0001  # ~2.5% annual, simplified

    return factors.dropna()


def align_data(stock_returns: pd.DataFrame, factors: pd.DataFrame) -> tuple:
    """
    Align stock returns and factor data to common dates.

    Returns:
        Tuple of (aligned_stock_returns, aligned_factors)
    """
    common_dates = stock_returns.index.intersection(factors.index)

    aligned_returns = stock_returns.loc[common_dates]
    aligned_factors = factors.loc[common_dates]

    print(f"Aligned data: {len(common_dates)} common trading days")

    return aligned_returns, aligned_factors


def get_current_prices(tickers: list) -> pd.Series:
    """Get the most recent prices for a list of tickers."""
    prices = {}
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period='1d')
            if not hist.empty:
                prices[ticker] = hist['Close'].iloc[-1]
        except Exception:
            pass
    return pd.Series(prices)


# Quick test when run directly
if __name__ == "__main__":
    print("Testing data_loader module...")

    # Test price fetching
    test_tickers = ['AAPL', 'MSFT', 'GOOGL']
    prices = fetch_stock_prices(test_tickers, '2024-01-01')
    print(f"\nPrice data shape: {prices.shape}")
    print(prices.tail())

    # Test factor fetching
    factors = fetch_fama_french_factors('2024-01-01')
    print(f"\nFactor data shape: {factors.shape}")
    print(factors.tail())

    # Test alignment
    returns = calculate_returns(prices)
    aligned_ret, aligned_fac = align_data(returns, factors)
    print(f"\nAligned data: {len(aligned_ret)} days")
=======
"""
Data Loader Module
Handles CSV parsing, price fetching from Yahoo Finance, and Fama-French factor data.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from io import StringIO, BytesIO
import requests
import zipfile
import warnings

warnings.filterwarnings('ignore')


def load_portfolio_csv(csv_path: str) -> pd.DataFrame:
    """
    Load portfolio holdings from CSV file.

    Expected columns: Ticker, Shares, BuyDate, [SellDate]
    SellDate is optional - if blank, position is assumed still held.

    Returns DataFrame with columns: ticker, shares, buy_date, sell_date
    """
    # Auto-detect delimiter (comma or semicolon)
    with open(csv_path, 'r') as f:
        first_line = f.readline()
    delimiter = ';' if ';' in first_line else ','

    df = pd.read_csv(csv_path, delimiter=delimiter)

    # Normalize column names (handle various formats)
    df.columns = df.columns.str.strip().str.lower()

    # Map common column name variations
    column_mapping = {
        'symbol': 'ticker',
        'stock': 'ticker',
        'quantity': 'shares',
        'units': 'shares',
        'buydate': 'buy_date',
        'buy_date': 'buy_date',
        'purchasedate': 'buy_date',
        'purchase_date': 'buy_date',
        'costdate': 'buy_date',
        'selldate': 'sell_date',
        'sell_date': 'sell_date',
        'solddate': 'sell_date',
    }

    df = df.rename(columns=column_mapping)

    # Validate required columns
    required = ['ticker', 'shares', 'buy_date']
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Parse dates
    df['buy_date'] = pd.to_datetime(df['buy_date'])

    if 'sell_date' in df.columns:
        df['sell_date'] = pd.to_datetime(df['sell_date'], errors='coerce')
    else:
        df['sell_date'] = pd.NaT

    # Clean ticker symbols
    df['ticker'] = df['ticker'].str.strip().str.upper()

    # Ensure shares is numeric
    df['shares'] = pd.to_numeric(df['shares'], errors='coerce')

    print(f"Loaded {len(df)} positions from {csv_path}")
    print(f"Tickers: {', '.join(df['ticker'].unique())}")

    return df[['ticker', 'shares', 'buy_date', 'sell_date']]


def fetch_stock_prices(tickers: list, start_date: str, end_date: str = None) -> pd.DataFrame:
    """
    Fetch historical adjusted close prices from Yahoo Finance.

    Args:
        tickers: List of stock ticker symbols
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD), defaults to today

    Returns:
        DataFrame with dates as index and tickers as columns (adjusted close prices)
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    print(f"Fetching price data for {len(tickers)} tickers...")

    # Download all tickers at once for efficiency
    data = yf.download(
        tickers=tickers,
        start=start_date,
        end=end_date,
        progress=False,
        auto_adjust=True  # Use adjusted prices
    )

    # Handle single ticker case (yfinance returns different format)
    if len(tickers) == 1:
        if isinstance(data['Close'], pd.Series):
            prices = data['Close'].to_frame(name=tickers[0])
        else:
            prices = data['Close']
            if prices.columns.nlevels > 1:
                prices.columns = prices.columns.droplevel(0)
    else:
        prices = data['Close']
        if prices.columns.nlevels > 1:
            prices.columns = prices.columns.droplevel(0)

    # Report data quality
    for ticker in tickers:
        if ticker in prices.columns:
            valid_days = prices[ticker].notna().sum()
            print(f"  {ticker}: {valid_days} trading days")
        else:
            print(f"  {ticker}: NO DATA FOUND")

    # Drop columns with no data
    prices = prices.dropna(axis=1, how='all')

    failed_tickers = set(tickers) - set(prices.columns)
    if failed_tickers:
        print(f"WARNING: Could not fetch data for: {failed_tickers}")

    return prices


def calculate_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate daily returns from price data.

    Returns percentage returns (not log returns) for compatibility with factor data.
    """
    returns = prices.pct_change().dropna()
    return returns


def fetch_fama_french_factors(start_date: str, end_date: str = None) -> pd.DataFrame:
    """
    Fetch Fama-French 3 factors + Momentum from Kenneth French's data library.

    Returns DataFrame with columns: Mkt-RF, SMB, HML, Mom, RF
    Values are in decimal form (not percentage).
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    print("Fetching Fama-French factors...")

    # URLs for the factor data (daily)
    ff3_url = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip"
    mom_url = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_CSV.zip"

    try:
        # Download and parse FF3 factors
        ff3_data = _download_french_data(ff3_url)
        mom_data = _download_french_data(mom_url)

        # Merge factors
        factors = ff3_data.join(mom_data, how='inner')

        # Filter date range
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        factors = factors[(factors.index >= start) & (factors.index <= end)]

        # Convert from percentage to decimal
        factors = factors / 100

        print(f"  Loaded {len(factors)} days of factor data")
        print(f"  Factors: {', '.join(factors.columns)}")

        return factors

    except Exception as e:
        print(f"Error fetching Fama-French data: {e}")
        print("Falling back to ETF proxy construction...")
        return _construct_factor_proxies(start_date, end_date)


def _download_french_data(url: str) -> pd.DataFrame:
    """Download and parse data from Kenneth French's website."""
    response = requests.get(url)
    response.raise_for_status()

    # Extract CSV from zip (use BytesIO for binary data)
    with zipfile.ZipFile(BytesIO(response.content)) as z:
        # Get the CSV filename (first file in zip)
        csv_name = [n for n in z.namelist() if n.endswith('.CSV') or n.endswith('.csv')][0]
        with z.open(csv_name) as f:
            content = f.read().decode('latin-1')

    # Parse the CSV - find daily data section
    lines = content.split('\n')
    data_lines = []
    in_data = False

    for line in lines:
        line = line.strip()
        if not line:
            if in_data:
                break  # End of data section
            continue

        parts = line.split(',')
        # Check if first field is a valid date (YYYYMMDD)
        if len(parts) >= 2 and len(parts[0].strip()) == 8:
            try:
                int(parts[0].strip())
                data_lines.append(line)
                in_data = True
            except ValueError:
                if in_data:
                    break

    if not data_lines:
        raise ValueError("Could not find daily data in French data file")

    # Parse collected data
    df = pd.read_csv(StringIO('\n'.join(data_lines)), header=None)

    # First column is date (YYYYMMDD format as integer)
    df[0] = df[0].astype(str).str.strip()
    df[0] = pd.to_datetime(df[0], format='%Y%m%d')
    df = df.set_index(0)

    # Name columns based on file type
    if len(df.columns) == 4:  # FF3 + RF
        df.columns = ['Mkt-RF', 'SMB', 'HML', 'RF']
    elif len(df.columns) == 1:  # Momentum
        df.columns = ['Mom']

    df.index.name = 'Date'
    return df


def _construct_factor_proxies(start_date: str, end_date: str) -> pd.DataFrame:
    """
    Construct factor proxies from ETFs when French data unavailable.

    Market: SPY
    Size (SMB): IWM - SPY
    Value (HML): IWD - VUG (Value - Growth)
    Momentum: Calculated from universe (simplified)
    """
    etfs = ['SPY', 'IWM', 'IWD', 'VUG']
    prices = fetch_stock_prices(etfs, start_date, end_date)
    returns = calculate_returns(prices)

    factors = pd.DataFrame(index=returns.index)
    factors['Mkt-RF'] = returns['SPY']  # Simplified (ignoring RF)
    factors['SMB'] = returns['IWM'] - returns['SPY']  # Small - Large
    factors['HML'] = returns['IWD'] - returns['VUG']  # Value - Growth
    factors['Mom'] = returns['SPY'].rolling(21).mean()  # Simplified momentum proxy
    factors['RF'] = 0.0001  # ~2.5% annual, simplified

    return factors.dropna()


def align_data(stock_returns: pd.DataFrame, factors: pd.DataFrame) -> tuple:
    """
    Align stock returns and factor data to common dates.

    Returns:
        Tuple of (aligned_stock_returns, aligned_factors)
    """
    common_dates = stock_returns.index.intersection(factors.index)

    aligned_returns = stock_returns.loc[common_dates]
    aligned_factors = factors.loc[common_dates]

    print(f"Aligned data: {len(common_dates)} common trading days")

    return aligned_returns, aligned_factors


def get_current_prices(tickers: list) -> pd.Series:
    """Get the most recent prices for a list of tickers."""
    prices = {}
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period='1d')
            if not hist.empty:
                prices[ticker] = hist['Close'].iloc[-1]
        except Exception:
            pass
    return pd.Series(prices)


# Quick test when run directly
if __name__ == "__main__":
    print("Testing data_loader module...")

    # Test price fetching
    test_tickers = ['AAPL', 'MSFT', 'GOOGL']
    prices = fetch_stock_prices(test_tickers, '2024-01-01')
    print(f"\nPrice data shape: {prices.shape}")
    print(prices.tail())

    # Test factor fetching
    factors = fetch_fama_french_factors('2024-01-01')
    print(f"\nFactor data shape: {factors.shape}")
    print(factors.tail())

    # Test alignment
    returns = calculate_returns(prices)
    aligned_ret, aligned_fac = align_data(returns, factors)
    print(f"\nAligned data: {len(aligned_ret)} days")
>>>>>>> 19dde37b83c378e4960c4ec0d65165e18eb451c1
