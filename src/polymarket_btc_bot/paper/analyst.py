from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from math import erf, log, sqrt
from pathlib import Path
from typing import Any

from polymarket_btc_bot.adapters.polymarket import ClobClient, GammaClient
from polymarket_btc_bot.adapters.reference_feeds import BinanceHistoricalKlineClient, BinancePriceFeed
from polymarket_btc_bot.config import BotSettings
from polymarket_btc_bot.domain import (
    BotMode,
    BtcTick,
    DashboardSnapshot,
    Market,
    MarketAsset,
    OrderBook,
    OrderBookLevel,
)
from polymarket_btc_bot.execution import PaperExecutor
from polymarket_btc_bot.portfolio import PortfolioLedger
from polymarket_btc_bot.risk import PositionSizingConfig, RiskEngine, RiskLimits, RiskState, calculate_position_notional
from polymarket_btc_bot.scheduler import CycleGate, CycleGateConfig, MarketScheduler
from polymarket_btc_bot.strategy import BaselineProbabilityStrategy, StrategyInputs, WalletOpportunityOverlay, WalletSignalConfig


class PaperAnalyst:
    def __init__(
        self,
        settings: BotSettings,
        market_client: GammaClient | None = None,
        clob_client: ClobClient | None = None,
        price_feed: BinancePriceFeed | None = None,
        scheduler: MarketScheduler | None = None,
        strategy: BaselineProbabilityStrategy | None = None,
        executor: PaperExecutor | None = None,
        risk_engine: RiskEngine | None = None,
        wallet_overlay: WalletOpportunityOverlay | None = None,
        use_live_market_discovery: bool | None = None,
        kline_client: BinanceHistoricalKlineClient | None = None,
    ) -> None:
        self.settings = settings
        self.market_client = market_client or GammaClient(settings.gamma_api_base)
        self.clob_client = clob_client or ClobClient(settings.clob_api_base)
        self.price_feed = price_feed or BinancePriceFeed()
        self.kline_client = kline_client or BinanceHistoricalKlineClient()
        self._cycle_open_cache: tuple[int, float] | None = None
        self.scheduler = scheduler or MarketScheduler(entry_cutoff=timedelta(seconds=settings.market_entry_cutoff_seconds))
        self.cycle_gate = CycleGate(
            CycleGateConfig(
                enabled=settings.cycle_mode_enabled,
                length_seconds=settings.cycle_length_seconds,
                analysis_seconds=settings.cycle_analysis_seconds,
                cooldown_seconds=settings.cycle_cooldown_seconds,
                max_trades=settings.cycle_max_trades,
            )
        )
        self.strategy = strategy or BaselineProbabilityStrategy(
            min_edge=settings.strategy_min_edge,
            max_spread=settings.strategy_max_spread,
            max_book_age=timedelta(seconds=settings.strategy_max_book_age_seconds),
            assumed_5m_volatility=settings.strategy_assumed_volatility,
            market_blend_weight=settings.strategy_market_blend_weight,
            min_divergence=settings.strategy_min_divergence,
        )
        self.executor = executor or PaperExecutor(
            fee_bps=settings.exec_fee_bps,
            slippage=settings.exec_slippage,
            max_levels=settings.exec_max_levels,
        )
        self.risk_engine = risk_engine or RiskEngine()
        self.wallet_overlay = wallet_overlay or _wallet_overlay_from_settings(settings)
        self.market_data_mode = "live" if use_live_market_discovery is True else settings.market_data_mode
        self.ledger_path = Path(settings.portfolio_ledger_path)
        self._settlement_klines: tuple[int, dict[int, tuple[float, float, float]]] | None = None
        self._vol_cache: tuple[int, float] | None = None

    def snapshot(self, persist: bool = False) -> dict[str, Any]:
        now = datetime.now(tz=UTC)
        # The ledger is the source of truth for exposure / PnL / trade counts.
        # Reload from disk each call so the read-only dashboard sees fills that
        # the executing loop wrote. Only persist=True runs settle + record.
        ledger = PortfolioLedger.load(self.ledger_path, starting_bankroll=self.settings.starting_bankroll)
        settled_now: list[Any] = []
        if persist:
            settled_now = ledger.settle_due(now, resolver=self._resolve_position)
        btc_tick = self._latest_btc_tick(now)
        market, state_source = self._select_market(now)
        schedule = self.scheduler.select([market], now)
        reference_price = self._reference_price_for_market(market, btc_tick, state_source, now)
        up_book, down_book, book_source = self._books_for_market(
            market, btc_tick=btc_tick, reference_price=reference_price, now=now
        )
        tradable = schedule.tradable and not self.settings.kill_switch and not state_source.startswith("live_unavailable")

        volatility_5m = self._recent_5m_volatility(now) if self.settings.strategy_use_realized_vol else None
        baseline_decision = self.strategy.evaluate(
            StrategyInputs(
                market=market,
                btc_tick=btc_tick,
                up_book=up_book,
                down_book=down_book,
                reference_price=reference_price,
                tradable=tradable,
                schedule_reason=_blocking_reason(self.settings.kill_switch, schedule.reason, state_source),
                volatility_5m=volatility_5m,
            )
        )
        decision = self.wallet_overlay.apply(
            baseline_decision,
            market=market,
            up_book=up_book,
            down_book=down_book,
            now=now,
        )
        cycle_state = self.cycle_gate.evaluate(now)
        decision = self.cycle_gate.apply(decision, cycle_state)
        risk_state = ledger.risk_state_for(market.market_id, now)
        portfolio_summary = ledger.summary(now)
        requested_notional = calculate_position_notional(
            decision,
            equity=float(portfolio_summary.get("equity") or self.settings.starting_bankroll),
            volatility_5m=volatility_5m,
            config=PositionSizingConfig(
                enabled=self.settings.position_sizing_enabled,
                max_order_notional=self.settings.max_order_notional,
                bankroll_fraction=self.settings.position_bankroll_fraction,
                min_notional=self.settings.position_min_notional,
                edge_scale=self.settings.position_edge_scale,
                volatility_target=self.settings.position_volatility_target,
            ),
        )
        risk_validation = self.risk_engine.validate_order_intent(
            decision=decision,
            market=market,
            limits=RiskLimits(
                max_order_notional=self.settings.max_order_notional,
                max_market_exposure=self.settings.max_market_exposure,
                max_daily_loss=self.settings.max_daily_loss,
                max_trades_per_market=self.settings.max_trades_per_market,
                kill_switch=self.settings.kill_switch,
            ),
            state=risk_state,
            requested_notional=requested_notional,
        )
        if risk_validation.approved:
            execution = self.executor.execute(
                decision=decision,
                up_book=up_book,
                down_book=down_book,
                max_order_notional=risk_validation.allowed_notional or self.settings.max_order_notional,
            )
            if persist and execution.status in {"FILLED", "PARTIAL_FILL"} and execution.order and execution.fill:
                cycle_epoch = int(market.start_ts.timestamp()) // 300 * 300
                ledger.record_fill(
                    market_id=market.market_id,
                    slug=market.slug,
                    outcome=execution.order.outcome,
                    asset_id=execution.order.asset_id,
                    shares=execution.fill.shares,
                    price=execution.fill.price,
                    fees=execution.fill.fees,
                    end_ts=market.end_ts,
                    cycle_open_epoch=cycle_epoch,
                    reference_open=reference_price,
                    now=now,
                )
        else:
            execution = self.executor.reject(risk_validation.reason_code)

        snapshot = DashboardSnapshot(
            mode=BotMode(self.settings.mode),
            market=market,
            btc_tick=btc_tick,
            up_book=up_book,
            down_book=down_book,
            decision=decision,
            risk_state={
                "market_data_mode": self.market_data_mode,
                "state_source": state_source,
                "book_source": book_source,
                "reference_price": round(reference_price, 2),
                "schedule_reason": schedule.reason,
                "market_entry_cutoff_seconds": self.settings.market_entry_cutoff_seconds,
                "cycle_mode_enabled": self.settings.cycle_mode_enabled,
                "cycle_length_seconds": self.settings.cycle_length_seconds,
                "cycle_analysis_seconds": self.settings.cycle_analysis_seconds,
                "cycle_cooldown_seconds": self.settings.cycle_cooldown_seconds,
                "cycle_max_trades": self.settings.cycle_max_trades,
                "cycle": cycle_state.to_dict(),
                "kill_switch": self.settings.kill_switch,
                "max_order_notional": self.settings.max_order_notional,
                "requested_order_notional": requested_notional,
                "position_sizing_enabled": self.settings.position_sizing_enabled,
                "max_market_exposure": self.settings.max_market_exposure,
                "max_daily_loss": self.settings.max_daily_loss,
                "max_trades_per_market": self.settings.max_trades_per_market,
                "open_exposure": risk_state.open_exposure,
                "daily_pnl": risk_state.daily_pnl,
                "trades_in_market": risk_state.trades_in_market,
                "portfolio": portfolio_summary,
                "settled_this_tick": len(settled_now),
                "risk_validation": risk_validation.to_dict(),
                "wallet_signal_enabled": self.wallet_overlay.config.enabled,
                "wallet_signal_mode": self.wallet_overlay.config.mode,
                "wallet_signal_path": self.settings.wallet_signal_path,
            },
            execution_state=execution.to_dict(),
        )
        return snapshot.to_dict()

    def _latest_btc_tick(self, now: datetime) -> BtcTick:
        try:
            return self.price_feed.latest_tick()
        except Exception:
            return BtcTick(
                venue="fallback",
                symbol="BTCUSDT",
                price=62482.35,
                bid=62482.30,
                ask=62482.40,
                source_ts=now,
                observed_ts=now,
            )

    def _select_market(self, now: datetime) -> tuple[Market, str]:
        if self.market_data_mode in {"auto", "live"}:
            try:
                markets = self.market_client.discover_btc_5m_markets(limit=100, pages=10)
                schedule = self.scheduler.select(markets, now)
                if schedule.current is not None:
                    return schedule.current, "gamma_live"
                if schedule.next_market is not None:
                    return schedule.next_market, "gamma_next"
                if self.market_data_mode == "live":
                    return build_demo_market(now, status="UNAVAILABLE"), "live_unavailable_no_btc_5m_market"
                return build_demo_market(now), "auto_demo_no_live_btc_5m_market"
            except Exception as exc:
                if self.market_data_mode == "live":
                    return build_demo_market(now, status="UNAVAILABLE"), f"live_unavailable_gamma_error:{type(exc).__name__}"
                return build_demo_market(now), f"auto_demo_gamma_error:{type(exc).__name__}"
        if self.market_data_mode == "live":
            return build_demo_market(now, status="UNAVAILABLE"), "live_unavailable_no_btc_5m_market"
        return build_demo_market(now), "demo_market"

    def _books_for_market(
        self,
        market: Market,
        btc_tick: BtcTick | None = None,
        reference_price: float | None = None,
        now: datetime | None = None,
    ) -> tuple[OrderBook, OrderBook, str]:
        if market.up.asset_id.startswith("demo-"):
            if market.status == "UNAVAILABLE":
                up_book, down_book = build_empty_orderbooks(market)
                return up_book, down_book, "live_unavailable_no_orderbook"
            fair_up = 0.5
            if btc_tick is not None and reference_price:
                fair_up = demo_fair_probability_up(
                    market, btc_tick.price, reference_price, now or datetime.now(tz=UTC)
                )
            up_book, down_book = build_demo_orderbooks(market, fair_up=fair_up)
            return up_book, down_book, "demo_book"
        try:
            return (
                self.clob_client.get_book(market.up.asset_id),
                self.clob_client.get_book(market.down.asset_id),
                "clob_live",
            )
        except Exception as exc:
            up_book, down_book = build_empty_orderbooks(market)
            return up_book, down_book, f"clob_unavailable:{type(exc).__name__}"

    def _reference_price_for_market(
        self, market: Market, btc_tick: BtcTick, state_source: str, now: datetime
    ) -> float:
        # The reference is the OPEN price of the current real 5m BTC candle
        # (locked for the whole cycle), matching Polymarket BTC Up/Down 5m
        # semantics closely enough for paper trading. The live market resolves
        # from Chainlink BTC/USD, but using a moving spot price as reference
        # would incorrectly force the model back to ~50/50 every tick.
        cycle_open = self._current_cycle_open(now)
        if cycle_open is not None and cycle_open > 0:
            return cycle_open
        return btc_tick.price

    def _current_cycle_open(self, now: datetime) -> float | None:
        cycle_key = int(now.timestamp() // 300) * 300
        if self._cycle_open_cache is not None and self._cycle_open_cache[0] == cycle_key:
            return self._cycle_open_cache[1]
        try:
            klines = self.kline_client.get_klines(symbol="BTCUSDT", interval="5m", limit=1)
        except Exception:
            return None
        if not klines:
            return None
        open_price = float(klines[-1].open)
        self._cycle_open_cache = (cycle_key, open_price)
        return open_price

    def _settlement_map(self, now: datetime) -> dict[int, tuple[float, float, float]]:
        """Map cycle-open-epoch -> (open, close, close_epoch) for recent 5m candles,
        cached ~15s. Used to settle open positions against the real candle."""
        bucket = int(now.timestamp() // 15)
        if self._settlement_klines is not None and self._settlement_klines[0] == bucket:
            return self._settlement_klines[1]
        try:
            klines = self.kline_client.get_klines(symbol="BTCUSDT", interval="5m", limit=288)
        except Exception:
            return self._settlement_klines[1] if self._settlement_klines else {}
        mapping = {
            int(k.open_time.timestamp()): (float(k.open), float(k.close), k.close_time.timestamp())
            for k in klines
        }
        self._settlement_klines = (bucket, mapping)
        return mapping

    def _recent_5m_volatility(self, now: datetime) -> float | None:
        """Realized per-5m volatility = stdev of recent 5m log returns (close/open).
        Cached ~5 min. Falls back to None (static vol) on any failure."""
        bucket = int(now.timestamp() // 300)
        if self._vol_cache is not None and self._vol_cache[0] == bucket:
            return self._vol_cache[1]
        try:
            klines = self.kline_client.get_klines(symbol="BTCUSDT", interval="5m", limit=144)
        except Exception:
            return self._vol_cache[1] if self._vol_cache else None
        returns = []
        for k in klines:
            if k.open > 0 and k.close > 0:
                returns.append(log(k.close / k.open))
        if len(returns) < 20:
            return None
        mean_r = sum(returns) / len(returns)
        var = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
        vol = sqrt(var)
        vol = max(0.0003, min(0.02, vol))  # clamp to sane 5m range
        self._vol_cache = (bucket, vol)
        return vol

    def _resolve_position(self, position: Any) -> bool | None:
        """Resolve a BTC 5m position: True if UP (candle close>open), False if DOWN,
        None if the candle for that cycle is not yet closed / not available."""
        now = datetime.now(tz=UTC)
        mapping = self._settlement_map(now)
        candle = mapping.get(int(position.cycle_open_epoch))
        if candle is None:
            return None
        open_price, close_price, close_epoch = candle
        if close_epoch > now.timestamp():
            return None
        return close_price > open_price


def _wallet_overlay_from_settings(settings: BotSettings) -> WalletOpportunityOverlay:
    report = None
    if settings.wallet_signal_path:
        report = json.loads(Path(settings.wallet_signal_path).read_text(encoding="utf-8"))
    return WalletOpportunityOverlay(
        report,
        WalletSignalConfig(
            enabled=settings.wallet_signal_enabled and report is not None,
            mode=settings.wallet_signal_mode,
            min_win_rate=settings.wallet_signal_min_win_rate,
            min_support=settings.wallet_signal_min_support,
            min_recurrence_days=settings.wallet_signal_min_days,
            max_entry_price=settings.wallet_signal_max_entry_price,
            min_confidence_boost=settings.wallet_signal_min_confidence_boost,
            local_tz=settings.wallet_signal_local_tz,
            require_validated=settings.wallet_signal_require_validated,
            min_validation_win_rate=settings.wallet_signal_min_validation_win_rate,
            min_validation_wilson_lower=settings.wallet_signal_min_validation_wilson_lower,
            max_train_validation_win_rate_delta=settings.wallet_signal_max_train_validation_win_rate_delta,
        ),
    )


def build_demo_market(now: datetime, status: str = "OPEN") -> Market:
    # Anchor the demo cycle to the real wall-clock 5-minute grid so the
    # countdown actually ticks down 300->0 and resets every 5 minutes,
    # exactly like a live BTC Up/Down 5m market, instead of sliding with now.
    floored_minute = (now.minute // 5) * 5
    start = now.replace(minute=floored_minute, second=0, microsecond=0)
    end = start + timedelta(minutes=5)
    return Market(
        market_id="demo-btc-5m",
        slug="btc-updown-5m-demo",
        question="Bitcoin Up or Down - demo paper cycle",
        start_ts=start,
        end_ts=end,
        up=MarketAsset("demo-up-token", "UP"),
        down=MarketAsset("demo-down-token", "DOWN"),
        status=status,
    )


# Demo strategy volatility must match the baseline strategy so the demo book is
# priced on the same fair value the strategy uses; any edge then comes only from
# the injected micro-noise, not from a structural mispricing.
_DEMO_5M_VOL = 0.0018


def demo_fair_probability_up(market: Market, btc_price: float, reference_price: float, now: datetime) -> float:
    """Fair P(up) from current price vs the locked cycle open (same model the
    baseline strategy uses). This is a weak momentum read, not a real edge."""
    if reference_price <= 0:
        return 0.5
    seconds_to_close = max(1.0, (market.end_ts - now).total_seconds())
    sigma = max(0.0001, _DEMO_5M_VOL * sqrt(seconds_to_close / 300.0))
    z = log(btc_price / reference_price) / sigma
    return min(0.99, max(0.01, 0.5 * (1.0 + erf(z / sqrt(2.0)))))


def build_demo_orderbooks(market: Market, fair_up: float = 0.5) -> tuple[OrderBook, OrderBook]:
    """Build a realistic demo book priced around fair value with a small spread
    and random micro-noise.

    The book mid tracks the fair probability, so there is NO permanent free
    edge. Only when the random noise happens to push an ask below fair by more
    than the strategy's min_edge does the bot trade. Because resolution is the
    real candle close-vs-open, wins and losses are genuinely ~50/50 and the
    equity curve reflects real (near-zero) edge instead of a rigged win rate.
    """
    now = datetime.now(tz=UTC)
    spread = 0.02
    noise = random.uniform(-0.06, 0.06)
    up_mid = min(0.97, max(0.03, fair_up + noise))
    down_mid = 1.0 - up_mid

    def _round(x: float) -> float:
        return round(min(0.99, max(0.01, x)), 2)

    up_ask = _round(up_mid + spread / 2)
    up_bid = _round(up_mid - spread / 2)
    down_ask = _round(down_mid + spread / 2)
    down_bid = _round(down_mid - spread / 2)

    up_book = OrderBook(
        asset_id=market.up.asset_id,
        bids=(OrderBookLevel(up_bid, 500), OrderBookLevel(_round(up_bid - 0.01), 800)),
        asks=(OrderBookLevel(up_ask, 600), OrderBookLevel(_round(up_ask + 0.01), 900)),
        observed_ts=now,
    )
    down_book = OrderBook(
        asset_id=market.down.asset_id,
        bids=(OrderBookLevel(down_bid, 500), OrderBookLevel(_round(down_bid - 0.01), 800)),
        asks=(OrderBookLevel(down_ask, 600), OrderBookLevel(_round(down_ask + 0.01), 900)),
        observed_ts=now,
    )
    return up_book, down_book


def build_empty_orderbooks(market: Market) -> tuple[OrderBook, OrderBook]:
    now = datetime.now(tz=UTC)
    return (
        OrderBook(asset_id=market.up.asset_id, bids=(), asks=(), observed_ts=now),
        OrderBook(asset_id=market.down.asset_id, bids=(), asks=(), observed_ts=now),
    )


def _blocking_reason(kill_switch: bool, schedule_reason: str, state_source: str) -> str:
    if kill_switch:
        return "kill_switch_enabled"
    if state_source.startswith("live_unavailable"):
        return state_source
    return schedule_reason
