<<<<<<< HEAD
#' Plot Risk Decomposition Pie Chart
#' 
#' @param risk_decomp Output from decompose_portfolio_risk()
#' @param save_path Optional path to save plot
#' @export
plot_risk_pie <- function(risk_decomp, save_path = NULL) {
  
  library(ggplot2)
  
  df <- data.frame(
    Component = c("Factor Risk", "Idiosyncratic Risk"),
    Percentage = c(risk_decomp$pct_factor, risk_decomp$pct_idio)
  )
  
  p <- ggplot(df, aes(x = "", y = Percentage, fill = Component)) +
    geom_bar(stat = "identity", width = 1) +
    coord_polar("y", start = 0) +
    scale_fill_manual(values = c("Factor Risk" = "#E74C3C", 
                                 "Idiosyncratic Risk" = "#27AE60")) +
    theme_void() +
    labs(title = "Portfolio Risk Decomposition",
         subtitle = sprintf("%.1f%% Idiosyncratic | %.1f%% Factor",
                            risk_decomp$pct_idio, risk_decomp$pct_factor)) +
    theme(plot.title = element_text(hjust = 0.5, size = 16, face = "bold"),
          plot.subtitle = element_text(hjust = 0.5, size = 12))
  
  if (!is.null(save_path)) {
    ggsave(save_path, p, width = 8, height = 6)
    message("✓ Plot saved to ", save_path)
  }
  
  print(p)
  return(p)
}


#' Plot Factor Exposures
#' 
#' @param portfolio_betas Named vector of portfolio-level betas
#' @param save_path Optional path to save
#' @export
plot_factor_exposures <- function(portfolio_betas, save_path = NULL) {
  
  library(ggplot2)
  
  df <- data.frame(
    Factor = names(portfolio_betas),
    Beta = as.numeric(portfolio_betas)
  )
  
  p <- ggplot(df, aes(x = Factor, y = Beta, fill = Beta > 0)) +
    geom_col(show.legend = FALSE) +
    geom_hline(yintercept = 0, linetype = "dashed") +
    scale_fill_manual(values = c("TRUE" = "#3498DB", "FALSE" = "#E74C3C")) +
    labs(title = "Portfolio Factor Exposures",
         y = "Beta (Factor Sensitivity)",
         x = NULL) +
    theme_minimal() +
    theme(plot.title = element_text(hjust = 0.5, size = 16, face = "bold"))
  
  if (!is.null(save_path)) {
    ggsave(save_path, p, width = 10, height = 6)
    message("✓ Plot saved to ", save_path)
  }
  
  print(p)
  return(p)
}

=======
#' Plot Risk Decomposition Pie Chart
#' 
#' @param risk_decomp Output from decompose_portfolio_risk()
#' @param save_path Optional path to save plot
#' @export
plot_risk_pie <- function(risk_decomp, save_path = NULL) {
  
  library(ggplot2)
  
  df <- data.frame(
    Component = c("Factor Risk", "Idiosyncratic Risk"),
    Percentage = c(risk_decomp$pct_factor, risk_decomp$pct_idio)
  )
  
  p <- ggplot(df, aes(x = "", y = Percentage, fill = Component)) +
    geom_bar(stat = "identity", width = 1) +
    coord_polar("y", start = 0) +
    scale_fill_manual(values = c("Factor Risk" = "#E74C3C", 
                                 "Idiosyncratic Risk" = "#27AE60")) +
    theme_void() +
    labs(title = "Portfolio Risk Decomposition",
         subtitle = sprintf("%.1f%% Idiosyncratic | %.1f%% Factor",
                            risk_decomp$pct_idio, risk_decomp$pct_factor)) +
    theme(plot.title = element_text(hjust = 0.5, size = 16, face = "bold"),
          plot.subtitle = element_text(hjust = 0.5, size = 12))
  
  if (!is.null(save_path)) {
    ggsave(save_path, p, width = 8, height = 6)
    message("✓ Plot saved to ", save_path)
  }
  
  print(p)
  return(p)
}


#' Plot Factor Exposures
#' 
#' @param portfolio_betas Named vector of portfolio-level betas
#' @param save_path Optional path to save
#' @export
plot_factor_exposures <- function(portfolio_betas, save_path = NULL) {
  
  library(ggplot2)
  
  df <- data.frame(
    Factor = names(portfolio_betas),
    Beta = as.numeric(portfolio_betas)
  )
  
  p <- ggplot(df, aes(x = Factor, y = Beta, fill = Beta > 0)) +
    geom_col(show.legend = FALSE) +
    geom_hline(yintercept = 0, linetype = "dashed") +
    scale_fill_manual(values = c("TRUE" = "#3498DB", "FALSE" = "#E74C3C")) +
    labs(title = "Portfolio Factor Exposures",
         y = "Beta (Factor Sensitivity)",
         x = NULL) +
    theme_minimal() +
    theme(plot.title = element_text(hjust = 0.5, size = 16, face = "bold"))
  
  if (!is.null(save_path)) {
    ggsave(save_path, p, width = 10, height = 6)
    message("✓ Plot saved to ", save_path)
  }
  
  print(p)
  return(p)
}

>>>>>>> 19dde37b83c378e4960c4ec0d65165e18eb451c1
