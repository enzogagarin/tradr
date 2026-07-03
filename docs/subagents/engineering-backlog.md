# Polymarket BTC Up/Down 5m Bot Engineering Backlog

## Scope

Build an MVP trading bot for Polymarket BTC Up/Down 5-minute markets, step by step. The MVP should discover active BTC 5m markets, ingest price and market data, generate a simple deterministic signal, place tightly controlled orders, track positions, and run safely in paper mode before live trading.

This backlog is engineering-focused only. It does not define a profitable strategy, investment advice, custody policy, or production operations beyond the minimum controls needed to test safely.

## MVP Principles

- Paper trading is the default mode.
- Live trading requires explicit configuration and hard risk limits.
- Every decision must be observable after the fact.
- Market discovery and order placement must tolerate missing, stale, or inconsistent external data.
- The first strategy should be intentionally simple so the infrastructure can be validated before strategy complexity grows.

## Epics

### Epic 1: Project Foundation

Tasks:

- Scaffold the `polymarket-btc-bot` repository with a clear app layout.
- Define runtime configuration for environments, credentials, feature flags, and risk limits.
- Add structured logging, error handling conventions, and basic CLI entrypoints.
- Add unit test and lint/type-check commands.

Acceptance Criteria:

- A developer can run setup, tests, and the bot CLI from a clean checkout.
- Secrets are loaded from environment variables or local ignored files only.
- Paper mode is enabled unless live mode is explicitly selected.
- Logs include timestamp, component, market id when available, and decision/order correlation ids.

Dependencies:

- None.

### Epic 2: Polymarket Market Data Integration

Tasks:

- Implement a Polymarket client for market discovery, order book reads, and order status reads.
- Identify BTC Up/Down 5m markets from available metadata.
- Normalize market records into internal models with start time, end time, outcome tokens, tick size, and minimum order data.
- Handle pagination, rate limits, retries, and temporary API failures.

Acceptance Criteria:

- The bot can list current and upcoming BTC 5m markets.
- The bot rejects markets that are expired, ambiguous, missing token ids, or outside configured time windows.
- API failures are retried with bounded backoff and surfaced as structured errors.
- Integration tests can run against mocked API responses.

Dependencies:

- Epic 1.

### Epic 3: BTC Price Feed

Tasks:

- Implement a BTC/USD price feed abstraction.
- Add at least one exchange-backed implementation suitable for low-latency 5m decisioning.
- Normalize price ticks with source, timestamp, bid/ask or last price, and staleness metadata.
- Add safeguards for stale, missing, or outlier price data.

Acceptance Criteria:

- The strategy can request the latest BTC reference price through a stable interface.
- Stale data prevents new entries and emits a clear risk event.
- Price feed behavior is covered with mocked unit tests.
- The feed implementation can be swapped without changing strategy code.

Dependencies:

- Epic 1.

### Epic 4: Market State and Scheduling

Tasks:

- Build a market lifecycle scheduler for 5-minute rounds.
- Track active, soon-to-open, nearing-close, and settled market states.
- Maintain in-memory state for current market, order attempts, fills, and open exposure.
- Persist enough state locally to recover after process restart.

Acceptance Criteria:

- The bot knows which market is tradable at any point in time.
- The bot avoids placing new orders after the configured cutoff before market close.
- A restart does not forget active orders or open positions known before shutdown.
- Scheduler behavior is tested with fixed clocks.

Dependencies:

- Epic 2.
- Epic 3.

### Epic 5: Strategy MVP

Tasks:

- Define a strategy interface that receives normalized market state and price feed data.
- Implement a simple baseline signal for BTC Up/Down markets.
- Add confidence, no-trade, and max-price thresholds.
- Emit a full decision record for every market evaluation.

Acceptance Criteria:

- Strategy can return `BUY_UP`, `BUY_DOWN`, or `NO_TRADE`.
- Strategy never produces orders when market data or price data is stale.
- Strategy decisions include inputs, thresholds, selected side, target price, and reason.
- Unit tests cover buy, no-trade, stale-data, and threshold edge cases.

Dependencies:

- Epic 3.
- Epic 4.

