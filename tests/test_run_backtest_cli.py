from __future__ import annotations

import pandas as pd

from run_backtest import _apply_date_filter, parse_args


def test_parse_args_maps_required_and_optional_values() -> None:
    args = parse_args(
        [
            "--prices",
            "prices.csv",
            "--candidates",
            "candidates.csv",
            "--universe",
            "quantus_minervini",
            "--entry",
            "trend_basic",
            "--exit",
            "trailing",
            "--start-date",
            "2025-01-01",
            "--end-date",
            "2025-12-31",
            "--top-n",
            "3",
        ]
    )

    assert args.prices == "prices.csv"
    assert args.candidates == "candidates.csv"
    assert args.universe == "quantus_minervini"
    assert args.entry == "trend_basic"
    assert args.exit_rule == "trailing"
    assert args.start_date == "2025-01-01"
    assert args.end_date == "2025-12-31"
    assert args.top_n == 3


def test_apply_date_filter_handles_timezone_qualified_timestamps() -> None:
    frame = pd.DataFrame(
        {
            "date": [
                "2025-01-01T23:59:59Z",
                "2025-01-02T00:00:00Z",
                "2025-01-03T00:00:00+00:00",
            ],
            "symbol": ["AAA", "BBB", "CCC"],
        }
    )

    filtered = _apply_date_filter(
        frame,
        "date",
        pd.Timestamp("2025-01-02", tz="UTC"),
        pd.Timestamp("2025-01-03", tz="UTC"),
    )

    assert list(filtered["symbol"]) == ["BBB", "CCC"]


def test_apply_date_filter_includes_non_midnight_rows_on_end_date() -> None:
    frame = pd.DataFrame(
        {
            "date": [
                "2025-01-31 15:30:00",
                "2025-02-01 00:00:00",
            ],
            "symbol": ["AAA", "BBB"],
        }
    )

    filtered = _apply_date_filter(
        frame,
        "date",
        pd.Timestamp("2025-01-01", tz="UTC"),
        pd.Timestamp("2025-01-31", tz="UTC"),
    )

    assert list(filtered["symbol"]) == ["AAA"]
