# Barra China Equity Model (CNE5) — Technical Summary for Implementation

**Source:** MSCI, "The Barra China Equity Model (CNE5) Empirical Notes", D.J. Orr, Igor Mashtaler, Adam Nagy, July 2012.

---

## 1. Overview & Purpose

The CNE5 is a multi-factor risk model for the China A-shares equity market. It decomposes stock returns into systematic factor components and stock-specific (idiosyncratic) components via cross-sectional regression. The model is used for risk forecasting, portfolio construction, performance attribution, and optimization.

The CNE5 follows the same methodology as the Barra US Equity Model (USE4), documented in "USE4 Methodology Notes" by Menchero, Orr, and Wang (2011).

### Model Variants
- **CNE5S** — Short-term: more responsive, better at monthly prediction horizon.
- **CNE5L** — Long-term: trades accuracy for stability in risk forecasts.
- **CNE5D** — Daily: tactical one-day risk forecast.

All three share identical **factor exposures** and **factor returns**; they differ only in their **factor covariance matrices** and **specific risk forecasts**.

---

## 2. Core Return Model (Equation B1)

Each stock's excess return is decomposed as:

```
r_n = Σ_k X_nk * f_k + u_n
```

Where:
- `r_n` = excess return of stock n
- `X_nk` = exposure of stock n to factor k
- `f_k` = return to factor k (estimated by cross-sectional regression each period)
- `u_n` = stock-specific (idiosyncratic) return

Factor returns `f_k` are estimated each period by **cross-sectional regression** (weighted by square root of market capitalization).

---

## 3. Key Methodological Innovations

### 3.1 Optimization Bias Adjustment
The sample covariance matrix systematically **underpredicts risk of low-volatility eigenfactors** and **overpredicts risk of high-volatility eigenfactors**. The CNE5 corrects this by:
1. Computing eigenfactors of the factor covariance matrix.
2. Estimating biases via Monte Carlo simulation.
3. Adjusting predicted volatilities of eigenfactors to correct for these biases.
4. Building corrections directly into the factor covariance matrix.

### 3.2 Volatility Regime Adjustment
Addresses non-stationarity: risk models tend to underpredict risk when volatility is rising and overpredict when falling. The adjustment uses a **cross-sectional bias statistic** as an instantaneous measure of risk model bias, then takes a weighted average over a suitable interval to recalibrate both **factor volatilities** and **specific risk**.

### 3.3 Country Factor
A single "Country" factor is introduced (analogous to the World factor in GEM2). Every stock has an exposure of 1 to the Country factor. This:
- Separates the overall market effect from pure industry effects.
- Makes industry factor portfolios **dollar-neutral** (100% long industry, 100% short Country).
- Produces intuitive attribution results.
- Captures rising industry correlations during crises in a timelier way.

### 3.4 Specific Risk Model with Bayesian Shrinkage
- Specific risk is estimated from **daily** asset-level specific returns (time-series approach).
- A **Bayesian shrinkage** technique reduces biases: stocks are segmented into **market-cap deciles**, and within each decile the specific risk forecast is pulled toward the decile mean. The shrinkage intensity increases with the number of standard deviations from the mean.

---

## 4. Factor Structure

### 4.1 Estimation Universe
A broad all A-shares universe (not just the largest/most liquid), to capture the full richness of China's industry structure.

### 4.2 Industry Factors (32 factors)
Based on GICS classification. Each stock has exposure of 1 to its industry and 0 to all others. Industry factor portfolios are dollar-neutral (long the industry, short the Country factor).

**Complete list of 32 CNE5 Industry Factors with GICS mappings:**

