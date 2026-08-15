from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from shotgun.data import (
    DataError,
    ONE_MINUTE_MS,
    FIFTEEN_MINUTES_MS,
    bar_from_binance_kline,
    completed_bar_cutoff_ms,
    fetch_binance_klines,
    fetch_binance_klines_parallel,
    filter_complete_bars,
    load_cache,
    metadata_path,
    normalize_timestamp_ms,
    validate_bars,
    write_cache,
)
from shotgun.models import Bar


BASE = (1_700_000_100_000 // ONE_MINUTE_MS) * ONE_MINUTE_MS


def make_bar(open_time: int, price: float = 100.0) -> Bar:
    return Bar(
        open_time=open_time,
        open=price,
        high=price + 2,
        low=price - 2,
        close=price + 1,
        volume=12.5,
        close_time=open_time + ONE_MINUTE_MS - 1,
    )


def kline(open_time: int, price: float = 100.0) -> list[object]:
    return [
        open_time,
        str(price),
        str(price + 2),
        str(price - 2),
        str(price + 1),
        "12.5",
        open_time + ONE_MINUTE_MS - 1,
        "0",
        1,
        "0",
        "0",
        "0",
    ]


class FakeResponse:
    def __init__(self, payload: object):
        self.payload = json.dumps(payload).encode()

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class DataTests(unittest.TestCase):
    def test_one_minute_cutoff_is_exact_at_utc_boundaries(self) -> None:
        boundary = BASE + ONE_MINUTE_MS
        self.assertEqual(completed_bar_cutoff_ms(boundary, interval_ms=ONE_MINUTE_MS), boundary)
        self.assertEqual(completed_bar_cutoff_ms(boundary - 1, interval_ms=ONE_MINUTE_MS), BASE)

    def test_normalizes_microseconds_and_constructs_bar(self) -> None:
        self.assertEqual(normalize_timestamp_ms(BASE * 1000 + 999), BASE)
        row = kline(BASE)
        row[0] = BASE * 1000
        row[6] = (BASE + ONE_MINUTE_MS - 1) * 1000
        bar = bar_from_binance_kline(row)
        self.assertEqual(bar.open_time, BASE)
        self.assertEqual(bar.close_time, BASE + ONE_MINUTE_MS - 1)
        self.assertEqual(bar.close, 101.0)

    def test_incomplete_bar_is_removed_at_exact_boundary(self) -> None:
        bars = [make_bar(BASE), make_bar(BASE + ONE_MINUTE_MS)]
        cutoff = BASE + ONE_MINUTE_MS
        self.assertEqual(filter_complete_bars(bars, cutoff), bars[:1])

    def test_validation_rejects_duplicates_order_and_gaps(self) -> None:
        with self.assertRaisesRegex(DataError, "duplicate"):
            validate_bars([make_bar(BASE), make_bar(BASE)], interval_ms=ONE_MINUTE_MS)
        with self.assertRaisesRegex(DataError, "out of order"):
            validate_bars([make_bar(BASE), make_bar(BASE - ONE_MINUTE_MS)], interval_ms=ONE_MINUTE_MS)
        with self.assertRaisesRegex(DataError, "gap"):
            validate_bars([make_bar(BASE), make_bar(BASE + 2 * ONE_MINUTE_MS)], interval_ms=ONE_MINUTE_MS)
        with self.assertRaisesRegex(DataError, "aligned"):
            validate_bars([make_bar(BASE + 1)], interval_ms=ONE_MINUTE_MS)
        malformed_close = Bar(BASE, 100, 102, 98, 101, 12.5, BASE + 10)
        with self.assertRaisesRegex(DataError, "duration"):
            validate_bars([malformed_close], interval_ms=ONE_MINUTE_MS)

    def test_paginated_fetch_uses_exclusive_end_and_drops_forming_bar(self) -> None:
        requested_starts: list[int] = []
        pages = [
            [kline(BASE), kline(BASE + ONE_MINUTE_MS)],
            [kline(BASE + 2 * ONE_MINUTE_MS), kline(BASE + 3 * ONE_MINUTE_MS)],
        ]

        def opener(request: object, timeout: float) -> FakeResponse:
            del timeout
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
            requested_starts.append(int(query["startTime"][0]))
            self.assertEqual(int(query["endTime"][0]), BASE + 4 * ONE_MINUTE_MS - 1)
            self.assertEqual(query["interval"], ["1m"])
            return FakeResponse(pages[len(requested_starts) - 1])

        bars = fetch_binance_klines(
            BASE,
            BASE + 5 * ONE_MINUTE_MS,
            now_ms=BASE + 4 * ONE_MINUTE_MS,
            interval="1m",
            limit=2,
            opener=opener,
            sleeper=lambda _: None,
        )
        self.assertEqual(
            requested_starts, [BASE, BASE + 2 * ONE_MINUTE_MS]
        )
        self.assertEqual(len(bars), 4)
        self.assertEqual(bars[-1].open_time, BASE + 3 * ONE_MINUTE_MS)

    def test_fetch_retries_with_exponential_backoff(self) -> None:
        calls = 0
        sleeps: list[float] = []

        def opener(request: object, timeout: float) -> FakeResponse:
            nonlocal calls
            del request, timeout
            calls += 1
            if calls < 3:
                raise urllib.error.URLError("temporary")
            return FakeResponse([kline(BASE)])

        bars = fetch_binance_klines(
            BASE,
            BASE + ONE_MINUTE_MS,
            now_ms=BASE + 2 * ONE_MINUTE_MS,
            interval="1m",
            opener=opener,
            sleeper=sleeps.append,
            backoff_seconds=0.25,
        )
        self.assertEqual(len(bars), 1)
        self.assertEqual(sleeps, [0.25, 0.5])

    def test_parallel_fetch_joins_bounded_pages_in_time_order(self) -> None:
        def fake_fetch(start, end, **kwargs):
            del kwargs
            return [
                make_bar(open_time)
                for open_time in range(start, end, ONE_MINUTE_MS)
            ]

        with patch("shotgun.data.fetch_binance_klines", side_effect=fake_fetch) as mocked:
            bars = fetch_binance_klines_parallel(
                BASE,
                BASE + 5 * ONE_MINUTE_MS,
                interval="1m",
                now_ms=BASE + 6 * ONE_MINUTE_MS,
                limit=2,
                workers=2,
            )
        self.assertEqual(mocked.call_count, 3)
        self.assertEqual(
            [item.open_time for item in bars],
            [BASE + index * ONE_MINUTE_MS for index in range(5)],
        )

    def test_cache_round_trip_metadata_hash_and_immutability(self) -> None:
        bars = [make_bar(BASE), make_bar(BASE + ONE_MINUTE_MS, 103.0)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bars.csv"
            metadata = write_cache(
                path,
                bars,
                requested_start_ms=BASE,
                requested_end_ms=BASE + 2 * ONE_MINUTE_MS,
                interval="1m",
            )
            self.assertEqual(load_cache(path), bars)
            self.assertEqual(
                load_cache(
                    path,
                    require_metadata=True,
                    expected_symbol="BTCUSDT",
                    expected_interval="1m",
                ),
                bars,
            )
            self.assertEqual(metadata["row_count"], 2)
            self.assertEqual(len(metadata["csv_sha256"]), 64)
            stored = json.loads(metadata_path(path).read_text())
            self.assertEqual(stored["csv_sha256"], metadata["csv_sha256"])

            write_cache(path, bars, interval="1m")
            with self.assertRaisesRegex(FileExistsError, "immutable"):
                write_cache(path, [make_bar(BASE, 999.0)], interval="1m")

    def test_hash_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bars.csv"
            write_cache(path, [make_bar(BASE)], interval="1m")
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaisesRegex(DataError, "hash mismatch"):
                load_cache(path)

    def test_csv_loader_normalizes_microsecond_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "micro.csv"
            path.write_text(
                "open_time,open,high,low,close,volume,close_time\n"
                f"{BASE * 1000},100,102,98,101,12.5,{(BASE + ONE_MINUTE_MS - 1) * 1000}\n"
            )
            loaded = load_cache(path)
            self.assertEqual(loaded[0], make_bar(BASE))
            with self.assertRaisesRegex(DataError, "metadata is required"):
                load_cache(path, require_metadata=True)

    def test_formal_cache_rejects_mislabeled_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bars.csv"
            write_cache(path, [make_bar(BASE)], symbol="ETHUSDT", interval="1m")
            with self.assertRaisesRegex(DataError, "expected symbol BTCUSDT"):
                load_cache(
                    path,
                    require_metadata=True,
                    expected_symbol="BTCUSDT",
                    expected_interval="1m",
                )

    def test_metadata_interval_cannot_mislabel_physical_bar_duration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            one_path = Path(directory) / "one.csv"
            write_cache(one_path, [make_bar(BASE)], interval="1m")
            one_metadata_path = metadata_path(one_path)
            one_metadata = json.loads(one_metadata_path.read_text())
            one_metadata["interval"] = "15m"
            one_metadata_path.write_text(json.dumps(one_metadata))
            with self.assertRaisesRegex(DataError, "duration"):
                load_cache(
                    one_path,
                    require_metadata=True,
                    expected_interval="15m",
                )

            fifteen_path = Path(directory) / "fifteen.csv"
            fifteen_bar = Bar(
                BASE,
                100.0,
                102.0,
                98.0,
                101.0,
                12.5,
                BASE + FIFTEEN_MINUTES_MS - 1,
            )
            write_cache(fifteen_path, [fifteen_bar], interval="15m")
            fifteen_metadata_path = metadata_path(fifteen_path)
            fifteen_metadata = json.loads(fifteen_metadata_path.read_text())
            fifteen_metadata["interval"] = "1m"
            fifteen_metadata_path.write_text(json.dumps(fifteen_metadata))
            with self.assertRaisesRegex(DataError, "duration"):
                load_cache(
                    fifteen_path,
                    require_metadata=True,
                    expected_interval="1m",
                )


if __name__ == "__main__":
    unittest.main()
