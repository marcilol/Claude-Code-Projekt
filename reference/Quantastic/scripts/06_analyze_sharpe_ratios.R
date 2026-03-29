# ============================================
# SHARPE RATIO ANALYSIS - BATCH MODE
# ============================================

source("R/data_download.R")
source("R/factor_models.R")
source("R/risk_decomposition.R")
source("R/visualization.R")
source("R/performance_metrics.R")

library(tidyverse)
library(tidyquant)
library(xts)

# ============================================
# CONFIGURATION
# ============================================

portfolios_folder <- "portfolios/"
start_date <- "2020-01-01"
end_date <- Sys.Date()
rf_rate <- 0.03  # 3% annualized

# ============================================
# LOAD ALL PORTFOLIOS
# ============================================

csv_files <- list.files(portfolios_folder, pattern = "\\.csv$", full.names = FALSE)

if (length(csv_files) == 0) {
  stop("No CSV files found in ", portfolios_folder)
}

cat("\n╔════════════════════════════════════════╗\n")
cat("║   SHARPE RATIO BATCH ANALYSIS        ║\n")
cat("╚════════════════════════════════════════╝\n\n")
cat("Found ", length(csv_files), " portfolios\n")
cat("Period: ", start_date, " to ", end_date, "\n")
cat("Risk-Free Rate: ", rf_rate * 100, "%\n\n")

# ============================================
# DOWNLOAD COMMON DATA
# ============================================

# Get all unique tickers
all_tickers <- character()
for (file in csv_files) {
  portfolio <- load_portfolio_csv(file.path(portfolios_folder, file))
  all_tickers <- c(all_tickers, portfolio$ticker)
}
all_tickers <- unique(all_tickers)

cat("=== DOWNLOADING DATA ===\n")
cat("Total unique tickers: ", length(all_tickers), "\n\n")

# Download stock returns
stock_returns <- download_stock_returns(
  tickers = all_tickers,
  start_date = start_date,
  end_date = end_date
)

# Download factor returns (for RF rate if needed)
factor_returns <- download_fama_french_factors(
  start_date = start_date,
  end_date = end_date
)

# Align data
aligned <- align_data(stock_returns, factor_returns)
stock_returns_aligned <- aligned$stock_returns
factor_returns_aligned <- aligned$factor_returns

# Extract risk-free rate from Fama-French data
rf_returns <- factor_returns_aligned$RF

# After the portfolio loop starts, add this diagnostic:
cat("\n=== DATA AVAILABILITY BY PORTFOLIO ===\n")

for (file in csv_files) {
  portfolio_name <- tools::file_path_sans_ext(file)
  portfolio <- load_portfolio_csv(file.path(portfolios_folder, file))
  portfolio_tickers <- portfolio$ticker
  
  # Filter to this portfolio's tickers
  portfolio_stock_returns <- stock_returns_aligned[, portfolio_tickers]
  
  cat("\n--- Portfolio:", portfolio_name, "---\n")
  
  data_coverage <- data.frame(
    Portfolio = portfolio_name,
    Ticker = portfolio_tickers,
    Start_Date = sapply(portfolio_tickers, function(x) {
      first_valid <- min(which(!is.na(portfolio_stock_returns[,x])))
      if (is.finite(first_valid)) {
        as.character(index(portfolio_stock_returns)[first_valid])
      } else {
        "NO DATA"
      }
    }),
    End_Date = sapply(portfolio_tickers, function(x) {
      last_valid <- max(which(!is.na(portfolio_stock_returns[,x])))
      if (is.finite(last_valid)) {
        as.character(index(portfolio_stock_returns)[last_valid])
      } else {
        "NO DATA"
      }
    }),
    N_Obs = colSums(!is.na(portfolio_stock_returns)),
    stringsAsFactors = FALSE
  )
  
  print(data_coverage, row.names = FALSE)
}

cat("\n=== END DATA AVAILABILITY CHECK ===\n\n")



# ============================================
# CALCULATE SHARPE FOR EACH PORTFOLIO
# ============================================

sharpe_results <- data.frame(
  Portfolio = character(),
  Sharpe_Ratio = numeric(),
  Ann_Return = numeric(),
  Ann_Volatility = numeric(),
  stringsAsFactors = FALSE
)

for (file in csv_files) {
  portfolio_name <- tools::file_path_sans_ext(file)
  
  # Load portfolio
  portfolio <- load_portfolio_csv(file.path(portfolios_folder, file))
  
  # Get current prices to calculate weights
  prices <- portfolio$ticker %>%
    tq_get(get = "stock.prices", from = start_date, to = end_date) %>%
    select(symbol, date, adjusted) %>%
    rename(ticker = symbol, price = adjusted)
  
  portfolio_value <- calculate_weights(portfolio, prices)
  weights <- portfolio_value$weight
  names(weights) <- portfolio_value$ticker
  
  # Filter returns to portfolio tickers
  portfolio_tickers <- portfolio$ticker
  stock_returns_portfolio <- stock_returns_aligned[, portfolio_tickers]
  
  # Calculate portfolio returns
  port_returns <- xts(rowSums(stock_returns_portfolio * rep(weights, each = nrow(stock_returns_portfolio))),
                      order.by = index(stock_returns_portfolio))
  
  # Calculate Sharpe ratio using daily returns
  sharpe <- calculate_sharpe_ratio(
    returns = port_returns,
    rf_rate = rf_rate,
    scale = 252,  # Daily returns
    geometric = FALSE
  )
  
  # Calculate annualized metrics
  ann_return <- mean(port_returns, na.rm = TRUE) * 252
  ann_vol <- sd(port_returns, na.rm = TRUE) * sqrt(252)
  
  # Add to results
  sharpe_results <- rbind(sharpe_results, data.frame(
    Portfolio = portfolio_name,
    Sharpe_Ratio = round(sharpe, 3),
    Ann_Return = round(ann_return * 100, 2),
    Ann_Volatility = round(ann_vol * 100, 2)
  ))
}

# Sort by Sharpe ratio
sharpe_results <- sharpe_results[order(-sharpe_results$Sharpe_Ratio), ]
rownames(sharpe_results) <- NULL

# ============================================
# DISPLAY AND SAVE RESULTS
# ============================================

cat("\n=== SHARPE RATIO RESULTS ===\n\n")
print(sharpe_results)

# Save results
dir.create("output", showWarnings = FALSE)
write_csv(sharpe_results, "output/sharpe_ratios.csv")
cat("\n✓ Results saved to output/sharpe_ratios.csv\n")

cat("\n╔════════════════════════════════════════╗\n")
cat("║   SHARPE ANALYSIS COMPLETE           ║\n")
cat("╚════════════════════════════════════════╝\n\n")
