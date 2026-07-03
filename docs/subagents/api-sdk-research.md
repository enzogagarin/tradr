# API/SDK Integration Research: Polymarket BTC Up/Down 5m Bot

Research date: 2026-07-02

Scope: API and SDK integration surface only. This document does not define strategy, sizing, deployment, or risk rules.

## Recommended Integration Stack

Use Polymarket as two separate surfaces:

- Market discovery and metadata: Gamma REST API at `https://gamma-api.polymarket.com`.
- Prices, order books, order placement, cancels, balances, and trading auth: CLOB REST plus CLOB WebSocket at `https://clob.polymarket.com` and `wss://ws-subscriptions-clob.polymarket.com/ws/market`.

For implementation, prefer the official unified Python SDK, `polymarket-client`, for application code if it covers the required trading flow by the time implementation starts. It is the newest official Python SDK and is designed to cover public data, authenticated account, trading, builder attribution, and wallet workflows. Because it is still beta, keep a thin internal adapter boundary so we can fall back to `py-clob-client-v2` for order signing/submission if needed.

Avoid the archived `py-clob-client` package for new work. Polymarket's archived client README now says to migrate to the new unified SDK. `py-clob-client-v2` remains useful as the direct CLOB v2 execution fallback and documents the current L1/L2 auth split and `create_and_post_order` / `create_and_post_market_order` helpers.

Primary sources:

- Polymarket clients and SDKs: https://docs.polymarket.com/api-reference/clients-sdks
- Unified Python SDK: https://docs.polymarket.com/dev-tooling/python.md and https://github.com/Polymarket/py-sdk
- CLOB v2 Python fallback: https://github.com/Polymarket/py-clob-client-v2
- Archived old client warning: https://github.com/Polymarket/py-clob-client

## Polymarket Gamma API

Purpose: discover the current BTC Up/Down 5m event/market, retrieve market metadata, map outcomes to token IDs, track end times, and refresh when the 5-minute window rolls.

Base URL: `https://gamma-api.polymarket.com`

Authentication: none for public market discovery.

Recommended endpoints:

- `GET /public-search` to search for active BTC Up/Down markets by text when slug is unknown. Use query terms such as `bitcoin up down`, `btc up or down`, and filter client-side to active/open markets with 5-minute cadence.
- `GET /events` or `GET /events/keyset` for event discovery. Prefer keyset pagination for stable long-running scanners.
- `GET /events/slug/{slug}` once a candidate event slug is known from the Polymarket URL or search result.
- `GET /markets` or `GET /markets/keyset` for market discovery. Prefer keyset pagination for scheduled sweeps.
- `GET /markets/slug/{slug}` once a market slug is known.
- `GET /markets/{id}` for direct market refresh by id.
- `GET /markets/{id}/tags` or event tags only for classification, not the trading-critical path.

Fields to persist per 5-minute market:

- `id`, `slug`, `question`, `conditionId`, `endDate`, `closed`, `archived`, `active`.
- Outcome names and token IDs from the market response. The bot should treat token IDs as the execution identifiers for CLOB calls.
- Any tick-size, fee, or CLOB-specific metadata if present, but validate those against CLOB before trading.

Recommendation:

- Do not scrape the Polymarket website.
- Use Gamma to discover the next market, then use CLOB `markets-by-token`, `tick-size`, `fee-rate`, `book`, and WebSocket subscriptions to verify tradability.
- Refresh discovery at least once per minute and around window boundaries. BTC Up/Down 5m markets roll quickly, so assume slugs and token IDs change every interval.

Sources:

- Gamma OpenAPI: https://docs.polymarket.com/api-spec/gamma-openapi.yaml
- Polymarket market data overview: https://docs.polymarket.com/market-data/overview.md
- Fetching markets guide: https://docs.polymarket.com/market-data/fetching-markets.md
- API index: https://docs.polymarket.com/llms.txt

## Polymarket CLOB REST

Purpose: tradability checks, order-book reads, price reads, order placement/cancel, balances/allowances, and user order/trade state.

Base URL: `https://clob.polymarket.com`

Staging URL: `https://clob-staging.polymarket.com`

Recommended public market-data endpoints:

