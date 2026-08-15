#!/usr/bin/env python3
"""Compare TradingView-exported Shotgun signal timestamps with golden JSON."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence


TIME_CANDIDATES = ("time", "timestamp", "datetime", "date")
SIGNAL_CANDIDATES = (
    "shotgun parity signal",
    "parity signal",
    "signal",
    "side",
    "direction",
)


class ParityInputError(ValueError):
    """Raised when an export or expected file is not usable."""


@dataclass(frozen=True, order=True)
class Signal:
    timestamp_ms: int
    side: str

    @property
    def timestamp_iso(self) -> str:
        value = datetime.fromtimestamp(self.timestamp_ms / 1000, tz=timezone.utc)
        return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Comparison:
    expected: tuple[Signal, ...]
    actual: tuple[Signal, ...]
    missing: tuple[Signal, ...]
    unexpected: tuple[Signal, ...]

    @property
    def matches(self) -> bool:
        return not self.missing and not self.unexpected


def _normalized_header(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", " ").split())


def _choose_column(
    fieldnames: Sequence[str], requested: str | None, candidates: Sequence[str], kind: str
) -> str:
    if requested:
        if requested not in fieldnames:
            raise ParityInputError(
                f"{kind} column {requested!r} is absent; available: {', '.join(fieldnames)}"
            )
        return requested

    normalized = {_normalized_header(name): name for name in fieldnames}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    for normalized_name, original in normalized.items():
        if any(candidate in normalized_name for candidate in candidates):
            return original
    raise ParityInputError(
        f"could not detect {kind} column; pass --{kind}-column. "
        f"Available: {', '.join(fieldnames)}"
    )


def parse_timestamp_ms(raw: object) -> int:
    text = str(raw).strip()
    if not text:
        raise ParityInputError("empty signal timestamp")

    try:
        numeric = float(text)
    except ValueError:
        numeric = None
    if numeric is not None:
        magnitude = abs(numeric)
        if magnitude < 100_000_000_000:
            numeric *= 1000
        elif magnitude >= 100_000_000_000_000:
            numeric /= 1000
        return int(round(numeric))

    iso_text = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(iso_text)
    except ValueError as exc:
        raise ParityInputError(f"unrecognized timestamp {text!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(round(parsed.astimezone(timezone.utc).timestamp() * 1000))


def parse_side(raw: object) -> str | None:
    text = str(raw).strip().lower()
    if not text or text in {"na", "nan", "null", "none", "—"}:
        return None
    aliases = {
        "long": "long",
        "buy": "long",
        "l": "long",
        "+1": "long",
        "short": "short",
        "sell": "short",
        "s": "short",
        "-1": "short",
    }
    if text in aliases:
        return aliases[text]
    try:
        numeric = float(text)
    except ValueError as exc:
        raise ParityInputError(f"unrecognized signal value {raw!r}") from exc
    if numeric > 0:
        return "long"
    if numeric < 0:
        return "short"
    return None


def _deduplicate(signals: Iterable[Signal], source: str) -> tuple[Signal, ...]:
    ordered = tuple(sorted(signals))
    for previous, current in zip(ordered, ordered[1:]):
        if previous == current:
            raise ParityInputError(
                f"duplicate {source} signal: {current.timestamp_iso} {current.side}"
            )
    return ordered


def load_exported_signals(
    path: Path, time_column: str | None = None, signal_column: str | None = None
) -> tuple[Signal, ...]:
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise ParityInputError(f"cannot read Pine CSV {path}: {exc}") from exc
    with handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ParityInputError(f"Pine CSV {path} has no header")
        time_name = _choose_column(reader.fieldnames, time_column, TIME_CANDIDATES, "time")
        signal_name = _choose_column(
            reader.fieldnames, signal_column, SIGNAL_CANDIDATES, "signal"
        )
        signals: list[Signal] = []
        for row_number, row in enumerate(reader, start=2):
            try:
                side = parse_side(row.get(signal_name, ""))
                if side is None:
                    continue
                signals.append(Signal(parse_timestamp_ms(row.get(time_name, "")), side))
            except ParityInputError as exc:
                raise ParityInputError(f"{path}:{row_number}: {exc}") from exc
    return _deduplicate(signals, "exported")


def _signal_from_mapping(value: Mapping[str, object], index: int) -> Signal:
    timestamp = value.get(
        "timestamp",
        value.get(
            "time",
            value.get(
                "signal_time", value.get("timestamp_ms", value.get("open_time"))
            ),
        ),
    )
    if timestamp is None:
        raise ParityInputError(f"expected signal {index} has no timestamp/time")
    side = parse_side(
        value.get("side", value.get("signal", value.get("direction", "")))
    )
    if side is None:
        raise ParityInputError(f"expected signal {index} has no long/short side")
    return Signal(parse_timestamp_ms(timestamp), side)


def load_expected_signals(path: Path) -> tuple[Signal, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ParityInputError(f"cannot read expected JSON {path}: {exc}") from exc
    values = payload.get("signals") if isinstance(payload, dict) else payload
    if not isinstance(values, list):
        raise ParityInputError("expected JSON must be a list or an object with a signals list")
    signals: list[Signal] = []
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise ParityInputError(f"expected signal {index} is not an object")
        signals.append(_signal_from_mapping(value, index))
    return _deduplicate(signals, "expected")


def compare_signals(expected: Sequence[Signal], actual: Sequence[Signal]) -> Comparison:
    expected_tuple = tuple(sorted(expected))
    actual_tuple = tuple(sorted(actual))
    expected_set = set(expected_tuple)
    actual_set = set(actual_tuple)
    return Comparison(
        expected=expected_tuple,
        actual=actual_tuple,
        missing=tuple(sorted(expected_set - actual_set)),
        unexpected=tuple(sorted(actual_set - expected_set)),
    )


def _format_signal(signal: Signal) -> str:
    return f"{signal.timestamp_iso} {signal.side}"


def render_comparison(comparison: Comparison) -> str:
    lines = [
        f"Expected signals: {len(comparison.expected)}",
        f"Exported signals: {len(comparison.actual)}",
    ]
    if comparison.matches:
        lines.append("PARITY OK: timestamps and directions match exactly.")
        return "\n".join(lines)
    lines.append("PARITY FAILED")
    if comparison.missing:
        lines.append("Missing from Pine export:")
        lines.extend(f"  - {_format_signal(signal)}" for signal in comparison.missing)
    if comparison.unexpected:
        lines.append("Unexpected in Pine export:")
        lines.extend(f"  + {_format_signal(signal)}" for signal in comparison.unexpected)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare TradingView Shotgun signal timestamps with golden JSON."
    )
    parser.add_argument("pine_csv", type=Path, help="TradingView chart-data CSV")
    parser.add_argument("expected_json", type=Path, help="expected signal JSON")
    parser.add_argument("--time-column", help="CSV time column (auto-detected by default)")
    parser.add_argument(
        "--signal-column", help="CSV parity signal column (auto-detected by default)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        actual = load_exported_signals(args.pine_csv, args.time_column, args.signal_column)
        expected = load_expected_signals(args.expected_json)
        comparison = compare_signals(expected, actual)
    except ParityInputError as exc:
        print(f"parity input error: {exc}", file=sys.stderr)
        return 2
    print(render_comparison(comparison))
    return 0 if comparison.matches else 1


if __name__ == "__main__":
    raise SystemExit(main())
