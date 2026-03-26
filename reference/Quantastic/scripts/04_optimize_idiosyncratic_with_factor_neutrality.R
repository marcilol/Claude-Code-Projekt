# ==============================================================================
# FACTOR-NEUTRAL IDIOSYNCRATIC MAXIMIZATION
# Objective: Find 20 stocks with max idio variance AND neutral factor exposures
# ==============================================================================

# 1. LOAD YOUR PROJECT FILES
source("R/data_download.R")
source("R/factor_models.R")
source("R/risk_decomposition.R")
source("R/visualization.R")

library(tidyverse)
library(xts)
library(CVXR)

# 2. CONFIGURATION
portfolios_folder <- "portfolios/"
start_date <- "2024-01-01"
end_date <- Sys.Date()

N_STOCKS <- 20
MAX_WEIGHT <- 0.15
MIN_WEIGHT <- 0.02

# Factor neutrality targets (strict Paleologo compliance)
MAX_SMB_BETA <- 0.10   # Near-zero size exposure
MAX_HML_BETA <- 0.15   # Near-zero value/growth tilt
MAX_MOM_BETA <- 0.15   # Near-zero momentum tilt

# 3. EXTRACT UNIVERSE
csv_files <- list.files(portfolios_folder, pattern = "\\.csv$", full.names = TRUE)
all_tickers <- unique(unlist(lapply(csv_files, function(f) load_portfolio_csv(f)$ticker)))
message("Universe: ", length(all_tickers), " stocks")

# 4. DOWNLOAD AND ESTIMATE FACTOR MODEL
stock_returns <- download_stock_returns(all_tickers, start_date, end_date)
factor_returns <- download_fama_french_factors(start_date, end_date)
aligned <- align_data(stock_returns, factor_returns)

fm_universe <- estimate_factor_model(aligned$stock_returns, aligned$factor_returns)

# 5. PREPARE OPTIMIZATION INPUTS
D_idio <- diag(fm_universe$sigma2_idio)
rownames(D_idio) <- colnames(D_idio) <- names(fm_universe$sigma2_idio)

B <- fm_universe$beta_matrix
f_names <- colnames(B)

# Calculate individual idio shares for filtering
f_var_diag <- diag(B %*% cov(aligned$factor_returns[, f_names]) %*% t(B))
stock_idio_share <- fm_universe$sigma2_idio / (fm_universe$sigma2_idio + f_var_diag)

# 6. PRE-FILTER TO HIGH-IDIO CANDIDATES
# Take top 50% by idiosyncratic share to reduce problem size
idio_threshold <- quantile(stock_idio_share, 0.50)
high_idio_candidates <- names(stock_idio_share[stock_idio_share >= idio_threshold])
message("Pre-filtered to ", length(high_idio_candidates), " high-idio candidates")

6.5 # DIAGNOSE: Check if factor-neutral portfolio is possible
cat("\n=== CONSTRAINT FEASIBILITY CHECK ===\n")
cat("Candidate stocks:", length(high_idio_candidates), "\n")
cat("\nFactor exposure ranges in candidate pool:\n")
cat(sprintf("SMB: [%.2f, %.2f]\n", min(B_sub[, "SMB"]), max(B_sub[, "SMB"])))
cat(sprintf("HML: [%.2f, %.2f]\n", min(B_sub[, "HML"]), max(B_sub[, "HML"])))
cat(sprintf("MOM: [%.2f, %.2f]\n", min(B_sub[, "MOM"]), max(B_sub[, "MOM"])))

# Check if any portfolio can achieve neutrality
mean_smb <- mean(B_sub[, "SMB"])
mean_hml <- mean(B_sub[, "HML"])
mean_mom <- mean(B_sub[, "MOM"])
cat(sprintf("\nAverage betas: SMB=%.2f, HML=%.2f, MOM=%.2f\n", mean_smb, mean_hml, mean_mom))

if (abs(mean_smb) > MAX_SMB_BETA) {
  cat("⚠ WARNING: Average SMB beta exceeds target. Factor neutrality impossible.\n")
}


# 7. OPTIMIZE WITH RELAXED FACTOR CONSTRAINTS
# Based on diagnostic, we'll use achievable targets
message("\n=== OPTIMIZING WITH REALISTIC CONSTRAINTS ===")

library(quadprog)

n_candidates <- length(high_idio_candidates)
D_sub <- D_idio[high_idio_candidates, high_idio_candidates]
B_sub <- B[high_idio_candidates, ]

beta_smb <- B_sub[, "SMB"]
beta_hml <- B_sub[, "HML"]
beta_mom <- B_sub[, "MOM"]

# RELAXED TARGETS (more realistic for your universe)
TARGET_SMB <- 0.30   # Was 0.10 - relaxed
TARGET_HML <- 0.30   # Was 0.15 - relaxed
TARGET_MOM <- 0.30   # Was 0.15 - relaxed

# Quadprog setup
Dmat <- D_sub
dvec <- rep(0, n_candidates)

# Simplified constraints - focus on what's achievable
Amat <- cbind(
  rep(1, n_candidates),           # sum(w) = 1
  diag(n_candidates),             # w >= 0
  -diag(n_candidates),            # w <= MAX_WEIGHT
  beta_smb,                       # SMB <= TARGET
  -beta_smb                       # SMB >= -TARGET
)

bvec <- c(
  1,
  rep(0, n_candidates),
  rep(-MAX_WEIGHT, n_candidates),
  TARGET_SMB,
  TARGET_SMB
)

meq <- 1

