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
    # Data-driven per-5m realized volatility (log-return stdev). When None the
    # strategy falls back to the static assumed volatility.
    volatility_5m: float | None = None


class BaselineProbabilityStrategy:
    def __init__(
        self,
        min_edge: float = 0.03,
        max_spread: float = 0.04,
        stale_after: timedelta = timedelta(seconds=5),
        max_book_age: timedelta = timedelta(seconds=10),
        assumed_5m_volatility: float = 0.0018,
        market_blend_weight: float = 0.5,
        min_divergence: float = 0.05,
    ) -> None:
        self.min_edge = min_edge
        self.max_spread = max_spread
        self.stale_after = stale_after
        self.max_book_age = max_book_age
        self.assumed_5m_volatility = assumed_5m_volatility
        # How much to trust the model vs the market's own implied probability.
        # fair = w*model + (1-w)*market_mid. Anchoring to the market price
        # prevents trading on a naive model that merely restates public info and
        # keeps size/edge honest when the market already agrees.
        self.market_blend_weight = min(1.0, max(0.0, market_blend_weight))
        # The model must disagree with the market by at least this much before
        # we act; otherwise there is no informational edge to capture.
        self.min_divergence = min_divergence

    def evaluate(self, inputs: StrategyInputs) -> StrategyDecision:
        now = utc_now()
        if not inputs.tradable:
            return self._no_trade(0.5, inputs.schedule_reason)
        if inputs.btc_tick.is_stale(self.stale_after):
            return self._no_trade(0.5, "stale_btc_tick")
        if utc_now() - inputs.up_book.observed_ts > self.max_book_age:
            return self._no_trade(0.5, "stale_up_orderbook")
        if utc_now() - inputs.down_book.observed_ts > self.max_book_age:
            return self._no_trade(0.5, "stale_down_orderbook")
        if inputs.reference_price <= 0:
            return self._no_trade(0.5, "invalid_reference_price")

        up_ask = None if inputs.up_book.best_ask is None else inputs.up_book.best_ask.price
        down_ask = None if inputs.down_book.best_ask is None else inputs.down_book.best_ask.price
        if up_ask is None or down_ask is None:
            return self._no_trade(0.5, "missing_executable_ask")

        if _too_wide(inputs.up_book.spread, self.max_spread) or _too_wide(inputs.down_book.spread, self.max_spread):
            return self._no_trade(0.5, "spread_too_wide")

        model_up = self._probability_up(
            inputs.market, inputs.btc_tick.price, inputs.reference_price, now, inputs.volatility_5m
        )

        # Market-implied P(up) from both token books (average of the UP mid and
        # 1 - DOWN mid when available). This is the crowd's consensus.
        market_up = _market_implied_up(inputs.up_book, inputs.down_book)

        if market_up is None:
            fair_up = model_up
            divergence = 1.0
        else:
            fair_up = self.market_blend_weight * model_up + (1.0 - self.market_blend_weight) * market_up
            divergence = abs(model_up - market_up)
            if divergence < self.min_divergence:
                return self._no_trade(round(fair_up, 4), "no_edge_vs_market")

        fair_up = min(0.99, max(0.01, fair_up))
        up_edge = fair_up - up_ask
        down_edge = (1.0 - fair_up) - down_ask
        div_tag = "" if market_up is None else f"|div={round(divergence, 3)}"

        if up_edge >= self.min_edge and up_edge >= down_edge:
            return StrategyDecision(
                action="BUY_UP",
                probability_up=round(fair_up, 4),
                edge=round(up_edge, 4),
                target_price=up_ask,
                reason=f"baseline_edge_up{div_tag}",
                observed_ts=now,
            )
        if down_edge >= self.min_edge:
            return StrategyDecision(
                action="BUY_DOWN",
                probability_up=round(fair_up, 4),
                edge=round(down_edge, 4),
                target_price=down_ask,
                reason=f"baseline_edge_down{div_tag}",
                observed_ts=now,
            )

        return self._no_trade(round(fair_up, 4), "edge_below_threshold")

    def _probability_up(
        self, market: Market, btc_price: float, reference_price: float, now, volatility_5m: float | None = None
    ) -> float:
        seconds_to_close = max(1.0, (market.end_ts - now).total_seconds())
        base_vol = volatility_5m if volatility_5m and volatility_5m > 0 else self.assumed_5m_volatility
        # Scale the full-cycle vol to the remaining time to close.
        tau_scale = sqrt(seconds_to_close / 300.0)
        sigma = max(0.0001, base_vol * tau_scale)
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


def _market_implied_up(up_book: OrderBook, down_book: OrderBook) -> float | None:
    """Crowd-implied P(up) from token mid prices, combining both books."""
    estimates: list[float] = []
    up_mid = up_book.midpoint
    if up_mid is not None:
        estimates.append(up_mid)
    down_mid = down_book.midpoint
    if down_mid is not None:
        estimates.append(1.0 - down_mid)
    if not estimates:
        return None
    return min(0.99, max(0.01, sum(estimates) / len(estimates)))
