import json

from polymarket_btc_bot.research import build_feature_snapshots, write_feature_snapshots_csv


def test_build_feature_snapshots_marks_demo_rows_not_replay_ready(tmp_path):
    raw_path = tmp_path / "events.jsonl"
    events = [
        {
            "event_type": "btc_tick",
            "observed_ts": "2026-07-03T00:00:00+00:00",
            "market_id": "m1",
            "market_data_mode": "demo",
            "state_source": "demo_market",
            "payload": {"price": 100_000.0},
        },
        {
            "event_type": "market_state",
            "observed_ts": "2026-07-03T00:00:00+00:00",
            "market_id": "m1",
            "market_data_mode": "demo",
            "state_source": "demo_market",
            "payload": {"reference_price": 99_950.0, "market": {"seconds_to_close": 120}},
        },
        {
            "event_type": "orderbook_snapshot",
            "outcome": "UP",
            "observed_ts": "2026-07-03T00:00:00+00:00",
            "market_id": "m1",
            "book_source": "demo_book",
            "payload": {"best_bid": 0.49, "best_ask": 0.51, "spread": 0.02},
        },
        {
            "event_type": "orderbook_snapshot",
            "outcome": "DOWN",
            "observed_ts": "2026-07-03T00:00:00+00:00",
            "market_id": "m1",
            "book_source": "demo_book",
            "payload": {"best_bid": 0.48, "best_ask": 0.52, "spread": 0.04},
        },
        {
            "event_type": "paper_decision",
            "observed_ts": "2026-07-03T00:00:00+00:00",
            "market_id": "m1",
            "payload": {"probability_up": 0.56, "edge": 0.05, "action": "BUY_UP", "target_price": 0.51},
        },
        {
            "event_type": "risk_validation",
            "observed_ts": "2026-07-03T00:00:00+00:00",
            "market_id": "m1",
            "payload": {"approved": True, "reason_code": "approved"},
        },
        {
            "event_type": "paper_execution",
            "observed_ts": "2026-07-03T00:00:00+00:00",
            "market_id": "m1",
            "payload": {"status": "FILLED", "reason": "filled"},
        },
    ]
    raw_path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")

    rows = build_feature_snapshots(raw_path)

    assert len(rows) == 1
    assert rows[0].btc_price == 100_000.0
    assert rows[0].up_best_ask == 0.51
    assert rows[0].probability_up == 0.56
    assert rows[0].replay_ready is False
    assert rows[0].blocking_reason == "non_live_market_state"


def test_write_feature_snapshots_csv(tmp_path):
    raw_path = tmp_path / "events.jsonl"
    raw_path.write_text("", encoding="utf-8")
    rows = build_feature_snapshots(raw_path)
    output_path = tmp_path / "features.csv"

    write_feature_snapshots_csv(rows, output_path)

    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8").startswith("observed_ts,market_id")
