# Shotgun v2 Pine and parity guide

1. Open a liquid BTCUSDT standard-candle chart in TradingView.
2. Select the **5-minute** interval. The strategy fails closed on every other timeframe.
3. Paste `pine/shotgun_strategy.pine` into Pine Editor and compile it as Pine v6.
4. Keep the displayed commission at 0.12% per fill and do not reinterpret the rejected research result as a live recommendation.

Signals use only completed candles. A marker is an execution-eligible setup; TradingView processes its market entry on the following bar. The `Shotgun Parity Signal` plot exposes every raw confirmed setup (`1` long, `-1` short) before position and cooldown gating so it can be compared with Python.

The chart plots EMA21/EMA55/EMA200 context, confirmed rolling eight-bar support and resistance, active entry/stop/target, and the `AT RISK` or `PROFIT-LOCKED / GAP RISK` state. The table permanently labels this configuration `REJECTED / PAPER ONLY`.

Protection moves only after a completed close reaches +0.80 raw R. The exact replacement price covers modeled fees and targets +0.10 planned-risk R if filled exactly. Gaps, liquidity, outages, tick rounding, and emulator differences can still create a loss.

## Python/Pine parity

The committed fixture contains 4,000 verified five-minute bars and frozen raw setups for the formula contract. Regenerate it when intentionally changing formulas:

```bash
python3 scripts/build_parity_fixture.py data/market/BTCUSDT_5m_20250120_20260721.csv --interval 5m
python3 scripts/parity_check.py tests/fixtures/parity_bars.csv tests/fixtures/parity_signals.json
```

For execution parity, export TradingView data from a 5-minute chart using the same formulas and compare signal timestamps/directions with the Python reference. TradingView cannot enforce Python's next-open excessive-gap rejection or universal conservative stop-first same-bar collision rule.
