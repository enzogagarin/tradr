from datetime import UTC, datetime, timedelta

from polymarket_btc_bot.domain import Market, MarketAsset
from polymarket_btc_bot.scheduler import MarketScheduler


def _market(start, end):
    return Market(
        market_id="m1",
        slug="btc-demo",
        question="BTC up?",
        start_ts=start,
        end_ts=end,
        up=MarketAsset("up", "UP"),
        down=MarketAsset("down", "DOWN"),
    )


def test_scheduler_selects_active_tradable_market():
    now = datetime.now(tz=UTC)
    state = MarketScheduler().select([_market(now - timedelta(minutes=1), now + timedelta(minutes=1))], now)

    assert state.current is not None
    assert state.tradable is True
    assert state.reason == "active_market_tradable"


def test_scheduler_blocks_inside_entry_cutoff():
    now = datetime.now(tz=UTC)
    state = MarketScheduler(entry_cutoff=timedelta(seconds=10)).select(
        [_market(now - timedelta(minutes=1), now + timedelta(seconds=5))],
        now,
    )

    assert state.tradable is False
    assert state.reason == "entry_cutoff_reached"

