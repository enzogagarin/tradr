# Polymarket BTC 5m Trading Bot

Research and implementation workspace for a BTC Up/Down 5 minute Polymarket trading bot.

## Goal

Build the system in stages:

1. Collect clean market, oracle, and exchange data.
2. Prove whether a measurable edge exists with leakage-safe backtests.
3. Run paper trading with realistic fill simulation.
4. Only then enable small-size live execution with strict risk limits.

## Current Phase

Phase 2: paper analyst, simulated execution, audit logging, risk validation, and operator dashboard.

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
polymarket-btc-bot --help
polymarket-btc-bot dashboard
```

Dashboard URL:

```text
http://127.0.0.1:8787
```

The app defaults to paper mode. Live mode will fail startup unless explicit credentials and limits are configured.

## CLI

```bash
polymarket-btc-bot config
polymarket-btc-bot snapshot
polymarket-btc-bot dashboard
polymarket-btc-bot discover-markets
polymarket-btc-bot btc-tick
polymarket-btc-bot paper-run --iterations 1 --market-data auto
polymarket-btc-bot paper-run
polymarket-btc-bot audit-tail --limit 5
polymarket-btc-bot collect --iterations 3 --interval 2 --market-data auto
polymarket-btc-bot raw-tail --limit 10
polymarket-btc-bot quality-report
polymarket-btc-bot feature-snapshots --raw-path data/raw/YYYY-MM-DD/events.jsonl
polymarket-btc-bot btc-history --start 2026-07-01 --end 2026-07-02 --interval 5m
polymarket-btc-bot btc-history-bulk --start 2024-01-01 --end 2025-01-01 --interval 5m
polymarket-btc-bot btc-history-report data/history/btcusdt-5m-2026-07-01-2026-07-02.jsonl
polymarket-btc-bot btc-training data/history/btcusdt-5m-2024.jsonl
polymarket-btc-bot btc-model-eval data/training/btcusdt-5m-2024-training.csv
polymarket-btc-bot btc-pattern-scan data/training/btcusdt-5m-2024-training.csv data/training/btcusdt-5m-2025-training.csv
polymarket-btc-bot wallet-collect --user 0x27091ce48a08a3e21d63c42d33428cf1e55d20f5 --label dgcf
polymarket-btc-bot wallet-report --activity-path data/wallets/dgcf-activity.jsonl --positions-path data/wallets/dgcf-positions.jsonl
```

`paper-run` runs the paper analyst: it selects a market, reads BTC top-of-book data, computes a baseline probability/edge decision, validates the order intent against risk limits, simulates paper execution, and writes a local JSONL audit event unless `--no-audit` is supplied. It never calls live order placement.

`collect` writes raw JSONL events to `data/raw/YYYY-MM-DD/events.jsonl`. Each collection cycle emits BTC tick, market state, both orderbooks, paper decision, risk validation, and paper execution events. This is the first time-series data path for later replay, quality checks, and backtesting.

`quality-report` summarizes raw event coverage and refuses to call demo/fallback-only data replay-ready. It reports event counts, market counts, live/demo ratios, complete cycle estimates, and blocking reasons such as `no_live_market_events`.

`feature-snapshots` converts raw event cycles into point-in-time CSV rows for research. Demo/fallback market state or non-live orderbooks are exported but marked `replay_ready=false`, so downstream evaluation cannot accidentally treat synthetic data as live edge evidence.

`btc-history` downloads Binance Spot kline/candlestick history into JSONL and prints a movement distribution report. This is for baseline volatility and BTC regime analysis; it does not prove Polymarket execution edge by itself.

`btc-history-bulk` paginates Binance history over larger ranges, writes organized JSONL under `data/history`, builds a training CSV under `data/training`, and writes a manifest next to the dataset. `btc-training` rebuilds the CSV from an existing history JSONL. Training rows separate current-bar features from forward labels (`label_next_1`, `label_next_3`, `label_next_12`) to avoid future leakage.

`btc-model-eval` runs a leakage-safe walk-forward evaluation over the BTC training CSV. It trains only on prior rows, compares a simple feature-correlation signal against a rolling up-rate baseline, and reports accuracy, Brier score, log loss, and a conservative verdict. A `candidate_signal_not_execution_edge` verdict means the BTC-only signal deserves deeper research; it still does not prove Polymarket edge after spread, fees, latency, and fills.

`btc-pattern-scan` ranks interpretable BTC regimes and candle patterns across one or more training CSVs. It groups rows by current direction, 15m/1h trend, volatility regime, range regime, wick rejection, hour, weekday, and selected combinations, then reports support, up-rate delta, forward-return delta, and a rough t-stat. Use it to discover candidate patterns before building a stronger model; do not treat a pattern as tradable until it survives year-by-year validation and Polymarket execution simulation.

`wallet-collect` and `wallet-report` capture public Polymarket wallet activity/positions and summarize copy-trading research features such as market concentration, asset mix, interval mix, price buckets, activity cashflow, redemption totals, and position snapshot PnL. Position PnL is explicitly treated as a snapshot; reconcile activity, redeems, merges, and positions before making any copy-trading claim.

Market data modes:

- `demo`: local deterministic demo market and book.
- `auto`: try live Gamma/CLOB first, then clearly marked demo fallback if no live BTC 5m market is found.
- `live`: require live Gamma/CLOB data; unavailable live data blocks trading instead of pretending demo books are real.

Make targets:

```bash
make setup
make test
make dashboard
```

Configuration starts from `.env.example`. Do not put live keys in tracked files.

## Documents

- `docs/master-plan.md`: consolidated implementation plan.
- `tasks/backlog.md`: task board and first implementation tickets.
- `docs/subagents/`: subagent research reports.
