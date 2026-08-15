"""Binance OHLCV ingestion and immutable, verifiable CSV caches.

All public functions use epoch milliseconds.  Binance's kline endpoint returns
an inclusive ``endTime``; this module exposes the less surprising exclusive
``end_ms`` contract and converts it at the HTTP boundary.
"""

from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .models import Bar


BINANCE_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
ONE_MINUTE_MS = 60 * 1000
FIVE_MINUTES_MS = 5 * 60 * 1000
FIFTEEN_MINUTES_MS = 15 * 60 * 1000
SUPPORTED_INTERVALS = {
    "1m": ONE_MINUTE_MS,
    "5m": FIVE_MINUTES_MS,
    "15m": FIFTEEN_MINUTES_MS,
}
MAX_KLINES_PER_REQUEST = 1000
CSV_FIELDS = (
    "open_time",
    "open_time_utc",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
)


class DataError(ValueError):
    """Raised when source or cached market data violates the data contract."""


def normalize_timestamp_ms(value: int | float | str) -> int:
    """Normalize a realistic Unix millisecond or microsecond timestamp to ms.

    Values at or above 100 trillion are unambiguously microseconds for all
    dates supported by Binance.  Smaller values are retained, which also makes
    short synthetic millisecond timelines useful in tests.
    """

    try:
        timestamp = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DataError(f"invalid timestamp: {value!r}") from exc
    if timestamp < 0:
        raise DataError(f"timestamp must be non-negative: {timestamp}")
    if timestamp >= 100_000_000_000_000:
        timestamp //= 1000
    return timestamp


def interval_milliseconds(interval: str) -> int:
    """Return the exact duration for a supported Binance interval."""

    try:
        return SUPPORTED_INTERVALS[interval]
    except KeyError as exc:
        raise ValueError(
            f"unsupported interval {interval!r}; choose one of {tuple(SUPPORTED_INTERVALS)}"
        ) from exc


def completed_bar_cutoff_ms(
    now_ms: int | float | str | None = None,
    *,
    interval_ms: int = FIVE_MINUTES_MS,
) -> int:
    """Return the exclusive opening-time cutoff for completed bars."""

    current = normalize_timestamp_ms(
        int(time.time() * 1000) if now_ms is None else now_ms
    )
    if interval_ms <= 0:
        raise ValueError("interval_ms must be positive")
    return current - current % interval_ms


def _number(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DataError(f"invalid {name}: {value!r}") from exc
    if result != result or result in (float("inf"), float("-inf")):
        raise DataError(f"non-finite {name}: {value!r}")
    return result


def bar_from_binance_kline(values: Sequence[Any]) -> Bar:
    """Construct a :class:`Bar` from one Binance REST kline row."""

    if len(values) < 7:
        raise DataError(f"Binance kline has {len(values)} fields; expected at least 7")
    return Bar(
        open_time=normalize_timestamp_ms(values[0]),
        open=_number(values[1], "open"),
        high=_number(values[2], "high"),
        low=_number(values[3], "low"),
        close=_number(values[4], "close"),
        volume=_number(values[5], "volume"),
        close_time=normalize_timestamp_ms(values[6]),
    )


def is_complete_bar(bar: Bar, now_ms: int | float | str | None = None) -> bool:
    """Return whether ``bar`` had closed by the supplied snapshot time."""

    snapshot = normalize_timestamp_ms(
        int(time.time() * 1000) if now_ms is None else now_ms
    )
    return bar.close_time < snapshot


def filter_complete_bars(
    bars: Iterable[Bar], now_ms: int | float | str | None = None
) -> list[Bar]:
    """Remove a still-forming final bar without mutating the input."""

    snapshot = normalize_timestamp_ms(
        int(time.time() * 1000) if now_ms is None else now_ms
    )
    return [bar for bar in bars if bar.close_time < snapshot]


def validate_bars(
    bars: Sequence[Bar],
    *,
    strict_gaps: bool = True,
    interval_ms: int = FIVE_MINUTES_MS,
) -> None:
    """Reject duplicate, out-of-order, and (by default) non-contiguous bars."""

    if interval_ms <= 0:
        raise ValueError("interval_ms must be positive")
    for index, bar in enumerate(bars):
        if strict_gaps and bar.open_time % interval_ms != 0:
            raise DataError(
                f"bar at index {index} is not aligned to the {interval_ms} ms UTC grid"
            )
        if strict_gaps and bar.close_time != bar.open_time + interval_ms - 1:
            raise DataError(
                f"bar at index {index} has invalid close_time duration"
            )
        if index == 0:
            continue
        previous = bars[index - 1]
        delta = bar.open_time - previous.open_time
        if delta == 0:
            raise DataError(
                f"duplicate bar open_time at index {index}: {bar.open_time}"
            )
        if delta < 0:
            raise DataError(
                "bars out of order at index "
                f"{index}: {previous.open_time} then {bar.open_time}"
            )
        if strict_gaps and delta != interval_ms:
            raise DataError(
                f"non-{interval_ms // 60000}m gap at index {index}: "
                f"expected {interval_ms} ms, got {delta} ms"
            )


def _retry_after_seconds(exc: BaseException) -> float | None:
    if not isinstance(exc, urllib.error.HTTPError) or exc.headers is None:
        return None
    value = exc.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _get_json(
    url: str,
    *,
    opener: Callable[..., Any],
    timeout: float,
    max_retries: int,
    backoff_seconds: float,
    sleeper: Callable[[float], None],
) -> Any:
    last_error: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={"Accept": "application/json", "User-Agent": "shotgun-research/1"},
            )
            with opener(request, timeout=timeout) as response:
                payload = response.read()
            return json.loads(payload.decode("utf-8"))
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            last_error = exc
            if attempt == max_retries:
                break
            retry_after = _retry_after_seconds(exc)
            delay = (
                retry_after
                if retry_after is not None
                else backoff_seconds * (2**attempt)
            )
            sleeper(delay)
    raise DataError(f"Binance request failed after {max_retries + 1} attempts: {last_error}")


