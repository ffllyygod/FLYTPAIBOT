# Shotgun v1 Product and Technical Specification

## Product definition

Shotgun v1 is a transparent, rules-based TradingView strategy plus a dependency-free Python reference backtester. It identifies selective BTCUSDT 15-minute long and short pullback-resumption setups and attaches an entry, invalidation stop, profit target, and risk-based size to every signal.

“Shotgun” describes decisive directional entries, not simultaneous hedging. “Smart” means regime-, momentum-, volume-, and volatility-aware. It does not imply certainty, machine learning, or guaranteed profitability. Every market trade can lose money, gap through a stop, or incur greater costs than modeled.

## Baseline assumptions

- Market: Binance BTCUSDT spot OHLCV, 15-minute bars, UTC.
- Execution: signals use completed candles only; entries occur at the next candle open.
- Direction: longs are spot-executable; shorts are synthetic in the tests and require a margin/futures-capable venue in practice.
- Portfolio: 10,000 USDT reporting capital, one position at a time, no pyramiding, no leverage, position notional capped at current equity.
- Planned risk: 0.5% of current equity per trade before fees and gap risk.
- Base costs: a combined 0.12% transaction-cost charge on entry and exit (0.10% fee plus a 0.02% slippage/impact proxy). Headline OHLC fill prices are unadjusted so Pine and Python share the same percentage-cost model. Stress costs double the 0.12% charge.
- Intrabar ambiguity: if a candle can hit both stop and target, the stop fills first. Adverse gaps fill at the worse opening price. Profit gaps do not receive price improvement.

## Frozen v1 signal

All calculations at index `i` use data at or before completed bar `i`.

### Long

1. Regime: `close[i] > EMA200[i]`, `EMA21[i] > EMA55[i] > EMA200[i]`, and `EMA55[i] > EMA55[i-5]`.
2. Trend strength: `ADX14[i] >= 20` and `+DI14[i] > -DI14[i]`.
3. Controlled pullback: within bars `i-8..i-1`, at least one low touched `EMA21 + 0.20 * ATR14`, and no close broke below `EMA55 - 0.50 * ATR14`.
4. Resumption: `close[i]` breaks the highest high of bars `i-3..i-1`, the candle is bullish, its body is at least `0.30 * ATR14`, and its close-location value is at least 0.65.
5. Momentum and participation: `52 <= RSI14[i] <= 70` and `volume[i] >= 0.80 * SMA20(volume)[i]`.
6. Quality: distance above EMA21 is at most `1.50 * ATR14`, and `0.0008 <= ATR14[i] / close[i] <= 0.015`.
7. Candidate structural stop: the lowest low over bars `i-7..i` minus `0.10 * ATR14[i]`.
8. Lock risk distance as the greater of `1.20 * ATR14[i]` and signal-close distance to the structural stop; reject it above `2.50 * ATR14[i]`.

### Short

1. Regime: `close[i] < EMA200[i]`, `EMA21[i] < EMA55[i] < EMA200[i]`, and `EMA55[i] < EMA55[i-5]`.
2. Trend strength: `ADX14[i] >= 20` and `-DI14[i] > +DI14[i]`.
3. Controlled pullback: within bars `i-8..i-1`, at least one high touched `EMA21 - 0.20 * ATR14`, and no close broke above `EMA55 + 0.50 * ATR14`.
4. Resumption: `close[i]` is strictly below the lowest low of bars `i-3..i-1`, the candle is bearish, its body is at least `0.30 * ATR14`, and its close-location value is at most 0.35.
5. Momentum and participation: `30 <= RSI14[i] <= 48` and `volume[i] >= 0.80 * SMA20(volume)[i]`.
6. Quality: `0 <= EMA21[i] - close[i] <= 1.50 * ATR14[i]`, and `0.0008 <= ATR14[i] / close[i] <= 0.015`.
7. Candidate structural stop: the highest high over bars `i-7..i` plus `0.10 * ATR14[i]`.
8. Lock risk distance as the greater of `1.20 * ATR14[i]` and structural-stop distance from the signal close; reject it strictly above `2.50 * ATR14[i]`.

### Exact numerical contract

