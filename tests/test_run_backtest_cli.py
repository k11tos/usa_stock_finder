from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd

from run_backtest import BASIC_COMPARISON_EXPERIMENTS, _apply_date_filter, main, parse_args


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
    assert args.save_output is False
    assert args.output_root == "outputs/backtests"


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


def test_parse_args_maps_compare_basic_flag() -> None:
    args = parse_args(
        [
            "--prices",
            "prices.csv",
            "--candidates",
            "candidates.csv",
            "--compare-basic",
        ]
    )

    assert args.compare_basic is True


def test_compare_basic_dispatches_expected_runs_and_prints_summary(
    monkeypatch, capsys
) -> None:
    prices_df = pd.DataFrame({"date": ["2025-01-01"], "symbol": ["AAA"], "close": [10.0]})
    candidates_df = pd.DataFrame({"asof_date": ["2025-01-01"], "symbol": ["AAA"], "rs_score": [99.0]})

    monkeypatch.setattr("run_backtest.data_loader.load_price_history", lambda _path: prices_df)
    monkeypatch.setattr("run_backtest.data_loader.load_candidate_snapshots", lambda _path: candidates_df)

    dispatched: list[tuple[str, str, str]] = []

    def _fake_run_backtest(*, universe, entry, exit_rule, **_kwargs):
        dispatched.append((universe, entry, exit_rule))
        return {
            "metrics": {
                "total_trades": 1,
                "total_return": 0.12,
                "max_drawdown": -0.03,
                "total_pnl": 1200.0,
                "ending_equity": 101200.0,
                "win_rate": 1.0,
            },
            "trades": pd.DataFrame(),
            "equity_curve": pd.DataFrame(),
            "candidate_stage_snapshots": {},
        }

    monkeypatch.setattr("run_backtest.run_backtest", _fake_run_backtest)
    monkeypatch.setattr("run_backtest.save_backtest_outputs", MagicMock())

    exit_code = main(["--prices", "prices.csv", "--candidates", "candidates.csv", "--compare-basic"])

    assert exit_code == 0
    assert dispatched == list(BASIC_COMPARISON_EXPERIMENTS)

    stdout = capsys.readouterr().out
    assert "comparison_summary:" in stdout
    assert "universe" in stdout
    assert "quantus_minervini" in stdout


def test_compare_basic_with_save_output_persists_each_run(monkeypatch, capsys) -> None:
    prices_df = pd.DataFrame({"date": ["2025-01-01"], "symbol": ["AAA"], "close": [10.0]})
    candidates_df = pd.DataFrame({"asof_date": ["2025-01-01"], "symbol": ["AAA"], "rs_score": [99.0]})

    monkeypatch.setattr("run_backtest.data_loader.load_price_history", lambda _path: prices_df)
    monkeypatch.setattr("run_backtest.data_loader.load_candidate_snapshots", lambda _path: candidates_df)

    dispatched: list[tuple[str, str, str]] = []

    def _fake_run_backtest(*, universe, entry, exit_rule, **_kwargs):
        dispatched.append((universe, entry, exit_rule))
        return {
            "metrics": {
                "total_trades": 1,
                "total_return": 0.12,
                "max_drawdown": -0.03,
                "total_pnl": 1200.0,
                "ending_equity": 101200.0,
                "win_rate": 1.0,
            },
            "trades": pd.DataFrame([{"symbol": "AAA"}]),
            "equity_curve": pd.DataFrame([{"date": "2025-01-01", "equity": 101200.0}]),
            "candidate_stage_snapshots": {"initial": pd.DataFrame([{"symbol": "AAA"}])},
        }

    monkeypatch.setattr("run_backtest.run_backtest", _fake_run_backtest)

    built_tags: list[str] = []

    def _fake_build_run_tag(*, universe, entry, exit_rule, **_kwargs):
        tag = f"{universe}_{entry}_{exit_rule}"
        built_tags.append(tag)
        return tag

    monkeypatch.setattr("run_backtest.build_run_tag", _fake_build_run_tag)
    save_outputs_mock = MagicMock(side_effect=lambda **kwargs: {"run_dir": f"/tmp/{kwargs['run_tag']}"})
    monkeypatch.setattr("run_backtest.save_backtest_outputs", save_outputs_mock)

    exit_code = main(
        [
            "--prices",
            "prices.csv",
            "--candidates",
            "candidates.csv",
            "--compare-basic",
            "--save-output",
            "--output-root",
            "outputs/custom",
        ]
    )

    assert exit_code == 0
    assert dispatched == list(BASIC_COMPARISON_EXPERIMENTS)
    assert save_outputs_mock.call_count == len(BASIC_COMPARISON_EXPERIMENTS)
    assert built_tags == [
        "quantus_none_hold_fixed",
        "quantus_trend_basic_hold_fixed",
        "quantus_minervini_none_hold_fixed",
        "quantus_minervini_trend_basic_hold_fixed",
    ]

    for idx, call in enumerate(save_outputs_mock.call_args_list):
        kwargs = call.kwargs
        assert kwargs["run_tag"] == built_tags[idx]
        assert kwargs["output_root"] == "outputs/custom"

    stdout = capsys.readouterr().out
    assert stdout.count("saved_outputs=/tmp/") == len(BASIC_COMPARISON_EXPERIMENTS)
    assert "comparison_summary:" in stdout
