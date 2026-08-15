#!/usr/bin/env python3
"""Build a deterministic 1m Python/Pine raw-signal parity fixture."""

from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shotgun.data import load_cache, read_cache_metadata  # noqa: E402
from shotgun.report import write_json, write_text_atomic  # noqa: E402
from shotgun.strategy import generate_signals  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build frozen 1m parity fixtures.")
    parser.add_argument("data", type=Path)
    parser.add_argument("--interval", choices=("1m", "5m"), default="5m")
    parser.add_argument("--bars", type=int, default=4000)
    parser.add_argument(
        "--csv-output", type=Path, default=Path("tests/fixtures/parity_bars.csv")
    )
    parser.add_argument(
        "--json-output", type=Path, default=Path("tests/fixtures/parity_signals.json")
    )
    args = parser.parse_args(argv)
    if args.bars <= 0:
        raise SystemExit("--bars must be positive")
    source = load_cache(
        args.data,
        require_metadata=True,
        expected_symbol="BTCUSDT",
        expected_interval=args.interval,
    )
    bars = source[-args.bars :]
    signals = generate_signals(bars)
    signal_by_index = {signal.index: 1 if signal.side == "long" else -1 for signal in signals}
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(
        [
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "Shotgun Parity Signal",
        ]
    )
    for index, bar in enumerate(bars):
        writer.writerow(
            [
                bar.open_time,
                format(bar.open, ".17g"),
                format(bar.high, ".17g"),
                format(bar.low, ".17g"),
                format(bar.close, ".17g"),
                format(bar.volume, ".17g"),
                bar.close_time,
                signal_by_index.get(index, ""),
            ]
        )
    write_text_atomic(args.csv_output, stream.getvalue())
    provenance = read_cache_metadata(args.data)
    write_json(
        args.json_output,
        {
            "schema": f"shotgun-parity-signals-v2-{args.interval}",
            "fixture": args.csv_output.name,
            "source_csv_sha256": provenance["csv_sha256"],
            "slice_first_open_time": bars[0].open_time,
            "slice_last_close_time": bars[-1].close_time,
            "signals": [
                {"timestamp": signal.time, "side": signal.side} for signal in signals
            ],
        },
    )
    print(f"wrote {len(bars)} bars and {len(signals)} signals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