def fetch_binance_klines(
    start_ms: int | float | str,
    end_ms: int | float | str | None = None,
    *,
    symbol: str = "BTCUSDT",
    interval: str = "5m",
    now_ms: int | float | str | None = None,
    limit: int = MAX_KLINES_PER_REQUEST,
    timeout: float = 20.0,
    max_retries: int = 4,
    backoff_seconds: float = 0.5,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleeper: Callable[[float], None] = time.sleep,
) -> list[Bar]:
    """Fetch completed Binance klines using safe forward pagination.

    ``end_ms`` is exclusive.  The fetch is always capped at the opening time of
    the currently forming UTC candle for ``interval``, even if a future end is given.
    """

    interval_ms = interval_milliseconds(interval)
    if not symbol or not symbol.isalnum():
        raise ValueError("symbol must be non-empty and alphanumeric")
    if not 1 <= limit <= MAX_KLINES_PER_REQUEST:
        raise ValueError(f"limit must be between 1 and {MAX_KLINES_PER_REQUEST}")
    if max_retries < 0 or backoff_seconds < 0 or timeout <= 0:
        raise ValueError("retry counts/delays must be non-negative and timeout positive")

    cursor = normalize_timestamp_ms(start_ms)
    snapshot = normalize_timestamp_ms(
        int(time.time() * 1000) if now_ms is None else now_ms
    )
    completed_cutoff = completed_bar_cutoff_ms(snapshot, interval_ms=interval_ms)
    requested_end = (
        completed_cutoff if end_ms is None else normalize_timestamp_ms(end_ms)
    )
    effective_end = min(requested_end, completed_cutoff)
    if effective_end <= cursor:
        return []

    bars: list[Bar] = []
    while cursor < effective_end:
        query = urllib.parse.urlencode(
            {
                "symbol": symbol.upper(),
                "interval": interval,
                "startTime": cursor,
                "endTime": effective_end - 1,
                "limit": limit,
            }
        )
        payload = _get_json(
            f"{BINANCE_KLINES_URL}?{query}",
            opener=opener,
            timeout=timeout,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            sleeper=sleeper,
        )
        if not isinstance(payload, list):
            raise DataError(f"unexpected Binance response: {payload!r}")
        if not payload:
            break

        page = [bar_from_binance_kline(row) for row in payload]
        page = [
            bar
            for bar in page
            if cursor <= bar.open_time < effective_end and bar.close_time < snapshot
        ]
        if not page:
            break
        bars.extend(page)

        next_cursor = page[-1].open_time + interval_ms
        if next_cursor <= cursor:
            raise DataError("Binance pagination did not advance")
        cursor = next_cursor
        if len(payload) < limit:
            break

    validate_bars(bars, strict_gaps=True, interval_ms=interval_ms)
    return bars


