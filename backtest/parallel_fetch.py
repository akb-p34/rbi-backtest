#!/usr/bin/env python3
"""
Parallel data fetching for RBI Filter Sensitivity Analysis.
Uses 32 parallel agents with separate SQLite databases to maximize throughput.

Usage:
    python parallel_fetch.py --start 2025-01-01 --end 2025-12-31
    python parallel_fetch.py --start 2025-01-01 --end 2025-12-31 --symbols-file data/high_beta_symbols.json
    python parallel_fetch.py --start 2025-01-01 --end 2025-12-31 --agents 16
"""

import os
import sys
import json
import time
import sqlite3
import argparse
from datetime import datetime
from typing import List, Dict, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import Queue, Process
import pandas as pd

from config import IBKR_HOST, IBKR_PORT, TIMEFRAME

# Parallel fetching config
MAX_AGENTS = 32
BASE_CLIENT_ID = 101  # Agents use clientId 101-132
CHUNK_DAYS = 10       # 10 days per request (~1,440 2-min bars)

# Data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
MASTER_DB = os.path.join(DATA_DIR, 'rbi_backtest.db')


def get_agent_db_path(agent_id: int) -> str:
    """Get database path for a specific agent."""
    return os.path.join(DATA_DIR, f'agent_{agent_id}.db')


def init_agent_db(agent_id: int):
    """Initialize agent's SQLite database."""
    db_path = get_agent_db_path(agent_id)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume INTEGER,
            UNIQUE(symbol, timestamp)
        )
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_bars_symbol_timestamp
        ON bars(symbol, timestamp)
    ''')

    conn.commit()
    conn.close()
    return db_path


def fetch_symbol_data(agent_id: int, symbol: str, start_date: str, end_date: str,
                      max_retries: int = 3) -> Dict:
    """
    Fetch historical data for a single symbol.
    Uses chunked requests walking backwards from end_date.

    Returns dict with status and bar count.
    """
    from ib_insync import IB, Stock

    result = {
        'symbol': symbol,
        'agent_id': agent_id,
        'status': 'error',
        'bars': 0,
        'error': None
    }

    client_id = BASE_CLIENT_ID + agent_id
    db_path = get_agent_db_path(agent_id)

    ib = IB()
    retries = 0

    while retries < max_retries:
        try:
            ib.connect(IBKR_HOST, IBKR_PORT, clientId=client_id, timeout=60)

            contract = Stock(symbol, 'SMART', 'USD')
            ib.qualifyContracts(contract)

            # Parse dates
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")

            all_bars = []
            dt = end_dt.strftime("%Y%m%d 16:00:00 US/Eastern")

            while True:
                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime=dt,
                    durationStr=f'{CHUNK_DAYS} D',
                    barSizeSetting=TIMEFRAME,
                    whatToShow='TRADES',
                    useRTH=True,
                    formatDate=2,
                    timeout=60  # 1 minute timeout per chunk
                )

                if not bars:
                    break

                all_bars.extend(bars)

                # Get oldest bar date
                oldest_bar = bars[0]
                oldest_date = oldest_bar.date
                if isinstance(oldest_date, datetime):
                    oldest_dt = oldest_date.replace(tzinfo=None) if oldest_date.tzinfo else oldest_date
                else:
                    oldest_dt = datetime.combine(oldest_date, datetime.min.time())

                if oldest_dt <= start_dt:
                    break

                dt = oldest_dt.strftime("%Y%m%d %H:%M:%S US/Eastern")
                time.sleep(1)  # IBKR pacing

            # Store in agent DB
            if all_bars:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()

                for bar in all_bars:
                    try:
                        cursor.execute('''
                            INSERT OR REPLACE INTO bars
                            (symbol, timestamp, open, high, low, close, volume)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            symbol,
                            str(bar.date),
                            bar.open,
                            bar.high,
                            bar.low,
                            bar.close,
                            bar.volume
                        ))
                    except Exception as e:
                        pass

                conn.commit()
                conn.close()

            result['status'] = 'success'
            result['bars'] = len(all_bars)
            break

        except Exception as e:
            retries += 1
            result['error'] = str(e)
            if retries < max_retries:
                time.sleep(2 ** retries)  # Exponential backoff
        finally:
            if ib.isConnected():
                ib.disconnect()

    return result


