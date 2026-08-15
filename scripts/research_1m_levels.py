#!/usr/bin/env python3
"""Second and final development pass: repeated 1m structural-level hypotheses."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shotgun.data import load_cache, read_cache_metadata  # noqa: E402
from shotgun.engine import run_backtest  # noqa: E402
from shotgun.evaluation import chronological_splits  # noqa: E402
from shotgun.metrics import summarize  # noqa: E402
from shotgun.models import StrategyConfig  # noqa: E402
from shotgun.report import write_json  # noqa: E402


def candidates() -> dict[str, StrategyConfig]:
    shared = StrategyConfig(
        interval_ms=60_000,
        pullback_required=False,
        risk_fraction=0.0020,
        target_r=2.2,
        breakeven_trigger_r=1.1,
        max_hold_bars=120,
        min_trend_exit_bars=12,
        cooldown_bars=30,
        gap_limit_r=0.20,
        atr_length=30,
        rsi_length=14,
        dmi_length=14,
        adx_length=14,
        volume_sma_length=30,
        min_signal_index=750,
        adx_min=18.0,
        long_rsi_min=52.0,
        long_rsi_max=74.0,
        short_rsi_min=26.0,
        short_rsi_max=48.0,
        volume_sma_fraction=1.0,
        slow_break_atr_offset=0.50,
        minimum_body_atr=0.40,
        long_clv_min=0.65,
        short_clv_max=0.35,
        max_ema_distance_atr=2.5,
        min_atr_fraction=0.0001,
        max_atr_fraction=0.004,
        min_risk_atr=3.0,
        max_risk_atr=25.0,
        min_price_risk_fraction=0.0040,
        max_price_risk_fraction=0.0120,
        min_net_target_planned_r=0.80,
    )
    repeated_break = replace(
        shared,
        ema_fast_length=55,
        ema_slow_length=200,
        ema_regime_length=600,
        slope_lookback=20,
        pullback_lookback=30,
        breakout_lookback=15,
        structural_lookback=60,
    )
    impulse_break = replace(
        shared,
        target_r=2.4,
        ema_fast_length=34,
        ema_slow_length=144,
        ema_regime_length=500,
        slope_lookback=15,
        pullback_lookback=20,
        breakout_lookback=8,
        structural_lookback=30,
        volume_sma_fraction=1.25,
        minimum_body_atr=0.60,
        long_clv_min=0.75,
        short_clv_max=0.25,
    )
    retest = replace(
        shared,
        pullback_required=True,
        ema_fast_length=55,
        ema_slow_length=144,
        ema_regime_length=500,
        slope_lookback=15,
        pullback_lookback=60,
        breakout_lookback=5,
        structural_lookback=30,
        volume_sma_fraction=0.90,
        minimum_body_atr=0.30,
    )
    return {
        "l1_repeated_structure_break": repeated_break,
        "l2_high_volume_impulse_break": impulse_break,
        "l3_trend_level_retest": retest,
    }


def compact(result) -> dict[str, object]:
    metrics = summarize(result)
    return {
        key: metrics[key]
        for key in (
            "trades",
            "win_rate",
            "net_return",
            "profit_factor",
            "expectancy_r",
            "max_drawdown_fraction",
            "bootstrap_mean_r_95",
            "by_side",
            "top_five_profit_concentration",
        )
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Final development-only 1m support/resistance hypothesis pass."
    )
    parser.add_argument("data", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("reports/shotgun-1m-levels-development.json")
    )
    args = parser.parse_args(argv)
    bars = load_cache(
        args.data,
        drop_incomplete=True,
        require_metadata=True,
        expected_symbol="BTCUSDT",
        expected_interval="1m",
    )
    ranges = chronological_splits(len(bars))
    development_end = ranges["validation"][1]
    development = bars[:development_end]
    report: dict[str, object] = {
        "contract": "final concept-driven development pass; final 20% not loaded",
        "data_provenance": read_cache_metadata(args.data),
        "development_bar_count": len(development),
        "untouched_test_start_index": development_end,
        "candidates": {},
    }
    for name, config in candidates().items():
        train = run_backtest(
            development, config, start_index=ranges["train"][0], end_index=ranges["train"][1]
        )
        validation = run_backtest(
            development,
            config,
            start_index=ranges["validation"][0],
            end_index=ranges["validation"][1],
        )
        stress = run_backtest(
            development,
            replace(config, cost_rate=0.0018),
            start_index=ranges["validation"][0],
            end_index=ranges["validation"][1],
        )
        train_metrics = compact(train)
        validation_metrics = compact(validation)
        stress_metrics = compact(stress)
        checks = {
            "train_positive_expectancy": (train_metrics["expectancy_r"] or 0.0) > 0,
            "validation_at_least_75_trades": validation_metrics["trades"] >= 75,
            "validation_positive_expectancy": (validation_metrics["expectancy_r"] or 0.0) > 0,
            "validation_profit_factor_at_least_1_20": (validation_metrics["profit_factor"] or 0.0) >= 1.20,
            "validation_both_sides_positive": all(
                ((validation_metrics["by_side"][side]["expectancy_r"] or 0.0) > 0)
                for side in ("long", "short")
            ),
            "stress_positive_expectancy": (stress_metrics["expectancy_r"] or 0.0) > 0,
        }
        report["candidates"][name] = {
            "config": config.to_dict(),
            "fingerprint": config.fingerprint(),
            "train": train_metrics,
            "validation": validation_metrics,
            "validation_cost_0_18pct_per_fill": stress_metrics,
            "development_gate": {"passed": all(checks.values()), "checks": checks},
        }
        print(
            f"{name}: train trades={train_metrics['trades']} E={train_metrics['expectancy_r']} "
            f"validation trades={validation_metrics['trades']} E={validation_metrics['expectancy_r']} "
            f"PF={validation_metrics['profit_factor']} stress E={stress_metrics['expectancy_r']} "
            f"gate={'PASS' if all(checks.values()) else 'FAIL'}"
        )
    write_json(args.output, report)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
