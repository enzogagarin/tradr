from datetime import UTC, datetime, timedelta

from polymarket_btc_bot.domain import BtcTick, Market, MarketAsset, OrderBook, OrderBookLevel
from polymarket_btc_bot.strategy import BaselineProbabilityStrategy, StrategyInputs


def _inputs(reference_price=100.0, btc_price=100.2, up_ask=0.56, down_ask=0.45, tradable=True):
    now = datetime.now(tz=UTC)
    market = Market(
        market_id="m1",
        slug="btc-demo",
        question="BTC up?",
        start_ts=now - timedelta(minutes=1),
        end_ts=now + timedelta(minutes=2),
        up=MarketAsset("up", "UP"),
        down=MarketAsset("down", "DOWN"),
    )
    return StrategyInputs(
        market=market,
        btc_tick=BtcTick("binance", "BTCUSDT", btc_price, now, now, btc_price - 0.01, btc_price + 0.01),
        up_book=OrderBook("up", (OrderBookLevel(0.54, 100),), (OrderBookLevel(up_ask, 100),), now),
        down_book=OrderBook("down", (OrderBookLevel(0.43, 100),), (OrderBookLevel(down_ask, 100),), now),
        reference_price=reference_price,
        tradable=tradable,
        schedule_reason="active_market_tradable",
    )


def test_baseline_strategy_buys_up_when_edge_passes():
    decision = BaselineProbabilityStrategy(min_edge=0.02).evaluate(_inputs())

    assert decision.action == "BUY_UP"
    assert decision.edge > 0.02


def test_baseline_strategy_no_trade_when_not_tradable():
    decision = BaselineProbabilityStrategy().evaluate(_inputs(tradable=False))

    assert decision.action == "NO_TRADE"
    assert decision.reason == "active_market_tradable"