- Long quality requires `0 <= close[i] - EMA21[i] <= 1.50 * ATR14[i]`. Long breakout is strictly `>`; short breakout is strictly `<`. Stated ranges and touch tests are inclusive.
- Close-location value is `(close - low) / (high - low)`. It is 0.5 when `high == low`.
- Long touch is `low[j] <= EMA21[j] + 0.20 * ATR14[j]`; short touch is `high[j] >= EMA21[j] - 0.20 * ATR14[j]`. Every bar in the eight-bar pullback window must satisfy its slow-trend close bound.
- EMA is seeded with the first source value and then uses `alpha = 2 / (length + 1)`. SMA is undefined before `length` values.
- Wilder RMA is undefined until `length` valid source values, seeds with their SMA, then uses `(previous * (length - 1) + source) / length`.
- True range at bar zero is `high - low`; later bars use the maximum of `high-low`, `abs(high-prev_close)`, and `abs(low-prev_close)`. ATR is RMA of true range.
- RSI uses RMA of positive and negative close changes beginning with the first change. Both zero yields 50; zero average loss only yields 100; zero average gain only yields 0.
- DMI uses Wilder-smoothed true range and directional movement (`up > down and up > 0` for +DM; `down > up and down > 0` for -DM). DI is 100 times smoothed DM divided by smoothed TR. DX is `100 * abs(+DI - -DI) / (+DI + -DI)` and is zero when the denominator is zero. ADX is RMA14 of valid DX values.
- Signals require index at least 250 and every referenced indicator value to be defined.

### Order and exit rules

- The next bar's raw open is the filled entry. The locked risk distance is applied around that fill; the stop is not kept at the structural candidate.
- Skip the entry when `abs(next_open - signal_close) > 0.50 * locked_risk_distance`; this is the exact excessive-gap rule.
- Size is fixed on the signal bar in both runtimes: `min(equity / signal_close, equity * 0.005 / (risk_distance + 2 * signal_close * cost_rate))`. Quantity does not change at the next open.
- Target is 1.80 times initial price risk from the filled entry.
- Initial stop and target are fixed. The stop changes only through the cost-covered rule below; there is no trailing stop, averaging down, martingale, or reversal.
- After a completed close reaches `1.00R` in the trade's favor, replace the initial stop with a fee-covered price that also locks `0.10R` net. Let `planned_risk_per_unit = risk_distance + 2 * signal_close * cost`; the long stop is `(entry * (1 + cost) + 0.10 * planned_risk_per_unit) / (1 - cost)` and the short stop is `(entry * (1 - cost) - 0.10 * planned_risk_per_unit) / (1 + cost)`. The adjusted stop becomes active on the next bar. Before activation the status is `AT RISK`; afterward it is `PROFIT-LOCKED / GAP RISK`, never “guaranteed.”
- Exit at stop, target, trend invalidation, or time. A trend invalidation is a close beyond EMA55 after at least three held bars. The entry bar is holding bar 1; a time exit queues at the close of holding bar 48. Close-derived exits execute at the next open unless an opening stop/target gap takes precedence.
- The eight-bar cooldown starts on exit bar `e`: signal bars `e` through `e+8` are disallowed and the first eligible signal bar is `e+9`.

### Deterministic fill and accounting contract

For each bar: (1) an existing position's stop/target opening gap is checked; (2) otherwise a queued trend/time exit fills at the raw open; (3) a pending entry fills at the raw open if its gap check passes; (4) its bracket is immediately active for that entry bar; (5) intrabar stop/target is evaluated; (6) holding count and close-derived exits are evaluated; (7) a new signal may be queued only when flat and cooldown-eligible.

- Long stop gaps (`open <= stop`) and short stop gaps (`open >= stop`) fill at the open. Favorable target gaps fill at the target, not the better open.
- If both bracket prices are inside a bar, the conservative headline fills the stop. A secondary TradingView-path sensitivity may be reported but cannot replace the headline.
- Each fill is charged `fill_price * quantity * cost_rate`. Gross P&L is signed price movement times quantity. Net P&L is gross P&L minus entry and exit charges.
- A fill at the profit-locked stop has positive modeled net P&L. If the next bar opens through it, the worse open still fills and can produce a loss; such exits are separately counted as `profit_locked_gap`.
- Planned risk cash is `quantity * (risk_distance + 2 * signal_close * cost_rate)`. Net R is net P&L divided by planned risk cash.
- At end of data, an open position remains open and is marked to the last close less an estimated exit charge for equity/drawdown. It is excluded from closed-trade metrics and reported separately.

