from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from polymarket_btc_bot.domain import Market


@dataclass(frozen=True)
class MarketScheduleState:
    current: Market | None
    next_market: Market | None
    tradable: bool
    reason: str


class MarketScheduler:
    def __init__(self, entry_cutoff: timedelta = timedelta(seconds=10)) -> None:
        self.entry_cutoff = entry_cutoff

    def select(self, markets: list[Market], now: datetime) -> MarketScheduleState:
        ordered = sorted(markets, key=lambda market: market.start_ts)
        current = next((market for market in ordered if market.start_ts <= now < market.end_ts), None)
        next_market = next((market for market in ordered if market.start_ts > now), None)

        if current is None:
            return MarketScheduleState(
                current=None,
                next_market=next_market,
                tradable=False,
                reason="no_active_market",
            )

        if current.end_ts - now <= self.entry_cutoff:
            return MarketScheduleState(
                current=current,
                next_market=next_market,
                tradable=False,
                reason="entry_cutoff_reached",
            )

        return MarketScheduleState(
            current=current,
            next_market=next_market,
            tradable=True,
            reason="active_market_tradable",
        )

