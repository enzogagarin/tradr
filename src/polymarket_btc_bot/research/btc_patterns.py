from __future__ import annotations

import csv
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Any


@dataclass(frozen=True)
class BtcPatternObservation:
    source: str
    open_time: datetime
    return_bps: float
    abs_return_bps: float
    range_bps: float
    upper_wick_bps: float
    lower_wick_bps: float
    close_to_close_return_bps: float
    rolling_12_mean_abs_return_bps: float
    rolling_12_realized_range_bps: float
    label_return_bps: float
    label_up: bool
    trailing_12_return_bps: float
    trailing_3_return_bps: float


@dataclass(frozen=True)
class PatternStat:
    pattern: str
    support: int
    support_ratio: float
    up_rate: float
    baseline_up_rate: float
    up_rate_delta: float
    mean_forward_return_bps: float
    baseline_mean_forward_return_bps: float
    mean_return_delta_bps: float
    t_stat: float | None
    score: float
    sources: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "support": self.support,
            "support_ratio": self.support_ratio,
            "up_rate": self.up_rate,
            "baseline_up_rate": self.baseline_up_rate,
            "up_rate_delta": self.up_rate_delta,
            "mean_forward_return_bps": self.mean_forward_return_bps,
            "baseline_mean_forward_return_bps": self.baseline_mean_forward_return_bps,
            "mean_return_delta_bps": self.mean_return_delta_bps,
            "t_stat": self.t_stat,
            "score": self.score,
            "sources": self.sources,
        }


def scan_btc_patterns(
    paths: list[Path | str],
    *,
    target_horizon: int = 1,
    min_support: int = 500,
    top_n: int = 30,
) -> dict[str, Any]:
    observations = _read_observations(paths, target_horizon=target_horizon)
    if not observations:
        return {
            "paths": [str(path) for path in paths],
            "target_horizon": target_horizon,
            "rows": 0,
            "baseline": {},
            "patterns": [],
            "blocking_reasons": ["no_observations"],
        }

    baseline_up_rate = sum(1 for row in observations if row.label_up) / len(observations)
    baseline_mean_return = mean(row.label_return_bps for row in observations)
    vol_low, vol_high = _quantile_pair([row.rolling_12_mean_abs_return_bps for row in observations])
    range_low, range_high = _quantile_pair([row.rolling_12_realized_range_bps for row in observations])

    buckets: dict[str, list[BtcPatternObservation]] = defaultdict(list)
    for row in observations:
        for pattern in _patterns_for(row, vol_low=vol_low, vol_high=vol_high, range_low=range_low, range_high=range_high):
            buckets[pattern].append(row)

    stats = [
        _pattern_stat(
            pattern,
            rows,
            total_rows=len(observations),
            baseline_up_rate=baseline_up_rate,
            baseline_mean_return=baseline_mean_return,
        )
        for pattern, rows in buckets.items()
        if len(rows) >= min_support
    ]
    stats.sort(key=lambda item: item.score, reverse=True)

    return {
        "paths": [str(path) for path in paths],
        "target_horizon": target_horizon,
        "rows": len(observations),
        "min_support": min_support,
        "baseline": {
            "up_rate": round(baseline_up_rate, 6),
            "mean_forward_return_bps": round(baseline_mean_return, 6),
            "volatility_low_cutoff_bps": round(vol_low, 6),
            "volatility_high_cutoff_bps": round(vol_high, 6),
            "range_low_cutoff_bps": round(range_low, 6),
            "range_high_cutoff_bps": round(range_high, 6),
        },
        "patterns": [item.to_dict() for item in stats[:top_n]],
        "blocking_reasons": [],
    }


def _read_observations(paths: list[Path | str], *, target_horizon: int) -> list[BtcPatternObservation]:
    observations: list[BtcPatternObservation] = []
    label_return_column = f"label_next_{target_horizon}_return_bps"
    label_up_column = f"label_next_{target_horizon}_up"

    for path in paths:
        source = str(path)
        trailing_returns: deque[float] = deque()
        with Path(path).open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for raw in reader:
                close_to_close = _parse_float(raw.get("close_to_close_return_bps"))
                if close_to_close is None:
                    continue
                trailing_returns.append(close_to_close)
                if len(trailing_returns) > 12:
                    trailing_returns.popleft()
                row = _parse_observation(
                    raw,
                    source=source,
                    label_return_column=label_return_column,
                    label_up_column=label_up_column,
                    trailing_12_return_bps=sum(trailing_returns),
                    trailing_3_return_bps=sum(list(trailing_returns)[-3:]),
                )
                if row is not None:
                    observations.append(row)
    return observations


