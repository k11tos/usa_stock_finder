from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

from tools.compare_avsl import (
    AVSLComparisonRow,
    build_telegram_monitor_summary,
    classify_avsl_status,
    compare_symbols,
    render_markdown_summary,
    write_csv,
)


def test_classify_avsl_status_categories() -> None:
    assert classify_avsl_status(100.0, 90.0, 95.0) == ("BOTH_HOLD", False, False)
    assert classify_avsl_status(80.0, 90.0, 95.0) == ("BOTH_SELL", True, True)
    assert classify_avsl_status(92.0, 95.0, 90.0) == ("LEGACY_ONLY_SELL", True, False)
    assert classify_avsl_status(92.0, 90.0, 95.0) == ("ORIGINAL_ONLY_SELL", False, True)


def test_classify_avsl_status_missing_values_are_insufficient_data() -> None:
    assert classify_avsl_status(None, 90.0, 95.0) == ("INSUFFICIENT_DATA", None, None)
    assert classify_avsl_status(100.0, None, 95.0) == ("INSUFFICIENT_DATA", None, None)
    assert classify_avsl_status(100.0, 90.0, None) == ("INSUFFICIENT_DATA", None, None)
    assert classify_avsl_status(100.0, 0.0, 95.0) == ("INSUFFICIENT_DATA", None, None)


def test_compare_symbols_handles_missing_legacy_or_original_values() -> None:
    finder = MagicMock()
    finder.current_price = {"NOLEGACY": 100.0, "NOORIG": 100.0}
    finder.get_latest_avsl.side_effect = lambda symbol: None if symbol == "NOLEGACY" else 90.0
    finder.calculate_original_avsl_report.side_effect = lambda symbol: None

    rows = compare_symbols(finder, ["NOLEGACY", "NOORIG"])

    assert [row.status for row in rows] == ["INSUFFICIENT_DATA", "INSUFFICIENT_DATA"]
    assert rows[0].legacy_sell_signal is None
    assert rows[1].original_sell_signal is None


def test_compare_symbols_continues_after_symbol_failure() -> None:
    finder = MagicMock()
    finder.current_price = {"BAD": 100.0, "GOOD": 100.0}

    def get_latest_avsl(symbol: str) -> float:
        if symbol == "BAD":
            raise RuntimeError("legacy failed")
        return 90.0

    original_report = MagicMock()
    original_report.empty = False
    original_report.__contains__.side_effect = lambda item: item == "original_avsl"
    original_report.__getitem__.return_value.dropna.return_value.empty = False
    original_report.__getitem__.return_value.dropna.return_value.iloc.__getitem__.return_value = 95.0
    finder.get_latest_avsl.side_effect = get_latest_avsl
    finder.calculate_original_avsl_report.return_value = original_report

    rows = compare_symbols(finder, ["BAD", "GOOD"])

    assert rows[0].status == "INSUFFICIENT_DATA"
    assert "legacy failed" in rows[0].error
    assert rows[1].status == "BOTH_HOLD"


def test_compare_helper_does_not_call_order_or_sell_execution_logic() -> None:
    finder = MagicMock()
    finder.current_price = {"SAFE": 100.0}
    finder.get_latest_avsl.return_value = 90.0
    finder.calculate_original_avsl_report.return_value = None
    forbidden_order_placement = MagicMock(side_effect=AssertionError("order placement called"))
    forbidden_sell_execution = MagicMock(side_effect=AssertionError("sell execution called"))
    finder.place_order = forbidden_order_placement
    finder.execute_sell = forbidden_sell_execution

    rows = compare_symbols(finder, ["SAFE"])

    assert rows[0].status == "INSUFFICIENT_DATA"
    forbidden_order_placement.assert_not_called()
    forbidden_sell_execution.assert_not_called()
    finder.get_latest_avsl.assert_called_once_with("SAFE")
    finder.calculate_original_avsl_report.assert_called_once_with("SAFE")


def test_compare_symbols_classifies_when_all_avsl_values_are_available() -> None:
    finder = MagicMock()
    finder.current_price = {"SAFE": 100.0, "LEG": 92.0}
    finder.get_latest_avsl.side_effect = lambda symbol: 90.0 if symbol == "SAFE" else 95.0

    def original_report(symbol: str) -> pd.DataFrame:
        latest_original = 95.0 if symbol == "SAFE" else 90.0
        return pd.DataFrame({"original_avsl": [latest_original]})

    finder.calculate_original_avsl_report.side_effect = original_report

    rows = compare_symbols(finder, ["SAFE", "LEG"])

    assert [row.status for row in rows] == ["BOTH_HOLD", "LEGACY_ONLY_SELL"]
    assert rows[0].legacy_sell_signal is False
    assert rows[0].original_sell_signal is False
    assert rows[1].legacy_sell_signal is True
    assert rows[1].original_sell_signal is False


def test_write_csv_and_markdown_include_monitoring_notice(tmp_path: Path) -> None:
    rows = [
        AVSLComparisonRow(
            symbol="AAPL",
            current_close=100.0,
            legacy_avsl=90.0,
            original_avsl=95.0,
            legacy_sell_signal=False,
            original_sell_signal=False,
            difference_amount=5.0,
            difference_percentage=5.555555,
            status="BOTH_HOLD",
        )
    ]

    csv_path = write_csv(rows, tmp_path)
    markdown = render_markdown_summary(rows, csv_path)

    csv_text = csv_path.read_text(encoding="utf-8")
    assert "symbol,current_close,legacy_avsl,original_avsl" in csv_text
    assert "AAPL,100.000000,90.000000,95.000000" in csv_text
    assert "MONITORING ONLY" in markdown
    assert "not used for trading decisions" in markdown
    assert "BOTH_HOLD: 1" in markdown


