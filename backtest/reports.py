"""
HTML report generation for RBI backtest using Plotly.
Dark mode dashboard.
"""
from __future__ import annotations

import os
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
import pandas as pd

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    go = None
    make_subplots = None
    print("Warning: plotly not installed. Run: pip install plotly")

from metrics import build_equity_curve, calculate_all_metrics

# Dark theme - professional hierarchy
COLORS = {
    'bg_page': '#000000',       # True black base
    'bg_card': '#0d0d0d',       # Elevated card
    'bg_elevated': '#1a1a1a',   # Tables/headers
    'bg_chart': '#0a0a0a',      # Chart area
    'text_primary': '#e8e8e8',  # Soft white (not harsh)
    'text_secondary': '#a0a0a0', # Readable muted
    'border': '#2a2a2a',        # Visible border
    'accent': '#00d4aa',        # Teal
    'positive': '#00c853',      # Green
    'negative': '#ff5252',      # Red
}

# Consistent strategy colors
STRATEGY_COLORS = {
    'A': '#00d4aa',   # Teal
    'B1': '#7c4dff',  # Purple
    'B2': '#ff9100',  # Orange
    'B3': '#ff5252',  # Coral red
    'B4': '#00bcd4',  # Cyan (tighter stop)
    'B5': '#e91e63',  # Pink (looser stop)
}


def get_dark_layout(title: str = '', height: int = 350) -> dict:
    """Get consistent dark layout for all charts."""
    return dict(
        title=dict(text=title, font=dict(color=COLORS['text_primary'], size=16)),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor=COLORS['bg_chart'],
        font=dict(color=COLORS['text_primary'], family='Inter, -apple-system, system-ui, sans-serif'),
        xaxis=dict(
            showgrid=False,
            color=COLORS['text_secondary'],
            linecolor=COLORS['border'],
            zeroline=False,
        ),
        yaxis=dict(
            showgrid=False,
            color=COLORS['text_secondary'],
            linecolor=COLORS['border'],
            zeroline=False,
        ),
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,           # Above chart (no overflow)
            xanchor='center',
            x=0.5,
            bgcolor='rgba(13, 13, 13, 0.9)',  # Subtle background
            font=dict(color=COLORS['text_primary']),
        ),
        margin=dict(l=60, r=40, t=80, b=40),  # More top margin for legend
        height=height,
        hovermode='x unified',
    )


def create_equity_curve_chart(trades_df: pd.DataFrame, initial_capital: float,
                               strategy_name: str = None) -> Any:
    """Create interactive equity curve chart."""
    if not PLOTLY_AVAILABLE:
        return None

    equity_curve = build_equity_curve(trades_df, initial_capital)

    fig = go.Figure()
    color = STRATEGY_COLORS.get(strategy_name, COLORS['accent'])

    fig.add_trace(go.Scatter(
        x=equity_curve.index,
        y=equity_curve.values,
        mode='lines',
        name=f'Strategy {strategy_name}' if strategy_name else 'Equity',
        line=dict(color=color, width=2),
        hovertemplate='%{x}<br>Equity: $%{y:,.2f}<extra></extra>'
    ))

    # Add initial capital reference line
    fig.add_hline(
        y=initial_capital,
        line_dash="dot",
        line_color=COLORS['text_secondary'],
        annotation_text=f"Initial: ${initial_capital:,.0f}",
        annotation_font_color=COLORS['text_secondary']
    )

    fig.update_layout(**get_dark_layout('Equity Curve', height=350))

    return fig


def create_drawdown_chart(trades_df: pd.DataFrame, initial_capital: float) -> Any:
    """Create drawdown chart showing peak-to-trough declines."""
    if not PLOTLY_AVAILABLE:
        return None

    equity_curve = build_equity_curve(trades_df, initial_capital)

    # Calculate drawdown
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max * 100  # As percentage

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=drawdown.index,
        y=drawdown.values,
        mode='lines',
        fill='tozeroy',
        name='Drawdown',
        line=dict(color=COLORS['negative'], width=2),  # Thicker line
        fillcolor='rgba(255, 82, 82, 0.35)',           # Higher opacity
        hovertemplate='%{x}<br>Drawdown: %{y:.2f}%<extra></extra>'
    ))

    layout = get_dark_layout('Drawdown', height=320)   # More height
    layout['yaxis']['ticksuffix'] = '%'
    fig.update_layout(**layout)

    return fig


def create_trade_distribution_chart(trades_df: pd.DataFrame) -> Any:
    """Create donut chart showing trade distribution by symbol."""
    if not PLOTLY_AVAILABLE or trades_df.empty:
        return None

    symbol_counts = trades_df['symbol'].value_counts()

    # Professional color palette for pie chart
    pie_colors = ['#00d4aa', '#7c4dff', '#ff9100', '#ff5252', '#00bcd4', '#e91e63']

    fig = go.Figure(data=[go.Pie(
        labels=symbol_counts.index,
        values=symbol_counts.values,
        hole=0.5,
        textinfo='label+percent',
        textposition='outside',
        textfont=dict(color=COLORS['text_primary']),
        marker=dict(colors=pie_colors[:len(symbol_counts)]),
        hovertemplate='%{label}<br>Trades: %{value}<br>%{percent}<extra></extra>'
    )])

    layout = get_dark_layout('Trade Distribution', height=320)
    layout['showlegend'] = False
    fig.update_layout(**layout)

    return fig


