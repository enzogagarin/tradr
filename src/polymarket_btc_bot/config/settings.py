from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BotSettings:
    mode: str = "paper"
    market_data_mode: str = "auto"
    gamma_api_base: str = "https://gamma-api.polymarket.com"
    clob_api_base: str = "https://clob.polymarket.com"
    binance_ws_base: str = "wss://stream.binance.com:9443"
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8787
    dashboard_auth_user: str | None = None
    dashboard_auth_password: str | None = None
    max_order_notional: float = 25.0
    max_market_exposure: float = 100.0
    max_daily_loss: float = 100.0
    max_trades_per_market: int = 20
    market_entry_cutoff_seconds: int = 90
    kill_switch: bool = False
    cycle_mode_enabled: bool = False
    cycle_length_seconds: int = 600
    cycle_analysis_seconds: int = 180
    cycle_cooldown_seconds: int = 90
    cycle_max_trades: int = 1
    wallet_signal_path: str | None = None
    wallet_signal_enabled: bool = False
    wallet_signal_mode: str = "overlay"
    wallet_signal_min_win_rate: float = 0.95
    wallet_signal_min_support: int = 20
    wallet_signal_min_days: int = 5
    wallet_signal_max_entry_price: float = 0.35
    wallet_signal_min_confidence_boost: float = 0.02
    wallet_signal_local_tz: str = "Europe/Istanbul"
    wallet_signal_require_validated: bool = True
    wallet_signal_min_validation_win_rate: float = 0.75
    wallet_signal_min_validation_wilson_lower: float = 0.60
    wallet_signal_max_train_validation_win_rate_delta: float = 0.30

    def validate(self) -> None:
        if self.mode not in {"paper", "live"}:
            raise ValueError("mode must be 'paper' or 'live'")
        if self.market_data_mode not in {"demo", "auto", "live"}:
            raise ValueError("market_data_mode must be 'demo', 'auto', or 'live'")
        if self.dashboard_port <= 0 or self.dashboard_port > 65535:
            raise ValueError("dashboard_port must be a valid TCP port")
        if self.dashboard_host not in {"127.0.0.1", "0.0.0.0", "localhost"} and not self.dashboard_auth_password:
            raise ValueError("dashboard_auth_password is required when binding to non-loopback host")
        if self.max_order_notional <= 0:
            raise ValueError("max_order_notional must be positive")
        if self.max_market_exposure <= 0:
            raise ValueError("max_market_exposure must be positive")
        if self.max_daily_loss <= 0:
            raise ValueError("max_daily_loss must be positive")
        if self.max_trades_per_market <= 0:
            raise ValueError("max_trades_per_market must be positive")
        if self.market_entry_cutoff_seconds < 0:
            raise ValueError("market_entry_cutoff_seconds cannot be negative")
        if self.cycle_length_seconds <= 0:
            raise ValueError("cycle_length_seconds must be positive")
        if self.cycle_analysis_seconds < 0:
            raise ValueError("cycle_analysis_seconds cannot be negative")
        if self.cycle_cooldown_seconds < 0:
            raise ValueError("cycle_cooldown_seconds cannot be negative")
        if self.cycle_analysis_seconds + self.cycle_cooldown_seconds >= self.cycle_length_seconds:
            raise ValueError("cycle analysis + cooldown must be shorter than cycle length")
        if self.cycle_max_trades <= 0:
            raise ValueError("cycle_max_trades must be positive")
        if self.wallet_signal_min_win_rate < 0 or self.wallet_signal_min_win_rate > 1:
            raise ValueError("wallet_signal_min_win_rate must be between 0 and 1")
        if self.wallet_signal_min_support <= 0:
            raise ValueError("wallet_signal_min_support must be positive")
        if self.wallet_signal_min_days <= 0:
            raise ValueError("wallet_signal_min_days must be positive")
        if self.wallet_signal_max_entry_price <= 0 or self.wallet_signal_max_entry_price > 1:
            raise ValueError("wallet_signal_max_entry_price must be in (0, 1]")
        if self.wallet_signal_min_confidence_boost < 0:
            raise ValueError("wallet_signal_min_confidence_boost cannot be negative")
        if self.wallet_signal_min_validation_win_rate < 0 or self.wallet_signal_min_validation_win_rate > 1:
            raise ValueError("wallet_signal_min_validation_win_rate must be between 0 and 1")
        if self.wallet_signal_min_validation_wilson_lower < 0 or self.wallet_signal_min_validation_wilson_lower > 1:
            raise ValueError("wallet_signal_min_validation_wilson_lower must be between 0 and 1")
        if self.wallet_signal_max_train_validation_win_rate_delta < 0:
            raise ValueError("wallet_signal_max_train_validation_win_rate_delta cannot be negative")
        if self.wallet_signal_enabled and self.wallet_signal_path and not Path(self.wallet_signal_path).exists():
            raise ValueError("wallet_signal_path does not exist")
        if self.wallet_signal_mode not in {"overlay", "gate"}:
            raise ValueError("wallet_signal_mode must be 'overlay' or 'gate'")
        if self.mode == "live":
            required = [
                "POLYMARKET_PRIVATE_KEY",
                "CLOB_API_KEY",
                "CLOB_SECRET",
                "CLOB_PASS_PHRASE",
            ]
            missing = [name for name in required if not os.getenv(name)]
            if missing:
                joined = ", ".join(missing)
                raise ValueError(f"live mode requires missing env vars: {joined}")


