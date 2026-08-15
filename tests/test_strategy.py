from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import unittest

from shotgun.models import (
    Bar,
    LONG,
    PreparedBar,
    SHORT,
    StrategyConfig,
    config_fingerprint,
)
from shotgun.strategy import (
    evaluate_signals as _evaluate_signals,
    signal_at as _signal_at,
    support_resistance_at,
)


INTERVAL = 300_000
SIGNAL_INDEX = 750
RULE_CONFIG = StrategyConfig(
    interval_ms=INTERVAL,
    ema_fast_length=63,
    ema_slow_length=165,
    ema_regime_length=600,
    atr_length=42,
    rsi_length=42,
    dmi_length=42,
    adx_length=42,
    volume_sma_length=60,
    slope_lookback=15,
    pullback_lookback=24,
    breakout_lookback=9,
    structural_lookback=24,
    min_signal_index=750,
    adx_min=20.0,
    long_rsi_max=70.0,
    short_rsi_min=30.0,
    volume_sma_fraction=0.80,
    max_ema_distance_atr=1.50,
    min_atr_fraction=0.0008,
    max_atr_fraction=0.015,
    min_risk_atr=1.20,
    max_risk_atr=2.50,
    min_price_risk_fraction=0.0,
    max_price_risk_fraction=0.0200,
    min_net_target_planned_r=0.75,
)


def signal_at(bars, prepared, index, config=None):
    return _signal_at(bars, prepared, index, config or RULE_CONFIG)


def evaluate_signals(bars, prepared=None, config=None):
    return _evaluate_signals(bars, prepared, config or RULE_CONFIG)


def _bar(index: int, open_: float, high: float, low: float, close: float, volume=100.0):
    opened = index * INTERVAL
    return Bar(opened, open_, high, low, close, volume, opened + INTERVAL - 1)


def _long_case():
    bars = [
        _bar(i, 100.8, 101.4, 100.6, 101.0)
        for i in range(SIGNAL_INDEX + 1)
    ]
    bars[SIGNAL_INDEX - 4] = _bar(
        SIGNAL_INDEX - 4, 100.8, 101.4, 100.1, 101.0
    )
    bars[SIGNAL_INDEX] = _bar(SIGNAL_INDEX, 101.0, 101.7, 100.8, 101.5)
    prepared = [
        PreparedBar(i, bars[i], 100.0, 95.0, 90.0, 1.0, 60.0, 100.0, 30.0, 10.0, 25.0)
        for i in range(SIGNAL_INDEX + 1)
    ]
    prepared[SIGNAL_INDEX - 15] = replace(
        prepared[SIGNAL_INDEX - 15], ema55=94.0
    )
    return bars, prepared


def _mirror_case():
    bars, rows = _long_case()
    mirrored_bars = [
        Bar(
            item.open_time,
            200.0 - item.open,
            200.0 - item.low,
            200.0 - item.high,
            200.0 - item.close,
            item.volume,
            item.close_time,
        )
        for item in bars
    ]
    mirrored_rows = [
        PreparedBar(
            row.index,
            mirrored_bars[row.index],
            200.0 - float(row.ema21),
            200.0 - float(row.ema55),
            200.0 - float(row.ema200),
            row.atr14,
            100.0 - float(row.rsi14),
            row.volume_sma20,
            row.minus_di14,
            row.plus_di14,
            row.adx14,
        )
        for row in rows
    ]
    return mirrored_bars, mirrored_rows


def _replace_bar(bars, rows, index, **changes):
    changed_bars = list(bars)
    changed_rows = list(rows)
    changed_bars[index] = replace(changed_bars[index], **changes)
    changed_rows[index] = replace(changed_rows[index], bar=changed_bars[index])
    return changed_bars, changed_rows


