from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from polymarket_btc_bot.paper import PaperAnalyst


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def default_raw_path(now: datetime | None = None) -> Path:
    ts = now or datetime.now(tz=UTC)
    return Path("data/raw") / ts.date().isoformat() / "events.jsonl"


@dataclass(frozen=True)
class RawEventWriter:
    path: Path

    def append_many(self, events: Iterable[dict[str, Any]]) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
        return self.path

    def tail(self, limit: int = 10) -> list[dict[str, Any]]:
        if limit <= 0 or not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[-limit:] if line.strip()]


class RawCollector:
    def __init__(self, analyst: PaperAnalyst, writer: RawEventWriter | None = None) -> None:
        self.analyst = analyst
        self.writer = writer or RawEventWriter(default_raw_path())

    def collect_once(self) -> dict[str, Any]:
        snapshot = self.analyst.snapshot()
        events = snapshot_to_raw_events(snapshot)
        path = self.writer.append_many(events)
        return {
            "path": str(path),
            "events_written": len(events),
            "event_types": [event["event_type"] for event in events],
            "market_id": snapshot["market"]["market_id"],
            "state_source": snapshot["risk_state"]["state_source"],
            "book_source": snapshot["risk_state"]["book_source"],
            "decision_action": snapshot["decision"]["action"],
            "execution_status": (snapshot.get("execution_state") or {}).get("status"),
        }


def snapshot_to_raw_events(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    observed_ts = utc_now_iso()
    market = snapshot["market"]
    risk = snapshot["risk_state"]
    base = {
        "observed_ts": observed_ts,
        "market_id": market["market_id"],
        "market_data_mode": risk.get("market_data_mode"),
        "state_source": risk.get("state_source"),
    }
    return [
        {
            **base,
            "event_type": "btc_tick",
            "payload": snapshot["btc_tick"],
        },
        {
            **base,
            "event_type": "market_state",
            "payload": {
                "market": market,
                "schedule_reason": risk.get("schedule_reason"),
                "reference_price": risk.get("reference_price"),
            },
        },
        {
            **base,
            "event_type": "orderbook_snapshot",
            "outcome": "UP",
            "book_source": risk.get("book_source"),
            "payload": snapshot["up_book"],
        },
        {
            **base,
            "event_type": "orderbook_snapshot",
            "outcome": "DOWN",
            "book_source": risk.get("book_source"),
            "payload": snapshot["down_book"],
        },
        {
            **base,
            "event_type": "paper_decision",
            "payload": snapshot["decision"],
        },
        {
            **base,
            "event_type": "risk_validation",
            "payload": risk.get("risk_validation"),
        },
        {
            **base,
            "event_type": "paper_execution",
            "payload": snapshot.get("execution_state"),
        },
    ]