def fetch_binance_klines_parallel(
    start_ms: int | float | str,
    end_ms: int | float | str | None = None,
    *,
    symbol: str = "BTCUSDT",
    interval: str = "5m",
    now_ms: int | float | str | None = None,
    workers: int = 4,
    limit: int = MAX_KLINES_PER_REQUEST,
    timeout: float = 20.0,
    max_retries: int = 4,
    backoff_seconds: float = 0.5,
) -> list[Bar]:
    """Fetch independent, bounded kline pages concurrently and validate the join."""

    if not 1 <= workers <= 8:
        raise ValueError("workers must be between 1 and 8")
    interval_ms = interval_milliseconds(interval)
    start = normalize_timestamp_ms(start_ms)
    snapshot = normalize_timestamp_ms(
        int(time.time() * 1000) if now_ms is None else now_ms
    )
    completed_cutoff = completed_bar_cutoff_ms(snapshot, interval_ms=interval_ms)
    requested_end = (
        completed_cutoff if end_ms is None else normalize_timestamp_ms(end_ms)
    )
    effective_end = min(requested_end, completed_cutoff)
    if effective_end <= start:
        return []
    page_span = limit * interval_ms
    windows = [
        (page_start, min(page_start + page_span, effective_end))
        for page_start in range(start, effective_end, page_span)
    ]

    def fetch_window(window: tuple[int, int]) -> list[Bar]:
        page_start, page_end = window
        return fetch_binance_klines(
            page_start,
            page_end,
            symbol=symbol,
            interval=interval,
            now_ms=snapshot,
            limit=limit,
            timeout=timeout,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        pages = list(executor.map(fetch_window, windows))
    bars = [bar for page in pages for bar in page]
    validate_bars(bars, strict_gaps=True, interval_ms=interval_ms)
    return bars


def _format_float(value: float) -> str:
    return format(value, ".17g")


def _utc_text(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def bars_to_csv_bytes(bars: Sequence[Bar]) -> bytes:
    """Serialize bars to stable UTF-8 CSV bytes suitable for hashing."""

    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for bar in bars:
        writer.writerow(
            {
                "open_time": str(bar.open_time),
                "open_time_utc": _utc_text(bar.open_time),
                "open": _format_float(bar.open),
                "high": _format_float(bar.high),
                "low": _format_float(bar.low),
                "close": _format_float(bar.close),
                "volume": _format_float(bar.volume),
                "close_time": str(bar.close_time),
            }
        )
    return stream.getvalue().encode("utf-8")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def metadata_path(csv_path: str | os.PathLike[str]) -> Path:
    path = Path(csv_path)
    return path.with_suffix(path.suffix + ".meta.json")


def read_cache_metadata(
    csv_path: str | os.PathLike[str], *, require: bool = True
) -> dict[str, Any] | None:
    """Read a cache sidecar, optionally requiring it to exist."""

    sidecar = metadata_path(csv_path)
    if not sidecar.exists():
        if require:
            raise DataError(f"formal cache metadata is required: {sidecar}")
        return None
    try:
        value = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataError(f"invalid cache metadata: {sidecar}") from exc
    if not isinstance(value, dict):
        raise DataError(f"cache metadata must be an object: {sidecar}")
    return value


def write_cache(
    csv_path: str | os.PathLike[str],
    bars: Sequence[Bar],
    *,
    source_url: str = BINANCE_KLINES_URL,
    symbol: str = "BTCUSDT",
    interval: str = "5m",
    requested_start_ms: int | None = None,
    requested_end_ms: int | None = None,
    downloaded_at: datetime | None = None,
) -> dict[str, Any]:
    """Write immutable CSV and metadata sidecar and return the metadata.

    An existing byte-identical pair is accepted idempotently.  Existing CSV
    bytes are never replaced; a hash mismatch raises ``FileExistsError``.
    """

    interval_ms = interval_milliseconds(interval)
    validate_bars(bars, strict_gaps=True, interval_ms=interval_ms)
    path = Path(csv_path)
    sidecar = metadata_path(path)
    content = bars_to_csv_bytes(bars)
    digest = sha256_bytes(content)
    downloaded = downloaded_at or datetime.now(timezone.utc)
    if downloaded.tzinfo is None:
        downloaded = downloaded.replace(tzinfo=timezone.utc)
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "source_url": source_url,
        "symbol": symbol.upper(),
        "interval": interval,
        "downloaded_at_utc": downloaded.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "requested_start_ms": requested_start_ms,
        "requested_end_ms_exclusive": requested_end_ms,
        "exact_data_cutoff_ms": bars[-1].close_time if bars else None,
        "first_open_time_ms": bars[0].open_time if bars else None,
        "last_open_time_ms": bars[-1].open_time if bars else None,
        "row_count": len(bars),
        "csv_sha256": digest,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_bytes()
        if sha256_bytes(existing) != digest:
            raise FileExistsError(f"refusing to overwrite immutable cache: {path}")
    else:
        try:
            with path.open("xb") as handle:
                handle.write(content)
        except FileExistsError:
            if sha256_bytes(path.read_bytes()) != digest:
                raise FileExistsError(f"refusing to overwrite immutable cache: {path}")

    encoded_metadata = (
        json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    if sidecar.exists():
        try:
            existing_metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataError(f"invalid cache metadata: {sidecar}") from exc
        if existing_metadata.get("csv_sha256") != digest:
            raise FileExistsError(f"refusing to overwrite immutable metadata: {sidecar}")
        return existing_metadata
    try:
        with sidecar.open("xb") as handle:
            handle.write(encoded_metadata)
    except FileExistsError:
        existing_metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        if existing_metadata.get("csv_sha256") != digest:
            raise FileExistsError(f"refusing to overwrite immutable metadata: {sidecar}")
        return existing_metadata
    return metadata


def _bar_from_csv_row(
    row: dict[str, str], row_number: int, default_interval_ms: int
) -> Bar:
    timestamp = row.get("open_time") or row.get("open_time_ms") or row.get("timestamp_ms")
    close_timestamp = row.get("close_time") or row.get("close_time_ms")
    if timestamp is None:
        raise DataError(f"CSV row {row_number} has no open timestamp")
    open_time = normalize_timestamp_ms(timestamp)
    close_time = (
        open_time + default_interval_ms - 1
        if close_timestamp in (None, "")
        else normalize_timestamp_ms(close_timestamp)
    )
    try:
        return Bar(
            open_time=open_time,
            open=_number(row["open"], "open"),
            high=_number(row["high"], "high"),
            low=_number(row["low"], "low"),
            close=_number(row["close"], "close"),
            volume=_number(row["volume"], "volume"),
            close_time=close_time,
        )
    except KeyError as exc:
        raise DataError(f"CSV row {row_number} missing column {exc.args[0]!r}") from exc


def load_cache(
    csv_path: str | os.PathLike[str],
    *,
    verify_hash: bool = True,
    drop_incomplete: bool = False,
    now_ms: int | float | str | None = None,
    strict_gaps: bool = True,
    require_metadata: bool = False,
    expected_symbol: str | None = None,
    expected_interval: str | None = None,
) -> list[Bar]:
    """Load and validate bars from CSV, optionally verifying its sidecar hash."""

    path = Path(csv_path)
    content = path.read_bytes()
    metadata = read_cache_metadata(path, require=require_metadata)
    if verify_hash and metadata is not None:
        expected = metadata.get("csv_sha256")
        actual = sha256_bytes(content)
        if not expected or expected != actual:
            raise DataError(f"cache hash mismatch for {path}")

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DataError(f"cache is not UTF-8: {path}") from exc
    interval_name = (
        metadata.get("interval") if metadata is not None else expected_interval
    )
    declared_interval_ms = (
        interval_milliseconds(interval_name) if interval_name is not None else None
    )
    reader = csv.DictReader(io.StringIO(text))
    bars = [
        _bar_from_csv_row(
            row,
            number,
            declared_interval_ms or FIVE_MINUTES_MS,
        )
        for number, row in enumerate(reader, start=2)
    ]
    if drop_incomplete:
        bars = filter_complete_bars(bars, now_ms=now_ms)
    inferred_interval_ms = (
        bars[0].close_time - bars[0].open_time + 1 if bars else FIVE_MINUTES_MS
    )
    validate_bars(
        bars,
        strict_gaps=strict_gaps,
        interval_ms=declared_interval_ms or inferred_interval_ms,
    )
    if metadata is not None:
        if metadata.get("schema_version") != 1:
            raise DataError("unsupported cache metadata schema_version")
        if expected_symbol and metadata.get("symbol") != expected_symbol.upper():
            raise DataError(
                f"expected symbol {expected_symbol.upper()}, got {metadata.get('symbol')!r}"
            )
        if expected_interval and metadata.get("interval") != expected_interval:
            raise DataError(
                f"expected interval {expected_interval}, got {metadata.get('interval')!r}"
            )
        checks = {
            "row_count": len(bars),
            "first_open_time_ms": bars[0].open_time if bars else None,
            "last_open_time_ms": bars[-1].open_time if bars else None,
            "exact_data_cutoff_ms": bars[-1].close_time if bars else None,
        }
        for name, actual in checks.items():
            if metadata.get(name) != actual:
                raise DataError(
                    f"cache metadata {name} mismatch: {metadata.get(name)!r} != {actual!r}"
                )
    return bars


def parse_time_argument(value: str) -> int:
    """Parse epoch ms/us or an ISO-8601 value into epoch milliseconds."""

    stripped = value.strip()
    try:
        return normalize_timestamp_ms(stripped)
    except DataError:
        pass
    iso_value = stripped[:-1] + "+00:00" if stripped.endswith("Z") else stripped
    try:
        parsed = datetime.fromisoformat(iso_value)
    except ValueError as exc:
        raise DataError(f"invalid date/time: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)