- `GET /book?token_id={token_id}` for one outcome order book.
- `POST /books` for both Up and Down outcome books in one request.
- `GET /price?token_id={token_id}&side=BUY|SELL` for best executable market price. BUY returns best bid; SELL returns best ask per docs.
- `POST /prices` for batch best prices.
- `GET /midpoint?token_id={token_id}` and `POST /midpoints` for midpoint monitoring.
- `GET /spread?token_id={token_id}` and `POST /spreads` for liquidity checks.
- `GET /last-trade-price?token_id={token_id}` and `POST /last-trades-prices` for recent execution reference.
- `GET /tick-size?token_id={token_id}` or `GET /tick-size/{token_id}` before building orders.
- `GET /fee-rate?token_id={token_id}` or `GET /fee-rate/{token_id}` before signing orders.
- `GET /neg-risk?token_id={token_id}` when building order parameters for markets that may require negative-risk handling.
- `GET /markets-by-token/{token_id}` to resolve a token back to its CLOB market.
- `GET /clob-markets/{condition_id}` for all CLOB parameters for a condition.
- `GET /time` for clock sync before authenticated requests.

Recommended authenticated endpoints:

- `POST /auth/api-key` or SDK equivalent to create an API key from L1 wallet auth.
- `GET /auth/derive-api-key` or SDK equivalent to derive/retrieve CLOB API credentials.
- `POST /order` to submit one signed order.
- `POST /orders` to submit multiple signed orders, if batching is ever needed.
- `DELETE /order` to cancel a single order.
- `DELETE /orders` to cancel multiple orders.
- `DELETE /cancel-all` as kill switch.
- `DELETE /cancel-market-orders` to clear a specific condition/asset.
- `GET /data/orders` for open/user orders.
- `GET /data/order/{orderID}` for one order.
- `GET /data/trades` for authenticated trade/fill history.
- `GET /balance-allowance` and `POST /balance-allowance/update` for preflight funding/allowance checks.
- `POST /heartbeats` or `/v1/heartbeats` if the bot leaves live orders resting. Polymarket documents heartbeats as a way for automated trading systems to have open orders canceled if the system becomes unresponsive.

Execution recommendation:

- For a 5-minute directional bot, use `FOK` or `FAK` market-style orders only when the strategy intentionally crosses the spread. Use `GTC` only if the bot also owns cancel/heartbeat handling.
- Before any order, fetch/refresh `tick-size`, `fee-rate`, `neg-risk`, and the book for the target token ID.
- Build and sign through SDK helpers rather than manually constructing order payloads. Manual signing requires exact order version, tick size, fees, and signature type handling.
- Implement cancel-all and market-specific cancel endpoints before enabling live orders.

Sources:

- CLOB OpenAPI: https://docs.polymarket.com/api-spec/clob-openapi.yaml
- CLOB auth docs: https://docs.polymarket.com/api-reference/authentication.md
- Public client methods: https://docs.polymarket.com/trading/clients/public.md
- L1 client methods: https://docs.polymarket.com/trading/clients/l1.md
- L2 client methods: https://docs.polymarket.com/trading/clients/l2.md
- Create order guide: https://docs.polymarket.com/trading/orders/create.md
- Matching-engine restarts: https://docs.polymarket.com/trading/matching-engine.md

## Polymarket CLOB WebSocket

Purpose: real-time order-book snapshots, price deltas, best bid/ask, and last trade updates for the active Up/Down token IDs.

Market WebSocket:

- URL: `wss://ws-subscriptions-clob.polymarket.com/ws/market`
- Auth: public for market channel.
- Subscribe with `assets_ids`, where each value is an outcome token ID.
- Send text `PING` every 10 seconds to keep the connection alive.
- Expected messages include `book`, `price_change`, `last_trade_price`, `tick_size_change`, and optionally `best_bid_ask`.

Recommended subscription shape:

```json
{
  "assets_ids": ["<UP_TOKEN_ID>", "<DOWN_TOKEN_ID>"],
  "type": "market"
}
```

Operational recommendations:

