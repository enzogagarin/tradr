from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from polymarket_btc_bot.domain import BtcTick

# Process-wide short-TTL cache so many rapid callers (dashboard poll + paper
# loop, each building a fresh analyst) do not each hit the Binance REST API.
# The BTC 5m game does not need sub-second freshness; ~0.75s is plenty and
# keeps the dashboard feeling live without adding request latency per poll.
_TICK_CACHE: dict[str, tuple[float, BtcTick]] = {}
_TICK_TTL_SECONDS = 0.75


class BinancePriceFeed:
    def __init__(self, rest_base_url: str = "https://api.binance.com", timeout: float = 10.0) -> None:
        self.rest_base_url = rest_base_url.rstrip("/")
        self.timeout = timeout

    def latest_tick(self, symbol: str = "BTCUSDT", use_cache: bool = True) -> BtcTick:
        key = symbol.upper()
        if use_cache:
            cached = _TICK_CACHE.get(key)
            if cached is not None and (time.monotonic() - cached[0]) < _TICK_TTL_SECONDS:
                return cached[1]
        query = urlencode({"symbol": key})
        payload = self._get_json(f"/api/v3/ticker/bookTicker?{query}")
        tick = btc_tick_from_book_ticker(payload)
        _TICK_CACHE[key] = (time.monotonic(), tick)
        return tick

    def _get_json(self, path: str) -> Any:
        request = Request(
            f"{self.rest_base_url}{path}",
            headers={
                "Accept": "application/json",
                "User-Agent": "polymarket-btc-bot/0.1",
            },
        )
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def btc_tick_from_book_ticker(payload: dict[str, Any]) -> BtcTick:
    observed_ts = datetime.now(tz=UTC)
    bid = float(payload["bidPrice"])
    ask = float(payload["askPrice"])
    return BtcTick(
        venue="binance",
        symbol=str(payload.get("symbol") or "BTCUSDT"),
        price=(bid + ask) / 2,
        bid=bid,
        ask=ask,
        source_ts=observed_ts,
        observed_ts=observed_ts,
    )

