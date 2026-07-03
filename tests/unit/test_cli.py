from polymarket_btc_bot.cli.main import main


def test_cli_help_exits_cleanly(capsys):
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "polymarket-btc-bot" in output
    assert "dashboard" in output


def test_config_defaults_to_paper(capsys, monkeypatch):
    monkeypatch.delenv("BOT_MODE", raising=False)
    assert main(["config"]) == 0
    output = capsys.readouterr().out
    assert '"mode": "paper"' in output


def test_audit_tail_handles_empty_log(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert main(["audit-tail", "--limit", "3"]) == 0
    assert capsys.readouterr().out.strip() == "[]"


def test_paper_run_accepts_demo_market_data_override(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    assert main(["paper-run", "--iterations", "1", "--market-data", "demo", "--no-audit"]) == 0

    output = capsys.readouterr().out
    assert '"source": "demo_market"' in output
    assert '"risk_reason_code"' in output


def test_discover_markets_prints_scan_metadata(capsys, monkeypatch):
    class FakeGammaClient:
        def __init__(self, base_url):
            self.last_scan_stats = {"pages_scanned": 1, "events_scanned": 0, "markets_found": 0}

        def discover_btc_5m_markets(self, limit, pages):
            assert limit == 7
            assert pages == 2
            return []

    monkeypatch.setattr("polymarket_btc_bot.cli.main.GammaClient", FakeGammaClient)

    assert main(["discover-markets", "--limit", "7", "--pages", "2"]) == 0

    output = capsys.readouterr().out
    assert '"scan"' in output
    assert '"markets": []' in output


def test_collect_writes_raw_events_and_raw_tail_reads_them(capsys, monkeypatch, tmp_path):
    raw_path = tmp_path / "events.jsonl"
    monkeypatch.chdir(tmp_path)

    assert (
        main(
            [
                "collect",
                "--iterations",
                "1",
                "--market-data",
                "demo",
                "--raw-path",
                str(raw_path),
            ]
        )
        == 0
    )
    collect_output = capsys.readouterr().out
    assert '"events_written": 7' in collect_output
    assert raw_path.exists()

    assert main(["raw-tail", "--limit", "2", "--raw-path", str(raw_path)]) == 0
    tail_output = capsys.readouterr().out
    assert '"event_type": "risk_validation"' in tail_output
    assert '"event_type": "paper_execution"' in tail_output


def test_quality_report_summarizes_raw_file(capsys, monkeypatch, tmp_path):
    raw_path = tmp_path / "events.jsonl"
    monkeypatch.chdir(tmp_path)

    assert main(["collect", "--iterations", "1", "--market-data", "demo", "--raw-path", str(raw_path)]) == 0
    capsys.readouterr()

    assert main(["quality-report", "--raw-path", str(raw_path)]) == 0

    output = capsys.readouterr().out
    assert '"total_events": 7' in output
    assert '"sufficient_for_replay": false' in output
    assert '"no_live_market_events"' in output


def test_feature_snapshots_exports_csv(capsys, monkeypatch, tmp_path):
    raw_path = tmp_path / "events.jsonl"
    output_path = tmp_path / "features.csv"
    monkeypatch.chdir(tmp_path)

    assert main(["collect", "--iterations", "1", "--market-data", "demo", "--raw-path", str(raw_path)]) == 0
    capsys.readouterr()

    assert main(["feature-snapshots", "--raw-path", str(raw_path), "--output", str(output_path)]) == 0

    output = capsys.readouterr().out
    assert output_path.exists()
    assert '"rows": 1' in output
    assert '"replay_ready_rows": 0' in output
    assert "non_live_market_state" in output


def test_btc_history_writes_jsonl_and_prints_report(capsys, monkeypatch, tmp_path):
    output_path = tmp_path / "history.jsonl"

    class FakeHistoryClient:
        def get_klines(self, *, symbol, interval, start, end, limit):
            from polymarket_btc_bot.adapters.reference_feeds import parse_klines

            assert symbol == "BTCUSDT"
            assert interval == "5m"
            assert limit == 3
            return parse_klines(
                [
                    [
                        1_782_864_000_000,
                        "100.0",
                        "101.0",
                        "99.0",
                        "100.5",
                        "1.0",
                        1_782_864_299_999,
                        "100.0",
                        10,
                    ]
                ],
                symbol=symbol,
                interval=interval,
            )

    monkeypatch.setattr("polymarket_btc_bot.cli.main.BinanceHistoricalKlineClient", lambda: FakeHistoryClient())

    assert (
        main(
            [
                "btc-history",
                "--start",
                "2026-07-01",
                "--end",
                "2026-07-02",
                "--limit",
                "3",
                "--output",
                str(output_path),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert output_path.exists()
    assert '"row_count": 1' in output
    assert '"less_than_one_day_of_5m_bars"' in output


def test_btc_history_report_reads_existing_jsonl(capsys, tmp_path):
    from polymarket_btc_bot.adapters.reference_feeds import parse_klines, write_klines_jsonl

    path = tmp_path / "history.jsonl"
    write_klines_jsonl(
        parse_klines(
            [[1_782_864_000_000, "100", "101", "99", "100.5", "1", 1_782_864_299_999, "100", 10]],
            symbol="BTCUSDT",
            interval="5m",
        ),
        path,
    )

    assert main(["btc-history-report", str(path)]) == 0

    output = capsys.readouterr().out
    assert '"symbol": "BTCUSDT"' in output
    assert '"row_count": 1' in output


def test_btc_history_bulk_writes_history_and_training(capsys, monkeypatch, tmp_path):
    history_path = tmp_path / "history.jsonl"
    training_path = tmp_path / "training.csv"

    class FakeHistoryClient:
        def get_klines_range(self, *, symbol, interval, start, end, limit, max_pages):
            from datetime import timedelta

            from polymarket_btc_bot.adapters.reference_feeds import parse_klines

            assert symbol == "BTCUSDT"
            assert interval == "5m"
            assert limit == 100
            assert max_pages == 2
            payload = []
            for index in range(16):
                open_time = start + timedelta(minutes=5 * index)
                close_time = open_time + timedelta(minutes=5) - timedelta(milliseconds=1)
                payload.append(
                    [
                        int(open_time.timestamp() * 1000),
                        "100",
                        "101",
                        "99",
                        "100.5",
                        "1",
                        int(close_time.timestamp() * 1000),
                        "100",
                        10,
                    ]
                )
            return parse_klines(payload, symbol=symbol, interval=interval)

    monkeypatch.setattr("polymarket_btc_bot.cli.main.BinanceHistoricalKlineClient", lambda: FakeHistoryClient())

    assert (
        main(
            [
                "btc-history-bulk",
                "--start",
                "2026-07-01",
                "--end",
                "2026-07-02",
                "--limit",
                "100",
                "--max-pages",
                "2",
                "--output",
                str(history_path),
                "--training-output",
                str(training_path),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert history_path.exists()
    assert training_path.exists()
    assert '"history"' in output
    assert '"training"' in output
    assert '"train_ready_rows"' in output


def test_btc_training_builds_csv_from_existing_history(capsys, tmp_path):
    from datetime import UTC, datetime, timedelta

    from polymarket_btc_bot.adapters.reference_feeds import parse_klines, write_klines_jsonl

    history_path = tmp_path / "history.jsonl"
    training_path = tmp_path / "training.csv"
    start = datetime(2026, 7, 1, tzinfo=UTC)
    payload = []
    for index in range(16):
        open_time = start + timedelta(minutes=5 * index)
        close_time = open_time + timedelta(minutes=5) - timedelta(milliseconds=1)
        payload.append(
            [
                int(open_time.timestamp() * 1000),
                "100",
                "101",
                "99",
                "100.5",
                "1",
                int(close_time.timestamp() * 1000),
                "100",
                10,
            ]
        )
    write_klines_jsonl(parse_klines(payload, symbol="BTCUSDT", interval="5m"), history_path)

    assert main(["btc-training", str(history_path), "--output", str(training_path)]) == 0

    output = capsys.readouterr().out
    assert training_path.exists()
    assert '"rows": 16' in output
    assert '"train_ready_rows"' in output


def test_btc_model_eval_prints_walk_forward_report(capsys, tmp_path):
    import csv

    from polymarket_btc_bot.research.btc_model import FEATURE_COLUMNS

    training_path = tmp_path / "training.csv"
    fieldnames = ["open_time", "train_ready", "label_next_1_up", *FEATURE_COLUMNS]
    with training_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index in range(30):
            label_up = index % 2 == 0
            signal = 10.0 if label_up else -10.0
            writer.writerow(
                {
                    "open_time": f"2024-01-01T00:{index:02d}:00+00:00",
                    "train_ready": "True",
                    "label_next_1_up": "True" if label_up else "False",
                    "return_bps": signal,
                    "abs_return_bps": abs(signal),
                    "range_bps": abs(signal) + 2.0,
                    "upper_wick_bps": 1.0 if label_up else 3.0,
                    "lower_wick_bps": 3.0 if label_up else 1.0,
                    "close_to_close_return_bps": signal,
                    "rolling_12_mean_abs_return_bps": abs(signal),
                    "rolling_12_realized_range_bps": abs(signal) + 5.0,
                    "volume": 100.0 + index,
                    "quote_volume": 1000.0 + index,
                    "trade_count": 10 + index,
                }
            )

    assert (
        main(
            [
                "btc-model-eval",
                str(training_path),
                "--min-train-rows",
                "10",
                "--min-evaluation-rows",
                "10",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert '"evaluated_rows": 20' in output
    assert '"decision": "candidate_signal_not_execution_edge"' in output


def test_wallet_daily_opportunities_cli_prints_report(capsys, tmp_path):
    import json

    activity_path = tmp_path / "activity.jsonl"
    positions_path = tmp_path / "positions.jsonl"
    activity = []
    positions = []
    base_ts = 1_783_008_000
    for index in range(3):
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
                "realizedPnl": 5,
                "endDate": "2026-07-01",
            }
        )
    activity_path.write_text("\n".join(json.dumps(row) for row in activity) + "\n", encoding="utf-8")
    positions_path.write_text("\n".join(json.dumps(row) for row in positions) + "\n", encoding="utf-8")

    assert (
        main(
            [
                "wallet-daily-opportunities",
                "--wallet",
                "sample",
                str(activity_path),
                str(positions_path),
                "--min-support",
                "3",
                "--min-days",
                "3",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert '"opportunities"' in output
    assert '"daily_time_opportunities"' in output
    assert '"wallet_summaries"' in output
    assert '"sample"' in output


def test_btc_pattern_scan_prints_ranked_patterns(capsys, tmp_path):
    import csv
    from datetime import UTC, datetime, timedelta

    training_path = tmp_path / "training.csv"
    fieldnames = [
        "open_time",
        "train_ready",
        "return_bps",
        "abs_return_bps",
        "range_bps",
        "upper_wick_bps",
        "lower_wick_bps",
        "close_to_close_return_bps",
        "rolling_12_mean_abs_return_bps",
        "rolling_12_realized_range_bps",
        "label_next_1_return_bps",
        "label_next_1_up",
        "label_next_3_return_bps",
        "label_next_3_up",
        "label_next_12_return_bps",
        "label_next_12_up",
    ]
    start = datetime(2024, 1, 1, tzinfo=UTC)
    with training_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index in range(24):
            open_time = start + timedelta(minutes=5 * index)
            writer.writerow(
                {
                    "open_time": open_time.isoformat(),
                    "train_ready": "True",
                    "return_bps": "3.0",
                    "abs_return_bps": "3.0",
                    "range_bps": "8.0",
                    "upper_wick_bps": "1.0",
                    "lower_wick_bps": "3.0",
                    "close_to_close_return_bps": "3.0",
                    "rolling_12_mean_abs_return_bps": "3.0",
                    "rolling_12_realized_range_bps": "10.0",
                    "label_next_1_return_bps": "2.0",
                    "label_next_1_up": "True",
                    "label_next_3_return_bps": "2.0",
                    "label_next_3_up": "True",
                    "label_next_12_return_bps": "2.0",
                    "label_next_12_up": "True",
                }
            )

    assert main(["btc-pattern-scan", str(training_path), "--min-support", "1", "--top", "3"]) == 0

    output = capsys.readouterr().out
    assert '"patterns"' in output
    assert '"baseline"' in output


def test_paper_run_loop_flag_runs_iterations(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    assert (
        main(["paper-run", "--iterations", "2", "--market-data", "demo", "--no-audit", "--interval", "0.1"])
        == 0
    )

    output = capsys.readouterr().out
    assert '"action"' in output
    assert '"execution_status"' in output


def test_dashboard_performance_endpoint(capsys, monkeypatch, tmp_path):
    from polymarket_btc_bot.dashboard.server import build_performance_report
    monkeypatch.chdir(tmp_path)

    report = build_performance_report(candle_map={})
    assert report["total_decisions"] == 0
    assert report["total_trades"] == 0
    assert report["recent_decisions"] == []
    assert report["estimated_pnl"] == 0.0
    assert report["resolved_trades"] == 0
    assert report["win_rate"] == 0.0
    assert report["equity_curve"] == []


def test_performance_report_equity_and_pnl(tmp_path):
    from polymarket_btc_bot.audit import AuditLog
    from polymarket_btc_bot.dashboard.server import build_performance_report

    audit_path = tmp_path / "paper-decisions.jsonl"
    log = AuditLog(audit_path)
    # Two trades in two different closed 5m cycles resolved against real candles.
    cycle_a_start = "2026-07-03T08:00:00+00:00"  # candle a: close > open -> UP wins
    cycle_b_start = "2026-07-03T08:05:00+00:00"  # candle b: close < open -> UP loses
    log.append(
        {
            "event_type": "paper_decision",
            "observed_ts": "2026-07-03T08:02:00+00:00",
            "market": {"start_ts": cycle_a_start},
            "summary": {"action": "BUY_UP", "target_price": 0.10},
            "decision": {"reason": "baseline_edge_up"},
            "execution": {"status": "FILLED", "fill": {"price": 0.10, "shares": 250.0, "notional": 25.0}},
        }
    )
    log.append(
        {
            "event_type": "paper_decision",
            "observed_ts": "2026-07-03T08:07:00+00:00",
            "market": {"start_ts": cycle_b_start},
            "summary": {"action": "BUY_UP", "target_price": 0.10},
            "decision": {"reason": "baseline_edge_up"},
            "execution": {"status": "FILLED", "fill": {"price": 0.10, "shares": 250.0, "notional": 25.0}},
        }
    )

    import datetime as _dt

    a_epoch = int(_dt.datetime.fromisoformat(cycle_a_start).timestamp())
    b_epoch = int(_dt.datetime.fromisoformat(cycle_b_start).timestamp())
    candle_map = {
        a_epoch: (100.0, 101.0, a_epoch + 300),  # close > open -> UP wins -> +225
        b_epoch: (100.0, 99.0, b_epoch + 300),   # close < open -> UP loses -> -25
    }

    report = build_performance_report(audit_path, candle_map=candle_map)
    assert report["resolved_trades"] == 2
    assert report["wins"] == 1
    assert report["losses"] == 1
    assert report["estimated_pnl"] == 200.0
    assert report["win_rate"] == 0.5
    assert report["pending_trades"] == 0
    assert len(report["equity_curve"]) == 2
    assert report["equity_curve"][-1]["equity"] == 200.0


def test_performance_report_pending_when_candle_open(tmp_path):
    from polymarket_btc_bot.audit import AuditLog
    from polymarket_btc_bot.dashboard.server import build_performance_report
    import datetime as _dt

    audit_path = tmp_path / "paper-decisions.jsonl"
    log = AuditLog(audit_path)
    start = "2026-07-03T08:00:00+00:00"
    log.append(
        {
            "event_type": "paper_decision",
            "observed_ts": "2026-07-03T08:02:00+00:00",
            "market": {"start_ts": start},
            "summary": {"action": "BUY_UP", "target_price": 0.10},
            "decision": {"reason": "baseline_edge_up"},
            "execution": {"status": "FILLED", "fill": {"price": 0.10, "shares": 250.0, "notional": 25.0}},
        }
    )
    epoch = int(_dt.datetime.fromisoformat(start).timestamp())
    # Candle close far in the future -> trade is still pending, no P&L yet.
    future = _dt.datetime.now(tz=_dt.UTC).timestamp() + 10_000
    report = build_performance_report(audit_path, candle_map={epoch: (100.0, 101.0, future)})
    assert report["resolved_trades"] == 0
    assert report["pending_trades"] == 1
    assert report["estimated_pnl"] == 0.0
