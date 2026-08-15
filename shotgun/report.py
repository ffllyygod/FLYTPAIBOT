"""Stable JSON, CSV, and Markdown report writers."""

from __future__ import annotations

import csv
from dataclasses import asdict, fields
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from .metrics import summarize
from .models import BacktestResult, Bar, StrategyConfig, Trade


TRADE_CSV_FIELDS = [field.name for field in fields(Trade)] + [
    "signal_time_utc",
    "entry_time_utc",
    "exit_time_utc",
    "fees",
]


def iso_utc(timestamp_ms: int | None) -> str | None:
    if timestamp_ms is None:
        return None
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def trade_record(trade: Trade) -> dict[str, Any]:
    record = asdict(trade)
    record["signal_time_utc"] = iso_utc(trade.signal_time)
    record["entry_time_utc"] = iso_utc(trade.entry_time)
    record["exit_time_utc"] = iso_utc(trade.exit_time)
    record["fees"] = trade.fees
    return record


def result_record(result: BacktestResult) -> dict[str, Any]:
    return {
        "metrics": summarize(result),
        "trades": [trade_record(trade) for trade in result.trades],
        "signals": [asdict(signal) | {"time_utc": iso_utc(signal.time)} for signal in result.signals],
        "open_position": asdict(result.open_position) if result.open_position else None,
    }


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def write_text_atomic(path: str | Path, content: str) -> Path:
    """Write a UTF-8 text artifact through same-directory atomic replacement."""

    target = Path(path)
    _atomic_text(target, content)
    return target


def validate_stem(stem: str) -> str:
    if not stem or stem in {".", ".."} or Path(stem).name != stem:
        raise ValueError("report stem must be one plain filename component")
    return stem


def write_json(path: str | Path, payload: Mapping[str, Any]) -> Path:
    target = Path(path)
    _atomic_text(target, json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return target


def write_trades_csv(path: str | Path, trades: Sequence[Trade]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = [trade_record(trade) for trade in trades]
    fieldnames = TRADE_CSV_FIELDS
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    temporary.replace(target)
    return target


def markdown_summary(
    title: str,
    metrics: Mapping[str, Any],
    *,
    bars: Sequence[Bar] | None = None,
    config: StrategyConfig | None = None,
    promotion: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> str:
    lines = [f"# {title}", ""]
    if bars:
        lines.extend(
            [
                f"- Data: {iso_utc(bars[0].open_time)} through {iso_utc(bars[-1].close_time)}",
                f"- Completed bars: {len(bars):,}",
            ]
        )
    if config:
        lines.extend(
            [
                f"- Config fingerprint: `{config.fingerprint()}`",
                f"- Cost proxy: {config.cost_rate:.3%} per fill",
                f"- Planned risk: {config.risk_fraction:.2%} of equity per trade",
            ]
        )
    if provenance:
        lines.extend(
            [
                f"- Source: {provenance.get('source_url', 'unknown')}",
                f"- Symbol / interval: {provenance.get('symbol', 'unknown')} / {provenance.get('interval', 'unknown')}",
                f"- Downloaded: {provenance.get('downloaded_at_utc', 'unknown')}",
                f"- CSV SHA-256: `{provenance.get('csv_sha256', 'unknown')}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Results",
            "",
            f"- Trades: {metrics.get('trades', 0)}",
            f"- Win rate: {_percent(metrics.get('win_rate'))}",
            f"- Net return: {_percent(metrics.get('net_return'))}",
            f"- Profit factor: {_number(metrics.get('profit_factor'))}",
            f"- Expectancy: {_number(metrics.get('expectancy_r'))} R/trade",
            f"- Maximum drawdown: {_percent(metrics.get('max_drawdown_fraction'))}",
            f"- Long / short trades: {(metrics.get('by_side') or {}).get('long', {}).get('trades', 0)} / {(metrics.get('by_side') or {}).get('short', {}).get('trades', 0)}",
            f"- Open position at cutoff: {'yes' if metrics.get('open_position') else 'no'}",
        ]
    )
    if promotion is not None:
        lines.extend(
            [
                "",
                "## Research promotion gate",
                "",
                f"Overall: **{'PASS' if promotion.get('passed') else 'FAIL — research prototype only'}**",
                "",
            ]
        )
        for name, passed in (promotion.get("checks") or {}).items():
            lines.append(f"- {'PASS' if passed else 'FAIL'}: {name.replace('_', ' ')}")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "These are simulated historical results, not a guarantee or a no-risk trade. Shorts are synthetic and require a margin/futures-capable venue in practice. Paper-forward testing is required before any live-capital decision.",
            "",
        ]
    )
    return "\n".join(lines)


def _percent(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.2%}"


def _number(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.3f}"


def write_backtest_bundle(
    output_dir: str | Path,
    stem: str,
    result: BacktestResult,
    bars: Sequence[Bar],
    config: StrategyConfig,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Path]:
    stem = validate_stem(stem)
    directory = Path(output_dir)
    payload = result_record(result)
    payload["config"] = config.to_dict()
    payload["data"] = {
        "bars": len(bars),
        "start": bars[0].open_time if bars else None,
        "end": bars[-1].close_time if bars else None,
        "provenance": dict(provenance) if provenance else None,
    }
    json_path = write_json(directory / f"{stem}.json", payload)
    csv_path = write_trades_csv(directory / f"{stem}-trades.csv", result.trades)
    md_path = directory / f"{stem}.md"
    write_text_atomic(
        md_path,
        markdown_summary(
            "Shotgun v2 Backtest",
            payload["metrics"],
            bars=bars,
            config=config,
            provenance=provenance,
        ),
    )
    return {"json": json_path, "csv": csv_path, "markdown": md_path}
