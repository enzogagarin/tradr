from pathlib import Path

from polymarket_btc_bot.collector import RawCollector, RawEventWriter
from polymarket_btc_bot.collector.raw import snapshot_to_raw_events


def _snapshot():
    return {
        "market": {
            "market_id": "m1",
            "slug": "btc-updown",
            "question": "BTC up?",
            "seconds_to_close": 120,
        },
        "btc_tick": {"price": 62000, "venue": "test"},
        "up_book": {"asset_id": "up", "bids": [], "asks": []},
        "down_book": {"asset_id": "down", "bids": [], "asks": []},
        "decision": {"action": "NO_TRADE", "reason": "edge_below_threshold"},
        "execution_state": {"status": "SKIPPED"},
        "risk_state": {
            "market_data_mode": "demo",
            "state_source": "demo_market",
            "book_source": "demo_book",
            "schedule_reason": "active_market_tradable",
            "reference_price": 61990,
            "risk_validation": {"approved": True, "reason_code": "no_order_intent"},
        },
    }


def test_snapshot_to_raw_events_splits_operational_payloads():
    events = snapshot_to_raw_events(_snapshot())

    assert [event["event_type"] for event in events] == [
        "btc_tick",
        "market_state",
        "orderbook_snapshot",
        "orderbook_snapshot",
        "paper_decision",
        "risk_validation",
        "paper_execution",
    ]
    assert events[2]["outcome"] == "UP"
    assert events[3]["outcome"] == "DOWN"


def test_raw_event_writer_appends_and_tails_jsonl(tmp_path):
    writer = RawEventWriter(tmp_path / "events.jsonl")

    path = writer.append_many(snapshot_to_raw_events(_snapshot()))

    assert path == tmp_path / "events.jsonl"
    assert len(writer.tail(2)) == 2
    assert writer.tail(1)[0]["event_type"] == "paper_execution"


def test_raw_collector_writes_snapshot_events(tmp_path):
    collector = RawCollector(_FakeAnalyst(), RawEventWriter(Path(tmp_path) / "raw.jsonl"))

    summary = collector.collect_once()

    assert summary["events_written"] == 7
    assert summary["event_types"][0] == "btc_tick"
    assert summary["market_id"] == "m1"
    assert summary["decision_action"] == "NO_TRADE"


class _FakeAnalyst:
    def snapshot(self):
        return _snapshot()
