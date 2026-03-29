<<<<<<< HEAD
# R/performance_metrics.R
# Performance metric calculations for portfolios

#' Calculate Annualized Sharpe Ratio
#'
#' @param returns xts or vector of portfolio returns
#' @param rf_rate numeric, annualized risk-free rate (default 0)
#' @param scale numeric, periods per year (252 for daily, 12 for monthly, 1 for annual)
#' @param geometric logical, use geometric mean for returns (default FALSE)
#' @return numeric, annualized Sharpe ratio
#' @export
calculate_sharpe_ratio <- function(returns, rf_rate = 0, scale = 252, geometric = FALSE) {
  
  returns <- na.omit(returns)
  rf_period <- rf_rate / scale
  excess_returns <- returns - rf_period
  
  if (geometric) {
    mean_excess <- prod(1 + excess_returns)^(1/length(excess_returns)) - 1
  } else {
    mean_excess <- mean(excess_returns)
  }
  
  sd_returns <- sd(excess_returns)
  sharpe_annualized <- (mean_excess / sd_returns) * sqrt(scale)
  
  return(sharpe_annualized)
}

#' Calculate Sharpe Ratios for Multiple Portfolios
#'
#' @param price_data xts object with asset prices
#' @param portfolio_weights list of named vectors, each containing portfolio weights
#' @param start_date character, start date in "YYYY-MM-DD" format
#' @param end_date character, end date in "YYYY-MM-DD" format
#' @param rf_rate numeric, annualized risk-free rate (default 0.03)
#' @param rebalance_on character, rebalancing frequency ("months", "quarters", "years", NULL)
#' @return data.frame with portfolio names and Sharpe ratios
#' @export
calculate_portfolio_sharpe <- function(price_data, 
                                       portfolio_weights, 
                                       start_date, 
                                       end_date,
                                       rf_rate = 0.03,
                                       rebalance_on = "months") {
  
  require(PerformanceAnalytics)
  
  # Subset price data by date range
  price_data_subset <- price_data[paste0(start_date, "/", end_date)]
  
  # Calculate asset returns
  asset_returns <- Return.calculate(price_data_subset, method = "discrete") %>%
    na.omit()
  
  # Determine scale based on rebalancing frequency
  scale <- switch(rebalance_on,
                  "days" = 252,
                  "months" = 12,
                  "quarters" = 4,
                  "years" = 1,
                  252)
  
  # Initialize results
  results <- data.frame(
    Portfolio = character(),
    Sharpe_Ratio = numeric(),
    Ann_Return = numeric(),
    Ann_Volatility = numeric(),
    stringsAsFactors = FALSE
  )
  
  # Calculate Sharpe ratio for each portfolio
  for (portfolio_name in names(portfolio_weights)) {
    
    weights <- portfolio_weights[[portfolio_name]]
    
    # Calculate portfolio returns
    port_returns <- Return.portfolio(
      R = asset_returns,
      weights = weights,
      rebalance_on = rebalance_on,
      geometric = FALSE
    )
    
    # Calculate Sharpe ratio
    sharpe <- calculate_sharpe_ratio(
      returns = port_returns,
      rf_rate = rf_rate,
      scale = scale
    )
    
    # Calculate annualized return and volatility
    ann_return <- mean(port_returns, na.rm = TRUE) * scale
    ann_vol <- sd(port_returns, na.rm = TRUE) * sqrt(scale)
    
    # Add to results
    results <- rbind(results, data.frame(
      Portfolio = portfolio_name,
      Sharpe_Ratio = round(sharpe, 3),
      Ann_Return = round(ann_return * 100, 2),
      Ann_Volatility = round(ann_vol * 100, 2)
    ))
  }
  
  # Sort by Sharpe ratio descending
  results <- results[order(-results$Sharpe_Ratio), ]
  rownames(results) <- NULL
  
  return(results)
}

