# Shotgun v1 Implementation Plan

## Delivery shape

Build one auditable strategy in two runtimes:

- `pine/shotgun_strategy.pine`: TradingView Pine v6 strategy that also acts as the visual indicator and alert source.
- `shotgun/`: dependency-free Python reference implementation for data ingestion, signals, execution, metrics, and chronological validation.

Python is the authoritative reproducibility and conservative-fill harness. Pine provides chart visualization and TradingView Strategy Tester parity where its emulator permits it.

## Files

```text
README.md
pyproject.toml
shotgun/
  __init__.py
  models.py
  indicators.py
  strategy.py
  engine.py
  metrics.py
  data.py
  report.py
scripts/
  fetch_data.py
  backtest.py
  evaluate.py
  recent_signals.py
  parity_check.py
pine/
  shotgun_strategy.pine
tests/
  fixtures/
    parity_bars.csv
    parity_signals.json
  test_indicators.py
  test_strategy.py
  test_engine.py
  test_data.py
  test_metrics.py
reports/
data/market/
```

## Execution sequence

1. Define immutable dataclasses for bars, configuration, prepared indicator rows, signals, positions, trades, and results. Normalize config JSON and fingerprint it with SHA-256.
2. Implement Pine-compatible SMA, EMA, Wilder RMA, ATR, RSI, and DMI/ADX arrays. Make warm-up/undefined values explicit.
3. Implement the frozen mirrored long/short setup evaluator. It returns signals only and never accesses future bars.
4. Implement the event-driven backtest loop using the exact event and accounting contract in the specification:
   - existing bracket gaps precede queued close-derived exits at the next open;
   - queued entries fill at the next open;
   - stop/target gaps and conservative same-bar collision rules apply;
   - fixed brackets, trend invalidation, timeout, cooldown, costs, and sizing are recorded;
   - one position maximum and no reversal/pyramiding.
5. Implement metrics: return, drawdown, profit factor, R expectancy, payoff, win rate with Wilson interval, trade counts, long/short split, streak, holding time, exposure, cost total, ambiguity count, top-five concentration, and fixed-seed bootstrap mean-R interval.
6. Implement Binance public kline pagination with `urllib`, retry/backoff, immutable CSV cache, metadata, complete-bar filtering, timestamp normalization, and duplicate/order/gap validation.
7. Implement JSON/CSV/Markdown reporting and four CLIs: fetch, single backtest, chronological evaluation, and recent signals.
8. Implement Pine v6 with the same formulas, confirmed-bar gating, signal-time sizing, next-bar entry semantics, combined 0.12% per-fill cost proxy, fixed tick-distance bracket, risk sizing, plots, strategy-compatible `alert()` calls/order-fill messages, and status table.
9. Document installation, data fetching, testing, TradingView use, execution differences, risk limits, and interpretation of evidence.
10. Add a golden OHLCV fixture and expected Python signal timestamps. `parity_check.py` compares those timestamps with a TradingView-exported CSV. Document the repeatable Pine export procedure; absence of a local Pine runtime is a named verification gap, not silently replaced by static checks.

## Validation design

- Primary split: chronological 60% train, 20% validation, 20% untouched final test. Fixed v1 is reported on all three; no final-test retuning.
- Walk-forward: expanding history with a minimum 180-day train and 60-day OOS windows when data length permits.
- Robustness: base and doubled costs; conservative and TradingView-path collision policies; long/short splits; recent 7/30-day windows.
- Optional predeclared sensitivity grid is descriptive only for v1: breakout lookback 3/5, ADX floor 18/22, target 1.6/1.8/2.0. The frozen default remains the headline and is never replaced after final-test inspection.
- Minimum history target: 18 months. If unavailable, produce the report with a prominent evidence-shortfall warning.

## Test matrix

- Indicators: exact SMA/EMA/RMA values, flat/rising RSI, ATR true range, DMI direction and warm-up.
- Signals: handcrafted qualifying long, qualifying short, each individual filter rejection, mirror symmetry, confirmed data only.
- Engine: next-open entry, risk/exposure sizing, fee/slippage, stop, target, stop-first collision, gap-through stop, queued trend exit, timeout, cooldown, end-of-data open position.
- Anti-lookahead: prefix signals and closed trades are invariant after future bars are appended.
- Data: valid parse, microsecond-to-millisecond normalization, incomplete candle removal, duplicates/out-of-order rejection, and strict 15-minute gap rejection for formal evaluation.
- Metrics/reporting: known trade set, drawdown, profit factor, Wilson/bootstrap determinism, JSON/CSV schema.
- Parity: golden Python timestamps plus an executable comparator for TradingView's exported Pine timestamps; static checks additionally reject lookahead/security calls and unfrozen constants.
- Smoke: `unittest discover`, `compileall`, CLI help, and cached-data end-to-end run.

## Risk controls and stop conditions

- No live-order path or credentials.
- Do not weaken filters to manufacture recent signals.
- Do not describe backtests as guaranteed or proven.
- If base or OOS evidence fails the research promotion gate, keep the artifact labeled a research prototype.
- If Pine and Python signal timestamps disagree on the same OHLCV fixture, completion is blocked until parity is restored or the difference is explicitly isolated and tested. If TradingView/Pine execution is unavailable locally, the comparator and golden fixture must still be delivered and the unexecuted manual export must be disclosed.

## Completion evidence

- Fresh test, compilation, and CLI smoke outputs.
- Cached raw market data plus metadata and SHA-256.
- Reproducible report with exact period boundaries and current completed-bar cutoff.
- Recent signal/trade list with unresolved trades labeled.
- Architecture, security, and code-quality reviewers approve or all findings are resolved.