- Treat the first `book` message as the authoritative snapshot.
- Apply `price_change` updates only after a snapshot is loaded for that token.
- Reconnect and resubscribe when the 5-minute market rolls or after missed heartbeats.
- Keep REST `book` as a snapshot repair path if sequence or message handling becomes uncertain.
- Use one connection for the active market pair; do not subscribe to broad token sets for this bot.

User WebSocket:

- Use only if SDK support is mature enough for authenticated order/trade updates. Otherwise poll `GET /data/orders` and `GET /data/trades` on a short interval after submitting orders.

Sources:

- Polymarket AsyncAPI: https://docs.polymarket.com/asyncapi.json
- Market WebSocket docs: https://docs.polymarket.com/market-data/websocket/market-channel.md
- WebSocket overview: https://docs.polymarket.com/market-data/websocket/overview.md
- User channel docs: https://docs.polymarket.com/market-data/websocket/user-channel.md

## Auth And Execution SDK Choice

Polymarket CLOB auth has two practical levels:

- L1 wallet signature: EIP-712 wallet signing. Required to create or derive CLOB API keys.
- L2 API credentials: HMAC-style API credentials. Required for order placement, cancellation, and account/order/trade data.

Recommended path:

1. Start with the official unified Python SDK `polymarket-client` behind an internal `PolymarketGateway` interface.
2. Use `AsyncPublicClient` / public client methods for market reads if they expose the needed calls.
3. Use the SDK's trading/auth flows for L1/L2 if available.
4. Keep `py-clob-client-v2` as the execution fallback because its README explicitly documents current CLOB v2 order placement and auth:
   - `ClobClient(host, chain_id=137, key=PRIVATE_KEY)`
   - `create_or_derive_api_key()`
   - `ClobClient(..., creds=ApiCreds(...))`
   - `create_and_post_order(...)`
   - `create_and_post_market_order(...)`
5. Do not use the old `py-clob-client` package.

Required environment variables for live execution:

- `POLYMARKET_PRIVATE_KEY`: wallet key used for L1 signing. Never log it.
- `CLOB_API_KEY`, `CLOB_SECRET`, `CLOB_PASS_PHRASE`: L2 credentials, if not deriving at runtime.
- Optional builder attribution variables only if the project joins Polymarket's builder program.

Chain and wallet notes:

- Polymarket CLOB examples use `chain_id = 137` for Polygon mainnet and `80002` for Amoy testnet.
- If using email/proxy/Safe wallet flows, preserve the distinction between signer, funder/proxy, and owner addresses. Use SDK helpers rather than manually guessing signature type.
- Do all balance and allowance checks before the first live order.

Sources:

- Polymarket clients and SDKs: https://docs.polymarket.com/api-reference/clients-sdks
- Unified Python SDK repo: https://github.com/Polymarket/py-sdk
- CLOB v2 Python client: https://github.com/Polymarket/py-clob-client-v2
- Authentication: https://docs.polymarket.com/api-reference/authentication.md
- Deposit wallets: https://docs.polymarket.com/trading/deposit-wallets.md
- Gasless transactions: https://docs.polymarket.com/trading/gasless.md

## Chainlink Data Streams BTC/USD

Purpose: low-latency external BTC/USD reference price for signal generation or settlement-aligned price validation. This should be treated as an independent market-data input, not as a Polymarket execution source.

Product: BTC / USD Data Stream

Product name shown by Chainlink: `BTC/USD-RefPrice-DS-Premium-Global-003`

Feed ID: Chainlink's public page currently truncates it as `0x0003...75b8`; retrieve the full feed ID from Chainlink's Data Streams dashboard/API during credential provisioning before implementation.

REST base URLs:

- Mainnet: `https://api.dataengine.chain.link`
- Testnet: `https://api.testnet-dataengine.chain.link`

Authentication:

- All REST requests require HMAC auth headers:
  - `Authorization`: user UUID.
  - `X-Authorization-Timestamp`: current timestamp with millisecond precision.
  - `X-Authorization-Signature-SHA256`: HMAC-SHA256 signature.
- If using an official Chainlink Data Streams SDK, the SDK handles those headers.

Recommended endpoints:

