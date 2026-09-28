#!/usr/bin/env python3
"""
RBI Filter Sensitivity Analysis - Full Analysis Runner

This script orchestrates the complete filter sensitivity analysis:
1. Build universe (if needed)
2. Fetch data (if needed)
3. Run baseline + ablation tests
4. Generate sensitivity report

Usage:
    python analyze_filters.py --start 2025-01-01 --end 2025-12-31
    python analyze_filters.py --start 2025-01-01 --end 2025-12-31 --skip-fetch
"""

import os
import sys
import json
import argparse
from datetime import datetime
from typing import Dict, List, Tuple

import pandas as pd

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    DEFAULT_SYMBOLS, DEFAULT_INITIAL_CASH,
    NEAR_20_MA_THRESHOLDS, ABLATION_CONFIGS,
    SMA_SHORT, SMA_LONG, PROFIT_TARGET_R, CAPITAL_ALLOCATION
)
import database as db
from backtest import (
    load_or_fetch_data, add_indicators, detect_patterns,
    generate_signals, simulate_trades_all_strategies,
    print_results_all_strategies, save_results_all_strategies
)
from whatif import simulate_rejected_trades, calculate_filter_impact, print_filter_impact
from reports import generate_html_report, generate_sensitivity_report, generate_combined_report, save_run_history


def run_analysis(symbols: List[str], start_date: str, end_date: str,
                 initial_cash: float, skip_fetch: bool = False) -> Dict:
    """
    Run complete filter sensitivity analysis.

    Returns dict with all results.
    """
    print("=" * 70)
    print("RBI FILTER SENSITIVITY ANALYSIS")
    print("=" * 70)
    print(f"Symbols: {len(symbols)}")
    print(f"Period: {start_date} to {end_date}")
    print(f"Initial Cash: ${initial_cash:,.0f}")
    print("=" * 70)

    db.init_db()

    # Step 1: Load/fetch data
    print("\n[1/5] Loading data...")
    all_data = load_or_fetch_data(symbols, start_date, end_date, force_refresh=not skip_fetch)

    if not all_data:
        print("ERROR: No data loaded. Check IBKR connection.")
        return None

    print(f"  Loaded data for {len(all_data)} symbols")

    # Step 2: Run baseline analysis
    print("\n[2/5] Running baseline analysis (1% threshold)...")
    baseline_results = run_single_config(
        all_data, initial_cash, start_date, end_date, symbols,
        threshold='1pct', ablation=None
    )

    # Step 3: Run threshold variants
    print("\n[3/5] Running threshold variants...")
    threshold_results = {}
    for threshold_label in ['2pct', '5pct', '10pct']:
        print(f"\n  Testing {threshold_label}...")
        threshold_results[threshold_label] = run_single_config(
            all_data, initial_cash, start_date, end_date, symbols,
            threshold=threshold_label, ablation=None
        )

    # Step 4: Run ablation tests
    print("\n[4/5] Running ablation tests...")
    ablation_results = {}
    for ablation_name in ['near_ma', 'pop', 'body_ratio', 'max_ignored']:
        print(f"\n  Ablation: {ablation_name}...")
        ablation_results[ablation_name] = run_single_config(
            all_data, initial_cash, start_date, end_date, symbols,
            threshold='1pct', ablation=ablation_name
        )

    # Step 5: Generate reports
    print("\n[5/5] Generating reports...")

    # Build filter impact from baseline rejection stats and what-if
    filter_impact = calculate_filter_impact(
        baseline_results['rejection_stats'],
        baseline_results['whatif_results']
    )

    print_filter_impact(filter_impact)

    # Generate MEGA DASHBOARD (combined report)
    run_id = f"sensitivity_{datetime.now().strftime('%Y-%m-%d_%H%M')}"

    # Package threshold results for combined report
    threshold_results_pkg = {'baseline': {'results': baseline_results['results']}}
    for label, results in threshold_results.items():
        threshold_results_pkg[label] = {'results': results['results']}

    # Package ablation results
    ablation_results_pkg = {'baseline': {'results': baseline_results['results']}}
    for name, results in ablation_results.items():
        ablation_results_pkg[name] = {'results': results['results']}

    report_path = generate_combined_report(
        all_results=baseline_results['results'],
        initial_capital=initial_cash,
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
        symbols=symbols,
        filter_impact=filter_impact,
        rejection_stats=baseline_results['rejection_stats'],
        threshold_results=threshold_results_pkg,
        ablation_results=ablation_results_pkg,
        output_dir='reports'
    )

    # Also generate the simple sensitivity report for backwards compatibility
    generate_sensitivity_report(
        filter_impact,
        baseline_results['rejection_stats'],
        baseline_results['whatif_results'],
        run_id,
        output_dir='reports'
    )

    # Build summary
    summary = {
        'run_id': run_id,
        'symbols': symbols,
        'period': {'start': start_date, 'end': end_date},
        'baseline': {
            'trades': baseline_results['metrics'].get('A', {}).get('trades', 0),
            'return_pct': baseline_results['metrics'].get('A', {}).get('return_pct', 0),
        },
        'filter_impact': filter_impact,
        'threshold_comparison': {
            threshold: {
                'trades': results['metrics'].get('A', {}).get('trades', 0),
                'return_pct': results['metrics'].get('A', {}).get('return_pct', 0),
            }
            for threshold, results in threshold_results.items()
        },
        'ablation_comparison': {
            name: {
                'trades': results['metrics'].get('A', {}).get('trades', 0),
                'return_pct': results['metrics'].get('A', {}).get('return_pct', 0),
            }
            for name, results in ablation_results.items()
        }
    }

    # Save summary JSON
    summary_path = os.path.join('data/results', f'analysis_{run_id}.json')
    os.makedirs('data/results', exist_ok=True)
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\nAnalysis complete!")
    print(f"  Summary: {summary_path}")
    print(f"  Mega Dashboard: reports/mega_dashboard_{run_id}.html")
    print(f"  Sensitivity Report: reports/sensitivity_{run_id}.html")

    return summary


