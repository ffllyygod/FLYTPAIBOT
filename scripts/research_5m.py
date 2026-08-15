#!/usr/bin/env python3
"""Predeclared development-only comparison for Shotgun 5-minute hypotheses."""

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
    control = StrategyConfig(
        interval_ms=300_000,
        risk_fraction=0.005,
        target_r=1.8,
        breakeven_trigger_r=1.0,
        max_hold_bars=48,
        min_trend_exit_bars=3,
        cooldown_bars=8,
        gap_limit_r=0.5,
        ema_fast_length=21,
        ema_slow_length=55,
        ema_regime_length=200,
        atr_length=14,
        rsi_length=14,
        dmi_length=14,
        adx_length=14,
        volume_sma_length=20,
        slope_lookback=5,
        pullback_lookback=8,
        breakout_lookback=3,
        structural_lookback=8,
        min_signal_index=250,
        adx_min=20.0,
        volume_sma_fraction=0.80,
        max_ema_distance_atr=1.50,
        min_atr_fraction=0.0008,
        max_atr_fraction=0.015,
        min_risk_atr=1.20,
        max_risk_atr=2.50,
        min_price_risk_fraction=0.0,
        max_price_risk_fraction=0.10,
        min_net_target_planned_r=0.000001,
    )
    fast = replace(
        control,
        risk_fraction=0.0025,
        breakeven_trigger_r=0.8,
        max_hold_bars=36,
        cooldown_bars=12,
        gap_limit_r=0.35,
        adx_min=22.0,
        volume_sma_fraction=1.0,
        min_atr_fraction=0.0006,
        max_atr_fraction=0.008,
        min_risk_atr=1.5,
        max_risk_atr=3.0,
        min_price_risk_fraction=0.0040,
        max_price_risk_fraction=0.0100,
        min_net_target_planned_r=0.75,
    )
    balanced = StrategyConfig(
        risk_fraction=0.0025,
        target_r=2.0,
        breakeven_trigger_r=1.0,
        max_hold_bars=36,
        min_trend_exit_bars=6,
        cooldown_bars=12,
        gap_limit_r=0.30,
        ema_fast_length=34,
        ema_slow_length=89,
        ema_regime_length=300,
        atr_length=21,
        rsi_length=14,
        dmi_length=14,
        adx_length=14,
        volume_sma_length=20,
        slope_lookback=8,
        pullback_lookback=12,
        breakout_lookback=5,
        structural_lookback=12,
        min_signal_index=400,
        adx_min=22.0,
        long_rsi_min=54.0,
        long_rsi_max=68.0,
        short_rsi_min=32.0,
        short_rsi_max=46.0,
        volume_sma_fraction=1.10,
        slow_break_atr_offset=0.40,
        minimum_body_atr=0.45,
        long_clv_min=0.72,
        short_clv_max=0.28,
        min_atr_fraction=0.0004,
        max_atr_fraction=0.006,
        min_risk_atr=1.75,
        max_risk_atr=3.5,
        min_price_risk_fraction=0.0045,
        max_price_risk_fraction=0.0100,
        min_net_target_planned_r=0.85,
    )
    scaled = StrategyConfig(
        risk_fraction=0.0025,
        target_r=2.2,
        breakeven_trigger_r=1.2,
        max_hold_bars=36,
        min_trend_exit_bars=9,
        cooldown_bars=12,
        gap_limit_r=0.25,
        ema_fast_length=63,
        ema_slow_length=165,
        ema_regime_length=600,
        atr_length=42,
        rsi_length=14,
        dmi_length=14,
        adx_length=14,
        volume_sma_length=20,
        slope_lookback=15,
        pullback_lookback=12,
        breakout_lookback=5,
        structural_lookback=12,
        min_signal_index=750,
        adx_min=23.0,
        long_rsi_min=55.0,
        long_rsi_max=68.0,
        short_rsi_min=32.0,
        short_rsi_max=45.0,
        volume_sma_fraction=1.10,
        slow_break_atr_offset=0.35,
        minimum_body_atr=0.45,
        long_clv_min=0.72,
        short_clv_max=0.28,
        min_atr_fraction=0.0004,
        max_atr_fraction=0.006,
        min_risk_atr=2.0,
        max_risk_atr=4.0,
        min_price_risk_fraction=0.0045,
        max_price_risk_fraction=0.0100,
        min_net_target_planned_r=0.90,
    )
    return {
        "c0_literal_5m_control": control,
        "h1_fast_cost_aware": fast,
        "h2_balanced_structure": balanced,
        "h3_scaled_trend_pullback": scaled,
    }


def compact_metrics(result) -> dict[str, object]:
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
        description="Compare frozen 5m hypotheses without reading the final 20% test."
    )
    parser.add_argument("data", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("reports/shotgun-5m-development.json")
    )
    args = parser.parse_args(argv)
    bars = load_cache(
        args.data,
        drop_incomplete=True,
        require_metadata=True,
        expected_symbol="BTCUSDT",
        expected_interval="5m",
    )
    train_range = chronological_splits(len(bars))
    development_end = train_range["validation"][1]
    development_bars = bars[:development_end]
    train_start, train_end = train_range["train"]
    validation_start, validation_end = train_range["validation"]
    report: dict[str, object] = {
        "contract": "development-only; final 20% not loaded into candidate runs",
        "data_provenance": read_cache_metadata(args.data),
        "full_bar_count": len(bars),
        "development_bar_count": len(development_bars),
        "untouched_test_start_index": development_end,
        "candidates": {},
    }
    for name, config in candidates().items():
        train = run_backtest(
            development_bars,
            config,
            start_index=train_start,
            end_index=train_end,
        )
        validation = run_backtest(
            development_bars,
            config,
            start_index=validation_start,
            end_index=validation_end,
        )
        stress = run_backtest(
            development_bars,
            replace(config, cost_rate=0.0018),
            start_index=validation_start,
            end_index=validation_end,
        )
        train_metrics = compact_metrics(train)
        validation_metrics = compact_metrics(validation)
        stress_metrics = compact_metrics(stress)
        checks = {
            "train_positive_expectancy": (train_metrics["expectancy_r"] or 0.0) > 0,
            "validation_at_least_50_trades": validation_metrics["trades"] >= 50,
            "validation_positive_expectancy": (validation_metrics["expectancy_r"] or 0.0) > 0,
            "validation_profit_factor_at_least_1_15": (validation_metrics["profit_factor"] or 0.0) >= 1.15,
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
            f"{name}: train E={train_metrics['expectancy_r']} "
            f"validation trades={validation_metrics['trades']} "
            f"E={validation_metrics['expectancy_r']} "
            f"PF={validation_metrics['profit_factor']} "
            f"stress E={stress_metrics['expectancy_r']} "
            f"gate={'PASS' if all(checks.values()) else 'FAIL'}"
        )
    write_json(args.output, report)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
