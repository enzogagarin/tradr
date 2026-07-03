from __future__ import annotations

import csv
from dataclasses import dataclass, fields
from pathlib import Path
from statistics import mean
from typing import Any

from polymarket_btc_bot.adapters.reference_feeds import BinanceKline


@dataclass(frozen=True)
class BtcTrainingRow:
    open_time: str
    close_time: str
    symbol: str
    interval: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trade_count: int
    return_bps: float
    abs_return_bps: float
    range_bps: float
    upper_wick_bps: float
    lower_wick_bps: float
    close_to_close_return_bps: float | None
    rolling_12_mean_abs_return_bps: float | None
    rolling_12_realized_range_bps: float | None
    label_next_1_return_bps: float | None
    label_next_1_up: bool | None
    label_next_3_return_bps: float | None
    label_next_3_up: bool | None
    label_next_12_return_bps: float | None
    label_next_12_up: bool | None
    train_ready: bool
    blocking_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


def build_btc_training_rows(klines: list[BinanceKline]) -> list[BtcTrainingRow]:
    rows: list[BtcTrainingRow] = []
    for index, kline in enumerate(klines):
        previous = klines[index - 1] if index > 0 else None
        rolling_window = klines[max(0, index - 11) : index + 1]
        label_next_1 = _future_return_bps(klines, index, 1)
        label_next_3 = _future_return_bps(klines, index, 3)
        label_next_12 = _future_return_bps(klines, index, 12)
        blocking_reason = _row_blocking_reason(kline, previous, label_next_1, label_next_3, label_next_12)
        rows.append(
            BtcTrainingRow(
                open_time=kline.open_time.isoformat(),
                close_time=kline.close_time.isoformat(),
                symbol=kline.symbol,
                interval=kline.interval,
                open=kline.open,
                high=kline.high,
                low=kline.low,
                close=kline.close,
                volume=kline.volume,
                quote_volume=kline.quote_volume,
                trade_count=kline.trade_count,
                return_bps=round(kline.open_return_bps, 6),
                abs_return_bps=round(abs(kline.open_return_bps), 6),
                range_bps=round(((kline.high / kline.low) - 1.0) * 10_000, 6),
                upper_wick_bps=round(((kline.high / max(kline.open, kline.close)) - 1.0) * 10_000, 6),
                lower_wick_bps=round(((min(kline.open, kline.close) / kline.low) - 1.0) * 10_000, 6),
                close_to_close_return_bps=None
                if previous is None
                else round(((kline.close / previous.close) - 1.0) * 10_000, 6),
                rolling_12_mean_abs_return_bps=_rolling_mean_abs_return_bps(rolling_window),
                rolling_12_realized_range_bps=_rolling_realized_range_bps(rolling_window),
                label_next_1_return_bps=label_next_1,
                label_next_1_up=None if label_next_1 is None else label_next_1 > 0,
                label_next_3_return_bps=label_next_3,
                label_next_3_up=None if label_next_3 is None else label_next_3 > 0,
                label_next_12_return_bps=label_next_12,
                label_next_12_up=None if label_next_12 is None else label_next_12 > 0,
                train_ready=blocking_reason is None,
                blocking_reason=blocking_reason,
            )
        )
    return rows


def write_btc_training_csv(rows: list[BtcTrainingRow], path: Path | str) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    names = [field.name for field in fields(BtcTrainingRow)]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())
    return output_path


def btc_training_summary(rows: list[BtcTrainingRow], path: Path | str | None = None) -> dict[str, Any]:
    train_ready_rows = [row for row in rows if row.train_ready]
    blocking_reasons = sorted({row.blocking_reason for row in rows if row.blocking_reason})
    return {
        "path": str(path) if path else None,
        "rows": len(rows),
        "train_ready_rows": len(train_ready_rows),
        "train_ready_ratio": round(len(train_ready_rows) / len(rows), 4) if rows else 0.0,
        "blocking_reasons": blocking_reasons,
        "first_open_time": rows[0].open_time if rows else None,
        "last_open_time": rows[-1].open_time if rows else None,
    }


def _future_return_bps(klines: list[BinanceKline], index: int, horizon: int) -> float | None:
    target_index = index + horizon
    if target_index >= len(klines):
        return None
    return round(((klines[target_index].close / klines[index].close) - 1.0) * 10_000, 6)


def _rolling_mean_abs_return_bps(klines: list[BinanceKline]) -> float | None:
    if len(klines) < 2:
        return None
    return round(mean(abs(kline.open_return_bps) for kline in klines), 6)


def _rolling_realized_range_bps(klines: list[BinanceKline]) -> float | None:
    if not klines:
        return None
    low = min(kline.low for kline in klines)
    high = max(kline.high for kline in klines)
    return round(((high / low) - 1.0) * 10_000, 6)


def _row_blocking_reason(
    kline: BinanceKline,
    previous: BinanceKline | None,
    label_next_1: float | None,
    label_next_3: float | None,
    label_next_12: float | None,
) -> str | None:
    if previous is None:
        return "missing_previous_close"
    if label_next_1 is None or label_next_3 is None or label_next_12 is None:
        return "missing_forward_label"
    if min(kline.open, kline.high, kline.low, kline.close) <= 0:
        return "non_positive_price"
    if kline.high < max(kline.open, kline.close) or kline.low > min(kline.open, kline.close):
        return "ohlc_inconsistent"
    return None
