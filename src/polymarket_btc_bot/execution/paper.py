from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from polymarket_btc_bot.domain import OrderBook, StrategyDecision, utc_now


@dataclass(frozen=True)
class PaperOrder:
    client_order_id: str
    side: str
    outcome: str
    asset_id: str
    limit_price: float
    requested_shares: float
    requested_notional: float
    created_ts: datetime

    def to_dict(self) -> dict:
        return {
            "client_order_id": self.client_order_id,
            "side": self.side,
            "outcome": self.outcome,
            "asset_id": self.asset_id,
            "limit_price": self.limit_price,
            "requested_shares": self.requested_shares,
            "requested_notional": self.requested_notional,
            "created_ts": self.created_ts.isoformat(),
        }


@dataclass(frozen=True)
class PaperFill:
    price: float
    shares: float
    notional: float
    liquidity: str
    filled_ts: datetime

    def to_dict(self) -> dict:
        return {
            "price": self.price,
            "shares": self.shares,
            "notional": self.notional,
            "liquidity": self.liquidity,
            "filled_ts": self.filled_ts.isoformat(),
        }


@dataclass(frozen=True)
class PaperExecutionResult:
    status: str
    reason: str
    order: PaperOrder | None
    fill: PaperFill | None
    observed_ts: datetime

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "order": None if self.order is None else self.order.to_dict(),
            "fill": None if self.fill is None else self.fill.to_dict(),
            "observed_ts": self.observed_ts.isoformat(),
        }


class PaperExecutor:
    def reject(self, reason: str) -> PaperExecutionResult:
        return PaperExecutionResult("REJECTED", reason, None, None, utc_now())

    def execute(
        self,
        decision: StrategyDecision,
        up_book: OrderBook,
        down_book: OrderBook,
        max_order_notional: float,
    ) -> PaperExecutionResult:
        now = utc_now()
        if decision.action == "NO_TRADE":
            return PaperExecutionResult("SKIPPED", decision.reason, None, None, now)
        if decision.target_price is None or decision.target_price <= 0:
            return PaperExecutionResult("REJECTED", "missing_target_price", None, None, now)
        if max_order_notional <= 0:
            return PaperExecutionResult("REJECTED", "invalid_max_order_notional", None, None, now)

        outcome, book = ("UP", up_book) if decision.action == "BUY_UP" else ("DOWN", down_book)
        ask = book.best_ask
        if ask is None:
            return PaperExecutionResult("REJECTED", "missing_best_ask", None, None, now)
        if ask.price > decision.target_price:
            return PaperExecutionResult("REJECTED", "best_ask_above_limit", None, None, now)

        requested_shares = round(max_order_notional / decision.target_price, 6)
        fill_shares = round(min(requested_shares, ask.size), 6)
        if fill_shares <= 0:
            return PaperExecutionResult("REJECTED", "zero_fill_size", None, None, now)

        order = PaperOrder(
            client_order_id=_client_order_id(now, outcome),
            side="BUY",
            outcome=outcome,
            asset_id=book.asset_id,
            limit_price=round(decision.target_price, 4),
            requested_shares=requested_shares,
            requested_notional=round(requested_shares * decision.target_price, 4),
            created_ts=now,
        )
        fill = PaperFill(
            price=round(ask.price, 4),
            shares=fill_shares,
            notional=round(fill_shares * ask.price, 4),
            liquidity="TAKER_TOP_OF_BOOK",
            filled_ts=now,
        )
        status = "FILLED" if fill_shares == requested_shares else "PARTIAL_FILL"
        return PaperExecutionResult(status, "simulated_top_of_book_fill", order, fill, now)


def _client_order_id(now: datetime, outcome: str) -> str:
    timestamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    return f"paper-{outcome.lower()}-{timestamp}"
