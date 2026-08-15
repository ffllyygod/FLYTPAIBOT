from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from shotgun.engine import run_backtest
from shotgun.models import Bar, LONG, SHORT, Signal, StrategyConfig


INTERVAL = 300_000


def bar(index: int, open_: float, high: float, low: float, close: float) -> Bar:
    return Bar(
        open_time=index * INTERVAL,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=10.0,
        close_time=(index + 1) * INTERVAL - 1,
    )


def long_signal(index: int, close: float = 100.0, risk: float = 1.0) -> Signal:
    return Signal(index, index * INTERVAL, LONG, close, risk, 1.0, close - risk)


def short_signal(index: int, close: float = 100.0, risk: float = 1.0) -> Signal:
    return Signal(index, index * INTERVAL, SHORT, close, risk, 1.0, close + risk)


class EngineTests(unittest.TestCase):
    def test_default_engine_accepts_5m_grid_and_rejects_1m_grid(self):
        five_minute = [bar(i, 100, 101, 99, 100) for i in range(3)]
        self.assertEqual(run_backtest(five_minute).trades, ())
        one_minute = [
            Bar(i * 60_000, 100, 101, 99, 100, 10, (i + 1) * 60_000 - 1)
            for i in range(3)
        ]
        with self.assertRaisesRegex(ValueError, "duration|aligned|gap"):
            run_backtest(one_minute)

    def run_with_signals(self, bars, signal_indexes, **config_values):
        config = StrategyConfig(
            min_signal_index=0,
            cost_rate=config_values.pop("cost_rate", 0.0),
            risk_fraction=config_values.pop("risk_fraction", 0.005),
            target_r=config_values.pop("target_r", 1.8),
            breakeven_trigger_r=config_values.pop("breakeven_trigger_r", 1.0),
            max_hold_bars=config_values.pop("max_hold_bars", 48),
            min_trend_exit_bars=config_values.pop("min_trend_exit_bars", 3),
            cooldown_bars=config_values.pop("cooldown_bars", 8),
            gap_limit_r=config_values.pop("gap_limit_r", 0.5),
            **config_values,
        )
        rows = [SimpleNamespace(ema55=0.0) for _ in bars]

        def fake_signal(_bars, _prepared, index, _config):
            return long_signal(index, _bars[index].close) if index in signal_indexes else None

        with (
            patch("shotgun.engine.prepare_bars", return_value=rows),
            patch("shotgun.engine.signal_at", side_effect=fake_signal),
        ):
            return run_backtest(bars, config, validate_data=False)

    def test_next_open_entry_and_entry_bar_target(self):
        bars = [bar(0, 100, 101, 99, 100), bar(1, 100, 102, 99.5, 101)]
        result = self.run_with_signals(bars, {0})
        trade = result.trades[0]
        self.assertEqual(trade.entry_index, 1)
        self.assertEqual(trade.entry_price, 100)
        self.assertAlmostEqual(trade.exit_price, 101.8)
        self.assertEqual(trade.exit_reason, "target")
        self.assertEqual(trade.bars_held, 1)
        self.assertAlmostEqual(trade.r_multiple, 1.8)
        self.assertAlmostEqual(trade.quantity, 50.0)
        self.assertAlmostEqual(trade.planned_risk_cash, 50.0)
        self.assertAlmostEqual(trade.maximum_favorable_excursion, 1.8)

    def test_conservative_collision_is_stop_first(self):
        bars = [bar(0, 100, 101, 99, 100), bar(1, 100, 102, 98.5, 100)]
        result = self.run_with_signals(bars, {0})
        trade = result.trades[0]
        self.assertEqual(trade.exit_reason, "stop")
        self.assertEqual(trade.exit_price, 99)
        self.assertTrue(trade.ambiguous_bar)
        self.assertAlmostEqual(trade.r_multiple, -1.0)

    def test_excessive_gap_skips_pending_entry(self):
        bars = [bar(0, 100, 101, 99, 100), bar(1, 101, 102, 100, 101)]
        result = self.run_with_signals(bars, {0})
        self.assertEqual(result.trades, ())
        self.assertIsNone(result.open_position)
        self.assertEqual(result.skipped_gap_signals, 1)

    def test_bracket_gap_precedes_queued_trend_exit(self):
        bars = [
            bar(0, 100, 101, 99, 100),
            bar(1, 100, 100.5, 99.5, 100),
            bar(2, 100, 100.5, 99.5, 100),
            bar(3, 100, 100.5, 99.5, 100),
            bar(4, 98, 99, 97.5, 98.5),
        ]
        config = StrategyConfig(min_signal_index=0, cost_rate=0.0)
        rows = [SimpleNamespace(ema55=101.0) for _ in bars]
        with (
            patch("shotgun.engine.prepare_bars", return_value=rows),
            patch(
                "shotgun.engine.signal_at",
                side_effect=lambda _b, _p, i, _c: long_signal(0) if i == 0 else None,
            ),
        ):
            result = run_backtest(bars, config, validate_data=False)
        trade = result.trades[0]
        self.assertEqual(trade.exit_index, 4)
        self.assertEqual(trade.exit_reason, "stop_gap")
        self.assertEqual(trade.exit_price, 98)
        self.assertEqual(trade.maximum_adverse_excursion, 2.0)

    def test_ordinary_trend_exit_and_time_has_bar_48_precedence(self):
        bars = [bar(i, 100, 100.5, 99.5, 100) for i in range(6)]
        config = StrategyConfig(
            min_signal_index=0,
            cost_rate=0.0,
            max_hold_bars=3,
            min_trend_exit_bars=3,
        )
        rows = [SimpleNamespace(ema55=101.0) for _ in bars]
        with (
            patch("shotgun.engine.prepare_bars", return_value=rows),
            patch(
                "shotgun.engine.signal_at",
                side_effect=lambda _b, _p, i, _c: long_signal(0, risk=5.0) if i == 0 else None,
            ),
        ):
            result = run_backtest(bars, config, validate_data=False)
        self.assertEqual(result.trades[0].exit_reason, "time")
        self.assertEqual(result.trades[0].exit_index, 4)

        config = StrategyConfig(
            min_signal_index=0,
            cost_rate=0.0,
            max_hold_bars=10,
            min_trend_exit_bars=3,
        )
        with (
            patch("shotgun.engine.prepare_bars", return_value=rows),
            patch(
                "shotgun.engine.signal_at",
                side_effect=lambda _b, _p, i, _c: long_signal(0, risk=5.0) if i == 0 else None,
            ),
        ):
            result = run_backtest(bars, config, validate_data=False)
        self.assertEqual(result.trades[0].exit_reason, "trend")

    def test_favorable_target_gap_fills_at_target_not_better_open(self):
        bars = [
            bar(0, 100, 101, 99, 100),
            bar(1, 100, 101, 99.5, 100),
            bar(2, 103, 104, 102, 103),
        ]
        result = self.run_with_signals(bars, {0})
        trade = result.trades[0]
        self.assertEqual(trade.exit_reason, "target")
        self.assertEqual(trade.exit_price, 101.8)

    def test_short_entry_gap_and_profit_lock_are_mirrored(self):
        bars = [
            bar(0, 100, 101, 99, 100),
            bar(1, 100, 100.5, 98.9, 98.99),
            bar(2, 99.5, 99.8, 99.2, 99.5),
        ]
        config = StrategyConfig(
            min_signal_index=0,
            cost_rate=0.0012,
            target_r=1.8,
            breakeven_trigger_r=1.0,
            min_trend_exit_bars=3,
        )
        rows = [SimpleNamespace(ema55=200.0) for _ in bars]
        with (
            patch("shotgun.engine.prepare_bars", return_value=rows),
            patch(
                "shotgun.engine.signal_at",
                side_effect=lambda _b, _p, i, _c: short_signal(0) if i == 0 else None,
            ),
        ):
            result = run_backtest(bars, config, validate_data=False)
        trade = result.trades[0]
        self.assertEqual(trade.side, SHORT)
        self.assertEqual(trade.exit_reason, "profit_locked_stop")
        self.assertAlmostEqual(trade.r_multiple, 0.10, places=9)

    def test_closed_trade_prefix_is_invariant_to_appended_future_bars(self):
        prefix = [bar(0, 100, 101, 99, 100), bar(1, 100, 102, 99.5, 101)]
        future = [bar(i, 100, 101, 99, 100) for i in range(2, 8)]
        first = self.run_with_signals(prefix, {0})
        second = self.run_with_signals(prefix + future, {0})
        self.assertEqual(first.trades, second.trades)

    def test_time_exit_and_cooldown_boundaries(self):
        bars = [bar(i, 100, 100.4, 99.6, 100) for i in range(8)]
        time_result = self.run_with_signals(
            bars, {0}, max_hold_bars=3, cooldown_bars=0
        )
        self.assertEqual(time_result.trades[0].exit_reason, "time")
        self.assertEqual(time_result.trades[0].exit_index, 4)
        self.assertEqual(time_result.trades[0].bars_held, 3)

        target_bars = [
            bar(0, 100, 101, 99, 100),
            bar(1, 100, 102, 99.5, 101),
            bar(2, 100, 101, 99, 100),
            bar(3, 100, 101, 99, 100),
            bar(4, 100, 101, 99, 100),
            bar(5, 100, 102, 99.5, 101),
        ]
        cooldown_result = self.run_with_signals(
            target_bars, {0, 1, 2, 3, 4}, cooldown_bars=2
        )
        self.assertEqual([signal.index for signal in cooldown_result.signals], [0, 4])
        self.assertEqual(len(cooldown_result.trades), 2)

    def test_open_position_is_marked_but_not_force_closed(self):
        bars = [bar(0, 100, 101, 99, 100), bar(1, 100, 100.5, 99.5, 100.25)]
        result = self.run_with_signals(bars, {0}, cost_rate=0.0012)
        self.assertEqual(result.trades, ())
        self.assertIsNotNone(result.open_position)
        self.assertGreater(result.marked_equity, result.final_equity)

    def test_confirmed_profit_locked_stop_is_positive_after_fees(self):
        bars = [
            bar(0, 100, 101, 99, 100),
            bar(1, 100, 101.1, 99.5, 101.01),
            bar(2, 100.5, 100.6, 100.1, 100.3),
        ]
        result = self.run_with_signals(bars, {0}, cost_rate=0.0012)
        trade = result.trades[0]
        self.assertEqual(trade.exit_reason, "profit_locked_stop")
        self.assertTrue(trade.cost_covered_before_exit)
        self.assertEqual(trade.initial_stop_price, 99.0)
        self.assertGreater(trade.stop_price, trade.entry_price)
        self.assertGreater(trade.net_pnl, 0.0)
        self.assertAlmostEqual(trade.r_multiple, 0.10, places=9)

    def test_profit_locked_state_still_discloses_gap_loss(self):
        bars = [
            bar(0, 100, 101, 99, 100),
            bar(1, 100, 101.1, 99.5, 101.01),
            bar(2, 99, 99.5, 98.5, 99),
        ]
        result = self.run_with_signals(bars, {0}, cost_rate=0.0012)
        trade = result.trades[0]
        self.assertEqual(trade.exit_reason, "profit_locked_gap")
        self.assertTrue(trade.cost_covered_before_exit)
        self.assertLess(trade.net_pnl, 0.0)


if __name__ == "__main__":
    unittest.main()
