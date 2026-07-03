from polymarket_btc_bot.adapters.polymarket.data_api import PolymarketDataApiClient, read_jsonl, write_jsonl
from urllib.error import HTTPError


def test_data_api_paginates_until_short_page():
    client = _FakeDataClient(
        {
            "activity": [[{"id": 1}], [{"id": 2}], []],
            "positions": [[{"id": "p1"}], []],
        }
    )

    assert client.get_activity_pages(user="0xabc", page_limit=1, max_rows=5) == [{"id": 1}, {"id": 2}]
    assert client.get_position_pages(user="0xabc", page_limit=1, max_rows=5) == [{"id": "p1"}]


def test_data_api_stops_on_400_after_collecting_rows():
    client = _ErrorAfterFirstPageClient()

    assert client.get_activity_pages(user="0xabc", page_limit=1, max_rows=5) == [{"id": 1}]


def test_jsonl_round_trip(tmp_path):
    path = tmp_path / "rows.jsonl"

    write_jsonl([{"id": 1}, {"id": 2}], path)

    assert read_jsonl(path) == [{"id": 1}, {"id": 2}]


class _FakeDataClient(PolymarketDataApiClient):
    def __init__(self, pages):
        super().__init__("https://example.test")
        self.pages = pages
        self.calls = {"activity": 0, "positions": 0}

    def get_activity(self, *, user, limit=500, offset=0):
        index = self.calls["activity"]
        self.calls["activity"] += 1
        return self.pages["activity"][index]

    def get_positions(self, *, user, limit=500, offset=0):
        index = self.calls["positions"]
        self.calls["positions"] += 1
        return self.pages["positions"][index]


class _ErrorAfterFirstPageClient(PolymarketDataApiClient):
    def __init__(self):
        super().__init__("https://example.test")
        self.calls = 0

    def get_activity(self, *, user, limit=500, offset=0):
        self.calls += 1
        if self.calls == 1:
            return [{"id": 1}]
        raise HTTPError("https://example.test", 400, "Bad Request", hdrs=None, fp=None)