def test_write_monitor_outputs_creates_latest_and_history_dirs(tmp_path: Path) -> None:
    rows = [
        AVSLComparisonRow(
            symbol="AAPL",
            current_close=100.0,
            legacy_avsl=90.0,
            original_avsl=95.0,
            legacy_sell_signal=False,
            original_sell_signal=False,
            difference_amount=5.0,
            difference_percentage=5.555555,
            status="BOTH_HOLD",
        )
    ]

    from tools.compare_avsl import write_monitor_outputs

    paths = write_monitor_outputs(rows, tmp_path, "2026-05-29")

    assert paths["latest_csv"].parent == tmp_path / "latest"
    assert paths["latest_markdown"].exists()
    assert paths["history_csv"].parent == tmp_path / "history" / "2026-05-29"
    assert paths["history_markdown"].exists()


def test_summarize_status_counts_includes_zero_categories() -> None:
    from tools.compare_avsl import summarize_status_counts

    rows = [
        AVSLComparisonRow("HOLD", 100.0, 90.0, 95.0, False, False, 5.0, 5.0, "BOTH_HOLD"),
        AVSLComparisonRow("SELL", 80.0, 90.0, 95.0, True, True, 5.0, 5.0, "BOTH_SELL"),
        AVSLComparisonRow("LEG", 92.0, 95.0, 90.0, True, False, -5.0, -5.0, "LEGACY_ONLY_SELL"),
        AVSLComparisonRow("ORG", 92.0, 90.0, 95.0, False, True, 5.0, 5.0, "ORIGINAL_ONLY_SELL"),
        AVSLComparisonRow("MISS", None, None, None, None, None, None, None, "INSUFFICIENT_DATA"),
    ]

    assert summarize_status_counts(rows) == {
        "BOTH_HOLD": 1,
        "BOTH_SELL": 1,
        "LEGACY_ONLY_SELL": 1,
        "ORIGINAL_ONLY_SELL": 1,
        "INSUFFICIENT_DATA": 1,
    }


def test_build_telegram_monitor_summary_empty_results() -> None:
    message = build_telegram_monitor_summary([], Path("outputs/avsl_monitor/latest/report.md"))

    assert "[AVSL Monitor]" in message
    assert "MONITORING ONLY" in message
    assert "not used for trading decisions" in message
    assert "BOTH_HOLD=0" in message
    assert "BOTH_SELL=0" in message
    assert "LEGACY_ONLY_SELL=0" in message
    assert "ORIGINAL_ONLY_SELL=0" in message
    assert "INSUFFICIENT_DATA=0" in message
    assert "LEGACY_ONLY_SELL: (none)" in message
    assert "ORIGINAL_ONLY_SELL: (none)" in message
    assert "Artifact: outputs/avsl_monitor/latest/report.md" in message


def test_build_telegram_monitor_summary_difference_categories_only_listed() -> None:
    rows = [
        AVSLComparisonRow("HOLD", 100.0, 90.0, 95.0, False, False, 5.0, 5.0, "BOTH_HOLD"),
        AVSLComparisonRow("SELL", 80.0, 90.0, 95.0, True, True, 5.0, 5.0, "BOTH_SELL"),
        AVSLComparisonRow("LEG", 92.0, 95.0, 90.0, True, False, -5.0, -5.0, "LEGACY_ONLY_SELL"),
        AVSLComparisonRow("ORG", 92.0, 90.0, 95.0, False, True, 5.0, 5.0, "ORIGINAL_ONLY_SELL"),
        AVSLComparisonRow("MISS", None, None, None, None, None, None, None, "INSUFFICIENT_DATA"),
    ]

    message = build_telegram_monitor_summary(rows)

    assert "BOTH_HOLD=1" in message
    assert "BOTH_SELL=1" in message
    assert "LEGACY_ONLY_SELL=1" in message
    assert "ORIGINAL_ONLY_SELL=1" in message
    assert "INSUFFICIENT_DATA=1" in message
    assert "LEGACY_ONLY_SELL: LEG" in message
    assert "ORIGINAL_ONLY_SELL: ORG" in message
    assert "BOTH_HOLD: HOLD" not in message
    assert "BOTH_SELL: SELL" not in message
    assert "INSUFFICIENT_DATA: MISS" not in message


def test_build_telegram_monitor_summary_truncates_difference_symbols() -> None:
    rows = [
        AVSLComparisonRow(f"L{i}", 92.0, 95.0, 90.0, True, False, -5.0, -5.0, "LEGACY_ONLY_SELL")
        for i in range(1, 6)
    ]
    rows.extend(
        AVSLComparisonRow(f"O{i}", 92.0, 90.0, 95.0, False, True, 5.0, 5.0, "ORIGINAL_ONLY_SELL")
        for i in range(1, 5)
    )

    message = build_telegram_monitor_summary(rows, max_symbols_per_list=3)

    assert "LEGACY_ONLY_SELL: L1, L2, L3, +2 more" in message
    assert "ORIGINAL_ONLY_SELL: O1, O2, O3, +1 more" in message
    assert "L4" not in message
    assert "O4" not in message
