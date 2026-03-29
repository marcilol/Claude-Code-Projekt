#' Estimate Factor Model for Single Stock
#' 
#' WHAT THIS DOES:
#' Runs a time-series regression to decompose stock returns into:
#' 1. Factor-driven returns (explained by market, size, value)
#' 2. Idiosyncratic returns (stock-specific)
#' 
#' THE REGRESSION [Paleologo Ch. 3, Eq. 3.1]:
#' (Stock_Return - RF) = α + β₁(Mkt-RF) + β₂(SMB) + β₃(HML) + ε
#' 
#' WHY each component:
#' - Left side: Excess return (what you earned above T-bills)
#' - α (alpha): Stock-specific expected return (the "edge")
#' - β (beta): Sensitivity to each factor (how much stock moves with factor)
#' - ε (epsilon): Idiosyncratic return (unexplained by factors)
#' 
#' @param stock_returns Numeric vector of daily returns for ONE stock
#' @param factor_returns Matrix/xts of factor returns (columns: Mkt.RF, SMB, HML)
#' @param rf_rate Numeric vector of risk-free rate (same length as stock_returns)
#' @return List with alpha, betas, residuals, R², idiosyncratic variance
#' @export
estimate_single_stock_model <- function(stock_returns, factor_returns, rf_rate) {
  
  # WHY subtract RF?
  # We want EXCESS returns = return ABOVE the risk-free rate
  # If T-bills pay 2% and stock returns 12%, excess is 10%
  # This is compensation for RISK (vs. safe T-bill investment)
  y <- stock_returns - rf_rate
  
  # WHY as.matrix?
  # lm() expects numeric matrix for multiple predictors
  # factor_returns might be xts or data.frame, need plain matrix
  X <- as.matrix(factor_returns)
  
  # THE REGRESSION
  # Formula: y ~ X means "regress y (stock excess return) on X (factors)"
  # Behind scenes: Ordinary Least Squares (OLS) solves (X'X)⁻¹X'y
  # This finds the β coefficients that minimize squared errors
  fit <- lm(y ~ X)
  
  # EXTRACT RESULTS
  # WHY coef(fit)[1]? First coefficient is intercept (α)
  # WHY coef(fit)[-1]? Remaining coefficients are slopes (β₁, β₂, β₃)
  #   The "-1" means "all except first element"
  # WHY var(residuals)? Variance of ε = idiosyncratic risk
  # WHY r.squared? % of variance explained by factors
  #   Example: R² = 0.6 means 60% explained by factors, 40% is stock-specific
  list(
    alpha        = coef(fit)[1],           # Intercept (α)
    betas        = coef(fit)[-1],          # Slopes (β vector)
    residuals    = residuals(fit),         # Unexplained returns (ε)
    r_squared    = summary(fit)$r.squared, # Goodness of fit
    sigma2_idio  = var(residuals(fit)),    # Var(ε) = idiosyncratic variance
    fitted_model = fit                     # Full lm object (for diagnostics)
  )
}