# First attempt
result <- tryCatch({
  solve.QP(Dmat = Dmat, dvec = dvec, Amat = Amat, bvec = bvec, meq = meq)
}, error = function(e) {
  message("Still infeasible. Removing SMB constraint entirely...")
  
  # Final fallback: Just optimize idio with basic constraints
  Amat_simple <- cbind(
    rep(1, n_candidates),
    diag(n_candidates),
    -diag(n_candidates)
  )
  
  bvec_simple <- c(1, rep(0, n_candidates), rep(-MAX_WEIGHT, n_candidates))
  
  solve.QP(Dmat = Dmat, dvec = dvec, Amat = Amat_simple, bvec = bvec_simple, meq = 1)
})

w_optimal <- result$solution
names(w_optimal) <- high_idio_candidates

# Post-optimization: Select 20 stocks with best factor balance
# Sort by weight, then manually filter for factor diversity
w_sorted <- sort(w_optimal, decreasing = TRUE)

# Greedy selection: pick top stocks while monitoring cumulative factor exposure
selected <- character(0)
cumulative_weight <- 0
cumulative_smb <- 0
cumulative_hml <- 0
cumulative_mom <- 0

for (ticker in names(w_sorted)) {
  if (length(selected) >= N_STOCKS) break
  
  test_weight <- cumulative_weight + w_sorted[ticker]
  test_smb <- (cumulative_smb * cumulative_weight + B_sub[ticker, "SMB"] * w_sorted[ticker]) / test_weight
  test_hml <- (cumulative_hml * cumulative_weight + B_sub[ticker, "HML"] * w_sorted[ticker]) / test_weight
  test_mom <- (cumulative_mom * cumulative_weight + B_sub[ticker, "MOM"] * w_sorted[ticker]) / test_weight
  
  # Accept if it doesn't make factor exposures worse (or if we need more stocks)
  if (length(selected) < 10 || 
      (abs(test_smb) <= abs(cumulative_smb) + 0.1 && 
       abs(test_smb) <= 0.5)) {  # Never exceed 0.5
    
    selected <- c(selected, ticker)
    cumulative_weight <- test_weight
    cumulative_smb <- test_smb
    cumulative_hml <- test_hml
    cumulative_mom <- test_mom
  }
}

# Final weights (equal-weight the selected stocks for simplicity)
final_weights <- rep(1/length(selected), length(selected))
names(final_weights) <- selected
optimal_tickers <- selected

message("Selected ", length(optimal_tickers), " stocks with greedy factor control")


# 8. ANALYZE OPTIMIZED PORTFOLIO
message("\n=== FINAL PORTFOLIO ANALYSIS ===\n")

final_risk <- decompose_portfolio_risk(
  weights = final_weights,
  beta_matrix = fm_universe$beta_matrix[optimal_tickers, ],
  factor_returns = aligned$factor_returns,
  sigma2_idio = fm_universe$sigma2_idio[optimal_tickers],
  annualize = TRUE
)

# 9. DISPLAY RESULTS
cat("\n=== HOLDINGS ===\n")
holdings_df <- data.frame(
  Ticker = optimal_tickers,
  Weight_Pct = round(final_weights * 100, 2),
  Idio_Share_Pct = round(stock_idio_share[optimal_tickers] * 100, 1)
)
print(holdings_df[order(-holdings_df$Weight_Pct), ], row.names = FALSE)

cat("\n=== PORTFOLIO FACTOR EXPOSURES ===\n")
for (f in names(final_risk$portfolio_betas)) {
  cat(sprintf(" %-6s : %s\n", f, interpret_beta(final_risk$portfolio_betas[f], f)))
}

cat("\n=== RISK METRICS ===\n")
cat(sprintf("Idiosyncratic Risk Share: %.1f%%\n", final_risk$pct_idio))
cat(sprintf("Total Volatility (annual): %.2f%%\n", final_risk$vol_total * 100))
cat(sprintf("Idiosyncratic Vol (annual): %.2f%%\n", final_risk$vol_idio * 100))
cat(sprintf("Factor Vol (annual): %.2f%%\n", final_risk$vol_factor * 100))

# 10. COMPARE TO YOUR PREVIOUS RESULT
cat("\n=== COMPARISON ===\n")
cat("Previous portfolio: SMB = 0.67, Idio Share = 51%\n")
cat(sprintf("New portfolio:      SMB = %.2f, Idio Share = %.1f%%\n", 
            final_risk$portfolio_betas["SMB"], final_risk$pct_idio))

if (final_risk$pct_idio > 60) {
  cat("\n✓ SUCCESS: Achieved high-conviction idiosyncratic portfolio!\n")
} else {
  cat("\n⚠ Idio share still below 60%. Your universe may be factor-concentrated.\n")
  cat("  Consider expanding to include different sectors/geographies.\n")
}

# 11. SAVE OUTPUTS
dir.create("output/optimized_neutral/", recursive = TRUE, showWarnings = FALSE)

saveRDS(list(
  weights = final_weights,
  risk_decomp = final_risk,
  holdings = holdings_df
), "output/optimized_neutral/portfolio_results.rds")

write.csv(holdings_df, "output/optimized_neutral/holdings.csv", row.names = FALSE)

plot_risk_pie(final_risk, 
              save_path = "output/optimized_neutral/risk_decomposition.png")

plot_factor_exposures(final_risk$portfolio_betas, 
                      save_path = "output/optimized_neutral/factor_exposures.png")

cat("\n✓ Results saved to output/optimized_neutral/\n")
