#' Calculate Portfolio Weights
#' 
#' @param portfolio Tibble with ticker and shares columns
#' @param prices Tibble with ticker, date, price
#' @return Tibble with weights
#' @export
calculate_weights <- function(portfolio, prices) {
  
  latest_prices <- prices %>%
    dplyr::group_by(ticker) %>%
    dplyr::slice_tail(n = 1) %>%
    dplyr::ungroup()
  
  portfolio_value <- portfolio %>%
    dplyr::left_join(latest_prices, by = "ticker") %>%
    dplyr::mutate(
      position_value = shares * price,
      weight         = position_value / sum(position_value)
    )
  
  return(portfolio_value)
}


#' Decompose Portfolio Risk
#' 
#' @param weights Named numeric vector of portfolio weights
#' @param beta_matrix Matrix of factor exposures (stocks x factors)
#' @param factor_returns xts of factor returns
#' @param sigma2_idio Named vector of idiosyncratic variances
#' @param annualize Annualize results (default TRUE)
#' @return List with risk decomposition
#' @export
decompose_portfolio_risk <- function(weights, beta_matrix, factor_returns, 
                                     sigma2_idio, annualize = TRUE) {
  
  message("\n=== RISK DECOMPOSITION ===\n")
  
  tickers <- names(weights)
  weights <- weights[rownames(beta_matrix)]
  sigma2_idio <- sigma2_idio[rownames(beta_matrix)]
  
  factor_names <- setdiff(colnames(factor_returns), "RF")
  
  Sigma_f <- cov(factor_returns[, factor_names])
  
  if (annualize) {
    Sigma_f <- Sigma_f * 252
    sigma2_idio <- sigma2_idio * 252
  }
  
  D_idio <- diag(sigma2_idio)
  
  B <- beta_matrix
  Sigma_factor <- B %*% Sigma_f %*% t(B)
  
  var_factor <- as.numeric(t(weights) %*% Sigma_factor %*% weights)
  var_idio   <- as.numeric(t(weights) %*% D_idio %*% weights)
  var_total  <- var_factor + var_idio
  
  vol_factor <- sqrt(var_factor)
  vol_idio   <- sqrt(var_idio)
  vol_total  <- sqrt(var_total)
  
  pct_factor <- var_factor / var_total * 100
  pct_idio   <- var_idio / var_total * 100
  
  portfolio_betas <- as.numeric(t(weights) %*% B)
  names(portfolio_betas) <- colnames(B)
  
  cat("Portfolio Volatility", ifelse(annualize, "(annualized)", "(daily)"), ":\n")
  cat(sprintf("  Total:          %5.2f%%\n", vol_total * 100))
  cat(sprintf("  Factor-driven:  %5.2f%% (%4.1f%% of variance)\n", 
              vol_factor * 100, pct_factor))
  cat(sprintf("  Idiosyncratic:  %5.2f%% (%4.1f%% of variance)\n\n", 
              vol_idio * 100, pct_idio))
  
  interpret_risk_decomposition(pct_idio)
  
  return(list(
    var_total       = var_total,
    var_factor      = var_factor,
    var_idio        = var_idio,
    vol_total       = vol_total,
    vol_factor      = vol_factor,
    vol_idio        = vol_idio,
    pct_factor      = pct_factor,
    pct_idio        = pct_idio,
    portfolio_betas = portfolio_betas,
    Sigma_f         = Sigma_f,
    Sigma_factor    = Sigma_factor
  ))
}


#' Interpret Risk Decomposition
#' 
#' @param pct_idio Percentage idiosyncratic variance
#' @export
interpret_risk_decomposition <- function(pct_idio) {
  
  cat("Interpretation:\n")
  
  if (pct_idio >= 70 & pct_idio <= 90) {
    cat("  ✓ GOOD: Idiosyncratic variance is", round(pct_idio, 1), "%\n")
    cat("    Your portfolio is driven by stock-specific bets (target: 70-90%)\n\n")
  } else if (pct_idio > 90) {
    cat("  ⚠ You may be over-diversified (", round(pct_idio, 1), "% idio)\n")
    cat("    Consider concentrating in your highest-conviction ideas\n\n")
  } else {
    cat("  ⚠ WARNING: Only", round(pct_idio, 1), "% idiosyncratic variance\n")
    cat("    Your portfolio is too factor-driven. You're making\n")
    cat("    market/style bets rather than stock-specific bets.\n\n")
  }
}
