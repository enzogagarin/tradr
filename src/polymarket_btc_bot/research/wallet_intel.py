from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import math
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class WalletSummary:
    user: str | None
    name: str | None
    pseudonym: str | None
    activity_rows: int
    position_rows: int
    trade_count: int
    buy_count: int
    sell_count: int
    redeem_count: int
    merge_count: int
    split_count: int
    total_trade_usdc: float
    total_buy_usdc: float
    total_sell_usdc: float
    total_redeem_usdc: float
    activity_net_cashflow_usdc: float
    activity_first_ts: str | None
    activity_last_ts: str | None
    position_initial_value: float
    position_current_value: float
    position_cash_pnl: float
    position_realized_pnl: float
    profitable_positions: int
    losing_positions: int
    realized_profitable_positions: int
    realized_losing_positions: int
    last_30d_position_count: int
    last_30d_realized_pnl: float
    last_30d_realized_win_rate: float | None
    top_markets_by_trade_usdc: list[dict[str, Any]]
    by_asset: list[dict[str, Any]]
    by_interval: list[dict[str, Any]]
    by_price_bucket: list[dict[str, Any]]
    by_hour_utc: list[dict[str, Any]]
    position_pnl_by_asset: list[dict[str, Any]]
    caveats: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "user": self.user,
            "name": self.name,
            "pseudonym": self.pseudonym,
            "activity_rows": self.activity_rows,
            "position_rows": self.position_rows,
            "trade_count": self.trade_count,
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "redeem_count": self.redeem_count,
            "merge_count": self.merge_count,
            "split_count": self.split_count,
            "total_trade_usdc": self.total_trade_usdc,
            "total_buy_usdc": self.total_buy_usdc,
            "total_sell_usdc": self.total_sell_usdc,
            "total_redeem_usdc": self.total_redeem_usdc,
            "activity_net_cashflow_usdc": self.activity_net_cashflow_usdc,
            "activity_first_ts": self.activity_first_ts,
            "activity_last_ts": self.activity_last_ts,
            "position_initial_value": self.position_initial_value,
            "position_current_value": self.position_current_value,
            "position_cash_pnl": self.position_cash_pnl,
            "position_realized_pnl": self.position_realized_pnl,
            "profitable_positions": self.profitable_positions,
            "losing_positions": self.losing_positions,
            "realized_profitable_positions": self.realized_profitable_positions,
            "realized_losing_positions": self.realized_losing_positions,
            "last_30d_position_count": self.last_30d_position_count,
            "last_30d_realized_pnl": self.last_30d_realized_pnl,
            "last_30d_realized_win_rate": self.last_30d_realized_win_rate,
            "top_markets_by_trade_usdc": self.top_markets_by_trade_usdc,
            "by_asset": self.by_asset,
            "by_interval": self.by_interval,
            "by_price_bucket": self.by_price_bucket,
            "by_hour_utc": self.by_hour_utc,
            "position_pnl_by_asset": self.position_pnl_by_asset,
            "caveats": self.caveats,
        }


def scan_wallet_outcomes(
    positions: list[dict[str, Any]], *, min_support: int = 10, as_of: date | None = None
) -> dict[str, Any]:
    as_of = as_of or datetime.now(UTC).date()
    decided = [position for position in positions if _float(position.get("realizedPnl")) != 0]
    winners = [position for position in decided if _float(position.get("realizedPnl")) > 0]
    losers = [position for position in decided if _float(position.get("realizedPnl")) < 0]

    groups: dict[str, dict[str, Any]] = {}
    for position in decided:
        for key in _position_pattern_keys(position):
            bucket = groups.setdefault(key, _outcome_bucket(key))
            realized_pnl = _float(position.get("realizedPnl"))
            initial_value = _float(position.get("initialValue"))
            total_bought = _float(position.get("totalBought"))
            bucket["count"] += 1
            bucket["realized_pnl"] += realized_pnl
            bucket["initial_value"] += initial_value
            bucket["total_bought"] += total_bought
            if realized_pnl > 0:
                bucket["wins"] += 1
                bucket["win_realized_pnl"] += realized_pnl
            else:
                bucket["losses"] += 1
                bucket["loss_realized_pnl"] += realized_pnl

    ranked = [_finalize_outcome_bucket(bucket) for bucket in groups.values() if bucket["count"] >= min_support]
    success_patterns = sorted(ranked, key=lambda item: (item["win_rate"], item["realized_pnl"]), reverse=True)[:30]
    failure_patterns = sorted(ranked, key=lambda item: (item["loss_rate"], -item["realized_pnl"]), reverse=True)[:30]
    pnl_patterns = sorted(ranked, key=lambda item: item["realized_pnl"], reverse=True)[:30]

    last_30d_cutoff = as_of - timedelta(days=30)
    last_30d = [position for position in decided if (end_date := _date_from_iso(position.get("endDate"))) and end_date >= last_30d_cutoff]

    return {
        "position_rows": len(positions),
        "decided_positions": len(decided),
        "winner_positions": len(winners),
        "loser_positions": len(losers),
        "win_rate": round(len(winners) / len(decided), 4) if decided else None,
        "realized_pnl": round(sum(_float(position.get("realizedPnl")) for position in decided), 4),
        "last_30d_decided_positions": len(last_30d),
        "last_30d_realized_pnl": round(sum(_float(position.get("realizedPnl")) for position in last_30d), 4),
        "last_30d_win_rate": (
            round(sum(1 for position in last_30d if _float(position.get("realizedPnl")) > 0) / len(last_30d), 4)
            if last_30d
            else None
        ),
        "success_patterns": success_patterns,
        "failure_patterns": failure_patterns,
        "pnl_patterns": pnl_patterns,
        "top_winning_positions": _rank_positions(winners, reverse=True),
        "top_losing_positions": _rank_positions(losers, reverse=False),
        "caveats": [
            "realized_pnl_is_from_polymarket_positions_snapshot",
            "onchain_usdc_redeem_merge_split_reconciliation_is_required_before_trading",
            "patterns_are_descriptive_not_out_of_sample_signals",
        ],
    }


