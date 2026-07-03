from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from polymarket_btc_bot import __version__
from polymarket_btc_bot.adapters.polymarket import ClobClient, GammaClient, PolymarketDataApiClient
from polymarket_btc_bot.adapters.polymarket.data_api import read_jsonl, write_jsonl
from polymarket_btc_bot.adapters.reference_feeds import (
    BinanceHistoricalKlineClient,
    BinancePriceFeed,
    build_kline_history_report,
    default_history_path,
    read_klines_jsonl,
    write_klines_jsonl,
)
from polymarket_btc_bot.audit import AuditLog, default_audit_path
from polymarket_btc_bot.collector import RawCollector, RawEventWriter, default_raw_path
from polymarket_btc_bot.config import load_settings
from polymarket_btc_bot.dashboard.server import build_demo_snapshot, run_dashboard
from polymarket_btc_bot.paper import PaperAnalyst
from polymarket_btc_bot.research import (
    btc_training_summary,
    build_btc_training_rows,
    build_data_quality_report,
    build_feature_snapshots,
    evaluate_btc_training_csv,
    scan_btc_patterns,
    scan_wallet_daily_opportunities,
    scan_wallet_outcomes,
    summarize_wallet,
    write_btc_training_csv,
    write_feature_snapshots_csv,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="polymarket-btc-bot",
        description="Research-first Polymarket BTC Up/Down 5m paper trading bot",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("config", help="print validated runtime configuration")
    snapshot = subparsers.add_parser("snapshot", help="print the current paper analyst snapshot")
    snapshot.add_argument("--market-data", choices=("demo", "auto", "live"), help="override market data mode")
    dashboard = subparsers.add_parser("dashboard", help="serve the operator dashboard")
    dashboard.add_argument("--market-data", choices=("demo", "auto", "live"), help="override market data mode")
    paper_run = subparsers.add_parser("paper-run", help="run the paper analyst loop")
    paper_run.add_argument("--iterations", type=int, default=1, help="number of evaluations to print")
    paper_run.add_argument("--market-data", choices=("demo", "auto", "live"), help="override market data mode")
    paper_run.add_argument(
        "--no-audit",
        action="store_true",
        help="print paper decisions without appending the local JSONL audit log",
    )
    paper_run.add_argument("--loop", action="store_true", help="run continuously until interrupted")
    paper_run.add_argument("--interval", type=float, default=5.0, help="seconds between loop iterations (default 5)")
    audit_tail = subparsers.add_parser("audit-tail", help="print recent paper audit events")
    audit_tail.add_argument("--limit", type=int, default=5, help="number of audit events to print")
    collect = subparsers.add_parser("collect", help="collect raw paper-market events into JSONL")
    collect.add_argument("--iterations", type=int, default=1, help="number of collection cycles")
    collect.add_argument("--interval", type=float, default=0.0, help="seconds to wait between cycles")
    collect.add_argument("--market-data", choices=("demo", "auto", "live"), help="override market data mode")
    collect.add_argument("--raw-path", help="override raw JSONL output path")
    raw_tail = subparsers.add_parser("raw-tail", help="print recent raw collector events")
    raw_tail.add_argument("--limit", type=int, default=10, help="number of raw events to print")
    raw_tail.add_argument("--raw-path", help="override raw JSONL output path")
    quality_report = subparsers.add_parser("quality-report", help="summarize raw event quality for replay research")
    quality_report.add_argument("--raw-path", help="override raw JSONL input path")
    feature_snapshots = subparsers.add_parser("feature-snapshots", help="build point-in-time feature rows from raw events")
    feature_snapshots.add_argument("--raw-path", help="override raw JSONL input path")
    feature_snapshots.add_argument("--output", default="data/features/snapshots.csv", help="output CSV path")
    btc_history = subparsers.add_parser("btc-history", help="download Binance BTC kline history into JSONL")
    btc_history.add_argument("--symbol", default="BTCUSDT", help="Binance symbol")
    btc_history.add_argument("--interval", default="5m", help="Binance kline interval")
    btc_history.add_argument("--start", required=True, help="UTC date/datetime, for example 2026-07-01")
    btc_history.add_argument("--end", required=True, help="UTC date/datetime, exclusive-ish API end bound")
    btc_history.add_argument("--limit", type=int, default=1000, help="maximum bars to request, capped at 1000")
    btc_history.add_argument("--output", help="override output JSONL path")
    btc_history_bulk = subparsers.add_parser(
        "btc-history-bulk",
        help="download a multi-page Binance BTC kline range and build training CSV",
    )
    btc_history_bulk.add_argument("--symbol", default="BTCUSDT", help="Binance symbol")
    btc_history_bulk.add_argument("--interval", default="5m", help="Binance kline interval")
    btc_history_bulk.add_argument("--start", required=True, help="UTC date/datetime, for example 2024-01-01")
    btc_history_bulk.add_argument("--end", required=True, help="UTC date/datetime, for example 2024-02-01")
    btc_history_bulk.add_argument("--limit", type=int, default=1000, help="page size, capped at 1000")
    btc_history_bulk.add_argument("--max-pages", type=int, default=200, help="safety cap for paginated requests")
    btc_history_bulk.add_argument("--output", help="override output JSONL path")
    btc_history_bulk.add_argument("--training-output", help="override training CSV path")
    btc_history_bulk.add_argument("--manifest-output", help="override dataset manifest JSON path")
    btc_history_report = subparsers.add_parser("btc-history-report", help="summarize Binance kline JSONL history")
    btc_history_report.add_argument("path", help="kline JSONL path")
    btc_training = subparsers.add_parser("btc-training", help="build BTC training CSV from kline JSONL history")
    btc_training.add_argument("path", help="kline JSONL path")
    btc_training.add_argument("--output", default="data/training/btc_5m_training.csv", help="output CSV path")
    btc_model_eval = subparsers.add_parser(
        "btc-model-eval",
        help="walk-forward evaluate BTC training CSV against a baseline",
    )
    btc_model_eval.add_argument("path", help="training CSV path")
    btc_model_eval.add_argument("--target", default="label_next_1_up", help="boolean target column")
    btc_model_eval.add_argument("--min-train-rows", type=int, default=288, help="minimum prior rows before scoring")
    btc_model_eval.add_argument("--train-window-rows", type=int, default=2016, help="rolling prior rows to train on")
    btc_model_eval.add_argument("--min-evaluation-rows", type=int, default=100, help="minimum scored rows for a verdict")
    btc_pattern_scan = subparsers.add_parser(
        "btc-pattern-scan",
        help="rank BTC training-data regimes and candle patterns by forward outcome",
    )
    btc_pattern_scan.add_argument("paths", nargs="+", help="one or more BTC training CSV paths")
    btc_pattern_scan.add_argument("--target-horizon", type=int, default=1, choices=(1, 3, 12), help="forward label horizon")
    btc_pattern_scan.add_argument("--min-support", type=int, default=500, help="minimum rows a pattern must cover")
    btc_pattern_scan.add_argument("--top", type=int, default=30, help="number of ranked patterns to print")
    btc_pattern_scan.add_argument("--output", help="optional JSON output path")
    wallet_collect = subparsers.add_parser("wallet-collect", help="collect Polymarket wallet activity and positions")
    wallet_collect.add_argument("--user", required=True, help="proxy wallet address")
    wallet_collect.add_argument("--label", default="wallet", help="file label, for example dgcf")
    wallet_collect.add_argument("--max-rows", type=int, default=10_000, help="maximum rows per endpoint")
    wallet_collect.add_argument("--activity-output", help="activity JSONL output path")
    wallet_collect.add_argument("--positions-output", help="positions JSONL output path")
    wallet_report = subparsers.add_parser("wallet-report", help="summarize collected Polymarket wallet data")
    wallet_report.add_argument("--activity-path", required=True, help="activity JSONL path")
    wallet_report.add_argument("--positions-path", required=True, help="positions JSONL path")
    wallet_report.add_argument("--output", help="optional JSON report output path")
    wallet_outcomes = subparsers.add_parser(
        "wallet-outcomes",
        help="model successful and failed wallet positions from realized PnL",
    )
    wallet_outcomes.add_argument("--positions-path", required=True, help="positions JSONL path")
    wallet_outcomes.add_argument("--min-support", type=int, default=10, help="minimum positions per pattern")
    wallet_outcomes.add_argument("--output", help="optional JSON report output path")
    wallet_daily_opportunities = subparsers.add_parser(
        "wallet-daily-opportunities",
        help="rank recurring 24h wallet opportunity and avoid patterns",
    )
    wallet_daily_opportunities.add_argument(
        "--wallet",
        action="append",
        nargs=3,
        metavar=("LABEL", "ACTIVITY_JSONL", "POSITIONS_JSONL"),
        required=True,
        help="wallet label plus activity and positions JSONL paths; can be repeated",
    )
    wallet_daily_opportunities.add_argument("--lookback-days", type=int, default=30, help="position lookback window")
    wallet_daily_opportunities.add_argument("--local-tz", default="Europe/Istanbul", help="timezone for local 24h slots")
    wallet_daily_opportunities.add_argument("--min-support", type=int, default=10, help="minimum positions per pattern")
    wallet_daily_opportunities.add_argument("--min-days", type=int, default=3, help="minimum recurrence days per pattern")
    wallet_daily_opportunities.add_argument("--min-win-rate", type=float, default=0.75, help="minimum exploratory/train opportunity win rate")
    wallet_daily_opportunities.add_argument("--validation-ratio", type=float, default=0.30, help="recent chronological holdout ratio")
    wallet_daily_opportunities.add_argument("--min-validation-support", type=int, default=5, help="minimum holdout positions per pattern")
    wallet_daily_opportunities.add_argument("--min-validation-days", type=int, default=2, help="minimum holdout recurrence days per pattern")
    wallet_daily_opportunities.add_argument("--min-validation-win-rate", type=float, help="minimum holdout win rate; defaults to --min-win-rate")
    wallet_daily_opportunities.add_argument("--min-validation-wilson-lower", type=float, default=0.70, help="minimum Wilson lower bound on holdout win rate")
    wallet_daily_opportunities.add_argument("--max-train-validation-win-rate-delta", type=float, default=0.25, help="maximum train/holdout win-rate gap")
    wallet_daily_opportunities.add_argument("--output", help="optional JSON report output path")
    discover = subparsers.add_parser("discover-markets", help="discover BTC Up/Down 5m markets through Gamma")
    discover.add_argument("--limit", type=int, default=50, help="maximum Gamma events to scan")
    discover.add_argument("--pages", type=int, default=5, help="number of Gamma pages to scan")
    book = subparsers.add_parser("book", help="fetch a CLOB orderbook for one token id")
    book.add_argument("token_id", help="Polymarket CLOB outcome token id")
    btc_tick = subparsers.add_parser("btc-tick", help="fetch latest Binance BTCUSDT top-of-book tick")
    btc_tick.add_argument("--symbol", default="BTCUSDT", help="Binance symbol")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    settings = load_settings()

    if args.command == "config":
        print(json.dumps(settings.__dict__, indent=2, sort_keys=True))
        return 0
    if args.command == "snapshot":
        settings = _settings_with_market_data(settings, args.market_data)
        print(json.dumps(build_demo_snapshot(settings), indent=2))
        return 0
    if args.command == "dashboard":
        settings = _settings_with_market_data(settings, args.market_data)
        run_dashboard(settings)
        return 0
    if args.command == "paper-run":
        settings = _settings_with_market_data(settings, args.market_data)
        analyst = PaperAnalyst(settings)
        audit_log = AuditLog()
        iterations = args.iterations if not args.loop else 10**9
        for index in range(iterations):
            # paper-run is the executing loop: persist settles + records fills.
            snapshot = analyst.snapshot(persist=True)
            summary = _paper_summary(snapshot)
            if not args.no_audit:
                audit_path = audit_log.append(_audit_event(snapshot, summary))
                summary["audit_path"] = str(audit_path)
            print(json.dumps(summary, indent=2))
            if args.loop:
                summary_keys = ["action", "execution_status", "btc_price", "edge"]
                brief = {k: summary.get(k) for k in summary_keys}
                print(f"  loop[{index}] {brief}", flush=True)
            if index < iterations - 1 and args.interval > 0:
                time.sleep(args.interval)
        return 0
    if args.command == "audit-tail":
        print(json.dumps(AuditLog(default_audit_path()).tail(args.limit), indent=2))
        return 0
    if args.command == "collect":
        settings = _settings_with_market_data(settings, args.market_data)
        writer = RawEventWriter(Path(args.raw_path) if args.raw_path else default_raw_path())
        collector = RawCollector(PaperAnalyst(settings), writer=writer)
        for index in range(args.iterations):
            print(json.dumps(collector.collect_once(), indent=2))
            if index < args.iterations - 1 and args.interval > 0:
                time.sleep(args.interval)
        return 0
    if args.command == "raw-tail":
        writer = RawEventWriter(Path(args.raw_path) if args.raw_path else default_raw_path())
        print(json.dumps(writer.tail(args.limit), indent=2))
        return 0
    if args.command == "quality-report":
        report = build_data_quality_report(Path(args.raw_path) if args.raw_path else default_raw_path())
        print(json.dumps(report.to_dict(), indent=2))
        return 0
    if args.command == "feature-snapshots":
        rows = build_feature_snapshots(Path(args.raw_path) if args.raw_path else default_raw_path())
        output_path = write_feature_snapshots_csv(rows, args.output)
        print(
            json.dumps(
                {
                    "path": str(output_path),
                    "rows": len(rows),
                    "replay_ready_rows": sum(1 for row in rows if row.replay_ready),
                    "blocking_reasons": sorted({row.blocking_reason for row in rows if row.blocking_reason}),
                },
                indent=2,
            )
        )
        return 0
    if args.command == "btc-history":
        start = _parse_utc_datetime(args.start)
        end = _parse_utc_datetime(args.end)
        output_path = Path(args.output) if args.output else default_history_path(args.symbol, args.interval, start, end)
        klines = BinanceHistoricalKlineClient().get_klines(
            symbol=args.symbol,
            interval=args.interval,
            start=start,
            end=end,
            limit=args.limit,
        )
        write_klines_jsonl(klines, output_path)
        report = build_kline_history_report(klines, path=output_path)
        print(json.dumps(report.to_dict(), indent=2))
        return 0
    if args.command == "btc-history-bulk":
        start = _parse_utc_datetime(args.start)
        end = _parse_utc_datetime(args.end)
        history_path = Path(args.output) if args.output else default_history_path(args.symbol, args.interval, start, end)
        training_path = (
            Path(args.training_output)
            if args.training_output
            else Path("data/training") / f"{args.symbol.lower()}-{args.interval}-{start.date()}-{end.date()}-training.csv"
        )
        manifest_path = (
            Path(args.manifest_output)
            if args.manifest_output
            else training_path.with_suffix(".manifest.json")
        )
        klines = BinanceHistoricalKlineClient().get_klines_range(
            symbol=args.symbol,
            interval=args.interval,
            start=start,
            end=end,
            limit=args.limit,
            max_pages=args.max_pages,
        )
        write_klines_jsonl(klines, history_path)
        history_report = build_kline_history_report(klines, path=history_path)
        training_rows = build_btc_training_rows(klines)
        write_btc_training_csv(training_rows, training_path)
        result = {
            "history": history_report.to_dict(),
            "training": btc_training_summary(training_rows, path=training_path),
            "manifest_path": str(manifest_path),
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "btc-history-report":
        klines = read_klines_jsonl(args.path)
        report = build_kline_history_report(klines, path=args.path)
        print(json.dumps(report.to_dict(), indent=2))
        return 0
    if args.command == "btc-training":
        klines = read_klines_jsonl(args.path)
        rows = build_btc_training_rows(klines)
        output_path = write_btc_training_csv(rows, args.output)
        print(json.dumps(btc_training_summary(rows, path=output_path), indent=2))
        return 0
    if args.command == "btc-model-eval":
        report = evaluate_btc_training_csv(
            args.path,
            target=args.target,
            min_train_rows=args.min_train_rows,
            train_window_rows=args.train_window_rows,
            min_evaluation_rows=args.min_evaluation_rows,
        )
        print(json.dumps(report.to_dict(), indent=2))
        return 0
    if args.command == "btc-pattern-scan":
        report = scan_btc_patterns(
            args.paths,
            target_horizon=args.target_horizon,
            min_support=args.min_support,
            top_n=args.top,
        )
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0
    if args.command == "wallet-collect":
        activity_path = Path(args.activity_output) if args.activity_output else Path("data/wallets") / f"{args.label}-activity.jsonl"
        positions_path = (
            Path(args.positions_output) if args.positions_output else Path("data/wallets") / f"{args.label}-positions.jsonl"
        )
        client = PolymarketDataApiClient()
        activity = client.get_activity_pages(user=args.user, max_rows=args.max_rows)
        positions = client.get_position_pages(user=args.user, max_rows=args.max_rows)
        write_jsonl(activity, activity_path)
        write_jsonl(positions, positions_path)
        print(
            json.dumps(
                {
                    "user": args.user,
                    "activity_path": str(activity_path),
                    "activity_rows": len(activity),
                    "positions_path": str(positions_path),
                    "position_rows": len(positions),
                },
                indent=2,
            )
        )
        return 0
    if args.command == "wallet-report":
        summary = summarize_wallet(read_jsonl(args.activity_path), read_jsonl(args.positions_path)).to_dict()
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(summary, indent=2))
        return 0
    if args.command == "wallet-outcomes":
        report = scan_wallet_outcomes(read_jsonl(args.positions_path), min_support=args.min_support)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0
    if args.command == "wallet-daily-opportunities":
        report = scan_wallet_daily_opportunities(
            [
                (label, read_jsonl(activity_path), read_jsonl(positions_path))
                for label, activity_path, positions_path in args.wallet
            ],
            min_support=args.min_support,
            min_days=args.min_days,
            min_win_rate=args.min_win_rate,
            lookback_days=args.lookback_days,
            local_tz=args.local_tz,
            validation_ratio=args.validation_ratio,
            min_validation_support=args.min_validation_support,
            min_validation_days=args.min_validation_days,
            min_validation_win_rate=args.min_validation_win_rate,
            min_validation_wilson_lower=args.min_validation_wilson_lower,
            max_train_validation_win_rate_delta=args.max_train_validation_win_rate_delta,
        )
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0
    if args.command == "discover-markets":
        client = GammaClient(settings.gamma_api_base)
        markets = client.discover_btc_5m_markets(limit=args.limit, pages=args.pages)
        print(
            json.dumps(
                {
                    "scan": client.last_scan_stats,
                    "markets": [_market_to_cli_dict(market) for market in markets],
                },
                indent=2,
            )
        )
        return 0
    if args.command == "book":
        book = ClobClient(settings.clob_api_base).get_book(args.token_id)
        print(json.dumps(_book_to_cli_dict(book), indent=2))
        return 0
    if args.command == "btc-tick":
        tick = BinancePriceFeed().latest_tick(symbol=args.symbol)
        print(json.dumps(_btc_tick_to_cli_dict(tick), indent=2))
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


def _settings_with_market_data(settings, market_data):
    if market_data is None:
        return settings
    return replace(settings, market_data_mode=market_data)


def _parse_utc_datetime(value: str) -> datetime:
    if len(value) == 10:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _market_to_cli_dict(market):
    return {
        "market_id": market.market_id,
        "slug": market.slug,
        "question": market.question,
        "start_ts": market.start_ts.isoformat(),
        "end_ts": market.end_ts.isoformat(),
        "seconds_to_close": market.seconds_to_close,
        "up_asset_id": market.up.asset_id,
        "down_asset_id": market.down.asset_id,
    }


def _book_to_cli_dict(book):
    return {
        "asset_id": book.asset_id,
        "best_bid": None if book.best_bid is None else book.best_bid.price,
        "best_ask": None if book.best_ask is None else book.best_ask.price,
        "midpoint": book.midpoint,
        "spread": book.spread,
        "bid_levels": len(book.bids),
        "ask_levels": len(book.asks),
        "observed_ts": book.observed_ts.isoformat(),
    }


def _btc_tick_to_cli_dict(tick):
    return {
        "venue": tick.venue,
        "symbol": tick.symbol,
        "price": tick.price,
        "bid": tick.bid,
        "ask": tick.ask,
        "source_ts": tick.source_ts.isoformat(),
        "observed_ts": tick.observed_ts.isoformat(),
    }


def _paper_summary(snapshot):
    decision = snapshot["decision"]
    market = snapshot["market"]
    risk = snapshot["risk_state"]
    execution = snapshot.get("execution_state") or {}
    order = execution.get("order") or {}
    fill = execution.get("fill") or {}
    return {
        "market_id": market["market_id"],
        "source": risk["state_source"],
        "book_source": risk["book_source"],
        "seconds_to_close": market["seconds_to_close"],
        "btc_price": snapshot["btc_tick"]["price"],
        "reference_price": risk["reference_price"],
        "action": decision["action"],
        "probability_up": decision["probability_up"],
        "edge": decision["edge"],
        "target_price": decision["target_price"],
        "reason": decision["reason"],
        "execution_status": execution.get("status"),
        "execution_reason": execution.get("reason"),
        "risk_approved": (risk.get("risk_validation") or {}).get("approved"),
        "risk_reason_code": (risk.get("risk_validation") or {}).get("reason_code"),
        "paper_order_id": order.get("client_order_id"),
        "paper_outcome": order.get("outcome"),
        "paper_fill_shares": fill.get("shares"),
        "paper_fill_notional": fill.get("notional"),
    }


def _audit_event(snapshot, summary):
    return {
        "event_type": "paper_decision",
        "observed_ts": snapshot["decision"]["observed_ts"],
        "summary": summary,
        "market": snapshot["market"],
        "decision": snapshot["decision"],
        "execution": snapshot.get("execution_state"),
        "risk_state": snapshot["risk_state"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
