<<<<<<< HEAD
#' Download Stock Price Data
#' 
#' @param tickers Character vector of stock tickers
#' @param start_date Start date (YYYY-MM-DD format)
#' @param end_date End date (YYYY-MM-DD format)
#' @return xts object with daily log returns
#' @export
download_stock_returns <- function(tickers, start_date, end_date) {
  message("Downloading price data for ", length(tickers), " stocks...")
  
  prices <- tickers %>%
    tidyquant::tq_get(
      get = "stock.prices",
      from = start_date,
      to = end_date
    ) %>%
    dplyr::select(symbol, date, adjusted) %>%
    dplyr::rename(ticker = symbol, price = adjusted)
  
  returns <- prices %>%
    dplyr::group_by(ticker) %>%
    tidyquant::tq_transmute(
      select = price,
      mutate_fun = periodReturn,
      period = "daily",
      type = "log"
    ) %>%
    dplyr::rename(ret = daily.returns) %>%
    dplyr::ungroup()
  
  returns_wide <- returns %>%
    tidyr::pivot_wider(names_from = ticker, values_from = ret) %>%
    dplyr::arrange(date)
  
  ret_xts <- xts::xts(
    returns_wide[, -1],
    order.by = returns_wide$date
  )
  
  # CHANGE: Allow missing data, but require 30 consecutive days minimum
  # Remove rows with all NAs, but keep rows with some NAs
  ret_xts <- ret_xts[rowSums(!is.na(ret_xts)) > 0, ]
  
  # Report data quality
  message("✓ Downloaded ", nrow(ret_xts), " days of returns")
  message("Data completeness by ticker:")
  completeness <- colSums(!is.na(ret_xts)) / nrow(ret_xts) * 100
  print(summary(completeness))
  
  return(ret_xts)
}


#' Download Fama-French Factor Data
#' 
#' @param start_date Start date
#' @param end_date End date
#' @param save_path Optional path to save raw data
#' @return xts object with factor returns
#' @export
download_fama_french_factors <- function(start_date, end_date,
                                         save_path = "data/factors/ff_factors.rds") {
  message("Downloading Fama-French 4 factors (including momentum)...")
  
  # Download base 3 factors + RF
  ff_url <- "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip"
  temp_file <- tempfile(fileext = ".zip")
  
  tryCatch({
    download.file(ff_url, temp_file, mode = "wb", quiet = TRUE)
  }, error = function(e) {
    stop("Failed to download Fama-French data. Check internet connection.")
  })
  
  files_in_zip <- unzip(temp_file, list = TRUE)$Name
  message("Files found in zip: ", paste(files_in_zip, collapse = ", "))
  
  csv_file <- files_in_zip[grep("CSV$", files_in_zip, ignore.case = TRUE)][1]
  if (is.na(csv_file)) {
    stop("Could not find CSV file in downloaded zip.")
  }
  
  message("Reading file: ", csv_file)
  
  # Read base 3 factors
  ff_data <- read.csv(
    unz(temp_file, csv_file),
    skip = 4,
    stringsAsFactors = FALSE
  )
  
  ff_data <- ff_data %>%
    dplyr::filter(!is.na(X)) %>%
    dplyr::filter(nchar(X) == 8) %>%
    dplyr::rename(date = X) %>%
    dplyr::mutate(
      date = as.Date(as.character(date), format = "%Y%m%d"),
      Mkt.RF = as.numeric(Mkt.RF) / 100,
      SMB = as.numeric(SMB) / 100,
      HML = as.numeric(HML) / 100,
      RF = as.numeric(RF) / 100
    ) %>%
    dplyr::filter(date >= start_date & date <= end_date) %>%
    dplyr::select(date, Mkt.RF, SMB, HML, RF)
  
  # Download momentum factor
  mom_url <- "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_CSV.zip"
  temp_mom <- tempfile(fileext = ".zip")
  
  tryCatch({
    download.file(mom_url, temp_mom, mode = "wb", quiet = TRUE)
  }, error = function(e) {
    stop("Failed to download momentum factor. Check internet connection.")
  })
  
  files_mom <- unzip(temp_mom, list = TRUE)$Name
  csv_mom <- files_mom[grep("CSV$", files_mom, ignore.case = TRUE)][1]
  
  mom_data <- read.csv(
    unz(temp_mom, csv_mom),
    skip = 13,  # Momentum file has different header rows
    stringsAsFactors = FALSE
  )
  
  mom_data <- mom_data %>%
    dplyr::filter(!is.na(X)) %>%
    dplyr::filter(nchar(X) == 8) %>%
    dplyr::rename(date = X) %>%
    dplyr::mutate(
      date = as.Date(as.character(date), format = "%Y%m%d"),
      MOM = as.numeric(Mom) / 100
    ) %>%
    dplyr::filter(date >= start_date & date <= end_date) %>%
    dplyr::select(date, MOM)
  
  # Merge momentum with base factors
  ff_data <- ff_data %>%
    dplyr::left_join(mom_data, by = "date")
  
  # Convert to xts
  ff_xts <- xts::xts(ff_data[, -1], order.by = ff_data$date)
  
  # Save to disk
  if (!is.null(save_path)) {
    dir.create(dirname(save_path), recursive = TRUE, showWarnings = FALSE)
    saveRDS(ff_xts, save_path)
    message("✓ Saved factors to ", save_path)
  }
  
  message("✓ Downloaded factors: ", paste(colnames(ff_xts), collapse = ", "))
  return(ff_xts)
}



