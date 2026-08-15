from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shotgun.models import BacktestResult, StrategyConfig
from shotgun.models import Bar
from shotgun.data import write_cache
from shotgun.report import (
    TRADE_CSV_FIELDS,
    validate_stem,
    write_backtest_bundle,
    write_text_atomic,
    write_trades_csv,
)


ROOT = Path(__file__).resolve().parents[1]


class ReportTests(unittest.TestCase):
    def test_atomic_text_replaces_existing_artifact_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluation.md"
            path.write_text("old", encoding="utf-8")
            returned = write_text_atomic(path, "complete report")

            self.assertEqual(returned, path)
            self.assertEqual(path.read_text(encoding="utf-8"), "complete report")
            self.assertEqual(list(Path(directory).glob(".evaluation.md.*.tmp")), [])

    def test_empty_trade_csv_uses_full_stable_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.csv"
            write_trades_csv(path, ())
            with path.open(newline="", encoding="utf-8") as handle:
                header = next(csv.reader(handle))
        self.assertEqual(header, TRADE_CSV_FIELDS)
        self.assertIn("planned_risk_cash", header)
        self.assertIn("maximum_favorable_excursion", header)
        self.assertIn("fees", header)

    def test_bundle_embeds_verified_provenance(self):
        provenance = {
            "source_url": "https://data-api.binance.vision/api/v3/klines",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "downloaded_at_utc": "2026-07-21T00:00:00Z",
            "csv_sha256": "a" * 64,
            "exact_data_cutoff_ms": 123,
        }
        result = BacktestResult("fingerprint", 100.0, 100.0, ())
        with tempfile.TemporaryDirectory() as directory:
            paths = write_backtest_bundle(
                directory,
                "report",
                result,
                (),
                StrategyConfig(),
                provenance=provenance,
            )
            payload = json.loads(paths["json"].read_text(encoding="utf-8"))
            markdown = paths["markdown"].read_text(encoding="utf-8")
        self.assertEqual(payload["data"]["provenance"], provenance)
        self.assertIn(provenance["csv_sha256"], markdown)

    def test_report_stem_cannot_escape_output_directory(self):
        self.assertEqual(validate_stem("shotgun"), "shotgun")
        for bad in ("", "..", "../escape", "nested/report"):
            with self.assertRaises(ValueError):
                validate_stem(bad)

    def test_cli_help_smoke(self):
        for name in (
            "fetch_data.py",
            "backtest.py",
            "evaluate.py",
            "recent_signals.py",
            "parity_check.py",
            "build_parity_fixture.py",
            "research_5m.py",
            "research_1m.py",
            "research_1m_levels.py",
        ):
            completed = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / name), "--help"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, f"{name}: {completed.stderr}")

    def test_formal_clis_accept_5m_cache_and_reject_15m_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bars = [
                Bar(
                    index * 300_000,
                    100.0,
                    101.0,
                    99.0,
                    100.0,
                    10.0,
                    (index + 1) * 300_000 - 1,
                )
                for index in range(800)
            ]
            one_minute = root / "one.csv"
            write_cache(one_minute, bars, interval="5m")
            commands = (
                [
                    str(ROOT / "scripts" / "backtest.py"),
                    str(one_minute),
                    "--output-dir",
                    str(root),
                    "--stem",
                    "backtest",
                ],
                [
                    str(ROOT / "scripts" / "evaluate.py"),
                    str(one_minute),
                    "--output-dir",
                    str(root),
                    "--stem",
                    "evaluation",
                ],
                [
                    str(ROOT / "scripts" / "recent_signals.py"),
                    str(one_minute),
                    "--output",
                    str(root / "recent.json"),
                ],
            )
            for command in commands:
                completed = subprocess.run(
                    [sys.executable, *command],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

            fifteen_minute = root / "fifteen.csv"
            fifteen_bar = Bar(0, 100.0, 101.0, 99.0, 100.0, 10.0, 899_999)
            write_cache(fifteen_minute, [fifteen_bar], interval="15m")
            rejected = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "backtest.py"),
                    str(fifteen_minute),
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("expected interval 5m", rejected.stderr)


if __name__ == "__main__":
    unittest.main()
