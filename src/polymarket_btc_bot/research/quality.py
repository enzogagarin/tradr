from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DataQualityReport:
    path: str
    total_events: int
    market_count: int
    event_counts: dict[str, int]
    state_source_counts: dict[str, int]
    book_source_counts: dict[str, int]
    market_event_counts: dict[str, dict[str, int]]
    first_observed_ts: str | None
    last_observed_ts: str | None
    live_event_ratio: float
    demo_or_fallback_ratio: float
    complete_cycles_estimate: int
    sufficient_for_replay: bool
    blocking_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "total_events": self.total_events,
            "market_count": self.market_count,
            "event_counts": self.event_counts,
            "state_source_counts": self.state_source_counts,
            "book_source_counts": self.book_source_counts,
            "market_event_counts": self.market_event_counts,
            "first_observed_ts": self.first_observed_ts,
            "last_observed_ts": self.last_observed_ts,
            "live_event_ratio": self.live_event_ratio,
            "demo_or_fallback_ratio": self.demo_or_fallback_ratio,
            "complete_cycles_estimate": self.complete_cycles_estimate,
            "sufficient_for_replay": self.sufficient_for_replay,
            "blocking_reasons": self.blocking_reasons,
        }


def build_data_quality_report(path: Path | str) -> DataQualityReport:
    raw_path = Path(path)
    events = _read_events(raw_path)
    event_counts = Counter(event.get("event_type", "unknown") for event in events)
    state_source_counts = Counter(str(event.get("state_source") or "unknown") for event in events)
    book_source_counts = Counter(str(event.get("book_source") or "none") for event in events)
    market_counts: dict[str, Counter] = defaultdict(Counter)
    observed_ts_values: list[str] = []

    for event in events:
        market_id = str(event.get("market_id") or "unknown")
        market_counts[market_id][str(event.get("event_type") or "unknown")] += 1
        if event.get("observed_ts"):
            observed_ts_values.append(str(event["observed_ts"]))

    live_events = sum(count for source, count in state_source_counts.items() if source.startswith("gamma"))
    demo_or_fallback_events = sum(
        count
        for source, count in state_source_counts.items()
        if "demo" in source or "fallback" in source or source.startswith("live_unavailable")
    )
    complete_cycles = _complete_cycle_estimate(event_counts)
    blocking_reasons = _blocking_reasons(events, event_counts, live_events, complete_cycles)

    return DataQualityReport(
        path=str(raw_path),
        total_events=len(events),
        market_count=len({event.get("market_id") for event in events if event.get("market_id")}),
        event_counts=dict(sorted(event_counts.items())),
        state_source_counts=dict(sorted(state_source_counts.items())),
        book_source_counts=dict(sorted(book_source_counts.items())),
        market_event_counts={market: dict(sorted(counts.items())) for market, counts in sorted(market_counts.items())},
        first_observed_ts=min(observed_ts_values) if observed_ts_values else None,
        last_observed_ts=max(observed_ts_values) if observed_ts_values else None,
        live_event_ratio=round(live_events / len(events), 4) if events else 0.0,
        demo_or_fallback_ratio=round(demo_or_fallback_events / len(events), 4) if events else 0.0,
        complete_cycles_estimate=complete_cycles,
        sufficient_for_replay=not blocking_reasons,
        blocking_reasons=blocking_reasons,
    )


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    return events


def _complete_cycle_estimate(event_counts: Counter) -> int:
    required = {
        "btc_tick": 1,
        "market_state": 1,
        "orderbook_snapshot": 2,
        "paper_decision": 1,
        "risk_validation": 1,
        "paper_execution": 1,
    }
    if not event_counts:
        return 0
    return min(event_counts.get(event_type, 0) // needed for event_type, needed in required.items())


def _blocking_reasons(
    events: list[dict[str, Any]],
    event_counts: Counter,
    live_events: int,
    complete_cycles: int,
) -> list[str]:
    reasons: list[str] = []
    if not events:
        return ["no_raw_events"]
    if complete_cycles == 0:
        reasons.append("no_complete_collection_cycle")
    if live_events == 0:
        reasons.append("no_live_market_events")
    if event_counts.get("orderbook_snapshot", 0) < 2:
        reasons.append("missing_up_down_orderbooks")
    if event_counts.get("btc_tick", 0) == 0:
        reasons.append("missing_btc_ticks")
    if event_counts.get("paper_decision", 0) == 0:
        reasons.append("missing_decisions")
    if _has_invalid_timestamp(events):
        reasons.append("invalid_observed_timestamp")
    return reasons


def _has_invalid_timestamp(events: list[dict[str, Any]]) -> bool:
    for event in events:
        value = event.get("observed_ts")
        if not value:
            return True
        try:
            datetime.fromisoformat(str(value))
        except ValueError:
            return True
    return False
