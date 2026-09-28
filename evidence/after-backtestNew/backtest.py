import os
import json
import pandas as pd
import numpy as np
from ib_insync import IB, Stock
from datetime import datetime, timedelta
import pytz
import warnings
import time
import hashlib

warnings.filterwarnings("ignore", message="The behavior of array concatenation with empty entries is deprecated")
warnings.filterwarnings("ignore", message="The behavior of DataFrame concatenation with empty or all-NA entries is deprecated")

# === CONFIGURATION ===
default_config = {
    "tickers": [
        "TSLA", "NFLX", "PLTR", "QCOM", "V"
    ],
    "initial_cash": 100000.0,
    "sma_short": 10,
    "sma_long": 100,
    "sma_divergence_threshold": 0.0001,
    "granularity": "2 mins",
    "force_refresh": False
}

# Assign config variables directly from default_config
tickers = default_config['tickers']
sma_short = default_config['sma_short']
sma_long = default_config['sma_long']
sma_divergence_threshold = default_config['sma_divergence_threshold']
granularity = default_config['granularity']
force_refresh = default_config['force_refresh']

# Prompt user for backtest start and end dates (inclusive)
while True:
    try:
        start_date_input = input("Enter the start date (inclusive, YYYY-MM-DD): ")
        backtest_start_date = datetime.strptime(start_date_input, "%Y-%m-%d").strftime("%Y-%m-%d")
        break
    except ValueError:
        print("Invalid date format. Please use YYYY-MM-DD (e.g., 2025-03-03).")

while True:
    try:
        end_date_input = input("Enter the end date (inclusive, YYYY-MM-DD): ")
        backtest_end_date = datetime.strptime(end_date_input, "%Y-%m-%d").strftime("%Y-%m-%d")
        break
    except ValueError:
        print("Invalid date format. Please use YYYY-MM-DD (e.g., 2025-03-25).")

# Calculate the number of trading days (business days) between start and end (inclusive)
trading_days = pd.date_range(backtest_start_date, backtest_end_date, freq='B')
trading_days_counted = len(trading_days)

if input(f"Confirm backtest period: {backtest_start_date} to {backtest_end_date} (inclusive, {trading_days_counted} trading days) [y/n]: ").lower() != 'y':
    exit(0)

# Prompt user for initial capital
while True:
    try:
        initial_cash_input = input("Enter initial capital (e.g., 100000): ")
        initial_cash = float(initial_cash_input)
        if initial_cash <= 0:
            raise ValueError("Capital must be positive.")
        break
    except ValueError:
        print("Invalid input. Please enter a positive number for initial capital.")

# Compute config hash for validation (using user inputs)
config_str = f"{backtest_start_date}{backtest_end_date}{sma_short}{sma_long}{sma_divergence_threshold}{granularity}"
config_hash = hashlib.md5(config_str.encode()).hexdigest()

script_dir = os.path.dirname(os.path.abspath(__file__))
print(f"✅ Config setup complete: Loaded {len(tickers)} tickers")
print(f"📜 First 5 tickers: {tickers[:5]}")
print(f"📅 Backtest period: {backtest_start_date} to {backtest_end_date} ({trading_days_counted} trading days)")

# === SETUP DIRECTORIES ===
print("🚀 Starting directory setup...")
stock_data_dir = os.path.join(script_dir, "Stock Data")
trade_logs_best_dir = os.path.join(script_dir, "Trade_Logs_Best")
trade_logs_worst_dir = os.path.join(script_dir, "Trade_Logs_Worst")
pattern_violations_dir = os.path.join(script_dir, "Pattern_Violations")
for directory in [stock_data_dir, trade_logs_best_dir, trade_logs_worst_dir, pattern_violations_dir]:
    if not os.path.exists(directory):
        os.makedirs(directory)
        print(f"📁 Created directory: {directory}")
print("✅ Directory setup complete")

# === SETUP IBKR CONNECTION ===
ib = IB()
print("🚀 Starting IBKR connection...")
try:
    ib.connect('127.0.0.1', 7497, clientId=101)
    print("✅ Connected successfully! 🚀")
except Exception as e:
    print(f"❌ Connection failed: {e} 😞")
    exit(1)

# === PATTERN VALIDATION FUNCTIONS ===
def validate_pattern_sequence(df, ticker):
    """
    Validate that the bar labels follow the strict pattern rules.
    Returns a list of violations.
    """
    violations = []
    
    # Define allowed transitions
    allowed_transitions = {
        "Noise Bar": ["Control Bar", "Noise Bar"],
        "Control Bar": ["Ignored Bar A", "Noise Bar"],
        "Ignored Bar A": ["Ignored Bar B", "Indicator Bar", "Noise Bar"],
        "Ignored Bar B": ["Indicator Bar", "Noise Bar"],
        "Indicator Bar": ["Control Bar", "Noise Bar"]
    }
    
    for i in range(1, len(df)):
        prev_label = df['Label'].iloc[i-1]
        curr_label = df['Label'].iloc[i]
        timestamp = df.index[i]
        
        # Check if transition is allowed
        if prev_label in allowed_transitions:
            if curr_label not in allowed_transitions[prev_label]:
                violation = {
                    'ticker': ticker,
                    'timestamp': timestamp,
                    'prev_label': prev_label,
                    'curr_label': curr_label,
                    'violation_type': f"Invalid transition: {prev_label} → {curr_label}"
                }
                violations.append(violation)
        else:
            # This shouldn't happen if labeling is correct
            violation = {
                'ticker': ticker,
                'timestamp': timestamp,
                'prev_label': prev_label,
                'curr_label': curr_label,
                'violation_type': f"Unknown label type: {prev_label}"
            }
            violations.append(violation)
    
    return violations

