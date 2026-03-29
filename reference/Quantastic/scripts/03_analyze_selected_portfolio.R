<<<<<<< HEAD
# ============================================
# ANALYZE SELECTED PORTFOLIO
# User chooses from portfolios/ folder
# ============================================

source("R/data_download.R")
source("R/factor_models.R")
source("R/risk_decomposition.R")
source("R/visualization.R")

library(tidyverse)
library(tidyquant)
library(xts)

# ============================================
# CONFIGURATION
# ============================================

portfolios_folder <- "portfolios/"  # Change if you want different location
start_date <- "2022-01-01"
end_date   <- Sys.Date()

# ============================================
# SELECT PORTFOLIO INTERACTIVELY
# ============================================

portfolio <- select_portfolio(portfolios_folder)

portfolio_name <- attr(portfolio, "filename")
portfolio_name <- tools::file_path_sans_ext(portfolio_name)  # Remove .csv

# ============================================
# ANALYSIS HEADER
# ============================================

cat("\n╔════════════════════════════════════════╗\n")
cat("║   PORTFOLIO X-RAY ANALYSIS             ║\n")
cat("╚════════════════════════════════════════╝\n\n")
cat("Portfolio:", portfolio_name, "\n")
cat("Holdings:", nrow(portfolio), "\n")
cat("Period:", start_date, "to", end_date, "\n")

# ============================================
# DOWNLOAD DATA
# ============================================

stock_returns <- download_stock_returns(
  tickers    = portfolio$ticker,
  start_date = start_date,
  end_date   = end_date
)

factor_returns <- download_fama_french_factors(
  start_date = start_date,
  end_date   = end_date
)

aligned <- align_data(stock_returns, factor_returns)
stock_returns  <- aligned$stock_returns
factor_returns <- aligned$factor_returns

# ============================================
# ESTIMATE FACTOR MODEL
# ============================================

factor_model <- estimate_factor_model(stock_returns, factor_returns)

# ============================================
# CALCULATE WEIGHTS
# ============================================

prices <- portfolio$ticker %>%
  tq_get(get = "stock.prices", from = start_date, to = end_date) %>%
  select(symbol, date, adjusted) %>%
  rename(ticker = symbol, price = adjusted)

portfolio_value <- calculate_weights(portfolio, prices)

cat("\nPortfolio Total Value: $", 
    format(round(sum(portfolio_value$position_value), 2), big.mark = ","), 
    "\n\n", sep = "")

print(portfolio_value %>% select(ticker, shares, price, position_value, weight))

weights <- portfolio_value$weight
names(weights) <- portfolio_value$ticker

# ============================================
# RISK DECOMPOSITION
# ============================================

risk_decomp <- decompose_portfolio_risk(
  weights        = weights,
  beta_matrix    = factor_model$beta_matrix,
  factor_returns = factor_returns,
  sigma2_idio    = factor_model$sigma2_idio,
  annualize      = TRUE
)

# ============================================
# PORTFOLIO FACTOR EXPOSURES
# ============================================

cat("\n=== PORTFOLIO FACTOR EXPOSURES ===\n\n")

for (i in seq_along(risk_decomp$portfolio_betas)) {
  beta_name  <- names(risk_decomp$portfolio_betas)[i]
  beta_value <- risk_decomp$portfolio_betas[i]
  
  cat(sprintf("  %-15s: %6.2f", beta_name, beta_value))
  
  if (beta_name == "Mkt.RF") {
    if (beta_value > 1.2) cat("  (High market sensitivity)")
    else if (beta_value < 0.8) cat("  (Defensive)")
  }
  cat("\n")
}

# ============================================
# VISUALIZATIONS
# ============================================

cat("\n=== GENERATING VISUALIZATIONS ===\n\n")

# Create portfolio-specific output folder
output_folder <- paste0("output/", portfolio_name, "/")
dir.create(output_folder, recursive = TRUE, showWarnings = FALSE)

plot_risk_pie(
  risk_decomp, 
  save_path = paste0(output_folder, "risk_decomposition.png")
)

plot_factor_exposures(
  risk_decomp$portfolio_betas, 
  save_path = paste0(output_folder, "factor_exposures.png")
)

# ============================================
# SAVE RESULTS
# ============================================

results <- list(
  portfolio_name  = portfolio_name,
  portfolio       = portfolio_value,
  factor_model    = factor_model,
  risk_decomp     = risk_decomp,
  analysis_date   = Sys.Date()
)

saveRDS(results, paste0(output_folder, "analysis_results.rds"))
write_csv(portfolio_value, paste0(output_folder, "portfolio_summary.csv"))

cat("\n✓ Results saved to", output_folder, "\n")
cat("\n╔════════════════════════════════════════╗\n")
cat("║   ANALYSIS COMPLETE                    ║\n")
cat("╚════════════════════════════════════════╝\n\n")

