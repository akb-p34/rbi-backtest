# Redactions

This repository is a public copy of parts of a private research repository. This file lists every change made for
the public release and every file that was left out.

## What was changed, in short

- **A firm's name** in two lines of `backtest/reports.py` described the report's design as "Citadel-quality" and
  "Citadel-inspired". This project has no connection to that firm, so the name is removed. The line count is
  unchanged, so line numbers match the original.
- Nothing else was edited. Every other file is a byte-for-byte copy.
- **Git history starts fresh.** The private repository's history (about 200 commits, including a personal email
  address in the author fields) is not carried over. This repository has one commit.

| File | Line | What was removed | Now reads |
|---|---|---|---|
| `backtest/reports.py` | 3 | a firm's name | `Dark mode dashboard.` |
| `backtest/reports.py` | 25 | a firm's name | `# Dark theme - professional hierarchy` |

## The evidence files are unchanged

The four files in `evidence/` are identical to the versions committed in the private repository on 2025-06-20
(commit `7e7bfc9`, message "We will use backtestNew instead, backtestIBKR is still lookahaead"). They were checked
byte for byte against that commit before this release:

- `evidence/before-backtestIBKR/backtest.py` and `metrics_06-20-2025.txt` (from `archive/backtestIBKR/` at that commit)
- `evidence/after-backtestNew/backtest.py` and `metrics_06-20-2025.txt` (from `archive/backtestNew/` at that commit)

Only the folder names changed: `before-` and `after-` were added in front.

A comment on line 288 of `evidence/after-backtestNew/backtest.py` reads "Forward bias existed when it was if
df['Open'].iloc[i] > trigger_price". That comment is garbled in the original: the diff in commit `7e7bfc9` shows the
old condition was `df['High'].iloc[i] > trigger_price`. It is left as it was.

## Files left out

| Left out | Why |
|---|---|
| `backtest/data/` (`rbi_backtest.db`, about 800 MB, and the per-agent databases) | 2-minute price bars downloaded from IBKR. IBKR market data isn't ours to redistribute. |
| `backtest/data/results/trades_*.csv`, `run_*.json`, the earlier `summary_*` runs | Trade-by-trade logs with entry and exit prices from IBKR data, and test runs. The three full-year summaries in `results/` are kept. |
| `backtest/data/results/analysis_sensitivity_*.json`, `symbols.json`, `high_beta_symbols*.json` | The wider-universe filter study. Its "near 20 MA" ablation gives exactly the baseline result, which suggests that switch didn't take effect, so it isn't published until it is checked. |
| `backtest/reports/` (HTML reports) | Generated output. The code that builds them is included. |
| `archive/` (12 older implementations, their stock data and trade logs) | Superseded code and downloaded data. The two versions that matter for the lookahead story are in `evidence/`. |
| `RBI Notes/RBI_Strategy_Transcript_Oliver_Velez.md` | A transcript of someone else's video. The README links to the video instead. |
| `RBI Notes/RBI_ANALYSIS_REPORT.md` | A planning document from January 2026. It is out of date, and it wrongly describes the biased version's 100% win rate as "higher-quality" signals. |
| `SPEC.md`, `ACCEPTANCE.md`, the old `README.md` | Planning documents for the filter study. The new README replaces them. |
| Tooling folders and dotfiles | Task tracker, tool settings and CI workflows for the private repository. |

## Terms that still appear, and why

A sweep of the whole tree searched for `passw`, `secret`, `token`, `key`, `account`, `username`, `login`, `@gmail`,
`@stevens`, the author's name, home-folder paths and IBKR account-number patterns. The remaining hits are:

- `127.0.0.1`, port `7497` and `clientId` values (101 to 132, and 199): the default address of a local IBKR Trader
  Workstation on the same computer, and connection slot numbers. They are not account numbers and give no access.
- `https://fonts.googleapis.com` (`backtest/reports.py`), Wikipedia index pages (`backtest/universe.py`) and the
  strategy video (`README.md`): public URLs.
- `key` in ordinary code: dictionary keys, sort keys, `KeyError` and SQL `PRIMARY KEY`.

No account number, password, API key or email address appears anywhere in the tree.
