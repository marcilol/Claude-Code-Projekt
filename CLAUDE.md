# Portfolio X-Ray

## Project Overview
Python tool for factor-based portfolio risk analysis using MSCI Barra-style cross-sectional regression. Decomposes portfolio risk into systematic (factor-driven) and idiosyncratic (stock-specific) components based on Giuseppe Paleologo's "Advanced Portfolio Management" methodology.

**Key Capabilities:**
1. **Risk Decomposition** - Factor vs idiosyncratic risk attribution
2. **Factor-Neutral Optimization** - Minimize factor exposure while staying close to original weights
3. **Alpha Sizing** - Convert expected returns into optimal position sizes with backtesting
4. **Factor Risk Management** - MCFR analysis, risk limits, and trade suggestions (Chapter 7)
5. **Verification & Testing** - 67 automated tests validating model math and outputs

## Key Commands

```bash
# Step 1: Fetch historical data (run once, takes ~60 min)
python scripts/fetch_data.py
python scripts/fetch_data.py --compute-only   # recompute factors from cached raw data

# Step 2: Run Barra factor model
python scripts/run_factor_model.py

# Step 3: Analyze a portfolio
python scripts/analyze_portfolio.py data/input/portfolios/Own_Portfolio_dated.csv

# Step 4: Optimize for factor neutrality
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

# Step 8: Run verification tests
pytest tests/ -v
```

## File Structure

```
portfolio-xray/
├── CLAUDE.md
├── requirements.txt
├── scripts/
│   ├── fetch_data.py              # Fetches 2y data + computes factors (--compute-only)
│   ├── run_factor_model.py        # Runs Barra cross-sectional regression
│   ├── analyze_portfolio.py       # Portfolio risk decomposition
│   ├── optimize_portfolio.py      # Factor-neutral weight optimization
│   ├── size_positions.py          # Alpha sizing with backtest (Chapter 6)
│   ├── compare_sizing_methods.py  # Multi-portfolio sizing comparison + charts
│   └── manage_risk.py             # Factor risk management (Chapter 7)
├── tests/
│   ├── conftest.py                # Shared fixtures, import helpers, constants
│   ├── test_sanity_checks.py      # Phase 1: Model output validation
│   ├── test_unit_zscore.py        # Phase 2: Z-scoring math
│   ├── test_unit_factor_risk.py   # Phase 2: Factor variance (b'Ωb)
│   ├── test_unit_mcfr.py          # Phase 2: Marginal contribution to factor risk
│   ├── test_unit_sizing.py        # Phase 2: All 4 sizing methods
│   ├── test_unit_idio_vol.py      # Phase 2: Idiosyncratic volatility
│   ├── test_unit_portfolio.py     # Phase 2: Portfolio loading, weight calc
│   ├── test_regression.py         # Phase 3: Baseline comparison (1% tolerance)
│   ├── test_benchmarks.py         # Phase 4: SPY regression, external checks
│   ├── baselines/                 # Saved model outputs for regression tests
│   └── TEST_REPORT.md             # Detailed test descriptions and results
├── data/
│   ├── input/
│   │   ├── russell_constituents.csv  # Russell 3000 tickers + sectors
│   │   └── portfolios/               # Portfolio CSV files
│   └── model/                        # Model outputs
│       ├── russell3000_factor_exposures_historical.csv  # Stock factor data (185 MB)
│       ├── russell3000_cross_sectional_data.csv         # Barra-format data (120 MB)
│       ├── barra_factor_returns.csv           # Daily factor returns (22 factors)
│       ├── barra_factor_covariance.csv        # Adjusted 22×22 covariance matrix
│       ├── barra_factor_statistics.csv        # Factor mean, vol, t-stat
│       └── barra_r2.csv                       # Model R² by date
├── reference/                     # Reference implementations (Barra, Quantastic)
└── archive/                       # Old/deprecated files
```

## Portfolio CSV Format

Supports comma or semicolon delimited (auto-detected). Column names are case-insensitive.

**Required columns:** `ticker`, `shares`
**Optional:** `costdate`/`BuyDate`, `sell_date`

## Factor Model

### How It Works
Each trading day, a cross-sectional regression across ~2,500 Russell 3000 stocks estimates how much each factor was rewarded:

```
return_i = f_country + f_industry_i + Σ(z_i,k × f_k) + ε_i

z_i,k = stock i's z-scored exposure to factor k (known input)
f_k   = factor k's return that day (estimated by OLS)
ε_i   = stock-specific residual
```

WLS regression with √(market cap) weights. R² averages ~28% cross-sectionally (range 3%–89%).

### 22 Factors

**1 Market (Country)** + **11 GICS Industry sectors** + **10 CNE5-style Style factors:**

