# Portfolio X-Ray

## Project Overview
Factor-based portfolio risk analysis using Barra-style cross-sectional regression. Decomposes portfolio risk into systematic (factor-driven) and idiosyncratic (stock-specific) components. Based on Giuseppe Paleologo's "Advanced Portfolio Management."

**Capabilities:**
1. **Risk Decomposition** — factor vs idiosyncratic risk attribution
2. **Factor-Neutral Optimization** — minimize factor exposure while staying close to original weights
3. **Alpha Sizing** — convert expected returns into optimal position sizes with backtesting
4. **Factor Risk Management** — MCFR analysis, risk limits, and trade suggestions
5. **Multi-Market Support** — US (Russell 3000 + 20-yr S&P 500), UK (LSE), Korea (KO), Eurozone (XETRA), China (SHE), Taiwan (TW)
6. **Web UI** — FastAPI backend + Vite/React frontend at `localhost:5173` for factor/basket performance, z-score table, rotation quadrant, portfolio analysis
7. **Verification** — 78 automated tests validating math, outputs, and alignment

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

Database: `data/db/market_data.db` (SQLite, ~1.9 GB). Inspect with DB Browser for SQLite.

## Universes

| Universe | Tickers | Exchange | Currency | Industry scheme | Price coverage |
|---|---:|---|---|---|---|
| `russell3000` | 2,942 | US | USD | 25 GICS Industry Groups | ~4 yr |
| `sp500_hist` | 947 | US | USD | 25 GICS Industry Groups | **20 yr, survivorship-bias-free** |
| `uk` | 1,319 | LSE | GBP | 11 GICS Sectors | ~4 yr |
| `korea` | 1,263 | KO | KRW | 11 GICS Sectors | ~4 yr |
| `eurozone` | 361 | XETRA | EUR | 11 GICS Sectors | ~4 yr |
| `china_she` | ~1,000 | SHE | CNY | 11 GICS Sectors (consolidated from EODHD `Industry`) | ~4 yr |
| `taiwan_tw` | ~1,100 | TW | TWD | 11 GICS Sectors | ~4 yr |

Non-US universes (UK, Korea, Eurozone, China, Taiwan) use 11-sector classification (`--sectors` flag) because EODHD's 25-group GICS classification has quality issues for non-US exchanges (misclassified cross-listings). A larger `us_common` universe (~12.5k tickers, expanded common-stock list built by `scripts/build_us_universe.py`) is loaded in the DB but not yet wired into the factor model — and is mostly *delisted-only* leftover (very few live names overlap with `russell3000`); the active arm of `build_us_universe.py` did not land cleanly. Use `sp500_hist` instead for survivorship-bias-free US analysis.

### `sp500_hist` — survivorship-bias-free 20-yr panel

