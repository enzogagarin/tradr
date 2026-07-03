# Polymarket BTC Up/Down 5m Data Architecture

## Scope

This document defines the data architecture and schemas for an MVP Polymarket BTC Up/Down 5m trading bot. It covers ingestion contracts, normalized storage, feature snapshots, labels, timestamp handling, and data quality checks. It does not define trading strategy, model selection, execution logic, or risk limits.

The target market family is the recurring 5-minute BTC Up/Down binary market. Each market asks whether BTC will close above or below a reference price over a 5-minute interval.

## Storage Choice For MVP

Use **PostgreSQL** as the MVP system of record.

Rationale:

- Strong constraints and indexes for market windows, assets, events, snapshots, and labels.
- Good enough write throughput for 5-minute markets, CLOB events, and BTC reference ticks.
- Simple local development and production migration path.
- Native JSONB support for raw event payloads without losing source fidelity.
- Easy analytical export to Parquet later.

Recommended MVP layout:

- PostgreSQL for raw events, normalized tables, feature snapshots, labels, and model-ready datasets.
- Local compressed JSONL archive for optional raw event backup.
- Add TimescaleDB or ClickHouse only if PostgreSQL becomes a measured bottleneck.

## Timestamp Strategy

Use UTC everywhere. Store all timestamps as `TIMESTAMPTZ` in PostgreSQL and ISO-8601 UTC strings in raw JSON.

Timestamp fields:

- `source_ts`: Timestamp supplied by the source system, if available.
- `observed_ts`: Local monotonic wall-clock timestamp when the event was first observed by the collector.
- `ingested_ts`: Timestamp when the event was committed to storage.
- `exchange_ts`: Timestamp reported by Polymarket or CLOB APIs, if distinct from `source_ts`.
- `chain_ts`: Block timestamp for on-chain events.
- `market_start_ts`: Start of the 5-minute market interval.
- `market_end_ts`: End of the 5-minute market interval.
- `snapshot_ts`: Timestamp at which features are computed.
- `label_cutoff_ts`: Last timestamp allowed for feature data before a label is assigned.

Rules:

- Never use local timezone for persisted data.
- Prefer source-provided event time for ordering market data, but retain observed time for latency and gap analysis.
- Feature snapshots must only use data with `source_ts <= snapshot_ts`.
- Labels must only be created after final resolution is known.
- For model training, enforce `snapshot_ts < label_cutoff_ts <= market_end_ts` unless the label type explicitly needs post-close resolution data.
- Use millisecond precision for off-chain events and second precision for on-chain block timestamps.
- Track collector clock drift as a data quality metric.

## Raw Event Schemas

Raw events preserve original source payloads and are append-only. They should be written before normalization whenever possible.

### `raw_events`

```sql
CREATE TABLE raw_events (
  raw_event_id       BIGSERIAL PRIMARY KEY,
  source             TEXT NOT NULL,
  event_type         TEXT NOT NULL,
  source_event_id    TEXT,
  source_ts          TIMESTAMPTZ,
  observed_ts        TIMESTAMPTZ NOT NULL,
  ingested_ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
  market_slug        TEXT,
  market_id          TEXT,
  asset_id           TEXT,
  sequence_id        TEXT,
  payload            JSONB NOT NULL,
  payload_hash       TEXT NOT NULL,
  schema_version     INTEGER NOT NULL DEFAULT 1,
  UNIQUE (source, event_type, payload_hash)
);
```

Common `source` values:

- `polymarket_gamma`
- `polymarket_clob`
- `polymarket_websocket`
- `polymarket_subgraph`
- `coinbase_btc_usd`
- `binance_btc_usdt`
- `kraken_btc_usd`
- `internal_collector`

Common `event_type` values:

- `market_discovered`
- `market_updated`
- `market_resolved`
- `orderbook_snapshot`
- `orderbook_delta`
- `trade`
- `quote_tick`
- `btc_reference_tick`
- `funding_balance`
- `position_snapshot`
- `order_submitted`
- `order_acknowledged`
- `order_filled`
- `order_cancelled`
- `order_rejected`
- `collector_heartbeat`

