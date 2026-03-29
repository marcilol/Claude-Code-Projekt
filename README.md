# Portfolio X-Ray

## Project Overview
Python tool for factor-based portfolio risk analysis using MSCI Barra-style cross-sectional regression. Decomposes portfolio risk into systematic (factor-driven) and idiosyncratic (stock-specific) components based on Giuseppe Paleologo's "Advanced Portfolio Management" methodology.

**Key Capabilities:**
1. **Risk Decomposition** - Factor vs idiosyncratic risk attribution
2. **Factor-Neutral Optimization** - Minimize factor exposure while staying close to original weights
3. **Alpha Sizing** - Convert expected returns into optimal position sizes with backtesting
4. **Factor Risk Management** - MCFR analysis, risk limits, and trade suggestions (Chapter 7)

## Key Commands

```bash
# Step 1: Fetch historical data (run once, takes ~60 min)
python scripts/fetch_data.py
# Or recompute factors from saved raw data (no re-fetch):
python scripts/fetch_data.py --compute-only

# Step 2: Run Barra factor model (run after data fetch)
python scripts/run_factor_model.py

# Step 3: Analyze a portfolio
python scripts/analyze_portfolio.py data/input/portfolios/Own_Portfolio_dated.csv

# Step 4: Optimize for factor neutrality (optional)
python scripts/optimize_portfolio.py data/input/portfolios/Own_Portfolio_dated.csv

# Step 5: Alpha sizing with backtest (Chapter 6)
python scripts/size_positions.py data/input/portfolios/Own_Portfolio_dated.csv
python scripts/size_positions.py data/input/portfolios/Own_Portfolio_dated.csv --decision=2025-07-01 --end=2025-12-31 --gmv=100000

# Step 6: Compare sizing methods across multiple portfolios
python scripts/compare_sizing_methods.py

# Step 7: Factor risk management (Chapter 7)
python scripts/manage_risk.py data/input/portfolios/Own_Portfolio_dated.csv
python scripts/manage_risk.py data/input/portfolios/Own_Portfolio_dated.csv --limits
python scripts/manage_risk.py data/input/portfolios/Own_Portfolio_dated.csv --limits --max-stock=15 --min-idio=60
```

## File Structure

```
portfolio-xray/
├── CLAUDE.md
├── requirements.txt
├── Chapter 6 Summary - Alpha Sizing Heuristics.pdf  # Reference material
├── scripts/
│   ├── fetch_data.py              # Fetches 2y data + computes factors (--compute-only)
│   ├── run_factor_model.py        # Runs Barra cross-sectional regression
│   ├── analyze_portfolio.py       # Portfolio risk decomposition
│   ├── optimize_portfolio.py      # Factor-neutral weight optimization
│   ├── size_positions.py          # Alpha sizing with backtest (Chapter 6)
│   ├── compare_sizing_methods.py  # Multi-portfolio sizing comparison + charts
│   └── manage_risk.py             # Factor risk management (Chapter 7)
├── data/
│   ├── input/
│   │   ├── russell_constituents.csv  # Russell 3000 tickers + sectors
│   │   └── portfolios/               # Portfolio CSV files
│   │       ├── Own_Portfolio_dated.csv
│   │       ├── Dynamic_AI.csv
│   │       ├── Robotics.csv
│   │       ├── Fiscal_Primacy.csv
│   │       ├── Small_Themes.csv
│   │       └── ...
│   └── model/                        # Model outputs
│       ├── russell3000_factor_exposures_historical.csv  # Stock factor data (185 MB)
│       ├── russell3000_cross_sectional_data.csv         # Barra-format data (120 MB)
│       ├── barra_factor_returns.csv           # Daily factor returns (22 factors)
│       ├── barra_factor_covariance.csv        # Adjusted 22x22 covariance matrix
│       ├── barra_factor_statistics.csv        # Factor mean, vol, t-stat
│       ├── barra_r2.csv                       # Model R-squared by date
│       ├── sizing_methods_comparison.png      # Sharpe ratio chart
│       └── sizing_methods_returns.png         # Returns chart
├── reference/
│   ├── Barra-master/         # Reference Barra implementation
│   └── Quantastic/           # Original R project
└── archive/                  # Old/deprecated files
```