class SignalRuleTests(unittest.TestCase):
    def test_confirmed_support_and_resistance_use_only_requested_window(self):
        bars = [
            _bar(0, 100.0, 101.0, 99.0, 100.0),
            _bar(1, 100.0, 103.0, 98.0, 101.0),
            _bar(2, 101.0, 102.0, 100.0, 101.5),
        ]
        self.assertEqual(support_resistance_at(bars, 2, 2), (98.0, 103.0))

    def test_exact_qualifying_long_and_locked_risk(self):
        bars, rows = _long_case()
        signal = signal_at(bars, rows, SIGNAL_INDEX)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side, LONG)
        self.assertEqual(signal.time, bars[SIGNAL_INDEX].open_time)
        self.assertAlmostEqual(signal.structural_stop, 100.0)
        self.assertAlmostEqual(signal.risk_distance, 1.5)

    def test_short_is_exact_price_and_indicator_mirror(self):
        long_bars, long_rows = _long_case()
        short_bars, short_rows = _mirror_case()
        long_signal = signal_at(long_bars, long_rows, SIGNAL_INDEX)
        short_signal = signal_at(short_bars, short_rows, SIGNAL_INDEX)
        self.assertEqual(short_signal.side, SHORT)
        self.assertAlmostEqual(short_signal.signal_close, 200.0 - long_signal.signal_close)
        self.assertAlmostEqual(short_signal.structural_stop, 200.0 - long_signal.structural_stop)
        self.assertAlmostEqual(short_signal.risk_distance, long_signal.risk_distance)

    def test_filters_independently_reject_an_almost_identical_long(self):
        base_bars, base_rows = _long_case()
        cases = {}

        rows = list(base_rows)
        rows[SIGNAL_INDEX] = replace(rows[SIGNAL_INDEX], ema200=96.0)
        cases["regime"] = (base_bars, rows)

        rows = list(base_rows)
        rows[SIGNAL_INDEX] = replace(rows[SIGNAL_INDEX], adx14=19.999)
        cases["adx"] = (base_bars, rows)

        rows = list(base_rows)
        rows[SIGNAL_INDEX] = replace(rows[SIGNAL_INDEX], plus_di14=10.0, minus_di14=10.0)
        cases["directional movement"] = (base_bars, rows)

        bars = list(base_bars)
        rows = list(base_rows)
        touch = SIGNAL_INDEX - 4
        bars[touch] = replace(bars[touch], low=100.3)
        rows[touch] = replace(rows[touch], bar=bars[touch])
        cases["pullback touch"] = (bars, rows)

        bars, rows = _replace_bar(
            base_bars,
            base_rows,
            SIGNAL_INDEX - 6,
            low=93.9,
            close=94.0,
        )
        cases["slow trend break"] = (bars, rows)

        bars, rows = _replace_bar(
            base_bars, base_rows, SIGNAL_INDEX, close=101.4
        )
        cases["strict breakout"] = (bars, rows)

        bars, rows = _replace_bar(
            base_bars, base_rows, SIGNAL_INDEX, open=101.5
        )
        cases["bullish candle"] = (bars, rows)

        bars, rows = _replace_bar(
            base_bars, base_rows, SIGNAL_INDEX, open=101.21
        )
        cases["body"] = (bars, rows)

        bars, rows = _replace_bar(
            base_bars, base_rows, SIGNAL_INDEX, high=102.5, low=100.0
        )
        cases["close location"] = (bars, rows)

        rows = list(base_rows)
        rows[SIGNAL_INDEX] = replace(rows[SIGNAL_INDEX], rsi14=51.999)
        cases["RSI"] = (base_bars, rows)

        bars, rows = _replace_bar(
            base_bars, base_rows, SIGNAL_INDEX, volume=79.999
        )
        cases["volume"] = (bars, rows)

        rows = list(base_rows)
        rows[SIGNAL_INDEX] = replace(rows[SIGNAL_INDEX], ema21=99.999)
        cases["EMA distance high"] = (base_bars, rows)

        rows = list(base_rows)
        rows[SIGNAL_INDEX] = replace(rows[SIGNAL_INDEX], ema21=101.501)
        cases["EMA distance negative"] = (base_bars, rows)

        rows = list(base_rows)
        rows[SIGNAL_INDEX] = replace(rows[SIGNAL_INDEX], atr14=0.08)
        cases["ATR fraction"] = (base_bars, rows)

        bars, rows = _replace_bar(
            base_bars,
            base_rows,
            SIGNAL_INDEX - 4,
            low=98.8,
        )
        cases["maximum structural risk"] = (bars, rows)

        for name, (bars, rows) in cases.items():
            with self.subTest(filter=name):
                self.assertIsNone(signal_at(bars, rows, SIGNAL_INDEX))

    def test_level_breakout_mode_does_not_require_fast_ema_touch(self):
        bars, rows = _long_case()
        touch = SIGNAL_INDEX - 4
        bars, rows = _replace_bar(bars, rows, touch, low=100.3)
        self.assertIsNone(signal_at(bars, rows, SIGNAL_INDEX))
        self.assertIsNotNone(
            signal_at(
                bars,
                rows,
                SIGNAL_INDEX,
                replace(RULE_CONFIG, pullback_required=False),
            )
        )

    def test_inclusive_thresholds_and_strict_breakout(self):
        bars, rows = _long_case()
        rows = list(rows)
        rows[SIGNAL_INDEX] = replace(
            rows[SIGNAL_INDEX], adx14=20.0, rsi14=52.0
        )
        self.assertIsNotNone(signal_at(bars, rows, SIGNAL_INDEX))

        bars, rows = _replace_bar(bars, rows, SIGNAL_INDEX, close=101.4)
        self.assertIsNone(signal_at(bars, rows, SIGNAL_INDEX))

    def test_requires_minimum_index_and_all_referenced_values(self):
        config = replace(RULE_CONFIG, min_signal_index=751)
        bars, rows = _long_case()
        self.assertIsNone(signal_at(bars, rows, SIGNAL_INDEX, config))

        rows = list(rows)
        rows[SIGNAL_INDEX - 1] = replace(rows[SIGNAL_INDEX - 1], atr14=None)
        self.assertIsNone(signal_at(bars, rows, SIGNAL_INDEX))

    def test_future_append_and_mutation_cannot_change_prior_signals(self):
        bars, rows = _long_case()
        expected = evaluate_signals(bars, rows)
        future_bar = _bar(SIGNAL_INDEX + 1, 500.0, 510.0, 490.0, 505.0)
        future_row = PreparedBar(
            SIGNAL_INDEX + 1,
            future_bar,
            500.0,
            500.0,
            500.0,
            20.0,
            50.0,
            1.0,
            0.0,
            0.0,
            0.0,
        )
        extended = evaluate_signals(bars + [future_bar], rows + [future_row])
        self.assertEqual(expected, tuple(s for s in extended if s.index <= SIGNAL_INDEX))
        self.assertEqual(
            signal_at(bars, rows, SIGNAL_INDEX),
            signal_at(bars + [future_bar], rows + [future_row], SIGNAL_INDEX),
        )