def save_pattern_violations(all_violations):
    """Save pattern violations to a CSV file."""
    if all_violations:
        violations_df = pd.DataFrame(all_violations)
        violations_file = os.path.join(pattern_violations_dir, f"pattern_violations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        violations_df.to_csv(violations_file, index=False)
        print(f"⚠️ Pattern violations saved to {violations_file}")
        
        # Print summary
        print("\n=== Pattern Violations Summary ===")
        print(f"Total violations: {len(all_violations)}")
        print("\nViolations by ticker:")
        for ticker in violations_df['ticker'].unique():
            count = len(violations_df[violations_df['ticker'] == ticker])
            print(f"  {ticker}: {count} violations")
    else:
        print("✅ No pattern violations detected!")

# === DATA FETCHING AND PREPROCESSING ===
def fetch_historical_data(ticker, start_date, end_date, granularity):
    print(f"🚀 Starting historical data fetch for {ticker} from {start_date} to {end_date}... [{tickers.index(ticker)+1}/{len(tickers)}]")
    contract = Stock(ticker, 'SMART', 'USD')
    start_datetime = datetime.strptime(start_date, "%Y-%m-%d").strftime("%Y%m%d 09:30:00 US/Eastern")
    end_datetime = datetime.strptime(end_date, "%Y-%m-%d").strftime("%Y%m%d 16:00:00 US/Eastern")
    
    duration = trading_days_counted

    try:
        bars = ib.reqHistoricalData(
            contract,
            endDateTime=end_datetime,
            durationStr=f"{duration} D",
            barSizeSetting=granularity,
            whatToShow="TRADES",
            useRTH=True,
            formatDate=2
        )
        if not bars:
            print(f"⚠️ No data fetched for {ticker} 📭")
            return None
        df = pd.DataFrame({
            'Ticker': [ticker] * len(bars),
            'Open': [bar.open for bar in bars],
            'High': [bar.high for bar in bars],
            'Low': [bar.low for bar in bars],
            'Close': [bar.close for bar in bars],
            'Volume': [bar.volume for bar in bars]
        }, index=[bar.date for bar in bars])
        df.index = pd.to_datetime(df.index).tz_convert('US/Eastern')
        print(f"✅ Fetched historical data for {ticker}")
        return df
    except Exception as e:
        print(f"❌ Error fetching data for {ticker}: {e} 😵")
        return None

def load_or_fetch_data(ticker):
    file_path = os.path.join(stock_data_dir, f"{ticker}_2min_data.csv")
    metadata_path = os.path.join(stock_data_dir, f"{ticker}_metadata.json")
    expected_start = pd.to_datetime(f"{backtest_start_date} 09:30:00-05:00")
    expected_end = pd.to_datetime(f"{backtest_end_date} 16:00:00-04:00")
    expected_bars = trading_days_counted * 195

    print(f"🚀 Starting data load or fetch for {ticker}... [{tickers.index(ticker)+1}/{len(tickers)}]")
    if not force_refresh and os.path.exists(file_path) and os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
            meta_start = pd.to_datetime(metadata['start_date'])
            meta_end = pd.to_datetime(metadata['end_date'])
            df = pd.read_csv(file_path, index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index, utc=True).tz_convert('US/Eastern')
            df['Ticker'] = ticker

            print(f"🧐 Checking {ticker}:")
            print(f"    Expected Start: {expected_start.date()}  | Received: {meta_start.date()}")
            print(f"    Expected End:   {expected_end.date()}  | Received: {meta_end.date()}")
            print(f"    Expected Len:   {expected_bars}          | Received: {len(df)}")

            if (meta_start.date() == expected_start.date() and
                meta_end.date() == expected_end.date() and
                metadata['config_hash'] == config_hash and
                metadata.get('granularity') == granularity and
                expected_bars * 0.9 <= len(df) <= expected_bars * 1.1 and
                df.index[0] >= expected_start and
                df.index[-1] <= expected_end and
                df.index.to_series().diff().dropna().median() <= pd.Timedelta(minutes=2)):
                print(f"📂 Loaded valid preprocessed data for {ticker} from {file_path}")
                return df
            else:
                print(f"⚠️ Existing data for {ticker} invalid (dates or length mismatch), fetching new data")
        except Exception as e:
            print(f"⚠️ Error loading data or metadata for {ticker}: {e}, fetching new data")

    df = fetch_historical_data(ticker, backtest_start_date, backtest_end_date, granularity)
    if df is None or df.empty:
        return None

    print(f"🔄 Processing data for {ticker}: Computing SMAs and labeling bars...")
    df['20min_SMA'] = df['Close'].rolling(window=sma_short).mean()
    df['200min_SMA'] = df['Close'].rolling(window=sma_long).mean()
    df['Setup'] = df['20min_SMA'] > df['200min_SMA']
    df['SMA_20_slope'] = df['20min_SMA'].diff()

    # Initialize all bars as Noise
    df['Label'] = "Noise Bar"
    df['Entry_Signal'] = False
    df['Trigger_Price'] = np.nan
    
    # Real-time labeling simulation
    for i in range(1, len(df) - 1):
        if df['Setup'].iloc[i]:
            # Check for Control Bar
            if df['Close'].iloc[i] > df['Open'].iloc[i]:
                # Verify previous bar was Noise or Indicator
                if i == 0 or df['Label'].iloc[i-1] in ["Noise Bar", "Indicator Bar"]:
                    df.iloc[i, df.columns.get_loc('Label')] = "Control Bar"
            
            # Check for Ignored Bar A
            if i > 0 and df['Label'].iloc[i-1] == "Control Bar":
                control_body = abs(df['Close'].iloc[i-1] - df['Open'].iloc[i-1])
                ignored_body = abs(df['Open'].iloc[i] - df['Close'].iloc[i])
                if (df['Close'].iloc[i] < df['Open'].iloc[i]) and (ignored_body <= 0.5 * control_body):
                    df.iloc[i, df.columns.get_loc('Label')] = "Ignored Bar A"
            
            # Check for Ignored Bar B
            if i > 1 and df['Label'].iloc[i-1] == "Ignored Bar A":
                # Find the Control Bar (should be 2 bars back)
                control_idx = i - 2
                if control_idx >= 0 and df['Label'].iloc[control_idx] == "Control Bar":
                    control_body = abs(df['Close'].iloc[control_idx] - df['Open'].iloc[control_idx])
                    ignored_body = abs(df['Open'].iloc[i] - df['Close'].iloc[i])
                    if (df['Close'].iloc[i] < df['Open'].iloc[i]) and (ignored_body <= 0.5 * control_body):
                        df.iloc[i, df.columns.get_loc('Label')] = "Ignored Bar B"
            
            # Check for Indicator Bar
            if i > 0 and df['Label'].iloc[i-1] in ["Ignored Bar A", "Ignored Bar B"]:
                ignored_high = df['High'].iloc[i-1]
                trigger_price = ignored_high + 0.01
                
                # Check if current bar's high exceeds trigger
                if df['Open'].iloc[i] > trigger_price: #Forward bias existed when it was if df['Open'].iloc[i] > trigger_price:
                    df.iloc[i, df.columns.get_loc('Label')] = "Indicator Bar"
                    df.iloc[i, df.columns.get_loc('Entry_Signal')] = True
                    df.iloc[i, df.columns.get_loc('Trigger_Price')] = trigger_price

    # Validate the pattern sequence
    violations = validate_pattern_sequence(df, ticker)
    
    # Save the labeled data with entry signals
    df.to_csv(file_path)
    data_hash = hashlib.md5(df.to_csv().encode()).hexdigest()
    metadata = {
        "config_hash": config_hash,
        "start_date": backtest_start_date,
        "end_date": backtest_end_date,
        "data_hash": data_hash,
        "granularity": granularity,
        "pattern_violations": len(violations)
    }
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f)
    print(f"💾 Computed SMAs, labeled bars, and saved 2-min data for {ticker} to {file_path} with metadata...")
    print(f"   Pattern violations detected: {len(violations)}")
    
    return df, violations