| Code | Industry Factor Name | GICS Codes |
|------|---------------------|------------|
| 1 | Energy | 10 |
| 2 | Chemicals | 151010 |
| 3 | Construction Materials | 151020 |
| 4 | Diversified Metals | 151040 |
| 5 | Materials | 151030, 151050 |
| 6 | Aerospace and Defense | 201010 |
| 7 | Building Products | 201020 |
| 8 | Construction and Engineering | 201030 |
| 9 | Electrical Equipment | 201040 |
| 10 | Industrial Conglomerates | 201050 |
| 11 | Industrial Machinery | 201060 |
| 12 | Trading Companies and Distributors | 201070 |
| 13 | Commercial and Professional Services | 2020 |
| 14 | Airlines | 203010, 203020 |
| 15 | Marine | 203030 |
| 16 | Road Rail and Transportation Infrastructure | 203040, 203050 |
| 17 | Automobiles and Components | 2510 |
| 18 | Household Durables (non-Homebuilding) | 252010 |
| 19 | Leisure Products Textiles Apparel and Luxury | 252020, 252030 |
| 20 | Hotels Restaurants and Leisure | 2530 |
| 21 | Media | 2540 |
| 22 | Retail | 2550 |
| 23 | Food Staples Retail Household Personal Prod | 3010, 3030 |
| 24 | Beverages | 302010 |
| 25 | Food Products | 302020 |
| 26 | Health | 35 |
| 27 | Banks | 4010 |
| 28 | Diversified Financial Services | 4020, 4030 |
| 29 | Real Estate | 4040 |
| 30 | Software | 4510 |
| 31 | Hardware and Semiconductors | 4520, 4530, 50 |
| 32 | Utilities | 55 |

### 4.3 Style Factors (10 factors)

Style factors are standardized to have **cap-weighted mean of 0** and **equal-weighted standard deviation of 1**. The cap-weighted estimation universe is therefore **style neutral**.

---

## 5. APPENDIX A: Style Factor Descriptor Definitions (CRITICAL FOR IMPLEMENTATION)

### 5.1 Size
**Definition:** `1.0 · LNCAP`

- **LNCAP** = Natural log of total market capitalization.

### 5.2 Beta
**Definition:** `1.0 · BETA`

- **BETA (β)** = Slope coefficient from time-series regression:
  ```
  r_t - r_ft = α + β * R_t + e_t
  ```
  where `r_t` is the stock return, `r_ft` is the risk-free rate, and `R_t` is the cap-weighted excess return of the estimation universe.
- Estimated over trailing **252 trading days** with a **half-life of 63 trading days** (exponential weighting).

### 5.3 Momentum
**Definition:** `1.0 · RSTR`

- **RSTR** (Relative Strength) = Sum of excess log returns over trailing T=504 trading days with a **lag of L=21 trading days** (to avoid short-term reversal):
  ```
  RSTR = Σ_{t=L}^{T+L} w_t * [ln(1 + r_t) - ln(1 + r_ft)]
  ```
  where `w_t` is an exponential weight with **half-life of 126 trading days**.

### 5.4 Residual Volatility
**Definition:** `0.74 · DASTD + 0.16 · CMRA + 0.10 · HSIGMA`

- **DASTD** (Daily standard deviation): Volatility of daily excess returns over past **252 trading days** with **half-life of 42 trading days**.
- **CMRA** (Cumulative range): 
  ```
  Z(T) = Σ_{τ=1}^{T} [ln(1 + r_τ) - ln(1 + r_fτ)]
  ```
  where each "month" τ = 21 trading days, T ranges over 1..12 months.
  ```
  CMRA = ln(1 + Z_max) - ln(1 + Z_min)
  ```
  where Z_max = max{Z(T)} and Z_min = min{Z(T)} for T=1,...,12.
- **HSIGMA** (Historical sigma): Standard deviation of residuals `e_t` from the Beta regression (Equation A1), estimated over trailing **252 trading days** with **half-life of 63 trading days**.

**Note:** Residual Volatility is **orthogonalized with respect to Beta and Size** to reduce collinearity.

### 5.5 Non-linear Size
**Definition:** `1.0 · NLSIZE`

- **NLSIZE** = Cube of the standardized Size exposure (i.e., cube of the standardized log of market cap).
- Then **orthogonalized with respect to Size** on a regression-weighted basis.
- Then winsorized and standardized.
- Captures the "barbell portfolio" effect (long mid-cap, short small-cap and large-cap).

