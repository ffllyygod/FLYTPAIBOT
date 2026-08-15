#!/usr/bin/env python3
"""Inspect recent completed-bar Shotgun signals and paper-trade status."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shotgun.data import load_cache, read_cache_metadata  # noqa: E402
from shotgun.engine import run_backtest  # noqa: E402
from shotgun.indicators import prepare_bars  # noqa: E402
from shotgun.models import StrategyConfig  # noqa: E402
from shotgun.report import iso_utc, write_json  # noqa: E402
from shotgun.strategy import support_resistance_at  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List recent frozen Shotgun signals.")
    parser.add_argument("data", type=Path)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("reports/shotgun-recent.json"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.days <= 0:
        raise SystemExit("--days must be positive")
    bars = load_cache(
        args.data,
        drop_incomplete=True,
        require_metadata=True,
        expected_symbol="BTCUSDT",
        expected_interval="5m",
    )
    provenance = read_cache_metadata(args.data)
    config = StrategyConfig()
    result = run_backtest(bars, config)
    prepared = prepare_bars(bars, config)
    report_end = bars[-1].close_time
    history_cutoff = report_end - max(args.days, 30) * 86_400_000
    trades_by_signal = {trade.signal_index: trade for trade in result.trades}
    records = []
    for signal in result.signals:
        if signal.time < history_cutoff:
            continue
        trade = trades_by_signal.get(signal.index)
        if trade is not None:
            status = trade.exit_reason
            outcome = {
                "entry_time_utc": iso_utc(trade.entry_time),
                "entry_price": trade.entry_price,
                "stop": trade.stop_price,
                "target": trade.target_price,
                "exit_time_utc": iso_utc(trade.exit_time),
                "net_pnl": trade.net_pnl,
                "r_multiple": trade.r_multiple,
            }
        elif result.open_position and result.open_position.signal.index == signal.index:
            position = result.open_position
            status = "open"
            outcome = {
                "entry_time_utc": iso_utc(position.entry_time),
                "entry_price": position.entry_price,
                "stop": position.stop_price,
                "target": position.target_price,
            }
        elif signal.index == len(bars) - 1:
            status = "pending_next_open"
            outcome = {}
        else:
            status = "not_filled_gap_or_segment_end"
            outcome = {}
        trigger_support, trigger_resistance = support_resistance_at(
            bars, signal.index - 1, config.breakout_lookback
        )
        structural_support, structural_resistance = support_resistance_at(
            bars, signal.index, config.structural_lookback
        )
        records.append(
            {
                "signal_time": signal.time,
                "signal_time_utc": iso_utc(signal.time),
                "side": signal.side,
                "signal_close": signal.signal_close,
                "atr": signal.atr,
                "risk_distance": signal.risk_distance,
                "levels": {
                    "trigger_support": trigger_support,
                    "trigger_resistance": trigger_resistance,
                    "structural_support": structural_support,
                    "structural_resistance": structural_resistance,
                },
                "status": status,
                **outcome,
            }
        )

    last = prepared[-1]
    if None not in (last.ema21, last.ema55, last.ema200):
        if last.ema21 > last.ema55 > last.ema200:
            regime = "long"
        elif last.ema21 < last.ema55 < last.ema200:
            regime = "short"
        else:
            regime = "neutral"
    else:
        regime = "warmup"
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    current_support, current_resistance = support_resistance_at(
        bars, len(bars) - 1, config.structural_lookback
    )
    current_trade = next(
        (
            record
            for record in reversed(records)
            if record["status"] in {"open", "pending_next_open"}
        ),
        None,
    )
    requested_cutoff = report_end - args.days * 86_400_000
    requested_records = [
        record for record in records if record["signal_time"] >= requested_cutoff
    ]
    seven_day_records = [
        record
        for record in records
        if record["signal_time"] >= report_end - 7 * 86_400_000
    ]
    thirty_day_records = [
        record
        for record in records
        if record["signal_time"] >= report_end - 30 * 86_400_000
    ]
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_cutoff_utc": iso_utc(bars[-1].close_time),
        "data_staleness_minutes": max(0.0, (now_ms - bars[-1].close_time) / 60_000),
        "days": args.days,
        "data_provenance": provenance,
        "current_regime": regime,
        "current_levels": {
            "support": current_support,
            "resistance": current_resistance,
            "lookback_bars": config.structural_lookback,
        },
        "current_trade": current_trade,
        "signals": requested_records,
        "windows": {
            "7d": {"count": len(seven_day_records), "signals": seven_day_records},
            "30d": {"count": len(thirty_day_records), "signals": thirty_day_records},
        },
        "latest": requested_records[-1] if requested_records else None,
        "warning": "Historical/paper-trade information only; no trade is risk-free.",
    }
    write_json(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
