# ============================================
# SHARPE RATIO ANALYSIS - WITH TRADE HISTORY
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
rf_rate <- 0.03  # 3% annualized

# ============================================
# LOAD ALL PORTFOLIOS
# ============================================

csv_files <- list.files(portfolios_folder, pattern = "\\.csv$", full.names = FALSE)

if (length(csv_files) == 0) {
  stop("No CSV files found in ", portfolios_folder)
}

cat("\n╔════════════════════════════════════════╗\n")
cat("║ SHARPE RATIO - TRADE HISTORY ANALYSIS ║\n")
cat("╚════════════════════════════════════════╝\n\n")
cat("Found ", length(csv_files), " portfolios\n")
cat("Risk-Free Rate: ", rf_rate * 100, "%\n\n")

# ============================================
# LOAD PORTFOLIOS AND DETERMINE DATE RANGE
# ============================================

all_tickers <- character()
earliest_date <- Sys.Date()
latest_date <- as.Date("1900-01-01")

portfolios_list <- list()

for (file in csv_files) {
  portfolio_name <- tools::file_path_sans_ext(file)
  portfolio <- load_portfolio_csv(file.path(portfolios_folder, file))
  
  # Ensure costdate column exists
  if (!"costdate" %in% colnames(portfolio)) {
    stop("Portfolio ", file, " missing 'costdate' column!")
  }
  
  portfolio$costdate <- as.Date(portfolio$costdate)
  
  portfolios_list[[portfolio_name]] <- portfolio
  all_tickers <- c(all_tickers, portfolio$ticker)
  
  # Track date range
  earliest_date <- min(earliest_date, min(portfolio$costdate))
  latest_date <- max(latest_date, max(portfolio$costdate))
}

all_tickers <- unique(all_tickers)

cat("=== DATE RANGE ===\n")
cat("Earliest position: ", as.character(earliest_date), "\n")
cat("Latest position: ", as.character(latest_date), "\n")
cat("Total unique tickers: ", length(all_tickers), "\n\n")

# ============================================
# DOWNLOAD DATA
# ============================================

cat("=== DOWNLOADING DATA ===\n")

start_date <- earliest_date
end_date <- Sys.Date()

# Download returns
stock_returns <- download_stock_returns(
  tickers = all_tickers,
  start_date = start_date,
  end_date = end_date
)

# Download prices
cat("Downloading price data...\n")
price_data <- all_tickers %>%
  tq_get(get = "stock.prices", from = start_date, to = end_date) %>%
  select(symbol, date, adjusted) %>%
  tidyr::pivot_wider(names_from = symbol, values_from = adjusted) %>%
  arrange(date)

price_data_xts <- xts(price_data[, -1], order.by = price_data$date)

cat("\n")

# ============================================
# CALCULATE SHARPE FOR EACH PORTFOLIO
# ============================================

sharpe_results <- data.frame(
  Portfolio = character(),
  Inception_Date = character(),
  N_Trades = integer(),
  Total_Days = integer(),
  Sharpe_Ratio = numeric(),
  Ann_Return = numeric(),
  Ann_Volatility = numeric(),
  stringsAsFactors = FALSE
)

for (portfolio_name in names(portfolios_list)) {
  
  cat("\n--- Analyzing:", portfolio_name, "---\n")
  
  portfolio <- portfolios_list[[portfolio_name]]
  
  # Calculate Sharpe from trade history
  tryCatch({
    results <- calculate_sharpe_from_history(
      portfolio = portfolio,
      price_data = price_data_xts,
      stock_returns = stock_returns,
      rf_rate = rf_rate,
      scale = 252
    )
    
    cat("  Inception:", as.character(results$inception_date), "\n")
    cat("  Trade dates:", results$n_periods, "\n")
    cat("  Trading days:", results$total_days, "\n")
    cat("  Sharpe Ratio:", round(results$sharpe_ratio, 3), "\n")
    
    # Add to results
    sharpe_results <- rbind(sharpe_results, data.frame(
      Portfolio = portfolio_name,
      Inception_Date = as.character(results$inception_date),
      N_Trades = results$n_periods,
      Total_Days = results$total_days,
      Sharpe_Ratio = round(results$sharpe_ratio, 3),
      Ann_Return = round(results$ann_return * 100, 2),
      Ann_Volatility = round(results$ann_volatility * 100, 2)
    ))
    
  }, error = function(e) {
    cat("  ERROR:", e$message, "\n")
  })
}

# Sort by Sharpe ratio
sharpe_results <- sharpe_results[order(-sharpe_results$Sharpe_Ratio), ]
rownames(sharpe_results) <- NULL

# ============================================
# DISPLAY AND SAVE RESULTS
# ============================================

cat("\n\n=== SHARPE RATIO RESULTS (WITH TRADE HISTORY) ===\n\n")
print(sharpe_results)

# Save results
dir.create("output", showWarnings = FALSE)
write_csv(sharpe_results, "output/sharpe_ratios_history.csv")
cat("\n✓ Results saved to output/sharpe_ratios_history.csv\n")

cat("\n╔════════════════════════════════════════╗\n")
cat("║   ANALYSIS COMPLETE                  ║\n")
cat("╚════════════════════════════════════════╝\n\n")