## Portfolio CSV Format

Supports comma or semicolon delimited. Auto-detected.

**Required columns:** `ticker`, `shares`

**Optional:** `costdate`/`BuyDate`, `sell_date`

Example:
```csv
Ticker;Shares;BuyDate
AAPL;100;2024-01-15
MSFT;50;2024-02-20
```

## Factor Model

### Barra Cross-Sectional Regression
For each day, regress stock returns against factor exposures:
```
r_i,t = f_market + f_industry + sum(beta_i,k * f_k,t) + epsilon_i,t

r = stock return
beta = factor exposures (known from fundamentals, z-scored)
f = factor returns (estimated via cross-sectional regression)
epsilon = idiosyncratic return (stock-specific)
```

### Style Factors (10 factors, CNE5-style)
| Factor | Calculation | Interpretation |
|--------|-------------|----------------|
| Size | LNCAP = log(market cap) | Large (+) vs Small (-) |
| Beta | EWM regression vs market (hl=63) | High beta (+) vs Low beta (-) |
| Momentum | EWM of lagged excess log returns (skip 21d, hl=126) | Winners (+) vs Losers (-) |
| Resid Vol | 0.74*DASTD + 0.16*CMRA + 0.10*HSIGMA, orthog vs beta+size | High resid vol (+) vs Low (-) |
| NL Size | Cube of z(size), orthog vs size | Mid-cap tilt (+) |
| BTOP | Book-to-Price | Value (+) vs Growth (-) |
| Liquidity | 0.35*STOM + 0.35*STOQ + 0.30*STOA, orthog vs size | Liquid (+) vs Illiquid (-) |
| Earn Yield | 0.656*CETOP + 0.344*ETOP (partial, no EPFWD) | High yield (+) vs Low (-) |
| Growth | 0.338*EGRO + 0.662*SGRO (partial, no analyst forecasts) | High growth (+) vs Low (-) |
| Leverage | 0.38*MLEV + 0.35*DTOA + 0.27*BLEV | High leverage (+) vs Low (-) |

### Industry Factors (11 GICS sectors)
One-hot encoded dummy variables. Factor returns estimated via regression represent "pure" industry effect after controlling for style factors.

### Model Adjustments (MSCI-style)
1. **WLS Regression**: sqrt(market cap) weights
2. **Industry Neutrality**: Constraint to handle multicollinearity with market factor
3. **Newey-West**: Autocorrelation adjustment (q=2, halflife=252)
4. **Eigenfactor Risk Adjustment**: Monte Carlo simulation (scale=1.4)
5. **Volatility Regime Adjustment**: Adaptive halflife=42

### Estimated Factor Returns (Feb 2025 - Jan 2026, 10-factor CNE5 model, R²=13.0%)
| Factor | Ann. Return | Ann. Vol | t-stat |
|--------|-------------|----------|--------|
| Country (Market) | +26.6% | 19.4% | 1.35 |
| Earn Yield | +7.4% | 2.2% | 3.38 |
| BTOP | -7.5% | 2.4% | -3.07 |
| Beta | +25.9% | 9.0% | 2.84 |
| Resid Vol | +37.0% | 14.0% | 2.59 |
| Utilities | +26.5% | 13.7% | 1.91 |
| Industrials | +11.0% | 6.4% | 1.68 |
| NL Size | +6.6% | 3.9% | 1.65 |
| Materials | +15.1% | 10.6% | 1.40 |
| Leverage | -3.4% | 2.4% | -1.40 |
| Growth | -3.6% | 2.9% | -1.22 |
| Info Technology | -8.7% | 7.9% | -1.08 |
| Liquidity | -6.7% | 6.7% | -0.99 |

## Key Metrics

### Risk Decomposition
- **Factor Volatility**: Risk from systematic factor exposure
- **Idiosyncratic Volatility**: Stock-specific risk (diversifiable)
- **Total Volatility**: sqrt(factor_var + idio_var)

