from __future__ import annotations

import unittest

from shotgun.evaluation import bars_per_day, chronological_splits
from shotgun.models import StrategyConfig


class EvaluationTests(unittest.TestCase):
    def test_chronological_split_is_disjoint_and_complete(self):
        splits = chronological_splits(1_001)
        self.assertEqual(splits["train"], (0, 600))
        self.assertEqual(splits["validation"], (600, 800))
        self.assertEqual(splits["test"], (800, 1_001))

    def test_too_little_data_is_rejected(self):
        with self.assertRaises(ValueError):
            chronological_splits(2)

    def test_five_minute_calendar_conversion_is_288_bars_per_day(self):
        self.assertEqual(bars_per_day(StrategyConfig()), 288)
        self.assertEqual(180 * bars_per_day(StrategyConfig()), 51_840)


if __name__ == "__main__":
    unittest.main()
