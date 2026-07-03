from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from polymarket_btc_bot.risk import RiskState


def default_ledger_path() -> Path:
    return Path("data/portfolio/ledger.json")


@dataclass
class LedgerPosition:
    """A single paper position taken in one BTC Up/Down market cycle.

    A position is opened when a paper order fills and settled once the market's
    5m candle closes: UP wins if candle close > open, DOWN wins otherwise.
    Payout per winning share is 1.0 USDC; a losing share is worth 0.
    """

    position_id: str
    market_id: str
    slug: str
    outcome: str  # "UP" | "DOWN"
    asset_id: str
    shares: float
    avg_price: float
    cost: float
    opened_ts: str
    end_ts: str
    cycle_open_epoch: int
    reference_open: float
    fees: float = 0.0
    status: str = "OPEN"  # "OPEN" | "SETTLED"
    won: bool | None = None
    payout: float = 0.0
    realized_pnl: float = 0.0
    settled_ts: str | None = None
    settle_close: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PortfolioLedger:
    """Persistent paper portfolio: positions, exposure, realized PnL.

    This is the single source of truth for risk state so that exposure, daily
    loss, and per-market trade limits actually bind (previously the analyst
    rebuilt an empty RiskState every snapshot, making all limits non-functional).
    Only the executing loop should mutate it; the dashboard reads it.
    """

    path: Path = field(default_factory=default_ledger_path)
    starting_bankroll: float = 1000.0
    positions: list[LedgerPosition] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | str | None = None, starting_bankroll: float = 1000.0) -> "PortfolioLedger":
        p = Path(path) if path is not None else default_ledger_path()
        ledger = cls(path=p, starting_bankroll=starting_bankroll)
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                ledger.starting_bankroll = float(raw.get("starting_bankroll", starting_bankroll))
                ledger.positions = [LedgerPosition(**row) for row in raw.get("positions", [])]
            except (OSError, ValueError, TypeError):
                ledger.positions = []
        return ledger

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "starting_bankroll": self.starting_bankroll,
            "positions": [p.to_dict() for p in self.positions],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    # --- mutations -------------------------------------------------------
    def record_fill(
        self,
        *,
        market_id: str,
        slug: str,
        outcome: str,
        asset_id: str,
        shares: float,
        price: float,
        fees: float,
        end_ts: datetime,
        cycle_open_epoch: int,
        reference_open: float,
        now: datetime | None = None,
    ) -> LedgerPosition:
        now = now or datetime.now(tz=UTC)
        cost = round(shares * price, 6)
        position = LedgerPosition(
            position_id=f"{market_id}:{outcome}:{now.strftime('%Y%m%dT%H%M%S%fZ')}",
            market_id=market_id,
            slug=slug,
            outcome=outcome,
            asset_id=asset_id,
            shares=round(shares, 6),
            avg_price=round(price, 6),
            cost=cost,
            fees=round(fees, 6),
            opened_ts=now.isoformat(),
            end_ts=end_ts.isoformat(),
            cycle_open_epoch=int(cycle_open_epoch),
            reference_open=round(reference_open, 4),
        )
        self.positions.append(position)
        self.save()
        return position

    def settle_due(
        self,
        now: datetime,
        resolver: Callable[[LedgerPosition], bool | None],
    ) -> list[LedgerPosition]:
        """Settle every open position whose market cycle has closed.

        `resolver(position)` returns True if UP won, False if DOWN won, or None
        if the outcome is not yet known (leave the position open).
        """
        settled: list[LedgerPosition] = []
        changed = False
        for pos in self.positions:
            if pos.status != "OPEN":
                continue
            end = _parse(pos.end_ts)
            if end is None or end > now:
                continue
            up_won = resolver(pos)
            if up_won is None:
                continue
            pos.won = up_won if pos.outcome == "UP" else (not up_won)
            pos.payout = round(pos.shares * (1.0 if pos.won else 0.0), 6)
            pos.realized_pnl = round(pos.payout - pos.cost - pos.fees, 6)
            pos.status = "SETTLED"
            pos.settled_ts = now.isoformat()
            settled.append(pos)
            changed = True
        if changed:
            self.save()
        return settled

    # --- read state ------------------------------------------------------
    def open_positions(self) -> list[LedgerPosition]:
        return [p for p in self.positions if p.status == "OPEN"]

    def open_exposure(self) -> float:
        return round(sum(p.cost + p.fees for p in self.open_positions()), 6)

    def trades_in_market(self, market_id: str) -> int:
        return sum(1 for p in self.positions if p.market_id == market_id)

    def realized_pnl_total(self) -> float:
        return round(sum(p.realized_pnl for p in self.positions if p.status == "SETTLED"), 6)

    def daily_pnl(self, now: datetime | None = None) -> float:
        now = now or datetime.now(tz=UTC)
        day = now.date()
        total = 0.0
        for p in self.positions:
            if p.status != "SETTLED" or not p.settled_ts:
                continue
            ts = _parse(p.settled_ts)
            if ts is not None and ts.date() == day:
                total += p.realized_pnl
        return round(total, 6)

    def risk_state_for(self, market_id: str, now: datetime | None = None) -> RiskState:
        return RiskState(
            open_exposure=max(0.0, self.open_exposure()),
            daily_pnl=self.daily_pnl(now),
            trades_in_market=self.trades_in_market(market_id),
        )

    def summary(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(tz=UTC)
        settled = [p for p in self.positions if p.status == "SETTLED"]
        wins = sum(1 for p in settled if p.won)
        losses = sum(1 for p in settled if p.won is False)
        realized = self.realized_pnl_total()
        return {
            "starting_bankroll": self.starting_bankroll,
            "equity": round(self.starting_bankroll + realized, 4),
            "realized_pnl": realized,
            "daily_pnl": self.daily_pnl(now),
            "open_positions": len(self.open_positions()),
            "open_exposure": self.open_exposure(),
            "settled_positions": len(settled),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / max(1, wins + losses), 4),
            "total_fees": round(sum(p.fees for p in self.positions), 4),
        }


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None
