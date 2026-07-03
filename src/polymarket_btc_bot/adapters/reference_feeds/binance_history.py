from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class BinanceKline:
    symbol: str
    interval: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trade_count: int

    @property
    def open_return_bps(self) -> float:
        return ((self.close / self.open) - 1.0) * 10_000

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "open_time": self.open_time.isoformat(),
            "close_time": self.close_time.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "quote_volume": self.quote_volume,
            "trade_count": self.trade_count,
            "open_return_bps": self.open_return_bps,
        }


@dataclass(frozen=True)
class KlineHistoryReport:
    path: str | None
    symbol: str
    interval: str
    row_count: int
    first_open_time: str | None
    last_close_time: str | None
    start_price: float | None
    end_price: float | None
    total_return_bps: float | None
    up_rate: float
    mean_return_bps: float
    median_return_bps: float
    mean_abs_return_bps: float
    p90_abs_return_bps: float
    max_abs_return_bps: float
    realized_vol_bps: float
    duplicate_open_time_count: int
    interval_gap_count: int
    sufficient_for_baseline: bool
    blocking_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "symbol": self.symbol,
            "interval": self.interval,
            "row_count": self.row_count,
            "first_open_time": self.first_open_time,
            "last_close_time": self.last_close_time,
            "start_price": self.start_price,
            "end_price": self.end_price,
            "total_return_bps": self.total_return_bps,
            "up_rate": self.up_rate,
            "mean_return_bps": self.mean_return_bps,
            "median_return_bps": self.median_return_bps,
            "mean_abs_return_bps": self.mean_abs_return_bps,
            "p90_abs_return_bps": self.p90_abs_return_bps,
            "max_abs_return_bps": self.max_abs_return_bps,
            "realized_vol_bps": self.realized_vol_bps,
            "duplicate_open_time_count": self.duplicate_open_time_count,
            "interval_gap_count": self.interval_gap_count,
            "sufficient_for_baseline": self.sufficient_for_baseline,
            "blocking_reasons": self.blocking_reasons,
        }


class BinanceHistoricalKlineClient:
    def __init__(self, rest_base_url: str = "https://api.binance.com", timeout: float = 15.0) -> None:
        self.rest_base_url = rest_base_url.rstrip("/")
        self.timeout = timeout

    def get_klines(
        self,
        *,
        symbol: str = "BTCUSDT",
        interval: str = "5m",
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 1000,
    ) -> list[BinanceKline]:
        query: dict[str, str | int] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": max(1, min(limit, 1000)),
        }
        if start is not None:
            query["startTime"] = _to_epoch_ms(start)
        if end is not None:
            query["endTime"] = _to_epoch_ms(end)
        payload = self._get_json(f"/api/v3/klines?{urlencode(query)}")
        return parse_klines(payload, symbol=symbol.upper(), interval=interval)

    def get_klines_range(
        self,
        *,
        symbol: str = "BTCUSDT",
        interval: str = "5m",
        start: datetime,
        end: datetime,
        limit: int = 1000,
        max_pages: int = 200,
    ) -> list[BinanceKline]:
        cursor = start
        page_limit = max(1, min(limit, 1000))
        interval_delta = _interval_delta(interval)
        all_klines: list[BinanceKline] = []
        seen_open_times: set[datetime] = set()

        for _ in range(max_pages):
            if cursor >= end:
                break
            page = self.get_klines(
                symbol=symbol,
                interval=interval,
                start=cursor,
                end=end,
                limit=page_limit,
            )
            if not page:
                break
            new_rows = [kline for kline in page if kline.open_time not in seen_open_times and kline.open_time < end]
            for kline in new_rows:
                seen_open_times.add(kline.open_time)
            all_klines.extend(new_rows)
            next_cursor = page[-1].open_time + interval_delta
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(page) < page_limit:
                break

        return sorted(all_klines, key=lambda kline: kline.open_time)

    def _get_json(self, path: str) -> Any:
        request = Request(
            f"{self.rest_base_url}{path}",
            headers={
                "Accept": "application/json",
                "User-Agent": "polymarket-btc-bot/0.1",
            },
        )
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def parse_klines(payload: list[list[Any]], *, symbol: str, interval: str) -> list[BinanceKline]:
    klines: list[BinanceKline] = []
    for row in payload:
        if len(row) < 9:
            raise ValueError("binance kline row must contain at least 9 fields")
        klines.append(
            BinanceKline(
                symbol=symbol.upper(),
                interval=interval,
                open_time=_from_epoch_ms(int(row[0])),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                close_time=_from_epoch_ms(int(row[6])),
                quote_volume=float(row[7]),
                trade_count=int(row[8]),
            )
        )
    return klines


def write_klines_jsonl(klines: list[BinanceKline], path: Path | str) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for kline in klines:
            handle.write(json.dumps(kline.to_dict(), sort_keys=True) + "\n")
    return output_path