### Epic 6: Execution Engine

Tasks:

- Build an execution interface with paper and live implementations.
- Implement paper order simulation using current order book snapshots.
- Implement live order placement behind an explicit feature flag.
- Add order sizing, limit price handling, idempotency keys, and order status polling.
- Add cancellation support for unfilled or stale orders.

Acceptance Criteria:

- Paper mode can simulate fills and rejections deterministically.
- Live mode cannot start unless credentials, chain configuration, and risk limits are present.
- Duplicate decision processing cannot place duplicate orders.
- Orders are cancelled when they exceed configured age or market cutoff rules.

Dependencies:

- Epic 2.
- Epic 4.
- Epic 5.

### Epic 7: Risk Controls

Tasks:

- Implement global and per-market risk limits.
- Add maximum order size, maximum open exposure, maximum daily loss, and maximum trades per day.
- Add kill switch configuration.
- Add pre-trade validation before any order reaches the execution engine.

Acceptance Criteria:

- Every order candidate passes through risk validation.
- Risk rejections are logged with machine-readable reasons.
- Kill switch prevents all new entries while allowing status polling and cancellation.
- Unit tests cover each risk limit.

Dependencies:

- Epic 1.
- Epic 6.

### Epic 8: Persistence and Audit Trail

Tasks:

- Store market snapshots, price ticks used for decisions, decisions, orders, fills, and risk events.
- Pick a simple MVP storage layer such as SQLite or append-only JSONL.
- Add query helpers for recent decisions and daily PnL.
- Ensure sensitive values are never written to audit logs.

Acceptance Criteria:

- A completed paper-trading session can be reviewed from local persisted records.
- Decision records can be joined to order and fill records by correlation id.
- Restart recovery can load active order and exposure state.
- Tests verify write/read behavior for core records.

Dependencies:

- Epic 4.
- Epic 5.
- Epic 6.

### Epic 9: Observability and Operator UX

Tasks:

- Add CLI commands for `discover-markets`, `paper-run`, `live-run`, `status`, and `replay`.
- Add concise terminal output for current market, signal, exposure, and recent orders.
- Add health checks for API connectivity, price feed freshness, and storage.
- Add error summaries for failed cycles.

Acceptance Criteria:

- An operator can run the bot in paper mode and understand its current state from logs and CLI output.
- Health checks fail clearly when required external services are unavailable.
- Replay mode can load stored decisions for debugging.
- CLI commands have documented required environment variables.

Dependencies:

- Epic 2.
- Epic 3.
- Epic 8.

### Epic 10: Safety Review and MVP Readiness

Tasks:

- Add a live-readiness checklist.
- Run paper trading through multiple market cycles.
- Document known risks, unsupported cases, and manual emergency steps.
- Add final smoke tests for startup, market discovery, paper execution, restart recovery, and kill switch.

Acceptance Criteria:

- MVP cannot be marked live-ready until checklist items pass.
- Paper run evidence includes at least several complete 5m market cycles.
- Known limitations are documented in the repo.
- A live run requires a deliberate config change and visible startup warning.

Dependencies:

- Epics 1-9.

## Cross-Epic Dependencies

- Strategy and execution depend on reliable normalized market and price data.
- Live execution depends on risk controls, persistence, and operator visibility.
- Restart recovery depends on persistence before long-running paper tests.
- Observability should be added early enough to debug market discovery and execution behavior.

## First 10 Implementation Tickets

### Ticket 1: Scaffold Repository and Tooling

Description:

Create the initial app structure, dependency manifest, test runner, lint/type-check commands, and a basic CLI shell for the bot.

Acceptance Criteria:

- `README.md` explains local setup and paper-mode default.
- `src` and `tests` directories exist with a minimal passing test.
- CLI exposes a help command and exits cleanly.
- No secrets or local env files are committed.

Dependencies:

- None.

### Ticket 2: Define Core Domain Models

Description:

Create typed models for markets, outcomes, order books, price ticks, strategy decisions, order intents, orders, fills, and risk events.

Acceptance Criteria:

- Models capture timestamps, source metadata, and correlation ids.
- Invalid market or order objects fail validation.
- Unit tests cover representative valid and invalid records.

