#!/usr/bin/env python3
"""Run one deterministic Shotgun backtest from cached completed bars."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shotgun.data import load_cache, read_cache_metadata  # noqa: E402
from shotgun.engine import run_backtest  # noqa: E402
from shotgun.models import StrategyConfig  # noqa: E402
from shotgun.report import write_backtest_bundle  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backtest frozen Shotgun v2 rules.")
    parser.add_argument("data", type=Path, help="cached 5-minute OHLCV CSV")
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--stem", default="shotgun-backtest")
    parser.add_argument(
        "--collision-policy",
        choices=("conservative", "tv_path", "optimistic"),
        default="conservative",
    )
    parser.add_argument("--cost-rate", type=float, default=0.0012)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = StrategyConfig(cost_rate=args.cost_rate)
    bars = load_cache(
        args.data,
        drop_incomplete=True,
        require_metadata=True,
        expected_symbol="BTCUSDT",
        expected_interval="5m",
    )
    provenance = read_cache_metadata(args.data)
    result = run_backtest(bars, config, collision_policy=args.collision_policy)
    paths = write_backtest_bundle(
        args.output_dir, args.stem, result, bars, config, provenance=provenance
    )
    print(json.dumps({name: str(path) for name, path in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
