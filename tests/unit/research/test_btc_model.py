import csv

from polymarket_btc_bot.research.btc_model import FEATURE_COLUMNS, evaluate_btc_training_csv


def test_evaluate_btc_training_csv_blocks_when_there_are_too_few_scored_rows(tmp_path):
    path = tmp_path / "training.csv"
    _write_training_csv(path, row_count=12)

    report = evaluate_btc_training_csv(path, min_train_rows=10, min_evaluation_rows=5)

    assert report.decision == "insufficient_data"
    assert report.evaluated_rows == 2
    assert "insufficient_evaluation_rows" in report.blocking_reasons


def test_evaluate_btc_training_csv_finds_clear_walk_forward_candidate_signal(tmp_path):
    path = tmp_path / "training.csv"
    _write_training_csv(path, row_count=80)

    report = evaluate_btc_training_csv(path, min_train_rows=20, train_window_rows=40, min_evaluation_rows=20)

    assert report.decision == "candidate_signal_not_execution_edge"
    assert report.evaluated_rows == 60
    assert report.model_brier < report.baseline_brier
    assert report.model_accuracy >= report.baseline_accuracy


def test_evaluate_btc_training_csv_handles_missing_file(tmp_path):
    report = evaluate_btc_training_csv(tmp_path / "missing.csv", min_train_rows=2, min_evaluation_rows=1)

    assert report.decision == "insufficient_data"
    assert report.rows == 0
    assert "training_csv_not_found" in report.blocking_reasons


def _write_training_csv(path, *, row_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "open_time",
        "train_ready",
        "label_next_1_up",
        *FEATURE_COLUMNS,
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index in range(row_count):
            label_up = index % 2 == 0
            signal = 10.0 if label_up else -10.0
            writer.writerow(
                {
                    "open_time": f"2024-01-01T00:{index:02d}:00+00:00",
                    "train_ready": "True",
                    "label_next_1_up": "True" if label_up else "False",
                    "return_bps": signal,
                    "abs_return_bps": abs(signal),
                    "range_bps": abs(signal) + 2.0,
                    "upper_wick_bps": 1.0 if label_up else 3.0,
                    "lower_wick_bps": 3.0 if label_up else 1.0,
                    "close_to_close_return_bps": signal,
                    "rolling_12_mean_abs_return_bps": abs(signal),
                    "rolling_12_realized_range_bps": abs(signal) + 5.0,
                    "volume": 100.0 + index,
                    "quote_volume": 1000.0 + index,
                    "trade_count": 10 + index,
                }
            )