### Raw Market Discovery Event

```json
{
  "schema_version": 1,
  "source": "polymarket_gamma",
  "event_type": "market_discovered",
  "source_ts": "2026-07-02T12:00:00.000Z",
  "observed_ts": "2026-07-02T12:00:00.125Z",
  "market_slug": "btc-updown-5m-2026-07-02-1200",
  "payload": {
    "condition_id": "0x...",
    "question": "Bitcoin Up or Down - July 2, 12:00PM ET",
    "market_slug": "btc-updown-5m-2026-07-02-1200",
    "outcomes": ["Up", "Down"],
    "token_ids": ["123...", "456..."],
    "start_time": "2026-07-02T16:00:00Z",
    "end_time": "2026-07-02T16:05:00Z",
    "resolution_source": "BTC/USD index",
    "raw": {}
  }
}
```

### Raw Order Book Snapshot Event

```json
{
  "schema_version": 1,
  "source": "polymarket_clob",
  "event_type": "orderbook_snapshot",
  "source_ts": "2026-07-02T16:01:10.432Z",
  "observed_ts": "2026-07-02T16:01:10.488Z",
  "market_id": "0x...",
  "asset_id": "123...",
  "sequence_id": "9823471",
  "payload": {
    "asset_id": "123...",
    "bids": [{"price": "0.47", "size": "850.5"}],
    "asks": [{"price": "0.48", "size": "430.0"}],
    "min_order_size": "5",
    "tick_size": "0.01"
  }
}
```

### Raw Order Book Delta Event

```json
{
  "schema_version": 1,
  "source": "polymarket_websocket",
  "event_type": "orderbook_delta",
  "source_ts": "2026-07-02T16:01:11.210Z",
  "observed_ts": "2026-07-02T16:01:11.255Z",
  "market_id": "0x...",
  "asset_id": "123...",
  "sequence_id": "9823472",
  "payload": {
    "changes": [
      {"side": "BUY", "price": "0.47", "size": "900.0"},
      {"side": "SELL", "price": "0.48", "size": "0"}
    ]
  }
}
```

### Raw Trade Event

```json
{
  "schema_version": 1,
  "source": "polymarket_clob",
  "event_type": "trade",
  "source_ts": "2026-07-02T16:01:12.034Z",
  "observed_ts": "2026-07-02T16:01:12.091Z",
  "market_id": "0x...",
  "asset_id": "123...",
  "payload": {
    "trade_id": "tr_...",
    "asset_id": "123...",
    "price": "0.48",
    "size": "125.0",
    "side": "BUY",
    "maker_order_id": "0x...",
    "taker_order_id": "0x..."
  }
}
```

### Raw BTC Reference Tick Event

```json
{
  "schema_version": 1,
  "source": "coinbase_btc_usd",
  "event_type": "btc_reference_tick",
  "source_ts": "2026-07-02T16:01:12.500Z",
  "observed_ts": "2026-07-02T16:01:12.552Z",
  "payload": {
    "symbol": "BTC-USD",
    "price": "64250.12",
    "bid": "64249.98",
    "ask": "64250.25",
    "last_size": "0.015",
    "venue": "coinbase"
  }
}
```

### Raw Bot Execution Event

```json
{
  "schema_version": 1,
  "source": "internal_collector",
  "event_type": "order_submitted",
  "source_ts": "2026-07-02T16:01:20.000Z",
  "observed_ts": "2026-07-02T16:01:20.000Z",
  "market_id": "0x...",
  "asset_id": "123...",
  "payload": {
    "client_order_id": "bot-20260702-160120-001",
    "side": "BUY",
    "price": "0.49",
    "size": "20.0",
    "reason_code": "strategy_signal",
    "feature_snapshot_id": 9842
  }
}
```

