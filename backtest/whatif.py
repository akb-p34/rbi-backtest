#!/usr/bin/env python3
"""
What-If Simulation for RBI Filter Sensitivity Analysis.
Simulates P&L for rejected trades to quantify filter impact.

Usage:
    from whatif import simulate_rejected_trades
    results = simulate_rejected_trades(rejected_signals, all_data, initial_cash)
"""

from typing import List, Dict, Tuple
import pandas as pd
import numpy as np

from strategies import STRATEGIES, run_strategy
from config import (
    PROFIT_TARGET_R, CAPITAL_ALLOCATION,
    COMMISSION_PER_SHARE, MIN_COMMISSION, MAX_COMMISSION_PCT
)


def calculate_commission(shares: int, price: float) -> float:
    """Calculate IBKR-style commission."""
    trade_value = shares * price
    commission = shares * COMMISSION_PER_SHARE
    commission = max(commission, MIN_COMMISSION)
    commission = min(commission, trade_value * MAX_COMMISSION_PCT)
    return commission


def simulate_single_trade(signal: Dict, symbol_data: pd.DataFrame,
                          strategy_name: str, initial_cash: float) -> Dict:
    """
    Simulate a single rejected trade using specified exit strategy.

    Args:
        signal: Rejected signal dict with trigger_price, stop_price, etc.
        symbol_data: DataFrame with OHLCV data for the symbol
        strategy_name: Exit strategy to use (A, B1, B2, B3, B4, B5)
        initial_cash: Starting capital

    Returns:
        Dict with trade result or None if can't simulate
    """
    # Skip signals that don't have full trade params
    if 'trigger_price' not in signal or 'stop_price' not in signal:
        return None

    entry_time = signal['timestamp']
    entry_price = signal.get('open_price', signal['trigger_price'])

    # Get appropriate stop price based on strategy
    if strategy_name == 'B4':
        stop_price = signal.get('stop_price_b4', signal['stop_price'])
    elif strategy_name == 'B5':
        stop_price = signal.get('stop_price_b5', signal['stop_price'])
    else:
        stop_price = signal['stop_price']

    target_price = signal.get('target_price')
    if target_price is None:
        risk = entry_price - stop_price
        target_price = entry_price + (PROFIT_TARGET_R * risk)

    # Calculate position size
    available_capital = initial_cash * CAPITAL_ALLOCATION
    shares = int(available_capital / entry_price)

    if shares <= 0:
        return None

    # Get future bars after entry
    future_bars = symbol_data[symbol_data.index > entry_time]

    if future_bars.empty:
        return None

    # Run exit strategy
    exit_result = run_strategy(strategy_name, entry_price, stop_price, target_price, future_bars)

    if exit_result is None:
        return None

    exit_price = exit_result['exit_price']
    exit_time = exit_result['exit_time']
    exit_type = exit_result['exit_type']

    # Calculate P&L
    entry_commission = calculate_commission(shares, entry_price)
    exit_commission = calculate_commission(shares, exit_price)
    gross_pnl = (exit_price - entry_price) * shares
    net_pnl = gross_pnl - entry_commission - exit_commission

    risk = entry_price - stop_price
    r_multiple = (exit_price - entry_price) / risk if risk > 0 else 0

    return {
        'strategy': strategy_name,
        'symbol': signal.get('symbol'),
        'rejection_reason': signal.get('rejection_reason'),
        'entry_time': entry_time,
        'exit_time': exit_time,
        'entry_price': entry_price,
        'exit_price': exit_price,
        'shares': shares,
        'gross_pnl': gross_pnl,
        'commission': entry_commission + exit_commission,
        'net_pnl': net_pnl,
        'r_multiple': r_multiple,
        'exit_type': exit_type,
    }


