import pytest

from polymarket_btc_bot.adapters.polymarket.clob import orderbook_from_payload


def test_orderbook_from_payload_computes_top_of_book():
    book = orderbook_from_payload(
        "token-1",
        {
            "asset_id": "token-1",
            "bids": [{"price": "0.51", "size": "100"}, {"price": "0.50", "size": "200"}],
            "asks": [{"price": "0.53", "size": "150"}, {"price": "0.54", "size": "250"}],
        },
    )

    assert book.best_bid.price == 0.51
    assert book.best_ask.price == 0.53
    assert book.midpoint == 0.52
    assert book.spread == 0.02


def test_orderbook_rejects_crossed_book():
    with pytest.raises(ValueError):
        orderbook_from_payload(
            "token-1",
            {
                "asset_id": "token-1",
                "bids": [{"price": "0.55", "size": "100"}],
                "asks": [{"price": "0.54", "size": "150"}],
            },
        )
