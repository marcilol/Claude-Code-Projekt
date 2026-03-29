# ============================================
# PORTFOLIO ANALYSIS - BATCH MODE (ALL PORTFOLIOS)
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

portfolios_folder <- "portfolios/"
start_date <- "2025-01-01"
end_date <- Sys.Date()

# ============================================
# LOAD ALL PORTFOLIOS
# ============================================

csv_files <- list.files(portfolios_folder, pattern = "\\.csv$", full.names = FALSE)

if (length(csv_files) == 0) {
  stop("No CSV files found in ", portfolios_folder)
}

cat("\n╔════════════════════════════════════════╗\n")
cat("║ BATCH PORTFOLIO ANALYSIS ║\n")
cat("╚════════════════════════════════════════╝\n\n")
cat("Found ", length(csv_files), " portfolios:\n")
for (i in seq_along(csv_files)) {
  cat(sprintf("  [%d] %s\n", i, csv_files[i]))
}
cat("\n")

# ============================================
# DOWNLOAD COMMON DATA (ONCE FOR ALL)
# ============================================

# Get all unique tickers across all portfolios
all_tickers <- character()
for (file in csv_files) {
  portfolio <- load_portfolio_csv(file.path(portfolios_folder, file))
  all_tickers <- c(all_tickers, portfolio$ticker)
}
all_tickers <- unique(all_tickers)

cat("\n=== DOWNLOADING DATA ===\n")
cat("Total unique tickers across all portfolios:", length(all_tickers), "\n\n")

# Download once for efficiency
stock_returns <- download_stock_returns(
  tickers = all_tickers,
  start_date = start_date,
  end_date = end_date
)

factor_returns <- download_fama_french_factors(
  start_date = start_date,
  end_date = end_date
)

aligned <- align_data(stock_returns, factor_returns)
stock_returns_aligned <- aligned$stock_returns
factor_returns_aligned <- aligned$factor_returns

# Check data availability per stock
cat("\n=== STOCK DATA AVAILABILITY ===\n")
data_quality <- data.frame(
  ticker = colnames(stock_returns_aligned),
  obs_count = colSums(!is.na(stock_returns_aligned)),
  completeness_pct = colSums(!is.na(stock_returns_aligned)) / nrow(stock_returns_aligned) * 100
)
data_quality <- data_quality[order(data_quality$completeness_pct), ]
cat("Stocks with <50% data coverage:\n")
print(data_quality[data_quality$completeness_pct < 50, ])

# ============================================
# ANALYZE EACH PORTFOLIO
# ============================================

results_all <- list()

for (file in csv_files) {
  portfolio_name <- tools::file_path_sans_ext(file)
  
  cat("\n", strrep("=", 50), "\n", sep = "")
  cat("Portfolio: ", portfolio_name, "\n")
  cat(strrep("=", 50), "\n\n", sep = "")
  
  # Load portfolio
  portfolio <- load_portfolio_csv(file.path(portfolios_folder, file))
  
  # Filter returns to only this portfolio's tickers
  portfolio_tickers <- portfolio$ticker
  stock_returns_portfolio <- stock_returns_aligned[, portfolio_tickers]
  
  # ESTIMATE FACTOR MODEL
  factor_model <- estimate_factor_model(stock_returns_portfolio, factor_returns_aligned)
  
  # CALCULATE WEIGHTS
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
  
  # RISK DECOMPOSITION
  risk_decomp <- decompose_portfolio_risk(
    weights = weights,
    beta_matrix = factor_model$beta_matrix,
    factor_returns = factor_returns_aligned,
    sigma2_idio = factor_model$sigma2_idio,
    annualize = TRUE
  )
  
  # PORTFOLIO FACTOR EXPOSURES
  cat("\n=== PORTFOLIO FACTOR EXPOSURES ===\n\n")
  for (i in seq_along(risk_decomp$portfolio_betas)) {
    beta_name  <- names(risk_decomp$portfolio_betas)[i]
    beta_value <- risk_decomp$portfolio_betas[i]
    
    explanation <- interpret_beta(beta_value, beta_name)
    
    # explanation already includes the numeric beta and label
    # e.g. "1.25 - High sensitivity (aggressive)"
    cat(sprintf(" %-6s : %s\n", beta_name, explanation))
  }
  
  # VISUALIZATIONS
  cat("\n=== GENERATING VISUALIZATIONS ===\n\n")
  
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
  
  # SAVE RESULTS
  results <- list(
    portfolio_name = portfolio_name,
    portfolio = portfolio_value,
    factor_model = factor_model,
    risk_decomp = risk_decomp,
    analysis_date = Sys.Date()
  )
  
  saveRDS(results, paste0(output_folder, "analysis_results.rds"))
  write_csv(portfolio_value, paste0(output_folder, "portfolio_summary.csv"))
  
  results_all[[portfolio_name]] <- results
  
  cat("\n✓ Results saved to ", output_folder, "\n")
}

# ============================================
# SUMMARY COMPARISON TABLE
# ============================================

cat("\n\n", strrep("=", 70), "\n", sep = "")
cat("BATCH ANALYSIS SUMMARY\n")
cat(strrep("=", 70), "\n\n", sep = "")

summary_df <- data.frame(
  Portfolio = character(),
  Holdings = integer(),
  Total_Value = numeric(),
  Market_Beta = numeric(),
  Volatility_pct = numeric(),
  Pct_Factor_Risk = numeric(),
  stringsAsFactors = FALSE
)

for (name in names(results_all)) {
  res <- results_all[[name]]
  summary_df <- rbind(summary_df, data.frame(
    Portfolio = name,
    Holdings = nrow(res$portfolio),
    Total_Value = sum(res$portfolio$position_value),
    Market_Beta = res$risk_decomp$portfolio_betas["Mkt.RF"],
    Volatility_pct = res$risk_decomp$vol_total * 100,
    Pct_Factor_Risk = res$risk_decomp$pct_factor,
    row.names = NULL
  ))
}

print(summary_df)

write_csv(summary_df, "output/batch_summary.csv")
cat("\n✓ Summary saved to output/batch_summary.csv\n")

saveRDS(results_all, "output/batch_results.rds")
cat("✓ All results saved to output/batch_results.rds\n")

cat("\n╔════════════════════════════════════════╗\n")
cat("║ BATCH ANALYSIS COMPLETE ║\n")
cat("╚════════════════════════════════════════╝\n\n")