class ModelContractTests(unittest.TestCase):
    def test_default_profile_is_five_minute_and_cost_aware(self):
        config = StrategyConfig()
        self.assertEqual(config.interval_ms, 300_000)
        self.assertGreaterEqual(config.min_price_risk_fraction, 0.004)
        self.assertTrue(config.pullback_required)

    def test_models_are_frozen(self):
        bar = _bar(0, 100.0, 101.0, 99.0, 100.5)
        with self.assertRaises(FrozenInstanceError):
            bar.close = 42.0

        config = StrategyConfig()
        with self.assertRaises(FrozenInstanceError):
            config.cost_rate = 0.0

    def test_normalized_config_fingerprint_is_sha256_and_parameter_sensitive(self):
        config = StrategyConfig()
        normalized = config.normalized_json()
        self.assertNotIn(" ", normalized)
        self.assertEqual(config_fingerprint(config), sha256(normalized.encode()).hexdigest())
        self.assertEqual(len(config.fingerprint()), 64)
        self.assertNotEqual(
            config.fingerprint(), StrategyConfig(cost_rate=0.0024).fingerprint()
        )

    def test_invalid_bar_and_config_are_rejected(self):
        with self.assertRaises(ValueError):
            _bar(0, 100.0, 99.0, 98.0, 98.5)
        with self.assertRaises(ValueError):
            StrategyConfig(risk_fraction=0.0)
        with self.assertRaises(ValueError):
            StrategyConfig(min_risk_atr=3.0, max_risk_atr=2.5)


if __name__ == "__main__":
    unittest.main()
