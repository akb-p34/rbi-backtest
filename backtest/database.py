"""
SQLite database operations for RBI backtest.
Handles storage and retrieval of bars, signals, trades, and runs.
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
import pandas as pd

# Database path
DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'rbi_backtest.db')


def get_connection() -> sqlite3.Connection:
    """Get a connection to the SQLite database."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create database tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    # Bars table: Raw OHLCV data with indicators
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
            sma_20 REAL,
            sma_200 REAL,
            sma_slope REAL,
            picture_of_power INTEGER,
            near_sma INTEGER,
            UNIQUE(symbol, timestamp)
        )
    ''')

    # Create index for faster queries
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_bars_symbol_timestamp
        ON bars(symbol, timestamp)
    ''')

    # Signals table: Detected entry signals
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            signal_time TEXT NOT NULL,
            control_bar_time TEXT,
            ignored_bar_time TEXT,
            trigger_price REAL NOT NULL,
            stop_price REAL NOT NULL,
            target_price_1_5r REAL,
            near_sma_pct REAL,
            entry_open_price REAL
        )
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_signals_run_id
        ON signals(run_id)
    ''')

    # Trades table: Executed trades with outcomes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            signal_id INTEGER,
            strategy TEXT NOT NULL,
            symbol TEXT NOT NULL,
            entry_time TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_time TEXT,
            exit_price REAL,
            exit_type TEXT,
            shares INTEGER,
            gross_pnl REAL,
            commission REAL,
            net_pnl REAL,
            r_multiple REAL,
            FOREIGN KEY (signal_id) REFERENCES signals(id)
        )
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_trades_run_id
        ON trades(run_id)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_trades_strategy
        ON trades(strategy)
    ''')

    # Runs table: Run metadata and summary
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            start_date TEXT,
            end_date TEXT,
            symbols TEXT,
            parameters TEXT,
            completed INTEGER DEFAULT 0
        )
    ''')

    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")


def store_bars(df: pd.DataFrame, symbol: str):
    """
    Store OHLCV data with indicators in the database.
    Uses INSERT OR REPLACE to handle updates.
    """
    conn = get_connection()
    cursor = conn.cursor()

    rows_inserted = 0
    for idx, row in df.iterrows():
        timestamp = str(idx)

        cursor.execute('''
            INSERT OR REPLACE INTO bars
            (symbol, timestamp, open, high, low, close, volume,
             sma_20, sma_200, sma_slope, picture_of_power, near_sma)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            symbol,
            timestamp,
            row['open'],
            row['high'],
            row['low'],
            row['close'],
            row.get('volume', 0),
            row.get('sma_short'),  # sma_20
            row.get('sma_long'),   # sma_200
            row.get('sma_slope'),
            1 if row.get('picture_of_power', False) else 0,
            1 if row.get('near_sma', False) else 0
        ))
        rows_inserted += 1

    conn.commit()
    conn.close()
    return rows_inserted


def get_bars(symbols: List[str], start_date: str = None, end_date: str = None) -> Dict[str, pd.DataFrame]:
    """
    Retrieve bars from database for specified symbols and date range.
    Returns dict of {symbol: DataFrame}.
    """
    conn = get_connection()

    all_data = {}
    for symbol in symbols:
        query = "SELECT * FROM bars WHERE symbol = ?"
        params = [symbol]

        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date + " 23:59:59")

        query += " ORDER BY timestamp"

        df = pd.read_sql_query(query, conn, params=params)

        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.set_index('timestamp')
            df = df.drop(columns=['id', 'symbol'], errors='ignore')

            # Convert boolean columns
            df['picture_of_power'] = df['picture_of_power'].astype(bool)
            df['near_sma'] = df['near_sma'].astype(bool)

            # Rename columns to match expected format
            df = df.rename(columns={
                'sma_20': 'sma_short',
                'sma_200': 'sma_long'
            })

            df['symbol'] = symbol
            all_data[symbol] = df

    conn.close()
    return all_data


def has_bars(symbols: List[str], start_date: str, end_date: str) -> bool:
    """Check if we have cached bars for the given symbols and date range."""
    conn = get_connection()
    cursor = conn.cursor()

    for symbol in symbols:
        cursor.execute('''
            SELECT COUNT(*) FROM bars
            WHERE symbol = ? AND timestamp >= ? AND timestamp <= ?
        ''', (symbol, start_date, end_date + " 23:59:59"))

        count = cursor.fetchone()[0]
        if count == 0:
            conn.close()
            return False

    conn.close()
    return True


