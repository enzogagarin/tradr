from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class PolymarketDataApiClient:
    def __init__(self, base_url: str = "https://data-api.polymarket.com", timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_activity(self, *, user: str, limit: int = 500, offset: int = 0) -> list[dict[str, Any]]:
        return _list_from_payload(
            self._get_json(
                "/activity?"
                + urlencode(
                    {
                        "user": user,
                        "limit": _bounded_limit(limit),
                        "offset": max(0, offset),
                    }
                )
            )
        )

    def get_positions(self, *, user: str, limit: int = 500, offset: int = 0) -> list[dict[str, Any]]:
        return _list_from_payload(
            self._get_json(
                "/positions?"
                + urlencode(
                    {
                        "user": user,
                        "limit": _bounded_limit(limit),
                        "offset": max(0, offset),
                    }
                )
            )
        )

    def get_activity_pages(self, *, user: str, page_limit: int = 500, max_rows: int = 10_000) -> list[dict[str, Any]]:
        return self._get_pages(kind="activity", user=user, page_limit=page_limit, max_rows=max_rows)

    def get_position_pages(self, *, user: str, page_limit: int = 500, max_rows: int = 10_000) -> list[dict[str, Any]]:
        return self._get_pages(kind="positions", user=user, page_limit=page_limit, max_rows=max_rows)

    def _get_pages(self, *, kind: str, user: str, page_limit: int, max_rows: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page_size = _bounded_limit(page_limit)
        max_rows = max(0, min(max_rows, 10_000))
        for offset in range(0, max_rows, page_size):
            try:
                page = (
                    self.get_activity(user=user, limit=page_size, offset=offset)
                    if kind == "activity"
                    else self.get_positions(user=user, limit=page_size, offset=offset)
                )
            except HTTPError as exc:
                if exc.code == 400 and rows:
                    break
                raise
            rows.extend(page)
            if len(page) < page_size:
                break
        return rows[:max_rows]

    def _get_json(self, path: str) -> Any:
        request = Request(
            f"{self.base_url}{path}",
            headers={
                "Accept": "application/json",
                "User-Agent": "polymarket-btc-bot/0.1",
            },
        )
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def write_jsonl(rows: list[dict[str, Any]], path: Path | str) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return output_path


def read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    input_path = Path(path)
    if not input_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in input_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _bounded_limit(limit: int) -> int:
    return max(1, min(limit, 500))


def _list_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "activity", "positions"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []
