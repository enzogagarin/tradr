from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from polymarket_btc_bot.domain import Market, OrderBook, StrategyDecision, utc_now


@dataclass(frozen=True)
class WalletSignalConfig:
    enabled: bool = True
    mode: str = "overlay"
    min_win_rate: float = 0.95
    min_support: int = 20
    min_recurrence_days: int = 5
    max_avoid_loss_rate: float = 0.5
    max_entry_price: float = 0.35
    min_confidence_boost: float = 0.02
    local_tz: str = "Europe/Istanbul"
    require_validated: bool = True
    min_validation_win_rate: float = 0.75
    min_validation_wilson_lower: float = 0.60
    max_train_validation_win_rate_delta: float = 0.30


class WalletOpportunityOverlay:
    """Apply wallet-learned opportunity/avoid patterns to baseline decisions.

    In overlay mode, wallet data can block known failure patterns or boost a
    baseline trade that also matches a high-quality wallet pattern. In gate
    mode, wallet data becomes a hard filter: the bot only trades when the
    baseline signal and a validated wallet opportunity agree.
    """

    def __init__(self, report: dict[str, Any] | None = None, config: WalletSignalConfig | None = None) -> None:
        self.report = report or {}
        self.config = config or WalletSignalConfig()

    def apply(
        self,
        decision: StrategyDecision,
        *,
        market: Market,
        up_book: OrderBook,
        down_book: OrderBook,
        now: datetime | None = None,
    ) -> StrategyDecision:
        if not self.config.enabled or not self.report:
            return decision
        if self.config.mode == "gate" and decision.action == "NO_TRADE":
            return self._gate_no_trade(decision, "wallet_gate_baseline_no_trade")
        current = self._current_context(decision, market=market, up_book=up_book, down_book=down_book, now=now)
        if current is None:
            return self._gate_no_trade(decision, "wallet_gate_no_trade_context") if self.config.mode == "gate" else decision

        avoid_match = self._best_match(self.report.get("validated_avoid_patterns") or self.report.get("avoid_patterns", []), current, avoid=True)
        if avoid_match is not None:
            return StrategyDecision(
                action="NO_TRADE",
                probability_up=decision.probability_up,
                edge=decision.edge,
                target_price=None,
                reason=f"wallet_avoid:{avoid_match['pattern']}",
                observed_ts=decision.observed_ts,
            )

        opportunity_match = self._best_match(
            self.report.get("validated_opportunities") or self.report.get("opportunities", []), current, avoid=False
        )
        if opportunity_match is None:
            return self._gate_no_trade(decision, "wallet_gate_no_validated_opportunity") if self.config.mode == "gate" else decision
        boosted_edge = round(decision.edge + self.config.min_confidence_boost, 4)
        return StrategyDecision(
            action=decision.action,
            probability_up=decision.probability_up,
            edge=boosted_edge,
            target_price=decision.target_price,
            reason=f"{decision.reason}|wallet_opportunity:{opportunity_match['pattern']}",
            observed_ts=decision.observed_ts,
        )

    def _gate_no_trade(self, decision: StrategyDecision, reason: str) -> StrategyDecision:
        return StrategyDecision(
            action="NO_TRADE",
            probability_up=decision.probability_up,
            edge=decision.edge,
            target_price=None,
            reason=reason,
            observed_ts=decision.observed_ts,
        )

    def _current_context(
        self,
        decision: StrategyDecision,
        *,
        market: Market,
        up_book: OrderBook,
        down_book: OrderBook,
        now: datetime | None,
    ) -> dict[str, str] | None:
        asset = _asset_from_slug(market.slug)
        interval = _interval_from_slug(market.slug)
        if asset == "unknown" or interval == "unknown":
            return None
        if decision.action == "BUY_UP":
            outcome = "up"
            price = up_book.best_ask.price if up_book.best_ask is not None else decision.target_price
        elif decision.action == "BUY_DOWN":
            outcome = "down"
            price = down_book.best_ask.price if down_book.best_ask is not None else decision.target_price
        else:
            outcome = "unknown"
            price = decision.target_price
        if price is None:
            return None
        timestamp = now or utc_now()
        local_time = timestamp.astimezone(_safe_zoneinfo(self.config.local_tz))
        return {
            "asset": asset,
            "interval": interval,
            "outcome": outcome,
            "avg_price": _price_bucket(float(price)),
            "hour_utc": f"{timestamp.hour:02d}",
            "slot_utc": f"{timestamp.hour:02d}:{timestamp.minute:02d}",
            "hour_local": f"{local_time.hour:02d}",
            "slot_local": f"{local_time.hour:02d}:{local_time.minute:02d}",
            "entry_phase": _entry_phase((timestamp - market.start_ts).total_seconds()),
        }

    def _best_match(self, patterns: list[dict[str, Any]], current: dict[str, str], *, avoid: bool) -> dict[str, Any] | None:
        matches = []
        for pattern in patterns:
            if not _pattern_matches(str(pattern.get("pattern") or ""), current):
                continue
            if avoid:
                if float(pattern.get("loss_rate") or 0.0) < self.config.max_avoid_loss_rate:
                    continue
            else:
                if self.config.require_validated and not pattern.get("is_validated"):
                    continue
                if float(pattern.get("win_rate") or 0.0) < self.config.min_win_rate:
                    continue
                if int(pattern.get("count") or 0) < self.config.min_support:
                    continue
                if int(pattern.get("recurrence_days") or 0) < self.config.min_recurrence_days:
                    continue
                validation = pattern.get("validation") or {}
                validation_win_rate = float(validation.get("win_rate") or 0.0)
                if validation and validation_win_rate < self.config.min_validation_win_rate:
                    continue
                validation_wilson = pattern.get("validation_wilson_lower")
                if validation_wilson is not None and float(validation_wilson) < self.config.min_validation_wilson_lower:
                    continue
                train = pattern.get("train") or {}
                if train and validation:
                    train_win_rate = float(train.get("win_rate") or 0.0)
                    if abs(train_win_rate - validation_win_rate) > self.config.max_train_validation_win_rate_delta:
                        continue
                prices = pattern.get("pattern", "")
                if "avg_price=" in prices and _price_bucket_ceiling(current["avg_price"]) > self.config.max_entry_price:
                    continue
            score_key = "avoid_score" if avoid else "opportunity_score"
            matches.append((float(pattern.get(score_key) or 0.0), pattern))
        if not matches:
            return None
        return max(matches, key=lambda item: item[0])[1]