=======
# ============================================
# ANALYZE SELECTED PORTFOLIO
# User chooses from portfolios/ folder
# ============================================

source("R/data_download.R")
source("R/factor_models.R")
source("R/risk_decomposition.R")
source("R/visualization.R")

library(tidyverse)
library(tidyquant)
library(xts)

# ============================================
# CONFIGURATION
# ============================================

portfolios_folder <- "portfolios/"  # Change if you want different location
start_date <- "2022-01-01"
end_date   <- Sys.Date()

# ============================================
# SELECT PORTFOLIO INTERACTIVELY
# ============================================

portfolio <- select_portfolio(portfolios_folder)

portfolio_name <- attr(portfolio, "filename")
portfolio_name <- tools::file_path_sans_ext(portfolio_name)  # Remove .csv

# ============================================
# ANALYSIS HEADER
# ============================================

cat("\n╔════════════════════════════════════════╗\n")
cat("║   PORTFOLIO X-RAY ANALYSIS             ║\n")
cat("╚════════════════════════════════════════╝\n\n")
cat("Portfolio:", portfolio_name, "\n")
cat("Holdings:", nrow(portfolio), "\n")
cat("Period:", start_date, "to", end_date, "\n")

# ============================================
# DOWNLOAD DATA
# ============================================

stock_returns <- download_stock_returns(
  tickers    = portfolio$ticker,
  start_date = start_date,
  end_date   = end_date
)

factor_returns <- download_fama_french_factors(
  start_date = start_date,
  end_date   = end_date
)

aligned <- align_data(stock_returns, factor_returns)
stock_returns  <- aligned$stock_returns
factor_returns <- aligned$factor_returns

# ============================================
# ESTIMATE FACTOR MODEL
# ============================================

factor_model <- estimate_factor_model(stock_returns, factor_returns)

# ============================================
# CALCULATE WEIGHTS
# ============================================

prices <- portfolio$ticker %>%
  tq_get(get = "stock.prices", from = start_date, to = end_date) %>%
  select(symbol, date, adjusted) %>%
  rename(ticker = symbol, price = adjusted)

portfolio_value <- calculate_weights(portfolio, prices)

cat("\nPortfolio Total Value: $", 
    format(round(sum(portfolio_value$position_value), 2), big.mark = ","), 
    "\n\n", sep = "")

print(portfolio_value %>% select(ticker, shares, price, position_value, weight))

weights <- portfolio_value$weight
names(weights) <- portfolio_value$ticker

# ============================================
# RISK DECOMPOSITION
# ============================================

risk_decomp <- decompose_portfolio_risk(
  weights        = weights,
  beta_matrix    = factor_model$beta_matrix,
  factor_returns = factor_returns,
  sigma2_idio    = factor_model$sigma2_idio,
  annualize      = TRUE
)

# ============================================
# PORTFOLIO FACTOR EXPOSURES
# ============================================

cat("\n=== PORTFOLIO FACTOR EXPOSURES ===\n\n")

for (i in seq_along(risk_decomp$portfolio_betas)) {
  beta_name  <- names(risk_decomp$portfolio_betas)[i]
  beta_value <- risk_decomp$portfolio_betas[i]
  
  cat(sprintf("  %-15s: %6.2f", beta_name, beta_value))
  
  if (beta_name == "Mkt.RF") {
    if (beta_value > 1.2) cat("  (High market sensitivity)")
    else if (beta_value < 0.8) cat("  (Defensive)")
  }
  cat("\n")
}

# ============================================
# VISUALIZATIONS
# ============================================

cat("\n=== GENERATING VISUALIZATIONS ===\n\n")

# Create portfolio-specific output folder
output_folder <- paste0("output/", portfolio_name, "/")
dir.create(output_folder, recursive = TRUE, showWarnings = FALSE)

plot_risk_pie(
  risk_decomp, 
  save_path = paste0(output_folder, "risk_decomposition.png")
)

plot_factor_exposures(
  risk_decomp$portfolio_betas, 
  save_path = paste0(output_folder, "factor_exposures.png")
)

# ============================================
# SAVE RESULTS
# ============================================

results <- list(
  portfolio_name  = portfolio_name,
  portfolio       = portfolio_value,
  factor_model    = factor_model,
  risk_decomp     = risk_decomp,
  analysis_date   = Sys.Date()
)

saveRDS(results, paste0(output_folder, "analysis_results.rds"))
write_csv(portfolio_value, paste0(output_folder, "portfolio_summary.csv"))

cat("\n✓ Results saved to", output_folder, "\n")
cat("\n╔════════════════════════════════════════╗\n")
cat("║   ANALYSIS COMPLETE                    ║\n")
cat("╚════════════════════════════════════════╝\n\n")

>>>>>>> 19dde37b83c378e4960c4ec0d65165e18eb451c1
