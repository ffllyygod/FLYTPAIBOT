"""The frozen Shotgun v2 completed-bar signal rules."""

from __future__ import annotations

from typing import Sequence

from .indicators import close_location_value, prepare_bars
from .models import Bar, LONG, PreparedBar, SHORT, Signal, StrategyConfig


def support_resistance_at(
    bars: Sequence[Bar], index: int, lookback: int
) -> tuple[float, float]:
    """Return confirmed rolling support/resistance through ``index``."""

    if not 0 <= index < len(bars):
        raise IndexError("level index is outside the supplied bars")
    if lookback <= 0:
        raise ValueError("level lookback must be positive")
    start = max(0, index - lookback + 1)
    window = bars[start : index + 1]
    return min(bar.low for bar in window), max(bar.high for bar in window)


def _net_target_is_viable(
    side: str,
    signal_close: float,
    risk_distance: float,
    config: StrategyConfig,
) -> bool:
    """Reject setups whose modeled reward is consumed by round-trip costs."""

    direction = 1.0 if side == LONG else -1.0
    target_price = signal_close + direction * config.target_r * risk_distance
    net_target_per_unit = (
        config.target_r * risk_distance
        - config.cost_rate * (signal_close + target_price)
    )
    planned_risk_per_unit = risk_distance + 2.0 * signal_close * config.cost_rate
    return (
        net_target_per_unit / planned_risk_per_unit
        >= config.min_net_target_planned_r
    )


def _defined(row: PreparedBar) -> bool:
    return all(
        value is not None
        for value in (
            row.ema21,
            row.ema55,
            row.ema200,
            row.atr14,
            row.rsi14,
            row.volume_sma20,
            row.plus_di14,
            row.minus_di14,
            row.adx14,
        )
    )


def _make_signal(
    index: int,
    side: str,
    bar: Bar,
    atr_value: float,
    structural_stop: float,
    risk_distance: float,
) -> Signal:
    return Signal(
        index=index,
        time=bar.open_time,
        side=side,
        signal_close=bar.close,
        risk_distance=risk_distance,
        atr=atr_value,
        structural_stop=structural_stop,
    )