def scan_wallet_daily_opportunities(
    wallet_datasets: list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]],
    *,
    min_support: int = 10,
    min_days: int = 3,
    min_win_rate: float = 0.75,
    lookback_days: int = 30,
    as_of: date | None = None,
    local_tz: str = "Europe/Istanbul",
    validation_ratio: float = 0.30,
    min_validation_support: int = 5,
    min_validation_days: int = 2,
    min_validation_win_rate: float | None = None,
    min_validation_wilson_lower: float = 0.70,
    max_train_validation_win_rate_delta: float = 0.25,
) -> dict[str, Any]:
    """Find wallet-learned opportunity scenarios that can recur inside a 24h cycle.

    The scanner deliberately separates discovery from validation. It discovers
    candidate patterns on the older part of the lookback window, then requires
    them to survive a chronological holdout before they are allowed into the
    validated opportunity set consumed by the strategy overlay.
    """
    as_of = as_of or _latest_date_from_wallet_datasets(wallet_datasets) or datetime.now(UTC).date()
    cutoff = as_of - timedelta(days=lookback_days)
    observations = _build_wallet_observations(wallet_datasets, cutoff=cutoff, local_tz=local_tz)
    min_validation_win_rate = min_win_rate if min_validation_win_rate is None else min_validation_win_rate
    if not observations:
        return {
            "wallets": [label for label, _, _ in wallet_datasets],
            "as_of": as_of.isoformat(),
            "lookback_days": lookback_days,
            "local_tz": local_tz,
            "observation_count": 0,
            "baseline": {},
            "validation": {
                "enabled": False,
                "blocking_reason": "no_resolved_position_observations",
                "ratio": validation_ratio,
                "min_validation_support": min_validation_support,
                "min_validation_days": min_validation_days,
                "min_validation_win_rate": min_validation_win_rate,
                "min_validation_wilson_lower": min_validation_wilson_lower,
            },
            "opportunities": [],
            "validated_opportunities": [],
            "daily_time_opportunities": [],
            "daily_time_validated_opportunities": [],
            "watchlist_opportunities": [],
            "daily_time_watchlist_opportunities": [],
            "avoid_patterns": [],
            "validated_avoid_patterns": [],
            "daily_time_avoid_patterns": [],
            "wallet_summaries": [],
            "blocking_reasons": ["no_resolved_position_observations"],
            "caveats": _daily_opportunity_caveats(),
        }

    observations = sorted(observations, key=lambda row: (row["market_ts"], row["slug"], row["wallet"]))
    train_observations, validation_observations, split = _temporal_validation_split(
        observations,
        validation_ratio=validation_ratio,
    )
    baseline = _daily_baseline(observations)
    train_baseline = _daily_baseline(train_observations)
    validation_baseline = _daily_baseline(validation_observations)
    all_ranked = _rank_daily_patterns(observations, min_support=min_support, min_days=min_days, baseline=baseline)
    train_ranked = _rank_daily_patterns(train_observations, min_support=min_support, min_days=min_days, baseline=train_baseline)
    validation_ranked = _rank_daily_patterns(
        validation_observations,
        min_support=1,
        min_days=1,
        baseline=validation_baseline,
    )
    all_by_pattern = {row["pattern"]: row for row in all_ranked}
    validation_by_pattern = {row["pattern"]: row for row in validation_ranked}

    exploratory_opportunities = [
        row
        for row in all_ranked
        if row["win_rate"] is not None
        and row["win_rate"] >= min_win_rate
        and row["avg_realized_pnl"] is not None
        and row["avg_realized_pnl"] > 0
    ]
    exploratory_opportunities.sort(key=lambda item: item["opportunity_score"], reverse=True)
    exploratory_avoid_patterns = [
        row
        for row in all_ranked
        if row["loss_rate"] is not None
        and row["loss_rate"] >= max(0.5, 1.0 - min_win_rate)
        and row["avg_realized_pnl"] is not None
        and row["avg_realized_pnl"] < 0
    ]
    exploratory_avoid_patterns.sort(key=lambda item: item["avoid_score"], reverse=True)

    train_opportunities = [
        row
        for row in train_ranked
        if row["win_rate"] is not None
        and row["win_rate"] >= min_win_rate
        and row["avg_realized_pnl"] is not None
        and row["avg_realized_pnl"] > 0
    ]
    train_opportunities.sort(key=lambda item: item["opportunity_score"], reverse=True)
    validated_opportunities, watchlist_opportunities = _validate_opportunity_candidates(
        train_opportunities,
        validation_by_pattern=validation_by_pattern,
        all_by_pattern=all_by_pattern,
        min_validation_support=min_validation_support,
        min_validation_days=min_validation_days,
        min_validation_win_rate=min_validation_win_rate,
        min_validation_wilson_lower=min_validation_wilson_lower,
        max_train_validation_win_rate_delta=max_train_validation_win_rate_delta,
    )

    train_avoid_candidates = [
        row
        for row in train_ranked
        if row["loss_rate"] is not None
        and row["loss_rate"] >= max(0.5, 1.0 - min_win_rate)
        and row["avg_realized_pnl"] is not None
        and row["avg_realized_pnl"] < 0
    ]
    train_avoid_candidates.sort(key=lambda item: item["avoid_score"], reverse=True)
    validated_avoid_patterns = _validate_avoid_candidates(
        train_avoid_candidates,
        validation_by_pattern=validation_by_pattern,
        all_by_pattern=all_by_pattern,
        min_validation_support=min_validation_support,
        min_validation_days=min_validation_days,
        max_train_validation_win_rate_delta=max_train_validation_win_rate_delta,
    )

    validation_blocking_reasons = []
    if not split["enabled"]:
        validation_blocking_reasons.append(split["blocking_reason"])
    if not validated_opportunities:
        validation_blocking_reasons.append("no_patterns_survived_chronological_validation")

    return {
        "wallets": [label for label, _, _ in wallet_datasets],
        "as_of": as_of.isoformat(),
        "lookback_days": lookback_days,
        "local_tz": local_tz,
        "observation_count": len(observations),
        "min_support": min_support,
        "min_days": min_days,
        "min_win_rate": min_win_rate,
        "baseline": {
            "win_rate": round(baseline["win_rate"], 4),
            "avg_realized_pnl": round(baseline["avg_realized_pnl"], 4),
            "realized_pnl": round(baseline["realized_pnl"], 4),
            "wallets_with_realized_positions": sorted({row["wallet"] for row in observations}),
            "first_market_ts": _iso_ts(min(row["market_ts"] for row in observations)),
            "last_market_ts": _iso_ts(max(row["market_ts"] for row in observations)),
        },
        "validation": {
            **split,
            "train_observations": len(train_observations),
            "validation_observations": len(validation_observations),
            "train_baseline": {
                "win_rate": round(train_baseline["win_rate"], 4),
                "avg_realized_pnl": round(train_baseline["avg_realized_pnl"], 4),
                "realized_pnl": round(train_baseline["realized_pnl"], 4),
            },
            "validation_baseline": {
                "win_rate": round(validation_baseline["win_rate"], 4),
                "avg_realized_pnl": round(validation_baseline["avg_realized_pnl"], 4),
                "realized_pnl": round(validation_baseline["realized_pnl"], 4),
            },
            "min_validation_support": min_validation_support,
            "min_validation_days": min_validation_days,
            "min_validation_win_rate": min_validation_win_rate,
            "min_validation_wilson_lower": min_validation_wilson_lower,
            "max_train_validation_win_rate_delta": max_train_validation_win_rate_delta,
            "overfit_controls": [
                "chronological_train_validation_split_by_market_date",
                "discover_on_train_only_validate_on_recent_holdout",
                "minimum_validation_support_and_recurrence_days",
                "wilson_lower_bound_for_small_sample_penalty",
                "train_validation_win_rate_stability_check",
                "validated_patterns_only_for_strategy_overlay",
            ],
        },
        "opportunities": validated_opportunities[:30],
        "validated_opportunities": validated_opportunities[:30],
        "daily_time_opportunities": [row for row in validated_opportunities if _is_daily_time_pattern(row["pattern"])][:30],
        "daily_time_validated_opportunities": [row for row in validated_opportunities if _is_daily_time_pattern(row["pattern"])][:30],
        "watchlist_opportunities": watchlist_opportunities[:30],
        "daily_time_watchlist_opportunities": [row for row in watchlist_opportunities if _is_daily_time_pattern(row["pattern"])][:30],
        "exploratory_opportunities": exploratory_opportunities[:30],
        "avoid_patterns": validated_avoid_patterns[:30],
        "validated_avoid_patterns": validated_avoid_patterns[:30],
        "daily_time_avoid_patterns": [row for row in validated_avoid_patterns if _is_daily_time_pattern(row["pattern"])][:30],
        "exploratory_avoid_patterns": exploratory_avoid_patterns[:30],
        "wallet_summaries": _wallet_daily_summaries(observations),
        "blocking_reasons": validation_blocking_reasons,
        "caveats": _daily_opportunity_caveats(),
    }

