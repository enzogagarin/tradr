from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from polymarket_btc_bot.domain import Market, MarketAsset


class GammaClient:
    def __init__(self, base_url: str = "https://gamma-api.polymarket.com", timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.last_scan_stats: dict[str, int] = {
            "pages_scanned": 0,
            "events_scanned": 0,
            "markets_found": 0,
        }

    def discover_btc_5m_markets(self, limit: int = 50, pages: int = 5) -> list[Market]:
        all_events: list[dict[str, Any]] = []
        page_size = min(max(limit, 1), 100)
        for page in range(max(pages, 1)):
            query = urlencode(
                {
                    "active": "true",
                    "closed": "false",
                    "limit": str(page_size),
                    "offset": str(page * page_size),
                    "order": "endDate",
                    "ascending": "true",
                }
            )
            payload = self._get_json(f"/events?{query}")
            events = _events_from_payload(payload)
            if not events:
                break
            all_events.extend(events)
        all_events.extend(self._direct_btc_5m_events())
        markets = discover_btc_5m_markets_from_payload(all_events)
        self.last_scan_stats = {
            "pages_scanned": page + 1 if all_events else 0,
            "events_scanned": len(all_events),
            "markets_found": len(markets),
        }
        return markets

    def _direct_btc_5m_events(self) -> list[dict[str, Any]]:
        """Fetch current/near-future BTC 5m events by deterministic slug.

        Gamma's broad event/search endpoints can omit these short-lived markets
        from paginated results, while direct slug lookups return them reliably.
        """
        now = datetime.now(tz=UTC)
        base_ts = int(now.timestamp() // 300) * 300
        events: list[dict[str, Any]] = []
        seen: set[str] = set()
        for offset in range(-1, 7):
            ts = base_ts + offset * 300
            for prefix in ("btc-updown-5m", "bitcoin-updown-5m"):
                slug = f"{prefix}-{ts}"
                if slug in seen:
                    continue
                seen.add(slug)
                query = urlencode({"slug": slug})
                try:
                    payload = self._get_json(f"/events?{query}")
                except Exception:
                    continue
                events.extend(_events_from_payload(payload))
        return events

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


def discover_btc_5m_markets_from_payload(events: list[dict[str, Any]]) -> list[Market]:
    markets: list[Market] = []
    now = datetime.now(tz=UTC)
    for event in events:
        event_title = str(event.get("title") or event.get("question") or "")
        event_slug = str(event.get("slug") or "")
        if not _looks_like_btc_5m(event_title, event_slug):
            continue
        for market_payload in event.get("markets") or []:
            market = _market_from_payload(event, market_payload)
            if market is not None:
                if market.end_ts > now:
                    markets.append(market)
    return sorted(markets, key=lambda market: market.end_ts)


def _events_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [event for event in payload if isinstance(event, dict)]
    if isinstance(payload, dict):
        events = payload.get("events", [])
        return [event for event in events if isinstance(event, dict)]
    return []


def _looks_like_btc_5m(title: str, slug: str) -> bool:
    text = f"{title} {slug}".lower()
    return (
        ("bitcoin" in text or "btc" in text)
        and "up" in text
        and "down" in text
        and ("5m" in text or "5-min" in text or "5 min" in text or _has_5m_timestamp_slug(slug))
    )


def _has_5m_timestamp_slug(slug: str) -> bool:
    # Current BTC 5m event slugs include a terminal unix timestamp.
    return slug.startswith("btc-updown-5m-") or slug.startswith("bitcoin-updown-5m-")


def _market_from_payload(event: dict[str, Any], market_payload: dict[str, Any]) -> Market | None:
    raw_token_ids = market_payload.get("clobTokenIds") or market_payload.get("tokenIds")
    raw_outcomes = market_payload.get("outcomes")
    token_ids = _decode_jsonish_list(raw_token_ids)
    outcomes = [str(item).upper() for item in _decode_jsonish_list(raw_outcomes)]
    if len(token_ids) != 2 or len(outcomes) != 2:
        return None

    token_by_outcome = dict(zip(outcomes, token_ids, strict=False))
    up_token = token_by_outcome.get("UP")
    down_token = token_by_outcome.get("DOWN")
    if not up_token or not down_token:
        return None

    slug = str(market_payload.get("slug") or event.get("slug") or "")
    start_ts = _start_ts_from_slug(slug) or _parse_ts(
        market_payload.get("startDate")
        or event.get("startDate")
        or market_payload.get("startTime")
        or event.get("startTime")
    )
    end_ts = _parse_ts(
        market_payload.get("endDate")
        or event.get("endDate")
        or market_payload.get("endTime")
        or event.get("endTime")
    )
    if start_ts is None or end_ts is None or end_ts <= start_ts:
        return None

    market_id = str(market_payload.get("id") or market_payload.get("conditionId") or event.get("id") or "")
    if not market_id:
        return None

    return Market(
        market_id=market_id,
        slug=slug,
        question=str(market_payload.get("question") or event.get("title") or ""),
        start_ts=start_ts,
        end_ts=end_ts,
        up=MarketAsset(str(up_token), "UP"),
        down=MarketAsset(str(down_token), "DOWN"),
        status="OPEN",
    )


def _start_ts_from_slug(slug: str) -> datetime | None:
    if not _has_5m_timestamp_slug(slug):
        return None
    try:
        timestamp = int(slug.rsplit("-", 1)[1])
    except (ValueError, IndexError):
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC)


def _decode_jsonish_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return None