## Normalized Tables

Normalized tables are derived from raw events. They should be reproducible from raw input and versioned transformation code.

### `markets`

One row per 5-minute BTC Up/Down market.

```sql
CREATE TABLE markets (
  market_id          TEXT PRIMARY KEY,
  condition_id       TEXT UNIQUE,
  market_slug        TEXT UNIQUE NOT NULL,
  question           TEXT NOT NULL,
  market_start_ts    TIMESTAMPTZ NOT NULL,
  market_end_ts      TIMESTAMPTZ NOT NULL,
  resolution_ts      TIMESTAMPTZ,
  reference_price    NUMERIC(18, 8),
  final_price        NUMERIC(18, 8),
  winning_outcome    TEXT CHECK (winning_outcome IN ('UP', 'DOWN', 'TIE', 'UNKNOWN')),
  status             TEXT NOT NULL CHECK (status IN ('DISCOVERED', 'OPEN', 'CLOSED', 'RESOLVED', 'CANCELLED')),
  source             TEXT NOT NULL,
  created_ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (market_end_ts > market_start_ts)
);
```

Indexes:

```sql
CREATE INDEX idx_markets_window ON markets (market_start_ts, market_end_ts);
CREATE INDEX idx_markets_status_end ON markets (status, market_end_ts);
```

### `market_assets`

One row per outcome token.

```sql
CREATE TABLE market_assets (
  asset_id           TEXT PRIMARY KEY,
  market_id          TEXT NOT NULL REFERENCES markets (market_id),
  outcome            TEXT NOT NULL CHECK (outcome IN ('UP', 'DOWN')),
  token_symbol       TEXT,
  active             BOOLEAN NOT NULL DEFAULT true,
  created_ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (market_id, outcome)
);
```

### `orderbook_snapshots`

Top-of-book and depth summary per asset.

```sql
CREATE TABLE orderbook_snapshots (
  orderbook_snapshot_id BIGSERIAL PRIMARY KEY,
  market_id             TEXT NOT NULL REFERENCES markets (market_id),
  asset_id              TEXT NOT NULL REFERENCES market_assets (asset_id),
  source_ts             TIMESTAMPTZ NOT NULL,
  observed_ts           TIMESTAMPTZ NOT NULL,
  sequence_id           TEXT,
  best_bid_price        NUMERIC(10, 6),
  best_bid_size         NUMERIC(24, 8),
  best_ask_price        NUMERIC(10, 6),
  best_ask_size         NUMERIC(24, 8),
  mid_price             NUMERIC(10, 6),
  spread                NUMERIC(10, 6),
  bid_depth_1pct        NUMERIC(24, 8),
  ask_depth_1pct        NUMERIC(24, 8),
  bid_depth_5pct        NUMERIC(24, 8),
  ask_depth_5pct        NUMERIC(24, 8),
  book_json             JSONB,
  raw_event_id          BIGINT REFERENCES raw_events (raw_event_id),
  UNIQUE (asset_id, source_ts, sequence_id)
);
```

Indexes:

```sql
CREATE INDEX idx_orderbook_asset_ts ON orderbook_snapshots (asset_id, source_ts DESC);
CREATE INDEX idx_orderbook_market_ts ON orderbook_snapshots (market_id, source_ts DESC);
```

### `trades`

Polymarket trades by market asset.

```sql
CREATE TABLE trades (
  trade_id          TEXT PRIMARY KEY,
  market_id         TEXT NOT NULL REFERENCES markets (market_id),
  asset_id          TEXT NOT NULL REFERENCES market_assets (asset_id),
  source_ts         TIMESTAMPTZ NOT NULL,
  observed_ts       TIMESTAMPTZ NOT NULL,
  price             NUMERIC(10, 6) NOT NULL,
  size              NUMERIC(24, 8) NOT NULL,
  side              TEXT CHECK (side IN ('BUY', 'SELL', 'UNKNOWN')),
  notional          NUMERIC(24, 8) GENERATED ALWAYS AS (price * size) STORED,
  maker_order_id    TEXT,
  taker_order_id    TEXT,
  raw_event_id      BIGINT REFERENCES raw_events (raw_event_id),
  CHECK (price >= 0 AND price <= 1),
  CHECK (size > 0)
);
```