# === BACKTESTING PER TICKER ===
def backtest_ticker(ticker, df, trade_logs_dir, scenario):
    trade_log_file = os.path.join(trade_logs_dir, f"{ticker}_Trade_Log.csv")
    metadata_path = os.path.join(trade_logs_dir, f"{ticker}_metadata.json")
    required_columns = ["Entry_Time", "Action_Price", "Stop_Loss", "Trade_Type", "Trade_ID", "Shares"]
    data_hash = hashlib.md5(df.to_csv().encode()).hexdigest()

    print(f"🚀 Starting {scenario} backtest for {ticker}... [{tickers.index(ticker)+1}/{len(tickers)}]")
    if not force_refresh and os.path.exists(trade_log_file) and os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
            if (metadata['config_hash'] == config_hash and
                metadata['data_hash'] == data_hash and
                metadata['scenario'] == scenario):
                trade_log = pd.read_csv(trade_log_file, parse_dates=["Entry_Time"])
                if all(col in trade_log.columns for col in required_columns):
                    print(f"📂 Using existing {scenario} trade log for {ticker} from {trade_log_file}")
                    return trade_log, initial_cash, 0
                else:
                    print(f"⚠️ Existing {scenario} trade log for {ticker} missing columns, regenerating")
            else:
                print(f"⚠️ Existing {scenario} trade log for {ticker} mismatched with data or config, regenerating")
        except Exception as e:
            print(f"⚠️ Error loading trade log or metadata for {ticker}: {e}, regenerating")

    trade_log = pd.DataFrame(columns=required_columns)
    active_positions = []
    trade_id_counter = 1
    cash = initial_cash
    epsilon = 0.005
    total_commissions = 0

    print(f"🔄 Running {scenario} backtest for {ticker} ({tickers.index(ticker)+1}/{len(tickers)})...")
    for i in range(1, len(df)):
        current = df.iloc[i]
        prev = df.iloc[i-1] if i > 0 else None

        # End of day liquidation
        if current.name.hour == 16 and current.name.minute == 0:
            for pos in active_positions[:]:
                _, _, _, _, shares, trade_id = pos
                action_price = current['Close']
                trade_value = shares * action_price
                commission = max(min(shares * 0.005, trade_value * 0.01), 1)
                cash += trade_value - commission
                total_commissions += commission
                trade_log = pd.concat([trade_log, pd.DataFrame({
                    "Entry_Time": [current.name],
                    "Action_Price": [action_price],
                    "Stop_Loss": [pos[3]],
                    "Trade_Type": ["Sell - End of Day"],
                    "Trade_ID": [trade_id],
                    "Shares": [shares]
                })], ignore_index=True)
                active_positions.remove(pos)
                if cash <= 0:
                    print(f"🚨 Capital depleted during end-of-day liquidation for {ticker} at {current.name}. Ending backtest early.")
                    trade_log = pd.concat([trade_log, pd.DataFrame({
                        "Entry_Time": [current.name],
                        "Action_Price": [None],
                        "Stop_Loss": [None],
                        "Trade_Type": ["Early Termination - Capital Depleted"],
                        "Trade_ID": [f"{ticker}_TERM"],
                        "Shares": [None]
                    })], ignore_index=True)
                    cash = 0
                    active_positions = []
                    break
            if cash <= 0:
                break
            continue

        # Check exits for active positions
        for pos in active_positions[:]:
            _, _, entry_price, stop_loss, shares, trade_id = pos
            profit_target = current['20min_SMA'] * (1 + sma_divergence_threshold)
            if scenario == "Best":
                if current['High'] >= profit_target:
                    action_price = profit_target
                    exit_type = "Sell - SMA Divergence (Profit)"
                elif current['Low'] <= stop_loss + epsilon:
                    action_price = stop_loss
                    exit_type = "Sell - Stop Loss"
                else:
                    continue
            else:  # Worst
                if current['Low'] <= stop_loss + epsilon:
                    action_price = stop_loss
                    exit_type = "Sell - Stop Loss"
                elif current['High'] >= profit_target:
                    action_price = profit_target
                    exit_type = "Sell - SMA Divergence (Profit)"
                else:
                    continue

            trade_value = shares * action_price
            commission = max(min(shares * 0.005, trade_value * 0.01), 1)
            cash += trade_value - commission
            total_commissions += commission
            trade_log = pd.concat([trade_log, pd.DataFrame({
                "Entry_Time": [current.name],
                "Action_Price": [action_price],
                "Stop_Loss": [stop_loss],
                "Trade_Type": [exit_type],
                "Trade_ID": [trade_id],
                "Shares": [shares]
            })], ignore_index=True)
            active_positions.remove(pos)
            if cash <= 0:
                print(f"🚨 Capital depleted during exit processing for {ticker} at {current.name}. Ending backtest early.")
                trade_log = pd.concat([trade_log, pd.DataFrame({
                    "Entry_Time": [current.name],
                    "Action_Price": [None],
                    "Stop_Loss": [None],
                    "Trade_Type": ["Early Termination - Capital Depleted"],
                    "Trade_ID": [f"{ticker}_TERM"],
                    "Shares": [None]
                })], ignore_index=True)
                cash = 0
                active_positions = []
                break
        if cash <= 0:
            break

        # Entry on Indicator Bar (bias-free implementation)
        if current['Entry_Signal'] and current['Label'] == "Indicator Bar":
            # Find the most recent ignored bar for stop loss
            recent_idx = i - 1
            while recent_idx >= 0 and df['Label'].iloc[recent_idx] not in ["Ignored Bar A", "Ignored Bar B"]:
                recent_idx -= 1
            stop_loss = df['Low'].iloc[recent_idx] - 0.01 if recent_idx >= 0 else current['Low'] - 0.01
            
            # Get trigger price from the dataframe
            trigger_price = current['Trigger_Price']
            
            # Determine actual fill price based on scenario
            if scenario == "Best":
                if current['Open'] > trigger_price:
                    entry_price = current['Open']  # Gapped above trigger
                else:
                    entry_price = trigger_price  # Normal fill at trigger
            else:  # Worst case
                if current['Open'] > trigger_price:
                    entry_price = current['Open']  # Gapped above trigger
                else:
                    entry_price = trigger_price + 0.01  # Add 1 penny slippage in worst case
            
            shares = int(cash * 0.5 / entry_price)
            if shares > 0:
                trade_id = f"{ticker}{trade_id_counter}"
                trade_value = shares * entry_price
                commission = max(min(shares * 0.005, trade_value * 0.01), 1)
                cash -= trade_value + commission
                total_commissions += commission
                active_positions.append((ticker, current.name, entry_price, stop_loss, shares, trade_id))
                trade_log = pd.concat([trade_log, pd.DataFrame({
                    "Entry_Time": [current.name],
                    "Action_Price": [entry_price],
                    "Stop_Loss": [stop_loss],
                    "Trade_Type": ["Buy"],
                    "Trade_ID": [trade_id],
                    "Shares": [shares]
                })], ignore_index=True)
                trade_id_counter += 1
            if cash <= 0:
                print(f"🚨 Capital depleted during entry processing for {ticker} at {current.name}. Ending backtest early.")
                trade_log = pd.concat([trade_log, pd.DataFrame({
                    "Entry_Time": [current.name],
                    "Action_Price": [None],
                    "Stop_Loss": [None],
                    "Trade_Type": ["Early Termination - Capital Depleted"],
                    "Trade_ID": [f"{ticker}_TERM"],
                    "Shares": [None]
                })], ignore_index=True)
                cash = 0
                active_positions = []
                break

    trade_log.to_csv(trade_log_file)
    metadata = {
        "config_hash": config_hash,
        "data_hash": data_hash,
        "scenario": scenario
    }
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f)
    print(f"✅ {scenario} case scenario backtest complete for {ticker} - Trades: {len(trade_log)}, saved with metadata... [{tickers.index(ticker)+1}/{len(tickers)}]")
    return trade_log, cash, total_commissions