def read_klines_jsonl(path: Path | str) -> list[BinanceKline]:
    input_path = Path(path)
    if not input_path.exists():
        return []
    klines: list[BinanceKline] = []
    for line in input_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        klines.append(
            BinanceKline(
                symbol=str(item["symbol"]),
                interval=str(item["interval"]),
                open_time=datetime.fromisoformat(str(item["open_time"])),
                close_time=datetime.fromisoformat(str(item["close_time"])),
                open=float(item["open"]),
                high=float(item["high"]),
                low=float(item["low"]),
                close=float(item["close"]),
                volume=float(item["volume"]),
                quote_volume=float(item["quote_volume"]),
                trade_count=int(item["trade_count"]),
            )
        )
    return klines


def build_kline_history_report(klines: list[BinanceKline], *, path: Path | str | None = None) -> KlineHistoryReport:
    if not klines:
        return KlineHistoryReport(
            path=str(path) if path else None,
            symbol="unknown",
            interval="unknown",
            row_count=0,
            first_open_time=None,
            last_close_time=None,
            start_price=None,
            end_price=None,
            total_return_bps=None,
            up_rate=0.0,
            mean_return_bps=0.0,
            median_return_bps=0.0,
            mean_abs_return_bps=0.0,
            p90_abs_return_bps=0.0,
            max_abs_return_bps=0.0,
            realized_vol_bps=0.0,
            duplicate_open_time_count=0,
            interval_gap_count=0,
            sufficient_for_baseline=False,
            blocking_reasons=["no_klines"],
        )

    returns = [kline.open_return_bps for kline in klines]
    abs_returns = sorted(abs(value) for value in returns)
    blocking_reasons = _history_blocking_reasons(klines)
    duplicate_count = _duplicate_open_time_count(klines)
    gap_count = _interval_gap_count(klines)
    start_price = klines[0].open
    end_price = klines[-1].close
    return KlineHistoryReport(
        path=str(path) if path else None,
        symbol=klines[0].symbol,
        interval=klines[0].interval,
        row_count=len(klines),
        first_open_time=klines[0].open_time.isoformat(),
        last_close_time=klines[-1].close_time.isoformat(),
        start_price=start_price,
        end_price=end_price,
        total_return_bps=((end_price / start_price) - 1.0) * 10_000,
        up_rate=round(sum(1 for value in returns if value > 0) / len(returns), 4),
        mean_return_bps=round(mean(returns), 6),
        median_return_bps=round(median(returns), 6),
        mean_abs_return_bps=round(mean(abs_returns), 6),
        p90_abs_return_bps=round(_percentile(abs_returns, 0.90), 6),
        max_abs_return_bps=round(max(abs_returns), 6),
        realized_vol_bps=round(pstdev(returns), 6) if len(returns) > 1 else 0.0,
        duplicate_open_time_count=duplicate_count,
        interval_gap_count=gap_count,
        sufficient_for_baseline=not blocking_reasons,
        blocking_reasons=blocking_reasons,
    )


def default_history_path(symbol: str, interval: str, start: datetime, end: datetime) -> Path:
    return Path("data/history") / (
        f"{symbol.lower()}-{interval}-{start.date().isoformat()}-{end.date().isoformat()}.jsonl"
    )


def _history_blocking_reasons(klines: list[BinanceKline]) -> list[str]:
    reasons: list[str] = []
    if len(klines) < 288:
        reasons.append("less_than_one_day_of_5m_bars")
    if any(kline.open <= 0 or kline.high <= 0 or kline.low <= 0 or kline.close <= 0 for kline in klines):
        reasons.append("non_positive_price")
    if any(kline.high < max(kline.open, kline.close) or kline.low > min(kline.open, kline.close) for kline in klines):
        reasons.append("ohlc_inconsistent")
    if any(left.open_time >= right.open_time for left, right in zip(klines, klines[1:])):
        reasons.append("non_monotonic_open_time")
    if _duplicate_open_time_count(klines) > 0:
        reasons.append("duplicate_open_times")
    if _interval_gap_count(klines) > 0:
        reasons.append("interval_gaps")
    return reasons


def _duplicate_open_time_count(klines: list[BinanceKline]) -> int:
    seen: set[datetime] = set()
    duplicates = 0
    for kline in klines:
        if kline.open_time in seen:
            duplicates += 1
        seen.add(kline.open_time)
    return duplicates


def _interval_gap_count(klines: list[BinanceKline]) -> int:
    if len(klines) < 2:
        return 0
    expected = _interval_delta(klines[0].interval)
    return sum(1 for left, right in zip(klines, klines[1:]) if right.open_time - left.open_time != expected)


def _percentile(sorted_values: list[float], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, max(0, int(round((len(sorted_values) - 1) * percentile))))
    return sorted_values[index]


def _to_epoch_ms(value: datetime) -> int:
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return int(aware.timestamp() * 1000)


def _from_epoch_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def _interval_delta(interval: str) -> timedelta:
    if interval.endswith("m"):
        return timedelta(minutes=int(interval[:-1]))
    if interval.endswith("h"):
        return timedelta(hours=int(interval[:-1]))
    if interval.endswith("d"):
        return timedelta(days=int(interval[:-1]))
    raise ValueError(f"unsupported kline interval: {interval}")
