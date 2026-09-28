#!/usr/bin/env python3
"""
RBI Strategy Backtest - Clean Implementation
Combines bias-free logic from backtestNew with simple detection from backtestIBKR.

Usage:
    python backtest.py --start 2025-01-01 --end 2025-01-31
    python backtest.py --start 2025-01-01 --end 2025-01-31 --symbols TSLA AAPL
"""

import os
import sys
import json
import argparse
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import pandas as pd
import numpy as np
import pytz

# Import configuration
from config import (
    TIMEFRAME, SMA_SHORT, SMA_LONG,
    IGNORED_BODY_MAX_RATIO, MAX_IGNORED_BARS, ENTRY_BUFFER, STOP_BUFFER,
    STOP_BUFFER_B4, STOP_BUFFER_B5,
    NEAR_20_MA_THRESHOLD, NEAR_20_MA_THRESHOLDS, SMA_SLOPE_LOOKBACK,
    PROFIT_TARGET_R, CAPITAL_ALLOCATION, COMMISSION_PER_SHARE, MIN_COMMISSION, MAX_COMMISSION_PCT,
    MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE, MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE,
    EOD_HOUR, EOD_MINUTE,
    DEFAULT_SYMBOLS, DEFAULT_INITIAL_CASH,
    RAW_DATA_DIR, PROCESSED_DATA_DIR, RESULTS_DIR,
    IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID,
    ABLATION_CONFIGS,
)

# Import database module
import database as db

# Import exit strategies
from strategies import STRATEGIES, run_strategy

# Import reporting (optional if plotly not installed)
try:
    from reports import generate_html_report, save_run_history
    REPORTS_AVAILABLE = True
except ImportError:
    REPORTS_AVAILABLE = False

EASTERN = pytz.timezone('US/Eastern')


def setup_directories():
    """Create data directories if they don't exist."""
    for directory in [RAW_DATA_DIR, PROCESSED_DATA_DIR, RESULTS_DIR]:
        os.makedirs(directory, exist_ok=True)


def get_config_hash(start_date: str, end_date: str, symbols: List[str]) -> str:
    """Generate hash for caching based on configuration."""
    config_str = f"{start_date}|{end_date}|{','.join(sorted(symbols))}|{SMA_SHORT}|{SMA_LONG}|{TIMEFRAME}"
    return hashlib.md5(config_str.encode()).hexdigest()[:12]


def calculate_commission(shares: int, price: float) -> float:
    """Calculate IBKR-style commission."""
    trade_value = shares * price
    commission = shares * COMMISSION_PER_SHARE
    commission = max(commission, MIN_COMMISSION)
    commission = min(commission, trade_value * MAX_COMMISSION_PCT)
    return commission