calculate_portfolio_returns_history <- function(portfolio, 
                                                price_data,
                                                stock_returns) {
  
  require(xts)
  
  portfolio$costdate <- as.Date(portfolio$costdate)
  portfolio <- portfolio[order(portfolio$costdate), ]
  
  # ADDED: Check which tickers are actually available in the data
  available_tickers <- intersect(portfolio$ticker, colnames(stock_returns))
  missing_tickers <- setdiff(portfolio$ticker, available_tickers)
  
  if (length(missing_tickers) > 0) {
    warning("Missing data for tickers: ", paste(missing_tickers, collapse = ", "))
  }
  
  if (length(available_tickers) == 0) {
    stop("No tickers have available data in the stock_returns")
  }
  
  # ADDED: Filter portfolio to only available tickers
  portfolio <- portfolio[portfolio$ticker %in% available_tickers, ]
  
  trade_dates <- sort(unique(portfolio$costdate))
  
  port_returns_list <- list()
  weight_history <- list()
  
  for (i in seq_along(trade_dates)) {
    
    period_start <- trade_dates[i]
    period_end <- if (i < length(trade_dates)) trade_dates[i + 1] - 1 else end(stock_returns)
    
    active_positions <- portfolio[portfolio$costdate <= period_start, ]
    active_tickers <- active_positions$ticker
    active_shares <- active_positions$shares
    names(active_shares) <- active_tickers
    
    # ADDED: Check if tickers exist in price_data
    active_tickers <- intersect(active_tickers, colnames(price_data))
    if (length(active_tickers) == 0) next  # Skip if no valid tickers
    
    active_shares <- active_shares[active_tickers]  # Filter to available tickers
    
    start_prices <- price_data[period_start, active_tickers]
    if (any(is.na(start_prices))) {
      next_date_idx <- which(index(price_data) >= period_start)[1]
      if (!is.na(next_date_idx)) {
        start_prices <- price_data[next_date_idx, active_tickers]
      }
    }
    
    # ADDED: Skip if still no prices available
    if (all(is.na(start_prices))) next
    
    position_values <- as.numeric(start_prices) * active_shares
    total_value <- sum(position_values, na.rm = TRUE)
    
    # ADDED: Skip if total value is zero
    if (total_value == 0) next
    
    weights <- position_values / total_value
    names(weights) <- active_tickers
    
    period_returns <- stock_returns[paste0(period_start, "/", period_end), active_tickers]
    
    if (nrow(period_returns) == 0) next
    
    period_port_returns <- xts(
      rowSums(period_returns * rep(weights, each = nrow(period_returns)), na.rm = TRUE),
      order.by = index(period_returns)
    )
    
    port_returns_list[[i]] <- period_port_returns
    weight_history[[i]] <- data.frame(
      date = period_start,
      ticker = active_tickers,
      shares = active_shares,
      price = as.numeric(start_prices),
      weight = weights
    )
  }
  
  portfolio_returns <- do.call(rbind, port_returns_list)
  weight_df <- do.call(rbind, weight_history)
  
  return(list(
    portfolio_returns = portfolio_returns,
    weight_history = weight_df,
    trade_dates = trade_dates,
    n_periods = length(trade_dates)
  ))
}

#' Calculate Sharpe Ratio from Portfolio History
#'
#' Wrapper function that calculates returns from trade history and computes Sharpe
#'
#' @param portfolio data.frame with columns: ticker, shares, costdate
#' @param price_data xts object of stock prices
#' @param stock_returns xts object of stock returns
#' @param rf_rate numeric, annualized risk-free rate
#' @param scale numeric, periods per year (252 for daily)
#' @return list with sharpe_ratio, ann_return, ann_volatility, portfolio_returns
#' @export
calculate_sharpe_from_history <- function(portfolio,
                                          price_data,
                                          stock_returns,
                                          rf_rate = 0.03,
                                          scale = 252) {
  
  # Calculate portfolio returns with trade history
  port_data <- calculate_portfolio_returns_history(  # Call the function above
    portfolio = portfolio,  # Your portfolio with costdate
    price_data = price_data,  # Daily prices for weight calculation
    stock_returns = stock_returns  # Daily returns for performance calculation
  )
  
  port_returns <- port_data$portfolio_returns  # Extract the return series
  
  # Calculate Sharpe ratio
  sharpe <- calculate_sharpe_ratio(  # Use the existing Sharpe function
    returns = port_returns,  # Portfolio return time series
    rf_rate = rf_rate,  # Risk-free rate (e.g., 3%)
    scale = scale,  # Annualization factor (252 for daily)
    geometric = FALSE  # Use arithmetic mean
  )
  
  # Calculate annualized metrics
  ann_return <- mean(port_returns, na.rm = TRUE) * scale  # Average daily return × 252 = annual return
  ann_vol <- sd(port_returns, na.rm = TRUE) * sqrt(scale)  # Daily vol × √252 = annual volatility
  
  return(list(
    sharpe_ratio = sharpe,  # Annualized Sharpe ratio
    ann_return = ann_return,  # Annualized return (e.g., 0.15 = 15%)
    ann_volatility = ann_vol,  # Annualized volatility (e.g., 0.20 = 20%)
    portfolio_returns = port_returns,  # Full time series of daily returns
    weight_history = port_data$weight_history,  # Weight snapshots at each rebalance
    trade_dates = port_data$trade_dates,  # Dates when trades occurred
    n_periods = port_data$n_periods,  # Number of rebalancing events
    inception_date = min(portfolio$costdate),  # First trade date
    total_days = nrow(port_returns)  # Number of trading days
  ))
}


