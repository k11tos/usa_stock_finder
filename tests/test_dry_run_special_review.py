from unittest.mock import Mock

from tools import dry_run_special_review
from tools.dry_run_special_review import (
    _parse_symbol_reason,
    build_review_packet,
    render_review_packets,
)


def test_parse_symbol_reason_defaults_and_validates():
    parsed = _parse_symbol_reason(["aapl", "ewcz:pinned_price"])
    assert parsed == [("AAPL", "event_quarantine"), ("EWCZ", "pinned_price")]


def test_build_review_packet_event_quarantine_without_news_api(monkeypatch):
    monkeypatch.delenv("NEWS_API_KEY", raising=False)
    finder = Mock()
    finder.get_event_quarantine_metrics.return_value = {
        "is_event_quarantine": True,
        "max_gap_up_pct": 0.2,
    }

    packet = build_review_packet(finder, "GAPX", "event_quarantine")

    assert packet["symbol"] == "GAPX"
    assert packet["price_based_reason"] == "event_quarantine"
    assert packet["key_metrics"]["is_event_quarantine"] is True
    assert packet["external_review_placeholder"] == "No news API configured. Price-based review only."


def test_render_review_packets_contains_explanation_only_note():
    output = render_review_packets(
        [
            {
                "symbol": "EWCZ",
                "price_based_reason": "pinned_price",
                "key_metrics": {"is_special_situation": True},
                "external_review_placeholder": "No news API configured. Price-based review only.",
            }
        ]
    )

    assert "Explanation-only report" in output
    assert "EWCZ" in output
    assert "pinned_price" in output


def test_main_builds_finder_with_symbols_and_prints_json(monkeypatch, capsys):
    finder_instance = Mock()
    finder_ctor = Mock(return_value=finder_instance)
    packet_builder = Mock(
        side_effect=lambda _finder, symbol, reason: {
            "symbol": symbol,
            "price_based_reason": reason,
            "key_metrics": {"ok": True},
            "external_review_placeholder": "No news API configured. Price-based review only.",
            "decision_policy_note": "Explanation-only",
        }
    )

    monkeypatch.setattr(dry_run_special_review, "UsaStockFinder", finder_ctor)
    monkeypatch.setattr(dry_run_special_review, "build_review_packet", packet_builder)
    monkeypatch.setattr(
        "sys.argv",
        [
            "dry_run_special_review.py",
            "--symbol-reason",
            "gapx:event_quarantine",
            "ewcz:pinned_price",
            "--json",
        ],
    )

    code = dry_run_special_review.main()
    out = capsys.readouterr().out

    assert code == 0
    finder_ctor.assert_called_once_with(["GAPX", "EWCZ"])
    assert packet_builder.call_count == 2
    assert '"symbol": "GAPX"' in out
    assert '"symbol": "EWCZ"' in out