def _pattern_matches(pattern: str, current: dict[str, str]) -> bool:
    if not pattern:
        return False
    for part in pattern.split("|"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key in current and current[key] != value:
            return False
    return True


def _asset_from_slug(slug: str) -> str:
    if not slug:
        return "unknown"
    return slug.split("-", 1)[0].lower()


def _interval_from_slug(slug: str) -> str:
    for part in slug.split("-"):
        if part.endswith("m") and part[:-1].isdigit():
            return part
    return "unknown"


def _entry_phase(seconds_after_open: float) -> str:
    if seconds_after_open < 0:
        return "pre_open"
    if seconds_after_open < 60:
        return "first_minute"
    if seconds_after_open < 180:
        return "middle"
    if seconds_after_open <= 330:
        return "late"
    return "post_close_or_late_report"


def _price_bucket(price: float) -> str:
    if price < 0.05:
        return "0.00-0.05"
    if price < 0.15:
        return "0.05-0.15"
    if price < 0.35:
        return "0.15-0.35"
    if price < 0.65:
        return "0.35-0.65"
    if price < 0.85:
        return "0.65-0.85"
    return "0.85-1.00"


def _price_bucket_ceiling(bucket: str) -> float:
    try:
        return float(bucket.rsplit("-", 1)[1])
    except (ValueError, IndexError):
        return 1.0


def _safe_zoneinfo(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")
