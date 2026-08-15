"""Chronological holdout, cost-stress, and walk-forward evaluation."""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from .engine import run_backtest
from .metrics import promotion_gate, summarize
from .models import BacktestResult, Bar, StrategyConfig


MILLISECONDS_PER_DAY = 86_400_000


def bars_per_day(config: StrategyConfig) -> int:
    if MILLISECONDS_PER_DAY % config.interval_ms != 0:
        raise ValueError("strategy interval must divide one UTC day exactly")
    return MILLISECONDS_PER_DAY // config.interval_ms


def chronological_splits(length: int) -> dict[str, tuple[int, int]]:
    if length < 3:
        raise ValueError("at least three bars are required")
    train_end = int(length * 0.60)
    validation_end = int(length * 0.80)
    return {
        "train": (0, train_end),
        "validation": (train_end, validation_end),
        "test": (validation_end, length),
    }


def _segment_record(
    bars: Sequence[Bar],
    config: StrategyConfig,
    start: int,
    end: int,
    *,
    validate_data: bool,
) -> tuple[BacktestResult, dict[str, object]]:
    result = run_backtest(
        bars,
        config,
        start_index=start,
        end_index=end,
        validate_data=validate_data,
    )
    metrics = summarize(result)
    metrics.update(
        {
            "start_index": start,
            "end_index_exclusive": end,
            "start_time": bars[start].open_time if start < end else None,
            "end_time": bars[end - 1].close_time if start < end else None,
            "bars": end - start,
            "buy_and_hold_return": (
                bars[end - 1].close / bars[start].open - 1.0 if start < end else None
            ),
        }
    )
    return result, metrics


def walk_forward(
    bars: Sequence[Bar],
    config: StrategyConfig,
    *,
    holdout_days: int = 30,
    initial_train_days: int = 60,
    test_days: int = 30,
    validate_data: bool = False,
) -> list[dict[str, object]]:
    daily_bars = bars_per_day(config)
    holdout_bars = holdout_days * daily_bars
    initial_train = initial_train_days * daily_bars
    test_size = test_days * daily_bars
    pre_holdout_end = max(0, len(bars) - holdout_bars)
    if pre_holdout_end < initial_train + test_size:
        return []
    folds: list[dict[str, object]] = []
    test_start = initial_train
    fold = 1
    while test_start + test_size <= pre_holdout_end:
        test_end = test_start + test_size
        _, metrics = _segment_record(
            bars,
            config,
            test_start,
            test_end,
            validate_data=validate_data,
        )
        metrics["fold"] = fold
        metrics["training_start_index"] = 0
        metrics["training_end_index_exclusive"] = test_start
        folds.append(metrics)
        fold += 1
        test_start += test_size
    return folds


def evaluate_history(
    bars: Sequence[Bar],
    config: StrategyConfig | None = None,
    *,
    validate_data: bool = True,
) -> tuple[dict[str, BacktestResult], dict[str, object]]:
    config = config or StrategyConfig()
    splits = chronological_splits(len(bars))
    results: dict[str, BacktestResult] = {}
    segments: dict[str, dict[str, object]] = {}
    for name, (start, end) in splits.items():
        result, metrics = _segment_record(
            bars, config, start, end, validate_data=validate_data
        )
        results[name] = result
        segments[name] = metrics

    stress_config = replace(config, cost_rate=config.cost_rate * 2.0)
    test_start, test_end = splits["test"]
    stress_result, stress_metrics = _segment_record(
        bars,
        stress_config,
        test_start,
        test_end,
        validate_data=validate_data,
    )
    results["test_doubled_cost"] = stress_result
    folds = walk_forward(bars, config, validate_data=False)
    positive_folds = sum((fold.get("expectancy_r") or 0.0) > 0.0 for fold in folds)
    fold_positive_fraction = positive_folds / len(folds) if folds else None
    gate = promotion_gate(segments["test"], stress_metrics)
    gate_checks = dict(gate["checks"])
    gate_checks["walk_forward_positive_at_least_60pct"] = (
        fold_positive_fraction is not None and fold_positive_fraction >= 0.60
    )
    gate["checks"] = gate_checks
    gate["passed"] = all(gate_checks.values())

    report = {
        "config": config.to_dict(),
        "config_fingerprint": config.fingerprint(),
        "bars": len(bars),
        "data_start": bars[0].open_time if bars else None,
        "data_end": bars[-1].close_time if bars else None,
        "segments": segments,
        "test_doubled_cost": stress_metrics,
        "walk_forward": folds,
        "walk_forward_positive_fraction": fold_positive_fraction,
        "research_promotion_gate": gate,
    }
    return results, report
