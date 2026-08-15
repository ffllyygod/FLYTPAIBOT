"""Performance metrics that emphasize expectancy, risk, and uncertainty."""

from __future__ import annotations

import math
import random
import statistics
from typing import Iterable

from .models import BacktestResult, LONG, SHORT, Trade


def _safe_mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def wilson_interval(wins: int, total: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if total <= 0:
        return None, None
    p = wins / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denominator
    margin = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def bootstrap_mean_interval(
    values: Iterable[float],
    *,
    samples: int = 2_000,
    seed: int = 20260721,
    confidence: float = 0.95,
) -> tuple[float | None, float | None]:
    data = tuple(values)
    if not data:
        return None, None
    if samples <= 0 or not 0.0 < confidence < 1.0:
        raise ValueError("invalid bootstrap settings")
    rng = random.Random(seed)
    means = sorted(
        statistics.fmean(data[rng.randrange(len(data))] for _ in data)
        for _ in range(samples)
    )
    tail = (1.0 - confidence) / 2.0
    lower = means[max(0, int(tail * samples))]
    upper = means[min(samples - 1, int((1.0 - tail) * samples) - 1)]
    return lower, upper


def maximum_drawdown(equity_curve: Iterable[float]) -> tuple[float, float]:
    peak: float | None = None
    max_cash = 0.0
    max_fraction = 0.0
    for equity in equity_curve:
        if peak is None or equity > peak:
            peak = equity
        if peak and peak > 0.0:
            cash = peak - equity
            fraction = cash / peak
            max_cash = max(max_cash, cash)
            max_fraction = max(max_fraction, fraction)
    return max_cash, max_fraction


def _max_losing_streak(trades: tuple[Trade, ...]) -> int:
    current = maximum = 0
    for trade in trades:
        if trade.net_pnl < 0.0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def summarize(result: BacktestResult) -> dict[str, object]:
    trades = result.trades
    winners = [trade for trade in trades if trade.net_pnl > 0.0]
    losers = [trade for trade in trades if trade.net_pnl < 0.0]
    scratch = len(trades) - len(winners) - len(losers)
    gross_profit = sum(trade.net_pnl for trade in winners)
    gross_loss = -sum(trade.net_pnl for trade in losers)
    profit_factor = gross_profit / gross_loss if gross_loss > 0.0 else None
    mean_win = _safe_mean([trade.net_pnl for trade in winners])
    mean_loss = _safe_mean([-trade.net_pnl for trade in losers])
    payoff = mean_win / mean_loss if mean_win is not None and mean_loss else None
    win_low, win_high = wilson_interval(len(winners), len(trades))
    r_values = [trade.r_multiple for trade in trades]
    bootstrap_low, bootstrap_high = bootstrap_mean_interval(r_values)
    drawdown_cash, drawdown_fraction = maximum_drawdown(
        (result.initial_equity, *result.equity_curve)
    )
    marked = result.marked_equity if result.marked_equity is not None else result.final_equity
    positive_pnl = sorted((trade.net_pnl for trade in winners), reverse=True)
    top_five = sum(positive_pnl[:5])
    concentration = top_five / gross_profit if gross_profit > 0.0 else None
    bars_observed = len(result.equity_curve)
    held_bars = sum(trade.bars_held for trade in trades)
    if result.open_position is not None:
        held_bars += result.open_position.bars_held

    by_side: dict[str, dict[str, object]] = {}
    for side in (LONG, SHORT):
        side_trades = [trade for trade in trades if trade.side == side]
        side_wins = [trade for trade in side_trades if trade.net_pnl > 0.0]
        by_side[side] = {
            "trades": len(side_trades),
            "win_rate": len(side_wins) / len(side_trades) if side_trades else None,
            "net_pnl": sum(trade.net_pnl for trade in side_trades),
            "expectancy_r": _safe_mean([trade.r_multiple for trade in side_trades]),
        }

    return {
        "initial_equity": result.initial_equity,
        "final_realized_equity": result.final_equity,
        "final_marked_equity": marked,
        "net_return": marked / result.initial_equity - 1.0,
        "trades": len(trades),
        "wins": len(winners),
        "losses": len(losers),
        "scratch": scratch,
        "win_rate": len(winners) / len(trades) if trades else None,
        "win_rate_wilson_95": [win_low, win_high],
        "profit_factor": profit_factor,
        "payoff_ratio": payoff,
        "expectancy_r": _safe_mean(r_values),
        "median_r": statistics.median(r_values) if r_values else None,
        "bootstrap_mean_r_95": [bootstrap_low, bootstrap_high],
        "max_drawdown_cash": drawdown_cash,
        "max_drawdown_fraction": drawdown_fraction,
        "max_losing_streak": _max_losing_streak(trades),
        "average_holding_bars": _safe_mean([float(trade.bars_held) for trade in trades]),
        "exposure_fraction": min(1.0, held_bars / bars_observed) if bars_observed else 0.0,
        "total_costs": sum(trade.fees for trade in trades)
        + (result.open_position.entry_fee if result.open_position else 0.0),
        "ambiguous_trades": sum(trade.ambiguous_bar for trade in trades),
        "profit_locked_trades": sum(trade.cost_covered_before_exit for trade in trades),
        "profit_locked_negative_gap_exits": sum(
            trade.cost_covered_before_exit and trade.net_pnl < -1e-8 for trade in trades
        ),
        "top_five_profit_concentration": concentration,
        "signals": len(result.signals),
        "skipped_gap_signals": result.skipped_gap_signals,
        "open_position": result.open_position is not None,
        "by_side": by_side,
        "config_fingerprint": result.config_fingerprint,
    }


def promotion_gate(metrics: dict[str, object], stress_metrics: dict[str, object] | None = None) -> dict[str, object]:
    by_side = metrics.get("by_side") or {}
    long_count = int((by_side.get(LONG) or {}).get("trades", 0))
    short_count = int((by_side.get(SHORT) or {}).get("trades", 0))
    checks = {
        "at_least_100_trades": int(metrics.get("trades", 0)) >= 100,
        "at_least_30_longs": long_count >= 30,
        "at_least_30_shorts": short_count >= 30,
        "positive_expectancy": (metrics.get("expectancy_r") or 0.0) > 0.0,
        "profit_factor_at_least_1_15": (metrics.get("profit_factor") or 0.0) >= 1.15,
        "max_drawdown_at_most_20pct": float(metrics.get("max_drawdown_fraction", 1.0)) <= 0.20,
        "top_five_concentration_at_most_50pct": (
            metrics.get("top_five_profit_concentration") is not None
            and float(metrics["top_five_profit_concentration"]) <= 0.50
        ),
    }
    if stress_metrics is not None:
        checks["doubled_cost_profit_factor_at_least_1"] = (
            stress_metrics.get("profit_factor") is not None
            and float(stress_metrics["profit_factor"]) >= 1.0
        )
        checks["doubled_cost_positive_expectancy"] = (
            stress_metrics.get("expectancy_r") is not None
            and float(stress_metrics["expectancy_r"]) > 0.0
        )
    return {"passed": all(checks.values()), "checks": checks}
