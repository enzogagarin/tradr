from datetime import UTC, datetime

from polymarket_btc_bot.domain import OrderBook, OrderBookLevel, StrategyDecision
from polymarket_btc_bot.execution import PaperExecutor


def _book(asset_id="up-token", ask_size=20):
    return OrderBook(
        asset_id=asset_id,
        bids=(OrderBookLevel(0.53, 100),),
        asks=(OrderBookLevel(0.55, ask_size),),
        observed_ts=datetime.now(tz=UTC),
    )


def _book_levels(asset_id="up-token"):
    return OrderBook(
        asset_id=asset_id,
        bids=(OrderBookLevel(0.50, 100),),
        asks=(
            OrderBookLevel(0.50, 10),
            OrderBookLevel(0.52, 10),
            OrderBookLevel(0.54, 100),
        ),
        observed_ts=datetime.now(tz=UTC),
    )


def test_paper_executor_skips_no_trade():
    decision = StrategyDecision("NO_TRADE", 0.5, 0.0, None, "edge_below_threshold", datetime.now(tz=UTC))

    result = PaperExecutor().execute(decision, _book(), _book("down-token"), max_order_notional=25)

    assert result.status == "SKIPPED"
    assert result.order is None
    assert result.fill is None


def test_paper_executor_fills_buy_up_against_top_ask():
    decision = StrategyDecision("BUY_UP", 0.64, 0.09, 0.55, "baseline_edge_up", datetime.now(tz=UTC))

    result = PaperExecutor().execute(decision, _book(ask_size=100), _book("down-token"), max_order_notional=11)

    assert result.status == "FILLED"
    assert result.order is not None
    assert result.fill is not None
    assert result.order.outcome == "UP"
    assert result.fill.price == 0.55
    assert result.fill.notional == 11.0


def test_paper_executor_partial_fills_when_book_size_is_smaller():
    decision = StrategyDecision("BUY_DOWN", 0.35, 0.1, 0.55, "baseline_edge_down", datetime.now(tz=UTC))

    result = PaperExecutor().execute(decision, _book(), _book("down-token", ask_size=3), max_order_notional=11)

    assert result.status == "PARTIAL_FILL"
    assert result.fill is not None
    assert result.fill.shares == 3
    assert result.fill.notional == 1.65


def test_paper_executor_walks_multiple_levels_and_charges_fee():
    decision = StrategyDecision("BUY_UP", 0.64, 0.09, 0.54, "baseline_edge_up", datetime.now(tz=UTC))

    result = PaperExecutor(fee_bps=10, max_levels=3).execute(
        decision,
        _book_levels(),
        _book("down-token"),
        max_order_notional=10.8,
    )

    assert result.status == "FILLED"
    assert result.fill is not None
    assert result.fill.levels_used == 2
    assert result.fill.price == 0.51
    assert result.fill.notional == 10.2
    assert result.fill.fees == 0.0102
    assert result.fill.liquidity == "TAKER_MULTI_LEVEL"


def test_paper_executor_slippage_respects_limit_price():
    decision = StrategyDecision("BUY_UP", 0.64, 0.09, 0.55, "baseline_edge_up", datetime.now(tz=UTC))

    result = PaperExecutor(slippage=0.01).execute(
        decision,
        _book(ask_size=100),
        _book("down-token"),
        max_order_notional=11,
    )

    assert result.status == "REJECTED"
    assert result.reason == "zero_fill_size"
