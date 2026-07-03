from __future__ import annotations

import csv
import math
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any


FEATURE_COLUMNS = [
    "return_bps",
    "abs_return_bps",
    "range_bps",
    "upper_wick_bps",
    "lower_wick_bps",
    "close_to_close_return_bps",
    "rolling_12_mean_abs_return_bps",
    "rolling_12_realized_range_bps",
    "volume",
    "quote_volume",
    "trade_count",
]


@dataclass(frozen=True)
class BtcModelInputRow:
    open_time: str
    features: dict[str, float]
    label_up: bool


@dataclass(frozen=True)
class BtcModelEvaluation:
    path: str
    target: str
    rows: int
    train_ready_rows: int
    evaluated_rows: int
    skipped_rows: int
    min_train_rows: int
    train_window_rows: int
    model_accuracy: float | None
    baseline_accuracy: float | None
    model_brier: float | None
    baseline_brier: float | None
    model_log_loss: float | None
    baseline_log_loss: float | None
    brier_improvement: float | None
    mean_model_probability: float | None
    mean_baseline_probability: float | None
    decision: str
    blocking_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "target": self.target,
            "rows": self.rows,
            "train_ready_rows": self.train_ready_rows,
            "evaluated_rows": self.evaluated_rows,
            "skipped_rows": self.skipped_rows,
            "min_train_rows": self.min_train_rows,
            "train_window_rows": self.train_window_rows,
            "model_accuracy": self.model_accuracy,
            "baseline_accuracy": self.baseline_accuracy,
            "model_brier": self.model_brier,
            "baseline_brier": self.baseline_brier,
            "model_log_loss": self.model_log_loss,
            "baseline_log_loss": self.baseline_log_loss,
            "brier_improvement": self.brier_improvement,
            "mean_model_probability": self.mean_model_probability,
            "mean_baseline_probability": self.mean_baseline_probability,
            "decision": self.decision,
            "blocking_reasons": self.blocking_reasons,
        }


def evaluate_btc_training_csv(
    path: Path | str,
    *,
    target: str = "label_next_1_up",
    min_train_rows: int = 288,
    train_window_rows: int = 2016,
    min_evaluation_rows: int = 100,
) -> BtcModelEvaluation:
    input_path = Path(path)
    rows, total_rows = read_btc_model_input_rows(input_path, target=target)
    evaluated: list[tuple[bool, float, float]] = []
    skipped_rows = total_rows - len(rows)
    rolling_stats = _RollingFeatureStats()
    rolling_rows: deque[BtcModelInputRow] = deque()

    for row in rows:
        if rolling_stats.count < min_train_rows:
            skipped_rows += 1
        else:
            model_probability = _walk_forward_probability(rolling_stats, row)
            baseline_probability = rolling_stats.baseline_probability()
            evaluated.append((row.label_up, model_probability, baseline_probability))

        rolling_rows.append(row)
        rolling_stats.add(row)
        if len(rolling_rows) > train_window_rows:
            rolling_stats.remove(rolling_rows.popleft())

    blocking_reasons: list[str] = []
    if not input_path.exists():
        blocking_reasons.append("training_csv_not_found")
    if not rows:
        blocking_reasons.append("no_train_ready_rows")
    if len(evaluated) < min_evaluation_rows:
        blocking_reasons.append("insufficient_evaluation_rows")

    metrics = _metrics(evaluated)
    brier_improvement = None
    if metrics["model_brier"] is not None and metrics["baseline_brier"] is not None:
        brier_improvement = round(metrics["baseline_brier"] - metrics["model_brier"], 8)

    decision = _decision(
        blocking_reasons=blocking_reasons,
        brier_improvement=brier_improvement,
        model_accuracy=metrics["model_accuracy"],
        baseline_accuracy=metrics["baseline_accuracy"],
    )

    return BtcModelEvaluation(
        path=str(input_path),
        target=target,
        rows=total_rows,
        train_ready_rows=len(rows),
        evaluated_rows=len(evaluated),
        skipped_rows=skipped_rows,
        min_train_rows=min_train_rows,
        train_window_rows=train_window_rows,
        model_accuracy=metrics["model_accuracy"],
        baseline_accuracy=metrics["baseline_accuracy"],
        model_brier=metrics["model_brier"],
        baseline_brier=metrics["baseline_brier"],
        model_log_loss=metrics["model_log_loss"],
        baseline_log_loss=metrics["baseline_log_loss"],
        brier_improvement=brier_improvement,
        mean_model_probability=metrics["mean_model_probability"],
        mean_baseline_probability=metrics["mean_baseline_probability"],
        decision=decision,
        blocking_reasons=blocking_reasons,
    )


def read_btc_model_input_rows(path: Path | str, *, target: str) -> tuple[list[BtcModelInputRow], int]:
    input_path = Path(path)
    if not input_path.exists():
        return [], 0

    parsed_rows: list[BtcModelInputRow] = []
    total_rows = 0
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            total_rows += 1
            if not _parse_bool(raw.get("train_ready")):
                continue
            label = _parse_bool(raw.get(target))
            if label is None:
                continue
            features = _parse_features(raw)
            if len(features) != len(FEATURE_COLUMNS):
                continue
            parsed_rows.append(
                BtcModelInputRow(
                    open_time=str(raw.get("open_time", "")),
                    features=features,
                    label_up=label,
                )
            )
    return parsed_rows, total_rows


