"""Offline regressions for the production daily notification orchestration."""

import asyncio
import json
import logging
from datetime import date
from threading import Event, Thread
from unittest.mock import AsyncMock, MagicMock

import pytest

import main
from sell_signals import SellDecision, SellReason
from telegram_utils import build_daily_report_message, build_performance_summary_message, send_telegram_message

SUMMARY = {
    "start_date": "2026-05-26",
    "end_date": "2026-08-26",
    "cumulative_return_pct": 7.2,
    "cumulative_return_SPY_pct": 4.1,
    "cumulative_return_IWM_pct": -3.3,
    "excess_return_vs_SPY": 3.1,
    "excess_return_vs_IWM": 10.5,
    "max_drawdown_pct": -6.8,
}
REPORT_URL = "https://reports.example/latest/"


@pytest.fixture
def daily_run(monkeypatch, tmp_path):
    """Exercise main's filters/formatters/sender, with all external services mocked."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(main, "_load_and_validate_runtime_prerequisites", lambda: True)
    monkeypatch.setattr(main, "generate_run_metadata", lambda: ("test-run", "2026-08-26"))
    fixed_date = MagicMock()
    fixed_date.today.return_value = date(2026, 8, 26)
    monkeypatch.setattr(main, "date", fixed_date)
    monkeypatch.setattr(main, "fetch_us_stock_holdings", lambda: ["HELD", "TSLA", "OLD"])
    monkeypatch.setattr(main, "_load_previous_tracked_items", lambda *_args: [])
    monkeypatch.setattr(main, "is_in_cooldown", lambda *_args: False)

    finder = MagicMock()
    finder.source_pool_by_symbol = {}
    finder.current_price = {"MOMO": 100.0, "HELD": 100.0}
    finder.get_event_quarantine_metrics.side_effect = lambda symbol, **_kwargs: {
        "is_event_quarantine": symbol.startswith("EVENT"),
        "max_gap_up_pct": 0.3,
        "days_since_gap": 10,
        "current_vs_gap_close_pct": 0.001,
        "drawdown_from_post_gap_high_pct": 0.01,
    }
    finder.get_special_situation_price_pinned_metrics.side_effect = lambda symbol: {
        "is_special_situation": symbol.startswith("PRTH"),
        "max_gap_up_pct": 0.3,
        "recent_range_pct": 0.001,
        "recent_abs_return_pct": 0.001,
        "atr_pct": 0.002,
    }
    stages = {
        "initial_input_symbols": 6,
        "tradability_excluded_symbols": 1,
        "exchange_eligible_symbols": 5,
        "trend_eligible_symbols": 4,
    }
    prepare = MagicMock(
        return_value=(finder, ["PRTH", "EVENT", "MOMO", "HELD"], [], {"PRTH", "EVENT", "MOMO", "HELD"}, stages)
    )
    monkeypatch.setattr(main, "_prepare_finder_and_candidates", prepare)
    decisions = {
        "TSLA": SellDecision("TSLA", SellReason.STOP_LOSS, 3),
        "OLD": SellDecision("OLD", SellReason.NONE, 0),
    }
    sells = {
        "TSLA": {
            "shares_to_sell": 3,
            "current_price": 80.0,
            "sell_amount": 240.0,
            "profit_loss": -60.0,
            "profit_loss_rate": -20.0,
        }
    }
    monkeypatch.setattr(
        main, "_prepare_sell_decisions_and_quantities", MagicMock(return_value=(decisions, sells, 240.0, []))
    )
    shares = {"MOMO": {"shares_to_buy": 5, "investment_amount": 500.0, "current_price": 100.0}}
    sizing = MagicMock(
        side_effect=lambda candidates, *_args, **_kwargs: (
            candidates, {"MOMO": 500.0}, shares, {"total_balance": 10000.0}
        )
    )
    monkeypatch.setattr(main, "_prepare_buy_side_orchestration", sizing)
    trades = MagicMock()
    snapshots = MagicMock()
    save = MagicMock()
    monkeypatch.setattr(main, "append_trade_signals", trades)
    monkeypatch.setattr(main, "append_account_snapshots", snapshots)
    monkeypatch.setattr(main, "save_json", save)
    monkeypatch.setenv("PERFORMANCE_REPORT_ENABLED", "true")
    monkeypatch.setenv("PERFORMANCE_REPORT_TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("PERFORMANCE_REPORT_OUTPUT_DIR", str(tmp_path / "report"))
    monkeypatch.setenv("PERFORMANCE_REPORT_URL", REPORT_URL)
    monkeypatch.setenv("PERFORMANCE_REPORT_BENCHMARKS", "SPY,IWM")
    env_values = {"TELEGRAM_BOT_TOKEN": "fake-token", "TELEGRAM_CHAT_ID": "fake-chat"}
    monkeypatch.setattr(main.EnvironmentConfig, "get", env_values.get)
    bot = MagicMock()
    bot.sendMessage = AsyncMock()
    monkeypatch.setattr("telegram_utils.telegram.Bot", lambda *_args: bot)

    def build_report(_args):
        # Today's records must be written before computing the performance section.
        trades.assert_called_once()
        snapshots.assert_called_once()
        save.assert_called_once()
        output = tmp_path / "report"
        output.mkdir(exist_ok=True)
        (output / "performance_summary.json").write_text(json.dumps(SUMMARY), encoding="utf-8")

    builder = MagicMock(side_effect=build_report)
    monkeypatch.setattr("performance_report_runner.build_report", builder)
    return {
        "bot": bot,
        "stages": stages,
        "prepare": prepare,
        "sizing": sizing,
        "shares": shares,
        "decisions": decisions,
        "trades": trades,
        "snapshots": snapshots,
        "save": save,
        "builder": builder,
        "summary_path": tmp_path / "report" / "performance_summary.json",
    }


def assert_trade_details(message):
    for detail in (
        "신규 매수: MOMO",
        "매수 수량: 5주",
        "투자 금액: $500.00",
        "현재가: $100.00",
        "매도 (절대 손절): TSLA",
        "매도 수량: 3주",
        "매도 금액: $240.00",
        "손익: $-60.00 (-20.00%)",
        "B-Plan 유지(유니버스 제외): OLD",
    ):
        assert detail in message
    assert "PRTH" not in message
    assert "EVENT" not in message


def sent_message(daily_run):
    daily_run["bot"].sendMessage.assert_awaited_once()
    return daily_run["bot"].sendMessage.call_args.kwargs["text"]


def sent_messages(daily_run):
    return [call.kwargs["text"] for call in daily_run["bot"].sendMessage.call_args_list]


def test_trade_day_sends_immediate_trade_alert_then_performance_follow_up(daily_run, caplog):
    with caplog.at_level(logging.INFO, logger="main"):
        main.main()
    trade_message, performance_message = sent_messages(daily_run)
    assert daily_run["bot"].sendMessage.await_count == 2
    assert trade_message.startswith("usa_stock_finder 일일 리포트\n2026-08-26\n\n매수 현황")
    # Two screened candidates, even though only one has an executable sized buy.
    assert "최종 매수 후보: 2종목" in trade_message
    assert len(daily_run["shares"]) == 1
    assert_trade_details(trade_message)
    # Actionable details are delivered before optional benchmark/report work.
    assert "전략 성과" not in trade_message
    assert trade_message.count("2026-08-26") == 1
    assert len(trade_message) < 4096
    assert "[Buy Funnel]" not in trade_message
    assert "전략 성과 (2026-05-26 ~ 2026-08-26)" in performance_message
    assert "SPY: +4.10%" in performance_message
    assert "IWM: -3.30%" in performance_message
    assert "상세: https://reports.example/latest/" in performance_message
    assert "최종 매수 후보" not in performance_message
    for detail in ("신규 매수: MOMO", "매도 (절대 손절): TSLA", "B-Plan 유지"):
        assert detail not in performance_message
    for line in main.build_buy_funnel_lines(daily_run["stages"]):
        assert line in caplog.messages
    assert daily_run["stages"]["event_quarantine_excluded_symbol_list"] == "EVENT"
    assert daily_run["stages"]["special_situation_excluded_symbol_list"] == "PRTH"
    assert any("symbol=PRTH excluded reason=pinned_price_like_special_situation" in line for line in caplog.messages)
    assert any("symbol=EVENT excluded reason=event_quarantine" in line for line in caplog.messages)
    assert daily_run["sizing"].call_args.args[0] == ["MOMO", "HELD"]


@pytest.mark.parametrize("candidates", [[], ["HELD"]])
def test_no_trade_day_still_sends_one_compact_daily_report(daily_run, candidates):
    finder, _, _, _, stages = daily_run["prepare"].return_value
    daily_run["prepare"].return_value = finder, candidates, [], set(candidates), stages
    daily_run["shares"].clear()
    daily_run["decisions"].clear()
    main.main()
    message = sent_message(daily_run)
    assert f"최종 매수 후보: {len(candidates)}종목" in message
    assert "전략: +7.20%" in message
    assert "매수 신호" not in message
    assert "매도 신호" not in message
    assert "[Buy Funnel]" not in message
    assert daily_run["bot"].sendMessage.await_count == 1


def test_json_persistence_failure_still_attempts_trade_alert_and_preserves_failure(daily_run, caplog):
    persistence_error = OSError("read-only filesystem")
    daily_run["save"].side_effect = persistence_error

    with pytest.raises(OSError, match="read-only filesystem"), caplog.at_level(logging.ERROR, logger="main"):
        main.main()

    assert_trade_details(sent_message(daily_run))
    daily_run["save"].assert_called_once_with(["HELD", "OLD", "MOMO"], "data/data.json")
    daily_run["builder"].assert_not_called()
    assert "Failed to persist final symbol state to data/data.json" in caplog.text
    assert "sending the daily trade alert before aborting" in caplog.text


@pytest.mark.parametrize(
    ("persistence_mock", "expected_log"),
    [
        ("trades", "Failed to append trade signals CSV: disk full"),
        ("snapshots", "Failed to append account snapshots CSV: disk full"),
    ],
)
def test_csv_persistence_failures_do_not_suppress_trade_alerts(
    daily_run, caplog, persistence_mock, expected_log
):
    daily_run[persistence_mock].side_effect = OSError("disk full")

    with caplog.at_level(logging.WARNING, logger="main"):
        main.main()

    assert_trade_details(sent_messages(daily_run)[0])
    assert expected_log in caplog.text
    daily_run["builder"].assert_called_once()
    assert daily_run["bot"].sendMessage.await_count == 2


def test_unexpected_json_persistence_error_is_not_converted_into_success(daily_run, caplog):
    daily_run["save"].side_effect = TypeError("not serializable")

    with pytest.raises(TypeError, match="not serializable"), caplog.at_level(logging.ERROR, logger="main"):
        main.main()

    daily_run["bot"].sendMessage.assert_not_awaited()
    daily_run["builder"].assert_not_called()
    assert "Failed to persist final symbol state" not in caplog.text


@pytest.mark.parametrize(
    "failure",
    [
        "disabled", "telegram_disabled", "builder_error", "missing_url", "missing_summary", "malformed_summary", "unexpected_error",
    ],
)
def test_optional_performance_failures_never_suppress_trade_alerts(daily_run, monkeypatch, caplog, failure):
    if failure == "disabled":
        monkeypatch.setenv("PERFORMANCE_REPORT_ENABLED", "false")
        # A stale summary must not be sent after a skipped/failed generation.
        daily_run["summary_path"].parent.mkdir()
        daily_run["summary_path"].write_text(json.dumps(SUMMARY), encoding="utf-8")
    elif failure == "telegram_disabled":
        monkeypatch.setenv("PERFORMANCE_REPORT_TELEGRAM_ENABLED", "false")
    elif failure == "builder_error":
        daily_run["builder"].side_effect = RuntimeError("builder failed")
    elif failure == "missing_url":
        monkeypatch.setenv("PERFORMANCE_REPORT_URL", "")
    elif failure == "missing_summary":
        daily_run["builder"].side_effect = lambda _args: None
    elif failure == "malformed_summary":
        daily_run["builder"].side_effect = lambda _args: (
            daily_run["summary_path"].parent.mkdir(exist_ok=True),
            daily_run["summary_path"].write_text("not-json", encoding="utf-8"),
        )
    elif failure == "unexpected_error":
        monkeypatch.setattr(main, "run_performance_report_safely", MagicMock(side_effect=RuntimeError("unexpected")))
    with caplog.at_level(logging.INFO):
        main.main()
    message = sent_message(daily_run)
    assert "최종 매수 후보: 2종목" in message
    assert_trade_details(message)
    assert "전략 성과" not in message
    assert "전략: +7.20%" not in message
    assert daily_run["bot"].sendMessage.await_count == 1
    if failure == "builder_error":
        assert "Performance report generation failed" in caplog.text
    elif failure == "unexpected_error":
        assert "notification preparation failed" in caplog.text


def test_slow_performance_generation_starts_after_trade_delivery(daily_run, monkeypatch):
    report_started = Event()
    allow_report_finish = Event()

    def slow_report() -> bool:
        report_started.set()
        assert allow_report_finish.wait(timeout=1)
        return False

    monkeypatch.setattr(main, "run_performance_report_safely", slow_report)
    worker = Thread(target=main.main)
    worker.start()
    assert report_started.wait(timeout=1)
    assert_trade_details(sent_message(daily_run))
    assert daily_run["bot"].sendMessage.await_count == 1
    allow_report_finish.set()
    worker.join(timeout=1)
    assert not worker.is_alive()


def test_all_excluded_symbols_remain_in_diagnostic_logs(daily_run, caplog):
    finder, _, _, _, stages = daily_run["prepare"].return_value
    event_symbols = [f"EVENT{i}" for i in range(7)]
    special_symbols = [f"PRTH{i}" for i in range(7)]
    candidates = event_symbols + special_symbols + ["MOMO", "HELD"]
    daily_run["prepare"].return_value = finder, candidates, [], set(candidates), stages
    with caplog.at_level(logging.INFO, logger="main"):
        main.main()
    message = sent_messages(daily_run)[0]
    assert "최종 매수 후보: 2종목" in message
    assert stages["event_quarantine_excluded_symbol_list"] == ", ".join(event_symbols)
    assert stages["special_situation_excluded_symbol_list"] == ", ".join(special_symbols)
    for symbol in event_symbols + special_symbols:
        assert f"symbol={symbol} excluded reason=" in caplog.text
        assert symbol not in message
    for line in main.build_buy_funnel_lines(stages):
        assert line in caplog.messages


def test_configured_benchmarks_are_forwarded_and_available_metrics_shown(daily_run, monkeypatch):
    monkeypatch.setenv("PERFORMANCE_REPORT_BENCHMARKS", "QQQ,DIA")
    finder, _, _, _, stages = daily_run["prepare"].return_value
    daily_run["prepare"].return_value = finder, [], [], set(), stages
    daily_run["shares"].clear()
    daily_run["decisions"].clear()
    summary = {
        "start_date": "2026-05-26",
        "end_date": "2026-08-26",
        "cumulative_return_pct": 7.2,
        "cumulative_return_QQQ_pct": 5.0,
        "excess_return_vs_QQQ": 2.2,
        "max_drawdown_pct": -6.8,
    }

    def build_report(_args):
        daily_run["summary_path"].parent.mkdir()
        daily_run["summary_path"].write_text(json.dumps(summary), encoding="utf-8")

    daily_run["builder"].side_effect = build_report
    main.main()
    message = sent_message(daily_run)
    assert daily_run["builder"].call_args.args[0].benchmarks == ["QQQ", "DIA"]
    assert "QQQ: +5.00%" in message
    assert "초과수익: QQQ 대비 +2.20%p" in message
    assert "DIA:" not in message
    assert "SPY:" not in message
    assert "IWM:" not in message
    assert "매수 신호" not in message
    assert "매도 신호" not in message


def test_telegram_failure_remains_observable_without_duplicate_sends(daily_run, caplog):
    from telegram.error import TelegramError

    daily_run["bot"].sendMessage.side_effect = TelegramError("delivery failed")
    with pytest.raises(TelegramError), caplog.at_level(logging.WARNING, logger="main"):
        main.main()
    assert "Daily Telegram notification failed: delivery failed" in caplog.text
    daily_run["bot"].sendMessage.assert_awaited_once()


def test_legacy_funnel_argument_does_not_leak_into_telegram():
    lines = ["[Buy Funnel]", "Initial: 96", "매수 제외: PRTH"]
    message = main.generate_telegram_message([], ["MOMO"], [], buy_funnel_lines=lines)
    assert "신규 매수: MOMO" in "\n".join(message)
    assert all(line not in message for line in lines)
    assert main.generate_telegram_message(["MOMO"], ["MOMO"], [], buy_funnel_lines=lines) is None


@pytest.mark.parametrize("value", [None, "invalid", float("nan"), float("inf"), float("-inf")])
def test_missing_benchmark_metrics_do_not_invent_returns_or_excess(value):
    summary = {
        **SUMMARY,
        "cumulative_return_SPY_pct": value,
        "cumulative_return_IWM_pct": None,
        "excess_return_vs_IWM": 100.0,
    }
    message = build_performance_summary_message(summary, REPORT_URL)
    assert "SPY:" not in message
    assert "IWM:" not in message
    assert "초과수익" not in message
    assert "전략: +7.20%" in message
    assert "최대 낙폭(MDD): -6.80%" in message
    assert f"상세: {REPORT_URL}" in message


def test_unavailable_strategy_metrics_are_marked_without_fabrication():
    message = build_performance_summary_message({"start_date": None, "end_date": None}, REPORT_URL)
    assert "전략 성과 (N/A ~ N/A)" in message
    assert "전략: N/A" in message
    assert "최대 낙폭(MDD): N/A" in message
    assert "초과수익" not in message


@pytest.mark.parametrize("body", ["X" * 10000, ("매수 수량: 5주 📈\n" * 800)])
def test_oversized_reports_are_split_without_losing_trade_details(monkeypatch, body):
    bot = MagicMock()
    bot.sendMessage = AsyncMock()
    monkeypatch.setattr("telegram_utils.telegram.Bot", lambda *_args: bot)
    message = build_daily_report_message("2026-08-26", 100, ["2026-08-26", body])
    asyncio.run(send_telegram_message("fake-token", "fake-chat", message))
    chunks = [call.kwargs["text"] for call in bot.sendMessage.call_args_list]
    assert len(chunks) > 1
    assert all(0 < len(chunk.encode("utf-16-le")) // 2 <= 4096 for chunk in chunks)
    assert "".join(chunks) == message