Dependencies:

- Ticket 1.

### Ticket 3: Add Configuration Loader

Description:

Implement configuration loading for paper/live mode, API endpoints, credentials references, strategy thresholds, and risk limits.

Acceptance Criteria:

- Paper mode is the default when no mode is set.
- Live mode requires explicit opt-in.
- Missing live credentials fail startup before any trading loop begins.
- Tests cover default, paper, and live config validation.

Dependencies:

- Ticket 1.
- Ticket 2.

### Ticket 4: Implement Polymarket Market Discovery Client

Description:

Build the first Polymarket client method to fetch and normalize BTC Up/Down 5m markets.

Acceptance Criteria:

- Client returns normalized market models for active or upcoming BTC 5m markets.
- Ambiguous or incomplete markets are skipped with logged reasons.
- Mocked tests cover successful discovery, empty results, pagination, and malformed records.

Dependencies:

- Ticket 2.
- Ticket 3.

### Ticket 5: Add Order Book Read Support

Description:

Extend the Polymarket client to fetch and normalize order books for selected market outcome tokens.

Acceptance Criteria:

- Order book includes bids, asks, midpoint when computable, and source timestamp.
- Empty or stale books prevent trade decisions.
- Tests cover normal, empty, crossed, and malformed books.

Dependencies:

- Ticket 4.

### Ticket 6: Implement BTC Price Feed Interface and First Provider

Description:

Add the price feed abstraction and a first BTC/USD provider implementation with freshness checks.

Acceptance Criteria:

- Strategy-facing interface returns a normalized latest price tick.
- Provider errors and stale ticks are represented explicitly.
- Tests cover fresh, stale, missing, and outlier price scenarios.

Dependencies:

- Ticket 2.
- Ticket 3.

### Ticket 7: Build Fixed-Clock Market Scheduler

Description:

Implement scheduler logic that selects the tradable market and enforces entry cutoffs based on market open and close times.

Acceptance Criteria:

- Scheduler identifies current, next, and closed markets.
- Scheduler blocks entries after configured cutoff before close.
- Fixed-clock tests cover market boundaries and restart-like state reload input.

Dependencies:

- Ticket 4.
- Ticket 6.

### Ticket 8: Implement Baseline Strategy

Description:

Create the first deterministic strategy returning `BUY_UP`, `BUY_DOWN`, or `NO_TRADE` from market state, order book, and BTC price feed input.

Acceptance Criteria:

- Strategy emits a decision record on every evaluation.
- Stale market data, stale price data, low confidence, or high target price returns `NO_TRADE`.
- Unit tests cover both sides, no-trade cases, and threshold boundaries.

Dependencies:

- Ticket 5.
- Ticket 6.
- Ticket 7.

### Ticket 9: Add Risk Validation Layer

Description:

Implement pre-trade risk checks for order size, per-market exposure, daily exposure, daily loss placeholder, trade count, and kill switch.

Acceptance Criteria:

- All order intents must pass risk validation before execution.
- Rejections include a clear reason code.
- Kill switch blocks new entries.
- Unit tests cover each configured limit.

Dependencies:

- Ticket 3.
- Ticket 8.

### Ticket 10: Implement Paper Execution and Audit Logging

Description:

Add paper execution using order book snapshots and persist decisions, order intents, simulated orders, fills, and risk events.

Acceptance Criteria:

- Paper execution never calls live order placement.
- Simulated fills are deterministic from supplied order book data.
- Audit records can be read back by correlation id.
- A smoke test runs discovery-to-decision-to-paper-order with mocked external data.

Dependencies:

- Ticket 5.
- Ticket 8.
- Ticket 9.

## MVP Done Definition

- Bot runs in paper mode across multiple BTC 5m market cycles.
- Market discovery, price feed, strategy, risk validation, paper execution, and audit logging are connected.
- Restart recovery preserves enough state to avoid duplicate order attempts.
- Live mode is present only behind explicit config, hard risk limits, and a visible startup warning.
- Tests cover core model validation, market discovery normalization, price feed freshness, scheduler boundaries, strategy decisions, risk checks, and paper execution.
