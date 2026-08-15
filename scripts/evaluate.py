#!/usr/bin/env python3
"""Run chronological, doubled-cost, and walk-forward Shotgun evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shotgun.data import load_cache, read_cache_metadata  # noqa: E402
from shotgun.evaluation import evaluate_history  # noqa: E402
from shotgun.models import StrategyConfig  # noqa: E402
from shotgun.report import (  # noqa: E402
    markdown_summary,
    validate_stem,
    write_json,
    write_text_atomic,
    write_trades_csv,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate frozen Shotgun v1 chronologically.")
    parser.add_argument("data", type=Path, help="cached 5-minute OHLCV CSV")
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    parser.add_argument("--stem", default="shotgun-evaluation")
    return parser


def _segment_table(report: dict[str, object]) -> str:
    lines = ["", "## Chronological segments", "", "| Segment | Trades | Win rate | Net return | Profit factor | Expectancy R | Max DD |", "|---|---:|---:|---:|---:|---:|---:|"]
    for name, metrics in report["segments"].items():
        def pct(value: object) -> str:
            return "n/a" if value is None else f"{float(value):.2%}"
        def num(value: object) -> str:
            return "n/a" if value is None else f"{float(value):.3f}"
        lines.append(
            f"| {name} | {metrics['trades']} | {pct(metrics['win_rate'])} | {pct(metrics['net_return'])} | {num(metrics['profit_factor'])} | {num(metrics['expectancy_r'])} | {pct(metrics['max_drawdown_fraction'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.stem = validate_stem(args.stem)
    bars = load_cache(
        args.data,
        drop_incomplete=True,
        require_metadata=True,
        expected_symbol="BTCUSDT",
        expected_interval="5m",
    )
    provenance = read_cache_metadata(args.data)
    config = StrategyConfig()
    results, report = evaluate_history(bars, config)
    report["data_provenance"] = provenance
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = write_json(args.output_dir / f"{args.stem}.json", report)
    trades_path = write_trades_csv(
        args.output_dir / f"{args.stem}-test-trades.csv", results["test"].trades
    )
    markdown = markdown_summary(
        "Shotgun v2 Chronological Evaluation",
        report["segments"]["test"],
        bars=bars,
        config=config,
        promotion=report["research_promotion_gate"],
        provenance=provenance,
    )
    markdown += _segment_table(report)
    markdown += (
        f"\nWalk-forward positive fold fraction: "
        f"{report['walk_forward_positive_fraction'] if report['walk_forward_positive_fraction'] is not None else 'n/a'}\n"
    )
    markdown_path = args.output_dir / f"{args.stem}.md"
    write_text_atomic(markdown_path, markdown)
    print(
        json.dumps(
            {"json": str(json_path), "markdown": str(markdown_path), "test_trades": str(trades_path)},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