Indexes:

```sql
CREATE INDEX idx_trades_market_ts ON trades (market_id, source_ts DESC);
CREATE INDEX idx_trades_asset_ts ON trades (asset_id, source_ts DESC);
```

### `btc_reference_ticks`

BTC price ticks from one or more venues.

```sql
CREATE TABLE btc_reference_ticks (
  btc_tick_id       BIGSERIAL PRIMARY KEY,
  venue             TEXT NOT NULL,
  symbol            TEXT NOT NULL,
  source_ts         TIMESTAMPTZ NOT NULL,
  observed_ts       TIMESTAMPTZ NOT NULL,
  price             NUMERIC(18, 8) NOT NULL,
  bid               NUMERIC(18, 8),
  ask               NUMERIC(18, 8),
  last_size         NUMERIC(24, 8),
  raw_event_id      BIGINT REFERENCES raw_events (raw_event_id),
  UNIQUE (venue, symbol, source_ts, price),
  CHECK (price > 0)
);
```

Indexes:

```sql
CREATE INDEX idx_btc_reference_ticks_ts ON btc_reference_ticks (source_ts DESC);
CREATE INDEX idx_btc_reference_ticks_venue_ts ON btc_reference_ticks (venue, source_ts DESC);
```

### `orders`

Bot order lifecycle.

```sql
CREATE TABLE orders (
  order_id             TEXT PRIMARY KEY,
  client_order_id      TEXT UNIQUE NOT NULL,
  market_id            TEXT NOT NULL REFERENCES markets (market_id),
  asset_id             TEXT NOT NULL REFERENCES market_assets (asset_id),
  feature_snapshot_id  BIGINT,
  side                 TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
  order_type           TEXT NOT NULL CHECK (order_type IN ('LIMIT', 'MARKET')),
  price                NUMERIC(10, 6),
  size                 NUMERIC(24, 8) NOT NULL,
  status               TEXT NOT NULL CHECK (status IN ('SUBMITTED', 'ACKNOWLEDGED', 'PARTIALLY_FILLED', 'FILLED', 'CANCELLED', 'REJECTED', 'EXPIRED')),
  submitted_ts         TIMESTAMPTZ NOT NULL,
  acknowledged_ts      TIMESTAMPTZ,
  terminal_ts          TIMESTAMPTZ,
  reject_reason        TEXT,
  raw_event_id         BIGINT REFERENCES raw_events (raw_event_id),
  CHECK (price IS NULL OR (price >= 0 AND price <= 1)),
  CHECK (size > 0)
);
```

### `fills`

Actual execution fills.

```sql
CREATE TABLE fills (
  fill_id           TEXT PRIMARY KEY,
  order_id          TEXT NOT NULL REFERENCES orders (order_id),
  market_id         TEXT NOT NULL REFERENCES markets (market_id),
  asset_id          TEXT NOT NULL REFERENCES market_assets (asset_id),
  source_ts         TIMESTAMPTZ NOT NULL,
  price             NUMERIC(10, 6) NOT NULL,
  size              NUMERIC(24, 8) NOT NULL,
  fee               NUMERIC(24, 8) DEFAULT 0,
  raw_event_id      BIGINT REFERENCES raw_events (raw_event_id),
  CHECK (price >= 0 AND price <= 1),
  CHECK (size > 0)
);
```

### `positions`

Current and historical position snapshots.

