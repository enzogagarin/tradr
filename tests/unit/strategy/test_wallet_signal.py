from datetime import UTC, datetime, timedelta

from polymarket_btc_bot.domain import Market, MarketAsset, OrderBook, OrderBookLevel, StrategyDecision
from polymarket_btc_bot.strategy import WalletOpportunityOverlay, WalletSignalConfig


def _market():
    now = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    return Market(
        market_id="m1",
        slug="btc-updown-5m-1783051200",
        question="BTC up?",
        start_ts=now - timedelta(minutes=1),
        end_ts=now + timedelta(minutes=4),
        up=MarketAsset("up", "UP"),
        down=MarketAsset("down", "DOWN"),
        status="OPEN",
    )


def _book(asset_id, ask):
    now = datetime(2026, 7, 3, 12, 0, tzinfo=UTC)
    return OrderBook(asset_id, (OrderBookLevel(max(0.0, ask - 0.01), 100),), (OrderBookLevel(ask, 100),), now)


def test_wallet_overlay_boosts_matching_baseline_decision():
    report = {
        "opportunities": [
            {
                "pattern": "asset=btc|interval=5m|outcome=up|avg_price=0.15-0.35",
                "win_rate": 0.98,
                "count": 25,
                "recurrence_days": 6,
                "opportunity_score": 100,
                "is_validated": True,
                "train": {"win_rate": 0.98},
                "validation": {"win_rate": 0.9},
                "validation_wilson_lower": 0.75,
            }
        ],
        "avoid_patterns": [],
    }
    decision = StrategyDecision("BUY_UP", 0.7, 0.03, 0.25, "baseline_edge_up", datetime(2026, 7, 3, 12, 0, tzinfo=UTC))

    updated = WalletOpportunityOverlay(report, WalletSignalConfig()).apply(
        decision,
        market=_market(),
        up_book=_book("up", 0.25),
        down_book=_book("down", 0.76),
        now=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
    )

    assert updated.action == "BUY_UP"
    assert updated.edge == 0.05
    assert "wallet_opportunity" in updated.reason


def test_wallet_overlay_ignores_unvalidated_opportunity_by_default():
    report = {
        "opportunities": [
            {
                "pattern": "asset=btc|interval=5m|outcome=up|avg_price=0.15-0.35",
                "win_rate": 0.98,
                "count": 25,
                "recurrence_days": 6,
                "opportunity_score": 100,
                "is_validated": False,
            }
        ],
        "avoid_patterns": [],
    }
    decision = StrategyDecision("BUY_UP", 0.7, 0.03, 0.25, "baseline_edge_up", datetime(2026, 7, 3, 12, 0, tzinfo=UTC))

    updated = WalletOpportunityOverlay(report, WalletSignalConfig()).apply(
        decision,
        market=_market(),
        up_book=_book("up", 0.25),
        down_book=_book("down", 0.76),
        now=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
    )

    assert updated == decision


def test_wallet_gate_blocks_when_no_validated_opportunity_matches():
    report = {
        "opportunities": [
            {
                "pattern": "asset=btc|interval=5m|outcome=down|avg_price=0.15-0.35",
                "win_rate": 0.98,
                "count": 25,
                "recurrence_days": 6,
                "opportunity_score": 100,
                "is_validated": True,
                "validation": {"win_rate": 0.9},
                "validation_wilson_lower": 0.75,
            }
        ],
        "avoid_patterns": [],
    }
    decision = StrategyDecision("BUY_UP", 0.7, 0.03, 0.25, "baseline_edge_up", datetime(2026, 7, 3, 12, 0, tzinfo=UTC))

    updated = WalletOpportunityOverlay(report, WalletSignalConfig(mode="gate")).apply(
        decision,
        market=_market(),
        up_book=_book("up", 0.25),
        down_book=_book("down", 0.76),
        now=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
    )

    assert updated.action == "NO_TRADE"
    assert updated.reason == "wallet_gate_no_validated_opportunity"


def test_wallet_gate_allows_matching_baseline_decision():
    report = {
        "opportunities": [
            {
                "pattern": "asset=btc|interval=5m|outcome=up|avg_price=0.15-0.35",
                "win_rate": 0.98,
                "count": 25,
                "recurrence_days": 6,
                "opportunity_score": 100,
                "is_validated": True,
                "validation": {"win_rate": 0.9},
                "validation_wilson_lower": 0.75,
            }
        ],
        "avoid_patterns": [],
    }
    decision = StrategyDecision("BUY_UP", 0.7, 0.03, 0.25, "baseline_edge_up", datetime(2026, 7, 3, 12, 0, tzinfo=UTC))

    updated = WalletOpportunityOverlay(report, WalletSignalConfig(mode="gate")).apply(
        decision,
        market=_market(),
        up_book=_book("up", 0.25),
        down_book=_book("down", 0.76),
        now=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
    )

    assert updated.action == "BUY_UP"
    assert "wallet_opportunity" in updated.reason


def test_wallet_gate_makes_baseline_no_trade_reason_visible():
    report = {
        "opportunities": [
            {
                "pattern": "asset=btc|interval=5m|avg_price=0.15-0.35",
                "win_rate": 0.98,
                "count": 25,
                "recurrence_days": 6,
                "opportunity_score": 100,
                "is_validated": True,
            }
        ],
        "avoid_patterns": [],
    }
    decision = StrategyDecision("NO_TRADE", 0.51, 0.0, None, "no_edge", datetime(2026, 7, 3, 12, 0, tzinfo=UTC))

    updated = WalletOpportunityOverlay(report, WalletSignalConfig(mode="gate")).apply(
        decision,
        market=_market(),
        up_book=_book("up", 0.25),
        down_book=_book("down", 0.76),
        now=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
    )

    assert updated.action == "NO_TRADE"
    assert updated.reason == "wallet_gate_baseline_no_trade"


def test_wallet_overlay_blocks_matching_avoid_pattern():
    report = {
        "opportunities": [],
        "avoid_patterns": [
            {
                "pattern": "asset=btc|interval=5m|outcome=up|avg_price=0.15-0.35",
                "loss_rate": 0.8,
                "avoid_score": 100,
            }
        ],
    }
    decision = StrategyDecision("BUY_UP", 0.7, 0.03, 0.25, "baseline_edge_up", datetime(2026, 7, 3, 12, 0, tzinfo=UTC))

    updated = WalletOpportunityOverlay(report, WalletSignalConfig()).apply(
        decision,
        market=_market(),
        up_book=_book("up", 0.25),
        down_book=_book("down", 0.76),
        now=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
    )

    assert updated.action == "NO_TRADE"
    assert updated.reason.startswith("wallet_avoid:")