def run_single_config(all_data: Dict[str, pd.DataFrame],
                       initial_cash: float,
                       start_date: str, end_date: str,
                       symbols: List[str],
                       threshold: str = '1pct',
                       ablation: str = None) -> Dict:
    """
    Run backtest with a single configuration.
    Returns dict with trades, metrics, rejection stats, whatif results.
    """
    near_ma_threshold = NEAR_20_MA_THRESHOLDS.get(threshold, 0.01)
    ablation_config = ABLATION_CONFIGS.get(ablation, {}) if ablation else {}

    # Process data
    processed_data = {}
    all_rejection_stats = {}
    all_rejected_signals = []

    for symbol, df in all_data.items():
        # Add indicators
        df_with_indicators = add_indicators(df.copy(), near_ma_threshold=near_ma_threshold)

        # Detect patterns with ablation config
        df_processed, rejection_stats, rejected_signals = detect_patterns(
            df_with_indicators, ablation=ablation_config
        )

        processed_data[symbol] = df_processed

        # Aggregate stats
        for key, value in rejection_stats.items():
            all_rejection_stats[key] = all_rejection_stats.get(key, 0) + value
        all_rejected_signals.extend(rejected_signals)

    # Generate signals
    signals = generate_signals(processed_data)

    # Simulate trades
    if not signals.empty:
        all_results = simulate_trades_all_strategies(signals, processed_data, initial_cash)
    else:
        all_results = {}

    # Run what-if simulation on rejected signals
    whatif_results = simulate_rejected_trades(
        all_rejected_signals, processed_data, initial_cash
    )

    # Extract metrics
    metrics = {
        strategy: result[1]
        for strategy, result in all_results.items()
    }

    return {
        'trades': {s: r[0] for s, r in all_results.items()},
        'metrics': metrics,
        'rejection_stats': all_rejection_stats,
        'rejected_signals': all_rejected_signals,
        'whatif_results': whatif_results,
    }


def main():
    parser = argparse.ArgumentParser(description='RBI Filter Sensitivity Analysis')
    parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--symbols', nargs='+', default=DEFAULT_SYMBOLS,
                       help='Symbols to analyze (default: 5 test symbols)')
    parser.add_argument('--symbols-file', help='JSON file with symbol list')
    parser.add_argument('--cash', type=float, default=DEFAULT_INITIAL_CASH,
                       help='Initial cash')
    parser.add_argument('--skip-fetch', action='store_true',
                       help='Skip data fetching, use cached data')
    args = parser.parse_args()

    # Load symbols from file if specified
    if args.symbols_file:
        with open(args.symbols_file, 'r') as f:
            data = json.load(f)
            symbols = data.get('symbols', data) if isinstance(data, dict) else data
    else:
        symbols = args.symbols

    # Run analysis
    run_analysis(
        symbols=symbols,
        start_date=args.start,
        end_date=args.end,
        initial_cash=args.cash,
        skip_fetch=args.skip_fetch
    )


if __name__ == '__main__':
    main()