#' Align Stock and Factor Data
#' 
#' @param stock_returns xts of stock returns
#' @param factor_returns xts of factor returns
#' @return List with aligned stock_returns and factor_returns
#' @export
align_data <- function(stock_returns, factor_returns) {
  
  common_dates <- index(stock_returns)[index(stock_returns) %in% index(factor_returns)]
  
  stock_aligned  <- stock_returns[common_dates, ]
  factor_aligned <- factor_returns[common_dates, ]
  
  message("✓ Aligned data: ", length(common_dates), " trading days")
  
  return(list(
    stock_returns  = stock_aligned,
    factor_returns = factor_aligned
  ))
}

#' Select Portfolio Interactively
#' 
#' Shows list of available portfolios and lets user choose one
#' 
#' @param folder_path Folder containing portfolio CSV files
#' @return Selected portfolio tibble
#' @export
select_portfolio <- function(folder_path = "portfolios/") {
  
  # Check folder exists
  if (!dir.exists(folder_path)) {
    stop("Folder not found: ", folder_path, "\n",
         "Create it with: dir.create('", folder_path, "')")
  }
  
  # Find all CSV files
  csv_files <- list.files(folder_path, pattern = "\\.csv$", full.names = FALSE)
  
  if (length(csv_files) == 0) {
    stop("No CSV files found in ", folder_path, "\n",
         "Add portfolio CSV files to this folder first.")
  }
  
  # Display menu
  cat("\n╔════════════════════════════════════════╗\n")
  cat("║   SELECT PORTFOLIO                     ║\n")
  cat("╚════════════════════════════════════════╝\n\n")
  cat("Available portfolios:\n\n")
  
  for (i in seq_along(csv_files)) {
    cat(sprintf("  [%2d] %s\n", i, csv_files[i]))
  }
  
  cat("\n")
  
  # Get user selection
  selection <- readline(prompt = "Enter number (1-" %+% length(csv_files) %+% "): ")
  selection <- as.integer(selection)
  
  # Validate selection
  if (is.na(selection) || selection < 1 || selection > length(csv_files)) {
    stop("Invalid selection. Must be between 1 and ", length(csv_files))
  }
  
  # Load selected portfolio
  selected_file <- csv_files[selection]
  full_path <- file.path(folder_path, selected_file)
  
  cat("\n✓ Selected:", selected_file, "\n")
  
  portfolio <- load_portfolio_csv(full_path)
  
  # Store metadata for later use
  attr(portfolio, "filename") <- selected_file
  attr(portfolio, "filepath") <- full_path
  
  return(portfolio)
}


#' Helper: String concatenation for readable prompts
`%+%` <- function(a, b) paste0(a, b)