#' Estimate Factor Model for Portfolio
#' 
#' WHY run separate regressions per stock?
#' Each stock has DIFFERENT sensitivities to factors [Paleologo Ch. 4]
#' - Apple might be growth (negative HML beta)
#' - Walmart might be value (positive HML beta)
#' - Tesla might be high-beta (Mkt beta > 2)
#' - Procter & Gamble might be defensive (Mkt beta < 1)
#' 
#' We need individual betas to build portfolio-level exposures
#' Portfolio beta = weighted average of stock betas
#' 
#' @param stock_returns xts object with stock returns (one column per stock)
#' @param factor_returns xts object with factor returns (Mkt.RF, SMB, HML, RF)
#' @return List containing beta matrix, alphas, idio variances, R-squared
#' @export
estimate_factor_model <- function(stock_returns, factor_returns) {
  
  message("\n=== ESTIMATING FACTOR EXPOSURES ===\n")
  
  # SETUP: Get stock tickers and factor names
  # WHY colnames? In xts, column names are ticker symbols
  tickers   <- colnames(stock_returns)
  n_stocks  <- length(tickers)
  
  # WHY setdiff? 
  # factor_returns has 4 columns: Mkt.RF, SMB, HML, RF
  # RF is NOT a factor we regress on (it's subtracted from stock returns)
  # setdiff(all_cols, "RF") gives just: Mkt.RF, SMB, HML
  factor_names <- setdiff(colnames(factor_returns), "RF")
  n_factors <- length(factor_names)
  
  # INITIALIZE STORAGE
  # WHY matrix for betas?
  # We need beta_ij where i=stock, j=factor
  # Example: beta["AAPL", "Mkt.RF"] = 1.23
  #          beta["AAPL", "SMB"] = -0.15
  # Matrix is natural structure for this (rows=stocks, cols=factors)
  beta_matrix <- matrix(
    NA,                                      # Fill with NA (catches bugs if we miss a stock)
    nrow = n_stocks,                         # One row per stock
    ncol = n_factors,                        # One column per factor
    dimnames = list(tickers, factor_names)   # Named rows/cols for readability
  )
  
  # WHY separate vectors for alpha, sigma2, R²?
  # These are one value per stock (not per factor)
  # Vector is appropriate: alpha["AAPL"] = 0.0002
  # Named vector allows: alpha["AAPL"] instead of alpha[1]
  alpha_vec   <- numeric(n_stocks)
  sigma2_idio <- numeric(n_stocks)
  r_squared   <- numeric(n_stocks)
  
  names(alpha_vec)   <- tickers
  names(sigma2_idio) <- tickers
  names(r_squared)   <- tickers
  
  # RUN REGRESSION FOR EACH STOCK
  # WHY loop instead of vectorized operation?
  # Each stock needs separate regression (different coefficients)
  # Could use apply() but loop is clearer for learning
  # Performance difference negligible for 5-50 stocks
  for (i in seq_along(tickers)) {
    
    tk <- tickers[i]
    
    # Run regression for this stock
    # WHY as.numeric on stock_returns?
    # stock_returns[, tk] is xts (has dates attached)
    # lm() needs plain numeric vector
    # as.numeric() strips the xts wrapper, keeps just numbers
    result <- estimate_single_stock_model(
      stock_returns  = as.numeric(stock_returns[, tk]),
      factor_returns = factor_returns[, factor_names],  # Just factors (exclude RF)
      rf_rate        = as.numeric(factor_returns[, "RF"])
    )
    
    # STORE RESULTS
    # WHY use tk instead of i for indexing?
    # tk = "AAPL" (ticker name)
    # i = 1 (position in loop)
    # Using tk is safer: if ticker order changes later, code still works
    # Also more readable: alpha_vec["AAPL"] vs alpha_vec[1]
    alpha_vec[tk]      <- result$alpha
    beta_matrix[tk, ]  <- result$betas     # Stores all 3 betas at once (vector assignment)
    sigma2_idio[tk]    <- result$sigma2_idio
    r_squared[tk]      <- result$r_squared
    
    # PRINT PROGRESS
    # WHY sprintf instead of paste?
    # sprintf gives precise formatting control (like printf in C)
    # %-6s = left-aligned string, 6 chars wide
    # %5.2f = number with 5 total chars, 2 decimals
    # Makes output line up nicely in columns
    message(sprintf(
      "  %-6s | Beta: %5.2f | R²: %5.1f%% | Idio Vol: %5.2f%%",
      tk,
      beta_matrix[tk, "Mkt.RF"],               # Market beta (most important factor)
      r_squared[tk] * 100,                     # Convert 0.45 → 45%
      sqrt(sigma2_idio[tk]) * sqrt(252) * 100  # WHY sqrt? Convert variance → vol
      # WHY *sqrt(252)? Annualize
      # Daily vol * sqrt(252) = annual vol
    ))
  }
  
  message("\n✓ Factor model estimation complete\n")
  
  # RETURN RESULTS
  # WHY return a list?
  # We have 4 related outputs (betas, alphas, variances, R²)
  # List groups them logically under one object
  # Access like: results$beta_matrix, results$alphas
  # Alternative would be separate return() calls (can't do in R)
  return(list(
    beta_matrix = beta_matrix,   # N×K matrix (N stocks, K factors)
    alphas      = alpha_vec,     # N-vector (one alpha per stock)
    sigma2_idio = sigma2_idio,   # N-vector (idiosyncratic variances)
    r_squared   = r_squared      # N-vector (goodness of fit)
  ))
}


#' Interpret Factor Loadings
#' 
#' Helper function to interpret what beta values mean
#' Useful for understanding your portfolio exposures
#' 
#' @param beta_value Numeric beta coefficient
#' @param factor_name Name of factor ("Mkt.RF", "SMB", "HML")
#' @return Character string with interpretation
#' @export
interpret_beta <- function(beta_value, factor_name) {
  
  # MARKET BETA INTERPRETATION
  if (factor_name == "Mkt.RF") {
    if (beta_value > 1.2) {
      return(paste0(round(beta_value, 2), " - High sensitivity (aggressive)"))
    } else if (beta_value < 0.8) {
      return(paste0(round(beta_value, 2), " - Low sensitivity (defensive)"))
    } else {
      return(paste0(round(beta_value, 2), " - Market-like sensitivity"))
    }
  }
  
  # SIZE FACTOR (SMB = Small Minus Big)
  if (factor_name == "SMB") {
    if (beta_value > 0.3) {
      return(paste0(round(beta_value, 2), " - Small-cap tilt"))
    } else if (beta_value < -0.3) {
      return(paste0(round(beta_value, 2), " - Large-cap tilt"))
    } else {
      return(paste0(round(beta_value, 2), " - Neutral size exposure"))
    }
  }
  
  # VALUE FACTOR (HML = High Minus Low book-to-market)
  if (factor_name == "HML") {
    if (beta_value > 0.3) {
      return(paste0(round(beta_value, 2), " - Value tilt"))
    } else if (beta_value < -0.3) {
      return(paste0(round(beta_value, 2), " - Growth tilt"))
    } else {
      return(paste0(round(beta_value, 2), " - Neutral value/growth"))
    }
  }
  
  # MOMENTUM FACTOR (MOM = Winners Minus Losers)
  if (factor_name == "MOM") {
    if (beta_value > 0.3) {
      return(paste0(round(beta_value, 2), " - Momentum tilt (winners)"))
    } else if (beta_value < -0.3) {
      return(paste0(round(beta_value, 2), " - Contrarian tilt (losers)"))
    } else {
      return(paste0(round(beta_value, 2), " - Neutral momentum exposure"))
    }
  }
  
  # Default
  return(as.character(round(beta_value, 2)))
}
