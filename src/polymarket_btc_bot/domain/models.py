from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any


class BotMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True)
class MarketAsset:
    asset_id: str
    outcome: str

    def __post_init__(self) -> None:
        if not self.asset_id:
            raise ValueError("asset_id is required")
        if self.outcome not in {"UP", "DOWN"}:
            raise ValueError("outcome must be UP or DOWN")


@dataclass(frozen=True)
class Market:
    market_id: str
    slug: str
    question: str
    start_ts: datetime
    end_ts: datetime
    up: MarketAsset
    down: MarketAsset
    status: str = "DISCOVERED"

    def __post_init__(self) -> None:
        if not self.market_id:
            raise ValueError("market_id is required")
        if self.end_ts <= self.start_ts:
            raise ValueError("end_ts must be after start_ts")
        if self.up.outcome != "UP" or self.down.outcome != "DOWN":
            raise ValueError("market assets must be ordered as up/down")

    @property
    def seconds_to_close(self) -> int:
        return max(0, int((self.end_ts - utc_now()).total_seconds()))


@dataclass(frozen=True)
class OrderBookLevel:
    price: float
    size: float

    def __post_init__(self) -> None:
        if self.price < 0 or self.price > 1:
            raise ValueError("orderbook price must be between 0 and 1")
        if self.size < 0:
            raise ValueError("orderbook size cannot be negative")


@dataclass(frozen=True)
class OrderBook:
    asset_id: str
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    observed_ts: datetime

    @property
    def best_bid(self) -> OrderBookLevel | None:
        return max(self.bids, key=lambda level: level.price, default=None)

    @property
    def best_ask(self) -> OrderBookLevel | None:
        return min(self.asks, key=lambda level: level.price, default=None)

    @property
    def midpoint(self) -> float | None:
        bid = self.best_bid
        ask = self.best_ask
        if bid is None or ask is None:
            return None
        return round((bid.price + ask.price) / 2, 4)

    @property
    def spread(self) -> float | None:
        bid = self.best_bid
        ask = self.best_ask
        if bid is None or ask is None:
            return None
        return round(ask.price - bid.price, 4)


@dataclass(frozen=True)
class BtcTick:
    venue: str
    symbol: str
    price: float
    source_ts: datetime
    observed_ts: datetime
    bid: float | None = None
    ask: float | None = None

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError("BTC price must be positive")
        if self.bid is not None and self.ask is not None and self.ask < self.bid:
            raise ValueError("ask cannot be lower than bid")

    def is_stale(self, max_age: timedelta) -> bool:
        return utc_now() - self.observed_ts > max_age


@dataclass(frozen=True)
class StrategyDecision:
    action: str
    probability_up: float
    edge: float
    target_price: float | None
    reason: str
    observed_ts: datetime

    def __post_init__(self) -> None:
        if self.action not in {"BUY_UP", "BUY_DOWN", "NO_TRADE"}:
            raise ValueError("invalid strategy action")
        if self.probability_up < 0 or self.probability_up > 1:
            raise ValueError("probability_up must be between 0 and 1")


@dataclass(frozen=True)
class DashboardSnapshot:
    mode: BotMode
    market: Market
    btc_tick: BtcTick
    up_book: OrderBook
    down_book: OrderBook
    decision: StrategyDecision
    risk_state: dict[str, Any]
    execution_state: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return _serialize_datetimes(
            {
                "mode": self.mode,
                "market": {
                    "market_id": self.market.market_id,
                    "slug": self.market.slug,
                    "question": self.market.question,
                    "start_ts": self.market.start_ts,
                    "end_ts": self.market.end_ts,
                    "seconds_to_close": self.market.seconds_to_close,
                    "status": self.market.status,
                    "up": {
                        "asset_id": self.market.up.asset_id,
                        "outcome": self.market.up.outcome,
                    },
                    "down": {
                        "asset_id": self.market.down.asset_id,
                        "outcome": self.market.down.outcome,
                    },
                },
                "btc_tick": {
                    "venue": self.btc_tick.venue,
                    "symbol": self.btc_tick.symbol,
                    "price": self.btc_tick.price,
                    "source_ts": self.btc_tick.source_ts,
                    "observed_ts": self.btc_tick.observed_ts,
                    "bid": self.btc_tick.bid,
                    "ask": self.btc_tick.ask,
                },
                "up_book": _book_to_dict(self.up_book),
                "down_book": _book_to_dict(self.down_book),
                "decision": {
                    "action": self.decision.action,
                    "probability_up": self.decision.probability_up,
                    "edge": self.decision.edge,
                    "target_price": self.decision.target_price,
                    "reason": self.decision.reason,
                    "observed_ts": self.decision.observed_ts,
                },
                "risk_state": self.risk_state,
                "execution_state": self.execution_state,
            }
        )


def _book_to_dict(book: OrderBook) -> dict[str, Any]:
    return {
        "asset_id": book.asset_id,
        "bids": [{"price": level.price, "size": level.size} for level in book.bids],
        "asks": [{"price": level.price, "size": level.size} for level in book.asks],
        "observed_ts": book.observed_ts,
        "best_bid": None if book.best_bid is None else book.best_bid.price,
        "best_ask": None if book.best_ask is None else book.best_ask.price,
        "midpoint": book.midpoint,
        "spread": book.spread,
    }


def _serialize_datetimes(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _serialize_datetimes(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_datetimes(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize_datetimes(item) for item in value]
    return value
