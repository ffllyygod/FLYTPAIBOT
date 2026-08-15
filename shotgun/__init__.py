"""Shotgun v1 research strategy and deterministic reference backtester."""

from .indicators import DMIResult, atr, dmi, ema, prepare_bars, rma, rsi, sma, true_range
from .models import (
    BacktestResult,
    Bar,
    LONG,
    Position,
    PreparedBar,
    SHORT,
    Signal,
    StrategyConfig,
    Trade,
    config_fingerprint,
    normalized_config_json,
)
from .strategy import evaluate_signals, generate_signals, signal_at

__all__ = [
    "BacktestResult",
    "Bar",
    "DMIResult",
    "LONG",
    "Position",
    "PreparedBar",
    "SHORT",
    "Signal",
    "StrategyConfig",
    "Trade",
    "atr",
    "config_fingerprint",
    "dmi",
    "ema",
    "evaluate_signals",
    "generate_signals",
    "normalized_config_json",
    "prepare_bars",
    "rma",
    "rsi",
    "signal_at",
    "sma",
    "true_range",
]
