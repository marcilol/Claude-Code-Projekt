# -*- coding: utf-8 -*-
"""
Consolidate non-canonical sector labels in stocks.sector to the 25 canonical
GICS Industry Groups used by russell3000. Operates on a target universe.

Usage: py scripts/consolidate_gics.py --universe china_she
"""
import argparse
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from data_manager import MarketDB

# Map non-canonical EODHD `Industry` values onto the 25 canonical GICS Industry Groups
MAP = {
    # Tech
    'Computer Hardware': 'Technology Hardware & Equipment',
    'Consumer Electronics': 'Technology Hardware & Equipment',
    'Communication Equipment': 'Technology Hardware & Equipment',
    'Scientific & Technical Instruments': 'Technology Hardware & Equipment',
    'Electronic Components': 'Technology Hardware & Equipment',
    'Software - Application': 'Software & Services',
    'Software - Infrastructure': 'Software & Services',
    'Information Technology Services': 'Software & Services',
    'Semiconductors': 'Semiconductors & Semiconductor Equipment',
    'Semiconductor Equipment & Materials': 'Semiconductors & Semiconductor Equipment',
    # Industrials / Capital Goods
    'Specialty Industrial Machinery': 'Capital Goods',
    'Electrical Equipment & Parts': 'Capital Goods',
    'Engineering & Construction': 'Capital Goods',
    'Conglomerates': 'Capital Goods',
    'Pollution & Treatment Controls': 'Capital Goods',
    'Solar': 'Capital Goods',
    'Aerospace & Defense': 'Capital Goods',
    'Industrial Distribution': 'Capital Goods',
    'Building Materials': 'Capital Goods',
    'Building Products & Equipment': 'Capital Goods',
    'Manufacturing - Tools & Accessories': 'Capital Goods',
    'Metal Fabrication': 'Capital Goods',
    'Specialty Chemicals': 'Materials',
    # Commercial services
    'Specialty Business Services': 'Commercial & Professional Services',
    'Business Equipment & Supplies': 'Commercial & Professional Services',
    'Staffing & Employment Services': 'Commercial & Professional Services',
    'Consulting Services': 'Commercial & Professional Services',
    'Security & Protection Services': 'Commercial & Professional Services',
    'Waste Management': 'Commercial & Professional Services',
    # Transportation
    'Airlines': 'Transportation',
    'Trucking': 'Transportation',
    'Railroads': 'Transportation',
    'Marine Shipping': 'Transportation',
    'Integrated Freight & Logistics': 'Transportation',
    # Autos
    'Auto Manufacturers': 'Automobiles & Components',
    'Auto Parts': 'Automobiles & Components',
    'Auto & Truck Dealerships': 'Automobiles & Components',
    'Recreational Vehicles': 'Consumer Durables & Apparel',
    # Consumer durables
    'Footwear & Accessories': 'Consumer Durables & Apparel',
    'Furnishings, Fixtures & Appliances': 'Consumer Durables & Apparel',
    'Textile Manufacturing': 'Consumer Durables & Apparel',
    'Apparel Manufacturing': 'Consumer Durables & Apparel',
    'Apparel Retail': 'Consumer Durables & Apparel',
    'Luxury Goods': 'Consumer Durables & Apparel',
    'Leisure': 'Consumer Services',
    'Restaurants': 'Consumer Services',
    'Lodging': 'Consumer Services',
    'Resorts & Casinos': 'Consumer Services',
    'Gambling': 'Consumer Services',
    'Personal Services': 'Consumer Services',
    'Education & Training Services': 'Consumer Services',
    'Travel Services': 'Consumer Services',
    # Consumer staples
    'Packaged Foods': 'Food, Beverage & Tobacco',
    'Beverages - Non-Alcoholic': 'Food, Beverage & Tobacco',
    'Beverages - Wineries & Distilleries': 'Food, Beverage & Tobacco',
    'Beverages - Brewers': 'Food, Beverage & Tobacco',
    'Tobacco': 'Food, Beverage & Tobacco',
    'Confectioners': 'Food, Beverage & Tobacco',
    'Farm Products': 'Food, Beverage & Tobacco',
    'Discount Stores': 'Consumer Staples Distribution & Retail',
    'Grocery Stores': 'Consumer Staples Distribution & Retail',
    'Food Distribution': 'Consumer Staples Distribution & Retail',
    # Discretionary retail
    'Internet Retail': 'Consumer Discretionary Distribution & Retail',
    'Specialty Retail': 'Consumer Discretionary Distribution & Retail',
    'Department Stores': 'Consumer Discretionary Distribution & Retail',
    'Home Improvement Retail': 'Consumer Discretionary Distribution & Retail',
    # Healthcare
    'Drug Manufacturers - Specialty & Generic': 'Pharmaceuticals, Biotechnology & Life Sciences',
    'Drug Manufacturers - General': 'Pharmaceuticals, Biotechnology & Life Sciences',
    'Biotechnology': 'Pharmaceuticals, Biotechnology & Life Sciences',
    'Diagnostics & Research': 'Pharmaceuticals, Biotechnology & Life Sciences',
    'Medical Devices': 'Health Care Equipment & Services',
    'Medical Care Facilities': 'Health Care Equipment & Services',
    'Medical Distribution': 'Health Care Equipment & Services',
    'Medical Instruments & Supplies': 'Health Care Equipment & Services',
    'Health Information Services': 'Health Care Equipment & Services',
    'Healthcare Plans': 'Health Care Equipment & Services',
    # Materials
    'Other Industrial Metals & Mining': 'Materials',
    'Copper': 'Materials',
    'Gold': 'Materials',
    'Silver': 'Materials',
    'Aluminum': 'Materials',
    'Steel': 'Materials',
    'Other Precious Metals & Mining': 'Materials',
    'Coking Coal': 'Materials',
    'Lumber & Wood Production': 'Materials',
    'Paper & Paper Products': 'Materials',
    'Agricultural Inputs': 'Materials',
    'Chemicals': 'Materials',
    'Specialty Chemicals': 'Materials',
    # Energy
    'Oil & Gas E&P': 'Energy',
    'Oil & Gas Integrated': 'Energy',
    'Oil & Gas Refining & Marketing': 'Energy',
    'Oil & Gas Midstream': 'Energy',
    'Oil & Gas Equipment & Services': 'Energy',
    'Oil & Gas Drilling': 'Energy',
    'Thermal Coal': 'Energy',
    'Uranium': 'Energy',
    # Financials
    'Asset Management': 'Financial Services',
    'Credit Services': 'Financial Services',
    'Capital Markets': 'Financial Services',
    'Mortgage Finance': 'Financial Services',
    'Financial Conglomerates': 'Financial Services',
    'Banks - Diversified': 'Banks',
    'Banks - Regional': 'Banks',
    'Insurance - Life': 'Insurance',
    'Insurance - Property & Casualty': 'Insurance',
    'Insurance - Reinsurance': 'Insurance',
    'Insurance - Diversified': 'Insurance',
    'Insurance - Specialty': 'Insurance',
    'Insurance Brokers': 'Insurance',
    # Real Estate
    'REIT - Diversified': 'Equity Real Estate Investment Trusts (REITs)',
    'REIT - Healthcare Facilities': 'Equity Real Estate Investment Trusts (REITs)',
    'REIT - Hotel & Motel': 'Equity Real Estate Investment Trusts (REITs)',
    'REIT - Industrial': 'Equity Real Estate Investment Trusts (REITs)',
    'REIT - Office': 'Equity Real Estate Investment Trusts (REITs)',
    'REIT - Residential': 'Equity Real Estate Investment Trusts (REITs)',
    'REIT - Retail': 'Equity Real Estate Investment Trusts (REITs)',
    'REIT - Specialty': 'Equity Real Estate Investment Trusts (REITs)',
    'REIT - Mortgage': 'Equity Real Estate Investment Trusts (REITs)',
    'Real Estate Services': 'Real Estate Management & Development',
    'Real Estate - Development': 'Real Estate Management & Development',
    'Real Estate - Diversified': 'Real Estate Management & Development',
    # Telecom + media
    'Internet Content & Information': 'Media & Entertainment',
    'Entertainment': 'Media & Entertainment',
    'Broadcasting': 'Media & Entertainment',
    'Publishing': 'Media & Entertainment',
    'Advertising Agencies': 'Media & Entertainment',
    'Electronic Gaming & Multimedia': 'Media & Entertainment',
    # Utilities
    'Utilities - Renewable': 'Utilities',
    'Utilities - Regulated Electric': 'Utilities',
    'Utilities - Regulated Gas': 'Utilities',
    'Utilities - Regulated Water': 'Utilities',
    'Utilities - Independent Power Producers': 'Utilities',
    'Utilities - Diversified': 'Utilities',
}