def summarize_wallet(
    activity: list[dict[str, Any]], positions: list[dict[str, Any]], *, as_of: date | None = None
) -> WalletSummary:
    trades = [row for row in activity if row.get("type") == "TRADE"]
    user = _first_string(activity, "proxyWallet") or _first_string(positions, "proxyWallet")
    name = _first_string(activity, "name")
    pseudonym = _first_string(activity, "pseudonym")

    by_market: dict[str, dict[str, Any]] = {}
    asset_stats: dict[str, dict[str, float]] = defaultdict(_stat_bucket)
    interval_stats: dict[str, dict[str, float]] = defaultdict(_stat_bucket)
    price_bucket_stats: dict[str, dict[str, float]] = defaultdict(_stat_bucket)
    hour_stats: dict[str, dict[str, float]] = defaultdict(_stat_bucket)

    buy_count = 0
    sell_count = 0
    total_buy_usdc = 0.0
    total_sell_usdc = 0.0
    for trade in trades:
        usdc = _float(trade.get("usdcSize"))
        side = str(trade.get("side") or "")
        if side == "BUY":
            buy_count += 1
            total_buy_usdc += usdc
        elif side == "SELL":
            sell_count += 1
            total_sell_usdc += usdc

        slug = str(trade.get("slug") or "")
        market = by_market.setdefault(
            slug,
            {
                "slug": slug,
                "title": trade.get("title"),
                "trade_count": 0,
                "trade_usdc": 0.0,
                "buy_usdc": 0.0,
                "sell_usdc": 0.0,
            },
        )
        market["trade_count"] += 1
        market["trade_usdc"] += usdc
        if side == "BUY":
            market["buy_usdc"] += usdc
        elif side == "SELL":
            market["sell_usdc"] += usdc

        _add_stat(asset_stats[_asset_from_slug(slug)], usdc)
        _add_stat(interval_stats[_interval_from_slug(slug)], usdc)
        _add_stat(price_bucket_stats[_price_bucket(_float(trade.get("price")))], usdc)
        _add_stat(hour_stats[_hour_from_timestamp(trade.get("timestamp"))], usdc)

    pnl_by_asset: dict[str, dict[str, float]] = defaultdict(_pnl_bucket)
    profitable_positions = 0
    losing_positions = 0
    realized_profitable_positions = 0
    realized_losing_positions = 0
    as_of = as_of or datetime.now(UTC).date()
    last_30d_cutoff = as_of - timedelta(days=30)
    last_30d_positions = 0
    last_30d_realized_pnl = 0.0
    last_30d_realized_wins = 0
    last_30d_realized_losses = 0
    for position in positions:
        asset = _asset_from_slug(str(position.get("slug") or ""))
        initial = _float(position.get("initialValue"))
        current = _float(position.get("currentValue"))
        pnl = _float(position.get("cashPnl"))
        realized_pnl = _float(position.get("realizedPnl"))
        pnl_by_asset[asset]["count"] += 1
        pnl_by_asset[asset]["initial_value"] += initial
        pnl_by_asset[asset]["current_value"] += current
        pnl_by_asset[asset]["cash_pnl"] += pnl
        pnl_by_asset[asset]["realized_pnl"] += realized_pnl
        if pnl > 0:
            profitable_positions += 1
        elif pnl < 0:
            losing_positions += 1
        if realized_pnl > 0:
            realized_profitable_positions += 1
        elif realized_pnl < 0:
            realized_losing_positions += 1
        end_date = _date_from_iso(position.get("endDate"))
        if end_date and end_date >= last_30d_cutoff:
            last_30d_positions += 1
            last_30d_realized_pnl += realized_pnl
            if realized_pnl > 0:
                last_30d_realized_wins += 1
            elif realized_pnl < 0:
                last_30d_realized_losses += 1

    total_redeem_usdc = sum(_float(row.get("usdcSize")) for row in activity if row.get("type") == "REDEEM")
    timestamps = [int(_float(row.get("timestamp"))) for row in activity if _float(row.get("timestamp")) > 0]
    last_30d_realized_decisions = last_30d_realized_wins + last_30d_realized_losses

    return WalletSummary(
        user=user,
        name=name,
        pseudonym=pseudonym,
        activity_rows=len(activity),
        position_rows=len(positions),
        trade_count=len(trades),
        buy_count=buy_count,
        sell_count=sell_count,
        redeem_count=sum(1 for row in activity if row.get("type") == "REDEEM"),
        merge_count=sum(1 for row in activity if row.get("type") == "MERGE"),
        split_count=sum(1 for row in activity if row.get("type") == "SPLIT"),
        total_trade_usdc=round(sum(_float(row.get("usdcSize")) for row in trades), 4),
        total_buy_usdc=round(total_buy_usdc, 4),
        total_sell_usdc=round(total_sell_usdc, 4),
        total_redeem_usdc=round(total_redeem_usdc, 4),
        activity_net_cashflow_usdc=round(total_redeem_usdc + total_sell_usdc - total_buy_usdc, 4),
        activity_first_ts=_iso_ts(min(timestamps)) if timestamps else None,
        activity_last_ts=_iso_ts(max(timestamps)) if timestamps else None,
        position_initial_value=round(sum(_float(row.get("initialValue")) for row in positions), 4),
        position_current_value=round(sum(_float(row.get("currentValue")) for row in positions), 4),
        position_cash_pnl=round(sum(_float(row.get("cashPnl")) for row in positions), 4),
        position_realized_pnl=round(sum(_float(row.get("realizedPnl")) for row in positions), 4),
        profitable_positions=profitable_positions,
        losing_positions=losing_positions,
        realized_profitable_positions=realized_profitable_positions,
        realized_losing_positions=realized_losing_positions,
        last_30d_position_count=last_30d_positions,
        last_30d_realized_pnl=round(last_30d_realized_pnl, 4),
        last_30d_realized_win_rate=(
            round(last_30d_realized_wins / last_30d_realized_decisions, 4) if last_30d_realized_decisions else None
        ),
        top_markets_by_trade_usdc=_top_markets(by_market),
        by_asset=_rank_stats(asset_stats),
        by_interval=_rank_stats(interval_stats),
        by_price_bucket=_rank_stats(price_bucket_stats),
        by_hour_utc=_rank_stats(hour_stats),
        position_pnl_by_asset=_rank_pnl(pnl_by_asset),
        caveats=[
            "positions_endpoint_is_a_snapshot_not_full_realized_pnl",
            "redeem_merge_split_cashflows_must_be_reconciled_before_copytrading",
            "public_activity_offset_is_capped_so_very_active_wallets_may_require_archival_collection",
        ],
    )