# === PERFORMANCE LOG AND METRICS ===
def generate_performance_log(trade_logs_dir, scenario, all_data):
    print(f"🚀 Starting {scenario} performance log generation...")
    holdings = {}   # ticker: {'shares': total_shares, 'last_price': price}
    combined_trade_log = pd.DataFrame()
    for ticker in tickers:
        trade_log_file = os.path.join(trade_logs_dir, f"{ticker}_Trade_Log.csv")
        if os.path.exists(trade_log_file):
            trade_log = pd.read_csv(trade_log_file, parse_dates=["Entry_Time"])
            trade_log["Ticker"] = ticker
            trade_log['Entry_Time'] = pd.to_datetime(trade_log['Entry_Time'], utc=True).dt.tz_convert('US/Eastern')
            combined_trade_log = pd.concat([combined_trade_log, trade_log], ignore_index=True)
        else:
            print(f"⚠️ No {scenario} trade log found for {ticker}, skipping")

    if combined_trade_log.empty:
        print(f"⚠️ No trades executed for {scenario} scenario - generating empty performance log")
        performance_log = pd.DataFrame(columns=[
            "Trade_ID", "Action_Type", "Ticker", "Action_Time", "Action_Price", "Shares",
            "Total_Action_Value", "Cash_After_Trade", "Value_of_Open_Positions", "Value_of_Fund",
            "Simple_Return", "R_Multiple"
        ])
        final_cash = initial_cash
        perf_log_path = os.path.join(script_dir, f"Performance_Log_{scenario}.csv")
        performance_log.to_csv(perf_log_path, index=False)
        print(f"💾 {scenario} performance log (empty) saved to {perf_log_path}")
        print(f"✅ {scenario} performance log generation complete (no trades)")
        return performance_log, final_cash

    combined_trade_log = combined_trade_log.sort_values(by="Entry_Time")
    performance_log = pd.DataFrame(columns=[
        "Trade_ID", "Action_Type", "Ticker", "Action_Time", "Action_Price", "Shares",
        "Total_Action_Value", "Cash_After_Trade", "Value_of_Open_Positions", "Value_of_Fund",
        "Simple_Return", "R_Multiple"
    ])
    cash = initial_cash
    positions = {}
    eastern = pytz.timezone('US/Eastern')

    for _, row in combined_trade_log.iterrows():
        ticker = row['Ticker']
        action_time = row['Entry_Time']
        action_price = row['Action_Price']
        shares = row.get('Shares', 0)
        trade_id = row['Trade_ID']

        # Calculate open positions' value
        open_pos_value = 0
        for pos_id, (pos_ticker, pos_shares, _, _) in positions.items():
            if pos_ticker in all_data and not all_data[pos_ticker].empty:
                try:
                    close_price = all_data[pos_ticker].loc[action_time, 'Close']
                    open_pos_value += pos_shares * close_price
                except KeyError:
                    close_price = all_data[pos_ticker]['Close'].iloc[-1]
                    open_pos_value += pos_shares * close_price

        if "Buy" in row['Trade_Type'] and shares > 0:
            total_value = shares * action_price
            commission = max(min(shares * 0.005, total_value * 0.01), 1)
            
            cash -= (total_value + commission)
            entry_price = action_price
            positions[trade_id] = (ticker, shares, entry_price, row['Stop_Loss'])
            
            # Update holdings FIRST
            if ticker not in holdings:
                holdings[ticker] = {'shares': 0, 'last_price': action_price}
            holdings[ticker]['shares'] += shares
            holdings[ticker]['last_price'] = action_price
            
            # THEN calculate open positions value (including the position we just bought)
            open_pos_value = sum(h['shares'] * h['last_price'] for h in holdings.values())
            
            performance_log = pd.concat([performance_log, pd.DataFrame({
                "Trade_ID": [trade_id], 
                "Action_Type": ["Buy"], 
                "Ticker": [ticker],
                "Action_Time": [action_time], 
                "Action_Price": [action_price],
                "Shares": [shares], 
                "Total_Action_Value": [total_value],
                "Cash_After_Trade": [cash], 
                "Value_of_Open_Positions": [open_pos_value],  # Now includes the position we just bought
                "Value_of_Fund": [cash + open_pos_value],
                "Simple_Return": [None], 
                "R_Multiple": [None]
            })], ignore_index=True)

        elif "Sell" in row['Trade_Type'] and trade_id in positions:
            ticker, shares, entry_price, stop_loss = positions.pop(trade_id)
            total_value = shares * action_price
            commission = max(min(shares * 0.005, total_value * 0.01), 1)
            
            cash += (total_value - commission)
            
            # Update holdings FIRST (remove sold shares)
            if ticker in holdings:
                holdings[ticker]['shares'] -= shares
                if holdings[ticker]['shares'] <= 0:
                    del holdings[ticker]
            
            # THEN calculate remaining open positions value
            open_pos_value = sum(h['shares'] * h['last_price'] for h in holdings.values())
            
            # Calculate metrics
            initial_risk = entry_price - stop_loss
            r_multiple = (action_price - entry_price) / initial_risk if initial_risk > 0 else 0
            simple_return = ((action_price - entry_price) / entry_price) * 100
            
            performance_log = pd.concat([performance_log, pd.DataFrame({
                "Trade_ID": [trade_id],
                "Action_Type": ["Sell"],
                "Ticker": [ticker],
                "Action_Time": [action_time],
                "Action_Price": [action_price],
                "Shares": [shares],
                "Total_Action_Value": [total_value],
                "Cash_After_Trade": [cash],
                "Value_of_Open_Positions": [open_pos_value],  # Now excludes sold position
                "Value_of_Fund": [cash + open_pos_value],
                "Simple_Return": [simple_return],
                "R_Multiple": [r_multiple]
            })], ignore_index=True)

    # Calculate final value with proper liquidation prices
    final_cash = cash  # Start with current cash
    if holdings:
        print(f"⚠️ Liquidating {len(holdings)} positions at end of backtest:")
        for ticker, holding_info in holdings.items():
            if ticker in all_data and not all_data[ticker].empty:
                # Use high for best case, low for worst case
                if scenario == "Best":
                    final_price = all_data[ticker]['High'].iloc[-1]
                else:  # Worst case
                    final_price = all_data[ticker]['Low'].iloc[-1]
                
                position_value = holding_info['shares'] * final_price
                final_cash += position_value  # Add liquidation proceeds to cash
                print(f"   {ticker}: {holding_info['shares']:.2f} shares @ ${final_price:.2f} = ${position_value:,.2f}")

    # Final row shows everything liquidated
    performance_log = pd.concat([performance_log, pd.DataFrame({
        "Trade_ID": ["Final"],
        "Action_Type": ["End of Backtest"],
        "Ticker": [None],
        "Action_Time": [datetime.now(pytz.UTC).astimezone(eastern)],
        "Action_Price": [None],
        "Shares": [None],
        "Total_Action_Value": [None],
        "Cash_After_Trade": [final_cash],  # All positions liquidated
        "Value_of_Open_Positions": [0.0],   # No positions left
        "Value_of_Fund": [final_cash],      # Everything is now cash
        "Simple_Return": [None],
        "R_Multiple": [None]
    })], ignore_index=True)

    perf_log_path = os.path.join(script_dir, f"Performance_Log_{scenario}.csv")
    try:
        performance_log.to_csv(perf_log_path, index=False)
        print(f"💾 {scenario} performance log saved to {perf_log_path}")
    except Exception as e:
        print(f"❌ Error saving {scenario} Performance_Log.csv: {e}")
    print(f"✅ {scenario} performance log generation complete")
    return performance_log, final_cash

