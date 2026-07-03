from datetime import UTC, datetime, timedelta

from polymarket_btc_bot.adapters.reference_feeds import parse_klines
from polymarket_btc_bot.research import btc_training_summary, build_btc_training_rows, write_btc_training_csv


def _sample_klines(count: int = 16):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    payload = []
    for index in range(count):
        open_time = start + timedelta(minutes=5 * index)
        close_time = open_time + timedelta(minutes=5) - timedelta(milliseconds=1)
        open_price = 100 + index
        close_price = open_price + (0.5 if index % 2 == 0 else -0.25)
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
    return parse_klines(payload, symbol="BTCUSDT", interval="5m")


def test_build_btc_training_rows_adds_forward_labels_without_marking_edges_ready():
    rows = build_btc_training_rows(_sample_klines())

    assert len(rows) == 16
    assert rows[0].train_ready is False
    assert rows[0].blocking_reason == "missing_previous_close"
    assert rows[1].close_to_close_return_bps is not None
    assert rows[1].label_next_1_return_bps is not None
    assert rows[-1].train_ready is False
    assert rows[-1].blocking_reason == "missing_forward_label"


def test_write_btc_training_csv_and_summary(tmp_path):
    rows = build_btc_training_rows(_sample_klines())
    output_path = tmp_path / "training.csv"

    write_btc_training_csv(rows, output_path)
    summary = btc_training_summary(rows, output_path)

    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8").startswith("open_time,close_time")
    assert summary["rows"] == 16
    assert 0 < summary["train_ready_rows"] < 16
    assert "missing_forward_label" in summary["blocking_reasons"]
