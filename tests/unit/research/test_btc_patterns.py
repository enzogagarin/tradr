import csv
from datetime import UTC, datetime, timedelta

from polymarket_btc_bot.research.btc_patterns import scan_btc_patterns


def test_scan_btc_patterns_ranks_patterns_by_forward_outcome(tmp_path):
    path = tmp_path / "training.csv"
    _write_pattern_csv(path, row_count=120)

    report = scan_btc_patterns([path], min_support=10, top_n=5)

    assert report["rows"] == 120
    assert report["blocking_reasons"] == []
    assert report["patterns"]
    assert any(item["pattern"] == "hour=00" and item["up_rate"] > item["baseline_up_rate"] for item in report["patterns"])


def test_scan_btc_patterns_handles_no_observations(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("open_time,train_ready\n", encoding="utf-8")

    report = scan_btc_patterns([path], min_support=1)

    assert report["rows"] == 0
    assert report["patterns"] == []
    assert "no_observations" in report["blocking_reasons"]


def _write_pattern_csv(path, *, row_count: int) -> None:
    fieldnames = [
        "open_time",
        "train_ready",
        "return_bps",
        "abs_return_bps",
        "range_bps",
        "upper_wick_bps",
        "lower_wick_bps",
        "close_to_close_return_bps",
        "rolling_12_mean_abs_return_bps",
        "rolling_12_realized_range_bps",
        "label_next_1_return_bps",
        "label_next_1_up",
        "label_next_3_return_bps",
        "label_next_3_up",
        "label_next_12_return_bps",
        "label_next_12_up",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index in range(row_count):
            open_time = start + timedelta(minutes=5 * index)
            hour_zero = open_time.hour == 0
            forward_return = 5.0 if hour_zero else -1.0
            writer.writerow(
                {
                    "open_time": open_time.isoformat(),
                    "train_ready": "True",
                    "return_bps": "4.0" if hour_zero else "-2.0",
                    "abs_return_bps": "4.0" if hour_zero else "2.0",
                    "range_bps": "8.0",
                    "upper_wick_bps": "1.0",
                    "lower_wick_bps": "3.0" if hour_zero else "1.0",
                    "close_to_close_return_bps": "4.0" if hour_zero else "-2.0",
                    "rolling_12_mean_abs_return_bps": "6.0" if hour_zero else "2.0",
                    "rolling_12_realized_range_bps": "20.0" if hour_zero else "8.0",
                    "label_next_1_return_bps": str(forward_return),
                    "label_next_1_up": "True" if forward_return > 0 else "False",
                    "label_next_3_return_bps": str(forward_return),
                    "label_next_3_up": "True" if forward_return > 0 else "False",
                    "label_next_12_return_bps": str(forward_return),
                    "label_next_12_up": "True" if forward_return > 0 else "False",
                }
            )
