#' Calculate Annualized Sharpe Ratio for Portfolio Returns
#'
#' @param returns xts or vector of portfolio returns
#' @param rf_rate numeric, annualized risk-free rate (default 0)
#' @param scale numeric, periods per year (252 for daily, 12 for monthly, 1 for annual)
#' @param geometric logical, use geometric mean for returns (default FALSE)
#' @return numeric, annualized Sharpe ratio
#' @export

calculate_sharpe_ratio <- function(returns, rf_rate = 0, scale = 252, geometric = FALSE) {
  
  # Remove NA values
  returns <- na.omit(returns)
  
  # Convert annualized rf_rate to period frequency
  rf_period <- rf_rate / scale
  
  # Calculate excess returns
  excess_returns <- returns - rf_period
  
  # Calculate mean excess return
  if (geometric) {
    mean_excess <- prod(1 + excess_returns)^(1/length(excess_returns)) - 1
  } else {
    mean_excess <- mean(excess_returns)
  }
  
  # Calculate standard deviation of excess returns
  sd_returns <- sd(excess_returns)
  
  # Annualize: multiply by sqrt(scale)
  # This accounts for return scaling by 'scale' and volatility by sqrt(scale)
  sharpe_annualized <- (mean_excess / sd_returns) * sqrt(scale)
  
  return(sharpe_annualized)
}
