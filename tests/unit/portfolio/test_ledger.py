from datetime import UTC, datetime, timedelta

from polymarket_btc_bot.portfolio import PortfolioLedger


def _record(ledger, outcome, price, shares, end, cycle_epoch, ref, now):
    return ledger.record_fill(
        market_id=f"m-{cycle_epoch}",
        slug="btc-updown-5m-x",
        outcome=outcome,
        asset_id=f"{outcome.lower()}-token",
        shares=shares,
        price=price,
        fees=0.5,
        end_ts=end,
        cycle_open_epoch=cycle_epoch,
        reference_open=ref,
        now=now,
    )


def test_record_fill_updates_exposure_and_persists(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = PortfolioLedger.load(path, starting_bankroll=1000.0)
    now = datetime(2026, 7, 3, 8, 2, tzinfo=UTC)
    end = datetime(2026, 7, 3, 8, 5, tzinfo=UTC)
    _record(ledger, "UP", 0.10, 250.0, end, 1783065600, 100.0, now)

    assert ledger.open_exposure() == 25.5  # 250*0.10 + 0.5 fee
    assert ledger.trades_in_market("m-1783065600") == 1

    reloaded = PortfolioLedger.load(path)
    assert len(reloaded.open_positions()) == 1
    assert reloaded.open_exposure() == 25.5


def test_settle_due_resolves_win_and_loss(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = PortfolioLedger.load(path)
    open_ts = datetime(2026, 7, 3, 8, 2, tzinfo=UTC)
    end = datetime(2026, 7, 3, 8, 5, tzinfo=UTC)
    _record(ledger, "UP", 0.40, 62.5, end, 1000, 100.0, open_ts)     # UP wins
    _record(ledger, "DOWN", 0.40, 62.5, end, 2000, 100.0, open_ts)   # DOWN loses (up won)

    after_close = datetime(2026, 7, 3, 8, 6, tzinfo=UTC)
    # Resolver: cycle 1000 up won, cycle 2000 up won too.
    resolver = lambda p: True
    settled = ledger.settle_due(after_close, resolver=resolver)
    assert len(settled) == 2

    up_pos = next(p for p in ledger.positions if p.outcome == "UP")
    down_pos = next(p for p in ledger.positions if p.outcome == "DOWN")
    # UP won: payout 62.5, cost 25, fee 0.5 -> +37.0
    assert up_pos.won is True
    assert up_pos.realized_pnl == 37.0
    # DOWN lost: payout 0, cost 25, fee 0.5 -> -25.5
    assert down_pos.won is False
    assert down_pos.realized_pnl == -25.5

    assert ledger.realized_pnl_total() == round(37.0 - 25.5, 6)
    assert ledger.open_exposure() == 0.0


def test_settle_due_skips_when_outcome_unknown(tmp_path):
    ledger = PortfolioLedger.load(tmp_path / "l.json")
    open_ts = datetime(2026, 7, 3, 8, 2, tzinfo=UTC)
    end = datetime(2026, 7, 3, 8, 5, tzinfo=UTC)
    _record(ledger, "UP", 0.5, 50, end, 1000, 100.0, open_ts)
    settled = ledger.settle_due(datetime(2026, 7, 3, 8, 6, tzinfo=UTC), resolver=lambda p: None)
    assert settled == []
    assert len(ledger.open_positions()) == 1


def test_risk_state_reflects_ledger(tmp_path):
    ledger = PortfolioLedger.load(tmp_path / "l.json")
    now = datetime(2026, 7, 3, 8, 2, tzinfo=UTC)
    end = datetime(2026, 7, 3, 8, 5, tzinfo=UTC)
    _record(ledger, "UP", 0.20, 50, end, 1000, 100.0, now)
    rs = ledger.risk_state_for("m-1000", now)
    assert rs.open_exposure == 10.5
    assert rs.trades_in_market == 1
    assert rs.daily_pnl == 0.0
