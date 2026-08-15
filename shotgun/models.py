"""Immutable domain models shared by the Shotgun reference implementation.

The models deliberately contain no exchange or I/O concerns.  Timestamps are
Unix milliseconds and prices/quantities are expressed in quote/base units as
appropriate for BTCUSDT.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from typing import Any


LONG = "long"
SHORT = "short"
SIDES = frozenset((LONG, SHORT))


def _require_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


@dataclass(frozen=True, slots=True)
class Bar:
    """One completed OHLCV candle; timestamps are Unix milliseconds."""

    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int

    def __post_init__(self) -> None:
        if self.open_time < 0 or self.close_time < self.open_time:
            raise ValueError("bar timestamps are invalid")
        for name in ("open", "high", "low", "close", "volume"):
            _require_finite(name, getattr(self, name))
        if self.low > self.high:
            raise ValueError("bar low cannot exceed high")
        if not self.low <= self.open <= self.high:
            raise ValueError("bar open must be within the high/low range")
        if not self.low <= self.close <= self.high:
            raise ValueError("bar close must be within the high/low range")
        if self.volume < 0:
            raise ValueError("bar volume cannot be negative")

    @property
    def open_time_ms(self) -> int:
        return self.open_time

    @property
    def close_time_ms(self) -> int:
        return self.close_time

    @property
    def timestamp_ms(self) -> int:
        return self.open_time


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """Frozen v2 five-minute signal, execution, and reporting parameters."""

    initial_equity: float = 10_000.0
    risk_fraction: float = 0.0025
    cost_rate: float = 0.0012
    target_r: float = 1.8
    breakeven_trigger_r: float = 0.8
    locked_profit_r: float = 0.10
    max_hold_bars: int = 36
    min_trend_exit_bars: int = 3
    trend_exit_enabled: bool = True
    pullback_required: bool = True
    cooldown_bars: int = 12
    gap_limit_r: float = 0.35
    interval_ms: int = 5 * 60 * 1000

    ema_fast_length: int = 21
    ema_slow_length: int = 55
    ema_regime_length: int = 200
    atr_length: int = 14
    rsi_length: int = 14
    dmi_length: int = 14
    adx_length: int = 14
    volume_sma_length: int = 20
    slope_lookback: int = 5
    pullback_lookback: int = 8
    breakout_lookback: int = 3
    structural_lookback: int = 8
    min_signal_index: int = 250

    adx_min: float = 22.0
    long_rsi_min: float = 52.0
    long_rsi_max: float = 70.0
    short_rsi_min: float = 30.0
    short_rsi_max: float = 48.0
    volume_sma_fraction: float = 1.0
    pullback_atr_offset: float = 0.20
    slow_break_atr_offset: float = 0.50
    minimum_body_atr: float = 0.30
    long_clv_min: float = 0.65
    short_clv_max: float = 0.35
    max_ema_distance_atr: float = 1.50
    min_atr_fraction: float = 0.0006
    max_atr_fraction: float = 0.008
    structural_stop_atr: float = 0.10
    min_risk_atr: float = 1.5
    max_risk_atr: float = 3.0
    min_price_risk_fraction: float = 0.0040
    max_price_risk_fraction: float = 0.0100
    min_net_target_planned_r: float = 0.75

    def __post_init__(self) -> None:
        positive_floats = (
            "initial_equity",
            "risk_fraction",
            "target_r",
            "breakeven_trigger_r",
            "gap_limit_r",
            "volume_sma_fraction",
            "minimum_body_atr",
            "max_ema_distance_atr",
            "min_atr_fraction",
            "max_atr_fraction",
            "min_risk_atr",
            "max_risk_atr",
            "max_price_risk_fraction",
            "min_net_target_planned_r",
        )
        for name in positive_floats:
            value = getattr(self, name)
            _require_finite(name, value)
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        nonnegative_floats = (
            "cost_rate",
            "adx_min",
            "pullback_atr_offset",
            "slow_break_atr_offset",
            "structural_stop_atr",
            "locked_profit_r",
            "min_price_risk_fraction",
        )
        for name in nonnegative_floats:
            value = getattr(self, name)
            _require_finite(name, value)
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        integer_lengths = (
            "interval_ms",
            "ema_fast_length",
            "ema_slow_length",
            "ema_regime_length",
            "atr_length",
            "rsi_length",
            "dmi_length",
            "adx_length",
            "volume_sma_length",
            "slope_lookback",
            "pullback_lookback",
            "breakout_lookback",
            "structural_lookback",
            "max_hold_bars",
            "min_trend_exit_bars",
        )
        for name in integer_lengths:
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.cooldown_bars < 0 or self.min_signal_index < 0:
            raise ValueError("cooldown_bars and min_signal_index cannot be negative")
        bounded = (
            ("long_rsi_min", self.long_rsi_min, 0.0, 100.0),
            ("long_rsi_max", self.long_rsi_max, 0.0, 100.0),
            ("short_rsi_min", self.short_rsi_min, 0.0, 100.0),
            ("short_rsi_max", self.short_rsi_max, 0.0, 100.0),
            ("long_clv_min", self.long_clv_min, 0.0, 1.0),
            ("short_clv_max", self.short_clv_max, 0.0, 1.0),
        )
        for name, value, lower, upper in bounded:
            _require_finite(name, value)
            if not lower <= value <= upper:
                raise ValueError(f"{name} must be between {lower} and {upper}")
        if self.long_rsi_min > self.long_rsi_max:
            raise ValueError("long RSI range is reversed")
        if self.short_rsi_min > self.short_rsi_max:
            raise ValueError("short RSI range is reversed")
        if self.min_atr_fraction > self.max_atr_fraction:
            raise ValueError("ATR fraction range is reversed")
        if self.min_risk_atr > self.max_risk_atr:
            raise ValueError("risk ATR range is reversed")
        if self.min_price_risk_fraction > self.max_price_risk_fraction:
            raise ValueError("price-risk fraction range is reversed")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def normalized_json(self) -> str:
        return json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )

    def fingerprint(self) -> str:
        return sha256(self.normalized_json().encode("utf-8")).hexdigest()


def normalized_config_json(config: StrategyConfig) -> str:
    return config.normalized_json()


def config_fingerprint(config: StrategyConfig) -> str:
    return config.fingerprint()


@dataclass(frozen=True, slots=True)
class PreparedBar:
    """A bar and every indicator value required by the frozen signal."""

    index: int
    bar: Bar
    ema21: float | None
    ema55: float | None
    ema200: float | None
    atr14: float | None
    rsi14: float | None
    volume_sma20: float | None
    plus_di14: float | None
    minus_di14: float | None
    adx14: float | None


@dataclass(frozen=True, slots=True)
class Signal:
    """A completed-bar setup.  It has no knowledge of a future entry open."""

    index: int
    time: int
    side: str
    signal_close: float
    risk_distance: float
    atr: float
    structural_stop: float

    def __post_init__(self) -> None:
        if self.index < 0 or self.time < 0:
            raise ValueError("signal index/time cannot be negative")
        if self.side not in SIDES:
            raise ValueError(f"unsupported side: {self.side}")
        for name in ("signal_close", "risk_distance", "atr", "structural_stop"):
            _require_finite(name, getattr(self, name))
        if self.signal_close <= 0 or self.risk_distance <= 0 or self.atr <= 0:
            raise ValueError("signal price, risk distance, and ATR must be positive")

    @property
    def timestamp(self) -> int:
        return self.time


@dataclass(frozen=True, slots=True)
class Position:
    signal: Signal
    entry_index: int
    entry_time: int
    entry_price: float
    initial_stop_price: float
    stop_price: float
    target_price: float
    quantity: float
    planned_risk_cash: float
    entry_fee: float
    bars_held: int = 0
    maximum_favorable_excursion: float = 0.0
    maximum_adverse_excursion: float = 0.0
    cost_covered: bool = False
    cost_covered_index: int | None = None

    @property
    def side(self) -> str:
        return self.signal.side


@dataclass(frozen=True, slots=True)
class Trade:
    signal_index: int
    signal_time: int
    entry_index: int
    entry_time: int
    exit_index: int
    exit_time: int
    side: str
    signal_price: float
    entry_price: float
    exit_price: float
    initial_stop_price: float
    stop_price: float
    target_price: float
    quantity: float
    planned_risk_cash: float
    entry_fee: float
    exit_fee: float
    gross_pnl: float
    net_pnl: float
    r_multiple: float
    maximum_favorable_excursion: float
    maximum_adverse_excursion: float
    bars_held: int
    exit_reason: str
    ambiguous_bar: bool = False
    cost_covered_before_exit: bool = False

    def __post_init__(self) -> None:
        if self.side not in SIDES:
            raise ValueError(f"unsupported side: {self.side}")

    @property
    def fees(self) -> float:
        return self.entry_fee + self.exit_fee


@dataclass(frozen=True, slots=True)
class BacktestResult:
    config_fingerprint: str
    initial_equity: float
    final_equity: float
    trades: tuple[Trade, ...]
    signals: tuple[Signal, ...] = ()
    open_position: Position | None = None
    marked_equity: float | None = None
    skipped_gap_signals: int = 0
    equity_curve: tuple[float, ...] = ()
