from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from polymarket_btc_bot.domain import OrderBook, OrderBookLevel


class ClobClient:
    def __init__(self, base_url: str = "https://clob.polymarket.com", timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_book(self, token_id: str) -> OrderBook:
        if not token_id:
            raise ValueError("token_id is required")
        query = urlencode({"token_id": token_id})
        payload = self._get_json(f"/book?{query}")
        return orderbook_from_payload(token_id, payload)

    def _get_json(self, path: str) -> Any:
        request = Request(
            f"{self.base_url}{path}",
            headers={
                "Accept": "application/json",
                "User-Agent": "polymarket-btc-bot/0.1",
            },
        )
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def orderbook_from_payload(token_id: str, payload: dict[str, Any]) -> OrderBook:
    observed_ts = datetime.now(tz=UTC)
    bids = tuple(_level_from_payload(level) for level in payload.get("bids", []))
    asks = tuple(_level_from_payload(level) for level in payload.get("asks", []))
    book = OrderBook(
        asset_id=str(payload.get("asset_id") or payload.get("token_id") or token_id),
        bids=bids,
        asks=asks,
        observed_ts=observed_ts,
    )
    _validate_book(book)
    return book


def _level_from_payload(level: dict[str, Any]) -> OrderBookLevel:
    return OrderBookLevel(price=float(level["price"]), size=float(level["size"]))


def _validate_book(book: OrderBook) -> None:
    bid = book.best_bid
    ask = book.best_ask
    if bid is not None and ask is not None and bid.price > ask.price:
        raise ValueError("crossed orderbook: best bid is above best ask")

