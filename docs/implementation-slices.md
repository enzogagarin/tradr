# Implementation Slices

This splits the project into subagent-friendly work packages. Each slice has a disjoint primary ownership area to reduce conflicts.

## Slice 1: Foundation

Owner area:

- `pyproject.toml` or package manifest
- `src/polymarket_btc_bot/config/`
- `src/polymarket_btc_bot/domain/`
- `tests/unit/`

Deliverables:

- Config loader.
- Domain models.
- Test harness.
- CLI shell.

## Slice 2: Polymarket Read-Only Adapters

Owner area:

- `src/polymarket_btc_bot/adapters/polymarket/`
- `tests/adapters/polymarket/`

Deliverables:

- Gamma market discovery.
- CLOB book/price read client.
- Market WebSocket recorder.
- Mocked tests.

## Slice 3: Reference Price Feeds

Owner area:

- `src/polymarket_btc_bot/adapters/reference_feeds/`
- `tests/adapters/reference_feeds/`

Deliverables:

- Binance provider first.
- Coinbase/OKX optional providers.
- Chainlink collector stub and HMAC auth placeholder.
- Normalized BTC tick model usage.

## Slice 4: Storage And Dataset

Owner area:

- `src/polymarket_btc_bot/storage/`
- `migrations/`
- `tests/storage/`

Deliverables:

- PostgreSQL schema.
- Raw event writer.
- Normalized market/orderbook/tick writers.
- Feature snapshot and label builders.

## Slice 5: Strategy And Backtest

Owner area:

- `src/polymarket_btc_bot/strategy/`
- `src/polymarket_btc_bot/backtest/`
- `tests/strategy/`
- `tests/backtest/`

Deliverables:

- Baseline probability model.
- Strategy rule engine.
- Orderbook replay.
- Fill and latency simulation.

## Slice 6: Paper Trading And Risk

Owner area:

- `src/polymarket_btc_bot/execution/`
- `src/polymarket_btc_bot/risk/`
- `tests/execution/`
- `tests/risk/`

Deliverables:

- Paper execution.
- Risk validator.
- Audit log records.
- Live execution interface, disabled by default.