```sql
CREATE TABLE positions (
  position_snapshot_id BIGSERIAL PRIMARY KEY,
  account_id           TEXT NOT NULL,
  market_id            TEXT NOT NULL REFERENCES markets (market_id),
  asset_id             TEXT NOT NULL REFERENCES market_assets (asset_id),
  source_ts            TIMESTAMPTZ NOT NULL,
  size                 NUMERIC(24, 8) NOT NULL,
  avg_entry_price      NUMERIC(10, 6),
  realized_pnl         NUMERIC(24, 8),
  unrealized_pnl       NUMERIC(24, 8),
  raw_event_id         BIGINT REFERENCES raw_events (raw_event_id),
  UNIQUE (account_id, asset_id, source_ts)
);
```

## Feature Snapshot Schema

Feature snapshots are immutable point-in-time rows used by strategies and training. Every row must be reproducible from normalized data and must avoid lookahead.

### `feature_snapshots`

```sql
CREATE TABLE feature_snapshots (
  feature_snapshot_id     BIGSERIAL PRIMARY KEY,
  market_id               TEXT NOT NULL REFERENCES markets (market_id),
  snapshot_ts             TIMESTAMPTZ NOT NULL,
  market_start_ts          TIMESTAMPTZ NOT NULL,
  market_end_ts            TIMESTAMPTZ NOT NULL,
  seconds_to_close         INTEGER NOT NULL,
  reference_price          NUMERIC(18, 8),
  btc_price                NUMERIC(18, 8),
  btc_return_5s            NUMERIC(18, 10),
  btc_return_15s           NUMERIC(18, 10),
  btc_return_30s           NUMERIC(18, 10),
  btc_return_60s           NUMERIC(18, 10),
  btc_realized_vol_60s     NUMERIC(18, 10),
  btc_price_distance       NUMERIC(18, 10),
  up_best_bid              NUMERIC(10, 6),
  up_best_ask              NUMERIC(10, 6),
  up_mid                  NUMERIC(10, 6),
  up_spread               NUMERIC(10, 6),
  up_bid_depth_1pct        NUMERIC(24, 8),
  up_ask_depth_1pct        NUMERIC(24, 8),
  down_best_bid            NUMERIC(10, 6),
  down_best_ask            NUMERIC(10, 6),
  down_mid                NUMERIC(10, 6),
  down_spread             NUMERIC(10, 6),
  down_bid_depth_1pct      NUMERIC(24, 8),
  down_ask_depth_1pct      NUMERIC(24, 8),
  market_implied_up        NUMERIC(10, 6),
  market_implied_down      NUMERIC(10, 6),
  implied_sum              NUMERIC(10, 6),
  orderbook_imbalance      NUMERIC(18, 10),
  trade_count_15s          INTEGER NOT NULL DEFAULT 0,
  trade_count_60s          INTEGER NOT NULL DEFAULT 0,
  trade_volume_15s         NUMERIC(24, 8) NOT NULL DEFAULT 0,
  trade_volume_60s         NUMERIC(24, 8) NOT NULL DEFAULT 0,
  up_trade_volume_60s      NUMERIC(24, 8) NOT NULL DEFAULT 0,
  down_trade_volume_60s    NUMERIC(24, 8) NOT NULL DEFAULT 0,
  collector_lag_ms         INTEGER,
  source_gap_count         INTEGER NOT NULL DEFAULT 0,
  feature_version          INTEGER NOT NULL,
  created_ts               TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (market_id, snapshot_ts, feature_version),
  CHECK (snapshot_ts >= market_start_ts),
  CHECK (snapshot_ts <= market_end_ts),
  CHECK (seconds_to_close >= 0),
  CHECK (feature_version > 0)
);
```

Indexes:

```sql
CREATE INDEX idx_feature_snapshots_market_ts ON feature_snapshots (market_id, snapshot_ts);
CREATE INDEX idx_feature_snapshots_version_ts ON feature_snapshots (feature_version, snapshot_ts);
```

Snapshot cadence:

- MVP live strategy: every 1 second per active market.
- MVP training data: every 1 second, with optional downsampling after initial experiments.
- Always store `feature_version` so models can be tied to the exact feature definition.

