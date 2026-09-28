"""
Performance metrics calculation for RBI backtest.
Calculates standard trading metrics including risk-adjusted returns.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional

# Annualization factor for 2-minute bars
# Approximately 195 trading days * 195 bars/day = ~38,025 bars/year
ANNUALIZATION_FACTOR = np.sqrt(38025)

# Risk-free rate (approximate annual, converted to per-bar)
RISK_FREE_RATE_ANNUAL = 0.05  # 5% annual
RISK_FREE_RATE_PER_BAR = RISK_FREE_RATE_ANNUAL / 38025


def calculate_win_rate(trades_df: pd.DataFrame) -> float:
    """Calculate win rate as percentage of winning trades."""
    if trades_df.empty:
        return 0.0
    wins = len(trades_df[trades_df['pnl'] > 0])
    return wins / len(trades_df)


def calculate_profit_factor(trades_df: pd.DataFrame) -> float:
    """Calculate profit factor = gross profit / gross loss."""
    if trades_df.empty:
        return 0.0

    gross_profit = trades_df[trades_df['pnl'] > 0]['pnl'].sum()
    gross_loss = abs(trades_df[trades_df['pnl'] < 0]['pnl'].sum())

    if gross_loss == 0:
        return float('inf') if gross_profit > 0 else 0.0

    return gross_profit / gross_loss


def calculate_max_drawdown(equity_curve: pd.Series) -> float:
    """
    Calculate maximum drawdown from equity curve.
    Returns as a decimal (e.g., 0.15 for 15% drawdown).
    """
    if equity_curve.empty or len(equity_curve) < 2:
        return 0.0

    # Calculate running maximum
    running_max = equity_curve.cummax()

    # Calculate drawdown at each point
    drawdown = (equity_curve - running_max) / running_max

    # Return worst (most negative) drawdown
    return abs(drawdown.min())


def build_equity_curve(trades_df: pd.DataFrame, initial_capital: float) -> pd.Series:
    """
    Build equity curve from trades.
    Returns a Series with timestamps as index and equity values.
    """
    if trades_df.empty:
        return pd.Series([initial_capital], index=[pd.Timestamp.now()])

    # Sort by exit time
    trades_sorted = trades_df.sort_values('exit_time')

    equity = [initial_capital]
    timestamps = [trades_sorted['entry_time'].iloc[0]]

    cumulative_pnl = 0
    for _, trade in trades_sorted.iterrows():
        cumulative_pnl += trade['pnl']
        equity.append(initial_capital + cumulative_pnl)
        timestamps.append(trade['exit_time'])

    return pd.Series(equity, index=timestamps)


def calculate_returns(trades_df: pd.DataFrame, initial_capital: float) -> pd.Series:
    """Calculate per-trade returns as a Series."""
    if trades_df.empty:
        return pd.Series([])

    trades_sorted = trades_df.sort_values('exit_time')

    # Build equity progression
    equity = initial_capital
    returns = []

    for _, trade in trades_sorted.iterrows():
        ret = trade['pnl'] / equity
        returns.append(ret)
        equity += trade['pnl']

    return pd.Series(returns)


def calculate_simple_return(net_pnl: float, initial_capital: float) -> float:
    """Calculate simple return = net_pnl / initial_capital."""
    if initial_capital == 0:
        return 0.0
    return net_pnl / initial_capital


def calculate_log_return(net_pnl: float, initial_capital: float) -> float:
    """Calculate log return = ln(1 + simple_return)."""
    simple_return = calculate_simple_return(net_pnl, initial_capital)
    if simple_return <= -1:
        return float('-inf')
    return np.log(1 + simple_return)


def calculate_sharpe_ratio(returns: pd.Series, annualize: bool = True) -> float:
    """
    Calculate Sharpe ratio = (mean return - risk-free rate) / std dev of returns.
    Optionally annualized.
    """
    if returns.empty or len(returns) < 2:
        return 0.0

    mean_return = returns.mean()
    std_return = returns.std()

    if std_return == 0:
        return 0.0

    # Excess return over risk-free rate
    excess_return = mean_return - RISK_FREE_RATE_PER_BAR

    sharpe = excess_return / std_return

    if annualize:
        sharpe *= ANNUALIZATION_FACTOR

    return sharpe


def calculate_sortino_ratio(returns: pd.Series, annualize: bool = True) -> float:
    """
    Calculate Sortino ratio = (mean return - risk-free rate) / downside deviation.
    Downside deviation only considers negative returns.
    """
    if returns.empty or len(returns) < 2:
        return 0.0

    mean_return = returns.mean()

    # Calculate downside returns (only negative)
    downside_returns = returns[returns < 0]

    if len(downside_returns) == 0:
        return float('inf') if mean_return > 0 else 0.0

    downside_std = np.sqrt((downside_returns ** 2).mean())

    if downside_std == 0:
        return 0.0

    # Excess return over risk-free rate
    excess_return = mean_return - RISK_FREE_RATE_PER_BAR

    sortino = excess_return / downside_std

    if annualize:
        sortino *= ANNUALIZATION_FACTOR

    return sortino


def calculate_all_metrics(trades_df: pd.DataFrame, initial_capital: float) -> Dict:
    """
    Calculate all performance metrics for a set of trades.
    Returns a comprehensive metrics dictionary.
    """
    if trades_df.empty:
        return {
            'total_trades': 0,
            'win_rate': 0.0,
            'profit_factor': 0.0,
            'max_drawdown': 0.0,
            'total_pnl_gross': 0.0,
            'total_pnl_net': 0.0,
            'total_commission': 0.0,
            'simple_return': 0.0,
            'log_return': 0.0,
            'sharpe_ratio': 0.0,
            'sortino_ratio': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'avg_trade': 0.0,
            'win_loss_ratio': 0.0,
        }

    # Basic counts
    wins = trades_df[trades_df['pnl'] > 0]
    losses = trades_df[trades_df['pnl'] <= 0]

    # P&L calculations
    total_pnl_net = trades_df['pnl'].sum()
    total_pnl_gross = trades_df['gross_pnl'].sum() if 'gross_pnl' in trades_df.columns else total_pnl_net
    total_commission = trades_df['commission'].sum() if 'commission' in trades_df.columns else 0

    # Build equity curve and calculate returns
    equity_curve = build_equity_curve(trades_df, initial_capital)
    returns = calculate_returns(trades_df, initial_capital)

    # Calculate all metrics
    metrics = {
        'total_trades': len(trades_df),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': calculate_win_rate(trades_df),
        'profit_factor': calculate_profit_factor(trades_df),
        'max_drawdown': calculate_max_drawdown(equity_curve),
        'total_pnl_gross': total_pnl_gross,
        'total_pnl_net': total_pnl_net,
        'total_commission': total_commission,
        'simple_return': calculate_simple_return(total_pnl_net, initial_capital),
        'log_return': calculate_log_return(total_pnl_net, initial_capital),
        'sharpe_ratio': calculate_sharpe_ratio(returns),
        'sortino_ratio': calculate_sortino_ratio(returns),
        'avg_win': wins['pnl'].mean() if len(wins) > 0 else 0.0,
        'avg_loss': losses['pnl'].mean() if len(losses) > 0 else 0.0,
        'avg_trade': trades_df['pnl'].mean(),
        'win_loss_ratio': (wins['pnl'].mean() / abs(losses['pnl'].mean())) if len(losses) > 0 and losses['pnl'].mean() != 0 else 0.0,
        'final_equity': initial_capital + total_pnl_net,
    }

    return metrics


def format_metrics_for_display(metrics: Dict) -> str:
    """Format metrics dictionary for console display."""
    if metrics.get('total_trades', 0) == 0:
        return "No trades executed"

    lines = [
        f"Trades:         {metrics['total_trades']} ({metrics.get('wins', 0)}W / {metrics.get('losses', 0)}L)",
        f"Win Rate:       {metrics['win_rate']*100:.1f}%",
        f"Profit Factor:  {metrics['profit_factor']:.2f}",
        f"Max Drawdown:   {metrics['max_drawdown']*100:.1f}%",
        "",
        f"Gross P&L:      ${metrics['total_pnl_gross']:,.2f}",
        f"Commission:     ${metrics['total_commission']:,.2f}",
        f"Net P&L:        ${metrics['total_pnl_net']:,.2f}",
        "",
        f"Simple Return:  {metrics['simple_return']*100:.2f}%",
        f"Log Return:     {metrics['log_return']*100:.2f}%",
        f"Sharpe Ratio:   {metrics['sharpe_ratio']:.2f}",
        f"Sortino Ratio:  {metrics['sortino_ratio']:.2f}",
        "",
        f"Avg Win:        ${metrics['avg_win']:,.2f}",
        f"Avg Loss:       ${metrics['avg_loss']:,.2f}",
        f"Avg Trade:      ${metrics['avg_trade']:,.2f}",
    ]

    return "\n".join(lines)


if __name__ == '__main__':
    # Quick test with sample data
    print("Metrics module loaded successfully")

    # Create sample trades for testing
    sample_trades = pd.DataFrame([
        {'pnl': 100, 'gross_pnl': 105, 'commission': 5, 'exit_time': pd.Timestamp('2025-01-01 10:00'), 'entry_time': pd.Timestamp('2025-01-01 09:30')},
        {'pnl': -50, 'gross_pnl': -45, 'commission': 5, 'exit_time': pd.Timestamp('2025-01-01 11:00'), 'entry_time': pd.Timestamp('2025-01-01 10:30')},
        {'pnl': 75, 'gross_pnl': 80, 'commission': 5, 'exit_time': pd.Timestamp('2025-01-01 12:00'), 'entry_time': pd.Timestamp('2025-01-01 11:30')},
        {'pnl': -25, 'gross_pnl': -20, 'commission': 5, 'exit_time': pd.Timestamp('2025-01-01 13:00'), 'entry_time': pd.Timestamp('2025-01-01 12:30')},
    ])

    metrics = calculate_all_metrics(sample_trades, 10000)
    print("\nSample metrics:")
    print(format_metrics_for_display(metrics))