=======
# R/performance_metrics.R
# Performance metric calculations for portfolios

#' Calculate Annualized Sharpe Ratio
#'
#' @param returns xts or vector of portfolio returns
#' @param rf_rate numeric, annualized risk-free rate (default 0)
#' @param scale numeric, periods per year (252 for daily, 12 for monthly, 1 for annual)
#' @param geometric logical, use geometric mean for returns (default FALSE)
#' @return numeric, annualized Sharpe ratio
#' @export
calculate_sharpe_ratio <- function(returns, rf_rate = 0, scale = 252, geometric = FALSE) {
  
  returns <- na.omit(returns)
  rf_period <- rf_rate / scale
  excess_returns <- returns - rf_period
  
  if (geometric) {
    mean_excess <- prod(1 + excess_returns)^(1/length(excess_returns)) - 1
  } else {
    mean_excess <- mean(excess_returns)
  }
  
  sd_returns <- sd(excess_returns)
  sharpe_annualized <- (mean_excess / sd_returns) * sqrt(scale)
  
  return(sharpe_annualized)
}

#' Calculate Sharpe Ratios for Multiple Portfolios
#'
#' @param price_data xts object with asset prices
#' @param portfolio_weights list of named vectors, each containing portfolio weights
#' @param start_date character, start date in "YYYY-MM-DD" format
#' @param end_date character, end date in "YYYY-MM-DD" format
#' @param rf_rate numeric, annualized risk-free rate (default 0.03)
#' @param rebalance_on character, rebalancing frequency ("months", "quarters", "years", NULL)
#' @return data.frame with portfolio names and Sharpe ratios
#' @export
calculate_portfolio_sharpe <- function(price_data, 
                                       portfolio_weights, 
                                       start_date, 
                                       end_date,
                                       rf_rate = 0.03,
                                       rebalance_on = "months") {
  
  require(PerformanceAnalytics)
  
  # Subset price data by date range
  price_data_subset <- price_data[paste0(start_date, "/", end_date)]
  
  # Calculate asset returns
  asset_returns <- Return.calculate(price_data_subset, method = "discrete") %>%
    na.omit()
  
  # Determine scale based on rebalancing frequency
  scale <- switch(rebalance_on,
                  "days" = 252,
                  "months" = 12,
                  "quarters" = 4,
                  "years" = 1,
                  252)
  
  # Initialize results
  results <- data.frame(
    Portfolio = character(),
    Sharpe_Ratio = numeric(),
    Ann_Return = numeric(),
    Ann_Volatility = numeric(),
    stringsAsFactors = FALSE
  )
  
  # Calculate Sharpe ratio for each portfolio
  for (portfolio_name in names(portfolio_weights)) {
    
    weights <- portfolio_weights[[portfolio_name]]
    
    # Calculate portfolio returns
    port_returns <- Return.portfolio(
      R = asset_returns,
      weights = weights,
      rebalance_on = rebalance_on,
      geometric = FALSE
    )
    
    # Calculate Sharpe ratio
    sharpe <- calculate_sharpe_ratio(
      returns = port_returns,
      rf_rate = rf_rate,
      scale = scale
    )
    
    # Calculate annualized return and volatility
    ann_return <- mean(port_returns, na.rm = TRUE) * scale
    ann_vol <- sd(port_returns, na.rm = TRUE) * sqrt(scale)
    
    # Add to results
    results <- rbind(results, data.frame(
      Portfolio = portfolio_name,
      Sharpe_Ratio = round(sharpe, 3),
      Ann_Return = round(ann_return * 100, 2),
      Ann_Volatility = round(ann_vol * 100, 2)
    ))
  }
  
  # Sort by Sharpe ratio descending
  results <- results[order(-results$Sharpe_Ratio), ]
  rownames(results) <- NULL
  
  return(results)
}

