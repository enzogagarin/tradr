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
    fees: float = 0.0
    levels_used: int = 1

    def to_dict(self) -> dict:
        return {
            "price": self.price,
            "shares": self.shares,
            "notional": self.notional,
            "liquidity": self.liquidity,
            "filled_ts": self.filled_ts.isoformat(),
            "fees": self.fees,
            "levels_used": self.levels_used,
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
    """Simulate a taker order crossing the book.

    A realistic paper fill walks multiple ask levels (so larger orders pay a
    worse VWAP), applies a slippage penalty per fill (a proxy for quote/latency
    drift), and charges a taker fee on notional. With the zero defaults it
    reduces to a top-of-book fill.
    """

    def __init__(self, fee_bps: float = 0.0, slippage: float = 0.0, max_levels: int = 5) -> None:
        self.fee_bps = max(0.0, fee_bps)
        self.slippage = max(0.0, slippage)
        self.max_levels = max(1, max_levels)

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

        # Walk ask levels (ascending) up to the limit price, accumulating a VWAP.
        asks = sorted(book.asks, key=lambda level: level.price)
        remaining = requested_shares
        filled_shares = 0.0
        gross_cost = 0.0
        levels_used = 0
        for level in asks[: self.max_levels]:
            if remaining <= 0:
                break
            fill_price = min(0.999, level.price + self.slippage)
            if fill_price > decision.target_price:
                break
            take = min(remaining, level.size)
            if take <= 0:
                continue
            gross_cost += take * fill_price
            filled_shares += take
            remaining -= take
            levels_used += 1

        filled_shares = round(filled_shares, 6)
        if filled_shares <= 0:
            return PaperExecutionResult("REJECTED", "zero_fill_size", None, None, now)

        avg_price = gross_cost / filled_shares
        notional = round(gross_cost, 4)
        fees = round(notional * self.fee_bps / 10_000.0, 6)

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
            price=round(avg_price, 4),
            shares=filled_shares,
            notional=notional,
            liquidity="TAKER_MULTI_LEVEL" if levels_used > 1 else "TAKER_TOP_OF_BOOK",
            filled_ts=now,
            fees=fees,
            levels_used=levels_used,
        )
        status = "FILLED" if filled_shares >= requested_shares - 1e-9 else "PARTIAL_FILL"
        reason = "simulated_multi_level_fill" if levels_used > 1 else "simulated_top_of_book_fill"
        return PaperExecutionResult(status, reason, order, fill, now)


def _client_order_id(now: datetime, outcome: str) -> str:
    timestamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    return f"paper-{outcome.lower()}-{timestamp}"