def create_strategy_comparison_chart(all_results: Dict[str, Tuple[pd.DataFrame, Dict]],
                                      initial_capital: float) -> Any:
    """Create grouped bar chart comparing exit strategies."""
    if not PLOTLY_AVAILABLE:
        return None

    strategies = list(all_results.keys())
    metrics_to_compare = ['win_rate', 'profit_factor', 'total_pnl', 'return_pct']
    metric_labels = ['Win Rate (%)', 'Profit Factor', 'Net P&L ($)', 'Return (%)']

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=metric_labels,
        vertical_spacing=0.15,
        horizontal_spacing=0.1
    )

    colors = [STRATEGY_COLORS.get(s, '#888888') for s in strategies]

    for i, (metric, label) in enumerate(zip(metrics_to_compare, metric_labels)):
        row = i // 2 + 1
        col = i % 2 + 1

        values = []
        for strategy in strategies:
            _, metrics = all_results[strategy]
            # win_rate is already a percentage from backtest.py, don't multiply by 100
            values.append(metrics.get(metric, 0))

        fig.add_trace(
            go.Bar(
                x=strategies,
                y=values,
                name=label,
                marker_color=colors,
                showlegend=False,
                hovertemplate='Strategy %{x}<br>' + label + ': %{y:.2f}<extra></extra>'
            ),
            row=row, col=col
        )

    # Apply dark theme
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor=COLORS['bg_chart'],
        font=dict(color=COLORS['text_primary'], family='Inter, -apple-system, system-ui, sans-serif'),
        height=500,
        margin=dict(l=60, r=40, t=60, b=40),
    )

    # Update all axes
    fig.update_xaxes(showgrid=False, color=COLORS['text_secondary'], linecolor=COLORS['border'])
    fig.update_yaxes(showgrid=False, color=COLORS['text_secondary'], linecolor=COLORS['border'])

    # Update subplot titles
    for annotation in fig.layout.annotations:
        annotation.font.color = COLORS['text_secondary']

    return fig


def create_combined_equity_chart(all_results: Dict[str, Tuple[pd.DataFrame, Dict]],
                                  initial_capital: float) -> Any:
    """Create equity curves for all strategies on one chart."""
    if not PLOTLY_AVAILABLE:
        return None

    fig = go.Figure()

    for strategy_name, (trades_df, metrics) in all_results.items():
        if trades_df.empty:
            continue

        equity_curve = build_equity_curve(trades_df, initial_capital)

        fig.add_trace(go.Scatter(
            x=equity_curve.index,
            y=equity_curve.values,
            mode='lines',
            name=f'Strategy {strategy_name}',
            line=dict(color=STRATEGY_COLORS.get(strategy_name, '#888888'), width=2),
            hovertemplate=f'Strategy {strategy_name}<br>' + '%{x}<br>Equity: $%{y:,.2f}<extra></extra>'
        ))

    fig.add_hline(
        y=initial_capital,
        line_dash="dot",
        line_color=COLORS['text_secondary'],
        annotation_text=f"Initial: ${initial_capital:,.0f}",
        annotation_font_color=COLORS['text_secondary']
    )

    fig.update_layout(**get_dark_layout('Equity Curves - All Strategies', height=400))

    return fig


def create_metrics_table_html(all_results: Dict[str, Tuple[pd.DataFrame, Dict]]) -> str:
    """Create HTML table of metrics for all strategies."""
    headers = ['Metric', 'Strategy A', 'Strategy B1', 'Strategy B2', 'Strategy B3']

    metrics_rows = [
        ('Trades', 'trades', '{:.0f}', False),
        ('Win Rate', 'win_rate', '{:.1f}%', False),
        ('Profit Factor', 'profit_factor', '{:.2f}', False),
        ('Net P&L', 'total_pnl', '${:,.2f}', True),
        ('Return', 'return_pct', '{:.2f}%', True),
        ('Max Drawdown', 'max_drawdown', '{:.2%}', True),
        ('Sharpe Ratio', 'sharpe_ratio', '{:.2f}', False),
        ('Sortino Ratio', 'sortino_ratio', '{:.2f}', False),
        ('Commissions', 'total_commissions', '${:,.2f}', False),
    ]

    html = '<table class="metrics-table">\n<thead><tr>'
    for h in headers:
        html += f'<th>{h}</th>'
    html += '</tr></thead>\n<tbody>\n'

    for label, key, fmt, highlight_pnl in metrics_rows:
        html += f'<tr><td class="metric-label">{label}</td>'
        for strategy in ['A', 'B1', 'B2', 'B3']:
            if strategy in all_results:
                _, metrics = all_results[strategy]
                value = metrics.get(key, 0)
                try:
                    formatted = fmt.format(value) if value is not None else 'N/A'
                except:
                    formatted = str(value)

                # Add color class for P&L values
                value_class = ''
                if highlight_pnl and value is not None:
                    if isinstance(value, (int, float)):
                        value_class = ' class="positive"' if value > 0 else ' class="negative"' if value < 0 else ''
            else:
                formatted = 'N/A'
                value_class = ''
            html += f'<td{value_class}>{formatted}</td>'
        html += '</tr>\n'

    html += '</tbody></table>'
    return html