def _parse_observation(
    raw: dict[str, str | None],
    *,
    source: str,
    label_return_column: str,
    label_up_column: str,
    trailing_12_return_bps: float,
    trailing_3_return_bps: float,
) -> BtcPatternObservation | None:
    if _parse_bool(raw.get("train_ready")) is not True:
        return None
    label_return = _parse_float(raw.get(label_return_column))
    label_up = _parse_bool(raw.get(label_up_column))
    fields = {
        "return_bps": _parse_float(raw.get("return_bps")),
        "abs_return_bps": _parse_float(raw.get("abs_return_bps")),
        "range_bps": _parse_float(raw.get("range_bps")),
        "upper_wick_bps": _parse_float(raw.get("upper_wick_bps")),
        "lower_wick_bps": _parse_float(raw.get("lower_wick_bps")),
        "close_to_close_return_bps": _parse_float(raw.get("close_to_close_return_bps")),
        "rolling_12_mean_abs_return_bps": _parse_float(raw.get("rolling_12_mean_abs_return_bps")),
        "rolling_12_realized_range_bps": _parse_float(raw.get("rolling_12_realized_range_bps")),
    }
    if label_return is None or label_up is None or any(value is None for value in fields.values()):
        return None
    return BtcPatternObservation(
        source=source,
        open_time=datetime.fromisoformat(str(raw["open_time"])),
        label_return_bps=label_return,
        label_up=label_up,
        trailing_12_return_bps=trailing_12_return_bps,
        trailing_3_return_bps=trailing_3_return_bps,
        **fields,  # type: ignore[arg-type]
    )


def _patterns_for(
    row: BtcPatternObservation,
    *,
    vol_low: float,
    vol_high: float,
    range_low: float,
    range_high: float,
) -> list[str]:
    direction = _direction(row.return_bps, threshold=2.0)
    trend_3 = _direction(row.trailing_3_return_bps, threshold=5.0)
    trend_12 = _direction(row.trailing_12_return_bps, threshold=15.0)
    vol_regime = _regime(row.rolling_12_mean_abs_return_bps, low=vol_low, high=vol_high)
    range_regime = _regime(row.rolling_12_realized_range_bps, low=range_low, high=range_high)
    wick = _wick_pattern(row)
    hour = row.open_time.hour
    day = row.open_time.weekday()

    patterns = [
        f"hour={hour:02d}",
        f"weekday={day}",
        f"direction={direction}",
        f"trend_3={trend_3}",
        f"trend_12={trend_12}",
        f"vol_regime={vol_regime}",
        f"range_regime={range_regime}",
        f"wick={wick}",
        f"direction={direction}|vol_regime={vol_regime}",
        f"trend_12={trend_12}|vol_regime={vol_regime}",
        f"trend_12={trend_12}|range_regime={range_regime}",
        f"hour={hour:02d}|vol_regime={vol_regime}",
        f"direction={direction}|wick={wick}",
    ]

    if abs(row.return_bps) >= 20:
        patterns.append(f"impulse_5m={direction}|vol_regime={vol_regime}")
    if trend_12 != "flat" and direction != "flat":
        relation = "continuation" if trend_12 == direction else "reversal"
        patterns.append(f"{relation}|trend_12={trend_12}|direction={direction}|vol_regime={vol_regime}")
    if row.range_bps >= range_high and direction != "flat":
        patterns.append(f"wide_range_{direction}|vol_regime={vol_regime}")
    return patterns


def _pattern_stat(
    pattern: str,
    rows: list[BtcPatternObservation],
    *,
    total_rows: int,
    baseline_up_rate: float,
    baseline_mean_return: float,
) -> PatternStat:
    labels = [1.0 if row.label_up else 0.0 for row in rows]
    forward_returns = [row.label_return_bps for row in rows]
    up_rate = mean(labels)
    mean_return = mean(forward_returns)
    mean_delta = mean_return - baseline_mean_return
    t_stat = _t_stat(forward_returns, baseline_mean_return)
    up_delta = up_rate - baseline_up_rate
    score = abs(mean_delta) * math.sqrt(len(rows)) + abs(up_delta) * 100.0 * math.sqrt(len(rows))
    return PatternStat(
        pattern=pattern,
        support=len(rows),
        support_ratio=round(len(rows) / total_rows, 6),
        up_rate=round(up_rate, 6),
        baseline_up_rate=round(baseline_up_rate, 6),
        up_rate_delta=round(up_delta, 6),
        mean_forward_return_bps=round(mean_return, 6),
        baseline_mean_forward_return_bps=round(baseline_mean_return, 6),
        mean_return_delta_bps=round(mean_delta, 6),
        t_stat=None if t_stat is None else round(t_stat, 6),
        score=round(score, 6),
        sources=sorted({row.source for row in rows}),
    )


def _t_stat(values: list[float], baseline: float) -> float | None:
    if len(values) < 2:
        return None
    std = pstdev(values)
    if std == 0:
        return None
    return (mean(values) - baseline) / (std / math.sqrt(len(values)))


def _direction(value: float, *, threshold: float) -> str:
    if value >= threshold:
        return "up"
    if value <= -threshold:
        return "down"
    return "flat"


def _regime(value: float, *, low: float, high: float) -> str:
    if value <= low:
        return "low"
    if value >= high:
        return "high"
    return "mid"


def _wick_pattern(row: BtcPatternObservation) -> str:
    if row.lower_wick_bps >= row.upper_wick_bps * 2 and row.lower_wick_bps >= 2:
        return "lower_rejection"
    if row.upper_wick_bps >= row.lower_wick_bps * 2 and row.upper_wick_bps >= 2:
        return "upper_rejection"
    return "balanced"


def _quantile_pair(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    sorted_values = sorted(values)
    return _quantile(sorted_values, 0.33), _quantile(sorted_values, 0.66)


def _quantile(sorted_values: list[float], q_value: float) -> float:
    index = min(len(sorted_values) - 1, max(0, int(round((len(sorted_values) - 1) * q_value))))
    return sorted_values[index]


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