### 5.6 Book-to-Price
**Definition:** `1.0 · BTOP`

- **BTOP** = Last reported book value of common equity / current market capitalization.

### 5.7 Liquidity
**Definition:** `0.35 · STOM + 0.35 · STOQ + 0.30 · STOA`

- **STOM** (Share turnover, 1 month):
  ```
  STOM = ln(Σ_{t=1}^{21} V_t / S_t)
  ```
  where V_t = trading volume on day t, S_t = shares outstanding.
- **STOQ** (Share turnover, trailing 3 months):
  ```
  STOQ = ln[(1/T) * Σ_{τ=1}^{T} exp(STOM_τ)]     where T = 3 months
  ```
- **STOA** (Share turnover, trailing 12 months):
  ```
  STOA = ln[(1/T) * Σ_{τ=1}^{T} exp(STOM_τ)]     where T = 12 months
  ```

**Note:** Liquidity is **orthogonalized with respect to Size** to reduce collinearity.

### 5.8 Earnings Yield
**Definition:** `0.68 · EPFWD + 0.21 · CETOP + 0.11 · ETOP`

- **EPFWD** (Predicted earnings-to-price): 12-month forward-looking earnings / current market cap. Forward earnings = weighted average of analyst-predicted earnings for current and next fiscal year.
- **CETOP** (Cash earnings-to-price): Trailing 12-month cash earnings / current price.
- **ETOP** (Trailing earnings-to-price): Trailing 12-month earnings / current market cap. Trailing earnings = last reported fiscal-year earnings + (current interim - comparative interim from prior year).

### 5.9 Growth
**Definition:** `0.18 · EGRLF + 0.11 · EGRSF + 0.24 · EGRO + 0.47 · SGRO`

- **EGRLF** (Long-term predicted earnings growth): 3-5 year earnings growth forecasted by analysts.
- **EGRSF** (Short-term predicted earnings growth): 1-year earnings growth forecasted by analysts.
- **EGRO** (Earnings growth, trailing 5 years): Slope of regression of annual EPS against time over past 5 fiscal years, divided by average annual EPS.
- **SGRO** (Sales growth, trailing 5 years): Slope of regression of annual sales per share against time over past 5 fiscal years, divided by average annual sales per share.

### 5.10 Leverage
**Definition:** `0.38 · MLEV + 0.35 · DTOA + 0.27 · BLEV`

- **MLEV** (Market leverage):
  ```
  MLEV = (ME + PE + LD) / ME
  ```
  ME = market value of common equity, PE = book value of preferred equity, LD = book value of long-term debt.
- **DTOA** (Debt-to-assets):
  ```
  DTOA = TD / TA
  ```
  TD = total debt (long-term debt + current liabilities), TA = total assets.
- **BLEV** (Book leverage):
  ```
  BLEV = (BE + PE + LD) / BE
  ```
  BE = book value of common equity, PE = book value of preferred equity, LD = book value of long-term debt.

---

## 6. APPENDIX B: Decomposing RMS Returns

The total R-squared of the cross-sectional regression:
```
R²_T = 1 - (Σ_n v_n * u_n²) / (Σ_n v_n * r_n²)
```
where `v_n` is the regression weight (proportional to sqrt of market cap).

Root mean square (RMS) return:
```
RMS = sqrt(Σ_n v_n * r_n²)
```

The RMS return can be decomposed using the x-sigma-rho formula:
```
RMS = Σ_k f_k * σ(X_k) * ρ(X_k, r) + σ(u) * ρ(u, r)
```
where `σ(X_k)` is the RMS dispersion of factor k exposures, and `ρ(X_k, r)` is the cross-sectional correlation between factor k and asset returns. The last term captures the stock-specific contribution.

---

## 7. APPENDIX C: Bias Statistics for Forecast Accuracy

### 7.1 Single-Window Bias Statistic

The **standardized return** for portfolio n at time t:
```
b_nt = R_nt / σ_nt
```
where R_nt = portfolio return, σ_nt = beginning-of-period volatility forecast.