def consolidate(universe_name):
    db = MarketDB()
    cur = db.conn.cursor()
    rows = cur.execute("""
        SELECT s.ticker, s.sector FROM stocks s
        JOIN universes u ON u.id = s.universe_id WHERE u.name = ?
    """, (universe_name,)).fetchall()
    print(f"{universe_name}: {len(rows)} stocks")

    # Read gic_group too (that's what fetch_data.py actually uses)
    rows_gg = cur.execute("""
        SELECT s.ticker, s.gic_group FROM stocks s
        JOIN universes u ON u.id = s.universe_id WHERE u.name = ?
    """, (universe_name,)).fetchall()

    n_changed = 0
    n_unmapped = set()
    for ticker, gg in rows_gg:
        if not gg:
            continue
        if gg in MAP:
            new_gg = MAP[gg]
            cur.execute("""
                UPDATE stocks SET gic_group = ?, sector = ?
                WHERE ticker = ? AND universe_id = (SELECT id FROM universes WHERE name = ?)
            """, (new_gg, new_gg, ticker, universe_name))
            n_changed += 1
        else:
            n_unmapped.add(gg)
    db.conn.commit()
    print(f"  Updated: {n_changed} rows (gic_group + sector both)")

    # Show what's left
    remaining = cur.execute("""
        SELECT DISTINCT s.gic_group FROM stocks s
        JOIN universes u ON u.id = s.universe_id WHERE u.name = ?
        ORDER BY s.gic_group
    """, (universe_name,)).fetchall()
    sectors = [r[0] for r in remaining]
    print(f"  Distinct sectors after: {len(sectors)}")

    # Identify any remaining non-canonical (not in the 25-group set)
    canonical = {
        'Automobiles & Components','Banks','Capital Goods',
        'Commercial & Professional Services',
        'Consumer Discretionary Distribution & Retail',
        'Consumer Durables & Apparel','Consumer Services',
        'Consumer Staples Distribution & Retail','Energy',
        'Equity Real Estate Investment Trusts (REITs)',
        'Financial Services','Food, Beverage & Tobacco',
        'Health Care Equipment & Services','Household & Personal Products',
        'Insurance','Materials','Media & Entertainment',
        'Pharmaceuticals, Biotechnology & Life Sciences',
        'Real Estate Management & Development',
        'Semiconductors & Semiconductor Equipment','Software & Services',
        'Technology Hardware & Equipment','Telecommunication Services',
        'Transportation','Utilities',
    }
    non_canon = [s for s in sectors if s not in canonical]
    if non_canon:
        print(f"  Still non-canonical (need manual mapping): {non_canon}")
    db.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--universe', required=True)
    args = p.parse_args()
    consolidate(args.universe)
