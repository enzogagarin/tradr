from datetime import date

from polymarket_btc_bot.research.wallet_intel import (
    scan_wallet_daily_opportunities,
    scan_wallet_outcomes,
    summarize_wallet,
)


def test_summarize_wallet_separates_activity_and_position_snapshot_pnl():
    activity = [
        {
            "proxyWallet": "0xabc",
            "name": "dgcf",
            "pseudonym": "Mad-Plot",
            "type": "TRADE",
            "side": "BUY",
            "usdcSize": 10,
            "price": 0.1,
            "timestamp": 1_783_058_700,
            "slug": "btc-updown-5m-1783058700",
            "title": "Bitcoin Up or Down",
        },
        {
            "proxyWallet": "0xabc",
            "name": "dgcf",
            "type": "TRADE",
            "side": "SELL",
            "usdcSize": 15,
            "price": 0.9,
            "timestamp": 1_783_058_760,
            "slug": "btc-updown-5m-1783058700",
            "title": "Bitcoin Up or Down",
        },
        {"proxyWallet": "0xabc", "name": "dgcf", "type": "REDEEM", "usdcSize": 100},
    ]
    positions = [
        {
            "proxyWallet": "0xabc",
            "slug": "btc-updown-5m-1",
            "initialValue": 10,
            "currentValue": 20,
            "cashPnl": 10,
            "realizedPnl": 4,
            "endDate": "2026-07-01",
        },
        {
            "proxyWallet": "0xabc",
            "slug": "eth-updown-15m-1",
            "initialValue": 12,
            "currentValue": 0,
            "cashPnl": -12,
            "realizedPnl": -1,
            "endDate": "2026-05-01",
        },
    ]

    summary = summarize_wallet(activity, positions, as_of=date(2026, 7, 3))

    assert summary.user == "0xabc"
    assert summary.name == "dgcf"
    assert summary.trade_count == 2
    assert summary.buy_count == 1
    assert summary.sell_count == 1
    assert summary.total_redeem_usdc == 100
    assert summary.activity_net_cashflow_usdc == 105
    assert summary.activity_first_ts is not None
    assert summary.activity_last_ts is not None
    assert summary.position_cash_pnl == -2
    assert summary.position_realized_pnl == 3
    assert summary.realized_profitable_positions == 1
    assert summary.realized_losing_positions == 1
    assert summary.last_30d_position_count == 1
    assert summary.last_30d_realized_pnl == 4
    assert summary.last_30d_realized_win_rate == 1
    assert summary.by_asset[0]["bucket"] == "btc"
    assert summary.by_price_bucket[0]["bucket"] in {"0.05-0.15", "0.85-1.00"}


def test_scan_wallet_daily_opportunities_ranks_recurring_wins_and_losses():
    activity = []
    positions = []
    base_ts = 1_783_008_000
    for index in range(4):
        market_ts = base_ts + index * 86_400
        slug = f"btc-updown-5m-{market_ts}"
        activity.append(
            {
                "type": "TRADE",
                "side": "BUY",
                "slug": slug,
                "timestamp": market_ts + 45,
                "usdcSize": 10,
            }
        )
        positions.append(
            {
                "slug": slug,
                "outcome": "Up",
                "avgPrice": 0.1,
                "initialValue": 10,
                "totalBought": 100,
                "realizedPnl": 5,
                "endDate": "2026-07-01",
                "title": "BTC recurring winner",
            }
        )
    for index in range(4):
        market_ts = base_ts + index * 86_400 + 3_600
        slug = f"btc-updown-15m-{market_ts}"
        activity.append(
            {
                "type": "TRADE",
                "side": "BUY",
                "slug": slug,
                "timestamp": market_ts + 250,
                "usdcSize": 10,
            }
        )
        positions.append(
            {
                "slug": slug,
                "outcome": "Down",
                "avgPrice": 0.7,
                "initialValue": 10,
                "totalBought": 100,
                "realizedPnl": -4,
                "endDate": "2026-07-01",
                "title": "BTC recurring loser",
            }
        )

    report = scan_wallet_daily_opportunities(
        [("sample", activity, positions)],
        min_support=2,
        min_days=2,
        min_win_rate=0.75,
        min_validation_support=1,
        min_validation_days=1,
        min_validation_wilson_lower=0.0,
        as_of=date(2026, 7, 3),
    )

    assert report["observation_count"] == 8
    assert report["baseline"]["win_rate"] == 0.5
    assert report["validation"]["enabled"] is True
    assert report["opportunities"][0]["is_validated"] is True
    assert report["opportunities"][0]["validation_status"] == "validated"
    assert report["opportunities"][0]["validation"]["win_rate"] == 1
    assert "avg_price=0.05-0.15" in report["opportunities"][0]["pattern"]
    assert report["avoid_patterns"][0]["loss_rate"] == 1
    assert "avg_price=0.65-0.85" in report["avoid_patterns"][0]["pattern"]
    assert report["wallet_summaries"][0]["wallet"] == "sample"


