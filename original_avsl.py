"""Original Buff Dormeier AVSL live sell-signal calculation.

This module implements the original AVSL path used by live AVSL sell decisions.
The calculation is pure, based on caller-provided OHLCV data, and does not call
network APIs.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config import AVSLConfig

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS = ("High", "Low", "Close", "Volume")
_EPSILON = 1e-12


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Divide two aligned series while converting zero/inf results to NaN."""
    safe_denominator = denominator.where(denominator.abs() > _EPSILON)
    result = numerator / safe_denominator
    return result.replace([np.inf, -np.inf], np.nan)


def _rolling_vwma(price: pd.Series, volume: pd.Series, window: int) -> pd.Series:
    """Return a rolling volume-weighted moving average with zero-volume protection."""
    weighted_price = (price * volume).rolling(window=window, min_periods=window).sum()
    rolling_volume = volume.rolling(window=window, min_periods=window).sum()
    return _safe_divide(weighted_price, rolling_volume)


def _dynamic_rolling_mean(values: pd.Series, lengths: pd.Series) -> pd.Series:
    """Calculate a per-row rolling mean using the row's already-clamped integer length."""
    output = pd.Series(np.nan, index=values.index, dtype="float64")
    for position, (_, length_value) in enumerate(lengths.items()):
        if pd.isna(length_value):
            continue
        length = int(length_value)
        start = position - length + 1
        if start < 0:
            continue
        window = values.iloc[start : position + 1]
        if window.notna().sum() == length:
            output.iloc[position] = float(window.mean())
    return output


def _dynamic_rolling_std(values: pd.Series, lengths: pd.Series) -> pd.Series:
    """Calculate a per-row population standard deviation using each row's length."""
    output = pd.Series(np.nan, index=values.index, dtype="float64")
    for position, (_, length_value) in enumerate(lengths.items()):
        if pd.isna(length_value):
            continue
        length = int(length_value)
        start = position - length + 1
        if start < 0:
            continue
        window = values.iloc[start : position + 1]
        if window.notna().sum() == length:
            output.iloc[position] = float(window.std(ddof=0))
    return output


def calculate_original_avsl(
    ohlcv: pd.DataFrame,
    fast_period: int | None = None,
    slow_period: int | None = None,
    min_length: int | None = None,
    max_length: int | None = None,
    stddev_mult: float | None = None,
) -> pd.DataFrame | None:
    """Calculate a conservative original Buff Dormeier AVSL live report.

    Public AVSL descriptions are not fully formalized.  This implementation
    keeps the stated shape of the formula while documenting the interpretation:

    * VPC is treated as a dimensionless slow VWMA/SMA price-confirmation ratio.
      This makes the public ``Low * 1/VPC * 1/VPR`` price component numerically
      stable; using a raw VWMA-SMA difference would make ``1/VPC`` explode near
      zero and can invert positive prices.
    * VPR compares fast and slow VWMA/SMA price-confirmation ratios.
    * VM is the fast/slow volume moving-average ratio.
    * The volume-price component indicator is the signed deviation of VPC from neutral, multiplied by VPR and VM.
    * Length follows the public dynamic length rule and is clamped by config.
    * The lower Bollinger-style stop subtracts a rolling standard-deviation term
      from the rolling average of ``Low * 1/VPC * 1/VPR``.  The deviation term is
      scaled by the volume-price component indicator and VM while remaining
      non-negative and deterministic.

    The result does not call network APIs. Its latest positive finite
    ``original_avsl`` value is used by ``check_avsl_sell_signal()`` for live
    AVSL sell decisions.
    """
    fast_period = AVSLConfig.FAST_PERIOD if fast_period is None else int(fast_period)
    slow_period = AVSLConfig.SLOW_PERIOD if slow_period is None else int(slow_period)
    min_length = AVSLConfig.MIN_LENGTH if min_length is None else int(min_length)
    max_length = AVSLConfig.MAX_LENGTH if max_length is None else int(max_length)
    stddev_mult = AVSLConfig.STDDEV_MULT if stddev_mult is None else float(stddev_mult)

    if ohlcv is None or ohlcv.empty:
        return None
    if fast_period <= 0 or slow_period <= 0 or min_length <= 0 or max_length < min_length:
        return None
    if slow_period < fast_period:
        return None

    missing_columns = [column for column in _REQUIRED_COLUMNS if column not in ohlcv.columns]
    if missing_columns:
        logger.debug("Original AVSL missing required columns: %s", missing_columns)
        return None

    data = ohlcv.loc[:, _REQUIRED_COLUMNS].apply(pd.to_numeric, errors="coerce")
    data = data.replace([np.inf, -np.inf], np.nan)
    data["Volume"] = data["Volume"].where(data["Volume"] > _EPSILON)

    required_history = slow_period + max_length - 1
    if len(data) < required_history:
        return None

    high = data["High"]
    low = data["Low"]
    close = data["Close"]
    volume = data["Volume"]
    typical_price = (high + low + close) / 3.0

    slow_sma = typical_price.rolling(window=slow_period, min_periods=slow_period).mean()
    fast_sma = typical_price.rolling(window=fast_period, min_periods=fast_period).mean()
    slow_vwma = _rolling_vwma(typical_price, volume, slow_period)
    fast_vwma = _rolling_vwma(typical_price, volume, fast_period)

    vpc = _safe_divide(slow_vwma, slow_sma)
    fast_price_volume_ratio = _safe_divide(fast_vwma, fast_sma)
    vpr = _safe_divide(fast_price_volume_ratio, vpc)
    fast_volume_ma = volume.rolling(window=fast_period, min_periods=fast_period).mean()
    slow_volume_ma = volume.rolling(window=slow_period, min_periods=slow_period).mean()
    vm = _safe_divide(fast_volume_ma, slow_volume_ma)
    vpci = (vpc - 1.0) * vpr * vm

    dynamic_length = (3.0 + vpci).round().clip(lower=min_length, upper=max_length)
    dynamic_length = dynamic_length.where(np.isfinite(dynamic_length), np.nan)

    price_basis = low * _safe_divide(pd.Series(1.0, index=low.index), vpc) * _safe_divide(
        pd.Series(1.0, index=low.index), vpr
    )
    price_basis = price_basis.where(price_basis > 0).replace([np.inf, -np.inf], np.nan)

    price_component = _dynamic_rolling_mean(price_basis, dynamic_length)
    rolling_std = _dynamic_rolling_std(price_basis, dynamic_length)
    deviation_component = rolling_std * stddev_mult * (1.0 + vpci.abs() * vm.abs())
    original_avsl = (price_component - deviation_component).where(lambda series: series > 0)

    result = pd.DataFrame(
        {
            "VPC": vpc,
            "VPR": vpr,
            "VM": vm,
            "vpci": vpci,
            "dynamic_length": dynamic_length,
            "price_component": price_component,
            "original_avsl": original_avsl,
        },
        index=data.index,
    )
    result = result.replace([np.inf, -np.inf], np.nan)

    if result["original_avsl"].dropna().empty:
        return None
    return result
