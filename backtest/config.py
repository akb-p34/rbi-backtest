"""
RBI Strategy Configuration
All quantitative parameters derived from Oliver Velez's qualitative descriptions.
"""

# =============================================================================
# CHART SETUP (Velez: "2-minute chart with 20 and 200 SMA")
# =============================================================================
TIMEFRAME = '2 mins'
SMA_SHORT = 20           # Velez: "20-period SMA" (40 min on 2-min bars)
SMA_LONG = 200           # Velez: "200-period SMA" (400 min on 2-min bars)

# =============================================================================
# PATTERN DETECTION
# =============================================================================
# "Small" red bar: Velez says "tiny", "small" - quantified as ≤ 50% of control body
IGNORED_BODY_MAX_RATIO = 0.50

# Velez: "one or two little ones okay"
MAX_IGNORED_BARS = 2

# Velez: "$0.01 above the high", "$0.01 below the low"
ENTRY_BUFFER = 0.01
STOP_BUFFER = 0.01

# Stop buffer variants for B4/B5 strategies
STOP_BUFFER_B4 = 0.005  # Tighter: $0.005 (half of standard)
STOP_BUFFER_B5 = 0.02   # Looser: $0.02 (double standard)

# =============================================================================
# TREND FILTERS (Picture of Power)
# =============================================================================
# "Near" the 20 MA - Velez: "enter near the 20, not away"
# Quantified: Within 1% of 20 MA price (set to None to disable)
NEAR_20_MA_THRESHOLD = 0.01  # 1% - set to None to disable

# Near 20 MA threshold variants (for multi-threshold testing)
NEAR_20_MA_THRESHOLDS = {
    '1pct': 0.01,   # Current strict (~52 trades/year)
    '2pct': 0.02,   # Relaxed (~150-200 trades/year)
    '5pct': 0.05,   # Loose (~300-400 trades/year)
    '10pct': 0.10,  # Very loose
    'disable': 1.0, # Effectively disabled (100%)
}

# Ablation test configurations
ABLATION_CONFIGS = {
    'near_ma': {'near_20_ma_threshold': 1.0},  # Disable Near MA filter
    'max_ignored': {'max_ignored_bars': 10},   # Increase max ignored bars
    'body_ratio': {'ignored_body_max_ratio': 1.0},  # Disable body ratio filter
    'pop': {'picture_of_power': False},  # Disable Picture of Power
    'all': {  # Disable all filters
        'near_20_ma_threshold': 1.0,
        'max_ignored_bars': 10,
        'ignored_body_max_ratio': 1.0,
        'picture_of_power': False,
    },
}

# 20 MA Slope - Velez: "20 MA must be rising"
# Quantified: Slope calculated over N bars
SMA_SLOPE_LOOKBACK = 3

# =============================================================================
# RISK MANAGEMENT
# =============================================================================
# Profit target: Velez says "away from 20 MA" - quantified as R-multiple
PROFIT_TARGET_R = 1.5

# Position size: Velez: "50% of capital"
CAPITAL_ALLOCATION = 0.50

# Commission: IBKR Pro rate
COMMISSION_PER_SHARE = 0.005
MIN_COMMISSION = 1.00
MAX_COMMISSION_PCT = 0.01  # Cap at 1% of trade value

# =============================================================================
# MARKET HOURS (Eastern Time)
# =============================================================================
# Skip opening volatility
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 34  # Skip first 4 minutes

# Liquidate before close
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 58  # 2 minutes before close

# End of day liquidation
EOD_HOUR = 16
EOD_MINUTE = 0

# =============================================================================
# SYMBOLS
# =============================================================================
DEFAULT_SYMBOLS = ['TSLA', 'NFLX', 'PLTR', 'QCOM', 'V']

# =============================================================================
# CAPITAL
# =============================================================================
DEFAULT_INITIAL_CASH = 100000.0

# =============================================================================
# DATA PATHS
# =============================================================================
DATA_DIR = 'data'
RAW_DATA_DIR = f'{DATA_DIR}/raw'
PROCESSED_DATA_DIR = f'{DATA_DIR}/processed'
RESULTS_DIR = f'{DATA_DIR}/results'

# =============================================================================
# IBKR CONNECTION
# =============================================================================
IBKR_HOST = '127.0.0.1'
IBKR_PORT = 7497  # Paper trading (use 7496 for live)
IBKR_CLIENT_ID = 101
