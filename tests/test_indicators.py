from __future__ import annotations

import math
import unittest

from shotgun.indicators import atr, dmi, ema, prepare_bars, rma, rsi, sma, true_range
from shotgun.models import Bar, StrategyConfig


INTERVAL = 300_000


def bar(index: int, open_: float, high: float, low: float, close: float) -> Bar:
    opened = index * INTERVAL
    return Bar(opened, open_, high, low, close, 100.0, opened + INTERVAL - 1)


class MovingAverageTests(unittest.TestCase):
    def assertOptionalAlmostEqual(self, actual, expected, places=12):
        self.assertEqual(len(actual), len(expected))
        for observed, wanted in zip(actual, expected):
            if wanted is None:
                self.assertIsNone(observed)
            else:
                self.assertIsNotNone(observed)
                self.assertAlmostEqual(observed, wanted, places=places)

    def test_sma_has_full_window_warmup(self):
        self.assertOptionalAlmostEqual(
            sma([1.0, 2.0, 3.0, 4.0], 3), [None, None, 2.0, 3.0]
        )
        self.assertOptionalAlmostEqual(
            sma([1.0, None, 3.0, 4.0], 2), [None, None, None, 3.5]
        )

    def test_ema_is_seeded_with_first_source_value(self):
        self.assertOptionalAlmostEqual(
            ema([1.0, 2.0, 3.0, 4.0], 3), [1.0, 1.5, 2.25, 3.125]
        )
        self.assertOptionalAlmostEqual(
            ema([None, 2.0, 4.0], 3), [None, 2.0, 3.0]
        )

    def test_rma_seeds_with_first_length_valid_values(self):
        self.assertOptionalAlmostEqual(
            rma([1.0, 2.0, 3.0, 4.0, 5.0], 3),
            [None, None, 2.0, 8.0 / 3.0, 31.0 / 9.0],
        )
        self.assertOptionalAlmostEqual(
            rma([None, 1.0, 2.0, 3.0], 3), [None, None, None, 2.0]
        )

    def test_bad_lengths_and_nonfinite_sources_are_rejected(self):
        for function in (sma, ema, rma):
            with self.subTest(function=function.__name__):
                with self.assertRaises(ValueError):
                    function([1.0], 0)
                with self.assertRaises(ValueError):
                    function([math.nan], 1)


class WilderIndicatorTests(unittest.TestCase):
    def test_true_range_and_atr_include_gap_from_previous_close(self):
        bars = (
            bar(0, 9.5, 10.0, 9.0, 9.5),
            bar(1, 11.0, 12.0, 10.5, 11.5),
            bar(2, 10.5, 11.0, 10.0, 10.5),
        )
        self.assertEqual(true_range(bars), [1.0, 2.5, 1.5])
        values = atr(bars, 2)
        self.assertIsNone(values[0])
        self.assertAlmostEqual(values[1], 1.75)
        self.assertAlmostEqual(values[2], 1.625)

    def test_rsi_warmup_and_zero_cases_are_exact(self):
        rising = rsi([1.0, 2.0, 3.0, 4.0, 5.0], 3)
        falling = rsi([5.0, 4.0, 3.0, 2.0, 1.0], 3)
        flat = rsi([2.0, 2.0, 2.0, 2.0, 2.0], 3)
        self.assertEqual(rising[:3], [None, None, None])
        self.assertEqual(rising[3:], [100.0, 100.0])
        self.assertEqual(falling[3:], [0.0, 0.0])
        self.assertEqual(flat[3:], [50.0, 50.0])

    def test_dmi_direction_and_double_wilder_warmup(self):
        rising_bars = tuple(
            bar(i, 10.0 + i, 11.0 + i, 9.0 + i, 10.5 + i) for i in range(6)
        )
        result = dmi(rising_bars, length=3, adx_length=3)
        self.assertEqual(result.plus_di[:2], (None, None))
        self.assertEqual(result.minus_di[:2], (None, None))
        self.assertAlmostEqual(result.plus_di[2], 100.0 / 3.0)
        self.assertEqual(result.minus_di[2], 0.0)
        self.assertEqual(result.adx[:4], (None, None, None, None))
        self.assertAlmostEqual(result.adx[4], 100.0)

    def test_flat_dmi_has_zero_dx_and_zero_adx(self):
        flat_bars = tuple(bar(i, 10.0, 11.0, 9.0, 10.0) for i in range(6))
        result = dmi(flat_bars, length=3, adx_length=3)
        self.assertEqual(result.plus_di[2], 0.0)
        self.assertEqual(result.minus_di[2], 0.0)
        self.assertEqual(result.adx[4], 0.0)


class PreparedRowsTests(unittest.TestCase):
    def test_prepared_rows_have_exact_indicator_warmups(self):
        bars = tuple(
            bar(i, 99.5 + i, 101.0 + i, 99.0 + i, 100.0 + i)
            for i in range(8)
        )
        config = StrategyConfig(
            ema_fast_length=2,
            ema_slow_length=3,
            ema_regime_length=4,
            atr_length=3,
            rsi_length=3,
            dmi_length=3,
            adx_length=3,
            volume_sma_length=3,
        )
        rows = prepare_bars(bars, config)
        self.assertEqual(tuple(row.index for row in rows), tuple(range(8)))
        self.assertEqual(rows[0].ema21, 100.0)
        self.assertIsNone(rows[1].atr14)
        self.assertIsNotNone(rows[2].atr14)
        self.assertIsNone(rows[2].rsi14)
        self.assertEqual(rows[3].rsi14, 100.0)
        self.assertIsNone(rows[3].adx14)
        self.assertEqual(rows[4].adx14, 100.0)
        self.assertEqual(rows[2].volume_sma20, 100.0)

    def test_appending_future_bars_cannot_change_indicator_prefix(self):
        prefix = tuple(
            bar(i, 100.0 + i / 10.0, 101.0 + i / 10.0, 99.0 + i / 10.0, 100.5 + i / 10.0)
            for i in range(40)
        )
        future = tuple(
            bar(i, 1000.0 + i, 1002.0 + i, 999.0 + i, 1001.0 + i)
            for i in range(40, 48)
        )
        prefix_rows = prepare_bars(prefix)
        extended_rows = prepare_bars(prefix + future)
        self.assertEqual(prefix_rows, extended_rows[: len(prefix)])


if __name__ == "__main__":
    unittest.main()