Built by `scripts/build_sp500_historical.py` from the [fja05680/sp500](https://github.com/fja05680/sp500) GitHub repo (point-in-time S&P 500 constituent lists since 1996). Combines two CSVs:
- Original CSV (1996-2019) — uses `-YYYYMM` suffixes for delisted entries; great for clean resolution.
- Newer CSV (1996-2026) — bare tickers; used only for the post-2019 tail to backfill TSLA, META, ABNB, COIN, CRWD, PLTR, etc.

Resolution to EODHD symbols handles three cases: (1) bare current ticker → EODHD active list; (2) `XYZ-YYYYMM` suffixed → tries `XYZ_old`, `XYZ_old1..5`, `XYZ-OLD` first (handles symbol reuse like BSC → BSC_old for Bear Stearns), then bare `XYZ` in delisted (e.g. LEH); (3) manual overrides for fja-vs-EODHD naming mismatches (`LEHMQ-201203 → LEH`, `MTLQQ-201103 → GM_old`, `ABKFQ-201304 → ABK`, `RSHCQ-201510 → RSH`, `RE → EG`, `ATGE → DV`, `FB → META`, `CDAY → DAY`).

Includes 2008-crisis casualties (LEH, BSC_old, GM_old, WB_old1, ABK, AGN_old, XL_old, WCG, RSH) with verified end-of-life dates matching real history. Cache files: `data/db/_sp500_hist_resolved.json` (947 fja→eodhd mappings), `data/db/_sp500_hist_unresolved.json`, `data/db/_eodhd_us_active.json`, `data/db/_eodhd_us_delisted.json`. Source CSVs cached at `data/input/sp500_historical_components.csv` and `data/input/sp500_historical_components_2026.csv`.

**⚠️ Coverage threshold gotcha:** for the full 20-yr range, fetch with `--min-coverage 0.4`, not the default `0.80`. Because sp500_hist is survivorship-bias-free, only ~500 of the 947 historical members are alive in any given year (the rest are at various stages of their delisting timeline), so a 0.8 threshold (≥705 alive on a date) silently truncates the panel to 2006 → 2018-11-05. With 0.4 (≥352 alive) you get the full 2006 → today (~5040 trading days).

```bash
py scripts/fetch_data.py --from-db --universe sp500_hist --target-days 5040 --min-coverage 0.4
py scripts/run_factor_model.py --universe sp500_hist
```

### Monthly variant (`sp500_hist_monthly`)

`scripts/aggregate_panel_monthly.py --universe sp500_hist` rolls the daily panel up to month-end: keeps the last trading day of each calendar month for industry dummies and z-scored style exposures (slow-moving, end-of-month-snapshot is standard practice), compounds daily simple returns into the monthly return, and uses end-of-month market cap. Output: `data/model/sp500_hist_monthly_cross_sectional_data.csv`. The factor model can then run on it with `--frequency monthly` (annualization = ×12, NW halflife = 24 mo, vol-regime halflife = 6 mo).

### `china_she` and `taiwan_tw`

Built end-to-end by `scripts/build_china_taiwan.py` (resumable, three phases: ticker list + fundamentals → universe table → daily prices). SHE is filtered to top ~1,000 by market cap; Taiwan keeps all common-stock listings. Because EODHD reports a free-text `Industry` field rather than canonical 25-group GICS for non-US exchanges, run `scripts/consolidate_gics.py --universe china_she` (or `taiwan_tw`) before the factor model — this maps EODHD industries onto the 11-sector scheme.

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
py scripts/fetch_data.py --from-db --universe X [--sectors] \
    [--target-days 504] [--min-coverage 0.80]                  # compute factor exposures
py scripts/run_factor_model.py --universe X [--frequency daily|monthly]  # cross-sectional regression

# Monthly aggregation (for survivorship-bias-free long-horizon work)
py scripts/aggregate_panel_monthly.py --universe sp500_hist
py scripts/run_factor_model.py --universe sp500_hist_monthly --frequency monthly

# Portfolio analysis (uses russell3000 / barra_* model by default; pass --universe for others)
py scripts/analyze_portfolio.py data/input/portfolios/Own_Portfolio_dated.csv
py scripts/optimize_portfolio.py data/input/portfolios/Own_Portfolio_dated.csv
py scripts/size_positions.py data/input/portfolios/Own_Portfolio_dated.csv
py scripts/manage_risk.py data/input/portfolios/Own_Portfolio_dated.csv
py scripts/mcfr_matrix.py data/input/portfolios/Own_Portfolio_dated.csv  # joint stock×factor MCFR

# Basket workflow (multi-portfolio in one CSV)
py scripts/convert_baskets.py --scheme cap|equal|original --input <baskets.csv>
py scripts/append_basket_coverage.py [--phase A|B]            # add missing tickers (e.g. JP cross-listings)
py scripts/generate_basket_report.py                          # per-basket HTML report

# Validation & EDA
py scripts/explore_data.py                    # 16-check data quality report
py scripts/validate_model.py                  # 8-check model validation
py scripts/validate_alignment_v2.py           # permutation + decomposition tests
py scripts/validate_etf_loadings.py           # 20 ETF factor loading regressions
py scripts/validate_sp500_hist.py             # sp500_hist coverage + crisis spot-checks
py scripts/validate_all_markets.py            # cross-market EDA (auto-publishes data/eda_latest/)
py scripts/generate_market_report.py          # cross-market overview report
pytest tests/ -v                              # 78 automated tests
```

### Frequency-aware regression

`run_factor_model.py --frequency` switches all annualization-dependent constants:

| Constant | Daily | Monthly |
|---|---:|---:|
| Periods per year | 252 | 12 |
| Newey-West halflife | 252 | 24 |
| Volatility regime halflife | 42 | 6 |

### `fetch_data.py` flags

- `--target-days N` — number of dates retained after beta warmup is trimmed (default 504 ≈ 2 yr daily)
- `--min-coverage F` — minimum fraction of universe with data on a date (default 0.80)
- Sanity filter: rows with `close > 5000 × penny_threshold` are dropped to defend against EODHD symbol-reuse contamination on delisted US tickers (e.g. MEL.US, WFT) where the symbol got reassigned at $5k–$1M prices.
- Core-factor NaN guard: rows missing `size`/`beta`/`momentum` are now **dropped** rather than zero-filled (zero-filling created phantom zero-exposure rows that biased the regression). Composite factors (residvol, liquidity, etc.) still get filled.

### `update_data.py prices` extra flag

- `--start-date YYYY-MM-DD` — forces full-range fetch from that date for every ticker, ignoring incremental logic. Useful for backfilling history when extending an existing universe (e.g. `sp500_hist` 20-yr backfill).

## Web Frontend

Two-process app: FastAPI backend (`backend/`) serves JSON from the existing CSVs and SQLite DB; Vite + React + TypeScript + Tailwind frontend (`frontend/`) renders charts. Visual style sampled from aibottlenecks.app (warm cream background, dark teal accent).

```bash
# First-time install
py -m pip install -r backend/requirements.txt
cd frontend && npm install

# Run (two terminals)
py -m uvicorn app:app --reload --app-dir "C:/Users/danie/Documents/portfolio-xray/backend" --port 8000
cd frontend && npm run dev    # http://localhost:5173
```

Vite proxies `/api/*` to the backend on :8000.

**Markets page** (default tab):
1. **Cumulative Factor Returns** — 10 style factors only, 6 timeframes (1D/1W/1M/3M/6M/1Y), toggleable per-factor
2. **Cumulative Basket Returns** — 50 thematic baskets from `data/input/portfolios/Baskets/cap_weighted/`, multi-select
3. **Z-Score Table** — factors+baskets unified, sortable, 4 windows (63d/126d/252d/504d), sparklines, ±2σ bolded. Z = (today's daily return − rolling mean) / rolling std over the selected window.
4. **Rotation Quadrant** — 5D × 21D scatter colored by Leaders / Fading / Recovering / Laggards quadrants, factor/basket toggle

**Portfolio page:**
- Default loads `data/input/portfolios/own_ibkr_us_mapped.csv` (path configurable in `backend/portfolio.py`)
- KPI tiles: annualized vol, factor variance %, idio variance %, position count
- Returns-explained progress bar
- MCFR by factor table (sorted by abs contribution)
- Joint Stock × Style Factor MCFR heatmap (green = adds risk, red = hedges)
- Sector exposure pie (GICS sector from `stocks` table)
- Skipped-tickers warning for portfolio names not in Russell 3000

**Backend modules:**
- `app.py` — FastAPI app, 7 endpoints, CORS for :5173, basket warmup on startup
- `factors.py` — load + cumulate Russell 3000 factor returns
- `baskets.py` — load all baskets from CSV, compute constant-weight return series via SQL prices
- `zscores.py` — period returns + z-scores for factors and baskets
- `portfolio.py` — full risk decomposition (factor variance b'Ωb, idio vol from per-stock residual std, MCFR matrix, sector pie)
- `db.py` — SQLite helpers for `daily_prices` and `stocks`
- `theme.py` — variable-name → human-name map (`btop` → `Book-to-Price`, etc.)

**Frontend structure:**
- `src/api.ts` — typed fetch wrappers for the 7 endpoints
- `src/theme.ts` — chart color palette (10 colors)
- `src/components/` — `FactorChart`, `BasketChart`, `ZScoreTable`, `RotationQuadrant`, `PortfolioPage`, `Sparkline`, `TimeframePills`
- `tailwind.config.ts` — cream/forest/ink color tokens

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
- (Optional) the small annualized model outputs per market (`*_factor_covariance.csv`, `*_factor_returns.csv`, `*_factor_statistics.csv`, `*_r2.csv` — all <5 MB; `sp500_hist_factor_returns.csv` is ~4 MB at 20-yr horizon) so collaborators can run portfolio analysis without rebuilding the model.

**Do NOT share** (gitignored, reproducible from DB):
- `*_cross_sectional_data.csv`, `*_factor_exposures_historical.csv` (multi-GB across markets; `sp500_hist` alone is ~3.2 GB)
- `data/eda/` and `data/eda_latest/` (HTML reports + self-contained mirror, regenerable)
- `data/model/russell3000_raw_data.pkl` (intermediate cache)
- `Frontendreferences/` (design references, not for distribution)

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