def test_scan_wallet_daily_opportunities_demotes_train_only_patterns_to_watchlist():
    activity = []
    positions = []
    base_ts = 1_783_008_000
    for index in range(6):
        market_ts = base_ts + index * 86_400
        slug = f"btc-updown-5m-{market_ts}"
        activity.append({"type": "TRADE", "side": "BUY", "slug": slug, "timestamp": market_ts + 40, "usdcSize": 10})
        positions.append(
            {
                "slug": slug,
                "outcome": "Up",
                "avgPrice": 0.1,
                "initialValue": 10,
                "totalBought": 100,
                "realizedPnl": 5 if index < 4 else -5,
                "endDate": "2026-07-01",
                "title": "train good validation bad",
            }
        )

    report = scan_wallet_daily_opportunities(
        [("sample", activity, positions)],
        min_support=3,
        min_days=3,
        min_win_rate=0.75,
        min_validation_support=2,
        min_validation_days=2,
        min_validation_wilson_lower=0.0,
        as_of=date(2026, 7, 3),
    )

    assert report["validated_opportunities"] == []
    assert report["watchlist_opportunities"]
    assert "validation_win_rate_below_minimum" in report["watchlist_opportunities"][0]["validation_reasons"]
    assert "no_patterns_survived_chronological_validation" in report["blocking_reasons"]


def test_scan_wallet_outcomes_models_success_and_failure_patterns():
    positions = [
        {
            "slug": "btc-updown-5m-1",
            "outcome": "Up",
            "avgPrice": 0.42,
            "initialValue": 10,
            "totalBought": 100,
            "realizedPnl": 5,
            "endDate": "2026-07-01",
            "title": "BTC 1",
        },
        {
            "slug": "btc-updown-5m-2",
            "outcome": "Up",
            "avgPrice": 0.47,
            "initialValue": 12,
            "totalBought": 100,
            "realizedPnl": 7,
            "endDate": "2026-07-02",
            "title": "BTC 2",
        },
        {
            "slug": "eth-updown-5m-3",
            "outcome": "Down",
            "avgPrice": 0.9,
            "initialValue": 20,
            "totalBought": 50,
            "realizedPnl": -4,
            "endDate": "2026-07-02",
            "title": "ETH 1",
        },
        {
            "slug": "eth-updown-5m-4",
            "outcome": "Down",
            "avgPrice": 0.92,
            "initialValue": 25,
            "totalBought": 50,
            "realizedPnl": -6,
            "endDate": "2026-05-01",
            "title": "ETH 2",
        },
    ]

    report = scan_wallet_outcomes(positions, min_support=2, as_of=date(2026, 7, 3))

    assert report["decided_positions"] == 4
    assert report["win_rate"] == 0.5
    assert report["realized_pnl"] == 2
    assert report["last_30d_decided_positions"] == 3
    assert report["last_30d_realized_pnl"] == 8
    assert report["last_30d_win_rate"] == 0.6667
    assert report["success_patterns"][0]["pattern"] in {"asset=btc", "asset=btc|interval=5m"}
    assert report["failure_patterns"][0]["pattern"] in {"asset=eth", "asset=eth|interval=5m"}
    assert report["top_winning_positions"][0]["realized_pnl"] == 7
    assert report["top_losing_positions"][0]["realized_pnl"] == -6
