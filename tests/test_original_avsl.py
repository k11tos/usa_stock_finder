"""Tests for the original Buff Dormeier AVSL calculation path."""

from unittest.mock import patch

import numpy as np
import pandas as pd

from original_avsl import calculate_original_avsl
from stock_analysis import UsaStockFinder


def _synthetic_ohlcv(periods: int = 90, symbol: str | None = None) -> pd.DataFrame:
    index = pd.date_range(start="2025-01-01", periods=periods, freq="D")
    trend = np.linspace(40.0, 58.0, periods)
    wave = np.sin(np.linspace(0.0, 6.0, periods)) * 0.8
    close = trend + wave
    high = close + 1.2
    low = close - 1.1
    volume = np.linspace(1000.0, 2400.0, periods) + np.cos(np.linspace(0.0, 8.0, periods)) * 100.0

    if symbol is None:
        return pd.DataFrame(
            {
                "High": high,
                "Low": low,
                "Close": close,
                "Volume": volume,
            },
            index=index,
        )

    data = pd.DataFrame(
        {
            ("High", symbol): high,
            ("Low", symbol): low,
            ("Close", symbol): close,
            ("Volume", symbol): volume,
        },
        index=index,
    )
    data.columns = pd.MultiIndex.from_tuples(data.columns)
    return data


def test_original_avsl_returns_none_safely_on_insufficient_data() -> None:
    ohlcv = _synthetic_ohlcv(periods=10)

    result = calculate_original_avsl(ohlcv, fast_period=5, slow_period=20, min_length=3, max_length=50)

    assert result is None


def test_original_avsl_final_valid_output_has_no_nan_or_inf() -> None:
    ohlcv = _synthetic_ohlcv()
    ohlcv.loc[ohlcv.index[5], "Volume"] = 0.0

    result = calculate_original_avsl(ohlcv, fast_period=5, slow_period=20, min_length=3, max_length=12)

    assert result is not None
    valid = result.dropna(subset=["original_avsl"])
    assert not valid.empty
    assert np.isfinite(valid[["VPC", "VPR", "VM", "VPCI", "price_component", "original_avsl"]].to_numpy()).all()


def test_original_avsl_dynamic_length_is_clamped_within_configured_range() -> None:
    ohlcv = _synthetic_ohlcv(periods=100)

    result = calculate_original_avsl(ohlcv, fast_period=3, slow_period=8, min_length=4, max_length=6)

    assert result is not None
    valid_lengths = result["dynamic_length"].dropna()
    assert not valid_lengths.empty
    assert valid_lengths.min() >= 4
    assert valid_lengths.max() <= 6


def test_original_avsl_line_is_positive_for_positive_prices() -> None:
    ohlcv = _synthetic_ohlcv(periods=100)

    result = calculate_original_avsl(ohlcv, fast_period=5, slow_period=20, min_length=3, max_length=12)

    assert result is not None
    valid_avsl = result["original_avsl"].dropna()
    assert not valid_avsl.empty
    assert (valid_avsl > 0).all()


def test_original_avsl_report_does_not_affect_legacy_sell_signal() -> None:
    with patch("yfinance.download") as mock_download:
        mock_download.return_value = _synthetic_ohlcv(periods=100, symbol="SAFE")
        finder = UsaStockFinder(["SAFE"])

        before = finder.check_avsl_sell_signal()
        report = finder.calculate_original_avsl_report("SAFE")
        after = finder.check_avsl_sell_signal()

    assert report is not None
    assert list(report.columns) == ["VPC", "VPR", "VM", "VPCI", "dynamic_length", "price_component", "original_avsl"]
    assert before == after