The **bias statistic** for portfolio n over T periods:
```
B_n = sqrt[(1/(T-1)) * Σ_{t=1}^{T} (b_nt - b̄_n)²]
```
- Ideal value = **1.0** (realized risk matches forecast).
- 95% confidence interval (assuming normality): `[1 - sqrt(2/T), 1 + sqrt(2/T)]`
- If B_n > 1: model **underpredicts** risk.
- If B_n < 1: model **overpredicts** risk.

### 7.2 Rolling-Window Bias Statistic

Rolling 12-period bias statistic for portfolio n starting at window τ:
```
B_n^τ = sqrt[(1/11) * Σ_{t=τ}^{τ+11} (b_nt - b̄_n)²]
```

Mean of rolling bias statistics across N portfolios:
```
B̄^τ = (1/N) * Σ_n B_n^τ
```

### 7.3 MRAD (Mean Rolling Absolute Deviation)
```
MRAD^τ = (1/N) * Σ_n |B_n^τ - 1|
```
- Penalizes any deviation from the ideal bias statistic of 1.
- **Lower MRAD = better forecasts.**
- Theoretical lower bound (normal returns, perfect forecasts): **0.17**
- With fat tails (kurtosis 3.5–4.0): lower bound ≈ **0.19**

### Key Benchmarks for Backtesting:
- **Mean bias** should be close to 1.0.
- **P5 bias** (5th percentile) should be near 0.66 (normal) or 0.61 (fat-tailed).
- **P95 bias** (95th percentile) should be near 1.34 (normal) or 1.40 (fat-tailed).
- **MRAD** should be as close to 0.17–0.19 as possible.

---

## 8. Conclusion Highlights

The CNE5 model incorporates:
1. **Optimization Bias Adjustment** — better-conditioned covariance matrix, more accurate risk for optimized portfolios.
2. **Volatility Regime Adjustment** — calibrates to current market levels, crucial during turmoil.
3. **Country Factor** — intuitive attribution, timelier industry correlation forecasts.
4. **Bayesian Shrinkage for Specific Risk** — reduces biases in specific risk forecasts.

The backtesting (Section 5) compared CNE5 vs. its predecessor CHE2 across six portfolio types: pure factors, random active, factor-tilt long-only, factor-tilt active, optimized style-tilt, and specific risk. CNE5 generally showed improved or comparable MRAD and bias statistics across all portfolio types and all model horizons (S, L, D).

---

## 9. Implementation Checklist for Claude Code

To replicate this model given stock-level data, you need:

1. **Data inputs per stock:** price/return series, market cap, book value, preferred equity, long-term debt, total debt, total assets, shares outstanding, trading volume, analyst earnings forecasts (current/next FY, long-term growth), trailing EPS (5 years), trailing sales/share (5 years), cash earnings, GICS classification, risk-free rate series.

2. **Factor exposure computation:** Calculate each of the 10 style factor descriptors per the formulas in Appendix A above. Standardize to cap-weighted mean 0, equal-weighted std 1. Apply orthogonalizations (Residual Vol → orthog to Beta & Size; Non-linear Size → orthog to Size; Liquidity → orthog to Size).

3. **Industry exposures:** Binary 0/1 based on GICS mapping to the 32 industries. Country factor exposure = 1 for all stocks.

4. **Cross-sectional regression:** Each period, regress stock returns on factor exposures (weighted by sqrt of market cap) to obtain factor returns f_k and specific returns u_n.

5. **Factor covariance matrix:** Estimated from factor return time series, then apply Optimization Bias Adjustment (eigen-adjustment) and Volatility Regime Adjustment.

6. **Specific risk:** Time-series volatility of specific returns (daily), then apply Bayesian shrinkage by market-cap decile.

7. **Portfolio risk:** For any portfolio with weights w, total risk = sqrt(w' * X * F * X' * w + w' * Δ * w), where X = exposure matrix, F = factor covariance matrix, Δ = diagonal specific risk matrix.

8. **Backtesting:** Compute bias statistics, MRAD, P5, P95 on rolling 12-period windows per Appendix C formulas.