def signal_at(
    bars: Sequence[Bar],
    prepared: Sequence[PreparedBar],
    index: int,
    config: StrategyConfig | None = None,
) -> Signal | None:
    """Evaluate one completed bar without reading any later array element."""

    config = config or StrategyConfig()
    if len(bars) != len(prepared):
        raise ValueError("bars and prepared rows must have equal lengths")
    if not 0 <= index < len(bars):
        raise IndexError("signal index is outside the supplied bars")
    required_history = max(
        config.min_signal_index,
        config.slope_lookback,
        config.pullback_lookback,
        config.breakout_lookback,
        config.structural_lookback - 1,
    )
    if index < required_history:
        return None

    current = prepared[index]
    if current.index != index or current.bar != bars[index] or not _defined(current):
        return None

    history_start = index - max(
        config.slope_lookback,
        config.pullback_lookback,
        config.breakout_lookback,
        config.structural_lookback - 1,
    )
    for row_index in range(history_start, index):
        if prepared[row_index].index != row_index or prepared[row_index].bar != bars[row_index]:
            return None

    # Type narrowing after the explicit defined check.
    ema_fast = float(current.ema21)
    ema_slow = float(current.ema55)
    ema_regime = float(current.ema200)
    atr_value = float(current.atr14)
    rsi_value = float(current.rsi14)
    volume_average = float(current.volume_sma20)
    plus_di = float(current.plus_di14)
    minus_di = float(current.minus_di14)
    adx_value = float(current.adx14)
    bar = bars[index]
    if atr_value <= 0.0 or bar.close <= 0.0:
        return None

    pullback_start = index - config.pullback_lookback
    pullback = range(pullback_start, index)
    if any(
        prepared[j].ema21 is None
        or prepared[j].ema55 is None
        or prepared[j].atr14 is None
        for j in pullback
    ):
        return None

    previous_high = max(
        bars[j].high for j in range(index - config.breakout_lookback, index)
    )
    previous_low = min(
        bars[j].low for j in range(index - config.breakout_lookback, index)
    )
    clv = close_location_value(bar)
    body = abs(bar.close - bar.open)
    atr_fraction = atr_value / bar.close
    slow_slope_row = prepared[index - config.slope_lookback]
    if slow_slope_row.ema55 is None:
        return None
    slow_past = float(slow_slope_row.ema55)

    common = (
        adx_value >= config.adx_min
        and body >= config.minimum_body_atr * atr_value
        and bar.volume >= config.volume_sma_fraction * volume_average
        and config.min_atr_fraction <= atr_fraction <= config.max_atr_fraction
    )
    if not common:
        return None

    long_regime = (
        bar.close > ema_regime
        and ema_fast > ema_slow > ema_regime
        and ema_slow > slow_past
    )
    long_pullback = (not config.pullback_required) or (any(
        bars[j].low
        <= float(prepared[j].ema21) + config.pullback_atr_offset * float(prepared[j].atr14)
        for j in pullback
    ) and all(
        bars[j].close
        >= float(prepared[j].ema55) - config.slow_break_atr_offset * float(prepared[j].atr14)
        for j in pullback
    ))
    long_distance = bar.close - ema_fast
    long_resumption = (
        bar.close > previous_high
        and bar.close > bar.open
        and clv >= config.long_clv_min
    )
    long_momentum = (
        config.long_rsi_min <= rsi_value <= config.long_rsi_max
        and plus_di > minus_di
    )
    long_quality = 0.0 <= long_distance <= config.max_ema_distance_atr * atr_value
    if long_regime and long_pullback and long_resumption and long_momentum and long_quality:
        structural_start = index - config.structural_lookback + 1
        structural_stop = (
            min(bars[j].low for j in range(structural_start, index + 1))
            - config.structural_stop_atr * atr_value
        )
        risk_distance = max(
            config.min_risk_atr * atr_value,
            config.min_price_risk_fraction * bar.close,
            bar.close - structural_stop,
        )
        if (
            risk_distance <= config.max_risk_atr * atr_value
            and risk_distance <= config.max_price_risk_fraction * bar.close
            and _net_target_is_viable(LONG, bar.close, risk_distance, config)
        ):
            return _make_signal(
                index, LONG, bar, atr_value, structural_stop, risk_distance
            )

    short_regime = (
        bar.close < ema_regime
        and ema_fast < ema_slow < ema_regime
        and ema_slow < slow_past
    )
    short_pullback = (not config.pullback_required) or (any(
        bars[j].high
        >= float(prepared[j].ema21) - config.pullback_atr_offset * float(prepared[j].atr14)
        for j in pullback
    ) and all(
        bars[j].close
        <= float(prepared[j].ema55) + config.slow_break_atr_offset * float(prepared[j].atr14)
        for j in pullback
    ))
    short_distance = ema_fast - bar.close
    short_resumption = (
        bar.close < previous_low
        and bar.close < bar.open
        and clv <= config.short_clv_max
    )
    short_momentum = (
        config.short_rsi_min <= rsi_value <= config.short_rsi_max
        and minus_di > plus_di
    )
    short_quality = 0.0 <= short_distance <= config.max_ema_distance_atr * atr_value
    if short_regime and short_pullback and short_resumption and short_momentum and short_quality:
        structural_start = index - config.structural_lookback + 1
        structural_stop = (
            max(bars[j].high for j in range(structural_start, index + 1))
            + config.structural_stop_atr * atr_value
        )
        risk_distance = max(
            config.min_risk_atr * atr_value,
            config.min_price_risk_fraction * bar.close,
            structural_stop - bar.close,
        )
        if (
            risk_distance <= config.max_risk_atr * atr_value
            and risk_distance <= config.max_price_risk_fraction * bar.close
            and _net_target_is_viable(SHORT, bar.close, risk_distance, config)
        ):
            return _make_signal(
                index, SHORT, bar, atr_value, structural_stop, risk_distance
            )
    return None


def evaluate_signals(
    bars: Sequence[Bar],
    prepared: Sequence[PreparedBar] | None = None,
    config: StrategyConfig | None = None,
) -> tuple[Signal, ...]:
    config = config or StrategyConfig()
    prepared = prepare_bars(bars, config) if prepared is None else prepared
    return tuple(
        signal
        for index in range(len(bars))
        if (signal := signal_at(bars, prepared, index, config)) is not None
    )


def generate_signals(
    bars: Sequence[Bar], config: StrategyConfig | None = None
) -> tuple[Signal, ...]:
    return evaluate_signals(bars, config=config)
