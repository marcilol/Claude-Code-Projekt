"""
Batch analyze all portfolios in Quantastic/portfolios folder.
Adds missing costdate (1 year ago) where needed.
"""

import os
import pandas as pd
from datetime import datetime, timedelta
from src.portfolio import Portfolio
from src.metrics import generate_metrics_summary
from src.visualizer import generate_all_charts
from src.export import export_to_excel


def prepare_portfolio(csv_path: str, output_path: str) -> str:
    """Check if portfolio has costdate, add if missing. Return path to use."""

    # Auto-detect delimiter
    with open(csv_path, 'r') as f:
        first_line = f.readline()
    delimiter = ';' if ';' in first_line else ','

    df = pd.read_csv(csv_path, delimiter=delimiter)
    df.columns = df.columns.str.strip().str.lower()

    # Check if date column exists
    date_cols = ['costdate', 'buy_date', 'buydate', 'purchase_date']
    has_date = any(col in df.columns for col in date_cols)

    if has_date:
        return csv_path  # Use original

    # Add costdate (1 year ago)
    one_year_ago = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    df['costdate'] = one_year_ago

    # Save modified version
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    df.to_csv(output_path, sep=';', index=False)
    print(f"  Added costdate ({one_year_ago}) to {os.path.basename(csv_path)}")

    return output_path


def analyze_portfolio(name: str, csv_path: str, output_dir: str):
    """Run full analysis on a single portfolio."""

    print(f"\n{'='*60}")
    print(f"  ANALYZING: {name}")
    print(f"{'='*60}")

    try:
        pf = Portfolio(csv_path, benchmark='SPY')
        pf.run_full_analysis()

        # Generate metrics
        all_metrics = generate_metrics_summary(pf)

        # Generate charts (no display)
        os.makedirs(output_dir, exist_ok=True)
        generate_all_charts(pf, output_dir=output_dir, show=False)

        # Export Excel
        excel_path = os.path.join(output_dir, 'portfolio_analysis.xlsx')
        export_to_excel(pf, all_metrics, excel_path)

        print(f"\n  Results saved to: {output_dir}")

        return {
            'name': name,
            'positions': all_metrics['num_positions'],
            'gmv': all_metrics['gmv'],
            'sharpe': all_metrics['sharpe'],
            'ir': all_metrics['information_ratio'],
            'total_vol': all_metrics['total_vol'],
            'idio_vol': all_metrics['idio_vol'],
            'pct_idio': all_metrics['pct_idio_var'],
            'annual_return': all_metrics['annual_return'],
            'max_dd': all_metrics['max_drawdown'],
            'status': 'OK'
        }

    except Exception as e:
        print(f"  ERROR: {e}")
        return {
            'name': name,
            'status': f'FAILED: {e}'
        }


def main():
    portfolios_dir = "Quantastic/portfolios"
    output_base = "output_all_portfolios"
    temp_dir = "temp_portfolios"

    os.makedirs(output_base, exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)

    # Get all CSV files
    csv_files = [f for f in os.listdir(portfolios_dir) if f.endswith('.csv')]

    print(f"\nFound {len(csv_files)} portfolios to analyze")
    print("="*60)

    results = []

    for csv_file in sorted(csv_files):
        name = csv_file.replace('.csv', '')
        csv_path = os.path.join(portfolios_dir, csv_file)
        temp_path = os.path.join(temp_dir, csv_file)
        output_dir = os.path.join(output_base, name)

        # Prepare portfolio (add date if needed)
        prepared_path = prepare_portfolio(csv_path, temp_path)

        # Analyze
        result = analyze_portfolio(name, prepared_path, output_dir)
        results.append(result)

    # Summary table
    print("\n" + "="*60)
    print("  BATCH ANALYSIS COMPLETE")
    print("="*60)

    # Create summary DataFrame
    summary_df = pd.DataFrame(results)

    # Save summary
    summary_path = os.path.join(output_base, "summary_all_portfolios.csv")
    summary_df.to_csv(summary_path, index=False)

    # Print summary
    print("\n  SUMMARY:")
    print("-"*60)

    for r in results:
        if r.get('status') == 'OK':
            print(f"  {r['name']:25} | Sharpe: {r['sharpe']:5.2f} | "
                  f"IR: {r['ir']:5.2f} | Idio%: {r['pct_idio']*100:4.1f}%")
        else:
            print(f"  {r['name']:25} | {r['status']}")

    print(f"\n  Summary saved to: {summary_path}")
    print(f"  Individual results in: {output_base}/[portfolio_name]/")


if __name__ == "__main__":
    main()