def fetch_ibkr_data(symbols: List[str], start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
    """
    Fetch historical data from IBKR using chunked requests.

    IBKR limits ~2,000 bars per request for 2-minute data.
    We use 10-day chunks (~1,440 bars) and walk backwards from end_date.
    """
    import time

    try:
        from ib_insync import IB, Stock
    except ImportError:
        print("ERROR: ib_insync not installed. Run: pip install ib_insync")
        sys.exit(1)

    ib = IB()
    all_data = {}

    # Parse dates for comparison
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt_parsed = datetime.strptime(end_date, "%Y-%m-%d")

    # Estimate chunks needed (10 trading days per chunk, ~252 trading days per year)
    trading_days = len(pd.date_range(start_date, end_date, freq='B'))
    estimated_chunks = max(1, (trading_days + 9) // 10)  # Round up

    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID)
        print(f"Connected to IBKR at {IBKR_HOST}:{IBKR_PORT}")

        for sym_idx, symbol in enumerate(symbols):
            print(f"  Fetching {symbol}... [{sym_idx+1}/{len(symbols)}]")
            contract = Stock(symbol, 'SMART', 'USD')

            all_bars = []
            dt = end_dt_parsed.strftime("%Y%m%d 16:00:00 US/Eastern")
            chunk_num = 0

            while True:
                chunk_num += 1
                print(f"    Chunk {chunk_num}/{estimated_chunks}: fetching...", end='', flush=True)

                try:
                    bars = ib.reqHistoricalData(
                        contract,
                        endDateTime=dt,
                        durationStr='10 D',  # Safe chunk size (~1,440 bars for 2-min)
                        barSizeSetting=TIMEFRAME,
                        whatToShow="TRADES",
                        useRTH=True,
                        formatDate=2
                    )
                except Exception as e:
                    print(f" error: {e}")
                    break

                if not bars:
                    print(" no data")
                    break

                print(f" got {len(bars)} bars")
                all_bars.extend(bars)

                # Get oldest bar date to continue walking backwards
                oldest_bar = bars[0]
                oldest_date = oldest_bar.date

                # Check if we've reached the start date
                if isinstance(oldest_date, datetime):
                    oldest_dt = oldest_date.replace(tzinfo=None) if oldest_date.tzinfo else oldest_date
                else:
                    oldest_dt = datetime.combine(oldest_date, datetime.min.time())

                if oldest_dt <= start_dt:
                    break

                # Set next end datetime to oldest bar's date (walk backwards)
                dt = oldest_dt.strftime("%Y%m%d %H:%M:%S US/Eastern")

                # IBKR pacing requirement: 1 second between requests
                time.sleep(1)

            if not all_bars:
                print(f"    WARNING: No data for {symbol}")
                continue

            # Create DataFrame from all chunks
            df = pd.DataFrame({
                'symbol': symbol,
                'open': [b.open for b in all_bars],
                'high': [b.high for b in all_bars],
                'low': [b.low for b in all_bars],
                'close': [b.close for b in all_bars],
                'volume': [b.volume for b in all_bars]
            }, index=[b.date for b in all_bars])

            df.index = pd.to_datetime(df.index).tz_convert(EASTERN)
            df.index.name = 'timestamp'

            # Filter to requested date range and remove duplicates
            start_ts = pd.Timestamp(start_date, tz=EASTERN)
            end_ts = pd.Timestamp(end_date, tz=EASTERN) + pd.Timedelta(days=1)
            df = df[(df.index >= start_ts) & (df.index < end_ts)]
            df = df[~df.index.duplicated(keep='first')]
            df = df.sort_index()

            all_data[symbol] = df
            print(f"    Total: {len(df)} bars for {symbol}")

    except Exception as e:
        print(f"IBKR Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if ib.isConnected():
            ib.disconnect()

    return all_data


def load_or_fetch_data(symbols: List[str], start_date: str, end_date: str,
                       force_refresh: bool = False) -> Dict[str, pd.DataFrame]:
    """Load data from SQLite cache or fetch from IBKR."""
    # Initialize database
    db.init_db()

    all_data = {}
    missing_symbols = []

    # Check SQLite cache first
    if not force_refresh:
        cached_data = db.get_bars(symbols, start_date, end_date)
        for symbol in symbols:
            if symbol in cached_data and not cached_data[symbol].empty:
                all_data[symbol] = cached_data[symbol]
                print(f"  Loaded cached data for {symbol} ({len(cached_data[symbol])} bars)")
            else:
                missing_symbols.append(symbol)
    else:
        missing_symbols = symbols.copy()

    # Fetch missing data from IBKR
    if missing_symbols:
        print(f"Fetching data from IBKR for: {missing_symbols}")
        fetched = fetch_ibkr_data(missing_symbols, start_date, end_date)

        for symbol, df in fetched.items():
            # Store raw data in SQLite
            rows = db.store_bars(df, symbol)
            print(f"    Stored {rows} bars for {symbol} in SQLite")
            all_data[symbol] = df

    return all_data


def add_indicators(df: pd.DataFrame, near_ma_threshold: float = None) -> pd.DataFrame:
    """Add SMA indicators and setup conditions.

    Args:
        df: DataFrame with OHLCV data
        near_ma_threshold: Override for NEAR_20_MA_THRESHOLD (e.g., 0.01, 0.02, 0.05)
    """
    df = df.copy()

    # Use provided threshold or default from config
    threshold = near_ma_threshold if near_ma_threshold is not None else NEAR_20_MA_THRESHOLD

    # SMAs
    df['sma_short'] = df['close'].rolling(window=SMA_SHORT).mean()
    df['sma_long'] = df['close'].rolling(window=SMA_LONG).mean()

    # SMA slope (for trend confirmation)
    df['sma_slope'] = df['sma_short'].diff(SMA_SLOPE_LOOKBACK)

    # Picture of Power: price > SMA_short > SMA_long AND SMA_short rising
    df['picture_of_power'] = (
        (df['close'] > df['sma_short']) &
        (df['sma_short'] > df['sma_long']) &
        (df['sma_slope'] > 0)
    )

    # Near 20 MA check (optional filter)
    if threshold is not None:
        df['near_sma'] = (abs(df['close'] - df['sma_short']) / df['sma_short']) <= threshold
    else:
        df['near_sma'] = True

    return df


def detect_patterns(df: pd.DataFrame, ablation: Dict = None) -> Tuple[pd.DataFrame, Dict, List]:
    """
    Detect RBI patterns using simple IBKR-style detection.
    Labels: 'control', 'ignored', 'entry', or None
    Also calculates B4/B5 stop prices for multi-stop testing.

    Args:
        df: DataFrame with OHLCV and indicator columns
        ablation: Dict of filters to disable for ablation testing
            - 'picture_of_power': bool - if False, disable PoP filter
            - 'max_ignored_bars': int - override max ignored bars
            - 'ignored_body_max_ratio': float - override body ratio (1.0 = disabled)

    Returns:
        (df, rejection_stats, rejected_signals)
    """
    df = df.copy()
    df['label'] = None
    df['entry_signal'] = False
    df['trigger_price'] = np.nan
    df['stop_price'] = np.nan
    df['stop_price_b4'] = np.nan  # Tighter stop ($0.005)
    df['stop_price_b5'] = np.nan  # Looser stop ($0.02)
    df['target_price'] = np.nan

    # Ablation overrides
    ablation = ablation or {}
    check_pop = ablation.get('picture_of_power', True)
    max_ignored = ablation.get('max_ignored_bars', MAX_IGNORED_BARS)
    body_ratio = ablation.get('ignored_body_max_ratio', IGNORED_BODY_MAX_RATIO)

    # Rejection tracking
    rejection_stats = {
        'total_control_bars': 0,
        'rejected_picture_of_power': 0,
        'rejected_near_20_ma': 0,
        'rejected_max_ignored_bars': 0,
        'rejected_ignored_bar_size': 0,
        'rejected_entry_trigger': 0,
        'rejected_no_ignored_bar': 0,
        'accepted': 0,
    }

    rejected_signals = []

    n = len(df)
    i = SMA_LONG  # Start after we have enough data for indicators

    while i < n - 1:
        # Check for Control Bar: bullish candle
        if df['close'].iloc[i] > df['open'].iloc[i]:
            rejection_stats['total_control_bars'] += 1

            # Picture of Power check (can be disabled via ablation)
            if check_pop and not df['picture_of_power'].iloc[i]:
                rejection_stats['rejected_picture_of_power'] += 1
                rejected_signals.append({
                    'timestamp': df.index[i],
                    'symbol': df['symbol'].iloc[i] if 'symbol' in df.columns else None,
                    'rejection_reason': 'picture_of_power',
                    'control_idx': i,
                })
                i += 1
                continue

            control_idx = i
            control_body = df['close'].iloc[i] - df['open'].iloc[i]

            # Look for Ignored Bar(s)
            ignored_count = 0
            ignored_idx = i + 1
            rejection_reason = None

            while ignored_idx < n and ignored_count < max_ignored:
                # Must be bearish
                if df['close'].iloc[ignored_idx] >= df['open'].iloc[ignored_idx]:
                    break

                # Must be small (can be relaxed via ablation)
                ignored_body = df['open'].iloc[ignored_idx] - df['close'].iloc[ignored_idx]
                if ignored_body > body_ratio * control_body:
                    if ignored_count == 0:
                        rejection_reason = 'ignored_bar_size'
                    break

                # Must still be in Picture of Power (if checking)
                if check_pop and not df['picture_of_power'].iloc[ignored_idx]:
                    if ignored_count == 0:
                        rejection_reason = 'picture_of_power'
                    break

                ignored_count += 1
                ignored_idx += 1

            # Need at least one ignored bar
            if ignored_count == 0:
                if rejection_reason == 'ignored_bar_size':
                    rejection_stats['rejected_ignored_bar_size'] += 1
                elif rejection_reason == 'picture_of_power':
                    rejection_stats['rejected_picture_of_power'] += 1
                else:
                    rejection_stats['rejected_no_ignored_bar'] += 1
                rejected_signals.append({
                    'timestamp': df.index[i],
                    'symbol': df['symbol'].iloc[i] if 'symbol' in df.columns else None,
                    'rejection_reason': rejection_reason or 'no_ignored_bar',
                    'control_idx': i,
                })
                i += 1
                continue

            # Check for entry on next bar
            entry_idx = ignored_idx
            if entry_idx >= n:
                break

            last_ignored_idx = ignored_idx - 1
            trigger_price = df['high'].iloc[last_ignored_idx] + ENTRY_BUFFER
            ignored_low = df['low'].iloc[last_ignored_idx]

            # Calculate stop prices for all strategies
            stop_price = ignored_low - STOP_BUFFER       # Standard ($0.01)
            stop_price_b4 = ignored_low - STOP_BUFFER_B4  # Tighter ($0.005)
            stop_price_b5 = ignored_low - STOP_BUFFER_B5  # Looser ($0.02)

            # Entry condition: current bar's OPEN breaks above trigger (bias-free)
            if df['open'].iloc[entry_idx] > trigger_price:
                risk = trigger_price - stop_price
                target_price = trigger_price + (PROFIT_TARGET_R * risk)

                # MANDATORY: Entry must be near 20 MA (Rule 3)
                if not df['near_sma'].iloc[entry_idx]:
                    rejection_stats['rejected_near_20_ma'] += 1
                    rejected_signals.append({
                        'timestamp': df.index[entry_idx],
                        'symbol': df['symbol'].iloc[entry_idx] if 'symbol' in df.columns else None,
                        'rejection_reason': 'near_20_ma',
                        'trigger_price': trigger_price,
                        'stop_price': stop_price,
                        'stop_price_b4': stop_price_b4,
                        'stop_price_b5': stop_price_b5,
                        'target_price': target_price,
                        'open_price': df['open'].iloc[entry_idx],
                    })
                    i = entry_idx + 1
                    continue

                # ACCEPTED
                rejection_stats['accepted'] += 1

                # Label the bars
                df.iloc[control_idx, df.columns.get_loc('label')] = 'control'
                for j in range(control_idx + 1, last_ignored_idx + 1):
                    df.iloc[j, df.columns.get_loc('label')] = 'ignored'
                df.iloc[entry_idx, df.columns.get_loc('label')] = 'entry'
                df.iloc[entry_idx, df.columns.get_loc('entry_signal')] = True
                df.iloc[entry_idx, df.columns.get_loc('trigger_price')] = trigger_price
                df.iloc[entry_idx, df.columns.get_loc('stop_price')] = stop_price
                df.iloc[entry_idx, df.columns.get_loc('stop_price_b4')] = stop_price_b4
                df.iloc[entry_idx, df.columns.get_loc('stop_price_b5')] = stop_price_b5
                df.iloc[entry_idx, df.columns.get_loc('target_price')] = target_price

                i = entry_idx + 1
                continue
            else:
                rejection_stats['rejected_entry_trigger'] += 1

        i += 1

    return df, rejection_stats, rejected_signals


def detect_patterns_simple(df: pd.DataFrame) -> pd.DataFrame:
    """Backward-compatible wrapper - returns only DataFrame."""
    df_result, _, _ = detect_patterns(df)
    return df_result


def generate_signals(all_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Generate trade signals from all symbols, sorted chronologically."""
    signals = []

    for symbol, df in all_data.items():
        entries = df[df['entry_signal'] == True]

        for idx, row in entries.iterrows():
            # Calculate near_sma_pct for verification
            sma_short = row.get('sma_short')
            close = row['close']
            near_sma_pct = abs(close - sma_short) / sma_short if sma_short else None

            signals.append({
                'timestamp': idx,
                'symbol': symbol,
                'entry_price': row['trigger_price'],
                'stop_price': row['stop_price'],
                'stop_price_b4': row['stop_price_b4'],  # Tighter stop for B4
                'stop_price_b5': row['stop_price_b5'],  # Looser stop for B5
                'target_price': row['target_price'],
                'open_price': row['open'],  # Actual fill price (bias-free)
                'near_sma_pct': near_sma_pct,
            })

    if not signals:
        return pd.DataFrame()

    signals_df = pd.DataFrame(signals)
    signals_df = signals_df.sort_values('timestamp').reset_index(drop=True)
    return signals_df


def simulate_trades_single_strategy(signals: pd.DataFrame, all_data: Dict[str, pd.DataFrame],
                                     initial_cash: float, strategy_name: str) -> Tuple[pd.DataFrame, Dict]:
    """
    Simulate trade execution for a single exit strategy.
    Uses the new strategies module for exit logic.
    """
    if signals.empty:
        return pd.DataFrame(), {'final_cash': initial_cash, 'trades': 0, 'strategy': strategy_name}

    trades = []
    cash = initial_cash

    for _, signal in signals.iterrows():
        # Check if we have enough capital
        available_capital = cash * CAPITAL_ALLOCATION
        entry_price = signal['open_price']  # Use actual open, not trigger (bias-free)
        shares = int(available_capital / entry_price)

        if shares <= 0:
            continue

        # Calculate entry commission
        entry_commission = calculate_commission(shares, entry_price)
        trade_cost = (shares * entry_price) + entry_commission

        if trade_cost > cash:
            shares = int((cash - MIN_COMMISSION) / entry_price)
            if shares <= 0:
                continue
            entry_commission = calculate_commission(shares, entry_price)
            trade_cost = (shares * entry_price) + entry_commission

        cash -= trade_cost

        # Get trade parameters
        symbol = signal['symbol']
        entry_time = signal['timestamp']
        target_price = signal['target_price']

        # Use appropriate stop price based on strategy
        if strategy_name == 'B4':
            stop_price = signal['stop_price_b4']
        elif strategy_name == 'B5':
            stop_price = signal['stop_price_b5']
        else:
            stop_price = signal['stop_price']

        # Get future bars for this symbol
        symbol_data = all_data[symbol]
        future_bars = symbol_data[symbol_data.index > entry_time]

        # Run exit strategy
        exit_result = run_strategy(strategy_name, entry_price, stop_price, target_price, future_bars)

        if exit_result is None:
            # No exit found, refund entry cost
            cash += trade_cost
            continue

        exit_price = exit_result['exit_price']
        exit_time = exit_result['exit_time']
        exit_type = exit_result['exit_type']

        # Calculate exit
        exit_commission = calculate_commission(shares, exit_price)
        exit_proceeds = (shares * exit_price) - exit_commission
        cash += exit_proceeds

        # Calculate metrics
        gross_pnl = (exit_price - entry_price) * shares
        total_commission = entry_commission + exit_commission
        net_pnl = gross_pnl - total_commission
        risk = entry_price - stop_price
        r_multiple = (exit_price - entry_price) / risk if risk > 0 else 0

        trades.append({
            'strategy': strategy_name,
            'symbol': symbol,
            'entry_time': entry_time,
            'exit_time': exit_time,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'shares': shares,
            'gross_pnl': gross_pnl,
            'commission': total_commission,
            'pnl': net_pnl,  # Net P&L
            'r_multiple': r_multiple,
            'exit_type': exit_type,
            'entry_commission': entry_commission,
            'exit_commission': exit_commission,
        })

    trades_df = pd.DataFrame(trades)

    # Calculate summary metrics
    if trades_df.empty:
        metrics = {'final_cash': cash, 'trades': 0, 'strategy': strategy_name}
    else:
        wins = trades_df[trades_df['pnl'] > 0]
        losses = trades_df[trades_df['pnl'] <= 0]

        metrics = {
            'strategy': strategy_name,
            'final_cash': cash,
            'trades': len(trades_df),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': len(wins) / len(trades_df) * 100 if len(trades_df) > 0 else 0,
            'total_pnl': trades_df['pnl'].sum(),
            'gross_pnl': trades_df['gross_pnl'].sum(),
            'avg_win': wins['pnl'].mean() if len(wins) > 0 else 0,
            'avg_loss': losses['pnl'].mean() if len(losses) > 0 else 0,
            'avg_r_multiple': trades_df['r_multiple'].mean(),
            'profit_factor': abs(wins['pnl'].sum() / losses['pnl'].sum()) if len(losses) > 0 and losses['pnl'].sum() != 0 else float('inf'),
            'total_commissions': trades_df['entry_commission'].sum() + trades_df['exit_commission'].sum(),
            'return_pct': (cash - initial_cash) / initial_cash * 100,
        }

    return trades_df, metrics


def simulate_trades_all_strategies(signals: pd.DataFrame, all_data: Dict[str, pd.DataFrame],
                                   initial_cash: float) -> Dict[str, Tuple[pd.DataFrame, Dict]]:
    """
    Run all 4 exit strategies on the same signals.
    Returns dict of {strategy_name: (trades_df, metrics)}.
    """
    results = {}
    for strategy_name in STRATEGIES.keys():
        trades_df, metrics = simulate_trades_single_strategy(signals, all_data, initial_cash, strategy_name)
        results[strategy_name] = (trades_df, metrics)
    return results


# Keep old function for backward compatibility
def simulate_trades(signals: pd.DataFrame, all_data: Dict[str, pd.DataFrame],
                    initial_cash: float, scenario: str = 'best') -> Tuple[pd.DataFrame, Dict]:
    """
    Backward-compatible wrapper. Uses Strategy A.
    scenario parameter is deprecated - always uses conservative (stop first).
    """
    return simulate_trades_single_strategy(signals, all_data, initial_cash, 'A')


def print_results_all_strategies(all_results: Dict[str, Tuple[pd.DataFrame, Dict]], initial_cash: float):
    """Print formatted results for all exit strategies."""
    print("\n" + "="*70)
    print("RBI STRATEGY BACKTEST RESULTS - ALL EXIT STRATEGIES")
    print("="*70)

    for strategy_name, (trades_df, metrics) in all_results.items():
        print(f"\n--- Strategy {strategy_name} ---")
        if metrics['trades'] == 0:
            print("  No trades executed")
            continue

        print(f"  Trades:         {metrics['trades']}")
        print(f"  Win Rate:       {metrics['win_rate']:.1f}% ({metrics['wins']}W / {metrics['losses']}L)")
        print(f"  Profit Factor:  {metrics['profit_factor']:.2f}")
        print(f"  Avg R-Multiple: {metrics['avg_r_multiple']:.2f}")
        print(f"  Avg Win:        ${metrics['avg_win']:,.2f}")
        print(f"  Avg Loss:       ${metrics['avg_loss']:,.2f}")
        print(f"  Gross P&L:      ${metrics.get('gross_pnl', 0):,.2f}")
        print(f"  Commissions:    ${metrics['total_commissions']:,.2f}")
        print(f"  Net P&L:        ${metrics['total_pnl']:,.2f}")
        print(f"  Return:         {metrics['return_pct']:.2f}%")
        print(f"  Final Cash:     ${metrics['final_cash']:,.2f}")

    # Print comparison table
    print("\n" + "-"*70)
    print("STRATEGY COMPARISON")
    print("-"*70)
    print(f"{'Strategy':<12} {'Trades':<8} {'Win Rate':<10} {'Net P&L':<12} {'Return':<10}")
    print("-"*70)
    for strategy_name, (trades_df, metrics) in all_results.items():
        if metrics['trades'] > 0:
            print(f"{strategy_name:<12} {metrics['trades']:<8} {metrics['win_rate']:.1f}%{'':<5} ${metrics['total_pnl']:>10,.2f} {metrics['return_pct']:>8.2f}%")
        else:
            print(f"{strategy_name:<12} {0:<8} {'N/A':<10} {'N/A':<12} {'N/A':<10}")

    print("="*70)


def print_results(metrics_best: Dict, metrics_worst: Dict, initial_cash: float):
    """Print formatted results (legacy function for backward compatibility)."""
    print("\n" + "="*60)
    print("RBI STRATEGY BACKTEST RESULTS")
    print("="*60)

    for scenario, metrics in [('BEST CASE', metrics_best), ('WORST CASE', metrics_worst)]:
        print(f"\n--- {scenario} ---")
        if metrics['trades'] == 0:
            print("  No trades executed")
            continue

        print(f"  Trades:         {metrics['trades']}")
        print(f"  Win Rate:       {metrics['win_rate']:.1f}% ({metrics['wins']}W / {metrics['losses']}L)")
        print(f"  Profit Factor:  {metrics['profit_factor']:.2f}")
        print(f"  Avg R-Multiple: {metrics['avg_r_multiple']:.2f}")
        print(f"  Avg Win:        ${metrics['avg_win']:,.2f}")
        print(f"  Avg Loss:       ${metrics['avg_loss']:,.2f}")
        print(f"  Total P&L:      ${metrics['total_pnl']:,.2f}")
        print(f"  Return:         {metrics['return_pct']:.2f}%")
        print(f"  Commissions:    ${metrics['total_commissions']:,.2f}")
        print(f"  Final Cash:     ${metrics['final_cash']:,.2f}")

    print("\n" + "="*60)


def save_results_all_strategies(all_results: Dict[str, Tuple[pd.DataFrame, Dict]],
                                 start_date: str, end_date: str, symbols: List[str],
                                 run_id: str, near_ma_threshold: float = None,
                                 threshold_label: str = None):
    """Save results for all strategies to files."""
    # Create results directory if needed
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # Use provided threshold or default from config
    threshold = near_ma_threshold if near_ma_threshold is not None else NEAR_20_MA_THRESHOLD

    # Save trades for each strategy
    for strategy_name, (trades_df, metrics) in all_results.items():
        if not trades_df.empty:
            trades_df.to_csv(os.path.join(RESULTS_DIR, f"trades_{strategy_name}_{run_id}.csv"))

    # Build summary with all strategies
    summary = {
        'run_id': run_id,
        'config': {
            'start_date': start_date,
            'end_date': end_date,
            'symbols': symbols,
            'sma_short': SMA_SHORT,
            'sma_long': SMA_LONG,
            'profit_target_r': PROFIT_TARGET_R,
            'near_20_ma_threshold': threshold,
            'near_20_ma_threshold_label': threshold_label,
            'capital_allocation': CAPITAL_ALLOCATION,
        },
        'strategies': {}
    }

    for strategy_name, (trades_df, metrics) in all_results.items():
        # Clean metrics for JSON serialization
        clean_metrics = {k: v for k, v in metrics.items() if not isinstance(v, float) or not (v != v)}  # Remove NaN
        summary['strategies'][strategy_name] = clean_metrics

    with open(os.path.join(RESULTS_DIR, f"summary_{run_id}.json"), 'w') as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\nResults saved to {RESULTS_DIR}/")
    print(f"  - summary_{run_id}.json")
    for strategy_name in all_results.keys():
        print(f"  - trades_{strategy_name}_{run_id}.csv")


def save_results(trades_best: pd.DataFrame, trades_worst: pd.DataFrame,
                 metrics_best: Dict, metrics_worst: Dict,
                 start_date: str, end_date: str, symbols: List[str]):
    """Save results to files (legacy function)."""
    config_hash = get_config_hash(start_date, end_date, symbols)

    # Save trades
    if not trades_best.empty:
        trades_best.to_csv(os.path.join(RESULTS_DIR, f"trades_best_{config_hash}.csv"))
    if not trades_worst.empty:
        trades_worst.to_csv(os.path.join(RESULTS_DIR, f"trades_worst_{config_hash}.csv"))

    # Save summary
    summary = {
        'config': {
            'start_date': start_date,
            'end_date': end_date,
            'symbols': symbols,
            'sma_short': SMA_SHORT,
            'sma_long': SMA_LONG,
            'profit_target_r': PROFIT_TARGET_R,
        },
        'best_case': metrics_best,
        'worst_case': metrics_worst,
    }

    with open(os.path.join(RESULTS_DIR, f"summary_{config_hash}.json"), 'w') as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\nResults saved to {RESULTS_DIR}/")


def main():
    parser = argparse.ArgumentParser(description='RBI Strategy Backtest')
    parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--symbols', nargs='+', default=DEFAULT_SYMBOLS, help='Symbols to backtest')
    parser.add_argument('--cash', type=float, default=DEFAULT_INITIAL_CASH, help='Initial cash')
    parser.add_argument('--refresh', action='store_true', help='Force refresh data from IBKR')
    parser.add_argument('--fetch-only', action='store_true', help='Only fetch data, do not run backtest')
    parser.add_argument('--threshold', choices=['1pct', '2pct', '5pct', '10pct', 'disable'], default='1pct',
                       help='Near 20 MA threshold: 1pct (strict), 2pct, 5pct, 10pct, disable')
    parser.add_argument('--ablation', choices=['near_ma', 'max_ignored', 'body_ratio', 'pop', 'all'],
                       help='Ablation test: disable specific filter')
    parser.add_argument('--analyze-filters', action='store_true',
                       help='Run full filter sensitivity analysis')
    args = parser.parse_args()

    # Get actual threshold value from config
    near_ma_threshold = NEAR_20_MA_THRESHOLDS.get(args.threshold, 0.01)

    # Get ablation config if specified
    ablation_config = ABLATION_CONFIGS.get(args.ablation, {}) if args.ablation else {}

    print(f"RBI Strategy Backtest")
    print(f"Period: {args.start} to {args.end}")
    print(f"Symbols: {args.symbols}")
    print(f"Initial Cash: ${args.cash:,.0f}")
    print(f"Near 20 MA Threshold: {args.threshold} ({near_ma_threshold*100:.0f}%)")
    if args.ablation:
        print(f"Ablation Mode: {args.ablation}")
    print()

    # Setup
    setup_directories()

    # Load/fetch data
    print("Loading data...")
    all_data = load_or_fetch_data(args.symbols, args.start, args.end, args.refresh)

    if not all_data:
        print("ERROR: No data loaded. Check IBKR connection.")
        sys.exit(1)

    # If fetch-only mode, stop here
    if getattr(args, 'fetch_only', False):
        print(f"\nFetch-only mode: Data loaded for {len(all_data)} symbols")
        total_bars = sum(len(df) for df in all_data.values())
        print(f"Total bars in database: {db.get_bar_count()}")
        print(f"Bars loaded this session: {total_bars}")
        return

    # Add indicators and detect patterns
    print("\nProcessing data...")
    all_rejection_stats = {}
    all_rejected_signals = []

    for symbol in all_data:
        all_data[symbol] = add_indicators(all_data[symbol], near_ma_threshold=near_ma_threshold)
        all_data[symbol], rejection_stats, rejected_signals = detect_patterns(
            all_data[symbol], ablation=ablation_config
        )

        # Aggregate rejection stats
        for key, value in rejection_stats.items():
            all_rejection_stats[key] = all_rejection_stats.get(key, 0) + value

        all_rejected_signals.extend(rejected_signals)

        # Store processed data with indicators in SQLite
        db.store_bars(all_data[symbol], symbol)
        print(f"  Processed {symbol}: {len(all_data[symbol])} bars, {rejection_stats['accepted']} patterns")

    # Print rejection stats summary
    print("\n" + "-" * 50)
    print("REJECTION STATS")
    print("-" * 50)
    print(f"  Total control bars:         {all_rejection_stats.get('total_control_bars', 0):,}")
    print(f"  Rejected (Picture of Power): {all_rejection_stats.get('rejected_picture_of_power', 0):,}")
    print(f"  Rejected (Near 20 MA):       {all_rejection_stats.get('rejected_near_20_ma', 0):,}")
    print(f"  Rejected (No ignored bar):   {all_rejection_stats.get('rejected_no_ignored_bar', 0):,}")
    print(f"  Rejected (Ignored bar size): {all_rejection_stats.get('rejected_ignored_bar_size', 0):,}")
    print(f"  Rejected (Entry trigger):    {all_rejection_stats.get('rejected_entry_trigger', 0):,}")
    print(f"  ACCEPTED:                    {all_rejection_stats.get('accepted', 0):,}")
    print("-" * 50)

    # Generate run ID and create run record (include threshold in run_id for uniqueness)
    base_run_id = db.generate_run_id()
    run_id = f"{base_run_id}_{args.threshold}"
    db.create_run(run_id, args.start, args.end, args.symbols, {
        'sma_short': SMA_SHORT,
        'sma_long': SMA_LONG,
        'near_20_ma_threshold': near_ma_threshold,
        'near_20_ma_threshold_label': args.threshold,
        'profit_target_r': PROFIT_TARGET_R,
        'capital_allocation': CAPITAL_ALLOCATION,
    })
    print(f"\nRun ID: {run_id}")

    # Generate signals
    print("Generating signals...")
    signals = generate_signals(all_data)
    print(f"  Found {len(signals)} entry signals")

    # Store signals in SQLite
    if not signals.empty:
        db.store_signals(signals, run_id)
        print(f"  Stored {len(signals)} signals in database")

    if signals.empty:
        print("\nNo trades to simulate.")
        db.complete_run(run_id)
        return

    # Simulate trades with all 4 exit strategies
    print("\nSimulating trades with all exit strategies...")
    all_results = simulate_trades_all_strategies(signals, all_data, args.cash)

    # Store trades in SQLite for each strategy
    for strategy_name, (trades_df, metrics) in all_results.items():
        if not trades_df.empty:
            db.store_trades(trades_df, run_id, strategy_name)
            print(f"  Strategy {strategy_name}: {len(trades_df)} trades stored")

    # Mark run as complete
    db.complete_run(run_id)

    # Print results for all strategies
    print_results_all_strategies(all_results, args.cash)

    # Save results (updated to handle all strategies)
    save_results_all_strategies(all_results, args.start, args.end, args.symbols, run_id,
                                near_ma_threshold=near_ma_threshold, threshold_label=args.threshold)

    # Generate HTML report and save run history
    if REPORTS_AVAILABLE:
        parameters = {
            'sma_short': SMA_SHORT,
            'sma_long': SMA_LONG,
            'near_20_ma_threshold': near_ma_threshold,
            'near_20_ma_threshold_label': args.threshold,
            'profit_target_r': PROFIT_TARGET_R,
            'capital_allocation': CAPITAL_ALLOCATION,
            'initial_cash': args.cash,
        }

        # Generate HTML report
        generate_html_report(
            all_results, args.cash, run_id,
            args.start, args.end, args.symbols,
            output_dir='reports',
            threshold_label=args.threshold
        )

        # Save run history JSON
        save_run_history(
            all_results, run_id,
            args.start, args.end, args.symbols,
            parameters,
            output_dir='reports/history'
        )
    else:
        print("\nNote: Install plotly for HTML reports: pip install plotly")


if __name__ == '__main__':
    main()