def simulate_rejected_trades(rejected_signals: List[Dict],
                              all_data: Dict[str, pd.DataFrame],
                              initial_cash: float) -> Dict[str, Dict]:
    """
    Simulate all rejected trades with all exit strategies.

    Args:
        rejected_signals: List of rejected signal dicts from detect_patterns
        all_data: Dict of {symbol: DataFrame}
        initial_cash: Starting capital

    Returns:
        Dict with results by rejection reason and strategy:
        {
            'by_reason': {
                'near_20_ma': {'trades': [...], 'total_pnl': float, 'count': int},
                ...
            },
            'by_strategy': {
                'A': {'trades': [...], 'total_pnl': float, 'count': int},
                ...
            },
            'summary': {...}
        }
    """
    results = {
        'by_reason': {},
        'by_strategy': {},
        'all_trades': [],
        'summary': {}
    }

    # Filter signals that have full trade params (near_20_ma rejections)
    tradeable_signals = [s for s in rejected_signals if 'trigger_price' in s]

    if not tradeable_signals:
        print("No tradeable rejected signals found for what-if simulation")
        return results

    print(f"\nSimulating {len(tradeable_signals)} rejected trades...")

    for strategy_name in STRATEGIES.keys():
        strategy_trades = []
        strategy_pnl = 0

        for signal in tradeable_signals:
            symbol = signal.get('symbol')
            if symbol not in all_data:
                continue

            trade = simulate_single_trade(
                signal, all_data[symbol], strategy_name, initial_cash
            )

            if trade:
                strategy_trades.append(trade)
                strategy_pnl += trade['net_pnl']
                results['all_trades'].append(trade)

                # Track by rejection reason
                reason = signal.get('rejection_reason', 'unknown')
                if reason not in results['by_reason']:
                    results['by_reason'][reason] = {
                        'trades': [], 'total_pnl': 0, 'count': 0
                    }
                results['by_reason'][reason]['trades'].append(trade)
                results['by_reason'][reason]['total_pnl'] += trade['net_pnl']
                results['by_reason'][reason]['count'] += 1

        results['by_strategy'][strategy_name] = {
            'trades': strategy_trades,
            'total_pnl': strategy_pnl,
            'count': len(strategy_trades),
            'avg_pnl': strategy_pnl / len(strategy_trades) if strategy_trades else 0,
            'win_rate': sum(1 for t in strategy_trades if t['net_pnl'] > 0) / len(strategy_trades) * 100 if strategy_trades else 0,
        }

        print(f"  {strategy_name}: {len(strategy_trades)} trades, ${strategy_pnl:,.2f} total P&L")

    # Build summary
    total_trades = len(results['all_trades'])
    total_pnl = sum(t['net_pnl'] for t in results['all_trades'])

    results['summary'] = {
        'total_rejected_signals': len(rejected_signals),
        'tradeable_signals': len(tradeable_signals),
        'simulated_trades': total_trades,
        'total_hypothetical_pnl': total_pnl,
        'by_reason_summary': {
            reason: {
                'count': data['count'],
                'total_pnl': data['total_pnl'],
                'avg_pnl': data['total_pnl'] / data['count'] if data['count'] > 0 else 0
            }
            for reason, data in results['by_reason'].items()
        }
    }

    return results


def calculate_filter_impact(rejection_stats: Dict, whatif_results: Dict) -> Dict:
    """
    Calculate the impact of each filter based on rejection stats and what-if results.

    Args:
        rejection_stats: Dict from detect_patterns
        whatif_results: Dict from simulate_rejected_trades

    Returns:
        Dict with filter impact analysis:
        {
            'filter_name': {
                'rejected_count': int,
                'missed_pnl': float,
                'pct_of_total_alpha': float,
            }
        }
    """
    impact = {}

    # Map rejection reasons to filter names
    filter_map = {
        'picture_of_power': 'Picture of Power',
        'near_20_ma': 'Near 20 MA',
        'no_ignored_bar': 'No Ignored Bar',
        'ignored_bar_size': 'Ignored Bar Size',
        'entry_trigger': 'Entry Trigger',
        'max_ignored_bars': 'Max Ignored Bars',
    }

    total_missed_pnl = whatif_results.get('summary', {}).get('total_hypothetical_pnl', 0)

    for reason, filter_name in filter_map.items():
        rejected_count = rejection_stats.get(f'rejected_{reason}', 0)

        reason_data = whatif_results.get('by_reason', {}).get(reason, {})
        missed_pnl = reason_data.get('total_pnl', 0)

        impact[filter_name] = {
            'rejected_count': rejected_count,
            'missed_pnl': missed_pnl,
            'pct_of_total_alpha': (missed_pnl / total_missed_pnl * 100) if total_missed_pnl != 0 else 0,
        }

    # Sort by missed P&L (most impactful first)
    impact = dict(sorted(
        impact.items(),
        key=lambda x: abs(x[1]['missed_pnl']),
        reverse=True
    ))

    return impact


def print_filter_impact(impact: Dict):
    """Print formatted filter impact table."""
    print("\n" + "=" * 70)
    print("FILTER IMPACT ANALYSIS")
    print("=" * 70)
    print(f"{'Filter':<25} {'Rejected':<12} {'Missed P&L':<15} {'% of Alpha':<12}")
    print("-" * 70)

    for filter_name, data in impact.items():
        print(f"{filter_name:<25} {data['rejected_count']:<12,} ${data['missed_pnl']:>12,.2f} {data['pct_of_total_alpha']:>10.1f}%")

    print("=" * 70)


if __name__ == '__main__':
    # Test with sample data
    print("What-If Simulation module loaded.")
    print("Use: from whatif import simulate_rejected_trades")
