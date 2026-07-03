from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from math import erf, log, sqrt

from polymarket_btc_bot.domain import BtcTick, Market, OrderBook, StrategyDecision, utc_now


@dataclass(frozen=True)
class StrategyInputs:
    market: Market
    btc_tick: BtcTick
    up_book: OrderBook
    down_book: OrderBook
    reference_price: float
    tradable: bool
    schedule_reason: str


class BaselineProbabilityStrategy:
    def __init__(
        self,
        min_edge: float = 0.03,
        max_spread: float = 0.04,
        stale_after: timedelta = timedelta(seconds=5),
        assumed_5m_volatility: float = 0.0018,
    ) -> None:
        self.min_edge = min_edge
        self.max_spread = max_spread
        self.stale_after = stale_after
        self.assumed_5m_volatility = assumed_5m_volatility

    def evaluate(self, inputs: StrategyInputs) -> StrategyDecision:
        now = utc_now()
        if not inputs.tradable:
            return self._no_trade(0.5, inputs.schedule_reason)
        if inputs.btc_tick.is_stale(self.stale_after):
            return self._no_trade(0.5, "stale_btc_tick")
        if inputs.reference_price <= 0:
            return self._no_trade(0.5, "invalid_reference_price")

        up_ask = None if inputs.up_book.best_ask is None else inputs.up_book.best_ask.price
        down_ask = None if inputs.down_book.best_ask is None else inputs.down_book.best_ask.price
        if up_ask is None or down_ask is None:
            return self._no_trade(0.5, "missing_executable_ask")

        if _too_wide(inputs.up_book.spread, self.max_spread) or _too_wide(inputs.down_book.spread, self.max_spread):
            return self._no_trade(0.5, "spread_too_wide")

        probability_up = self._probability_up(inputs.market, inputs.btc_tick.price, inputs.reference_price, now)
        up_edge = probability_up - up_ask
        down_edge = (1.0 - probability_up) - down_ask

        if up_edge >= self.min_edge and up_edge >= down_edge:
            return StrategyDecision(
                action="BUY_UP",
                probability_up=round(probability_up, 4),
                edge=round(up_edge, 4),
                target_price=up_ask,
                reason="baseline_edge_up",
                observed_ts=now,
            )
        if down_edge >= self.min_edge:
            return StrategyDecision(
                action="BUY_DOWN",
                probability_up=round(probability_up, 4),
                edge=round(down_edge, 4),
                target_price=down_ask,
                reason="baseline_edge_down",
                observed_ts=now,
            )

        return self._no_trade(probability_up, "edge_below_threshold")

    def _probability_up(self, market: Market, btc_price: float, reference_price: float, now) -> float:
        seconds_to_close = max(1.0, (market.end_ts - now).total_seconds())
        tau_scale = sqrt(seconds_to_close / 300.0)
        sigma = max(0.0001, self.assumed_5m_volatility * tau_scale)
        z_score = log(btc_price / reference_price) / sigma
        probability = 0.5 * (1.0 + erf(z_score / sqrt(2.0)))
        return min(0.99, max(0.01, probability))

    def _no_trade(self, probability_up: float, reason: str) -> StrategyDecision:
        return StrategyDecision(
            action="NO_TRADE",
            probability_up=round(probability_up, 4),
            edge=0.0,
            target_price=None,
            reason=reason,
            observed_ts=utc_now(),
        )


def _too_wide(spread: float | None, max_spread: float) -> bool:
    return spread is None or spread > max_spread

