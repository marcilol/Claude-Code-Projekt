# Portfolio X-Ray

## Project Overview
Factor-based portfolio risk analysis using Barra-style cross-sectional regression. Decomposes portfolio risk into systematic (factor-driven) and idiosyncratic (stock-specific) components. Based on Giuseppe Paleologo's "Advanced Portfolio Management."

**Capabilities:**
1. **Risk Decomposition** — factor vs idiosyncratic risk attribution
2. **Factor-Neutral Optimization** — minimize factor exposure while staying close to original weights
3. **Alpha Sizing** — convert expected returns into optimal position sizes with backtesting
4. **Factor Risk Management** — MCFR analysis, risk limits, and trade suggestions
5. **Multi-Market Support** — US (Russell 3000), UK (LSE), Korea (KO), Eurozone (XETRA)
6. **Verification** — 78 automated tests validating math, outputs, and alignment

## Data Source

All market data from **EODHD** ($99/mo All-World plan). No yfinance dependency.

| Table | Content | Key |
|---|---|---|
| `stocks` | Ticker list, GICS sector/group, added/removed dates | (ticker, universe_id) |
| `daily_prices` | OHLCV + shares_out per day | (ticker, date) |
| `fundamentals_quarterly` | Book equity, net income, debt, revenue, etc. | (ticker, report_date) |
| `fundamentals_annual` | EPS, revenue | (ticker, report_date) |
| `analyst_estimates` | Forward EPS, growth YoY (single snapshot) | (ticker, as_of_date) |
| `risk_free_rate` | Daily 13-week T-bill rate | (date) |

Database: `data/db/market_data.db` (SQLite, ~537 MB). Inspect with DB Browser for SQLite.

## Universes

| Universe | Active tickers | Exchange | Currency | Industry scheme |
|---|---:|---|---|---|
| `russell3000` | 2,942 | US | USD | 25 GICS Industry Groups |
| `uk` | 1,319 | LSE | GBP | 11 GICS Sectors |
| `korea` | 1,263 | KO | KRW | 11 GICS Sectors |
| `eurozone` | 361 | XETRA | EUR | 11 GICS Sectors |

Non-US universes (UK, Korea, Eurozone) use 11-sector classification (`--sectors` flag) because EODHD's 25-group GICS classification has quality issues for non-US exchanges (misclassified cross-listings). A larger `us_common` universe (~12.5k tickers, expanded common-stock list built by `scripts/build_us_universe.py`) is loaded in the DB but not yet wired into the factor model.

## Pipeline

```bash
# Data management (incremental, all via EODHD)
py scripts/update_data.py init --universe X --source eodhd       # load ticker list
py scripts/update_data.py classify --universe X --source eodhd   # GICS classification
py scripts/update_data.py prices --universe X --source eodhd     # daily prices + shares_out
py scripts/update_data.py fundamentals --universe X --source eodhd
py scripts/update_data.py estimates --universe X --source eodhd  # analyst estimates
py scripts/update_data.py status                                 # coverage summary

# Factor model
py scripts/fetch_data.py --from-db --universe X [--sectors]      # compute factor exposures
py scripts/run_factor_model.py --universe X                      # cross-sectional regression

# Portfolio analysis (uses russell3000 / barra_* model by default; pass --universe for others)
py scripts/analyze_portfolio.py data/input/portfolios/Own_Portfolio_dated.csv
py scripts/optimize_portfolio.py data/input/portfolios/Own_Portfolio_dated.csv
py scripts/size_positions.py data/input/portfolios/Own_Portfolio_dated.csv
py scripts/manage_risk.py data/input/portfolios/Own_Portfolio_dated.csv

# Validation & EDA
py scripts/explore_data.py                    # 16-check data quality report
py scripts/validate_model.py                  # 8-check model validation
py scripts/validate_alignment_v2.py           # permutation + decomposition tests
py scripts/validate_etf_loadings.py           # 20 ETF factor loading regressions
pytest tests/ -v                              # 78 automated tests
```

## Factor Model

Cross-sectional WLS regression per trading day across the universe:

```
return_i = f_country + f_industry_i + Σ(z_i,k × f_k) + ε_i
```

Weights: √(market cap). R² averages ~30% (US), ~36% (UK), ~30% (Korea), ~30% (Eurozone, preliminary).

### Style Factors (10)

| Factor | Calculation | Interpretation |
|---|---|---|
| Size | log(market cap) | Large (+) vs Small (−) |
| Beta | EWM regression vs market (halflife=63) | High beta (+) vs Low beta (−) |
| Momentum | EWM of lagged excess log returns (skip 21d, halflife=126) | Winners (+) vs Losers (−) |
| Resid Vol | 0.74×DASTD + 0.16×CMRA + 0.10×HSIGMA, orthog vs beta+size | Volatile (+) vs Stable (−) |
| NL Size | Cube of z(size), orthog vs size | Mid-cap tilt (+) |
| BTOP | Book-to-Price | Value (+) vs Growth (−) |
| Liquidity | 0.35×STOM + 0.35×STOQ + 0.30×STOA, orthog vs size | Liquid (+) vs Illiquid (−) |
| Earn Yield | 0.656×CETOP + 0.344×ETOP (partial, no EPFWD) | High yield (+) vs Low (−) |
| Growth | 0.338×EGRO + 0.662×SGRO (partial, no analyst forecasts) | High growth (+) vs Low (−) |
| Leverage | 0.38×MLEV + 0.35×DTOA + 0.27×BLEV | High leverage (+) vs Low (−) |