load_portfolio_csv <- function(filepath) {
  portfolio <- read.csv(
    filepath,
    sep = ";",
    dec = ".",
    stringsAsFactors = FALSE
  )
  
  colnames(portfolio) <- tolower(colnames(portfolio))
  colnames(portfolio) <- trimws(colnames(portfolio))
  
  # Remove periods (thousand separators) before converting to numeric
  portfolio$shares <- as.numeric(gsub("\\.", "", portfolio$shares))
  
  if (!all(c("ticker", "shares") %in% colnames(portfolio))) {
    stop("Portfolio CSV must have columns: ticker, shares")
  }
  
  portfolio <- portfolio[complete.cases(portfolio), ]
  
  if (nrow(portfolio) == 0) {
    stop("No valid portfolio data found")
  }
  
  if (any(portfolio$shares <= 0)) {
    stop("All shares must be positive numbers")
  }
  
  cat("✓ Loaded portfolio with", nrow(portfolio), "holdings\n")
  return(portfolio)
}
=======
#' Download Stock Price Data
#' 
#' @param tickers Character vector of stock tickers
#' @param start_date Start date (YYYY-MM-DD format)
#' @param end_date End date (YYYY-MM-DD format)
#' @return xts object with daily log returns
#' @export
download_stock_returns <- function(tickers, start_date, end_date) {
  message("Downloading price data for ", length(tickers), " stocks...")
  
  prices <- tickers %>%
    tidyquant::tq_get(
      get = "stock.prices",
      from = start_date,
      to = end_date
    ) %>%
    dplyr::select(symbol, date, adjusted) %>%
    dplyr::rename(ticker = symbol, price = adjusted)
  
  returns <- prices %>%
    dplyr::group_by(ticker) %>%
    tidyquant::tq_transmute(
      select = price,
      mutate_fun = periodReturn,
      period = "daily",
      type = "log"
    ) %>%
    dplyr::rename(ret = daily.returns) %>%
    dplyr::ungroup()
  
  returns_wide <- returns %>%
    tidyr::pivot_wider(names_from = ticker, values_from = ret) %>%
    dplyr::arrange(date)
  
  ret_xts <- xts::xts(
    returns_wide[, -1],
    order.by = returns_wide$date
  )
  
  # CHANGE: Allow missing data, but require 30 consecutive days minimum
  # Remove rows with all NAs, but keep rows with some NAs
  ret_xts <- ret_xts[rowSums(!is.na(ret_xts)) > 0, ]
  
  # Report data quality
  message("✓ Downloaded ", nrow(ret_xts), " days of returns")
  message("Data completeness by ticker:")
  completeness <- colSums(!is.na(ret_xts)) / nrow(ret_xts) * 100
  print(summary(completeness))
  
  return(ret_xts)
}


#' Download Fama-French Factor Data
#' 
#' @param start_date Start date
#' @param end_date End date
#' @param save_path Optional path to save raw data
#' @return xts object with factor returns
#' @export
download_fama_french_factors <- function(start_date, end_date,
                                         save_path = "data/factors/ff_factors.rds") {
  message("Downloading Fama-French 4 factors (including momentum)...")
  
  # Download base 3 factors + RF
  ff_url <- "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip"
  temp_file <- tempfile(fileext = ".zip")
  
  tryCatch({
    download.file(ff_url, temp_file, mode = "wb", quiet = TRUE)
  }, error = function(e) {
    stop("Failed to download Fama-French data. Check internet connection.")
  })
  
  files_in_zip <- unzip(temp_file, list = TRUE)$Name
  message("Files found in zip: ", paste(files_in_zip, collapse = ", "))
  
  csv_file <- files_in_zip[grep("CSV$", files_in_zip, ignore.case = TRUE)][1]
  if (is.na(csv_file)) {
    stop("Could not find CSV file in downloaded zip.")
  }
  
  message("Reading file: ", csv_file)
  
  # Read base 3 factors
  ff_data <- read.csv(
    unz(temp_file, csv_file),
    skip = 4,
    stringsAsFactors = FALSE
  )
  
  ff_data <- ff_data %>%
    dplyr::filter(!is.na(X)) %>%
    dplyr::filter(nchar(X) == 8) %>%
    dplyr::rename(date = X) %>%
    dplyr::mutate(
      date = as.Date(as.character(date), format = "%Y%m%d"),
      Mkt.RF = as.numeric(Mkt.RF) / 100,
      SMB = as.numeric(SMB) / 100,
      HML = as.numeric(HML) / 100,
      RF = as.numeric(RF) / 100
    ) %>%
    dplyr::filter(date >= start_date & date <= end_date) %>%
    dplyr::select(date, Mkt.RF, SMB, HML, RF)
  
  # Download momentum factor
  mom_url <- "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_CSV.zip"
  temp_mom <- tempfile(fileext = ".zip")
  
  tryCatch({
    download.file(mom_url, temp_mom, mode = "wb", quiet = TRUE)
  }, error = function(e) {
    stop("Failed to download momentum factor. Check internet connection.")
  })
  
  files_mom <- unzip(temp_mom, list = TRUE)$Name
  csv_mom <- files_mom[grep("CSV$", files_mom, ignore.case = TRUE)][1]
  
  mom_data <- read.csv(
    unz(temp_mom, csv_mom),
    skip = 13,  # Momentum file has different header rows
    stringsAsFactors = FALSE
  )
  
  mom_data <- mom_data %>%
    dplyr::filter(!is.na(X)) %>%
    dplyr::filter(nchar(X) == 8) %>%
    dplyr::rename(date = X) %>%
    dplyr::mutate(
      date = as.Date(as.character(date), format = "%Y%m%d"),
      MOM = as.numeric(Mom) / 100
    ) %>%
    dplyr::filter(date >= start_date & date <= end_date) %>%
    dplyr::select(date, MOM)
  
  # Merge momentum with base factors
  ff_data <- ff_data %>%
    dplyr::left_join(mom_data, by = "date")
  
  # Convert to xts
  ff_xts <- xts::xts(ff_data[, -1], order.by = ff_data$date)
  
  # Save to disk
  if (!is.null(save_path)) {
    dir.create(dirname(save_path), recursive = TRUE, showWarnings = FALSE)
    saveRDS(ff_xts, save_path)
    message("✓ Saved factors to ", save_path)
  }
  
  message("✓ Downloaded factors: ", paste(colnames(ff_xts), collapse = ", "))
  return(ff_xts)
}



