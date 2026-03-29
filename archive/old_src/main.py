<<<<<<< HEAD
"""
Portfolio X-Ray - Main CLI Interface

A quantitative portfolio analysis tool that decomposes returns into
systematic (factor-driven) and idiosyncratic (stock-specific) components.

Based on Giuseppe Paleologo's "Advanced Portfolio Management" book.

Usage:
    python -m src.main my_portfolio.csv
    python -m src.main my_portfolio.csv --benchmark QQQ
    python -m src.main my_portfolio.csv --start 2023-01-01 --end 2024-12-31
    python -m src.main my_portfolio.csv --export-only --output results/
"""

import argparse
import sys
import os
from datetime import datetime

import pandas as pd


def main():
    parser = argparse.ArgumentParser(
        description='Portfolio X-Ray: Factor-based portfolio analysis tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.main portfolio.csv                  # Basic analysis
  python -m src.main portfolio.csv --benchmark QQQ  # Use QQQ as benchmark
  python -m src.main portfolio.csv --no-charts      # Skip chart display
  python -m src.main portfolio.csv --output results # Save outputs to folder
        """
    )

    parser.add_argument('csv_file', help='Path to portfolio CSV file')
    parser.add_argument('--benchmark', '-b', default='SPY',
                        help='Benchmark ticker (default: SPY)')
    parser.add_argument('--start', '-s', default=None,
                        help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', '-e', default=None,
                        help='End date (YYYY-MM-DD)')
    parser.add_argument('--output', '-o', default=None,
                        help='Output directory for charts and Excel')
    parser.add_argument('--no-charts', action='store_true',
                        help='Skip chart display (still saves if --output)')
    parser.add_argument('--export-only', action='store_true',
                        help='Only export files, no interactive display')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')

    args = parser.parse_args()

    # Validate input file
    if not os.path.exists(args.csv_file):
        print(f"Error: File not found: {args.csv_file}")
        sys.exit(1)

    # Import modules
    from .portfolio import Portfolio
    from .metrics import generate_metrics_summary
    from .visualizer import generate_all_charts
    from .export import export_to_excel

    print("\n" + "=" * 60)
    print("  PORTFOLIO X-RAY")
    print("  Factor-Based Portfolio Analysis")
    print("=" * 60)
    print(f"\nInput file: {args.csv_file}")
    print(f"Benchmark: {args.benchmark}")

    # Create and run portfolio analysis
    try:
        pf = Portfolio(
            csv_path=args.csv_file,
            start_date=args.start,
            end_date=args.end,
            benchmark=args.benchmark
        )

        pf.run_full_analysis()

        # Generate extended metrics
        all_metrics = generate_metrics_summary(pf)

        # Print summary
        print("\n" + "=" * 60)
        print("  ANALYSIS COMPLETE")
        print("=" * 60)

        print("\n--- Key Metrics ---")
        print(f"  Sharpe Ratio:       {all_metrics['sharpe']:.2f}")
        print(f"  Information Ratio:  {all_metrics['information_ratio']:.2f}")
        print(f"  Sortino Ratio:      {all_metrics['sortino']:.2f}")
        print(f"  Max Drawdown:       {all_metrics['max_drawdown']:.1%}")
        print(f"  Annual Return:      {all_metrics['annual_return']:.1%}")

        print("\n--- Risk Decomposition ---")
        print(f"  Total Volatility:   {all_metrics['total_vol']:.1%}")
        print(f"  Factor Volatility:  {all_metrics['factor_vol']:.1%}")
        print(f"  Idio Volatility:    {all_metrics['idio_vol']:.1%}")
        print(f"  % Idio Variance:    {all_metrics['pct_idio_var']:.1%}")

        print("\n--- Portfolio Stats ---")
        print(f"  Positions:          {all_metrics['num_positions']}")
        print(f"  GMV:                ${all_metrics['gmv']:,.0f}")
        print(f"  Effective N:        {all_metrics['effective_n']:.1f}")
        print(f"  Hit Rate:           {all_metrics['hit_rate']:.1%}")

        # Generate charts
        output_dir = args.output
        show_charts = not args.no_charts and not args.export_only

        if output_dir or show_charts:
            print("\n--- Generating Charts ---")
            generate_all_charts(pf, output_dir=output_dir, show=show_charts)

        # Export to Excel
        if output_dir:
            excel_path = os.path.join(output_dir, 'portfolio_analysis.xlsx')
            export_to_excel(pf, all_metrics, excel_path)
            print(f"\nExcel report saved: {excel_path}")

        print("\n" + "=" * 60)
        print("  Analysis complete!")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\nError during analysis: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
=======
"""
Portfolio X-Ray - Main CLI Interface

A quantitative portfolio analysis tool that decomposes returns into
systematic (factor-driven) and idiosyncratic (stock-specific) components.

Based on Giuseppe Paleologo's "Advanced Portfolio Management" book.

Usage:
    python -m src.main my_portfolio.csv
    python -m src.main my_portfolio.csv --benchmark QQQ
    python -m src.main my_portfolio.csv --start 2023-01-01 --end 2024-12-31
    python -m src.main my_portfolio.csv --export-only --output results/
"""

import argparse
import sys
import os
from datetime import datetime

import pandas as pd


def main():
    parser = argparse.ArgumentParser(
        description='Portfolio X-Ray: Factor-based portfolio analysis tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.main portfolio.csv                  # Basic analysis
  python -m src.main portfolio.csv --benchmark QQQ  # Use QQQ as benchmark
  python -m src.main portfolio.csv --no-charts      # Skip chart display
  python -m src.main portfolio.csv --output results # Save outputs to folder
        """
    )

    parser.add_argument('csv_file', help='Path to portfolio CSV file')
    parser.add_argument('--benchmark', '-b', default='SPY',
                        help='Benchmark ticker (default: SPY)')
    parser.add_argument('--start', '-s', default=None,
                        help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', '-e', default=None,
                        help='End date (YYYY-MM-DD)')
    parser.add_argument('--output', '-o', default=None,
                        help='Output directory for charts and Excel')
    parser.add_argument('--no-charts', action='store_true',
                        help='Skip chart display (still saves if --output)')
    parser.add_argument('--export-only', action='store_true',
                        help='Only export files, no interactive display')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')

    args = parser.parse_args()

    # Validate input file
    if not os.path.exists(args.csv_file):
        print(f"Error: File not found: {args.csv_file}")
        sys.exit(1)

    # Import modules
    from .portfolio import Portfolio
    from .metrics import generate_metrics_summary
    from .visualizer import generate_all_charts
    from .export import export_to_excel

    print("\n" + "=" * 60)
    print("  PORTFOLIO X-RAY")
    print("  Factor-Based Portfolio Analysis")
    print("=" * 60)
    print(f"\nInput file: {args.csv_file}")
    print(f"Benchmark: {args.benchmark}")

    # Create and run portfolio analysis
    try:
        pf = Portfolio(
            csv_path=args.csv_file,
            start_date=args.start,
            end_date=args.end,
            benchmark=args.benchmark
        )

        pf.run_full_analysis()

        # Generate extended metrics
        all_metrics = generate_metrics_summary(pf)

        # Print summary
        print("\n" + "=" * 60)
        print("  ANALYSIS COMPLETE")
        print("=" * 60)

        print("\n--- Key Metrics ---")
        print(f"  Sharpe Ratio:       {all_metrics['sharpe']:.2f}")
        print(f"  Information Ratio:  {all_metrics['information_ratio']:.2f}")
        print(f"  Sortino Ratio:      {all_metrics['sortino']:.2f}")
        print(f"  Max Drawdown:       {all_metrics['max_drawdown']:.1%}")
        print(f"  Annual Return:      {all_metrics['annual_return']:.1%}")

        print("\n--- Risk Decomposition ---")
        print(f"  Total Volatility:   {all_metrics['total_vol']:.1%}")
        print(f"  Factor Volatility:  {all_metrics['factor_vol']:.1%}")
        print(f"  Idio Volatility:    {all_metrics['idio_vol']:.1%}")
        print(f"  % Idio Variance:    {all_metrics['pct_idio_var']:.1%}")

        print("\n--- Portfolio Stats ---")
        print(f"  Positions:          {all_metrics['num_positions']}")
        print(f"  GMV:                ${all_metrics['gmv']:,.0f}")
        print(f"  Effective N:        {all_metrics['effective_n']:.1f}")
        print(f"  Hit Rate:           {all_metrics['hit_rate']:.1%}")

        # Generate charts
        output_dir = args.output
        show_charts = not args.no_charts and not args.export_only

        if output_dir or show_charts:
            print("\n--- Generating Charts ---")
            generate_all_charts(pf, output_dir=output_dir, show=show_charts)

        # Export to Excel
        if output_dir:
            excel_path = os.path.join(output_dir, 'portfolio_analysis.xlsx')
            export_to_excel(pf, all_metrics, excel_path)
            print(f"\nExcel report saved: {excel_path}")

        print("\n" + "=" * 60)
        print("  Analysis complete!")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\nError during analysis: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
>>>>>>> 19dde37b83c378e4960c4ec0d65165e18eb451c1