### Model Adjustments
1. **WLS**: √(market cap) weights
2. **Industry Neutrality**: constraint handling multicollinearity with market factor
3. **Newey-West**: autocorrelation adjustment (q=2, halflife=252)
4. **Eigenfactor Risk Adjustment**: Monte Carlo simulation (scale=1.4)
5. **Volatility Regime Adjustment**: adaptive halflife=42

### Data Quality Filters
- Zero/negative prices filtered before return computation
- Daily log returns capped at ±25%
- Stale data (>5 calendar days behind) excluded
- Penny stocks (median close < $1) excluded
- Raw values winsorized at ±3.5σ BEFORE z-scoring
- Rows with NaN beta/momentum/size dropped from regression

## Model Outputs

Per universe, saved to `data/model/`:

**Naming asymmetry — important:** US uses two prefixes for legacy reasons (`russell3000_*` for the panel data, `barra_*` for the regression outputs). UK / Korea / Eurozone use one prefix (`{universe}_*`) for all six files. Worth normalizing to `russell3000_*` everywhere when there's a pause in development.

| File | Content |
|---|---|
| `{universe}_cross_sectional_data.csv` | Daily stock × factor exposure panel |
| `{universe}_factor_exposures_historical.csv` | Raw + z-scored factor values |
| `barra_factor_returns.csv` (US) / `{universe}_factor_returns.csv` | Daily factor returns |
| `barra_factor_covariance.csv` / `{universe}_factor_covariance.csv` | Adjusted covariance matrix (DAILY units — ×252 to annualize) |
| `barra_factor_statistics.csv` / `{universe}_factor_statistics.csv` | Factor mean, vol, t-stat |
| `barra_r2.csv` / `{universe}_r2.csv` | Daily R² |

## Sharing & Reproducibility

The repo is set up so collaborators only need **one large artifact**: `data/db/market_data.db` (~537 MB SQLite). Everything in `data/model/` is derived and gitignored.

**Reproduce a market from a shared DB:**
```bash
py scripts/fetch_data.py --from-db --universe X [--sectors]
py scripts/run_factor_model.py --universe X
```

**What to share out-of-band (Google Drive / R2 / etc.):**
- `data/db/market_data.db` — required, only file you must share
- (Optional) the small annualized model outputs per market (`*_factor_covariance.csv`, `*_factor_returns.csv`, `*_factor_statistics.csv`, `*_r2.csv` — all <1 MB) so collaborators can run portfolio analysis without rebuilding the model.

**Do NOT share** (gitignored, reproducible from DB):
- `*_cross_sectional_data.csv`, `*_factor_exposures_historical.csv` (~720 MB across 4 markets)
- `data/eda/` (HTML reports, regenerable)
- `data/model/russell3000_raw_data.pkl` (intermediate cache)

## Portfolio CSV Format

Comma or semicolon delimited (auto-detected). Column names case-insensitive.

**Required:** `ticker`, `shares`
**Optional:** `costdate`/`BuyDate`, `sell_date`

## Risk Decomposition

```
Total Variance = Factor Variance + Idiosyncratic Variance
Factor Variance = b' × Ω × b
Idio Variance   = Σ(w_i² × σ_idio_i²)
```

- **>50% idiosyncratic** = stock-picking portfolio
- **<50% idiosyncratic** = factor-driven portfolio

## Testing

78 tests across 5 phases:

| Phase | Tests | What |
|---|---:|---|
| Sanity Checks | 11 | Z-score conventions, R² range, covariance properties, factor count |
| Unit Tests | 34 | Z-scoring, factor variance, MCFR, sizing methods, idio vol, portfolio loading |
| Regression | 4 | Current outputs vs baselines (1% tolerance) |
| Benchmarks | 6 | SPY regression, beta-market correlation, covariance symmetry |
| Model Validation | 12 | Autocorrelation, VIF, CAPM lift, R² distribution, known stock loadings, alignment, permutation |

## Known Limitations
- **Survivorship bias**: historical regressions use today's index membership, not point-in-time. EODHD doesn't provide historical Russell constituents.
- **Partial factors**: Earnings Yield missing EPFWD (68% of Barra weight), Growth missing EGRLF/EGRSF (29%). Would need recurring estimate fetches.
- **Non-US classification quality**: EODHD's GICS group classification has issues for LSE/KO (cross-listings misclassified). Use `--sectors` for non-US markets.
- **Factor covariance in DAILY units** — multiply by 252 to annualize variance.
- **Idiosyncratic variance already annualized**: (std × √252)².
- **EODHD gaps**: Japan and India not available. Daily API limit: 100,000 calls.