#' Align Stock and Factor Data
#' 
#' @param stock_returns xts of stock returns
#' @param factor_returns xts of factor returns
#' @return List with aligned stock_returns and factor_returns
#' @export
align_data <- function(stock_returns, factor_returns) {
  
  common_dates <- index(stock_returns)[index(stock_returns) %in% index(factor_returns)]
  
  stock_aligned  <- stock_returns[common_dates, ]
  factor_aligned <- factor_returns[common_dates, ]
  
  message("✓ Aligned data: ", length(common_dates), " trading days")
  
  return(list(
    stock_returns  = stock_aligned,
    factor_returns = factor_aligned
  ))
}

#' Select Portfolio Interactively
#' 
#' Shows list of available portfolios and lets user choose one
#' 
#' @param folder_path Folder containing portfolio CSV files
#' @return Selected portfolio tibble
#' @export
select_portfolio <- function(folder_path = "portfolios/") {
  
  # Check folder exists
  if (!dir.exists(folder_path)) {
    stop("Folder not found: ", folder_path, "\n",
         "Create it with: dir.create('", folder_path, "')")
  }
  
  # Find all CSV files
  csv_files <- list.files(folder_path, pattern = "\\.csv$", full.names = FALSE)
  
  if (length(csv_files) == 0) {
    stop("No CSV files found in ", folder_path, "\n",
         "Add portfolio CSV files to this folder first.")
  }
  
  # Display menu
  cat("\n╔════════════════════════════════════════╗\n")
  cat("║   SELECT PORTFOLIO                     ║\n")
  cat("╚════════════════════════════════════════╝\n\n")
  cat("Available portfolios:\n\n")
  
  for (i in seq_along(csv_files)) {
    cat(sprintf("  [%2d] %s\n", i, csv_files[i]))
  }
  
  cat("\n")
  
  # Get user selection
  selection <- readline(prompt = "Enter number (1-" %+% length(csv_files) %+% "): ")
  selection <- as.integer(selection)
  
  # Validate selection
  if (is.na(selection) || selection < 1 || selection > length(csv_files)) {
    stop("Invalid selection. Must be between 1 and ", length(csv_files))
  }
  
  # Load selected portfolio
  selected_file <- csv_files[selection]
  full_path <- file.path(folder_path, selected_file)
  
  cat("\n✓ Selected:", selected_file, "\n")
  
  portfolio <- load_portfolio_csv(full_path)
  
  # Store metadata for later use
  attr(portfolio, "filename") <- selected_file
  attr(portfolio, "filepath") <- full_path
  
  return(portfolio)
}


#' Helper: String concatenation for readable prompts
`%+%` <- function(a, b) paste0(a, b)

load_portfolio_csv <- function(filepath) {
  portfolio <- read.csv(
    filepath,
    sep = ";",
    dec = ".",
    stringsAsFactors = FALSE
  )
  
  colnames(portfolio) <- tolower(colnames(portfolio))
  colnames(portfolio) <- trimws(colnames(portfolio))
  
  # Remove periods (thousand separators) before converting to numeric
  portfolio$shares <- as.numeric(gsub("\\.", "", portfolio$shares))
  
  if (!all(c("ticker", "shares") %in% colnames(portfolio))) {
    stop("Portfolio CSV must have columns: ticker, shares")
  }
  
  portfolio <- portfolio[complete.cases(portfolio), ]
  
  if (nrow(portfolio) == 0) {
    stop("No valid portfolio data found")
  }
  
  if (any(portfolio$shares <= 0)) {
    stop("All shares must be positive numbers")
  }
  
  cat("✓ Loaded portfolio with", nrow(portfolio), "holdings\n")
  return(portfolio)
}
>>>>>>> 19dde37b83c378e4960c4ec0d65165e18eb451c1
