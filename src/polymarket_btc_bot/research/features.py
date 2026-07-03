from __future__ import annotations

import csv
import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FeatureSnapshotRow:
    observed_ts: str
    market_id: str
    market_data_mode: str | None
    state_source: str | None
    book_source: str | None
    btc_price: float | None
    reference_price: float | None
    seconds_to_close: int | None
    up_best_bid: float | None
    up_best_ask: float | None
    up_spread: float | None
    down_best_bid: float | None
    down_best_ask: float | None
    down_spread: float | None
    probability_up: float | None
    edge: float | None
    action: str | None
    target_price: float | None
    risk_approved: bool | None
    risk_reason_code: str | None
    execution_status: str | None
    execution_reason: str | None
    replay_ready: bool
    blocking_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


def build_feature_snapshots(raw_path: Path | str) -> list[FeatureSnapshotRow]:
    events = _read_events(Path(raw_path))
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        key = (str(event.get("observed_ts")), str(event.get("market_id")))
        cycle = grouped.setdefault(key, {"observed_ts": key[0], "market_id": key[1]})
        event_type = event.get("event_type")
        if event_type == "orderbook_snapshot":
            outcome = str(event.get("outcome") or "").lower()
            cycle[f"{outcome}_book"] = event
        else:
            cycle[str(event_type)] = event

    return [_cycle_to_row(cycle) for cycle in grouped.values()]


def write_feature_snapshots_csv(rows: list[FeatureSnapshotRow], path: Path | str) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    names = [field.name for field in fields(FeatureSnapshotRow)]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())
    return output_path


def _cycle_to_row(cycle: dict[str, Any]) -> FeatureSnapshotRow:
    market_state = cycle.get("market_state") or {}
    btc_tick = cycle.get("btc_tick") or {}
    up_book = cycle.get("up_book") or {}
    down_book = cycle.get("down_book") or {}
    decision = cycle.get("paper_decision") or {}
    risk_validation = cycle.get("risk_validation") or {}
    execution = cycle.get("paper_execution") or {}

    state_source = _first_present(cycle, "state_source")
    book_source = (up_book.get("book_source") or down_book.get("book_source")) if up_book or down_book else None
    blocking_reason = _blocking_reason(cycle, state_source, book_source)
    return FeatureSnapshotRow(
        observed_ts=str(cycle.get("observed_ts")),
        market_id=str(cycle.get("market_id")),
        market_data_mode=_first_present(cycle, "market_data_mode"),
        state_source=state_source,
        book_source=book_source,
        btc_price=_as_float(_payload(btc_tick).get("price")),
        reference_price=_as_float(_payload(market_state).get("reference_price")),
        seconds_to_close=_as_int((_payload(market_state).get("market") or {}).get("seconds_to_close")),
        up_best_bid=_as_float(_payload(up_book).get("best_bid")),
        up_best_ask=_as_float(_payload(up_book).get("best_ask")),
        up_spread=_as_float(_payload(up_book).get("spread")),
        down_best_bid=_as_float(_payload(down_book).get("best_bid")),
        down_best_ask=_as_float(_payload(down_book).get("best_ask")),
        down_spread=_as_float(_payload(down_book).get("spread")),
        probability_up=_as_float(_payload(decision).get("probability_up")),
        edge=_as_float(_payload(decision).get("edge")),
        action=_payload(decision).get("action"),
        target_price=_as_float(_payload(decision).get("target_price")),
        risk_approved=_payload(risk_validation).get("approved"),
        risk_reason_code=_payload(risk_validation).get("reason_code"),
        execution_status=_payload(execution).get("status"),
        execution_reason=_payload(execution).get("reason"),
        replay_ready=blocking_reason is None,
        blocking_reason=blocking_reason,
    )


def _blocking_reason(cycle: dict[str, Any], state_source: str | None, book_source: str | None) -> str | None:
    required = ("btc_tick", "market_state", "up_book", "down_book", "paper_decision")
    missing = [name for name in required if name not in cycle]
    if missing:
        return f"missing:{','.join(missing)}"
    if not state_source or "demo" in state_source or "fallback" in state_source or state_source.startswith("live_unavailable"):
        return "non_live_market_state"
    if not book_source or "demo" in book_source or "fallback" in book_source or book_source.startswith("clob_unavailable"):
        return "non_live_orderbook"
    return None


def _first_present(cycle: dict[str, Any], key: str) -> str | None:
    for value in cycle.values():
        if isinstance(value, dict) and value.get(key) is not None:
            return str(value[key])
    return None


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event, dict) else None
    return payload if isinstance(payload, dict) else {}


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
