# Shotgun v2 — 5-minute structural research indicator

Shotgun v2 is a selective, non-repainting BTCUSDT five-minute trend/pullback indicator with confirmed support and resistance. It was tested against a predeclared development matrix and remains research-only because every 5m candidate failed its expectancy and cost gates.

No directional entry is literally risk-free. A position starts `AT RISK`. After a completed close reaches +0.80 raw price-risk units, the model moves the stop to the exact fee-adjusted price intended to lock +0.10 planned-risk R. It then displays `PROFIT-LOCKED / GAP RISK`, because a market gap or failed fill can still produce a loss.

## Frozen five-minute setup

- Confirmed 21/55/200 EMA trend stack and EMA55 slope.
- ADX/DMI strength, RSI direction, volume participation, and an ATR regime filter.
- A prior eight-bar pullback, followed by a strict three-bar resistance/support break.
- Confirmed rolling eight-bar support and resistance plotted on the chart and emitted in alerts.
- Raw risk is at least 0.40% of signal price so the 0.12% per-fill cost model does not dominate small trades; risk above 1.00% is rejected.
- Next-open entries, one position, no pyramiding, 0.25% planned equity risk.
- Target 1.80 raw risk units; maximum hold 36 bars; 12-bar cooldown.
- Conservative Python stop-first handling when a five-minute candle touches stop and target.

The cost-viability gate rejects a setup unless its modeled target remains at least +0.75 planned-risk R after round-trip fees. This improves trade definition; it did not create positive historical expectancy.

## Evidence

The verified primary study used 157,686 completed BTCUSDT 5-minute bars from 2025-01-20 through 2026-07-21. Four development hypotheses all had negative training and validation expectancy, so the final 20% was not used to tune them.

The best-sample fast cost-aware candidate subsequently produced 39 validation trades with -0.350R expectancy and 0.251 profit factor. The recorded five-minute matrix is in [the research log](reports/shotgun-v2-research-log.md). A separate six-month 1m fallback was also tested and rejected; it is retained only as archived evidence.

The latest five-minute replay has no open or pending trade. Current levels are recorded in `reports/shotgun-5m-recent.json`; levels are descriptive, not an instruction to enter.

## Run locally

Python 3.11+ is the only requirement.

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q shotgun scripts tests

python3 scripts/fetch_data.py --start 2025-01-20T00:00:00Z --interval 5m
python3 scripts/backtest.py data/market/BTCUSDT_5m_20250120_20260721.csv --stem shotgun-5m-full-history
python3 scripts/evaluate.py data/market/BTCUSDT_5m_20250120_20260721.csv --stem shotgun-5m-evaluation
python3 scripts/recent_signals.py data/market/BTCUSDT_5m_20250120_20260721.csv --output reports/shotgun-5m-recent.json
```

The fetcher uses Binance's public market-data endpoint, requires no API key, drops the forming candle, and writes an immutable CSV plus SHA-256 metadata. Formal commands reject the wrong symbol, interval, physical candle duration, gaps, metadata bounds, or hash.

The development scripts preserve the rejected evidence:

```bash
python3 scripts/research_5m.py data/market/BTCUSDT_5m_20250120_20260721.csv
python3 scripts/research_1m.py data/market/BTCUSDT_1m_20260120_20260721.csv
python3 scripts/research_1m_levels.py data/market/BTCUSDT_1m_20260120_20260721.csv
```

## TradingView

Copy `pine/shotgun_strategy.pine` into TradingView Pine Editor and use a standard BTCUSDT five-minute candle chart. The script fails closed on every other timeframe, plots support/resistance and active risk levels, and labels itself `REJECTED / PAPER ONLY`.

TradingView cannot exactly reproduce Python's excessive-gap entry skip or guaranteed conservative stop-first collision policy. Python remains the deterministic execution reference. See `docs/pine.md` for the export/parity workflow.

Do not loosen filters to manufacture a signal. A genuinely new hypothesis needs new forward data or an independently predeclared market, realistic venue-specific fees/slippage/funding, and the same hard promotion gate before any live-capital decision.