def agent_worker(agent_id: int, symbols: List[str], start_date: str, end_date: str,
                 result_queue: Queue):
    """
    Worker process for a single agent.
    Fetches all assigned symbols and reports progress.
    """
    # Initialize agent DB
    init_agent_db(agent_id)

    results = []
    for i, symbol in enumerate(symbols):
        print(f"  Agent {agent_id}: [{i+1}/{len(symbols)}] {symbol}...", flush=True)

        result = fetch_symbol_data(agent_id, symbol, start_date, end_date)
        results.append(result)

        if result['status'] == 'success':
            print(f"  Agent {agent_id}: {symbol} ✓ ({result['bars']} bars)")
        else:
            print(f"  Agent {agent_id}: {symbol} ✗ ({result['error']})")

        time.sleep(3)  # Delay between symbols

    result_queue.put((agent_id, results))


def merge_agent_databases(agent_ids: List[int]) -> int:
    """
    Merge all agent databases into the master database.
    Returns total bars merged.
    """
    print("\nMerging agent databases...")

    # Connect to master DB
    master_conn = sqlite3.connect(MASTER_DB)
    master_cursor = master_conn.cursor()

    # Ensure bars table exists
    master_cursor.execute('''
        CREATE TABLE IF NOT EXISTS bars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume INTEGER,
            sma_20 REAL,
            sma_200 REAL,
            sma_slope REAL,
            picture_of_power INTEGER,
            near_sma INTEGER,
            UNIQUE(symbol, timestamp)
        )
    ''')

    total_bars = 0

    for agent_id in agent_ids:
        db_path = get_agent_db_path(agent_id)
        if not os.path.exists(db_path):
            continue

        print(f"  Merging agent {agent_id}...", end='', flush=True)

        # Attach agent DB
        master_cursor.execute(f"ATTACH DATABASE '{db_path}' AS agent{agent_id}")

        # Count bars
        master_cursor.execute(f"SELECT COUNT(*) FROM agent{agent_id}.bars")
        count = master_cursor.fetchone()[0]

        # Copy bars
        master_cursor.execute(f'''
            INSERT OR IGNORE INTO bars (symbol, timestamp, open, high, low, close, volume)
            SELECT symbol, timestamp, open, high, low, close, volume
            FROM agent{agent_id}.bars
        ''')

        master_cursor.execute(f"DETACH DATABASE agent{agent_id}")

        total_bars += count
        print(f" {count} bars")

        # Clean up agent DB
        os.remove(db_path)

    master_conn.commit()
    master_conn.close()

    print(f"\nTotal bars merged: {total_bars:,}")
    return total_bars


