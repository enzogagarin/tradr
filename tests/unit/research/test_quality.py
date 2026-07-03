from pathlib import Path

from polymarket_btc_bot.collector import RawEventWriter
from polymarket_btc_bot.collector.raw import snapshot_to_raw_events
from polymarket_btc_bot.research import build_data_quality_report


def _snapshot(state_source="gamma_live", book_source="clob_live"):
    return {
        "market": {
            "market_id": "m1",
            "slug": "btc-updown",
            "question": "BTC up?",
            "seconds_to_close": 120,
        },
        "btc_tick": {"price": 62000, "venue": "test"},
        "up_book": {"asset_id": "up", "bids": [{"price": 0.5, "size": 10}], "asks": [{"price": 0.52, "size": 10}]},
        "down_book": {"asset_id": "down", "bids": [{"price": 0.47, "size": 10}], "asks": [{"price": 0.49, "size": 10}]},
        "decision": {"action": "NO_TRADE", "reason": "edge_below_threshold"},
        "execution_state": {"status": "SKIPPED"},
        "risk_state": {
            "market_data_mode": "live",
            "state_source": state_source,
            "book_source": book_source,
            "schedule_reason": "active_market_tradable",
            "reference_price": 61990,
            "risk_validation": {"approved": True, "reason_code": "no_order_intent"},
        },
    }


def test_quality_report_marks_missing_file_as_not_replayable(tmp_path):
    report = build_data_quality_report(tmp_path / "missing.jsonl")

    assert report.total_events == 0
    assert report.sufficient_for_replay is False
    assert report.blocking_reasons == ["no_raw_events"]


def test_quality_report_rejects_demo_only_data_for_replay(tmp_path):
    path = Path(tmp_path) / "events.jsonl"
    RawEventWriter(path).append_many(
        snapshot_to_raw_events(_snapshot(state_source="auto_demo_no_live_btc_5m_market", book_source="demo_book"))
    )

    report = build_data_quality_report(path)

    assert report.total_events == 7
    assert report.complete_cycles_estimate == 1
    assert report.live_event_ratio == 0
    assert report.demo_or_fallback_ratio == 1
    assert report.sufficient_for_replay is False
    assert "no_live_market_events" in report.blocking_reasons


def test_quality_report_accepts_complete_live_cycle_for_replay(tmp_path):
    path = Path(tmp_path) / "events.jsonl"
    RawEventWriter(path).append_many(snapshot_to_raw_events(_snapshot()))

    report = build_data_quality_report(path)

    assert report.total_events == 7
    assert report.event_counts["orderbook_snapshot"] == 2
    assert report.complete_cycles_estimate == 1
    assert report.live_event_ratio == 1
    assert report.demo_or_fallback_ratio == 0
    assert report.sufficient_for_replay is True
    assert report.blocking_reasons == []