| Factor | Calculation | Interpretation |
|--------|-------------|----------------|
| Size | log(market cap) | Large (+) vs Small (−) |
| Beta | EWM regression vs market (hl=63) | High beta (+) vs Low beta (−) |
| Momentum | EWM of lagged excess log returns (skip 21d, hl=126) | Winners (+) vs Losers (−) |
| Resid Vol | 0.74×DASTD + 0.16×CMRA + 0.10×HSIGMA, orthog vs beta+size | Volatile (+) vs Stable (−) |
| NL Size | Cube of z(size), orthog vs size | Mid-cap tilt (+) |
| BTOP | Book-to-Price | Value (+) vs Growth (−) |
| Liquidity | 0.35×STOM + 0.35×STOQ + 0.30×STOA, orthog vs size | Liquid (+) vs Illiquid (−) |
| Earn Yield | 0.656×CETOP + 0.344×ETOP (partial, no EPFWD) | High yield (+) vs Low (−) |
| Growth | 0.338×EGRO + 0.662×SGRO (partial, no analyst forecasts) | High growth (+) vs Low (−) |
| Leverage | 0.38×MLEV + 0.35×DTOA + 0.27×BLEV | High leverage (+) vs Low (−) |

**Z-scoring convention:** Cap-weighted mean = 0, equal-weighted std = 1 per factor per date. Orthogonalized factors (residvol, nlsize, liquidity) may have CW mean up to ±0.7 after orthogonalization.

### Model Adjustments (MSCI-style)
1. **WLS Regression**: √(market cap) weights
2. **Industry Neutrality**: Constraint to handle multicollinearity with market factor
3. **Newey-West**: Autocorrelation adjustment (q=2, halflife=252)
4. **Eigenfactor Risk Adjustment**: Monte Carlo simulation (scale=1.4)
5. **Volatility Regime Adjustment**: Adaptive halflife=42

## Risk Decomposition

```
Total Variance = Factor Variance + Idiosyncratic Variance
Factor Variance = b' × Ω × b        (b = portfolio factor exposures, Ω = factor covariance)
Idio Variance   = Σ(w_i² × σ_idio_i²)
```

- **>50% idiosyncratic** = stock-picking portfolio (good diversification of factor risk)
- **<50% idiosyncratic** = factor-driven portfolio (exposed to systematic risk)

## Alpha Sizing (Chapter 6)

| Method | Formula | Description |
|--------|---------|-------------|
| **Proportional** | NMV = κ × α | Simple, empirically best |
| Risk Parity | NMV = κ × α / σ | Scales down high-vol positions |
| Mean-Variance | NMV = κ × α / σ² | Classic Markowitz, penalizes vol heavily |
| Shrunk MV | NMV = κ × α / (p×σ² + (1−p)×σ²_sector) | Shrinks toward sector vol (p=0.75) |

**Key finding:** Proportional sizing empirically outperforms MV methods (avg Sharpe 2.64 vs 2.21, wins 4/5 portfolios) because estimation error in volatility hurts the more complex methods.

## Factor Risk Management (Chapter 7)

**MCFR (Marginal Contribution to Factor Risk):**
```
MCFR_i = [B × Ω × b]_i / √(b' × Ω × b)
```
Positive MCFR = position adds to factor risk. Negative = hedges it.

**Default risk limits:** Min 75% idio variance, max 10% single stock, HHI < 2× equal-weight.

## Verification & Testing

67 automated tests across 4 phases. Run with `pytest tests/ -v`. See `tests/TEST_REPORT.md` for full details.

| Phase | Tests | What it validates |
|-------|-------|-------------------|
| 1. Sanity Checks | 11 | Model output CSVs: z-score conventions, no NaN, R² range 2–95%, covariance positive definite, 22 factor names consistent across files |
| 2. Unit Tests | 34 | Core math against hand-calculated answers: z-scoring, factor variance (b'Ωb), MCFR, all 4 sizing methods, idiosyncratic volatility, portfolio loading |
| 3. Regression | 4 | Current outputs vs saved baselines within 1% tolerance (catches unintended drift after code changes) |
| 4. Benchmarks | 7 | SPY returns regressed on factor returns (R² = 99.1%), beta-market correlation, covariance symmetry, low autocorrelation |

**Key validation:** The factor model explains 99.1% of SPY's daily return variance (Country factor β = 1.04, industry coefficients match S&P 500 sector weights). Residual vol is only 2% annualized vs SPY's 20% total vol.

## Known Quirks
- **Date convention:** Factor model labels returns 1 business day ahead of yfinance. Factor date T = yfinance date T−1. The returns themselves are correct (0.99 correlation after alignment). Any code joining factor dates with external price data must shift by 1 day.
- **Factor covariance is in DAILY units** — multiply by 252 to annualize variance.
- **Idiosyncratic variance is already annualized:** (std × √252)².
- **Beta warmup:** Beta needs ~252 days of prior data. The first ~30% of dates in the dataset have beta z-scores of 0.
- **Partial factors:** Earnings Yield missing EPFWD (68% of CNE5 weight), Growth missing EGRLF/EGRSF (29% of weight) — would require a paid data API (~$20/month via Financial Modeling Prep).

## Data Sources
- **Stock prices/fundamentals**: Yahoo Finance (`yfinance`)
- **Russell 3000 constituents**: `data/input/russell_constituents.csv`
- **Sample period**: Feb 2025 – Jan 2026, 244 trading days, ~2,541 stocks/day
- **Raw data cache**: `data/model/russell3000_raw_data.pkl` (80 MB)