### Interpretation
- **>50% idiosyncratic** = Good stock-picking portfolio
- **<50% idiosyncratic** = Heavily exposed to factor risk

### Portfolio Factor Exposure
Weighted average of stock factor z-scores. Target: close to 0 for factor-neutral.

## Data Sources
- **Stock prices/fundamentals**: Yahoo Finance (`yfinance`)
- **Russell 3000 constituents**: `data/input/russell_constituents.csv`
- **Factor model**: ~1 year of point-in-time data (Feb 2025 - Jan 2026), 244 trading days
- **Coverage**: ~2,541 stocks per day (98% of Russell 3000)
- **Raw data cache**: `data/model/russell3000_raw_data.pkl` (use `--compute-only` to iterate on factors)

## Factor-Neutral Optimization

The optimizer uses quadratic programming to minimize factor variance:
```
minimize: w' * B * F * B' * w + lambda * ||w - w0||^2

subject to:
  - sum(w) = 1 (fully invested)
  - w >= 0 (long-only)
```

Key insight: Cannot achieve factor neutrality with long-only constraint if all stocks share similar factor profiles. Solutions:
1. Add stocks with opposite factor characteristics
2. Use shorting or factor hedges (ETFs)
3. Accept the factor tilt if intentional

## Alpha Sizing (Chapter 6)

Based on Paleologo's "Advanced Portfolio Management" Chapter 6.

### Core Question
How do you convert expected returns (alphas) into dollar positions that maximize risk-adjusted returns?

### Four Sizing Methods (Long-Only)

| Method | Formula | Description |
|--------|---------|-------------|
| **Proportional** | NMV = k * alpha | Simple, empirically best |
| Risk Parity | NMV = k * alpha / sigma | Scales down high-vol positions |
| Mean-Variance | NMV = k * alpha / sigma^2 | Classic Markowitz, penalizes vol heavily |
| Shrunk MV | NMV = k * alpha / (p*sigma^2 + (1-p)*sigma_sector^2) | Shrinks toward sector vol (p=0.75) |

### Idiosyncratic Volatility Calculation
Computed from Barra model residuals (not total volatility):
```
epsilon_i,t = r_i,t - f_market - f_industry - sum(beta_i,k * f_k,t)
sigma_idio = std(epsilon) * sqrt(252)
```

This isolates stock-specific risk from factor risk.

### Key Finding: Simple Beats Complex

**Proportional sizing empirically outperforms sophisticated MV methods** because:
1. Estimation error in volatility hurts MV-based approaches
2. Low-vol stocks get oversized in MV, amplifying mistakes
3. High-vol stocks that MV penalizes often perform well

### Backtest Results (Jul-Dec 2025, 30% expected return assumption)

| Portfolio | Proportional | Risk Parity | Mean-Var | Shrunk MV |
|-----------|-------------|-------------|----------|-----------|
| Own Portfolio | **2.99** | 2.85 | 2.63 | 2.65 |
| Dynamic AI | **2.77** | 2.59 | 2.45 | 2.46 |
| Robotics | **1.88** | 1.78 | 1.64 | 1.64 |
| Fiscal Primacy | 3.65 | **3.72** | 3.65 | 3.64 |
| Small Themes | **1.92** | 1.24 | 0.69 | 0.73 |

*Values shown are Sharpe ratios. Bold = best method for that portfolio.*

### Summary Statistics
| Method | Avg Sharpe | Avg Return | # Wins |
|--------|------------|------------|--------|
| **Proportional** | **2.64** | **46.2%** | **4/5** |
| Risk Parity | 2.44 | 38.2% | 1/5 |
| Mean-Variance | 2.21 | 32.5% | 0/5 |
| Shrunk MV | 2.22 | 32.7% | 0/5 |

### Usage
```bash
# Single portfolio analysis
python scripts/size_positions.py portfolio.csv --decision=2025-07-01 --end=2025-12-31 --gmv=100000

# Multi-portfolio comparison with charts
python scripts/compare_sizing_methods.py
```

Output charts saved to:
- `data/model/sizing_methods_comparison.png` (Sharpe ratios)
- `data/model/sizing_methods_returns.png` (Total returns)