def _bool_from_env(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> BotSettings:
    settings = BotSettings(
        mode=os.getenv("BOT_MODE", "paper").strip().lower(),
        market_data_mode=os.getenv("MARKET_DATA_MODE", BotSettings.market_data_mode).strip().lower(),
        gamma_api_base=os.getenv("GAMMA_API_BASE", BotSettings.gamma_api_base),
        clob_api_base=os.getenv("CLOB_API_BASE", BotSettings.clob_api_base),
        binance_ws_base=os.getenv("BINANCE_WS_BASE", BotSettings.binance_ws_base),
        dashboard_host=os.getenv("DASHBOARD_HOST", BotSettings.dashboard_host),
        dashboard_port=int(os.getenv("DASHBOARD_PORT", str(BotSettings.dashboard_port))),
        dashboard_auth_user=os.getenv("DASHBOARD_AUTH_USER") or None,
        dashboard_auth_password=os.getenv("DASHBOARD_AUTH_PASSWORD") or None,
        max_order_notional=float(os.getenv("MAX_ORDER_NOTIONAL", str(BotSettings.max_order_notional))),
        max_market_exposure=float(os.getenv("MAX_MARKET_EXPOSURE", str(BotSettings.max_market_exposure))),
        max_daily_loss=float(os.getenv("MAX_DAILY_LOSS", str(BotSettings.max_daily_loss))),
        max_trades_per_market=int(os.getenv("MAX_TRADES_PER_MARKET", str(BotSettings.max_trades_per_market))),
        market_entry_cutoff_seconds=int(
            os.getenv("MARKET_ENTRY_CUTOFF_SECONDS", str(BotSettings.market_entry_cutoff_seconds))
        ),
        kill_switch=_bool_from_env(os.getenv("KILL_SWITCH"), BotSettings.kill_switch),
        cycle_mode_enabled=_bool_from_env(os.getenv("CYCLE_MODE_ENABLED"), BotSettings.cycle_mode_enabled),
        cycle_length_seconds=int(os.getenv("CYCLE_LENGTH_SECONDS", str(BotSettings.cycle_length_seconds))),
        cycle_analysis_seconds=int(os.getenv("CYCLE_ANALYSIS_SECONDS", str(BotSettings.cycle_analysis_seconds))),
        cycle_cooldown_seconds=int(os.getenv("CYCLE_COOLDOWN_SECONDS", str(BotSettings.cycle_cooldown_seconds))),
        cycle_max_trades=int(os.getenv("CYCLE_MAX_TRADES", str(BotSettings.cycle_max_trades))),
        wallet_signal_path=os.getenv("WALLET_SIGNAL_PATH") or None,
        wallet_signal_enabled=_bool_from_env(os.getenv("WALLET_SIGNAL_ENABLED"), BotSettings.wallet_signal_enabled),
        wallet_signal_mode=os.getenv("WALLET_SIGNAL_MODE", BotSettings.wallet_signal_mode).strip().lower(),
        wallet_signal_min_win_rate=float(
            os.getenv("WALLET_SIGNAL_MIN_WIN_RATE", str(BotSettings.wallet_signal_min_win_rate))
        ),
        wallet_signal_min_support=int(os.getenv("WALLET_SIGNAL_MIN_SUPPORT", str(BotSettings.wallet_signal_min_support))),
        wallet_signal_min_days=int(os.getenv("WALLET_SIGNAL_MIN_DAYS", str(BotSettings.wallet_signal_min_days))),
        wallet_signal_max_entry_price=float(
            os.getenv("WALLET_SIGNAL_MAX_ENTRY_PRICE", str(BotSettings.wallet_signal_max_entry_price))
        ),
        wallet_signal_min_confidence_boost=float(
            os.getenv("WALLET_SIGNAL_MIN_CONFIDENCE_BOOST", str(BotSettings.wallet_signal_min_confidence_boost))
        ),
        wallet_signal_local_tz=os.getenv("WALLET_SIGNAL_LOCAL_TZ", BotSettings.wallet_signal_local_tz),
        wallet_signal_require_validated=_bool_from_env(
            os.getenv("WALLET_SIGNAL_REQUIRE_VALIDATED"), BotSettings.wallet_signal_require_validated
        ),
        wallet_signal_min_validation_win_rate=float(
            os.getenv("WALLET_SIGNAL_MIN_VALIDATION_WIN_RATE", str(BotSettings.wallet_signal_min_validation_win_rate))
        ),
        wallet_signal_min_validation_wilson_lower=float(
            os.getenv(
                "WALLET_SIGNAL_MIN_VALIDATION_WILSON_LOWER",
                str(BotSettings.wallet_signal_min_validation_wilson_lower),
            )
        ),
        wallet_signal_max_train_validation_win_rate_delta=float(
            os.getenv(
                "WALLET_SIGNAL_MAX_TRAIN_VALIDATION_WIN_RATE_DELTA",
                str(BotSettings.wallet_signal_max_train_validation_win_rate_delta),
            )
        ),
    )
    settings.validate()
    return settings
