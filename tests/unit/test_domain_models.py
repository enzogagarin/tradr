from datetime import UTC, datetime, timedelta

import pytest

from polymarket_btc_bot.domain import BtcTick, Market, MarketAsset, OrderBookLevel


def test_market_requires_end_after_start():
    now = datetime.now(tz=UTC)
    market = Market(
        market_id="m1",
        slug="btc-demo",
        question="BTC up?",
        start_ts=now,
        end_ts=now + timedelta(minutes=5),
        up=MarketAsset("up-token", "UP"),
        down=MarketAsset("down-token", "DOWN"),
    )
    assert market.market_id == "m1"


def test_market_rejects_invalid_window():
    now = datetime.now(tz=UTC)
    with pytest.raises(ValueError):
        Market(
            market_id="m1",
            slug="btc-demo",
            question="BTC up?",
            start_ts=now,
            end_ts=now,
            up=MarketAsset("up-token", "UP"),
            down=MarketAsset("down-token", "DOWN"),
        )


def test_orderbook_level_rejects_invalid_price():
    with pytest.raises(ValueError):
        OrderBookLevel(price=1.25, size=10)


def test_btc_tick_rejects_crossed_quote():
    now = datetime.now(tz=UTC)
    with pytest.raises(ValueError):
        BtcTick(
            venue="binance",
            symbol="BTCUSDT",
            price=62000,
            bid=62010,
            ask=62000,
            source_ts=now,
            observed_ts=now,
        )

