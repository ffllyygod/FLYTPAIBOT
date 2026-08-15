#!/usr/bin/env python3
"""Predeclared development-only comparison for Shotgun 1-minute fallback."""

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
        interval_ms=60_000,
        risk_fraction=0.0020,
        target_r=1.8,
        breakeven_trigger_r=1.0,
        max_hold_bars=60,
        min_trend_exit_bars=5,
        cooldown_bars=15,
        gap_limit_r=0.35,
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
        min_price_risk_fraction=0.0,
        max_price_risk_fraction=0.10,
        min_net_target_planned_r=0.000001,
    )
    micro = StrategyConfig(
        interval_ms=60_000,
        risk_fraction=0.0020,
        target_r=2.4,
        breakeven_trigger_r=1.2,
        max_hold_bars=120,
        min_trend_exit_bars=15,
        cooldown_bars=30,
        gap_limit_r=0.20,
        ema_fast_length=55,
        ema_slow_length=144,
        ema_regime_length=500,
        atr_length=30,
        rsi_length=14,
        dmi_length=14,
        adx_length=14,
        volume_sma_length=30,
        slope_lookback=15,
        pullback_lookback=30,
        breakout_lookback=10,
        structural_lookback=30,
        min_signal_index=650,
        adx_min=25.0,
        long_rsi_min=56.0,
        long_rsi_max=70.0,
        short_rsi_min=30.0,
        short_rsi_max=44.0,
        volume_sma_fraction=1.25,
        slow_break_atr_offset=0.40,
        minimum_body_atr=0.60,
        long_clv_min=0.75,
        short_clv_max=0.25,
        max_ema_distance_atr=2.0,
        min_atr_fraction=0.0002,
        max_atr_fraction=0.003,
        min_risk_atr=5.0,
        max_risk_atr=15.0,
        min_price_risk_fraction=0.0045,
        max_price_risk_fraction=0.0100,
        min_net_target_planned_r=1.0,
    )
    scaled = StrategyConfig(
        interval_ms=60_000,
        risk_fraction=0.0020,
        target_r=2.2,
        breakeven_trigger_r=1.2,
        max_hold_bars=180,
        min_trend_exit_bars=25,
        cooldown_bars=60,
        gap_limit_r=0.20,
        ema_fast_length=105,
        ema_slow_length=275,
        ema_regime_length=1000,
        atr_length=70,
        rsi_length=14,
        dmi_length=14,
        adx_length=14,
        volume_sma_length=50,
        slope_lookback=25,
        pullback_lookback=40,
        breakout_lookback=15,
        structural_lookback=40,
        min_signal_index=1250,
        adx_min=23.0,
        long_rsi_min=55.0,
        long_rsi_max=68.0,
        short_rsi_min=32.0,
        short_rsi_max=45.0,
        volume_sma_fraction=1.15,
        slow_break_atr_offset=0.40,
        minimum_body_atr=0.55,
        long_clv_min=0.75,
        short_clv_max=0.25,
        max_ema_distance_atr=2.0,
        min_atr_fraction=0.0002,
        max_atr_fraction=0.003,
        min_risk_atr=6.0,
        max_risk_atr=18.0,
        min_price_risk_fraction=0.0045,
        max_price_risk_fraction=0.0100,
        min_net_target_planned_r=0.90,
    )
    level_break = StrategyConfig(
        interval_ms=60_000,
        pullback_required=False,
        risk_fraction=0.0020,
        target_r=2.5,
        breakeven_trigger_r=1.3,
        max_hold_bars=150,
        min_trend_exit_bars=20,
        cooldown_bars=45,
        gap_limit_r=0.20,
        ema_fast_length=100,
        ema_slow_length=300,
        ema_regime_length=900,
        atr_length=60,
        rsi_length=21,
        dmi_length=21,
        adx_length=21,
        volume_sma_length=50,
        slope_lookback=30,
        pullback_lookback=60,
        breakout_lookback=20,
        structural_lookback=60,
        min_signal_index=1100,
        adx_min=24.0,
        long_rsi_min=57.0,
        long_rsi_max=72.0,
        short_rsi_min=28.0,
        short_rsi_max=43.0,
        volume_sma_fraction=1.40,
        slow_break_atr_offset=0.45,
        minimum_body_atr=0.70,
        long_clv_min=0.80,
        short_clv_max=0.20,
        max_ema_distance_atr=2.25,
        min_atr_fraction=0.0002,
        max_atr_fraction=0.003,
        min_risk_atr=6.0,
        max_risk_atr=20.0,
        min_price_risk_fraction=0.0045,
        max_price_risk_fraction=0.0100,
        min_net_target_planned_r=1.10,
    )
    return {
        "c0_literal_1m_control": control,
        "h1_micro_cost_aware": micro,
        "h2_scaled_5m_context": scaled,
        "h3_structural_level_break": level_break,
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
        description="Compare frozen 1m hypotheses without reading the final 20% test."
    )
    parser.add_argument("data", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("reports/shotgun-1m-development.json")
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
        "contract": "development-only; final 20% not loaded into candidate runs",
        "data_provenance": read_cache_metadata(args.data),
        "full_bar_count": len(bars),
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
