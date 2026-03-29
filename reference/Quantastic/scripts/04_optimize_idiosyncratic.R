# ==============================================================================
# IDIOSYNCRATIC MAXIMIZATION SCRIPT
# Objective: Select 20 stocks with highest specific risk share from all portfolios
# ==============================================================================

# 1. LOAD YOUR PROJECT FILES
source("R/data_download.R")
source("R/factor_models.R")
source("R/risk_decomposition.R")
source("R/visualization.R")

library(tidyverse)
library(xts)

# 2. CONFIGURATION
portfolios_folder <- "portfolios/"
start_date <- "2024-01-01" # Using last 2 years for stable beta estimation
end_date <- Sys.Date()

# 3. EXTRACT UNIVERSE FROM ALL PORTFOLIOS
csv_files <- list.files(portfolios_folder, pattern = "\\.csv$", full.names = TRUE)
if (length(csv_files) == 0) stop("No portfolio CSVs found in portfolios/")

all_tickers <- unique(unlist(lapply(csv_files, function(f) load_portfolio_csv(f)$ticker)))
message("Extracted ", length(all_tickers), " unique tickers from universe.")

# 4. DOWNLOAD AND ALIGN DATA
stock_returns <- download_stock_returns(all_tickers, start_date, end_date)
factor_returns <- download_fama_french_factors(start_date, end_date) # Includes MOM
aligned <- align_data(stock_returns, factor_returns)

# 5. ESTIMATE 4-FACTOR MODEL FOR ALL STOCKS
# This uses your updated factor_models.R which now includes Momentum
fm_universe <- estimate_factor_model(aligned$stock_returns, aligned$factor_returns)

# 6. CALCULATE IDIOSYNCRATIC SHARE PER STOCK
# We use dynamic factor names to avoid the dimension error
f_names <- colnames(fm_universe$beta_matrix)
Sigma_f <- cov(aligned$factor_returns[, f_names])

# Factor Variance = diag(B %*% Sigma_f %*% t(B))
# Total Variance = Factor Variance + Idiosyncratic Variance
factor_var_diag <- diag(fm_universe$beta_matrix %*% Sigma_f %*% t(fm_universe$beta_matrix))
stock_idio_share <- fm_universe$sigma2_idio / (fm_universe$sigma2_idio + factor_var_diag)

# 7. SELECT TOP 20 AND ANALYZE
top_20_tickers <- names(sort(stock_idio_share, decreasing = TRUE)[1:20])
weights <- rep(1/20, 20)
names(weights) <- top_20_tickers

# Decompose the risk of this new "High-Idio" portfolio
final_risk <- decompose_portfolio_risk(
  weights = weights,
  beta_matrix = fm_universe$beta_matrix[top_20_tickers, ],
  factor_returns = aligned$factor_returns,
  sigma2_idio = fm_universe$sigma2_idio[top_20_tickers],
  annualize = TRUE
)

# 8. RESULTS OUTPUT
cat("\n=== TOP 20 IDIOSYNCRATIC STOCKS SELECTED ===\n")
print(round(sort(stock_idio_share[top_20_tickers], decreasing = TRUE), 4))

cat("\n=== OPTIMIZED PORTFOLIO SUMMARY ===\n")
cat(sprintf("Total Idiosyncratic Risk Share: %.1f%%\n", final_risk$pct_idio))
cat(sprintf("Portfolio Annualized Volatility: %.2f%%\n", final_risk$vol_total * 100))

# Save for reference
dir.create("output/optimized/", recursive = TRUE, showWarnings = FALSE)
saveRDS(final_risk, "output/optimized/idio_max_results.rds")
plot_risk_pie(final_risk, save_path = "output/optimized/idio_max_pie.png")