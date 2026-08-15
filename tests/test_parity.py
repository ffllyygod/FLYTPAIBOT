from __future__ import annotations

import csv
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "parity_check.py"
FIXTURES = ROOT / "tests" / "fixtures"
PINE = ROOT / "pine" / "shotgun_strategy.pine"

SPEC = importlib.util.spec_from_file_location("parity_check", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import machinery guard
    raise RuntimeError(f"cannot load {SCRIPT}")
parity_check = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = parity_check
SPEC.loader.exec_module(parity_check)


class ParityComparatorTests(unittest.TestCase):
    def test_golden_fixture_matches(self) -> None:
        actual = parity_check.load_exported_signals(FIXTURES / "parity_bars.csv")
        expected = parity_check.load_expected_signals(FIXTURES / "parity_signals.json")
        comparison = parity_check.compare_signals(expected, actual)
        self.assertTrue(comparison.matches)
        self.assertEqual([signal.side for signal in actual], ["short", "short", "short", "long"])

    def test_golden_fixture_is_a_real_frozen_strategy_signal(self) -> None:
        from shotgun.models import Bar
        from shotgun.strategy import generate_signals

        with (FIXTURES / "parity_bars.csv").open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            bars = [
                Bar(
                    open_time=int(row["open_time"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    close_time=int(row["close_time"]),
                )
                for row in csv.DictReader(handle)
            ]
        generated = generate_signals(bars)
        expected = parity_check.load_expected_signals(FIXTURES / "parity_signals.json")
        actual = tuple(
            parity_check.Signal(signal.time, signal.side) for signal in generated
        )
        self.assertTrue(parity_check.compare_signals(expected, actual).matches)
        self.assertEqual(
            [(signal.index, signal.side) for signal in generated],
            [(1610, "short"), (1620, "short"), (2522, "short"), (3563, "long")],
        )
        self.assertTrue(
            all(
                later.open_time - earlier.open_time == 300_000
                for earlier, later in zip(bars, bars[1:])
            )
        )

    def test_timestamp_units_and_side_aliases_are_normalized(self) -> None:
        seconds = parity_check.parse_timestamp_ms("1767312900")
        milliseconds = parity_check.parse_timestamp_ms("1767312900000")
        microseconds = parity_check.parse_timestamp_ms("1767312900000000")
        self.assertEqual(seconds, milliseconds)
        self.assertEqual(milliseconds, microseconds)
        self.assertEqual(parity_check.parse_side("BUY"), "long")
        self.assertEqual(parity_check.parse_side("-1.0"), "short")
        self.assertIsNone(parity_check.parse_side("0"))

    def test_mismatch_returns_nonzero_and_prints_diff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            export = Path(directory) / "export.csv"
            export.write_text(
                "Time,Shotgun Parity Signal\n"
                "2026-01-02T00:15:00Z,-1\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(export),
                    str(FIXTURES / "parity_signals.json"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("PARITY FAILED", completed.stdout)
        self.assertIn("Missing from Pine export", completed.stdout)
        self.assertIn("Unexpected in Pine export", completed.stdout)

    def test_pine_source_has_static_non_repainting_contract(self) -> None:
        from shotgun.models import StrategyConfig

        source = PINE.read_text(encoding="utf-8")
        compact = "".join(source.lower().split())
        self.assertIn("//@version=6", source)
        self.assertIn("barstate.isconfirmed", source)
        self.assertIn("commission_value = 0.12", source)
        self.assertIn("timeframe.multiplier == 5", source)
        self.assertIn("const int FAST_LEN = 21", source)
        self.assertIn("const int SLOW_LEN = 55", source)
        self.assertIn("const int REGIME_LEN = 200", source)
        self.assertIn("const int STRUCTURE_LEN = 8", source)
        self.assertIn("const float MIN_PRICE_RISK_FRACTION = 0.0040", source)
        self.assertIn('plot(supportLevel, "8-bar Support"', source)
        self.assertIn('plot(resistanceLevel, "8-bar Resistance"', source)
        self.assertIn('plot(paritySignal, "Shotgun Parity Signal"', source)
        self.assertNotIn("request.security", compact)
        self.assertNotIn("lookahead", compact)
        self.assertNotIn("[-", compact)

        config = StrategyConfig()
        integer_contract = {
            "FAST_LEN": config.ema_fast_length,
            "SLOW_LEN": config.ema_slow_length,
            "REGIME_LEN": config.ema_regime_length,
            "ATR_LEN": config.atr_length,
            "RSI_LEN": config.rsi_length,
            "DI_LEN": config.dmi_length,
            "ADX_SMOOTHING": config.adx_length,
            "VOLUME_LEN": config.volume_sma_length,
            "SLOPE_LOOKBACK": config.slope_lookback,
            "PULLBACK_LEN": config.pullback_lookback,
            "TRIGGER_LEN": config.breakout_lookback,
            "STRUCTURE_LEN": config.structural_lookback,
            "WARMUP_BARS": config.min_signal_index,
            "MIN_TREND_EXIT_BARS": config.min_trend_exit_bars,
            "MAX_HOLD_BARS": config.max_hold_bars,
            "COOLDOWN_BARS": config.cooldown_bars,
        }
        for name, value in integer_contract.items():
            self.assertIn(f"const int {name} = {value}", source)

        float_contract = {
            "ADX_FLOOR": config.adx_min,
            "PULLBACK_ATR_TOLERANCE": config.pullback_atr_offset,
            "SLOW_BOUND_ATR_TOLERANCE": config.slow_break_atr_offset,
            "MIN_BODY_ATR": config.minimum_body_atr,
            "LONG_MIN_CLV": config.long_clv_min,
            "SHORT_MAX_CLV": config.short_clv_max,
            "LONG_RSI_MIN": config.long_rsi_min,
            "LONG_RSI_MAX": config.long_rsi_max,
            "SHORT_RSI_MIN": config.short_rsi_min,
            "SHORT_RSI_MAX": config.short_rsi_max,
            "MIN_VOLUME_RATIO": config.volume_sma_fraction,
            "MAX_STRETCH_ATR": config.max_ema_distance_atr,
            "MIN_ATR_FRACTION": config.min_atr_fraction,
            "MAX_ATR_FRACTION": config.max_atr_fraction,
            "STRUCTURE_BUFFER_ATR": config.structural_stop_atr,
            "MIN_RISK_ATR": config.min_risk_atr,
            "MAX_RISK_ATR": config.max_risk_atr,
            "MIN_PRICE_RISK_FRACTION": config.min_price_risk_fraction,
            "MAX_PRICE_RISK_FRACTION": config.max_price_risk_fraction,
            "MIN_NET_TARGET_PLANNED_R": config.min_net_target_planned_r,
            "TARGET_R": config.target_r,
            "PROFIT_LOCK_TRIGGER_R": config.breakeven_trigger_r,
            "LOCKED_PROFIT_R": config.locked_profit_r,
            "RISK_FRACTION": config.risk_fraction,
            "COST_RATE": config.cost_rate,
            "MAX_ENTRY_GAP_RISK": config.gap_limit_r,
        }
        for name, value in float_contract.items():
            line = next(
                item for item in source.splitlines() if item.startswith(f"const float {name} = ")
            )
            self.assertAlmostEqual(float(line.rsplit("=", 1)[1].strip()), value)


if __name__ == "__main__":
    unittest.main()
