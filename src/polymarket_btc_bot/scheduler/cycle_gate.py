from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from polymarket_btc_bot.audit import default_audit_path
from polymarket_btc_bot.domain import StrategyDecision


@dataclass(frozen=True)
class CycleGateConfig:
    enabled: bool = False
    length_seconds: int = 600
    analysis_seconds: int = 180
    cooldown_seconds: int = 90
    max_trades: int = 1
    audit_path: Path | str | None = None


@dataclass(frozen=True)
class CycleGateState:
    enabled: bool
    cycle_id: int
    phase: str
    elapsed_seconds: int
    seconds_remaining: int
    entry_opens_in_seconds: int
    entry_closes_in_seconds: int
    trades_taken: int
    allows_new_trade: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "cycle_id": self.cycle_id,
            "phase": self.phase,
            "elapsed_seconds": self.elapsed_seconds,
            "seconds_remaining": self.seconds_remaining,
            "entry_opens_in_seconds": self.entry_opens_in_seconds,
            "entry_closes_in_seconds": self.entry_closes_in_seconds,
            "trades_taken": self.trades_taken,
            "allows_new_trade": self.allows_new_trade,
            "reason": self.reason,
        }


class CycleGate:
    def __init__(self, config: CycleGateConfig) -> None:
        self.config = config

    def evaluate(self, now: datetime) -> CycleGateState:
        length = self.config.length_seconds
        ts = int(now.timestamp())
        cycle_id = ts // length
        elapsed = ts - (cycle_id * length)
        remaining = max(0, length - elapsed)
        entry_opens_in = max(0, self.config.analysis_seconds - elapsed)
        entry_closes_in = max(0, length - self.config.cooldown_seconds - elapsed)
        trades_taken = self._trades_taken(cycle_id)

        if not self.config.enabled:
            return CycleGateState(
                enabled=False,
                cycle_id=cycle_id,
                phase="DISABLED",
                elapsed_seconds=elapsed,
                seconds_remaining=remaining,
                entry_opens_in_seconds=entry_opens_in,
                entry_closes_in_seconds=entry_closes_in,
                trades_taken=trades_taken,
                allows_new_trade=True,
                reason="cycle_disabled",
            )

        if elapsed < self.config.analysis_seconds:
            phase = "ANALYZING"
            allows = False
            reason = "cycle_analyzing"
        elif remaining <= self.config.cooldown_seconds:
            phase = "COOLDOWN"
            allows = False
            reason = "cycle_cooldown"
        else:
            phase = "ENTRY_WINDOW"
            allows = True
            reason = "cycle_entry_window"

        if allows and trades_taken >= self.config.max_trades:
            phase = "TRADE_TAKEN"
            allows = False
            reason = "cycle_trade_taken"

        return CycleGateState(
            enabled=True,
            cycle_id=cycle_id,
            phase=phase,
            elapsed_seconds=elapsed,
            seconds_remaining=remaining,
            entry_opens_in_seconds=entry_opens_in,
            entry_closes_in_seconds=entry_closes_in,
            trades_taken=trades_taken,
            allows_new_trade=allows,
            reason=reason,
        )

    def apply(self, decision: StrategyDecision, state: CycleGateState) -> StrategyDecision:
        if not state.enabled or state.allows_new_trade:
            return decision
        if decision.action == "NO_TRADE" and decision.reason.startswith("cycle_"):
            return decision
        return StrategyDecision(
            action="NO_TRADE",
            probability_up=decision.probability_up,
            edge=decision.edge,
            target_price=None,
            reason=f"{state.reason}|{decision.reason}",
            observed_ts=decision.observed_ts,
        )

    def _trades_taken(self, cycle_id: int) -> int:
        path = Path(self.config.audit_path) if self.config.audit_path is not None else default_audit_path()
        if not path.exists():
            return 0
        count = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            execution = event.get("execution") or {}
            if execution.get("status") not in {"FILLED", "PARTIAL_FILL"}:
                continue
            observed = execution.get("observed_ts") or event.get("observed_ts")
            if _cycle_id_from_iso(observed, self.config.length_seconds) == cycle_id:
                count += 1
        return count


def _cycle_id_from_iso(value: str | None, length_seconds: int) -> int | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
    return int(ts) // length_seconds