def calculate_metrics(performance_log, final_cash, total_commissions):
    print("🚀 Starting metrics calculation...")
    total_profit = 0.0
    total_loss = 0.0
    num_wins = 0
    num_losses = 0
    performance_log['Action_Time'] = pd.to_datetime(performance_log['Action_Time'], utc=True).dt.tz_convert('US/Eastern')
    equity_curve = performance_log.set_index("Action_Time")["Value_of_Fund"].astype(float)

    for i, row in performance_log.iterrows():
        if "Sell" in row["Action_Type"]:
            buy_row = performance_log[(performance_log["Trade_ID"] == row["Trade_ID"]) & (performance_log["Action_Type"] == "Buy")].iloc[0]
            trade_pnl = (float(row["Action_Price"]) - float(buy_row["Action_Price"])) * float(row["Shares"])
            if trade_pnl > 0:
                total_profit += trade_pnl
                num_wins += 1
            else:
                total_loss += abs(trade_pnl)
                num_losses += 1

    full_trades = num_wins + num_losses
    win_rate = round((num_wins / full_trades) * 100, 2) if full_trades > 0 else 0
    profit_factor = round(total_profit / total_loss, 3) if total_loss > 0 else float('inf')
    simple_return = round((final_cash - initial_cash) / initial_cash * 100, 2)

    try:
        roll_max = equity_curve.cummax()
        drawdown = (equity_curve - roll_max) / roll_max
        max_drawdown = drawdown.min() * -100

        daily_returns = equity_curve.resample('D').last().pct_change().dropna()
        if not daily_returns.empty:
            daily_log_returns = np.log(1 + daily_returns)
            total_log_return = daily_log_returns.sum() * 100
            sharpe_ratio = np.sqrt(252) * (daily_returns.mean() - (0.0535 / 252)) / daily_returns.std() if daily_returns.std() > 0 else 0
        else:
            total_log_return = 0
            sharpe_ratio = 0
    except Exception as e:
        print(f"⚠️ Error calculating advanced metrics: {e} 📉")
        total_log_return = 0
        sharpe_ratio = 0
        max_drawdown = 0

    print("✅ Metrics calculation complete")
    return {
        "Full Trades": full_trades, "Win Rate": win_rate, "Total Simple Return": simple_return,
        "Total Log Return": round(total_log_return, 2), "Profit Factor": profit_factor,
        "Sharpe Ratio": round(sharpe_ratio, 3), "Max Drawdown": round(max_drawdown, 2),
        "Total P&L": final_cash - initial_cash, "Total Commissions Paid": total_commissions
    }

