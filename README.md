# RBI momentum backtest: the 100% win rate that wasn't

I built a Python backtest for an intraday momentum pattern on Interactive Brokers (IBKR) 2-minute data. One version showed a **100% win rate**. It was lookahead bias. With the bias removed, the same five stocks over the same month won **29%** of trades and lost money.

| Same test: TSLA, NFLX, PLTR, QCOM, V, May 1-30, 2025 | Trades | Win rate | Profit factor | Return |
|---|---|---|---|---|
| Before the fix (`evidence/before-backtestIBKR/`) | 14 | 100.0% | inf | +1.89% |
| After the fix (`evidence/after-backtestNew/`) | 17 | 29.41% | 0.086 | -0.64% |

Both rows come straight from the metrics files saved next to each version on June 20, 2025. The folders in `evidence/` keep the names from my private repository, and the four files are unchanged from that day's commit.

## What the bug was

The strategy buys when a price bar breaks $0.01 above a small red bar's high. In a live market you'd be buying partway through that bar, before you know how it ends. The old version knew how it ended. In `evidence/before-backtestIBKR/backtest.py`:

- **Line 357** takes a trade only if the entry bar *closes* above the trigger: `current['Close'] > prev['High'] + 0.01`. The close is the last price of the bar, so the backtest only kept the trades that were already working by the end of it.
- **Line 362** fills the buy at the trigger price, `prev['High'] + 0.01`. But line 210 only flags a bar when it *opens* above that trigger. So every fill was at a price below where the bar opened, which no real order could get.
- **Lines 310 and 322** fill profit exits at the bar's high, its best price, instead of at the profit target.

My fix (`evidence/after-backtestNew/backtest.py`) decides entries from the bar's open alone (line 288), fills at the open (lines 453 and 458), and exits winners at the target price, not the high (lines 393 and 405). The win rate dropped from 100% to 29%.

## Rules I set after this

- Enter on the bar's open, never its close or high.
- Detect the pattern from finished bars only.
- Process signals from all symbols together, in time order, so trades compete for cash in the order they happened.
- Treat a win rate over 90%, an infinite profit factor or a zero drawdown as a bug until proven otherwise.

## The strategy

The pattern is "Red Bar Ignored" (RBI), a momentum continuation setup taught by Oliver Velez ([video](https://www.youtube.com/watch?v=Y55s2tihNI4)). On a 2-minute chart:

1. **Control bar:** a green bar in an uptrend, with price above the 20-period moving average and the 20 above the 200.
2. **Ignored bar:** one or two small red bars, each with a body at most half the size of the control bar's.
3. **Entry:** buy $0.01 above the red bar's high, but only if the entry comes near the 20-period average (1% away or closer by default).
4. **Stop:** $0.01 below the red bar's low. The default target is 1.5 times the risk.

## The 2026 rebuild

In January 2026 I rebuilt the backtest from scratch in `backtest/`, with the rules above built in, six exit strategies and a full year of data. It stores IBKR bars in SQLite, runs every exit strategy on the same signals and writes an HTML report.

Full year 2025, the same five stocks, $100,000 starting cash (`results/`):

| Near-20-MA filter | Trades | Win rate, 1.5R target (A) | Return (A) | Win rate, MA-cross exit with tight stop (B4) | Return (B4) |
|---|---|---|---|---|---|
| 1% | 52 | 46.2% | -0.69% | 25.0% | -0.11% |
| 2% | 56 | 46.4% | -1.06% | 28.6% | -0.29% |
| 5% | 60 | 43.3% | -3.92% | 30.0% | +0.65% |

The best of 18 configurations made +0.65% for the year. That isn't an edge. This pattern, coded this way, doesn't make money on these stocks.

## Known issue

The rebuild still has a small leak. The near-20-MA check (`backtest/backtest.py`, lines 257 and 395) uses the entry bar's close, while the fill happens at that bar's open (line 490). A clean version would use the previous bar's close. I haven't re-run the numbers above with that change.

## Running it

It needs IBKR's Trader Workstation or IB Gateway running with API access turned on, and it may need a market data subscription. The code connects to `127.0.0.1:7497` (paper trading) by default; see `backtest/config.py`.

```bash
cd backtest
pip install -r requirements.txt
python backtest.py --start 2025-01-01 --end 2025-12-31
python backtest.py --start 2025-01-01 --end 2025-12-31 --threshold 5pct
```

The first run downloads the 2-minute bars into `backtest/data/rbi_backtest.db`. No market data is included in this repository, because IBKR market data isn't mine to redistribute. `universe.py` also needs `requests`, `beautifulsoup4` and `yfinance`.

## Files

| Path | What it is |
|---|---|
| `evidence/before-backtestIBKR/` | The version with the bias, and its May 2025 metrics (100% win rate) |
| `evidence/after-backtestNew/` | The fixed version, and its May 2025 metrics (29% win rate) |
| `backtest/backtest.py` | The 2026 rebuild: data, pattern detection, signals, trade simulation |
| `backtest/strategies.py` | The six exit strategies (A, B1-B5) |
| `backtest/config.py` | Every parameter in one place |
| `backtest/metrics.py`, `backtest/reports.py` | Performance metrics and the HTML report |
| `backtest/whatif.py`, `backtest/analyze_filters.py` | Re-runs rejected signals to see what each filter costs |
| `backtest/universe.py`, `backtest/parallel_fetch.py` | Builds a wider stock universe and fetches it in parallel |
| `results/` | Summary numbers for the three full-year runs above |
| `REDACTIONS.md` | What was left out of this public copy |
