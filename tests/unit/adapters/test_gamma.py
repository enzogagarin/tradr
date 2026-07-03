from datetime import UTC, datetime, timedelta

from polymarket_btc_bot.adapters.polymarket.gamma import discover_btc_5m_markets_from_payload
from polymarket_btc_bot.adapters.polymarket.gamma import GammaClient


def test_discovers_btc_5m_market_from_gamma_event_payload():
    start = datetime.now(tz=UTC) + timedelta(minutes=5)
    end = start + timedelta(minutes=5)
    payload = [
        {
            "id": "event-1",
            "slug": "btc-updown-5m-1783010400",
            "title": "Bitcoin Up or Down - July 2, 12:40PM-12:45PM ET",
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "markets": [
                {
                    "id": "market-1",
                    "question": "Bitcoin Up or Down - July 2, 12:40PM-12:45PM ET",
                    "clobTokenIds": '["up-token", "down-token"]',
                    "outcomes": '["Up", "Down"]',
                    "startDate": start.isoformat(),
                    "endDate": end.isoformat(),
                }
            ],
        }
    ]

    markets = discover_btc_5m_markets_from_payload(payload)

    assert len(markets) == 1
    assert markets[0].market_id == "market-1"
    assert markets[0].up.asset_id == "up-token"
    assert markets[0].down.asset_id == "down-token"
    assert markets[0].start_ts == datetime.fromtimestamp(1783010400, tz=UTC)


def test_skips_incomplete_market_payloads():
    payload = [
        {
            "slug": "btc-updown-5m-1783010400",
            "title": "Bitcoin Up or Down - July 2, 12:40PM-12:45PM ET",
            "markets": [{"id": "market-1", "outcomes": '["Up", "Down"]'}],
        }
    ]

    assert discover_btc_5m_markets_from_payload(payload) == []


def test_gamma_client_scans_multiple_pages_for_btc_5m_markets():
    start = datetime.now(tz=UTC) + timedelta(minutes=5)
    end = start + timedelta(minutes=5)
    client = _PagedGammaClient(
        [
            [{"id": "noise", "slug": "election", "title": "Election", "markets": []}],
            [
                {
                    "id": "event-1",
                    "slug": "btc-updown-5m-1783010400",
                    "title": "Bitcoin Up or Down - July 2, 12:40PM-12:45PM ET",
                    "startDate": start.isoformat(),
                    "endDate": end.isoformat(),
                    "markets": [
                        {
                            "id": "market-1",
                            "question": "Bitcoin Up or Down - July 2, 12:40PM-12:45PM ET",
                            "clobTokenIds": '["up-token", "down-token"]',
                            "outcomes": '["Up", "Down"]',
                            "startDate": start.isoformat(),
                            "endDate": end.isoformat(),
                        }
                    ],
                }
            ],
        ]
    )

    markets = client.discover_btc_5m_markets(limit=1, pages=2)

    assert [market.market_id for market in markets] == ["market-1"]
    assert client.last_scan_stats == {
        "pages_scanned": 2,
        "events_scanned": 2,
        "markets_found": 1,
    }


class _PagedGammaClient(GammaClient):
    def __init__(self, pages):
        super().__init__("https://example.test")
        self.pages = pages

    def _get_json(self, path):
        index = len(getattr(self, "calls", []))
        self.calls = getattr(self, "calls", []) + [path]
        return self.pages[index] if index < len(self.pages) else []