## Factor Risk Management (Chapter 7)

Based on Paleologo's "Advanced Portfolio Management" Chapter 7.

### Core Concept
Manage portfolio risk by decomposing it into factor and idiosyncratic components, identifying which positions contribute most to factor risk via MCFR, and checking against risk limits.

### Key Metric: MCFR (Marginal Contribution to Factor Risk)
```
b = B' * w              (portfolio factor exposure)
MCFR_i = [B * Ω_f * b]_i / √(b' * Ω_f * b)
```
MCFR measures how much each position contributes to the portfolio's factor risk. Positive MCFR = adds to factor risk; negative = hedges it.

### Output Tables
1. **Risk Decomposition** - Hierarchical breakdown: Total > Idio/Factor > Market/Style/Industry > individual factors. Shows %Var, $Exposure, $Vol, MCFR per factor.
2. **Position Risk** - Per-stock NMV, %GMV, idio vol, MCFR, top factor exposure, breach flags.
3. **Limit Breach Summary** - Checks %idio variance (min 75%), max single stock (10%), HHI concentration.
4. **Suggested Trades** - MCFR-ranked reduction recommendations when limits are breached.

### Default Risk Limits
| Limit | Default | Rationale |
|-------|---------|-----------|
| Min % Idio Variance | 75% | Ensure stock-picking dominates |
| Max Single Stock | 10% | Concentration risk (relaxed from book's 4% for small portfolios) |
| HHI | 2x equal-weight | Prevent excessive concentration |

### Usage
```bash
# Basic risk analysis (Tables 1-2)
python scripts/manage_risk.py data/input/portfolios/Own_Portfolio_dated.csv

# With limit checking (Tables 1-4)
python scripts/manage_risk.py data/input/portfolios/Own_Portfolio_dated.csv --limits

# Custom limits
python scripts/manage_risk.py portfolio.csv --limits --max-stock=15 --min-idio=60
```

## Notes
- Data fetch takes ~60 minutes for full Russell 3000
- Raw data cached to `data/model/russell3000_raw_data.pkl` (80 MB) — use `--compute-only` to iterate on factor definitions without re-fetching
- Model R-squared averages ~11.75% (19-factor model, Feb 2025 - Jan 2026, 246 trading days)
- Some portfolio stocks may not be in Russell 3000 (handled gracefully)
- AVIO ticker is delisted (skipped automatically)
- Factor covariance is in DAILY units — multiply by 252 to annualize variance
- Idiosyncratic variance is already annualized: (std * sqrt(252))^2

---

## Current Status (Feb 2026)

The model implements **10 CNE5-style style factors** + 11 GICS industry factors + 1 Country factor = **22 total factors**.

### CNE5 Implementation Summary
All factor descriptors follow the MSCI Barra CNE5 methodology (see `CNE5_Model_Technical_Summary.md`):
- **Excess log returns** used for momentum (RSTR) and CMRA
- **Exponential weighting** for Beta (hl=63), Momentum (hl=126), DASTD (hl=42), HSIGMA (hl=63)
- **Composite descriptors**: ResidVol, Liquidity, Earnings Yield, Growth, Leverage built from z-scored sub-descriptors
- **Orthogonalization**: ResidVol vs (beta, size), NL Size vs size, Liquidity vs size
- **Standardization**: Cap-weighted mean=0, equal-weighted std=1
- **Risk-free rate**: ^IRX (13-week T-bill), stored in pickle with raw data

### Partial Factors (data limitations)
Without a paid API for analyst consensus forecasts:
- **Earnings Yield**: Uses CETOP + ETOP only (no EPFWD, 32% of original weight)
- **Growth**: Uses EGRO + SGRO only (no EGRLF/EGRSF, 71% of original weight)

### Optional Enhancement: Paid data API
Adding Financial Modeling Prep (~$20/month) would provide analyst consensus forecasts, enabling:
- EPFWD (68% weight in Earnings Yield — currently missing)
- EGRLF, EGRSF (29% weight in Growth — currently missing)
