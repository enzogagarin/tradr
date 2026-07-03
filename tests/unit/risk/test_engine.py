from datetime import UTC, datetime, timedelta

from polymarket_btc_bot.domain import Market, MarketAsset, StrategyDecision
from polymarket_btc_bot.risk import RiskEngine, RiskLimits, RiskState


def _market(status="OPEN"):
    now = datetime.now(tz=UTC)
    return Market(
        market_id="m1",
        slug="btc-up-down",
        question="BTC up?",
        start_ts=now - timedelta(minutes=1),
        end_ts=now + timedelta(minutes=4),
        up=MarketAsset("up", "UP"),
        down=MarketAsset("down", "DOWN"),
        status=status,
    )


def _decision(action="BUY_UP"):
    return StrategyDecision(action, 0.6, 0.06, 0.55, "baseline_edge_up", datetime.now(tz=UTC))


def _limits(**overrides):
    values = {
        "max_order_notional": 25,
        "max_market_exposure": 100,
        "max_daily_loss": 50,
        "max_trades_per_market": 3,
        "kill_switch": False,
    }
    values.update(overrides)
    return RiskLimits(**values)


def test_risk_engine_approves_valid_order_intent():
    result = RiskEngine().validate_order_intent(
        decision=_decision(),
        market=_market(),
        limits=_limits(),
        state=RiskState(open_exposure=20, daily_pnl=0, trades_in_market=1),
        requested_notional=25,
    )

    assert result.approved is True
    assert result.reason_code == "approved"
    assert result.allowed_notional == 25


def test_risk_engine_keeps_no_trade_as_no_order_intent():
    result = RiskEngine().validate_order_intent(
        decision=_decision("NO_TRADE"),
        market=_market(),
        limits=_limits(kill_switch=True),
    )

    assert result.approved is True
    assert result.reason_code == "no_order_intent"
    assert result.allowed_notional == 0


def test_risk_engine_rejects_kill_switch():
    result = RiskEngine().validate_order_intent(
        decision=_decision(),
        market=_market(),
        limits=_limits(kill_switch=True),
    )

    assert result.approved is False
    assert result.reason_code == "kill_switch_enabled"


def test_risk_engine_rejects_market_exposure_limit():
    result = RiskEngine().validate_order_intent(
        decision=_decision(),
        market=_market(),
        limits=_limits(max_market_exposure=30),
        state=RiskState(open_exposure=20),
        requested_notional=25,
    )

    assert result.approved is False
    assert result.reason_code == "max_market_exposure_exceeded"
    assert result.allowed_notional == 10


def test_risk_engine_rejects_trade_count_limit():
    result = RiskEngine().validate_order_intent(
        decision=_decision(),
        market=_market(),
        limits=_limits(max_trades_per_market=2),
        state=RiskState(trades_in_market=2),
    )

    assert result.approved is False
    assert result.reason_code == "max_trades_per_market_exceeded"
