from polymarket_btc_bot.adapters.reference_feeds.binance import btc_tick_from_book_ticker


def test_btc_tick_from_book_ticker_uses_mid_price():
    tick = btc_tick_from_book_ticker(
        {
            "symbol": "BTCUSDT",
            "bidPrice": "62480.10",
            "bidQty": "1.5",
            "askPrice": "62480.30",
            "askQty": "1.2",
        }
    )

    assert tick.venue == "binance"
    assert tick.symbol == "BTCUSDT"
    assert tick.bid == 62480.10
    assert tick.ask == 62480.30
    assert round(tick.price, 2) == 62480.20
