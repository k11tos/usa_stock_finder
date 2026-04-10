from __future__ import annotations

from run_backtest import parse_args


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
