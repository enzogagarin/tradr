from __future__ import annotations

import json
from datetime import UTC, datetime

from polymarket_btc_bot.domain import StrategyDecision
from polymarket_btc_bot.scheduler import CycleGate, CycleGateConfig


def _decision(now: datetime) -> StrategyDecision:
    return StrategyDecision("BUY_UP", 0.62, 0.08, 0.54, "baseline_edge_up", now)


def test_cycle_gate_blocks_during_analysis(tmp_path):
    now = datetime.fromtimestamp(1_000_000_260, tz=UTC)
    gate = CycleGate(CycleGateConfig(enabled=True, audit_path=tmp_path / "audit.jsonl"))

    state = gate.evaluate(now)
    decision = gate.apply(_decision(now), state)

    assert state.phase == "ANALYZING"
    assert not state.allows_new_trade
    assert decision.action == "NO_TRADE"
    assert decision.reason.startswith("cycle_analyzing|")


def test_cycle_gate_allows_entry_window(tmp_path):
    now = datetime.fromtimestamp(1_000_000_440, tz=UTC)
    gate = CycleGate(CycleGateConfig(enabled=True, audit_path=tmp_path / "audit.jsonl"))

    state = gate.evaluate(now)
    decision = gate.apply(_decision(now), state)

    assert state.phase == "ENTRY_WINDOW"
    assert state.allows_new_trade
    assert decision.action == "BUY_UP"


def test_cycle_gate_blocks_after_trade_taken(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    now = datetime.fromtimestamp(1_000_000_440, tz=UTC)
    audit_path.write_text(
        json.dumps(
            {
                "event_type": "paper_decision",
                "execution": {
                    "status": "FILLED",
                    "observed_ts": now.isoformat(),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gate = CycleGate(CycleGateConfig(enabled=True, audit_path=audit_path))

    state = gate.evaluate(now)
    decision = gate.apply(_decision(now), state)

    assert state.phase == "TRADE_TAKEN"
    assert state.trades_taken == 1
    assert decision.action == "NO_TRADE"
    assert decision.reason.startswith("cycle_trade_taken|")


def test_cycle_gate_blocks_cooldown(tmp_path):
    now = datetime.fromtimestamp(1_000_000_730, tz=UTC)
    gate = CycleGate(CycleGateConfig(enabled=True, audit_path=tmp_path / "audit.jsonl"))

    state = gate.evaluate(now)

    assert state.phase == "COOLDOWN"
    assert not state.allows_new_trade