calculate_portfolio_returns_history <- function(portfolio, 
                                                price_data,
                                                stock_returns) {
  
  require(xts)
  
  portfolio$costdate <- as.Date(portfolio$costdate)
  portfolio <- portfolio[order(portfolio$costdate), ]
  
  # ADDED: Check which tickers are actually available in the data
  available_tickers <- intersect(portfolio$ticker, colnames(stock_returns))
  missing_tickers <- setdiff(portfolio$ticker, available_tickers)
  
  if (length(missing_tickers) > 0) {
    warning("Missing data for tickers: ", paste(missing_tickers, collapse = ", "))
  }
  
  if (length(available_tickers) == 0) {
    stop("No tickers have available data in the stock_returns")
  }
  
  # ADDED: Filter portfolio to only available tickers
  portfolio <- portfolio[portfolio$ticker %in% available_tickers, ]
  
  trade_dates <- sort(unique(portfolio$costdate))
  
  port_returns_list <- list()
  weight_history <- list()
  
  for (i in seq_along(trade_dates)) {
    
    period_start <- trade_dates[i]
    period_end <- if (i < length(trade_dates)) trade_dates[i + 1] - 1 else end(stock_returns)
    
    active_positions <- portfolio[portfolio$costdate <= period_start, ]
    active_tickers <- active_positions$ticker
    active_shares <- active_positions$shares
    names(active_shares) <- active_tickers
    
    # ADDED: Check if tickers exist in price_data
    active_tickers <- intersect(active_tickers, colnames(price_data))
    if (length(active_tickers) == 0) next  # Skip if no valid tickers
    
    active_shares <- active_shares[active_tickers]  # Filter to available tickers
    
    start_prices <- price_data[period_start, active_tickers]
    if (any(is.na(start_prices))) {
      next_date_idx <- which(index(price_data) >= period_start)[1]
      if (!is.na(next_date_idx)) {
        start_prices <- price_data[next_date_idx, active_tickers]
      }
    }
    
    # ADDED: Skip if still no prices available
    if (all(is.na(start_prices))) next
    
    position_values <- as.numeric(start_prices) * active_shares
    total_value <- sum(position_values, na.rm = TRUE)
    
    # ADDED: Skip if total value is zero
    if (total_value == 0) next
    
    weights <- position_values / total_value
    names(weights) <- active_tickers
    
    period_returns <- stock_returns[paste0(period_start, "/", period_end), active_tickers]
    
    if (nrow(period_returns) == 0) next
    
    period_port_returns <- xts(
      rowSums(period_returns * rep(weights, each = nrow(period_returns)), na.rm = TRUE),
      order.by = index(period_returns)
    )
    
    port_returns_list[[i]] <- period_port_returns
    weight_history[[i]] <- data.frame(
      date = period_start,
      ticker = active_tickers,
      shares = active_shares,
      price = as.numeric(start_prices),
      weight = weights
    )
  }
  
  portfolio_returns <- do.call(rbind, port_returns_list)
  weight_df <- do.call(rbind, weight_history)
  
  return(list(
    portfolio_returns = portfolio_returns,
    weight_history = weight_df,
    trade_dates = trade_dates,
    n_periods = length(trade_dates)
  ))
}

#' Calculate Sharpe Ratio from Portfolio History
#'
#' Wrapper function that calculates returns from trade history and computes Sharpe
#'
#' @param portfolio data.frame with columns: ticker, shares, costdate
#' @param price_data xts object of stock prices
#' @param stock_returns xts object of stock returns
#' @param rf_rate numeric, annualized risk-free rate
#' @param scale numeric, periods per year (252 for daily)
#' @return list with sharpe_ratio, ann_return, ann_volatility, portfolio_returns
#' @export
calculate_sharpe_from_history <- function(portfolio,
                                          price_data,
                                          stock_returns,
                                          rf_rate = 0.03,
                                          scale = 252) {
  
  # Calculate portfolio returns with trade history
  port_data <- calculate_portfolio_returns_history(  # Call the function above
    portfolio = portfolio,  # Your portfolio with costdate
    price_data = price_data,  # Daily prices for weight calculation
    stock_returns = stock_returns  # Daily returns for performance calculation
  )
  
  port_returns <- port_data$portfolio_returns  # Extract the return series
  
  # Calculate Sharpe ratio
  sharpe <- calculate_sharpe_ratio(  # Use the existing Sharpe function
    returns = port_returns,  # Portfolio return time series
    rf_rate = rf_rate,  # Risk-free rate (e.g., 3%)
    scale = scale,  # Annualization factor (252 for daily)
    geometric = FALSE  # Use arithmetic mean
  )
  
  # Calculate annualized metrics
  ann_return <- mean(port_returns, na.rm = TRUE) * scale  # Average daily return × 252 = annual return
  ann_vol <- sd(port_returns, na.rm = TRUE) * sqrt(scale)  # Daily vol × √252 = annual volatility
  
  return(list(
    sharpe_ratio = sharpe,  # Annualized Sharpe ratio
    ann_return = ann_return,  # Annualized return (e.g., 0.15 = 15%)
    ann_volatility = ann_vol,  # Annualized volatility (e.g., 0.20 = 20%)
    portfolio_returns = port_returns,  # Full time series of daily returns
    weight_history = port_data$weight_history,  # Weight snapshots at each rebalance
    trade_dates = port_data$trade_dates,  # Dates when trades occurred
    n_periods = port_data$n_periods,  # Number of rebalancing events
    inception_date = min(portfolio$costdate),  # First trade date
    total_days = nrow(port_returns)  # Number of trading days
  ))
}


>>>>>>> 19dde37b83c378e4960c4ec0d65165e18eb451c1
