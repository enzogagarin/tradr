# Polymarket BTC 5m Bot Master Plan

## Principles

- Treat the market as a binary option plus orderbook microstructure problem, not a generic BTC direction model.
- Train labels from the actual resolution source whenever possible.
- Keep raw event logs immutable.
- Every feature row must respect point-in-time availability.
- Do not write live execution before data collection, labeling, and replay backtesting are credible.

## Source Research

Subagent research outputs:

- `docs/subagents/api-sdk-research.md`
- `docs/subagents/data-architecture.md`
- `docs/subagents/quant-backtest-plan.md`
- `docs/subagents/engineering-backlog.md`

Key decisions from the research:

- Use Gamma REST for market discovery and CLOB REST/WebSocket for orderbook, prices, and eventual execution.
- Keep Polymarket access behind internal adapters because the unified Python SDK is new/beta and `py-clob-client-v2` may be needed as execution fallback.
- Use Chainlink Data Streams as the preferred settlement-aligned BTC reference when credentials/feed ID are available.
- Use Binance, Coinbase, and optionally OKX as exchange reference feeds for momentum, volatility, basis, and sanity checks.
- Use PostgreSQL as the MVP system of record, with raw JSONB payloads and normalized tables. Add ClickHouse/Timescale only after measured pressure.
- Default to paper mode. Live mode requires explicit opt-in, credentials, risk limits, cancel paths, and kill switch.

## Workstreams

1. API and SDK integration
2. Data collection and storage
3. Feature engineering and labeling
4. Baseline model and calibration
5. Orderbook replay backtester
6. Paper trading
7. Live execution and risk controls

## MVP Milestones

### M0: Repo And Integration Decisions

- Pick implementation stack.
- Confirm Polymarket SDK and auth path.
- Confirm Chainlink Data Streams access path.
- Define event schemas.
- Create adapter interfaces:
  - `PolymarketDiscovery`
  - `PolymarketMarketData`
  - `PolymarketExecution`
  - `ReferencePriceFeed`

### M1: Read-Only Data Collector

- Discover active BTC 5m markets.
- Subscribe to Polymarket market WebSocket.
- Subscribe to BTC exchange market streams.
- Pull Chainlink BTC/USD reports.
- Persist raw events with local receive timestamps.
- Data quality gates:
  - Source and observed timestamps recorded.
  - Heartbeat gaps detected.
  - Stale or malformed payloads quarantined or rejected.

### M2: Labels And Features

- Resolve completed market outcomes.
- Build time-aligned feature snapshots.
- Export training datasets.
- Enforce `snapshot_ts < label_cutoff_ts`.
- Use `feature_version` and `label_version`.

### M3: Baseline Model

- Implement probabilistic `P(up)` baseline.
- Calibrate with logistic regression or LightGBM.
- Produce calibration and edge reports.
- Baseline must compare against coin flip, distance-only, random-walk volatility, and Polymarket midpoint.

### M4: Replay Backtest

- Replay historical orderbook and price events.
- Simulate latency, slippage, partial fills, and cancels.
- Evaluate net EV by edge bucket.
- Test p50, p90, and pessimistic latency.
- Reject any strategy whose edge disappears under conservative fills.

### M5: Paper Trader

- Run live read-only decisions.
- Log trade and no-trade reasons.
- Compare predicted EV against simulated fills.
- Paper output must be replayable offline from captured data.

### M6: Limited Live Trader

- Add authenticated execution.
- Enforce max daily loss, per-market risk, stale data filters, and kill switch.
- Start with tiny limits only after paper evidence is positive.

## First Strategy

Start with late-window long-only mispricing detection:

- Evaluate only active 5 minute BTC markets.
- Trade only in configurable windows, likely `90s` to `10s` before close during research.
- Estimate `P(up)` from distance to reference, short-horizon volatility, momentum, and orderbook context.
- Compare fair probability against executable ask prices:
  - `buy_up_edge = P(up) - ask_up`
  - `buy_down_edge = (1 - P(up)) - ask_down`
- Enter only when net edge clears costs, slippage, adverse selection buffer, and model uncertainty buffer.
- Hard no-trade filters for stale Chainlink/exchange data, stale Polymarket book, wide spread, low depth, unknown strike/reference, final safety window, and probability outside calibrated support.

## Go/No-Go Gates

Proceed to paper trading only when:

- Full orderbook replay is deterministic enough to reproduce decisions.
- Out-of-sample calibration beats random-walk baseline and Polymarket midpoint benchmark.
- Net EV remains positive after fees, slippage, latency, and conservative fills.
- Profit is not dominated by one day, one regime, or the best 1 percent of trades.

Proceed to limited live only when:

- 2-4 weeks of paper trading show positive expected value by the same metrics.
- Real-time decisions match offline replay of the same captured data.
- Risk caps, daily stop, stale-feed filters, cancel-all, per-market cancel, and kill switch are implemented and tested.

## Immediate Next Build Order

1. Scaffold codebase, config, typed models, and tests.
2. Implement Gamma discovery for BTC 5m markets.
3. Implement CLOB read-only orderbook and price fetching.
4. Implement Polymarket market WebSocket recorder.
5. Implement Binance BTCUSDT trade/bookTicker collector.
6. Add Chainlink collector stub with auth placeholders and exact feed ID config.
7. Persist raw events in PostgreSQL, plus optional JSONL archive.
8. Generate labels and feature snapshots.
9. Implement baseline probability and calibration reports.
10. Implement orderbook replay and paper execution.