# === MAIN EXECUTION ===
def all_trade_logs_valid(trade_logs_dir, scenario):
    """Check if all trade logs for a scenario exist and are valid."""
    for ticker in tickers:
        trade_log_file = os.path.join(trade_logs_dir, f"{ticker}_Trade_Log.csv")
        metadata_path = os.path.join(trade_logs_dir, f"{ticker}_metadata.json")
        if not (os.path.exists(trade_log_file) and os.path.exists(metadata_path)):
            return False
        try:
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
            if (metadata['config_hash'] != config_hash or
                metadata['scenario'] != scenario):
                return False
            trade_log = pd.read_csv(trade_log_file, parse_dates=["Entry_Time"])
            required_columns = ["Entry_Time", "Action_Price", "Stop_Loss", "Trade_Type", "Trade_ID", "Shares"]
            if not all(col in trade_log.columns for col in required_columns):
                return False
        except Exception:
            return False
    return True

try:
    start_time = time.time()
    print("🚀 Starting main execution: Processing data and running two backtests...")
    batch_size = 49
    num_batches = (len(tickers) + batch_size - 1) // batch_size
    print(f"📏 Total batches to process: {num_batches}")

    # Fetch data once for all tickers and collect pattern violations
    all_data = {}
    all_violations = []
    
    for batch_idx in range(num_batches):
        batch_start = batch_idx * batch_size
        batch_end = min((batch_idx + 1) * batch_size, len(tickers))
        batch_tickers = tickers[batch_start:batch_end]
        print(f"🔄 Fetching data for batch {batch_idx + 1}/{num_batches} ({len(batch_tickers)} tickers)")

        print("🚀 Starting IBKR reconnection for batch...")
        if ib.isConnected():
            ib.disconnect()
            time.sleep(2)
        ib.connect('127.0.0.1', 7497, clientId=101 + batch_idx)
        print(f"✅ Reconnected to IBKR for batch")

        for ticker in batch_tickers:
            result = load_or_fetch_data(ticker)
            if isinstance(result, tuple):
                # New format with violations
                df, violations = result
                all_data[ticker] = df
                all_violations.extend(violations)
            else:
                # Old format without violations
                all_data[ticker] = result

        print("🚀 Starting IBKR disconnection for batch...")
        ib.disconnect()
        print(f"🔌 Disconnected from IBKR after batch {batch_idx + 1}")
    
    # Save pattern violations report
    save_pattern_violations(all_violations)

    # Run backtests using pre-fetched data
    scenarios = ["Best", "Worst"]
    trade_logs_dirs = {"Best": trade_logs_best_dir, "Worst": trade_logs_worst_dir}
    all_metrics = {}

    for scenario in scenarios:
        print(f"\n=== Starting {scenario} Case Backtest ===")
        all_trade_logs = []
        total_commissions_scenario = 0

        if not force_refresh and all_trade_logs_valid(trade_logs_dirs[scenario], scenario):
            print(f"📂 All {scenario} trade logs are valid and up-to-date, skipping backtesting")
        else:
            for batch_idx in range(num_batches):
                batch_start = batch_idx * batch_size
                batch_end = min((batch_idx + 1) * batch_size, len(tickers))
                batch_tickers = tickers[batch_start:batch_end]
                print(f"🔄 Running {scenario} backtest for batch {batch_idx + 1}/{num_batches} ({len(batch_tickers)} tickers)")

                for ticker in batch_tickers:
                    df = all_data[ticker]
                    if df is not None and not df.empty and len(df) >= sma_long:
                        trade_log, _, commissions = backtest_ticker(ticker, df, trade_logs_dirs[scenario], scenario)
                        all_trade_logs.append(trade_log)
                        total_commissions_scenario += commissions

            preprocess_time = time.time() - start_time
            print(f"✅ {scenario} preprocessing and backtesting completed in {preprocess_time:.2f} seconds")

        start_time = time.time()
        performance_log, final_cash = generate_performance_log(trade_logs_dirs[scenario], scenario, all_data)
        perf_log_time = time.time() - start_time
        print(f"✅ {scenario} performance log generation completed in {perf_log_time:.2f} seconds")

        start_time = time.time()
        metrics = calculate_metrics(performance_log, final_cash, total_commissions_scenario)
        metrics_time = time.time() - start_time
        print(f"✅ {scenario} metrics calculation completed in {metrics_time:.2f} seconds")

        print(f"\n=== {scenario} Case Portfolio Performance Metrics ===")
        pnl_sign = "+" if metrics["Total P&L"] > 0 else "-"
        print(f"Full Trades: {metrics['Full Trades']} 🎯")
        
        # Check if detailed win/loss metrics exist
        if 'Winning Trades' in metrics and 'Losing Trades' in metrics:
            print(f"Win Rate: {metrics['Win Rate']}% ({metrics['Winning Trades']}W/{metrics['Losing Trades']}L) 🏆")
        else:
            print(f"Win Rate: {metrics['Win Rate']}% 🏆")
            
        print(f"Total Simple Return: {metrics['Total Simple Return']}% 📈")
        print(f"Profit Factor: {metrics['Profit Factor']} 💰")
        print(f"Sharpe Ratio: {metrics['Sharpe Ratio']} 📊")
        
        if 'Sortino Ratio' in metrics:
            print(f"Sortino Ratio: {metrics['Sortino Ratio']} 🎯")
            
        print(f"Max Drawdown: {metrics['Max Drawdown']}% 🔻")
        print(f"Total P&L: {pnl_sign}${abs(metrics['Total P&L']):,.2f} 💸")
        print(f"Total Commissions Paid: ${metrics['Total Commissions Paid']:,.2f} 💵")
        
        if 'Average R-Multiple' in metrics:
            print(f"Average R-Multiple: {metrics['Average R-Multiple']} 📏")
        if 'Average Win' in metrics:
            print(f"Average Win: ${metrics['Average Win']:,.2f} ✅")
        if 'Average Loss' in metrics:
            print(f"Average Loss: ${metrics['Average Loss']:,.2f} ❌")

        all_metrics[scenario] = metrics

    print("🚀 Starting metrics file write...")
    today_str = datetime.today().strftime('%m-%d-%Y')
    metrics_file = os.path.join(script_dir, f"metrics_{today_str}.txt")
    with open(metrics_file, 'w') as f:
        start_date_fmt = pd.to_datetime(backtest_start_date).strftime('%-m/%-d/%Y')
        end_date_fmt = pd.to_datetime(backtest_end_date).strftime('%-m/%-d/%Y')
        f.write(f"Start Date: {start_date_fmt}\n")
        f.write(f"End Date: {end_date_fmt}\n")
        f.write(f"Business Days: {trading_days_counted}\n")
        f.write(f"Starting Cash: ${initial_cash:,.0f}\n")
        f.write(f"Pattern Violations: {len(all_violations)}\n")
        for scenario in scenarios:
            metrics = all_metrics[scenario]
            pnl_sign = "+" if metrics["Total P&L"] > 0 else "-"
            f.write(f"\n=== {scenario} Case Portfolio Performance Metrics ===\n")
            f.write(f"Full Trades: {metrics['Full Trades']}\n")
            
            # Check if detailed win/loss metrics exist
            if 'Winning Trades' in metrics and 'Losing Trades' in metrics:
                f.write(f"Win Rate: {metrics['Win Rate']}% ({metrics['Winning Trades']}W/{metrics['Losing Trades']}L)\n")
            else:
                f.write(f"Win Rate: {metrics['Win Rate']}%\n")
                
            f.write(f"Total Simple Return: {metrics['Total Simple Return']}%\n")
            f.write(f"Profit Factor: {metrics['Profit Factor']}\n")
            f.write(f"Sharpe Ratio: {metrics['Sharpe Ratio']}\n")
            
            if 'Sortino Ratio' in metrics:
                f.write(f"Sortino Ratio: {metrics['Sortino Ratio']}\n")
                
            f.write(f"Max Drawdown: {metrics['Max Drawdown']}%\n")
            f.write(f"Total P&L: {pnl_sign}${abs(metrics['Total P&L']):,.2f}\n")
            f.write(f"Total Commissions Paid: ${metrics['Total Commissions Paid']:,.2f}\n")
            
            if 'Average R-Multiple' in metrics:
                f.write(f"Average R-Multiple: {metrics['Average R-Multiple']}\n")
            if 'Average Win' in metrics:
                f.write(f"Average Win: ${metrics['Average Win']:,.2f}\n")
            if 'Average Loss' in metrics:
                f.write(f"Average Loss: ${metrics['Average Loss']:,.2f}\n")
    print(f"📝 Metrics saved to {metrics_file}")

    print("✅ Main execution complete! 🎉")
    ib.disconnect()
    print("🔌 Disconnected from IBKR")

except KeyboardInterrupt:
    print("\n🚪 Exited early by user")
    ib.disconnect()
    exit(0)
except Exception as e:
    print(f"❌ Unexpected error: {e}")
    ib.disconnect()
    exit(1)