def _temporal_validation_split(
    observations: list[dict[str, Any]], *, validation_ratio: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if not observations:
        return [], [], {"enabled": False, "blocking_reason": "no_observations", "ratio": validation_ratio}
    dates = sorted({row["market_date"] for row in observations})
    if len(dates) < 3 or validation_ratio <= 0:
        return observations, [], {
            "enabled": False,
            "blocking_reason": "not_enough_distinct_days_for_holdout",
            "ratio": validation_ratio,
            "distinct_days": len(dates),
        }
    validation_day_count = max(1, int(math.ceil(len(dates) * min(max(validation_ratio, 0.0), 0.9))))
    if validation_day_count >= len(dates):
        validation_day_count = len(dates) - 1
    validation_dates = set(dates[-validation_day_count:])
    train = [row for row in observations if row["market_date"] not in validation_dates]
    validation = [row for row in observations if row["market_date"] in validation_dates]
    return train, validation, {
        "enabled": bool(train and validation),
        "ratio": validation_ratio,
        "distinct_days": len(dates),
        "train_days": len(set(row["market_date"] for row in train)),
        "validation_days": len(set(row["market_date"] for row in validation)),
        "train_start_date": train[0]["market_date"] if train else None,
        "train_end_date": train[-1]["market_date"] if train else None,
        "validation_start_date": validation[0]["market_date"] if validation else None,
        "validation_end_date": validation[-1]["market_date"] if validation else None,
    }


def _daily_baseline(observations: list[dict[str, Any]]) -> dict[str, float]:
    if not observations:
        return {"win_rate": 0.0, "avg_realized_pnl": 0.0, "realized_pnl": 0.0}
    realized_pnl = sum(float(row["realized_pnl"]) for row in observations)
    return {
        "win_rate": sum(1 for row in observations if row["is_win"]) / len(observations),
        "avg_realized_pnl": realized_pnl / len(observations),
        "realized_pnl": realized_pnl,
    }


def _rank_daily_patterns(
    observations: list[dict[str, Any]], *, min_support: int, min_days: int, baseline: dict[str, float]
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for row in observations:
        for pattern in _daily_opportunity_pattern_keys(row):
            bucket = buckets.setdefault(pattern, _daily_opportunity_bucket(pattern))
            _add_daily_observation(bucket, row)
    ranked = [
        _finalize_daily_opportunity_bucket(
            bucket,
            baseline_win_rate=baseline["win_rate"],
            baseline_avg_pnl=baseline["avg_realized_pnl"],
            total_observations=len(observations),
        )
        for bucket in buckets.values()
        if bucket["count"] >= min_support and len(bucket["days"]) >= min_days
    ]
    ranked.sort(key=lambda item: max(item["opportunity_score"], item["avoid_score"]), reverse=True)
    return ranked


def _validate_opportunity_candidates(
    train_candidates: list[dict[str, Any]],
    *,
    validation_by_pattern: dict[str, dict[str, Any]],
    all_by_pattern: dict[str, dict[str, Any]],
    min_validation_support: int,
    min_validation_days: int,
    min_validation_win_rate: float,
    min_validation_wilson_lower: float,
    max_train_validation_win_rate_delta: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    validated: list[dict[str, Any]] = []
    watchlist: list[dict[str, Any]] = []
    seen: set[str] = set()
    for train in train_candidates:
        pattern = str(train["pattern"])
        if pattern in seen:
            continue
        seen.add(pattern)
        validation = validation_by_pattern.get(pattern)
        combined = dict(all_by_pattern.get(pattern, train))
        decision = _opportunity_validation_decision(
            train,
            validation,
            min_validation_support=min_validation_support,
            min_validation_days=min_validation_days,
            min_validation_win_rate=min_validation_win_rate,
            min_validation_wilson_lower=min_validation_wilson_lower,
            max_train_validation_win_rate_delta=max_train_validation_win_rate_delta,
        )
        combined["train"] = _compact_validation_stat(train)
        combined["validation"] = _compact_validation_stat(validation)
        combined["validation_status"] = decision["status"]
        combined["validation_reasons"] = decision["reasons"]
        combined["validation_wilson_lower"] = decision["wilson_lower"]
        combined["selection_policy"] = "train_discovery_recent_holdout_validation"
        combined["is_validated"] = decision["status"] == "validated"
        if combined["is_validated"]:
            combined["opportunity_score"] = round(
                float(combined.get("opportunity_score") or 0.0) + float(decision["wilson_lower"] or 0.0) * 100.0,
                4,
            )
            validated.append(combined)
        else:
            watchlist.append(combined)
    validated.sort(key=lambda item: item["opportunity_score"], reverse=True)
    watchlist.sort(key=lambda item: item["opportunity_score"], reverse=True)
    return validated, watchlist


def _opportunity_validation_decision(
    train: dict[str, Any],
    validation: dict[str, Any] | None,
    *,
    min_validation_support: int,
    min_validation_days: int,
    min_validation_win_rate: float,
    min_validation_wilson_lower: float,
    max_train_validation_win_rate_delta: float,
) -> dict[str, Any]:
    reasons: list[str] = []
    if validation is None:
        return {"status": "watchlist", "reasons": ["missing_in_validation_holdout"], "wilson_lower": None}
    validation_count = int(validation.get("count") or 0)
    validation_days = int(validation.get("recurrence_days") or 0)
    validation_win_rate = float(validation.get("win_rate") or 0.0)
    validation_avg_pnl = float(validation.get("avg_realized_pnl") or 0.0)
    train_win_rate = float(train.get("win_rate") or 0.0)
    wilson_lower = _wilson_lower_bound(int(validation.get("wins") or 0), validation_count)
    if validation_count < min_validation_support:
        reasons.append("validation_support_below_minimum")
    if validation_days < min_validation_days:
        reasons.append("validation_recurrence_days_below_minimum")
    if validation_win_rate < min_validation_win_rate:
        reasons.append("validation_win_rate_below_minimum")
    if wilson_lower < min_validation_wilson_lower:
        reasons.append("validation_wilson_lower_below_minimum")
    if abs(train_win_rate - validation_win_rate) > max_train_validation_win_rate_delta:
        reasons.append("train_validation_win_rate_unstable")
    if validation_avg_pnl <= 0:
        reasons.append("validation_avg_pnl_not_positive")
    return {
        "status": "validated" if not reasons else "watchlist",
        "reasons": reasons or ["passed_chronological_holdout"],
        "wilson_lower": round(wilson_lower, 4),
    }


def _validate_avoid_candidates(
    train_candidates: list[dict[str, Any]],
    *,
    validation_by_pattern: dict[str, dict[str, Any]],
    all_by_pattern: dict[str, dict[str, Any]],
    min_validation_support: int,
    min_validation_days: int,
    max_train_validation_win_rate_delta: float,
) -> list[dict[str, Any]]:
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for train in train_candidates:
        pattern = str(train["pattern"])
        if pattern in seen:
            continue
        seen.add(pattern)
        validation = validation_by_pattern.get(pattern)
        if validation is None:
            continue
        reasons = []
        validation_count = int(validation.get("count") or 0)
        validation_days = int(validation.get("recurrence_days") or 0)
        validation_loss_rate = float(validation.get("loss_rate") or 0.0)
        train_loss_rate = float(train.get("loss_rate") or 0.0)
        validation_avg_pnl = float(validation.get("avg_realized_pnl") or 0.0)
        if validation_count < min_validation_support:
            reasons.append("validation_support_below_minimum")
        if validation_days < min_validation_days:
            reasons.append("validation_recurrence_days_below_minimum")
        if validation_loss_rate < 0.5:
            reasons.append("validation_loss_rate_below_avoid_threshold")
        if abs(train_loss_rate - validation_loss_rate) > max_train_validation_win_rate_delta:
            reasons.append("train_validation_loss_rate_unstable")
        if validation_avg_pnl >= 0:
            reasons.append("validation_avg_pnl_not_negative")
        if reasons:
            continue
        combined = dict(all_by_pattern.get(pattern, train))
        combined["train"] = _compact_validation_stat(train)
        combined["validation"] = _compact_validation_stat(validation)
        combined["validation_status"] = "validated"
        combined["validation_reasons"] = ["passed_chronological_holdout"]
        combined["selection_policy"] = "train_discovery_recent_holdout_validation"
        combined["is_validated"] = True
        validated.append(combined)
    validated.sort(key=lambda item: item["avoid_score"], reverse=True)
    return validated


def _compact_validation_stat(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    keys = [
        "count",
        "recurrence_days",
        "wins",
        "losses",
        "win_rate",
        "loss_rate",
        "realized_pnl",
        "avg_realized_pnl",
        "opportunity_score",
        "avoid_score",
    ]
    return {key: row.get(key) for key in keys}


def _wilson_lower_bound(wins: int, total: int, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    phat = wins / total
    denominator = 1 + z * z / total
    centre = phat + z * z / (2 * total)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    return max(0.0, (centre - margin) / denominator)

def _build_wallet_observations(
    wallet_datasets: list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]], *, cutoff: date, local_tz: str
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    local_zone = _safe_zoneinfo(local_tz)
    for label, activity, positions in wallet_datasets:
        activity_by_slug = _activity_features_by_slug(activity)
        for position in positions:
            realized_pnl = _float(position.get("realizedPnl"))
            if realized_pnl == 0:
                continue
            slug = str(position.get("slug") or "")
            market_ts = _market_timestamp_from_slug(slug)
            end_date = _date_from_iso(position.get("endDate"))
            market_date = datetime.fromtimestamp(market_ts, tz=UTC).date() if market_ts else end_date
            if market_date is None or market_date < cutoff:
                continue
            market_dt = datetime.fromtimestamp(market_ts, tz=UTC) if market_ts else datetime.combine(market_date, datetime.min.time(), tzinfo=UTC)
            local_dt = market_dt.astimezone(local_zone)
            activity_features = activity_by_slug.get(slug, {})
            avg_price = _float(position.get("avgPrice"))
            observation = {
                "wallet": label,
                "slug": slug,
                "title": position.get("title"),
                "asset": _asset_from_slug(slug),
                "interval": _interval_from_slug(slug),
                "outcome": str(position.get("outcome") or "unknown").lower(),
                "avg_price": avg_price,
                "avg_price_bucket": _price_bucket(avg_price),
                "size_bucket": _notional_bucket(_float(position.get("initialValue"))),
                "realized_pnl": realized_pnl,
                "initial_value": _float(position.get("initialValue")),
                "total_bought": _float(position.get("totalBought")),
                "is_win": realized_pnl > 0,
                "market_ts": market_ts or int(market_dt.timestamp()),
                "market_date": market_date.isoformat(),
                "hour_utc": f"{market_dt.hour:02d}",
                "slot_utc": f"{market_dt.hour:02d}:{market_dt.minute:02d}",
                "hour_local": f"{local_dt.hour:02d}",
                "slot_local": f"{local_dt.hour:02d}:{local_dt.minute:02d}",
                "weekday": str(market_dt.weekday()),
                "trade_count": int(activity_features.get("trade_count", 0)),
                "buy_usdc": round(float(activity_features.get("buy_usdc", 0.0)), 4),
                "redeem_usdc": round(float(activity_features.get("redeem_usdc", 0.0)), 4),
                "merge_usdc": round(float(activity_features.get("merge_usdc", 0.0)), 4),
                "first_trade_seconds_after_open": activity_features.get("first_trade_seconds_after_open"),
                "last_trade_seconds_after_open": activity_features.get("last_trade_seconds_after_open"),
                "entry_phase": _entry_phase(activity_features.get("first_trade_seconds_after_open")),
            }
            observations.append(observation)
    return observations


def _activity_features_by_slug(activity: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    features: dict[str, dict[str, Any]] = {}
    for row in activity:
        slug = str(row.get("slug") or "")
        if not slug:
            continue
        bucket = features.setdefault(
            slug,
            {
                "trade_count": 0,
                "buy_usdc": 0.0,
                "sell_usdc": 0.0,
                "redeem_usdc": 0.0,
                "merge_usdc": 0.0,
                "split_usdc": 0.0,
                "trade_timestamps": [],
            },
        )
        row_type = str(row.get("type") or "")
        usdc = _float(row.get("usdcSize"))
        if row_type == "TRADE":
            bucket["trade_count"] += 1
            if row.get("side") == "BUY":
                bucket["buy_usdc"] += usdc
            elif row.get("side") == "SELL":
                bucket["sell_usdc"] += usdc
            timestamp = int(_float(row.get("timestamp")))
            if timestamp:
                bucket["trade_timestamps"].append(timestamp)
        elif row_type == "REDEEM":
            bucket["redeem_usdc"] += usdc
        elif row_type == "MERGE":
            bucket["merge_usdc"] += usdc
        elif row_type == "SPLIT":
            bucket["split_usdc"] += usdc

    for slug, bucket in features.items():
        market_ts = _market_timestamp_from_slug(slug)
        timestamps = bucket.pop("trade_timestamps")
        if market_ts and timestamps:
            bucket["first_trade_seconds_after_open"] = min(timestamps) - market_ts
            bucket["last_trade_seconds_after_open"] = max(timestamps) - market_ts
        else:
            bucket["first_trade_seconds_after_open"] = None
            bucket["last_trade_seconds_after_open"] = None
    return features


def _daily_opportunity_pattern_keys(row: dict[str, Any]) -> list[str]:
    asset = row["asset"]
    interval = row["interval"]
    outcome = row["outcome"]
    price = row["avg_price_bucket"]
    hour = row["hour_utc"]
    slot = row["slot_utc"]
    local_hour = row["hour_local"]
    local_slot = row["slot_local"]
    entry_phase = row["entry_phase"]
    wallet = row["wallet"]
    return [
        f"asset={asset}|interval={interval}|avg_price={price}",
        f"asset={asset}|interval={interval}|outcome={outcome}|avg_price={price}",
        f"hour_utc={hour}|asset={asset}|interval={interval}|avg_price={price}",
        f"hour_utc={hour}|asset={asset}|interval={interval}|outcome={outcome}|avg_price={price}",
        f"slot_utc={slot}|asset={asset}|interval={interval}|avg_price={price}",
        f"slot_utc={slot}|asset={asset}|interval={interval}|outcome={outcome}|avg_price={price}",
        f"hour_local={local_hour}|asset={asset}|interval={interval}|avg_price={price}",
        f"hour_local={local_hour}|asset={asset}|interval={interval}|outcome={outcome}|avg_price={price}",
        f"slot_local={local_slot}|asset={asset}|interval={interval}|avg_price={price}",
        f"slot_local={local_slot}|asset={asset}|interval={interval}|outcome={outcome}|avg_price={price}",
        f"entry_phase={entry_phase}|asset={asset}|interval={interval}|avg_price={price}",
        f"entry_phase={entry_phase}|asset={asset}|interval={interval}|outcome={outcome}|avg_price={price}",
        f"wallet={wallet}|asset={asset}|interval={interval}|avg_price={price}",
    ]


def _daily_opportunity_bucket(pattern: str) -> dict[str, Any]:
    return {
        "pattern": pattern,
        "count": 0,
        "wins": 0,
        "losses": 0,
        "realized_pnl": 0.0,
        "initial_value": 0.0,
        "total_bought": 0.0,
        "days": set(),
        "wallets": set(),
        "assets": set(),
        "intervals": set(),
        "outcomes": set(),
        "hours_utc": set(),
        "slots_utc": set(),
        "hours_local": set(),
        "slots_local": set(),
        "entry_phases": set(),
        "examples": [],
    }


def _add_daily_observation(bucket: dict[str, Any], row: dict[str, Any]) -> None:
    realized_pnl = float(row["realized_pnl"])
    bucket["count"] += 1
    bucket["realized_pnl"] += realized_pnl
    bucket["initial_value"] += float(row["initial_value"])
    bucket["total_bought"] += float(row["total_bought"])
    if realized_pnl > 0:
        bucket["wins"] += 1
    else:
        bucket["losses"] += 1
    bucket["days"].add(row["market_date"])
    bucket["wallets"].add(row["wallet"])
    bucket["assets"].add(row["asset"])
    bucket["intervals"].add(row["interval"])
    bucket["outcomes"].add(row["outcome"])
    bucket["hours_utc"].add(row["hour_utc"])
    bucket["slots_utc"].add(row["slot_utc"])
    bucket["hours_local"].add(row["hour_local"])
    bucket["slots_local"].add(row["slot_local"])
    bucket["entry_phases"].add(row["entry_phase"])
    bucket["examples"].append(
        {
            "wallet": row["wallet"],
            "slug": row["slug"],
            "title": row["title"],
            "outcome": row["outcome"],
            "avg_price": round(float(row["avg_price"]), 4),
            "realized_pnl": round(realized_pnl, 4),
            "market_date": row["market_date"],
            "slot_utc": row["slot_utc"],
            "slot_local": row["slot_local"],
            "entry_phase": row["entry_phase"],
        }
    )


def _finalize_daily_opportunity_bucket(
    bucket: dict[str, Any], *, baseline_win_rate: float, baseline_avg_pnl: float, total_observations: int
) -> dict[str, Any]:
    count = int(bucket["count"])
    wins = int(bucket["wins"])
    losses = int(bucket["losses"])
    win_rate = wins / count if count else 0.0
    loss_rate = losses / count if count else 0.0
    avg_pnl = bucket["realized_pnl"] / count if count else 0.0
    recurrence_days = len(bucket["days"])
    support_ratio = count / total_observations if total_observations else 0.0
    opportunity_score = max(0.0, win_rate - baseline_win_rate) * math.sqrt(count) * 100.0
    opportunity_score += max(0.0, avg_pnl - baseline_avg_pnl) * math.sqrt(recurrence_days)
    opportunity_score += max(0.0, bucket["realized_pnl"]) * 0.02
    avoid_score = max(0.0, loss_rate - (1.0 - baseline_win_rate)) * math.sqrt(count) * 100.0
    avoid_score += max(0.0, baseline_avg_pnl - avg_pnl) * math.sqrt(recurrence_days)
    avoid_score += max(0.0, -bucket["realized_pnl"]) * 0.02
    examples = sorted(bucket["examples"], key=lambda item: item["realized_pnl"], reverse=True)
    return {
        "pattern": bucket["pattern"],
        "count": count,
        "support_ratio": round(support_ratio, 4),
        "recurrence_days": recurrence_days,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 4),
        "loss_rate": round(loss_rate, 4),
        "realized_pnl": round(bucket["realized_pnl"], 4),
        "avg_realized_pnl": round(avg_pnl, 4),
        "baseline_win_rate": round(baseline_win_rate, 4),
        "win_rate_lift": round(win_rate - baseline_win_rate, 4),
        "baseline_avg_realized_pnl": round(baseline_avg_pnl, 4),
        "avg_pnl_lift": round(avg_pnl - baseline_avg_pnl, 4),
        "initial_value": round(bucket["initial_value"], 4),
        "total_bought": round(bucket["total_bought"], 4),
        "wallets": sorted(bucket["wallets"]),
        "assets": sorted(bucket["assets"]),
        "intervals": sorted(bucket["intervals"]),
        "outcomes": sorted(bucket["outcomes"]),
        "hours_utc": sorted(bucket["hours_utc"]),
        "slots_utc": sorted(bucket["slots_utc"]),
        "hours_local": sorted(bucket["hours_local"]),
        "slots_local": sorted(bucket["slots_local"]),
        "entry_phases": sorted(bucket["entry_phases"]),
        "opportunity_score": round(opportunity_score, 4),
        "avoid_score": round(avoid_score, 4),
        "example_winners": examples[:3],
        "example_losers": sorted(bucket["examples"], key=lambda item: item["realized_pnl"])[:3],
    }


def _wallet_daily_summaries(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        grouped[row["wallet"]].append(row)
    summaries = []
    for wallet, rows in grouped.items():
        summaries.append(
            {
                "wallet": wallet,
                "observations": len(rows),
                "wins": sum(1 for row in rows if row["is_win"]),
                "losses": sum(1 for row in rows if not row["is_win"]),
                "win_rate": round(sum(1 for row in rows if row["is_win"]) / len(rows), 4) if rows else None,
                "realized_pnl": round(sum(row["realized_pnl"] for row in rows), 4),
                "days": len({row["market_date"] for row in rows}),
                "first_market_ts": _iso_ts(min(row["market_ts"] for row in rows)),
                "last_market_ts": _iso_ts(max(row["market_ts"] for row in rows)),
            }
        )
    return sorted(summaries, key=lambda item: item["realized_pnl"], reverse=True)


def _latest_date_from_wallet_datasets(wallet_datasets: list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]]) -> date | None:
    dates: list[date] = []
    for _, activity, positions in wallet_datasets:
        for row in activity:
            timestamp = int(_float(row.get("timestamp")))
            if timestamp:
                dates.append(datetime.fromtimestamp(timestamp, tz=UTC).date())
        for row in positions:
            parsed = _date_from_iso(row.get("endDate"))
            if parsed:
                dates.append(parsed)
    return max(dates, default=None)


def _safe_zoneinfo(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


def _market_timestamp_from_slug(slug: str) -> int | None:
    if not slug:
        return None
    tail = slug.rsplit("-", 1)[-1]
    if tail.isdigit():
        return int(tail)
    return None


def _entry_phase(seconds_after_open: Any) -> str:
    if seconds_after_open is None:
        return "unknown"
    seconds = _float(seconds_after_open)
    if seconds < 0:
        return "pre_open"
    if seconds < 60:
        return "first_minute"
    if seconds < 180:
        return "middle"
    if seconds <= 330:
        return "late"
    return "post_close_or_late_report"


def _notional_bucket(value: float) -> str:
    if value < 25:
        return "0-25"
    if value < 100:
        return "25-100"
    if value < 250:
        return "100-250"
    if value < 1_000:
        return "250-1000"
    return "1000+"


def _is_daily_time_pattern(pattern: str) -> bool:
    return pattern.startswith(("hour_utc=", "slot_utc=", "hour_local=", "slot_local="))


def _daily_opportunity_caveats() -> list[str]:
    return [
        "wallet_position_realized_pnl_must_be_reconciled_with_onchain_usdc_flows_before_live_trading",
        "public_activity_history_is_capped_and_can_miss_older_or_very_active_periods",
        "patterns_are_descriptive_and_may_overfit_until_train_test_split_is_added",
        "daily_opportunity_means_recurring_intraday_template_not_a_guaranteed_once_per_day_trade",
        "price_buckets_use_wallet_average_entry_price_not_full_orderbook_state_at_decision_time",
    ]


def _top_markets(markets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = sorted(markets.values(), key=lambda item: item["trade_usdc"], reverse=True)[:20]
    for row in rows:
        row["trade_usdc"] = round(row["trade_usdc"], 4)
        row["buy_usdc"] = round(row["buy_usdc"], 4)
        row["sell_usdc"] = round(row["sell_usdc"], 4)
    return rows


def _rank_stats(stats: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    rows = []
    for key, value in stats.items():
        rows.append(
            {
                "bucket": key,
                "trade_count": int(value["trade_count"]),
                "trade_usdc": round(value["trade_usdc"], 4),
            }
        )
    return sorted(rows, key=lambda item: item["trade_usdc"], reverse=True)


def _rank_pnl(stats: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    rows = []
    for key, value in stats.items():
        rows.append(
            {
                "asset": key,
                "position_count": int(value["count"]),
                "initial_value": round(value["initial_value"], 4),
                "current_value": round(value["current_value"], 4),
                "cash_pnl": round(value["cash_pnl"], 4),
                "realized_pnl": round(value["realized_pnl"], 4),
            }
        )
    return sorted(rows, key=lambda item: abs(item["cash_pnl"]), reverse=True)


def _outcome_bucket(pattern: str) -> dict[str, Any]:
    return {
        "pattern": pattern,
        "count": 0,
        "wins": 0,
        "losses": 0,
        "realized_pnl": 0.0,
        "win_realized_pnl": 0.0,
        "loss_realized_pnl": 0.0,
        "initial_value": 0.0,
        "total_bought": 0.0,
    }


def _finalize_outcome_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    count = int(bucket["count"])
    wins = int(bucket["wins"])
    losses = int(bucket["losses"])
    return {
        "pattern": bucket["pattern"],
        "count": count,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / count, 4) if count else None,
        "loss_rate": round(losses / count, 4) if count else None,
        "realized_pnl": round(bucket["realized_pnl"], 4),
        "avg_realized_pnl": round(bucket["realized_pnl"] / count, 4) if count else None,
        "win_realized_pnl": round(bucket["win_realized_pnl"], 4),
        "loss_realized_pnl": round(bucket["loss_realized_pnl"], 4),
        "initial_value": round(bucket["initial_value"], 4),
        "total_bought": round(bucket["total_bought"], 4),
    }


def _position_pattern_keys(position: dict[str, Any]) -> list[str]:
    slug = str(position.get("slug") or "")
    asset = _asset_from_slug(slug)
    interval = _interval_from_slug(slug)
    price_bucket = _price_bucket(_float(position.get("avgPrice")))
    outcome = str(position.get("outcome") or "unknown").lower()
    month = str(position.get("endDate") or "")[:7] or "unknown"
    return [
        f"asset={asset}",
        f"interval={interval}",
        f"avg_price={price_bucket}",
        f"outcome={outcome}",
        f"month={month}",
        f"asset={asset}|interval={interval}",
        f"asset={asset}|avg_price={price_bucket}",
        f"interval={interval}|avg_price={price_bucket}",
        f"asset={asset}|outcome={outcome}",
        f"outcome={outcome}|avg_price={price_bucket}",
    ]


def _rank_positions(positions: list[dict[str, Any]], *, reverse: bool) -> list[dict[str, Any]]:
    rows = sorted(positions, key=lambda position: _float(position.get("realizedPnl")), reverse=reverse)[:20]
    return [
        {
            "slug": position.get("slug"),
            "title": position.get("title"),
            "asset": _asset_from_slug(str(position.get("slug") or "")),
            "interval": _interval_from_slug(str(position.get("slug") or "")),
            "outcome": position.get("outcome"),
            "avg_price": round(_float(position.get("avgPrice")), 4),
            "initial_value": round(_float(position.get("initialValue")), 4),
            "realized_pnl": round(_float(position.get("realizedPnl")), 4),
            "end_date": position.get("endDate"),
        }
        for position in rows
    ]


def _stat_bucket() -> dict[str, float]:
    return {"trade_count": 0.0, "trade_usdc": 0.0}


def _pnl_bucket() -> dict[str, float]:
    return {"count": 0.0, "initial_value": 0.0, "current_value": 0.0, "cash_pnl": 0.0, "realized_pnl": 0.0}


def _add_stat(bucket: dict[str, float], usdc: float) -> None:
    bucket["trade_count"] += 1
    bucket["trade_usdc"] += usdc


def _first_string(rows: list[dict[str, Any]], key: str) -> str | None:
    for row in rows:
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _asset_from_slug(slug: str) -> str:
    if not slug:
        return "unknown"
    return slug.split("-")[0].lower()


def _interval_from_slug(slug: str) -> str:
    for part in slug.split("-"):
        if part.endswith("m") and part[:-1].isdigit():
            return part
    return "unknown"


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


def _hour_from_timestamp(value: Any) -> str:
    timestamp = int(_float(value))
    return f"{datetime.fromtimestamp(timestamp, tz=UTC).hour:02d}"


def _iso_ts(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()


def _date_from_iso(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