- `GET /api/v1/reports/latest?feedID={feedID}` for latest BTC/USD signed report.
- `GET /api/v1/reports?feedID={feedID}&timestamp={unix_seconds}` for a point-in-time report.
- `GET /api/v1/reports/page?feedID={feedID}&startTimestamp={unix_seconds}&limit={n}` for replay/backfill.
- `GET /api/v1/reports/bulk?feedIDs={feedID1},{feedID2}&timestamp={unix_seconds}` only if adding more streams later.

Recommendation:

- Use Chainlink Data Streams as the highest-integrity reference source if credentials are available.
- Use WebSocket streaming if the bot needs sub-second updates; otherwise poll latest reports around the decision boundary.
- Persist `observationsTimestamp`, decoded price, and source latency for every decision.
- Do not hardcode the truncated feed ID from the public data page.

Sources:

- Chainlink Data Streams overview: https://docs.chain.link/data-streams
- Chainlink Data Streams REST API: https://docs.chain.link/data-streams/reference/data-streams-api/interface-api
- BTC/USD stream page: https://data.chain.link/streams/btc-usd-cexprice-streams
- Chainlink WebSocket tutorial index: https://docs.chain.link/data-streams

## Binance BTC Market Data

Purpose: low-cost, highly liquid BTC spot reference data. Good for tick/trade/candle inputs and fallback reference pricing.

Recommended symbol: `BTCUSDT`

REST base URL: `https://api.binance.com`

WebSocket base URLs:

- Raw stream: `wss://stream.binance.com:9443/ws/<streamName>`
- Combined stream: `wss://stream.binance.com:9443/stream?streams=<stream1>/<stream2>`
- Market-data-only alternative: `wss://data-stream.binance.vision`

Recommended REST endpoints:

- `GET /api/v3/klines?symbol=BTCUSDT&interval=1m&limit=...` for recent candles.
- `GET /api/v3/klines?symbol=BTCUSDT&interval=5m&limit=...` for 5-minute candles.
- `GET /api/v3/ticker/bookTicker?symbol=BTCUSDT` for current best bid/ask.
- `GET /api/v3/avgPrice?symbol=BTCUSDT` for Binance's 5-minute weighted average.
- `GET /api/v3/depth?symbol=BTCUSDT&limit=100` only if local book validation is needed.

Recommended WebSocket streams:

- `btcusdt@trade` or `btcusdt@aggTrade` for last-trade ticks.
- `btcusdt@bookTicker` for best bid/ask.
- `btcusdt@kline_1m` for rolling 1-minute candles.
- `btcusdt@kline_5m` for exchange 5-minute candles.
- `btcusdt@avgPrice` for Binance average price updates.

Operational notes:

- Streams use lowercase symbols.
- Connections are valid for 24 hours and should be proactively recycled.
- Server sends ping frames every 20 seconds; reply with pong.
- Keep inbound control messages under Binance's documented limits.

Sources:

- Binance WebSocket streams: https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams
- Binance REST market data: https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints

## Coinbase BTC Market Data

Purpose: regulated US venue reference data and cross-exchange sanity check.

Recommended product: `BTC-USD`

Advanced Trade REST base URL: `https://api.coinbase.com/api/v3/brokerage`

Advanced Trade WebSocket URLs:

- Market data: `wss://advanced-trade-ws.coinbase.com`
- User order data: `wss://advanced-trade-ws-user.coinbase.com`

Recommended REST endpoints:

- `GET /api/v3/brokerage/market/products/BTC-USD/ticker` for public market trades/ticker snapshot.
- `GET /api/v3/brokerage/market/product_book?product_id=BTC-USD&limit=...` for public book snapshots.
- `GET /api/v3/brokerage/market/products/BTC-USD/candles?start=...&end=...&granularity=ONE_MINUTE|FIVE_MINUTE` for public candles if using public endpoints.
- If using authenticated Advanced Trade endpoints instead, equivalent product endpoints live under `/products/{product_id}` and require bearer auth.

Recommended WebSocket channels:

- Subscribe to ticker/trades for real-time price.
- Subscribe to candles if available in the current channel list and aligned with the bot's aggregation needs.
- Subscribe to heartbeats to monitor connection health.

Recommendation:

