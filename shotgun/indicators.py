"""Dependency-free, Pine-compatible indicator calculations."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from typing import Sequence

from .models import Bar, PreparedBar, StrategyConfig


Number = float | int
MaybeNumber = Number | None


def _validate_length(length: int) -> None:
    if length <= 0:
        raise ValueError("indicator length must be positive")


def _as_optional_floats(values: Sequence[MaybeNumber]) -> list[float | None]:
    result: list[float | None] = []
    for value in values:
        if value is None:
            result.append(None)
            continue
        converted = float(value)
        if not math.isfinite(converted):
            raise ValueError("indicator sources must be finite or None")
        result.append(converted)
    return result


def sma(values: Sequence[MaybeNumber], length: int) -> list[float | None]:
    """Simple moving average, undefined unless the entire window is valid."""

    _validate_length(length)
    source = _as_optional_floats(values)
    result: list[float | None] = [None] * len(source)
    window: deque[float | None] = deque()
    total = 0.0
    invalid = 0
    for index, value in enumerate(source):
        window.append(value)
        if value is None:
            invalid += 1
        else:
            total += value
        if len(window) > length:
            removed = window.popleft()
            if removed is None:
                invalid -= 1
            else:
                total -= removed
        if len(window) == length and invalid == 0:
            result[index] = total / length
    return result


def ema(values: Sequence[MaybeNumber], length: int) -> list[float | None]:
    """EMA seeded with the first valid source value."""

    _validate_length(length)
    source = _as_optional_floats(values)
    result: list[float | None] = [None] * len(source)
    alpha = 2.0 / (length + 1.0)
    previous: float | None = None
    for index, value in enumerate(source):
        if value is None:
            continue
        previous = value if previous is None else alpha * value + (1.0 - alpha) * previous
        result[index] = previous
    return result


def rma(values: Sequence[MaybeNumber], length: int) -> list[float | None]:
    """Wilder average seeded by the first ``length`` valid source values.

    Leading invalid values are skipped when collecting the seed.  An invalid
    value after seeding is undefined at that index but does not erase state.
    This is what lets ADX seed from the first valid DX rather than array zero.
    """

    _validate_length(length)
    source = _as_optional_floats(values)
    result: list[float | None] = [None] * len(source)
    seed: list[float] = []
    previous: float | None = None
    for index, value in enumerate(source):
        if value is None:
            continue
        if previous is None:
            seed.append(value)
            if len(seed) == length:
                previous = sum(seed) / length
                result[index] = previous
            continue
        previous = (previous * (length - 1) + value) / length
        result[index] = previous
    return result


def true_range(bars: Sequence[Bar]) -> list[float]:
    result: list[float] = []
    for index, bar in enumerate(bars):
        if index == 0:
            result.append(bar.high - bar.low)
        else:
            previous_close = bars[index - 1].close
            result.append(
                max(
                    bar.high - bar.low,
                    abs(bar.high - previous_close),
                    abs(bar.low - previous_close),
                )
            )
    return result


def atr(bars: Sequence[Bar], length: int = 14) -> list[float | None]:
    return rma(true_range(bars), length)


def rsi(values: Sequence[Number], length: int = 14) -> list[float | None]:
    """Wilder RSI whose seed begins with the first close-to-close change."""

    _validate_length(length)
    closes = _as_optional_floats(values)
    if any(value is None for value in closes):
        raise ValueError("RSI close values cannot be None")
    gains: list[float | None] = [None]
    losses: list[float | None] = [None]
    for index in range(1, len(closes)):
        # The None check above makes these values concrete floats.
        change = float(closes[index]) - float(closes[index - 1])
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = rma(gains, length)
    average_loss = rma(losses, length)
    result: list[float | None] = [None] * len(closes)
    for index, (gain, loss) in enumerate(zip(average_gain, average_loss)):
        if gain is None or loss is None:
            continue
        if gain == 0.0 and loss == 0.0:
            result[index] = 50.0
        elif loss == 0.0:
            result[index] = 100.0
        elif gain == 0.0:
            result[index] = 0.0
        else:
            result[index] = 100.0 - 100.0 / (1.0 + gain / loss)
    return result


@dataclass(frozen=True, slots=True)
class DMIResult:
    plus_di: tuple[float | None, ...]
    minus_di: tuple[float | None, ...]
    adx: tuple[float | None, ...]

    def __iter__(self):
        yield self.plus_di
        yield self.minus_di
        yield self.adx


def dmi(
    bars: Sequence[Bar], length: int = 14, adx_length: int | None = None
) -> DMIResult:
    """Wilder +DI, -DI, and ADX with explicit warm-up values."""

    _validate_length(length)
    if adx_length is None:
        adx_length = length
    _validate_length(adx_length)
    directional_up: list[float] = [0.0] * len(bars)
    directional_down: list[float] = [0.0] * len(bars)
    for index in range(1, len(bars)):
        up = bars[index].high - bars[index - 1].high
        down = bars[index - 1].low - bars[index].low
        directional_up[index] = up if up > down and up > 0.0 else 0.0
        directional_down[index] = down if down > up and down > 0.0 else 0.0

    smoothed_tr = rma(true_range(bars), length)
    smoothed_up = rma(directional_up, length)
    smoothed_down = rma(directional_down, length)
    plus_di: list[float | None] = [None] * len(bars)
    minus_di: list[float | None] = [None] * len(bars)
    dx: list[float | None] = [None] * len(bars)
    for index, (tr_value, up_value, down_value) in enumerate(
        zip(smoothed_tr, smoothed_up, smoothed_down)
    ):
        if tr_value is None or up_value is None or down_value is None:
            continue
        if tr_value == 0.0:
            plus_value = 0.0
            minus_value = 0.0
        else:
            plus_value = 100.0 * up_value / tr_value
            minus_value = 100.0 * down_value / tr_value
        plus_di[index] = plus_value
        minus_di[index] = minus_value
        denominator = plus_value + minus_value
        dx[index] = (
            0.0
            if denominator == 0.0
            else 100.0 * abs(plus_value - minus_value) / denominator
        )
    adx_values = rma(dx, adx_length)
    return DMIResult(tuple(plus_di), tuple(minus_di), tuple(adx_values))


def close_location_value(bar: Bar) -> float:
    spread = bar.high - bar.low
    return 0.5 if spread == 0.0 else (bar.close - bar.low) / spread


def prepare_bars(
    bars: Sequence[Bar], config: StrategyConfig | None = None
) -> tuple[PreparedBar, ...]:
    """Calculate the complete frozen-v1 indicator row for every bar."""

    config = config or StrategyConfig()
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars]
    ema_fast = ema(closes, config.ema_fast_length)
    ema_slow = ema(closes, config.ema_slow_length)
    ema_regime = ema(closes, config.ema_regime_length)
    atr_values = atr(bars, config.atr_length)
    rsi_values = rsi(closes, config.rsi_length)
    volume_average = sma(volumes, config.volume_sma_length)
    directional = dmi(bars, config.dmi_length, config.adx_length)

    return tuple(
        PreparedBar(
            index=index,
            bar=bar,
            ema21=ema_fast[index],
            ema55=ema_slow[index],
            ema200=ema_regime[index],
            atr14=atr_values[index],
            rsi14=rsi_values[index],
            volume_sma20=volume_average[index],
            plus_di14=directional.plus_di[index],
            minus_di14=directional.minus_di[index],
            adx14=directional.adx[index],
        )
        for index, bar in enumerate(bars)
    )