Recommended feature derivation rules:

- `market_implied_up` should use the UP midpoint when both bid and ask are present. Fall back to last traded price only with a quality flag.
- `market_implied_down` should use the DOWN midpoint when both bid and ask are present.
- `implied_sum = market_implied_up + market_implied_down`.
- `btc_price_distance = (btc_price - reference_price) / reference_price`.
- `orderbook_imbalance` should compare UP-side bid depth to DOWN-side bid depth or use a documented versioned formula.
- Set missing numeric features to `NULL`; do not silently fill unless the feature version defines an explicit imputation rule.

## Label Schema

Labels are generated after market resolution and joined to feature snapshots for training and evaluation.

### `market_labels`

One label row per market.

```sql
CREATE TABLE market_labels (
  market_id             TEXT PRIMARY KEY REFERENCES markets (market_id),
  label_version         INTEGER NOT NULL,
  label_created_ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
  market_start_ts       TIMESTAMPTZ NOT NULL,
  market_end_ts         TIMESTAMPTZ NOT NULL,
  resolution_ts         TIMESTAMPTZ NOT NULL,
  reference_price       NUMERIC(18, 8) NOT NULL,
  final_price           NUMERIC(18, 8) NOT NULL,
  price_delta           NUMERIC(18, 8) GENERATED ALWAYS AS (final_price - reference_price) STORED,
  winning_outcome       TEXT NOT NULL CHECK (winning_outcome IN ('UP', 'DOWN', 'TIE')),
  up_payout             NUMERIC(10, 6) NOT NULL,
  down_payout           NUMERIC(10, 6) NOT NULL,
  resolution_source     TEXT NOT NULL,
  quality_status        TEXT NOT NULL CHECK (quality_status IN ('VALID', 'SUSPECT', 'INVALID')),
  quality_notes         TEXT,
  CHECK (label_version > 0),
  CHECK (up_payout >= 0 AND up_payout <= 1),
  CHECK (down_payout >= 0 AND down_payout <= 1),
  CHECK (up_payout + down_payout <= 1.000001)
);
```

### `snapshot_labels`

One joined row per feature snapshot and label target.

```sql
CREATE TABLE snapshot_labels (
  feature_snapshot_id   BIGINT PRIMARY KEY REFERENCES feature_snapshots (feature_snapshot_id),
  market_id             TEXT NOT NULL REFERENCES markets (market_id),
  label_version         INTEGER NOT NULL,
  snapshot_ts           TIMESTAMPTZ NOT NULL,
  label_cutoff_ts       TIMESTAMPTZ NOT NULL,
  seconds_to_close      INTEGER NOT NULL,
  winning_outcome       TEXT NOT NULL CHECK (winning_outcome IN ('UP', 'DOWN', 'TIE')),
  target_up_win         BOOLEAN NOT NULL,
  target_down_win       BOOLEAN NOT NULL,
  target_up_payout      NUMERIC(10, 6) NOT NULL,
  target_down_payout    NUMERIC(10, 6) NOT NULL,
  target_btc_return_to_close NUMERIC(18, 10),
  created_ts            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (market_id, snapshot_ts, label_version),
  CHECK (snapshot_ts < label_cutoff_ts),
  CHECK (seconds_to_close >= 0)
);
```

Label rules:

- `target_up_win = true` when final BTC price is strictly greater than the market reference price.
- `target_down_win = true` when final BTC price is strictly less than the market reference price.
- If the market rules define a tie outcome, preserve `TIE` and set both win targets to false.
- If Polymarket resolution differs from locally reconstructed BTC price, mark `quality_status = SUSPECT` until reconciled.
- Labels should not be produced for cancelled, unresolved, or invalid markets.

## Data Quality Checks

Quality checks should run at ingest time, normalization time, and dataset build time.

### Ingest Checks

