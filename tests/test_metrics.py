from __future__ import annotations

import unittest

from shotgun.metrics import (
    bootstrap_mean_interval,
    maximum_drawdown,
    promotion_gate,
    wilson_interval,
)
from shotgun.models import BacktestResult


class MetricTests(unittest.TestCase):
    def test_drawdown_and_wilson_known_values(self):
        cash, fraction = maximum_drawdown([100.0, 120.0, 90.0, 130.0])
        self.assertEqual(cash, 30.0)
        self.assertAlmostEqual(fraction, 0.25)
        low, high = wilson_interval(5, 10)
        self.assertLess(low, 0.5)
        self.assertGreater(high, 0.5)
        self.assertEqual(wilson_interval(0, 0), (None, None))

    def test_summary_drawdown_includes_initial_equity(self):
        from shotgun.metrics import summarize

        result = BacktestResult(
            config_fingerprint="x",
            initial_equity=100.0,
            final_equity=90.0,
            marked_equity=90.0,
            trades=(),
            equity_curve=(90.0,),
        )
        metrics = summarize(result)
        self.assertEqual(metrics["max_drawdown_cash"], 10.0)
        self.assertAlmostEqual(metrics["max_drawdown_fraction"], 0.10)

    def test_bootstrap_is_deterministic(self):
        first = bootstrap_mean_interval([1.0, -1.0, 2.0], samples=100, seed=7)
        second = bootstrap_mean_interval([1.0, -1.0, 2.0], samples=100, seed=7)
        self.assertEqual(first, second)

    def test_promotion_sample_and_stress_requirements_are_hard(self):
        metrics = {
            "trades": 100,
            "expectancy_r": 0.1,
            "profit_factor": 1.2,
            "max_drawdown_fraction": 0.1,
            "top_five_profit_concentration": 0.4,
            "by_side": {"long": {"trades": 70}, "short": {"trades": 30}},
        }
        stress = {"profit_factor": 1.01, "expectancy_r": 0.01}
        self.assertTrue(promotion_gate(metrics, stress)["passed"])
        metrics["by_side"]["short"]["trades"] = 29
        self.assertFalse(promotion_gate(metrics, stress)["passed"])


if __name__ == "__main__":
    unittest.main()