## Functional requirements

1. Pine v6 strategy plots long/short signals and active entry, stop, and target levels; provides alert conditions; uses confirmed bars; and contains no lookahead or future indexing.
2. Python uses only the standard library, fetches paginated public Binance klines, caches immutable CSV plus source metadata, validates bar order/uniqueness, and excludes a still-forming bar.
3. CLI commands fetch data, backtest cached data, run a chronological evaluation, and write JSON/CSV/Markdown reports.
4. Trade records include signal/entry/exit timestamps, side, prices, stop, target, size, planned risk, fees, gross/net P&L, R multiple, maximum favorable/adverse excursion, bars held, and exit reason.
5. Python and Pine use the same signal formulas. Any execution-emulator difference is documented.
6. There is no API-key handling or live-order placement.

## Correctness acceptance criteria

- Deterministic results from identical cached data and configuration.
- Tests cover indicator warm-up/seeding, exact long and short rules, next-open entry, excessive-gap skip, no future leakage, event precedence, entry-bar bracket activation, stop-first same-bar ambiguity, adverse gap fills, favorable target gaps, costs/R, signal-time risk sizing, cooldown boundaries, the 48-bar timeout boundary, end-of-data marking, and incomplete-candle exclusion.
- Appending future bars cannot change prior signals or closed trades.
- Source URL, download time, exact data cutoff, parameters, costs, and a configuration fingerprint are written into reports.
- `unittest`, `compileall`, and CLI smoke tests pass.

## Evaluation protocol

- Fetch at least 18 months when the endpoint permits it; otherwise label the evidence shortfall.
- Freeze v1 before evaluation. Do not optimize the untouched segment.
- Use chronological 60% train, 20% validation, and 20% final test segments. Each segment starts flat with reset equity and cooldown. Earlier bars are indicator warm-up only. Signals and entries must fall inside the segment; pending entries at the end are discarded; positions open at the boundary are marked but not force-closed or carried; a trade belongs to the segment containing its entry.
- Missing, duplicate, out-of-order, or non-15-minute-contiguous bars make a formal evaluation invalid by default. A recent exploratory scan may continue only with a prominent invalid-data warning.
- Also report anchored walk-forward folds, seven- and thirty-day recent windows, long/short splits, base and doubled-cost results, and buy-and-hold context.
- Report trades, win rate, net return, profit factor, expectancy in R, payoff ratio, maximum drawdown, maximum losing streak, exposure, average holding time, top-five profit concentration, and a deterministic bootstrap confidence interval for mean R.

## Research promotion gate

The code is complete when correctness checks pass. The strategy is promoted beyond “research prototype” only if untouched/out-of-sample evidence has:

- at least 100 combined trades and at least 30 per side; an evidence warning does not satisfy promotion;
- positive net expectancy, profit factor at least 1.15, and maximum drawdown at most 20%;
- positive expectancy in at least 60% of walk-forward test folds;
- profit factor at least 1.0 and positive net expectancy under doubled costs;
- no more than 50% of profit concentrated in the best five trades.

Failure of the gate is reported honestly and does not trigger test-set retuning.

## Meaning of “test today”

On 2026-07-21, fetch the latest completed BTCUSDT 15-minute bars, record their exact UTC cutoff and staleness, run the frozen rules, list signals from the last seven and thirty days, and show the latest setup/trade as closed, open, or unresolved. This is historical replay and forward-paper preparation, not live execution or a statistically meaningful one-day proof.

## Non-goals

- Guaranteed returns, “no-risk” claims, a guaranteed win rate, or personalized financial advice.
- Live orders, exchange credentials, leverage optimization, or jurisdiction/tax guidance.
- Machine-learning, news, order-book, on-chain, grid, DCA, or loss-recovery systems.
- Retuning after observing the final test segment.
