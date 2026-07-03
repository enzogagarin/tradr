from datetime import UTC, datetime, timedelta

from polymarket_btc_bot.adapters.reference_feeds import (
    BinanceHistoricalKlineClient,
    build_kline_history_report,
    parse_klines,
    read_klines_jsonl,
    write_klines_jsonl,
)


def test_parse_klines_normalizes_binance_payload():
    klines = parse_klines(
        [
            [
                1_782_864_000_000,
                "100.0",
                "103.0",
                "99.0",
                "101.0",
                "2.5",
                1_782_864_299_999,
                "251.0",
                42,
                "1.1",
                "110.0",
                "0",
            ]
        ],
        symbol="btcusdt",
        interval="5m",
    )

    assert len(klines) == 1
    assert klines[0].symbol == "BTCUSDT"
    assert klines[0].interval == "5m"
    assert klines[0].open_time == datetime.fromtimestamp(1_782_864_000, tz=UTC)
    assert klines[0].close_time == datetime.fromtimestamp(1_782_864_299.999, tz=UTC)
    assert round(klines[0].open_return_bps, 6) == 100.0
    assert klines[0].quote_volume == 251.0
    assert klines[0].trade_count == 42


def test_kline_history_jsonl_round_trip(tmp_path):
    klines = parse_klines(
        [[1_782_864_000_000, "100", "101", "99", "100.5", "2", 1_782_864_299_999, "200", 10]],
        symbol="BTCUSDT",
        interval="5m",
    )
    path = tmp_path / "history.jsonl"

    write_klines_jsonl(klines, path)

    restored = read_klines_jsonl(path)
    assert restored == klines


def test_report_blocks_tiny_history_for_baseline():
    klines = parse_klines(
        [[1_782_864_000_000, "100", "101", "99", "100.5", "2", 1_782_864_299_999, "200", 10]],
        symbol="BTCUSDT",
        interval="5m",
    )

    report = build_kline_history_report(klines)

    assert report.row_count == 1
    assert report.sufficient_for_baseline is False
    assert "less_than_one_day_of_5m_bars" in report.blocking_reasons


def test_report_accepts_one_day_of_monotonic_5m_history():
    start = datetime(2026, 7, 1, tzinfo=UTC)
    payload = []
    for index in range(288):
        open_time = start + timedelta(minutes=5 * index)
        close_time = open_time + timedelta(minutes=5) - timedelta(milliseconds=1)
        open_price = 100 + index * 0.01
        close_price = open_price + (0.1 if index % 2 == 0 else -0.05)
        payload.append(
            [
                int(open_time.timestamp() * 1000),
                str(open_price),
                str(max(open_price, close_price) + 0.1),
                str(min(open_price, close_price) - 0.1),
                str(close_price),
                "1.0",
                int(close_time.timestamp() * 1000),
                "100.0",
                10,
            ]
        )
    klines = parse_klines(payload, symbol="BTCUSDT", interval="5m")

    report = build_kline_history_report(klines)

    assert report.row_count == 288
    assert report.sufficient_for_baseline is True
    assert report.blocking_reasons == []
    assert report.realized_vol_bps > 0
    assert report.interval_gap_count == 0
    assert report.duplicate_open_time_count == 0


def test_report_detects_interval_gaps():
    start = datetime(2026, 7, 1, tzinfo=UTC)
    payload = []
    for minute in (0, 5, 15):
        open_time = start + timedelta(minutes=minute)
        close_time = open_time + timedelta(minutes=5) - timedelta(milliseconds=1)
        payload.append(
            [
                int(open_time.timestamp() * 1000),
                "100",
                "101",
                "99",
                "100.5",
                "1.0",
                int(close_time.timestamp() * 1000),
                "100.0",
                10,
            ]
        )
    klines = parse_klines(payload, symbol="BTCUSDT", interval="5m")

    report = build_kline_history_report(klines)

    assert report.interval_gap_count == 1
    assert "interval_gaps" in report.blocking_reasons


def test_get_klines_range_paginates_and_deduplicates():
    start = datetime(2026, 7, 1, tzinfo=UTC)
    calls = []

    class FakeClient(BinanceHistoricalKlineClient):
        def __init__(self):
            pass

        def get_klines(self, *, symbol="BTCUSDT", interval="5m", start=None, end=None, limit=1000):
            calls.append(start)
            base = calls[0]
            if len(calls) == 1:
                payload = []
                offsets = (0, 5)
            else:
                payload = []
                offsets = (5, 10)
            for minute in offsets:
                open_time = base + timedelta(minutes=minute)
                close_time = open_time + timedelta(minutes=5) - timedelta(milliseconds=1)
                payload.append(
                    [
                        int(open_time.timestamp() * 1000),
                        "100",
                        "101",
                        "99",
                        "100.5",
                        "1.0",
                        int(close_time.timestamp() * 1000),
                        "100.0",
                        10,
                    ]
                )
            return parse_klines(payload, symbol=symbol, interval=interval)

    klines = FakeClient().get_klines_range(
        symbol="BTCUSDT",
        interval="5m",
        start=start,
        end=start + timedelta(minutes=15),
        limit=2,
        max_pages=3,
    )

    assert [kline.open_time for kline in klines] == [
        start,
        start + timedelta(minutes=5),
        start + timedelta(minutes=10),
    ]
