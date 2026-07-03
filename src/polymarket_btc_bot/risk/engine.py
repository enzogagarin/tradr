from __future__ import annotations

from dataclasses import dataclass

from polymarket_btc_bot.domain import Market, StrategyDecision


@dataclass(frozen=True)
class RiskLimits:
    max_order_notional: float
    max_market_exposure: float
    max_daily_loss: float
    max_trades_per_market: int
    kill_switch: bool = False

    def __post_init__(self) -> None:
        if self.max_order_notional <= 0:
            raise ValueError("max_order_notional must be positive")
        if self.max_market_exposure <= 0:
            raise ValueError("max_market_exposure must be positive")
        if self.max_daily_loss <= 0:
            raise ValueError("max_daily_loss must be positive")
        if self.max_trades_per_market <= 0:
            raise ValueError("max_trades_per_market must be positive")


@dataclass(frozen=True)
class RiskState:
    open_exposure: float = 0.0
    daily_pnl: float = 0.0
    trades_in_market: int = 0

    def __post_init__(self) -> None:
        if self.open_exposure < 0:
            raise ValueError("open_exposure cannot be negative")
        if self.trades_in_market < 0:
            raise ValueError("trades_in_market cannot be negative")


@dataclass(frozen=True)
class RiskValidation:
    approved: bool
    reason_code: str
    requested_notional: float
    allowed_notional: float
    checks: dict[str, bool]

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "reason_code": self.reason_code,
            "requested_notional": self.requested_notional,
            "allowed_notional": self.allowed_notional,
            "checks": self.checks,
        }


class RiskEngine:
    def validate_order_intent(
        self,
        *,
        decision: StrategyDecision,
        market: Market,
        limits: RiskLimits,
        state: RiskState | None = None,
        requested_notional: float | None = None,
    ) -> RiskValidation:
        risk_state = state or RiskState()
        notional = round(requested_notional if requested_notional is not None else limits.max_order_notional, 4)

        checks = {
            "has_order_intent": decision.action != "NO_TRADE",
            "kill_switch_off": not limits.kill_switch,
            "order_notional_positive": notional > 0,
            "order_notional_within_limit": notional <= limits.max_order_notional,
            "market_exposure_within_limit": risk_state.open_exposure + notional <= limits.max_market_exposure,
            "daily_loss_within_limit": risk_state.daily_pnl > -limits.max_daily_loss,
            "trade_count_within_limit": risk_state.trades_in_market < limits.max_trades_per_market,
            "market_open": market.status == "OPEN",
        }

        if decision.action == "NO_TRADE":
            return RiskValidation(True, "no_order_intent", 0.0, 0.0, checks)
        if limits.kill_switch:
            return RiskValidation(False, "kill_switch_enabled", notional, 0.0, checks)
        if notional <= 0:
            return RiskValidation(False, "invalid_order_notional", notional, 0.0, checks)
        if notional > limits.max_order_notional:
            return RiskValidation(False, "max_order_notional_exceeded", notional, limits.max_order_notional, checks)
        if risk_state.open_exposure + notional > limits.max_market_exposure:
            available = max(0.0, round(limits.max_market_exposure - risk_state.open_exposure, 4))
            return RiskValidation(False, "max_market_exposure_exceeded", notional, available, checks)
        if risk_state.daily_pnl <= -limits.max_daily_loss:
            return RiskValidation(False, "max_daily_loss_exceeded", notional, 0.0, checks)
        if risk_state.trades_in_market >= limits.max_trades_per_market:
            return RiskValidation(False, "max_trades_per_market_exceeded", notional, 0.0, checks)
        if market.status != "OPEN":
            return RiskValidation(False, "market_not_open", notional, 0.0, checks)

        return RiskValidation(True, "approved", notional, notional, checks)