- Prefer public market endpoints for data-only ingestion.
- Use Coinbase as an independent reference source alongside Binance/OKX, not as the sole signal source.
- Normalize timestamps to UTC seconds/milliseconds immediately on ingestion.

Sources:

- Coinbase Advanced Trade overview: https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/overview
- Coinbase WebSocket overview: https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/websocket/websocket-overview
- Coinbase WebSocket channels: https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/websocket/websocket-channels
- Coinbase public market trades: https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/get-public-market-trades
- Coinbase product candles: https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/products/get-product-candles
- Coinbase public products: https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/public/list-public-products

## OKX BTC Market Data

Purpose: additional high-liquidity offshore venue reference data and cross-exchange sanity check.

Recommended instrument: `BTC-USDT`

REST base URL: `https://www.okx.com`

Public WebSocket: `wss://ws.okx.com:8443/ws/v5/public`

Private WebSocket: `wss://ws.okx.com:8443/ws/v5/private`

Recommended REST endpoints:

- `GET /api/v5/market/ticker?instId=BTC-USDT` for last, best bid/ask, and 24-hour volume snapshot.
- `GET /api/v5/market/books?instId=BTC-USDT` for order book.
- `GET /api/v5/market/candles?instId=BTC-USDT&bar=1m|5m` for recent candles.
- `GET /api/v5/market/history-candles?instId=BTC-USDT&bar=1m|5m&limit=100` for backfill.
- `GET /api/v5/market/trades?instId=BTC-USDT` for recent trades.

Recommended WebSocket channels:

- `tickers` with `instId=BTC-USDT` for last/bid/ask.
- `trades` with `instId=BTC-USDT` for real-time trades.
- `books5` or `bbo-tbt` for lightweight best-book data.
- `candle1m` and `candle5m` for live candles if needed.

Recommendation:

- Use OKX as a third venue for median/consensus price checks.
- Keep REST candles for backfill and WebSocket tickers/trades for live operation.
- Normalize instrument naming separately from Binance/Coinbase symbols.

Sources:

- OKX API docs: https://www.okx.com/docs-v5/en/
- OKX market-data examples and candle endpoint snippets: https://tr.okx.com/docs-v5/en/

## Concrete Client Recommendations

Python packages to evaluate first:

- Polymarket:
  - Primary: `polymarket-client` from the official unified SDK.
  - Fallback for execution: `py_clob_client_v2`.
- HTTP/WebSocket infrastructure:
  - `httpx` for async REST.
  - `websockets` or `aiohttp` for raw WebSocket ingestion if SDKs are insufficient.
- Exchange market data:
  - Start with raw REST/WebSocket adapters for Binance, Coinbase, and OKX to keep payload handling explicit and reduce dependency risk.
  - Consider `ccxt` only for historical REST normalization. Do not use `ccxt` as the low-latency live WebSocket layer unless adding `ccxt.pro` intentionally.
- Chainlink:
  - Prefer official Data Streams SDK support if available for the implementation language.
  - Otherwise implement REST HMAC auth and report decoding in a small isolated adapter.

Adapter boundaries to create later:

- `PolymarketDiscovery`: Gamma search/events/markets to active Up/Down token IDs.
- `PolymarketMarketData`: CLOB REST and market WebSocket for books/prices.
- `PolymarketExecution`: CLOB auth, order creation, submit, cancel, order/trade state.
- `ReferencePriceFeed`: Chainlink, Binance, Coinbase, OKX normalized ticks/candles.

## Integration Checklist For The Next Build Step

- Confirm exact current BTC Up/Down 5m market naming and slug pattern through Gamma.
- Confirm the full Chainlink BTC/USD feed ID from provisioned Data Streams access.
- Choose Python SDK path after a spike: unified `polymarket-client` only, or `polymarket-client` plus `py_clob_client_v2` execution fallback.
- Implement read-only adapters first: Gamma discovery, CLOB books, CLOB WebSocket, and exchange price feeds.
- Add authenticated CLOB credential derivation and dry-run/preflight checks before any order path.
- Add order placement only after cancel-all, per-market cancel, balance/allowance checks, and fill/order-state reconciliation exist.