def create_run(run_id: str, start_date: str, end_date: str,
               symbols: List[str], parameters: Dict[str, Any]) -> str:
    """Create a new run record."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO runs (run_id, start_date, end_date, symbols, parameters)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        run_id,
        start_date,
        end_date,
        json.dumps(symbols),
        json.dumps(parameters)
    ))

    conn.commit()
    conn.close()
    return run_id


def complete_run(run_id: str):
    """Mark a run as completed."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        UPDATE runs SET completed = 1 WHERE run_id = ?
    ''', (run_id,))

    conn.commit()
    conn.close()


def store_signals(signals_df: pd.DataFrame, run_id: str) -> int:
    """Store entry signals in the database."""
    if signals_df.empty:
        return 0

    conn = get_connection()
    cursor = conn.cursor()

    rows_inserted = 0
    for _, row in signals_df.iterrows():
        cursor.execute('''
            INSERT INTO signals
            (run_id, symbol, signal_time, trigger_price, stop_price,
             target_price_1_5r, entry_open_price, near_sma_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            run_id,
            row['symbol'],
            str(row['timestamp']),
            row['entry_price'],
            row['stop_price'],
            row.get('target_price'),
            row.get('open_price'),
            row.get('near_sma_pct')
        ))
        rows_inserted += 1

    conn.commit()
    conn.close()
    return rows_inserted


def store_trades(trades_df: pd.DataFrame, run_id: str, strategy: str) -> int:
    """Store executed trades in the database."""
    if trades_df.empty:
        return 0

    conn = get_connection()
    cursor = conn.cursor()

    rows_inserted = 0
    for _, row in trades_df.iterrows():
        # Calculate net_pnl if not present
        gross_pnl = row.get('pnl', 0)
        entry_commission = row.get('entry_commission', 0)
        exit_commission = row.get('exit_commission', 0)
        commission = entry_commission + exit_commission
        net_pnl = gross_pnl  # pnl already includes commission in current code

        cursor.execute('''
            INSERT INTO trades
            (run_id, strategy, symbol, entry_time, entry_price,
             exit_time, exit_price, exit_type, shares,
             gross_pnl, commission, net_pnl, r_multiple)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            run_id,
            strategy,
            row['symbol'],
            str(row['entry_time']),
            row['entry_price'],
            str(row.get('exit_time', '')),
            row.get('exit_price'),
            row.get('exit_type'),
            row.get('shares'),
            gross_pnl,
            commission,
            net_pnl,
            row.get('r_multiple')
        ))
        rows_inserted += 1

    conn.commit()
    conn.close()
    return rows_inserted


def get_trades(run_id: str = None, strategy: str = None) -> pd.DataFrame:
    """Retrieve trades from database, optionally filtered by run_id and strategy."""
    conn = get_connection()

    query = "SELECT * FROM trades WHERE 1=1"
    params = []

    if run_id:
        query += " AND run_id = ?"
        params.append(run_id)
    if strategy:
        query += " AND strategy = ?"
        params.append(strategy)

    query += " ORDER BY entry_time"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if not df.empty:
        df['entry_time'] = pd.to_datetime(df['entry_time'])
        df['exit_time'] = pd.to_datetime(df['exit_time'])

    return df


def get_run(run_id: str) -> Optional[Dict]:
    """Get run metadata by ID."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            'run_id': row['run_id'],
            'created_at': row['created_at'],
            'start_date': row['start_date'],
            'end_date': row['end_date'],
            'symbols': json.loads(row['symbols']),
            'parameters': json.loads(row['parameters']),
            'completed': bool(row['completed'])
        }
    return None


def generate_run_id() -> str:
    """Generate a unique run ID based on timestamp."""
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')

    # Find existing runs for today
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM runs WHERE run_id LIKE ?",
        (f"{date_str}_%",)
    )
    count = cursor.fetchone()[0]
    conn.close()

    return f"{date_str}_{count + 1:03d}"


def clear_run_data(run_id: str):
    """Clear all data for a specific run (signals and trades)."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM trades WHERE run_id = ?", (run_id,))
    cursor.execute("DELETE FROM signals WHERE run_id = ?", (run_id,))
    cursor.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))

    conn.commit()
    conn.close()


def get_bar_count(symbol: str = None) -> int:
    """Get count of bars in database, optionally for a specific symbol."""
    conn = get_connection()
    cursor = conn.cursor()

    if symbol:
        cursor.execute("SELECT COUNT(*) FROM bars WHERE symbol = ?", (symbol,))
    else:
        cursor.execute("SELECT COUNT(*) FROM bars")

    count = cursor.fetchone()[0]
    conn.close()
    return count


if __name__ == '__main__':
    # Initialize database when run directly
    init_db()
    print(f"Database tables created at {DB_PATH}")
