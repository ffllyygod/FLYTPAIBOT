#!/usr/bin/env python3
"""Fetch completed BTCUSDT intraday Binance bars into an immutable cache."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shotgun.data import (  # noqa: E402
    completed_bar_cutoff_ms,
    fetch_binance_klines,
    fetch_binance_klines_parallel,
    interval_milliseconds,
    parse_time_argument,
    write_cache,
)


def _default_start_ms() -> int:
    return int((datetime.now(timezone.utc) - timedelta(days=548)).timestamp() * 1000)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch completed Binance BTCUSDT intraday bars into an immutable CSV cache."
    )
    parser.add_argument(
        "--start",
        help="inclusive ISO-8601, epoch-ms, or epoch-us start (default: 548 days ago)",
    )
    parser.add_argument(
        "--end", help="exclusive ISO-8601, epoch-ms, or epoch-us end (default: now)"
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="5m", choices=("1m", "5m"))
    parser.add_argument("--output", type=Path, help="destination CSV path")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument("--workers", type=int, default=4)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    start_ms = parse_time_argument(args.start) if args.start else _default_start_ms()
    requested_end_ms = parse_time_argument(args.end) if args.end else None
    snapshot_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    interval_ms = interval_milliseconds(args.interval)
    effective_end_ms = min(
        requested_end_ms if requested_end_ms is not None else completed_bar_cutoff_ms(snapshot_ms, interval_ms=interval_ms),
        completed_bar_cutoff_ms(snapshot_ms, interval_ms=interval_ms),
    )
    if effective_end_ms <= start_ms:
        raise SystemExit("end must be later than start after completed-candle filtering")

    output = args.output
    if output is None:
        start_label = datetime.fromtimestamp(start_ms / 1000, timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        end_label = datetime.fromtimestamp(effective_end_ms / 1000, timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = Path("data/market") / f"{args.symbol.upper()}_{args.interval}_{start_label}_{end_label}.csv"

    fetcher = fetch_binance_klines_parallel if args.workers > 1 else fetch_binance_klines
    fetch_options = {
        "symbol": args.symbol,
        "interval": args.interval,
        "now_ms": snapshot_ms,
        "timeout": args.timeout,
        "max_retries": args.max_retries,
    }
    if args.workers > 1:
        fetch_options["workers"] = args.workers
    bars = fetcher(start_ms, requested_end_ms, **fetch_options)
    if not bars:
        raise SystemExit("Binance returned no completed bars for the requested period")
    metadata = write_cache(
        output,
        bars,
        symbol=args.symbol,
        interval=args.interval,
        requested_start_ms=start_ms,
        requested_end_ms=requested_end_ms,
    )
    print(json.dumps({"csv": str(output), "metadata": metadata}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
