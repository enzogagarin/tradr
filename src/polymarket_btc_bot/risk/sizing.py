from __future__ import annotations

from dataclasses import dataclass

from polymarket_btc_bot.domain import StrategyDecision


@dataclass(frozen=True)
class PositionSizingConfig:
    enabled: bool = True
    max_order_notional: float = 25.0
    bankroll_fraction: float = 0.02
    min_notional: float = 5.0
    edge_scale: float = 0.10
    volatility_target: float = 0.0018


def calculate_position_notional(
    decision: StrategyDecision,
    *,
    equity: float,
    volatility_5m: float | None,
    config: PositionSizingConfig,
) -> float:
    if decision.action == "NO_TRADE":
        return 0.0
    if not config.enabled:
        return round(config.max_order_notional, 4)
    if equity <= 0:
        return 0.0

    equity_cap = equity * config.bankroll_fraction
    cap = max(0.0, min(config.max_order_notional, equity_cap))
    if cap <= 0:
        return 0.0

    edge_factor = min(1.0, max(0.0, decision.edge / max(1e-9, config.edge_scale)))
    if volatility_5m is None or volatility_5m <= 0:
        vol_factor = 1.0
    else:
        # High realized volatility reduces size; unusually quiet markets can
        # size up slightly, but never beyond the configured cap.
        vol_factor = min(1.2, max(0.25, config.volatility_target / volatility_5m))

    notional = cap * edge_factor * vol_factor
    if notional <= 0:
        return 0.0
    if config.min_notional > 0:
        notional = max(min(config.min_notional, cap), notional)
    return round(min(cap, notional), 4)
