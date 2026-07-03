# Data Directory

Local research data lives here. Do not put secrets in this tree.

## Layout

- `history/`: exchange reference data, currently Binance BTCUSDT 5m klines as JSONL.
- `training/`: model training CSVs and dataset manifests.
- `raw/`: live/paper collector event streams.
- `audit/`: paper decision and execution audit logs.

## Current BTC Training Block

- History: `data/history/btcusdt-5m-2024.jsonl`
- Training CSV: `data/training/btcusdt-5m-2024-training.csv`
- Manifest: `data/training/btcusdt-5m-2024-training.manifest.json`

The BTC training CSV is useful for baseline volatility/regime modeling. It is not enough to prove Polymarket execution edge; that still requires live Polymarket market state, CLOB books, and outcome labels.

Use `polymarket-btc-bot btc-model-eval data/training/btcusdt-5m-2024-training.csv` to check whether the BTC-only training features beat a rolling baseline in a walk-forward evaluation. Treat a positive result as a research candidate, not as permission to trade.
