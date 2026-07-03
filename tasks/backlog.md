# Task Board

## Status Legend

- `todo`: not started
- `doing`: active
- `blocked`: waiting on dependency or credential
- `done`: completed

## Epic A: Project Foundation

- A1 `done`: Select stack and repository layout.
- A2 `doing`: Add configuration and secrets handling.
- A3 `todo`: Add structured logging and run IDs.
- A4 `done`: Add docs for local setup.

## Epic B: Market Discovery

- B1 `done`: Query Gamma API for BTC Up/Down 5m markets.
- B2 `done`: Normalize market metadata.
- B3 `todo`: Persist market lifecycle states.

## Epic C: Raw Data Collection

- C1 `todo`: Polymarket market WebSocket collector.
- C2 `done`: Polymarket CLOB snapshot fetcher.
- C3 `blocked`: Chainlink BTC/USD collector. Needs Data Streams credentials and full feed ID.
- C4 `done`: BTC exchange stream and historical kline collector.
- C5 `done`: Raw event writer.

## Epic D: Dataset And Labels

- D1 `todo`: Outcome resolver.
- D2 `done`: Point-in-time feature snapshot builder.
- D3 `done`: Data quality reports.
- D4 `todo`: Dataset export.

## Epic E: Modeling

- E1 `todo`: Brownian baseline probability model.
- E2 `todo`: Calibration model.
- E3 `todo`: Model evaluation script.
- E4 `todo`: Model artifact registry.

## Epic F: Backtesting

- F1 `todo`: Orderbook replay engine.
- F2 `todo`: Fill and latency simulator.
- F3 `todo`: Strategy rules engine.
- F4 `todo`: Backtest report.

## Epic G: Paper And Live Trading

- G1 `doing`: Paper trader loop.
- G2 `todo`: Execution adapter.
- G3 `done`: Risk engine.
- G4 `todo`: Kill switch and monitoring.

## First 10 Tickets

### T1: Scaffold Repository And Tooling

Status: `done`

Acceptance criteria:

- `src` and `tests` exist.
- CLI help command exits cleanly.
- Paper mode is the default.
- No secrets are committed.

### T2: Define Core Domain Models

Status: `doing`

Acceptance criteria:

- Models exist for market, asset, orderbook, BTC tick, feature snapshot, decision, order intent, order, fill, and risk event.
- Invalid price, size, timestamp, or missing token IDs fail validation.
- Tests cover valid and invalid records.

### T3: Add Configuration Loader

Status: `doing`

Acceptance criteria:

- Supports mode, API endpoints, credentials references, thresholds, and risk limits.
- Live mode requires explicit opt-in and credentials.
- Tests cover default, paper, and live validation.

### T4: Implement Gamma Market Discovery Client

Status: `done`

Acceptance criteria:

- Returns normalized active/upcoming BTC 5m markets.
- Skips expired, ambiguous, or incomplete markets with reason logs.
- Mock tests cover success, empty results, pagination, and malformed records.

### T5: Add CLOB Orderbook Read Support

Status: `done`

Acceptance criteria:

- Fetches Up and Down books for selected token IDs.
- Computes best bid, best ask, midpoint, spread, and depth summaries.
- Empty, crossed, malformed, or stale books block trade decisions.

### T6: Implement BTC Price Feed Interface And Binance Provider

Status: `done`

Acceptance criteria:

- Provides normalized latest BTC price tick.
- Includes source timestamp, observed timestamp, bid, ask, price, and staleness.
- Tests cover fresh, stale, missing, and outlier ticks.

### T7: Build Fixed-Clock Market Scheduler

Status: `done`

Acceptance criteria:

- Identifies current, next, and closed markets.
- Blocks entries after configured cutoff before close.
- Fixed-clock tests cover market boundaries.

### T8: Implement Baseline Probability Strategy

Status: `done`

Acceptance criteria:

- Computes `P(up)` from distance to reference, volatility, and time to close.
- Emits `BUY_UP`, `BUY_DOWN`, or `NO_TRADE` with a full reason record.
- Stale data, low edge, wide spread, or final safety window returns `NO_TRADE`.

### T9: Add Risk Validation Layer

Status: `done`

Acceptance criteria:

- Validates every order intent before execution.
- Covers max order size, per-market exposure, daily exposure/loss placeholder, trade count, and kill switch.
- Rejections include machine-readable reason codes.

### T10: Implement Paper Execution And Audit Logging

Status: `done`

Acceptance criteria:

- Paper execution never calls live order placement.
- Simulated fills are deterministic from supplied orderbook state.
- Decisions, intents, orders, fills, and risk events are readable by correlation ID.

## Current Implementation Notes

- T7 market scheduler is implemented with fixed-clock tests.
- T8 baseline probability strategy is implemented with no-trade filters for stale data, spread, edge, invalid reference, and market cutoff state.
- `paper-run` now produces a read-only paper analyst decision summary.
- Dashboard `/api/snapshot` now uses the paper analyst snapshot instead of a hardcoded static snapshot.
- T9 risk validation is implemented before paper execution with kill switch, max order notional, max market exposure, daily loss placeholder, trade count, and market-open checks.
- T10 paper execution and JSONL audit logging are implemented for the paper analyst loop.
- Market data modes are implemented:
  - `demo` uses deterministic local market/book data.
  - `auto` attempts live Gamma/CLOB data and explicitly marks demo fallback when no live BTC 5m market is found.
  - `live` blocks trading when live Gamma/CLOB data is unavailable instead of falling back to demo books.
- Raw collector is implemented with `collect` and `raw-tail`. Each cycle writes BTC tick, market state, orderbook snapshots, paper decision, risk validation, and paper execution events to `data/raw/YYYY-MM-DD/events.jsonl`.
- Data quality reports are implemented with `quality-report`. Demo/fallback-only raw data is explicitly marked insufficient for replay/backtest research.
- Feature snapshots are implemented with `feature-snapshots`. Raw cycles are exported to point-in-time CSV rows, while demo/fallback or non-live books remain marked `replay_ready=false`.
- Binance historical kline collection is implemented with `btc-history`, `btc-history-bulk`, and `btc-history-report` for BTC 5m movement distribution and volatility baseline research.
- BTC training export is implemented with `btc-training`. The 2024 BTCUSDT 5m training dataset has 105,408 rows and 105,395 rows marked train-ready after forward-label checks.

## Credential/Access Blockers

- Chainlink Data Streams credentials and full BTC/USD feed ID.
- Polymarket wallet/private key and CLOB L2 API credentials for any live execution.
- Decision on primary Polymarket SDK after a short spike.

## Subagent Outputs To Consult

- API details: `docs/subagents/api-sdk-research.md`
- Schemas: `docs/subagents/data-architecture.md`
- Quant/backtest: `docs/subagents/quant-backtest-plan.md`
- Engineering backlog: `docs/subagents/engineering-backlog.md`
