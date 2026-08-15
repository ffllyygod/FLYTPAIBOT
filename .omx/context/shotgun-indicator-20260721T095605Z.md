# Shotgun Indicator Context

## Task statement

Build a smart long/short trading indicator that identifies selective entries aimed at medium-sized moves, then backtest it and inspect recent signals today.

## Desired outcome

- A TradingView-compatible Pine Script strategy/indicator with non-repainting confirmed-bar signals.
- A reproducible local Python backtester using no third-party dependencies.
- Risk-defined entries with stop, profit target, and position sizing guidance.
- Evidence from historical, walk-forward/out-of-sample, and recent-bar tests.

## Known facts and evidence

- The workspace has no existing application or trading strategy code.
- Binance provides public OHLCV klines through `GET /api/v3/klines` with up to 1,000 bars per request.
- TradingView strategies can simulate historical and realtime trades, but broker-emulator assumptions, fees, slippage, and lookahead bias must be handled explicitly.
- No legitimate trade is risk-free; claims of high return with no risk are a recognized warning sign.

## Constraints

- Do not promise guaranteed returns or a fixed win rate.
- Include realistic commission and slippage in tests.
- Avoid lookahead/repainting and tune only on a training segment.
- No new runtime dependencies; prefer Python standard library.
- Default market assumption: liquid BTC/USDT spot data, 15-minute signals, long and synthetic short backtesting. Short execution requires a futures/margin-capable venue.
- Paper/forward-test before risking capital.

## Unknowns and assumptions

- The user did not specify asset, venue, platform, timeframe, account size, or jurisdiction.
- Use BTCUSDT and 15-minute bars as a portable liquid baseline.
- Treat “today” as inspecting the most recent completed bars available from the public data endpoint, not placing live orders.

## Likely codebase touchpoints

- `pine/shotgun_strategy.pine`
- `shotgun/` Python package for indicators, signals, data loading, and backtesting
- `scripts/` CLI entry points
- `tests/` regression and anti-lookahead tests
- `reports/` generated evaluation artifacts
- `README.md`