def _walk_forward_probability(stats: _RollingFeatureStats, row: BtcModelInputRow) -> float:
    weighted_score = 0.0
    total_weight = 0.0
    for feature in FEATURE_COLUMNS:
        weight = stats.correlation(feature)
        std = stats.feature_std(feature)
        if std == 0:
            continue
        z_score = (row.features[feature] - stats.feature_mean(feature)) / std
        weighted_score += weight * max(-5.0, min(5.0, z_score))
        total_weight += abs(weight)

    if total_weight == 0:
        return stats.baseline_probability()
    return _clamp_probability(_sigmoid(weighted_score / total_weight))


class _RollingFeatureStats:
    def __init__(self) -> None:
        self.count = 0
        self.label_sum = 0.0
        self.label_square_sum = 0.0
        self.feature_sums = {feature: 0.0 for feature in FEATURE_COLUMNS}
        self.feature_square_sums = {feature: 0.0 for feature in FEATURE_COLUMNS}
        self.feature_label_sums = {feature: 0.0 for feature in FEATURE_COLUMNS}

    def add(self, row: BtcModelInputRow) -> None:
        self._apply(row, sign=1.0)
        self.count += 1

    def remove(self, row: BtcModelInputRow) -> None:
        self._apply(row, sign=-1.0)
        self.count -= 1

    def baseline_probability(self) -> float:
        if self.count == 0:
            return 0.5
        return _clamp_probability(self.label_sum / self.count)

    def feature_mean(self, feature: str) -> float:
        if self.count == 0:
            return 0.0
        return self.feature_sums[feature] / self.count

    def feature_std(self, feature: str) -> float:
        if self.count < 2:
            return 0.0
        mean_value = self.feature_mean(feature)
        variance = (self.feature_square_sums[feature] / self.count) - (mean_value * mean_value)
        return math.sqrt(max(0.0, variance))

    def correlation(self, feature: str) -> float:
        if self.count < 2:
            return 0.0
        feature_std = self.feature_std(feature)
        label_mean = self.label_sum / self.count
        label_variance = (self.label_square_sum / self.count) - (label_mean * label_mean)
        label_std = math.sqrt(max(0.0, label_variance))
        if feature_std == 0 or label_std == 0:
            return 0.0
        covariance = (self.feature_label_sums[feature] / self.count) - (self.feature_mean(feature) * label_mean)
        return covariance / (feature_std * label_std)

    def _apply(self, row: BtcModelInputRow, *, sign: float) -> None:
        label = 1.0 if row.label_up else 0.0
        self.label_sum += sign * label
        self.label_square_sum += sign * label * label
        for feature in FEATURE_COLUMNS:
            value = row.features[feature]
            self.feature_sums[feature] += sign * value
            self.feature_square_sums[feature] += sign * value * value
            self.feature_label_sums[feature] += sign * value * label


def _metrics(evaluated: list[tuple[bool, float, float]]) -> dict[str, float | None]:
    if not evaluated:
        return {
            "model_accuracy": None,
            "baseline_accuracy": None,
            "model_brier": None,
            "baseline_brier": None,
            "model_log_loss": None,
            "baseline_log_loss": None,
            "mean_model_probability": None,
            "mean_baseline_probability": None,
        }

    labels = [1.0 if label else 0.0 for label, _, _ in evaluated]
    model_probs = [probability for _, probability, _ in evaluated]
    baseline_probs = [probability for _, _, probability in evaluated]
    return {
        "model_accuracy": round(_accuracy(labels, model_probs), 4),
        "baseline_accuracy": round(_accuracy(labels, baseline_probs), 4),
        "model_brier": round(_brier(labels, model_probs), 8),
        "baseline_brier": round(_brier(labels, baseline_probs), 8),
        "model_log_loss": round(_log_loss(labels, model_probs), 8),
        "baseline_log_loss": round(_log_loss(labels, baseline_probs), 8),
        "mean_model_probability": round(mean(model_probs), 6),
        "mean_baseline_probability": round(mean(baseline_probs), 6),
    }


def _decision(
    *,
    blocking_reasons: list[str],
    brier_improvement: float | None,
    model_accuracy: float | None,
    baseline_accuracy: float | None,
) -> str:
    if blocking_reasons:
        return "insufficient_data"
    if brier_improvement is None or model_accuracy is None or baseline_accuracy is None:
        return "insufficient_data"
    if brier_improvement > 0.0005 and model_accuracy >= baseline_accuracy:
        return "candidate_signal_not_execution_edge"
    return "no_measurable_predictive_edge"


def _parse_features(raw: dict[str, str | None]) -> dict[str, float]:
    features: dict[str, float] = {}
    for name in FEATURE_COLUMNS:
        value = _parse_float(raw.get(name))
        if value is None:
            continue
        features[name] = value
    return features


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def _parse_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _accuracy(labels: list[float], probabilities: list[float]) -> float:
    return sum(1 for label, probability in zip(labels, probabilities) if (probability >= 0.5) == bool(label)) / len(labels)


def _brier(labels: list[float], probabilities: list[float]) -> float:
    return mean((probability - label) ** 2 for label, probability in zip(labels, probabilities))


def _log_loss(labels: list[float], probabilities: list[float]) -> float:
    return mean(
        -(label * math.log(_clamp_probability(probability)) + (1.0 - label) * math.log(1.0 - _clamp_probability(probability)))
        for label, probability in zip(labels, probabilities)
    )


def _sigmoid(value: float) -> float:
    if value >= 0:
        z_value = math.exp(-value)
        return 1.0 / (1.0 + z_value)
    z_value = math.exp(value)
    return z_value / (1.0 + z_value)


def _clamp_probability(value: float) -> float:
    return min(0.99, max(0.01, value))
