"""
Exit strategies for RBI backtest.
All strategies share the same stop loss logic but differ in profit-taking approach.
"""

from typing import Dict, Optional, Tuple
import pandas as pd
from datetime import datetime

# Import config for EOD settings
from config import EOD_HOUR, EOD_MINUTE


def check_stop_and_eod(bar: pd.Series, stop_price: float, bar_time: datetime) -> Tuple[bool, bool, bool]:
    """
    Check if stop or EOD is hit for a given bar.
    Returns: (hit_stop, is_eod, eod_takes_precedence)
    """
    hit_stop = bar['low'] <= stop_price
    is_eod = bar_time.hour == EOD_HOUR and bar_time.minute >= EOD_MINUTE - 2  # 3:58 PM
    return hit_stop, is_eod, is_eod


def exit_strategy_a(entry_price: float, stop_price: float, target_price: float,
                    future_bars: pd.DataFrame) -> Dict:
    """
    Strategy A: 1.5R Fixed Target
    Exit when HIGH >= target OR LOW <= stop.
    Same-bar: always assume stop hit first (conservative).
    """
    for bar_time, bar in future_bars.iterrows():
        hit_target = bar['high'] >= target_price
        hit_stop = bar['low'] <= stop_price
        is_eod = bar_time.hour == EOD_HOUR and bar_time.minute >= EOD_MINUTE - 2

        # Same-bar conflict: assume stop hit first (conservative, no hindsight)
        if hit_target and hit_stop:
            return {
                'exit_price': stop_price,
                'exit_type': 'stop',
                'exit_time': bar_time
            }
        elif hit_stop:
            return {
                'exit_price': stop_price,
                'exit_type': 'stop',
                'exit_time': bar_time
            }
        elif hit_target:
            return {
                'exit_price': target_price,
                'exit_type': 'target',
                'exit_time': bar_time
            }
        elif is_eod:
            return {
                'exit_price': bar['close'],
                'exit_type': 'eod',
                'exit_time': bar_time
            }

    # If no exit found, return last bar close
    if not future_bars.empty:
        last_time = future_bars.index[-1]
        return {
            'exit_price': future_bars.iloc[-1]['close'],
            'exit_type': 'open',  # Position still open at end of data
            'exit_time': last_time
        }
    return None


def exit_strategy_b1(entry_price: float, stop_price: float,
                     future_bars: pd.DataFrame, sma_column: str = 'sma_short') -> Dict:
    """
    Strategy B1: SMA Divergence 1%
    Exit when HIGH >= 1.01 * sma_20 (price is 1% above 20 MA).
    Stop loss same as Strategy A.
    """
    divergence_pct = 1.01  # 1% above

    for bar_time, bar in future_bars.iterrows():
        sma_20 = bar.get(sma_column)
        if pd.isna(sma_20):
            continue

        divergence_target = sma_20 * divergence_pct
        hit_divergence = bar['high'] >= divergence_target
        hit_stop = bar['low'] <= stop_price
        is_eod = bar_time.hour == EOD_HOUR and bar_time.minute >= EOD_MINUTE - 2

        # Same-bar conflict: assume stop hit first
        if hit_divergence and hit_stop:
            return {
                'exit_price': stop_price,
                'exit_type': 'stop',
                'exit_time': bar_time
            }
        elif hit_stop:
            return {
                'exit_price': stop_price,
                'exit_type': 'stop',
                'exit_time': bar_time
            }
        elif hit_divergence:
            return {
                'exit_price': divergence_target,
                'exit_type': 'divergence_1pct',
                'exit_time': bar_time
            }
        elif is_eod:
            return {
                'exit_price': bar['close'],
                'exit_type': 'eod',
                'exit_time': bar_time
            }

    # If no exit found
    if not future_bars.empty:
        last_time = future_bars.index[-1]
        return {
            'exit_price': future_bars.iloc[-1]['close'],
            'exit_type': 'open',
            'exit_time': last_time
        }
    return None


def exit_strategy_b2(entry_price: float, stop_price: float,
                     future_bars: pd.DataFrame, sma_column: str = 'sma_short') -> Dict:
    """
    Strategy B2: SMA Divergence 2%
    Exit when HIGH >= 1.02 * sma_20 (price is 2% above 20 MA).
    Stop loss same as Strategy A.
    """
    divergence_pct = 1.02  # 2% above

    for bar_time, bar in future_bars.iterrows():
        sma_20 = bar.get(sma_column)
        if pd.isna(sma_20):
            continue

        divergence_target = sma_20 * divergence_pct
        hit_divergence = bar['high'] >= divergence_target
        hit_stop = bar['low'] <= stop_price
        is_eod = bar_time.hour == EOD_HOUR and bar_time.minute >= EOD_MINUTE - 2

        # Same-bar conflict: assume stop hit first
        if hit_divergence and hit_stop:
            return {
                'exit_price': stop_price,
                'exit_type': 'stop',
                'exit_time': bar_time
            }
        elif hit_stop:
            return {
                'exit_price': stop_price,
                'exit_type': 'stop',
                'exit_time': bar_time
            }
        elif hit_divergence:
            return {
                'exit_price': divergence_target,
                'exit_type': 'divergence_2pct',
                'exit_time': bar_time
            }
        elif is_eod:
            return {
                'exit_price': bar['close'],
                'exit_type': 'eod',
                'exit_time': bar_time
            }

    # If no exit found
    if not future_bars.empty:
        last_time = future_bars.index[-1]
        return {
            'exit_price': future_bars.iloc[-1]['close'],
            'exit_type': 'open',
            'exit_time': last_time
        }
    return None