def generate_html_report(all_results: Dict[str, Tuple[pd.DataFrame, Dict]],
                          initial_capital: float,
                          run_id: str,
                          start_date: str,
                          end_date: str,
                          symbols: List[str],
                          output_dir: str = 'reports',
                          threshold_label: str = None) -> str:
    """
    Generate complete HTML report with all charts and metrics.
    Returns the path to the generated report.

    Args:
        threshold_label: Near 20 MA threshold label (e.g., '1pct', '2pct', '5pct')
    """
    if not PLOTLY_AVAILABLE:
        print("Error: plotly not installed. Cannot generate HTML report.")
        return None

    os.makedirs(output_dir, exist_ok=True)

    # Generate all charts
    charts = {}

    # Combined equity chart (all strategies)
    charts['equity_all'] = create_combined_equity_chart(all_results, initial_capital)

    # Strategy comparison
    charts['comparison'] = create_strategy_comparison_chart(all_results, initial_capital)

    # Individual strategy charts (use Strategy A for drawdown and distribution)
    if 'A' in all_results and not all_results['A'][0].empty:
        trades_a = all_results['A'][0]
        charts['drawdown'] = create_drawdown_chart(trades_a, initial_capital)
        charts['distribution'] = create_trade_distribution_chart(trades_a)

    # Convert charts to HTML
    chart_html = {}
    for name, fig in charts.items():
        if fig is not None:
            chart_html[name] = fig.to_html(full_html=False, include_plotlyjs='cdn')
        else:
            chart_html[name] = '<p class="no-data">Chart unavailable</p>'

    # Generate metrics table
    metrics_table = create_metrics_table_html(all_results)

    # Build HTML report with dark theme
    html_template = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RBI Backtest Report - {run_id}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}

        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            line-height: 1.5;
            color: {COLORS['text_primary']};
            background: {COLORS['bg_page']};
            padding: 24px;
            min-height: 100vh;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        .header {{
            background: linear-gradient(135deg, {COLORS['bg_card']} 0%, {COLORS['bg_elevated']} 100%);
            border: 1px solid {COLORS['border']};
            padding: 32px;
            border-radius: 12px;
            margin-bottom: 24px;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.6);
        }}

        .header h1 {{
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 8px;
            background: linear-gradient(90deg, {COLORS['accent']}, #7c4dff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}

        .header p {{
            color: {COLORS['text_secondary']};
            font-size: 14px;
        }}

        .header .run-info {{
            display: flex;
            gap: 24px;
            margin-top: 16px;
            flex-wrap: wrap;
        }}

        .header .info-item {{
            background: {COLORS['bg_page']};
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            font-family: 'JetBrains Mono', monospace;
        }}

        .card {{
            background: {COLORS['bg_card']};
            border: 1px solid {COLORS['border']};
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
        }}

        .card h2 {{
            color: {COLORS['text_primary']};
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 20px;
            padding-bottom: 12px;
            border-bottom: 1px solid {COLORS['border']};
        }}

        .metrics-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }}

        .metrics-table th {{
            padding: 14px 16px;
            text-align: right;
            background: {COLORS['bg_elevated']};
            color: {COLORS['accent']};
            font-weight: 600;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid {COLORS['border']};
        }}

        .metrics-table th:first-child {{
            text-align: left;
        }}

        .metrics-table td {{
            padding: 14px 16px;
            text-align: right;
            border-bottom: 1px solid {COLORS['border']};
            font-family: 'JetBrains Mono', monospace;
            font-size: 13px;
        }}

        .metrics-table td.metric-label {{
            text-align: left;
            font-family: 'Inter', sans-serif;
            font-weight: 500;
            color: {COLORS['text_secondary']};
        }}

        .metrics-table tr:hover {{
            background: rgba(255, 255, 255, 0.05);
        }}

        .metrics-table td.positive {{
            color: {COLORS['positive']};
        }}

        .metrics-table td.negative {{
            color: {COLORS['negative']};
        }}

        .grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 24px;
        }}

        @media (max-width: 1200px) {{
            .grid {{
                grid-template-columns: 1fr;
            }}
        }}

        .footer {{
            text-align: center;
            padding: 32px 20px;
            color: {COLORS['text_secondary']};
            font-size: 12px;
            border-top: 1px solid {COLORS['border']};
            margin-top: 24px;
        }}

        .no-data {{
            color: {COLORS['text_secondary']};
            font-style: italic;
            text-align: center;
            padding: 40px;
        }}

        .strategy-legend {{
            display: flex;
            gap: 16px;
            margin-bottom: 16px;
            flex-wrap: wrap;
        }}

        .strategy-legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            color: {COLORS['text_secondary']};
        }}

        .strategy-dot {{
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>RBI Strategy Backtest Report</h1>
            <p>Quantitative analysis of the Red Bar Ignored momentum continuation strategy</p>
            <div class="run-info">
                <div class="info-item">Run: {run_id}</div>
                <div class="info-item">Period: {start_date} to {end_date}</div>
                <div class="info-item">Symbols: {', '.join(symbols)}</div>
                <div class="info-item">Near 20 MA: {threshold_label or '1pct'}</div>
                <div class="info-item">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
            </div>
        </div>

        <div class="card">
            <h2>Strategy Performance Comparison</h2>
            <div class="strategy-legend">
                <div class="strategy-legend-item">
                    <div class="strategy-dot" style="background: {STRATEGY_COLORS['A']}"></div>
                    <span>A (1.5R Fixed)</span>
                </div>
                <div class="strategy-legend-item">
                    <div class="strategy-dot" style="background: {STRATEGY_COLORS['B1']}"></div>
                    <span>B1 (1% Div)</span>
                </div>
                <div class="strategy-legend-item">
                    <div class="strategy-dot" style="background: {STRATEGY_COLORS['B2']}"></div>
                    <span>B2 (2% Div)</span>
                </div>
                <div class="strategy-legend-item">
                    <div class="strategy-dot" style="background: {STRATEGY_COLORS['B3']}"></div>
                    <span>B3 (MA Cross)</span>
                </div>
                <div class="strategy-legend-item">
                    <div class="strategy-dot" style="background: {STRATEGY_COLORS['B4']}"></div>
                    <span>B4 (Tight Stop)</span>
                </div>
                <div class="strategy-legend-item">
                    <div class="strategy-dot" style="background: {STRATEGY_COLORS['B5']}"></div>
                    <span>B5 (Loose Stop)</span>
                </div>
            </div>
            {metrics_table}
        </div>

        <div class="card">
            <h2>Equity Curves</h2>
            {chart_html.get('equity_all', '')}
        </div>

        <div class="card">
            <h2>Strategy Metrics Comparison</h2>
            {chart_html.get('comparison', '')}
        </div>

        <div class="grid">
            <div class="card">
                <h2>Drawdown Analysis</h2>
                {chart_html.get('drawdown', '')}
            </div>
            <div class="card">
                <h2>Trade Distribution by Symbol</h2>
                {chart_html.get('distribution', '')}
            </div>
        </div>

        <div class="footer">
            <p>RBI 2025 Backtest &mdash; Bias-Free Implementation</p>
            <p style="margin-top: 8px;">Oliver Velez Strategy | 20/200 SMA | Near-MA Rule Enforced</p>
        </div>
    </div>
</body>
</html>'''

    # Save report
    report_path = os.path.join(output_dir, f'report_{run_id}.html')
    with open(report_path, 'w') as f:
        f.write(html_template)

    print(f"HTML report generated: {report_path}")
    return report_path


def save_run_history(all_results: Dict[str, Tuple[pd.DataFrame, Dict]],
                      run_id: str,
                      start_date: str,
                      end_date: str,
                      symbols: List[str],
                      parameters: Dict,
                      output_dir: str = 'reports/history') -> str:
    """
    Save run history to JSON file for comparison across runs.
    Returns path to the saved JSON file.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Build run history structure
    history = {
        'run_id': run_id,
        'created_at': datetime.now().isoformat(),
        'inputs': {
            'start_date': start_date,
            'end_date': end_date,
            'symbols': symbols,
            'parameters': parameters,
        },
        'outputs': {}
    }

    # Add outputs for each strategy
    for strategy_name, (trades_df, metrics) in all_results.items():
        # Clean metrics for JSON serialization
        clean_metrics = {}
        for k, v in metrics.items():
            if isinstance(v, float):
                if v != v:  # NaN check
                    clean_metrics[k] = None
                elif v == float('inf'):
                    clean_metrics[k] = 'inf'
                elif v == float('-inf'):
                    clean_metrics[k] = '-inf'
                else:
                    clean_metrics[k] = round(v, 6)
            else:
                clean_metrics[k] = v

        history['outputs'][strategy_name] = clean_metrics

    # Save to JSON file
    json_path = os.path.join(output_dir, f'run_{run_id}.json')
    with open(json_path, 'w') as f:
        json.dump(history, f, indent=2, default=str)

    print(f"Run history saved: {json_path}")
    return json_path


def list_run_history(history_dir: str = 'reports/history') -> List[str]:
    """List all available run history files."""
    if not os.path.exists(history_dir):
        return []

    files = [f for f in os.listdir(history_dir) if f.startswith('run_') and f.endswith('.json')]
    return sorted(files)


def load_run_history(run_id: str, history_dir: str = 'reports/history') -> Optional[Dict]:
    """Load a specific run history by ID."""
    json_path = os.path.join(history_dir, f'run_{run_id}.json')
    if not os.path.exists(json_path):
        return None

    with open(json_path, 'r') as f:
        return json.load(f)


def compare_runs(run_ids: List[str], history_dir: str = 'reports/history') -> pd.DataFrame:
    """
    Compare multiple runs side by side.
    Returns a DataFrame with metrics for each run.
    """
    comparison_data = []

    for run_id in run_ids:
        history = load_run_history(run_id, history_dir)
        if history is None:
            continue

        for strategy, metrics in history.get('outputs', {}).items():
            row = {
                'run_id': run_id,
                'strategy': strategy,
                **metrics
            }
            comparison_data.append(row)

    if not comparison_data:
        return pd.DataFrame()

    return pd.DataFrame(comparison_data)


def create_filter_impact_table_html(filter_impact: Dict) -> str:
    """Create HTML table showing filter impact on missed alpha."""
    if not filter_impact:
        return '<p class="no-data">No filter impact data available</p>'

    html = '''<table class="metrics-table">
    <thead><tr>
        <th style="text-align:left">Filter</th>
        <th>Rejected Trades</th>
        <th>Missed P&L</th>
        <th>% of Total Alpha</th>
        <th>Statistical Significance</th>
    </tr></thead>
    <tbody>
    '''

    for filter_name, data in filter_impact.items():
        missed_pnl = data.get('missed_pnl', 0)
        pnl_class = 'positive' if missed_pnl > 0 else 'negative' if missed_pnl < 0 else ''
        pct_alpha = data.get('pct_of_total_alpha', 0)
        p_value = data.get('p_value', None)

        # Significance indicator
        if p_value is not None:
            if p_value < 0.01:
                sig = '<span style="color:#00c853">*** p<0.01</span>'
            elif p_value < 0.05:
                sig = '<span style="color:#00d4aa">** p<0.05</span>'
            elif p_value < 0.10:
                sig = '<span style="color:#ff9100">* p<0.10</span>'
            else:
                sig = '<span style="color:#a0a0a0">n.s.</span>'
        else:
            sig = '<span style="color:#a0a0a0">-</span>'

        html += f'''<tr>
            <td class="metric-label">{filter_name}</td>
            <td>{data.get('rejected_count', 0):,}</td>
            <td class="{pnl_class}">${missed_pnl:,.2f}</td>
            <td>{pct_alpha:.1f}%</td>
            <td>{sig}</td>
        </tr>
        '''

    html += '</tbody></table>'
    return html


def create_filter_impact_chart(filter_impact: Dict) -> Any:
    """Create bar chart of filter impact on missed alpha."""
    if not PLOTLY_AVAILABLE or not filter_impact:
        return None

    filters = list(filter_impact.keys())
    missed_pnls = [data.get('missed_pnl', 0) for data in filter_impact.values()]

    # Color based on positive (green) vs negative (red) missed P&L
    colors = [COLORS['positive'] if p > 0 else COLORS['negative'] for p in missed_pnls]

    fig = go.Figure(data=[go.Bar(
        x=filters,
        y=missed_pnls,
        marker_color=colors,
        hovertemplate='%{x}<br>Missed P&L: $%{y:,.2f}<extra></extra>'
    )])

    fig.update_layout(**get_dark_layout('Missed Alpha by Filter', height=350))
    fig.update_layout(yaxis=dict(tickprefix='$', tickformat=',.0f'))

    return fig


def create_rejection_pie_chart(rejection_stats: Dict) -> Any:
    """Create pie chart of rejection reasons."""
    if not PLOTLY_AVAILABLE or not rejection_stats:
        return None

    # Filter to only rejection reasons (not totals)
    rejection_labels = {
        'rejected_picture_of_power': 'Picture of Power',
        'rejected_near_20_ma': 'Near 20 MA',
        'rejected_no_ignored_bar': 'No Ignored Bar',
        'rejected_ignored_bar_size': 'Ignored Bar Size',
        'rejected_entry_trigger': 'Entry Trigger',
        'rejected_max_ignored_bars': 'Max Ignored Bars',
    }

    labels = []
    values = []
    for key, label in rejection_labels.items():
        count = rejection_stats.get(key, 0)
        if count > 0:
            labels.append(label)
            values.append(count)

    if not values:
        return None

    colors = ['#ff5252', '#ff9100', '#7c4dff', '#00d4aa', '#00bcd4', '#e91e63']

    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        hole=0.4,
        textinfo='percent+label',
        textposition='outside',
        textfont=dict(color=COLORS['text_primary']),
        marker=dict(colors=colors[:len(labels)]),
    )])

    layout = get_dark_layout('Rejection Reasons', height=350)
    layout['showlegend'] = False
    fig.update_layout(**layout)

    return fig


def generate_combined_report(all_results: Dict[str, Tuple[pd.DataFrame, Dict]],
                              initial_capital: float,
                              run_id: str,
                              start_date: str,
                              end_date: str,
                              symbols: List[str],
                              filter_impact: Dict = None,
                              rejection_stats: Dict = None,
                              threshold_results: Dict = None,
                              ablation_results: Dict = None,
                              output_dir: str = 'reports') -> str:
    """
    Generate mega-dashboard combining financial metrics AND sensitivity analysis.

    Top section: Financial dashboard (equity curves, metrics, strategy comparison)
    Bottom section: Sensitivity analysis (filter impact, recommendations)

    Returns path to the generated report.
    """
    if not PLOTLY_AVAILABLE:
        print("Error: plotly not installed. Cannot generate HTML report.")
        return None

    os.makedirs(output_dir, exist_ok=True)

    # Generate all financial charts
    charts = {}
    charts['equity_all'] = create_combined_equity_chart(all_results, initial_capital)
    charts['comparison'] = create_strategy_comparison_chart(all_results, initial_capital)

    if 'A' in all_results and not all_results['A'][0].empty:
        trades_a = all_results['A'][0]
        charts['drawdown'] = create_drawdown_chart(trades_a, initial_capital)
        charts['distribution'] = create_trade_distribution_chart(trades_a)

    # Generate sensitivity charts (if available)
    if filter_impact:
        charts['filter_impact'] = create_filter_impact_chart(filter_impact)
    if rejection_stats:
        charts['rejection_pie'] = create_rejection_pie_chart(rejection_stats)

    # Convert charts to HTML
    chart_html = {}
    for name, fig in charts.items():
        if fig is not None:
            chart_html[name] = fig.to_html(full_html=False, include_plotlyjs='cdn')
        else:
            chart_html[name] = '<p class="no-data">Chart unavailable</p>'

    # Generate metrics table for all 6 strategies
    metrics_table = create_metrics_table_html_full(all_results)

    # Generate filter impact table
    filter_table_html = create_filter_impact_table_html(filter_impact) if filter_impact else ''

    # Build threshold comparison table
    threshold_table_html = ''
    if threshold_results:
        threshold_table_html = create_threshold_comparison_table(threshold_results)

    # Build ablation comparison table
    ablation_table_html = ''
    if ablation_results:
        ablation_table_html = create_ablation_comparison_table(ablation_results)

    # Build recommendations
    recommendations_html = ''
    if filter_impact:
        recommendations = []
        for filter_name, data in filter_impact.items():
            missed_pnl = data.get('missed_pnl', 0)
            if missed_pnl > 1000:
                recommendations.append(f"<li><strong>{filter_name}</strong>: Consider relaxing - missed ${missed_pnl:,.0f} in potential profit</li>")
            elif missed_pnl < -1000:
                recommendations.append(f"<li><strong>{filter_name}</strong>: Keep strict - prevented ${abs(missed_pnl):,.0f} in losses</li>")
        recommendations_html = '<ul>' + ''.join(recommendations) + '</ul>' if recommendations else '<p>No strong recommendations - filters appear balanced.</p>'

    # Summary stats
    best_strategy = max(all_results.items(), key=lambda x: x[1][1].get('total_pnl', 0))
    best_name, (best_trades, best_metrics) = best_strategy
    total_trades = best_metrics.get('trades', 0)
    total_pnl = best_metrics.get('total_pnl', 0)
    win_rate = best_metrics.get('win_rate', 0)
    sharpe = best_metrics.get('sharpe_ratio', 0)

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RBI Mega Dashboard - {run_id}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            line-height: 1.5;
            color: {COLORS['text_primary']};
            background: {COLORS['bg_page']};
            padding: 24px;
        }}
        .container {{ max-width: 1600px; margin: 0 auto; }}

        .header {{
            background: linear-gradient(135deg, {COLORS['bg_card']} 0%, {COLORS['bg_elevated']} 100%);
            border: 1px solid {COLORS['border']};
            padding: 32px;
            border-radius: 12px;
            margin-bottom: 24px;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.6);
        }}
        .header h1 {{
            font-size: 32px;
            font-weight: 700;
            margin-bottom: 8px;
            background: linear-gradient(90deg, {COLORS['accent']}, #7c4dff, #ff9100);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .header p {{ color: {COLORS['text_secondary']}; font-size: 14px; }}
        .header .run-info {{
            display: flex;
            gap: 16px;
            margin-top: 16px;
            flex-wrap: wrap;
        }}
        .header .info-item {{
            background: {COLORS['bg_page']};
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            font-family: 'JetBrains Mono', monospace;
        }}

        /* KPI Cards */
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-bottom: 24px;
        }}
        .kpi-card {{
            background: {COLORS['bg_card']};
            border: 1px solid {COLORS['border']};
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }}
        .kpi-value {{
            font-size: 28px;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }}
        .kpi-value.positive {{ color: {COLORS['positive']}; }}
        .kpi-value.negative {{ color: {COLORS['negative']}; }}
        .kpi-label {{
            font-size: 12px;
            color: {COLORS['text_secondary']};
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-top: 8px;
        }}

        .section-title {{
            font-size: 20px;
            font-weight: 600;
            margin: 32px 0 16px 0;
            padding-bottom: 12px;
            border-bottom: 2px solid {COLORS['border']};
            color: {COLORS['text_primary']};
        }}
        .section-title.sensitivity {{
            background: linear-gradient(90deg, #ff9100, #ff5252);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        .card {{
            background: {COLORS['bg_card']};
            border: 1px solid {COLORS['border']};
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
        }}
        .card h2 {{
            color: {COLORS['text_primary']};
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 20px;
            padding-bottom: 12px;
            border-bottom: 1px solid {COLORS['border']};
        }}

        .metrics-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }}
        .metrics-table th {{
            padding: 14px 12px;
            text-align: right;
            background: {COLORS['bg_elevated']};
            color: {COLORS['accent']};
            font-weight: 600;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid {COLORS['border']};
        }}
        .metrics-table th:first-child {{ text-align: left; }}
        .metrics-table td {{
            padding: 12px;
            text-align: right;
            border-bottom: 1px solid {COLORS['border']};
            font-family: 'JetBrains Mono', monospace;
            font-size: 13px;
        }}
        .metrics-table td.metric-label {{
            text-align: left;
            font-family: 'Inter', sans-serif;
            font-weight: 500;
            color: {COLORS['text_secondary']};
        }}
        .metrics-table tr:hover {{ background: rgba(255, 255, 255, 0.03); }}
        .metrics-table td.positive {{ color: {COLORS['positive']}; }}
        .metrics-table td.negative {{ color: {COLORS['negative']}; }}

        .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 24px; }}
        @media (max-width: 1200px) {{ .grid {{ grid-template-columns: 1fr; }} }}
        @media (max-width: 800px) {{ .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }} }}

        .strategy-legend {{
            display: flex;
            gap: 16px;
            margin-bottom: 16px;
            flex-wrap: wrap;
        }}
        .strategy-legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            color: {COLORS['text_secondary']};
        }}
        .strategy-dot {{
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }}

        .recommendations {{
            background: rgba(0, 212, 170, 0.1);
            border-left: 4px solid {COLORS['accent']};
            padding: 16px 24px;
            border-radius: 0 8px 8px 0;
        }}
        .recommendations ul {{ padding-left: 20px; }}
        .recommendations li {{ margin: 8px 0; color: {COLORS['text_secondary']}; }}
        .recommendations strong {{ color: {COLORS['text_primary']}; }}

        .footer {{
            text-align: center;
            padding: 32px 20px;
            color: {COLORS['text_secondary']};
            font-size: 12px;
            border-top: 1px solid {COLORS['border']};
            margin-top: 24px;
        }}
        .no-data {{
            color: {COLORS['text_secondary']};
            font-style: italic;
            text-align: center;
            padding: 40px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>RBI Strategy Mega Dashboard</h1>
            <p>Complete analysis: Financial Performance + Filter Sensitivity</p>
            <div class="run-info">
                <div class="info-item">Run: {run_id}</div>
                <div class="info-item">Period: {start_date} to {end_date}</div>
                <div class="info-item">Symbols: {len(symbols)}</div>
                <div class="info-item">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
            </div>
        </div>

        <!-- KPI Cards -->
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-value">{total_trades}</div>
                <div class="kpi-label">Total Trades</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value {'positive' if total_pnl > 0 else 'negative'}">${total_pnl:,.0f}</div>
                <div class="kpi-label">Best Strategy P&L ({best_name})</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">{win_rate:.1f}%</div>
                <div class="kpi-label">Win Rate</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-value">{sharpe:.2f}</div>
                <div class="kpi-label">Sharpe Ratio</div>
            </div>
        </div>

        <!-- FINANCIAL PERFORMANCE SECTION -->
        <h2 class="section-title">Financial Performance</h2>

        <div class="card">
            <h2>Strategy Performance Comparison</h2>
            <div class="strategy-legend">
                <div class="strategy-legend-item"><div class="strategy-dot" style="background: {STRATEGY_COLORS['A']}"></div><span>A (1.5R Fixed)</span></div>
                <div class="strategy-legend-item"><div class="strategy-dot" style="background: {STRATEGY_COLORS['B1']}"></div><span>B1 (1% Div)</span></div>
                <div class="strategy-legend-item"><div class="strategy-dot" style="background: {STRATEGY_COLORS['B2']}"></div><span>B2 (2% Div)</span></div>
                <div class="strategy-legend-item"><div class="strategy-dot" style="background: {STRATEGY_COLORS['B3']}"></div><span>B3 (MA Cross)</span></div>
                <div class="strategy-legend-item"><div class="strategy-dot" style="background: {STRATEGY_COLORS['B4']}"></div><span>B4 (Tight Stop)</span></div>
                <div class="strategy-legend-item"><div class="strategy-dot" style="background: {STRATEGY_COLORS['B5']}"></div><span>B5 (Loose Stop)</span></div>
            </div>
            {metrics_table}
        </div>

        <div class="card">
            <h2>Equity Curves - All Strategies</h2>
            {chart_html.get('equity_all', '')}
        </div>

        <div class="card">
            <h2>Strategy Metrics Comparison</h2>
            {chart_html.get('comparison', '')}
        </div>

        <div class="grid">
            <div class="card">
                <h2>Drawdown Analysis</h2>
                {chart_html.get('drawdown', '')}
            </div>
            <div class="card">
                <h2>Trade Distribution by Symbol</h2>
                {chart_html.get('distribution', '')}
            </div>
        </div>

        <!-- SENSITIVITY ANALYSIS SECTION -->
        <h2 class="section-title sensitivity">Filter Sensitivity Analysis</h2>

        <div class="card">
            <h2>Filter Impact Summary</h2>
            {filter_table_html if filter_table_html else '<p class="no-data">No filter impact data available</p>'}
        </div>

        <div class="grid">
            <div class="card">
                <h2>Missed Alpha by Filter</h2>
                {chart_html.get('filter_impact', '<p class="no-data">No filter data</p>')}
            </div>
            <div class="card">
                <h2>Rejection Distribution</h2>
                {chart_html.get('rejection_pie', '<p class="no-data">No rejection data</p>')}
            </div>
        </div>

        {f'<div class="card"><h2>Threshold Sensitivity</h2>{threshold_table_html}</div>' if threshold_table_html else ''}

        {f'<div class="card"><h2>Ablation Test Results</h2>{ablation_table_html}</div>' if ablation_table_html else ''}

        <div class="card">
            <h2>Recommendations</h2>
            <div class="recommendations">
                {recommendations_html if recommendations_html else '<p>Run sensitivity analysis to generate recommendations.</p>'}
            </div>
        </div>

        <div class="footer">
            <p>RBI 2025 Mega Dashboard &mdash; Bias-Free Implementation</p>
            <p style="margin-top: 8px;">Oliver Velez Strategy | 20/200 SMA | Near-MA Rule Enforced</p>
        </div>
    </div>
</body>
</html>'''

    report_path = os.path.join(output_dir, f'mega_dashboard_{run_id}.html')
    with open(report_path, 'w') as f:
        f.write(html)

    print(f"Mega dashboard generated: {report_path}")
    return report_path


def create_metrics_table_html_full(all_results: Dict[str, Tuple[pd.DataFrame, Dict]]) -> str:
    """Create HTML table of metrics for all 6 strategies."""
    strategies = ['A', 'B1', 'B2', 'B3', 'B4', 'B5']
    headers = ['Metric'] + [f'Strategy {s}' for s in strategies]

    metrics_rows = [
        ('Trades', 'trades', '{:.0f}', False),
        ('Win Rate', 'win_rate', '{:.1f}%', False),
        ('Profit Factor', 'profit_factor', '{:.2f}', False),
        ('Net P&L', 'total_pnl', '${:,.2f}', True),
        ('Return', 'return_pct', '{:.2f}%', True),
        ('Max Drawdown', 'max_drawdown', '{:.2%}', True),
        ('Sharpe Ratio', 'sharpe_ratio', '{:.2f}', False),
        ('Sortino Ratio', 'sortino_ratio', '{:.2f}', False),
        ('Avg Win', 'avg_win', '${:,.2f}', False),
        ('Avg Loss', 'avg_loss', '${:,.2f}', False),
        ('Commissions', 'total_commissions', '${:,.2f}', False),
    ]

    html = '<table class="metrics-table">\n<thead><tr>'
    for h in headers:
        html += f'<th>{h}</th>'
    html += '</tr></thead>\n<tbody>\n'

    for label, key, fmt, highlight_pnl in metrics_rows:
        html += f'<tr><td class="metric-label">{label}</td>'
        for strategy in strategies:
            if strategy in all_results:
                _, metrics = all_results[strategy]
                value = metrics.get(key, 0)
                try:
                    formatted = fmt.format(value) if value is not None else 'N/A'
                except:
                    formatted = str(value) if value is not None else 'N/A'

                value_class = ''
                if highlight_pnl and value is not None:
                    if isinstance(value, (int, float)):
                        value_class = ' class="positive"' if value > 0 else ' class="negative"' if value < 0 else ''
            else:
                formatted = 'N/A'
                value_class = ''
            html += f'<td{value_class}>{formatted}</td>'
        html += '</tr>\n'

    html += '</tbody></table>'
    return html


def create_threshold_comparison_table(threshold_results: Dict) -> str:
    """Create comparison table for different Near 20 MA thresholds."""
    if not threshold_results:
        return '<p class="no-data">No threshold comparison data</p>'

    html = '''<table class="metrics-table">
    <thead><tr>
        <th style="text-align:left">Threshold</th>
        <th>Trades</th>
        <th>B3 P&L</th>
        <th>B4 P&L</th>
        <th>B5 P&L</th>
        <th>Win Rate</th>
    </tr></thead>
    <tbody>'''

    for threshold_label, data in threshold_results.items():
        if 'results' in data:
            results = data['results']
            # Get B3 metrics as primary
            b3_trades, b3_metrics = results.get('B3', (None, {}))
            b4_trades, b4_metrics = results.get('B4', (None, {}))
            b5_trades, b5_metrics = results.get('B5', (None, {}))

            trades = b3_metrics.get('trades', 0)
            b3_pnl = b3_metrics.get('total_pnl', 0)
            b4_pnl = b4_metrics.get('total_pnl', 0)
            b5_pnl = b5_metrics.get('total_pnl', 0)
            win_rate = b3_metrics.get('win_rate', 0)

            b3_class = 'positive' if b3_pnl > 0 else 'negative'
            b4_class = 'positive' if b4_pnl > 0 else 'negative'
            b5_class = 'positive' if b5_pnl > 0 else 'negative'

            html += f'''<tr>
                <td class="metric-label">{threshold_label}</td>
                <td>{trades}</td>
                <td class="{b3_class}">${b3_pnl:,.0f}</td>
                <td class="{b4_class}">${b4_pnl:,.0f}</td>
                <td class="{b5_class}">${b5_pnl:,.0f}</td>
                <td>{win_rate:.1f}%</td>
            </tr>'''

    html += '</tbody></table>'
    return html


def create_ablation_comparison_table(ablation_results: Dict) -> str:
    """Create comparison table for ablation tests."""
    if not ablation_results:
        return '<p class="no-data">No ablation test data</p>'

    html = '''<table class="metrics-table">
    <thead><tr>
        <th style="text-align:left">Filter Disabled</th>
        <th>Trades</th>
        <th>B3 P&L</th>
        <th>B4 P&L</th>
        <th>B5 P&L</th>
        <th>Change vs Baseline</th>
    </tr></thead>
    <tbody>'''

    # Get baseline for comparison
    baseline_pnl = 0
    if 'baseline' in ablation_results:
        b_results = ablation_results['baseline'].get('results', {})
        if 'B3' in b_results:
            baseline_pnl = b_results['B3'][1].get('total_pnl', 0)

    for ablation_name, data in ablation_results.items():
        if 'results' in data:
            results = data['results']
            b3_trades, b3_metrics = results.get('B3', (None, {}))
            b4_trades, b4_metrics = results.get('B4', (None, {}))
            b5_trades, b5_metrics = results.get('B5', (None, {}))

            trades = b3_metrics.get('trades', 0)
            b3_pnl = b3_metrics.get('total_pnl', 0)
            b4_pnl = b4_metrics.get('total_pnl', 0)
            b5_pnl = b5_metrics.get('total_pnl', 0)

            b3_class = 'positive' if b3_pnl > 0 else 'negative'
            b4_class = 'positive' if b4_pnl > 0 else 'negative'
            b5_class = 'positive' if b5_pnl > 0 else 'negative'

            change = b3_pnl - baseline_pnl if ablation_name != 'baseline' else 0
            change_class = 'positive' if change > 0 else 'negative' if change < 0 else ''
            change_str = f'+${change:,.0f}' if change > 0 else f'-${abs(change):,.0f}' if change < 0 else '-'

            display_name = ablation_name.replace('_', ' ').title()

            html += f'''<tr>
                <td class="metric-label">{display_name}</td>
                <td>{trades}</td>
                <td class="{b3_class}">${b3_pnl:,.0f}</td>
                <td class="{b4_class}">${b4_pnl:,.0f}</td>
                <td class="{b5_class}">${b5_pnl:,.0f}</td>
                <td class="{change_class}">{change_str}</td>
            </tr>'''

    html += '</tbody></table>'
    return html


def generate_sensitivity_report(filter_impact: Dict,
                                 rejection_stats: Dict,
                                 whatif_results: Dict,
                                 run_id: str,
                                 output_dir: str = 'reports') -> str:
    """
    Generate standalone filter sensitivity HTML report.
    Returns path to the generated report.
    """
    if not PLOTLY_AVAILABLE:
        print("Error: plotly not installed. Cannot generate HTML report.")
        return None

    os.makedirs(output_dir, exist_ok=True)

    # Generate charts
    impact_chart = create_filter_impact_chart(filter_impact)
    rejection_chart = create_rejection_pie_chart(rejection_stats)

    impact_chart_html = impact_chart.to_html(full_html=False, include_plotlyjs='cdn') if impact_chart else ''
    rejection_chart_html = rejection_chart.to_html(full_html=False, include_plotlyjs='cdn') if rejection_chart else ''

    # Generate tables
    impact_table = create_filter_impact_table_html(filter_impact)

    # Build recommendations
    recommendations = []
    for filter_name, data in filter_impact.items():
        missed_pnl = data.get('missed_pnl', 0)
        if missed_pnl > 1000:  # Significant positive missed P&L
            recommendations.append(f"<li><strong>{filter_name}</strong>: Consider relaxing - missed ${missed_pnl:,.0f} in potential profit</li>")
        elif missed_pnl < -1000:  # Filter prevented losses
            recommendations.append(f"<li><strong>{filter_name}</strong>: Keep strict - prevented ${abs(missed_pnl):,.0f} in losses</li>")

    recommendations_html = '<ul>' + ''.join(recommendations) + '</ul>' if recommendations else '<p>No strong recommendations - filters appear balanced.</p>'

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Filter Sensitivity Report - {run_id}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Inter', sans-serif;
            background: {COLORS['bg_page']};
            color: {COLORS['text_primary']};
            padding: 24px;
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .header {{
            background: {COLORS['bg_card']};
            border: 1px solid {COLORS['border']};
            padding: 32px;
            border-radius: 12px;
            margin-bottom: 24px;
        }}
        .header h1 {{
            font-size: 28px;
            background: linear-gradient(90deg, {COLORS['accent']}, #ff9100);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .card {{
            background: {COLORS['bg_card']};
            border: 1px solid {COLORS['border']};
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
        }}
        .card h2 {{
            color: {COLORS['text_primary']};
            font-size: 16px;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid {COLORS['border']};
        }}
        .metrics-table {{
            width: 100%;
            border-collapse: collapse;
        }}
        .metrics-table th {{
            padding: 12px;
            text-align: right;
            background: {COLORS['bg_elevated']};
            color: {COLORS['accent']};
            font-size: 12px;
        }}
        .metrics-table th:first-child {{ text-align: left; }}
        .metrics-table td {{
            padding: 12px;
            text-align: right;
            border-bottom: 1px solid {COLORS['border']};
            font-family: 'JetBrains Mono', monospace;
        }}
        .metrics-table td.metric-label {{ text-align: left; font-family: 'Inter', sans-serif; }}
        .metrics-table .positive {{ color: {COLORS['positive']}; }}
        .metrics-table .negative {{ color: {COLORS['negative']}; }}
        .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 24px; }}
        .recommendations {{
            background: rgba(0, 212, 170, 0.1);
            border-left: 4px solid {COLORS['accent']};
            padding: 16px 24px;
            border-radius: 0 8px 8px 0;
        }}
        .recommendations ul {{ padding-left: 20px; }}
        .recommendations li {{ margin: 8px 0; color: {COLORS['text_secondary']}; }}
        .recommendations strong {{ color: {COLORS['text_primary']}; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Filter Sensitivity Analysis</h1>
            <p style="color:{COLORS['text_secondary']}; margin-top: 8px;">
                Run: {run_id} | Analysis of filter impact on strategy performance
            </p>
        </div>

        <div class="card">
            <h2>Filter Impact Summary</h2>
            {impact_table}
        </div>

        <div class="grid">
            <div class="card">
                <h2>Missed Alpha by Filter</h2>
                {impact_chart_html}
            </div>
            <div class="card">
                <h2>Rejection Distribution</h2>
                {rejection_chart_html}
            </div>
        </div>

        <div class="card">
            <h2>Recommendations</h2>
            <div class="recommendations">
                {recommendations_html}
            </div>
        </div>
    </div>
</body>
</html>'''

    report_path = os.path.join(output_dir, f'sensitivity_{run_id}.html')
    with open(report_path, 'w') as f:
        f.write(html)

    print(f"Sensitivity report generated: {report_path}")
    return report_path


if __name__ == '__main__':
    print("Reports module loaded successfully")
    print(f"Plotly available: {PLOTLY_AVAILABLE}")