- Reject raw events with missing `source`, `event_type`, `observed_ts`, or `payload`.
- Compute and store `payload_hash` for deduplication.
- Alert when collector heartbeat gap exceeds 10 seconds during active markets.
- Alert when `observed_ts - source_ts` exceeds 2 seconds for market data or BTC ticks.
- Track out-of-order sequence IDs by source and asset.
- Persist malformed payloads in a quarantine table or log with the parser error.

### Market Checks

- Market duration must be exactly 5 minutes unless explicitly marked as an exception.
- Each market must have exactly one UP asset and one DOWN asset.
- Market windows should not overlap for the same market family except during discovery ambiguity.
- `market_end_ts` must be after `market_start_ts`.
- Resolved markets must have `reference_price`, `final_price`, `winning_outcome`, and `resolution_ts`.

### Order Book Checks

- Prices must be between 0 and 1 inclusive.
- Sizes must be non-negative in snapshots and positive in trades.
- Best bid must be less than or equal to best ask for the same asset.
- UP and DOWN midpoint sum should usually be near 1; large persistent deviations should be flagged.
- Snapshot gaps longer than 3 seconds during an open market should set `source_gap_count`.
- Deltas must not be applied across missing sequence IDs without a fresh snapshot.

### BTC Reference Checks

- BTC price must be positive.
- Bid must be less than or equal to ask when both are present.
- Cross-venue prices should be within a configurable tolerance.
- Stale ticks older than 2 seconds should not be used for live feature snapshots.
- Reference price at market start and final price at market close must be reproducible from stored ticks or an official resolution source.

### Feature Checks

- No feature snapshot may use data with `source_ts > snapshot_ts`.
- `seconds_to_close` must equal `market_end_ts - snapshot_ts` rounded according to the feature version.
- Feature rows must be unique by `(market_id, snapshot_ts, feature_version)`.
- Missing critical features, such as BTC price or both UP and DOWN books, should mark the row unusable for live trading.
- `collector_lag_ms` and `source_gap_count` should be available to downstream strategy code.
- Feature generation should be deterministic for a fixed feature version and raw event set.

### Label Checks

- Labels are generated only for resolved markets.
- `snapshot_ts` must be strictly earlier than `label_cutoff_ts`.
- The label generation job must not update historical labels in place without incrementing `label_version`.
- Locally reconstructed outcome should match the stored market outcome.
- Ties, cancellations, and disputed resolutions must be explicit and excluded from default binary training datasets unless intentionally included.

### Execution Data Checks

- Every fill must reference a known order.
- Filled size across fills must not exceed order size.
- Order prices must be between 0 and 1.
- Orders should reference the feature snapshot that caused the decision when applicable.
- Execution timestamps should be checked against active market windows to avoid training on impossible fills.

## Dataset Build Contract

Training datasets should join:

- `feature_snapshots`
- `snapshot_labels`
- `markets`
- Optional execution outcomes from `orders` and `fills`

Minimum model-ready columns:

- `feature_snapshot_id`
- `market_id`
- `snapshot_ts`
- `seconds_to_close`
- `feature_version`
- `label_version`
- Feature columns from `feature_snapshots`
- `target_up_win`
- `target_down_win`
- `target_up_payout`
- `target_down_payout`
- `quality_status`

Default filters:

- Include only `market_labels.quality_status = 'VALID'`.
- Exclude cancelled markets.
- Exclude tie markets unless the model explicitly supports ties.
- Exclude snapshots with missing BTC price.
- Exclude snapshots with missing UP and DOWN top-of-book data.
- Exclude rows where `source_gap_count > 0` for strict backtests.

## Retention And Rebuild Policy

- Keep raw events indefinitely during MVP.
- Keep normalized events indefinitely unless storage becomes a measured issue.
- Feature snapshots may be regenerated for new `feature_version` values, but old versions should be retained if any model or backtest references them.
- Labels are append-versioned by `label_version`; do not mutate historical label definitions silently.
- All derived tables should record enough version metadata to rebuild model datasets exactly.
