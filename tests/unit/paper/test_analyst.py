from polymarket_btc_bot.config import BotSettings
from polymarket_btc_bot.domain import BtcTick
from polymarket_btc_bot.paper import PaperAnalyst


def test_paper_analyst_builds_snapshot_with_decision():
    snapshot = PaperAnalyst(BotSettings(market_data_mode="demo")).snapshot()

    assert snapshot["mode"] == "paper"
    assert snapshot["market"]["market_id"]
    assert snapshot["decision"]["action"] in {"BUY_UP", "BUY_DOWN", "NO_TRADE"}
    assert "reference_price" in snapshot["risk_state"]
    assert snapshot["execution_state"]["status"] in {"FILLED", "PARTIAL_FILL", "SKIPPED", "REJECTED"}


def test_live_market_data_mode_blocks_when_no_live_market_is_found():
    snapshot = PaperAnalyst(
        BotSettings(market_data_mode="live"),
        market_client=_EmptyMarketClient(),
        price_feed=_StaticPriceFeed(),
    ).snapshot()

    assert snapshot["risk_state"]["state_source"] == "live_unavailable_no_btc_5m_market"
    assert snapshot["risk_state"]["book_source"] == "live_unavailable_no_orderbook"
    assert snapshot["decision"]["action"] == "NO_TRADE"
    assert snapshot["execution_state"]["status"] == "SKIPPED"


def test_live_clob_error_does_not_fall_back_to_demo_book():
    market = __import__("polymarket_btc_bot.paper.analyst", fromlist=["build_demo_market"]).build_demo_market(
        __import__("datetime").datetime.now(tz=__import__("datetime").UTC)
    )
    _dt = __import__("datetime")
    _now = _dt.datetime.now(tz=_dt.UTC)
    live_market = __import__("dataclasses").replace(
        market,
        market_id="live-market",
        # Pin a comfortable tradable window so this CLOB-fallback test does not
        # depend on where wall-clock time falls within the 5m demo cycle.
        start_ts=_now - _dt.timedelta(minutes=2),
        end_ts=_now + _dt.timedelta(minutes=3),
        up=__import__("polymarket_btc_bot.domain", fromlist=["MarketAsset"]).MarketAsset("live-up", "UP"),
        down=__import__("polymarket_btc_bot.domain", fromlist=["MarketAsset"]).MarketAsset("live-down", "DOWN"),
    )

    snapshot = PaperAnalyst(
        BotSettings(market_data_mode="live"),
        market_client=_OneMarketClient(live_market),
        clob_client=_FailingClobClient(),
        price_feed=_StaticPriceFeed(),
    ).snapshot()

    assert snapshot["risk_state"]["state_source"] == "gamma_live"
    assert snapshot["risk_state"]["book_source"] == "clob_unavailable:RuntimeError"
    assert snapshot["decision"]["reason"] == "missing_executable_ask"


class _EmptyMarketClient:
    def discover_btc_5m_markets(self, limit=100, pages=10):
        return []


class _OneMarketClient:
    def __init__(self, market):
        self.market = market

    def discover_btc_5m_markets(self, limit=100, pages=10):
        return [self.market]


class _FailingClobClient:
    def get_book(self, token_id):
        raise RuntimeError("clob down")


class _StaticPriceFeed:
    def latest_tick(self):
        from datetime import UTC, datetime

        now = datetime.now(tz=UTC)
        return BtcTick(
            venue="test",
            symbol="BTCUSDT",
            price=62000,
            bid=61999,
            ask=62001,
            source_ts=now,
            observed_ts=now,
        )