def validate_data(symbols: List[str], start_date: str, end_date: str) -> Dict:
    """
    Run data quality checks on merged database.
    Returns validation report.
    """
    print("\nRunning data quality checks...")

    conn = sqlite3.connect(MASTER_DB)

    # Expected bars per symbol
    # ~195 bars/day * ~252 trading days = ~49,140 bars/year for 2-min data
    trading_days = len(pd.bdate_range(start_date, end_date))
    expected_bars = trading_days * 195  # Approximate

    report = {
        'total_symbols': len(symbols),
        'symbols_with_data': 0,
        'total_bars': 0,
        'expected_bars_per_symbol': expected_bars,
        'warnings': [],
        'missing_symbols': [],
    }

    for symbol in symbols:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) FROM bars WHERE symbol = ?
        ''', (symbol,))
        count = cursor.fetchone()[0]

        if count == 0:
            report['missing_symbols'].append(symbol)
        else:
            report['symbols_with_data'] += 1
            report['total_bars'] += count

            # Check for missing data (>5% threshold)
            if count < expected_bars * 0.95:
                missing_pct = (1 - count / expected_bars) * 100
                report['warnings'].append({
                    'symbol': symbol,
                    'bars': count,
                    'expected': expected_bars,
                    'missing_pct': missing_pct
                })

    conn.close()

    # Print summary
    print(f"\nData Quality Report:")
    print(f"  Symbols with data: {report['symbols_with_data']}/{report['total_symbols']}")
    print(f"  Total bars: {report['total_bars']:,}")
    print(f"  Missing symbols: {len(report['missing_symbols'])}")
    print(f"  Symbols with >5% missing: {len(report['warnings'])}")

    if report['warnings'][:5]:
        print("\n  Top warnings:")
        for w in report['warnings'][:5]:
            print(f"    {w['symbol']}: {w['missing_pct']:.1f}% missing")

    return report


def parallel_fetch(symbols: List[str], start_date: str, end_date: str,
                   num_agents: int = MAX_AGENTS) -> Dict:
    """
    Orchestrate parallel fetching across multiple agents.
    """
    print("=" * 60)
    print("PARALLEL DATA FETCH")
    print("=" * 60)
    print(f"Symbols: {len(symbols)}")
    print(f"Period: {start_date} to {end_date}")
    print(f"Agents: {num_agents}")
    print("=" * 60)

    os.makedirs(DATA_DIR, exist_ok=True)

    # Split symbols across agents
    symbols_per_agent = [[] for _ in range(num_agents)]
    for i, symbol in enumerate(symbols):
        symbols_per_agent[i % num_agents].append(symbol)

    print(f"\nSymbols per agent: ~{len(symbols) // num_agents}")

    # Create result queue
    from multiprocessing import Manager
    manager = Manager()
    result_queue = manager.Queue()

    # Start agent processes
    processes = []
    for agent_id in range(num_agents):
        if not symbols_per_agent[agent_id]:
            continue

        p = Process(
            target=agent_worker,
            args=(agent_id, symbols_per_agent[agent_id], start_date, end_date, result_queue)
        )
        p.start()
        processes.append((agent_id, p))
        time.sleep(2)  # Stagger starts more to avoid overwhelming IBKR

    print(f"\nStarted {len(processes)} agent processes")

    # Wait for all processes
    all_results = {}
    for agent_id, p in processes:
        p.join()
        try:
            aid, results = result_queue.get(timeout=5)
            all_results[aid] = results
        except:
            pass

    # Merge databases
    agent_ids = [aid for aid, _ in processes]
    total_bars = merge_agent_databases(agent_ids)

    # Validate data
    report = validate_data(symbols, start_date, end_date)

    # Summary
    success_count = sum(
        1 for results in all_results.values()
        for r in results if r['status'] == 'success'
    )
    error_count = len(symbols) - success_count

    print("\n" + "=" * 60)
    print("FETCH SUMMARY")
    print("=" * 60)
    print(f"  Successful: {success_count}/{len(symbols)}")
    print(f"  Errors: {error_count}")
    print(f"  Total bars: {total_bars:,}")
    print("=" * 60)

    return {
        'success_count': success_count,
        'error_count': error_count,
        'total_bars': total_bars,
        'validation': report
    }


def main():
    parser = argparse.ArgumentParser(description='Parallel data fetching for RBI')
    parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--symbols', nargs='+', help='Symbols to fetch')
    parser.add_argument('--symbols-file', help='JSON file with symbols list')
    parser.add_argument('--agents', type=int, default=MAX_AGENTS,
                       help=f'Number of parallel agents (default: {MAX_AGENTS})')
    args = parser.parse_args()

    # Load symbols
    if args.symbols:
        symbols = args.symbols
    elif args.symbols_file:
        with open(args.symbols_file, 'r') as f:
            data = json.load(f)
            symbols = data.get('symbols', data) if isinstance(data, dict) else data
    else:
        print("ERROR: Must specify --symbols or --symbols-file")
        sys.exit(1)

    print(f"Loaded {len(symbols)} symbols")

    # Run parallel fetch
    result = parallel_fetch(symbols, args.start, args.end, args.agents)

    print(f"\nReady for Phase 3: Rejection tracking")
    print(f"Data stored in {MASTER_DB}")


if __name__ == '__main__':
    main()
