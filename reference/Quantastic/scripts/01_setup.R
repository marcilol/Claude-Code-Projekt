# ============================================
# SETUP: Install Required Packages
# Run this once when starting the project
# ============================================

required_packages <- c(
  "tidyverse",
  "tidyquant",
  "xts",
  "PerformanceAnalytics",
  "ggplot2"
)

# Install missing packages
new_packages <- required_packages[!(required_packages %in% installed.packages()[,"Package"])]

if (length(new_packages) > 0) {
  message("Installing packages: ", paste(new_packages, collapse = ", "))
  install.packages(new_packages)
} else {
  message("✓ All required packages already installed")
}

# Load packages
lapply(required_packages, library, character.only = TRUE)

message("\n✓ Setup complete!")
