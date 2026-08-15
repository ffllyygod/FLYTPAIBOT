"""Deterministic event-driven execution for the frozen Shotgun strategy."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Sequence

from .data import validate_bars
from .indicators import prepare_bars
from .models import (
    BacktestResult,
    Bar,
    LONG,
    Position,
    SHORT,
    Signal,
    StrategyConfig,
    Trade,
)
from .strategy import signal_at


CollisionPolicy = Literal["conservative", "tv_path", "optimistic"]


@dataclass(frozen=True, slots=True)
class _PendingEntry:
    signal: Signal
    quantity: float
    planned_risk_cash: float


def _signal_size(signal: Signal, equity: float, config: StrategyConfig) -> tuple[float, float]:
    cost_allowance = 2.0 * signal.signal_close * config.cost_rate
    cash_per_unit = signal.risk_distance + cost_allowance
    risk_budget = equity * config.risk_fraction
    risk_quantity = risk_budget / cash_per_unit
    exposure_quantity = equity / signal.signal_close
    quantity = min(risk_quantity, exposure_quantity)
    planned_risk_cash = quantity * cash_per_unit
    return quantity, planned_risk_cash


def _new_position(pending: _PendingEntry, bar: Bar, index: int, config: StrategyConfig) -> Position:
    signal = pending.signal
    if signal.side == LONG:
        stop = bar.open - signal.risk_distance
        target = bar.open + config.target_r * signal.risk_distance
    else:
        stop = bar.open + signal.risk_distance
        target = bar.open - config.target_r * signal.risk_distance
    return Position(
        signal=signal,
        entry_index=index,
        entry_time=bar.open_time,
        entry_price=bar.open,
        initial_stop_price=stop,
        stop_price=stop,
        target_price=target,
        quantity=pending.quantity,
        planned_risk_cash=pending.planned_risk_cash,
        entry_fee=bar.open * pending.quantity * config.cost_rate,
    )


def _close_position(
    position: Position,
    *,
    exit_price: float,
    exit_index: int,
    exit_time: int,
    reason: str,
    ambiguous: bool,
    config: StrategyConfig,
) -> Trade:
    direction = 1.0 if position.side == LONG else -1.0
    gross = direction * (exit_price - position.entry_price) * position.quantity
    exit_fee = exit_price * position.quantity * config.cost_rate
    net = gross - position.entry_fee - exit_fee
    return Trade(
        signal_index=position.signal.index,
        signal_time=position.signal.time,
        entry_index=position.entry_index,
        entry_time=position.entry_time,
        exit_index=exit_index,
        exit_time=exit_time,
        side=position.side,
        signal_price=position.signal.signal_close,
        entry_price=position.entry_price,
        exit_price=exit_price,
        initial_stop_price=position.initial_stop_price,
        stop_price=position.stop_price,
        target_price=position.target_price,
        quantity=position.quantity,
        planned_risk_cash=position.planned_risk_cash,
        entry_fee=position.entry_fee,
        exit_fee=exit_fee,
        gross_pnl=gross,
        net_pnl=net,
        r_multiple=net / position.planned_risk_cash,
        maximum_favorable_excursion=position.maximum_favorable_excursion,
        maximum_adverse_excursion=position.maximum_adverse_excursion,
        bars_held=position.bars_held,
        exit_reason=reason,
        ambiguous_bar=ambiguous,
        cost_covered_before_exit=position.cost_covered,
    )


def _opening_bracket_fill(position: Position, bar: Bar) -> tuple[float, str] | None:
    if position.side == LONG:
        if bar.open <= position.stop_price:
            return bar.open, "profit_locked_gap" if position.cost_covered else "stop_gap"
        if bar.open >= position.target_price:
            return position.target_price, "target"
    else:
        if bar.open >= position.stop_price:
            return bar.open, "profit_locked_gap" if position.cost_covered else "stop_gap"
        if bar.open <= position.target_price:
            return position.target_price, "target"
    return None


def _intrabar_bracket_fill(
    position: Position, bar: Bar, policy: CollisionPolicy
) -> tuple[float, str, bool] | None:
    if position.side == LONG:
        stop_hit = bar.low <= position.stop_price
        target_hit = bar.high >= position.target_price
    else:
        stop_hit = bar.high >= position.stop_price
        target_hit = bar.low <= position.target_price
    if not stop_hit and not target_hit:
        return None
    ambiguous = stop_hit and target_hit
    if ambiguous:
        if policy == "conservative":
            choose_stop = True
        elif policy == "optimistic":
            choose_stop = False
        else:
            high_first = abs(bar.open - bar.high) < abs(bar.open - bar.low)
            choose_stop = high_first if position.side == SHORT else not high_first
        if choose_stop:
            return (
                position.stop_price,
                "profit_locked_stop" if position.cost_covered else "stop",
                True,
            )
        return position.target_price, "target", True
    if stop_hit:
        return (
            position.stop_price,
            "profit_locked_stop" if position.cost_covered else "stop",
            False,
        )
    return position.target_price, "target", False


def _update_excursions(position: Position, bar: Bar) -> Position:
    if position.side == LONG:
        favorable = max(0.0, bar.high - position.entry_price)
        adverse = max(0.0, position.entry_price - bar.low)
    else:
        favorable = max(0.0, position.entry_price - bar.low)
        adverse = max(0.0, bar.high - position.entry_price)
    return replace(
        position,
        maximum_favorable_excursion=max(position.maximum_favorable_excursion, favorable),
        maximum_adverse_excursion=max(position.maximum_adverse_excursion, adverse),
    )


def _update_excursion_at_price(position: Position, price: float) -> Position:
    """Record only movement known to have occurred by an exit fill."""

    direction = 1.0 if position.side == LONG else -1.0
    movement = direction * (price - position.entry_price)
    if movement >= 0.0:
        return replace(
            position,
            maximum_favorable_excursion=max(
                position.maximum_favorable_excursion, movement
            ),
        )
    return replace(
        position,
        maximum_adverse_excursion=max(
            position.maximum_adverse_excursion, -movement
        ),
    )


def _marked_equity(equity: float, position: Position | None, close: float, cost_rate: float) -> float:
    if position is None:
        return equity
    direction = 1.0 if position.side == LONG else -1.0
    unrealized = direction * (close - position.entry_price) * position.quantity
    estimated_exit_fee = close * position.quantity * cost_rate
    return equity + unrealized - estimated_exit_fee


def _cost_covered_stop(position: Position, config: StrategyConfig) -> float:
    """Return the fee-covered, profit-locked price before market-gap risk."""

    planned_risk_per_unit = (
        position.signal.risk_distance
        + 2.0 * position.signal.signal_close * config.cost_rate
    )
    locked_per_unit = config.locked_profit_r * planned_risk_per_unit
    if position.side == LONG:
        return (
            position.entry_price * (1.0 + config.cost_rate) + locked_per_unit
        ) / (1.0 - config.cost_rate)
    return (
        position.entry_price * (1.0 - config.cost_rate) - locked_per_unit
    ) / (1.0 + config.cost_rate)


def run_backtest(
    bars: Sequence[Bar],
    config: StrategyConfig | None = None,
    *,
    start_index: int = 0,
    end_index: int | None = None,
    collision_policy: CollisionPolicy = "conservative",
    validate_data: bool = True,
) -> BacktestResult:
    """Run one flat/reset chronological segment over ``[start_index, end_index)``.

    Bars before ``start_index`` are indicator warm-up only. Positions and pending
    entries never cross a segment boundary.
    """

    config = config or StrategyConfig()
    if collision_policy not in ("conservative", "tv_path", "optimistic"):
        raise ValueError(f"unsupported collision policy: {collision_policy}")
    if end_index is None:
        end_index = len(bars)
    if not 0 <= start_index <= end_index <= len(bars):
        raise ValueError("invalid backtest segment")
    if validate_data:
        validate_bars(bars, interval_ms=config.interval_ms)
    prepared = prepare_bars(bars, config)

    equity = config.initial_equity
    position: Position | None = None
    pending: _PendingEntry | None = None
    queued_exit: str | None = None
    last_exit_index: int | None = None
    skipped_gap_signals = 0
    trades: list[Trade] = []
    signals: list[Signal] = []
    equity_curve: list[float] = []

    for index in range(start_index, end_index):
        bar = bars[index]

        # Existing brackets remain live overnight and outrank a queued market exit.
        if position is not None:
            opening_fill = _opening_bracket_fill(position, bar)
            if opening_fill is not None:
                price, reason = opening_fill
                position = _update_excursion_at_price(position, price)
                trade = _close_position(
                    position,
                    exit_price=price,
                    exit_index=index,
                    exit_time=bar.open_time,
                    reason=reason,
                    ambiguous=False,
                    config=config,
                )
                equity += trade.gross_pnl - trade.exit_fee
                trades.append(trade)
                position = None
                queued_exit = None
                last_exit_index = index
            elif queued_exit is not None:
                position = _update_excursion_at_price(position, bar.open)
                trade = _close_position(
                    position,
                    exit_price=bar.open,
                    exit_index=index,
                    exit_time=bar.open_time,
                    reason=queued_exit,
                    ambiguous=False,
                    config=config,
                )
                equity += trade.gross_pnl - trade.exit_fee
                trades.append(trade)
                position = None
                queued_exit = None
                last_exit_index = index

        if pending is not None and position is None:
            if index != pending.signal.index + 1:
                pending = None
            elif abs(bar.open - pending.signal.signal_close) > (
                config.gap_limit_r * pending.signal.risk_distance
            ):
                skipped_gap_signals += 1
                pending = None
            else:
                position = _new_position(pending, bar, index, config)
                equity -= position.entry_fee
                pending = None

        if position is not None:
            position = replace(position, bars_held=position.bars_held + 1)
            bracket_fill = _intrabar_bracket_fill(position, bar, collision_policy)
            if bracket_fill is not None:
                price, reason, ambiguous = bracket_fill
                position = _update_excursion_at_price(position, price)
                trade = _close_position(
                    position,
                    exit_price=price,
                    exit_index=index,
                    exit_time=bar.close_time,
                    reason=reason,
                    ambiguous=ambiguous,
                    config=config,
                )
                equity += trade.gross_pnl - trade.exit_fee
                trades.append(trade)
                position = None
                queued_exit = None
                last_exit_index = index
            else:
                position = _update_excursions(position, bar)
                ema55 = prepared[index].ema55
                direction = 1.0 if position.side == LONG else -1.0
                close_progress_r = (
                    direction * (bar.close - position.entry_price)
                    / position.signal.risk_distance
                )
                if (
                    not position.cost_covered
                    and close_progress_r >= config.breakeven_trigger_r
                ):
                    covered_stop = _cost_covered_stop(position, config)
                    position = replace(
                        position,
                        stop_price=(
                            max(position.stop_price, covered_stop)
                            if position.side == LONG
                            else min(position.stop_price, covered_stop)
                        ),
                        cost_covered=True,
                        cost_covered_index=index,
                    )
                if position.bars_held >= config.max_hold_bars:
                    queued_exit = "time"
                elif (
                    config.trend_exit_enabled
                    and position.bars_held >= config.min_trend_exit_bars
                    and ema55 is not None
                    and (
                        (position.side == LONG and bar.close < ema55)
                        or (position.side == SHORT and bar.close > ema55)
                    )
                ):
                    queued_exit = "trend"

        cooldown_clear = (
            last_exit_index is None
            or index >= last_exit_index + config.cooldown_bars + 1
        )
        if position is None and pending is None and cooldown_clear:
            signal = signal_at(bars, prepared, index, config)
            if signal is not None:
                quantity, planned_risk = _signal_size(signal, equity, config)
                if quantity > 0.0:
                    signals.append(signal)
                    pending = _PendingEntry(signal, quantity, planned_risk)

        equity_curve.append(_marked_equity(equity, position, bar.close, config.cost_rate))

    marked = equity_curve[-1] if equity_curve else equity
    return BacktestResult(
        config_fingerprint=config.fingerprint(),
        initial_equity=config.initial_equity,
        final_equity=equity,
        marked_equity=marked,
        trades=tuple(trades),
        signals=tuple(signals),
        open_position=position,
        skipped_gap_signals=skipped_gap_signals,
        equity_curve=tuple(equity_curve),
    )


backtest = run_backtest