def exit_strategy_b3(entry_price: float, stop_price: float,
                     future_bars: pd.DataFrame, sma_column: str = 'sma_short') -> Dict:
    """
    Strategy B3: MA Cross
    Exit when CLOSE falls below 20 MA.
    Stop loss same as Strategy A.
    """
    for bar_time, bar in future_bars.iterrows():
        sma_20 = bar.get(sma_column)
        if pd.isna(sma_20):
            continue

        ma_cross = bar['close'] < sma_20
        hit_stop = bar['low'] <= stop_price
        is_eod = bar_time.hour == EOD_HOUR and bar_time.minute >= EOD_MINUTE - 2

        # Same-bar conflict: assume stop hit first
        if ma_cross and hit_stop:
            return {
                'exit_price': stop_price,
                'exit_type': 'stop',
                'exit_time': bar_time
            }
        elif hit_stop:
            return {
                'exit_price': stop_price,
                'exit_type': 'stop',
                'exit_time': bar_time
            }
        elif ma_cross:
            # Exit at close when price crosses below MA
            return {
                'exit_price': bar['close'],
                'exit_type': 'ma_cross',
                'exit_time': bar_time
            }
        elif is_eod:
            return {
                'exit_price': bar['close'],
                'exit_type': 'eod',
                'exit_time': bar_time
            }

    # If no exit found
    if not future_bars.empty:
        last_time = future_bars.index[-1]
        return {
            'exit_price': future_bars.iloc[-1]['close'],
            'exit_type': 'open',
            'exit_time': last_time
        }
    return None


def exit_strategy_b4(entry_price: float, stop_price: float,
                     future_bars: pd.DataFrame, sma_column: str = 'sma_short') -> Dict:
    """
    Strategy B4: MA Cross with Tighter Stop ($0.005 buffer)
    Same exit logic as B3 but uses reduced stop loss distance.
    - Reduces risk per trade by ~50%
    - More sensitive to false breakdowns
    - Better for strong momentum plays
    """
    for bar_time, bar in future_bars.iterrows():
        sma_20 = bar.get(sma_column)
        if pd.isna(sma_20):
            continue

        ma_cross = bar['close'] < sma_20
        hit_stop = bar['low'] <= stop_price
        is_eod = bar_time.hour == EOD_HOUR and bar_time.minute >= EOD_MINUTE - 2

        # Same-bar conflict: assume stop hit first
        if ma_cross and hit_stop:
            return {
                'exit_price': stop_price,
                'exit_type': 'stop',
                'exit_time': bar_time
            }
        elif hit_stop:
            return {
                'exit_price': stop_price,
                'exit_type': 'stop',
                'exit_time': bar_time
            }
        elif ma_cross:
            return {
                'exit_price': bar['close'],
                'exit_type': 'ma_cross',
                'exit_time': bar_time
            }
        elif is_eod:
            return {
                'exit_price': bar['close'],
                'exit_type': 'eod',
                'exit_time': bar_time
            }

    # If no exit found
    if not future_bars.empty:
        last_time = future_bars.index[-1]
        return {
            'exit_price': future_bars.iloc[-1]['close'],
            'exit_type': 'open',
            'exit_time': last_time
        }
    return None


def exit_strategy_b5(entry_price: float, stop_price: float,
                     future_bars: pd.DataFrame, sma_column: str = 'sma_short') -> Dict:
    """
    Strategy B5: MA Cross with Looser Stop ($0.02 buffer)
    Same exit logic as B3 but uses increased stop loss distance.
    - Increases risk per trade by ~100%
    - More room for normal price fluctuations
    - Better for choppy/volatile markets
    """
    for bar_time, bar in future_bars.iterrows():
        sma_20 = bar.get(sma_column)
        if pd.isna(sma_20):
            continue

        ma_cross = bar['close'] < sma_20
        hit_stop = bar['low'] <= stop_price
        is_eod = bar_time.hour == EOD_HOUR and bar_time.minute >= EOD_MINUTE - 2

        # Same-bar conflict: assume stop hit first
        if ma_cross and hit_stop:
            return {
                'exit_price': stop_price,
                'exit_type': 'stop',
                'exit_time': bar_time
            }
        elif hit_stop:
            return {
                'exit_price': stop_price,
                'exit_type': 'stop',
                'exit_time': bar_time
            }
        elif ma_cross:
            return {
                'exit_price': bar['close'],
                'exit_type': 'ma_cross',
                'exit_time': bar_time
            }
        elif is_eod:
            return {
                'exit_price': bar['close'],
                'exit_type': 'eod',
                'exit_time': bar_time
            }

    # If no exit found
    if not future_bars.empty:
        last_time = future_bars.index[-1]
        return {
            'exit_price': future_bars.iloc[-1]['close'],
            'exit_type': 'open',
            'exit_time': last_time
        }
    return None


# Strategy registry for easy iteration
STRATEGIES = {
    'A': exit_strategy_a,
    'B1': exit_strategy_b1,
    'B2': exit_strategy_b2,
    'B3': exit_strategy_b3,
    'B4': exit_strategy_b4,  # MA Cross with tighter stop ($0.005)
    'B5': exit_strategy_b5,  # MA Cross with looser stop ($0.02)
}


def run_strategy(strategy_name: str, entry_price: float, stop_price: float,
                 target_price: float, future_bars: pd.DataFrame) -> Optional[Dict]:
    """
    Run a specific exit strategy and return the exit result.
    """
    if strategy_name not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy_name}")

    strategy_func = STRATEGIES[strategy_name]

    if strategy_name == 'A':
        return strategy_func(entry_price, stop_price, target_price, future_bars)
    else:
        # B strategies use SMA divergence
        return strategy_func(entry_price, stop_price, future_bars)
