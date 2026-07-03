from __future__ import annotations

from datetime import UTC, datetime

from polymarket_btc_bot.domain import StrategyDecision
from polymarket_btc_bot.risk import PositionSizingConfig, calculate_position_notional


def _decision(edge: float = 0.05, action: str = "BUY_UP") -> StrategyDecision:
    return StrategyDecision(action, 0.62, edge, 0.50, "baseline_edge_up", datetime.now(tz=UTC))


def test_position_sizing_skips_no_trade():
    notional = calculate_position_notional(
        _decision(action="NO_TRADE"),
        equity=1000,
        volatility_5m=None,
        config=PositionSizingConfig(),
    )

    assert notional == 0.0


def test_position_sizing_scales_with_edge_and_bankroll_cap():
    cfg = PositionSizingConfig(max_order_notional=25, bankroll_fraction=0.02, edge_scale=0.10)

    small = calculate_position_notional(_decision(edge=0.03), equity=1000, volatility_5m=None, config=cfg)
    large = calculate_position_notional(_decision(edge=0.10), equity=1000, volatility_5m=None, config=cfg)

    assert small == 6.0
    assert large == 20.0


def test_position_sizing_respects_max_order_notional():
    cfg = PositionSizingConfig(max_order_notional=25, bankroll_fraction=0.10, edge_scale=0.05)

    notional = calculate_position_notional(_decision(edge=0.20), equity=1000, volatility_5m=None, config=cfg)

    assert notional == 25.0


def test_position_sizing_reduces_size_when_realized_vol_is_high():
    cfg = PositionSizingConfig(
        max_order_notional=25,
        bankroll_fraction=0.02,
        edge_scale=0.10,
        volatility_target=0.002,
    )

    quiet = calculate_position_notional(_decision(edge=0.10), equity=1000, volatility_5m=0.002, config=cfg)
    volatile = calculate_position_notional(_decision(edge=0.10), equity=1000, volatility_5m=0.008, config=cfg)

    assert quiet == 20.0
    assert volatile == 5.0
