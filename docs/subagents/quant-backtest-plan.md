# Polymarket BTC Up/Down 5m Quant and Backtest Plan

## Scope

Design the first quantitative strategy and validation plan for a Polymarket BTC Up/Down 5 minute trading bot. This document covers only research, modeling, strategy rules, and backtest methodology. It does not specify production infrastructure, key management, deployment, or live trading execution.

The initial objective is not to predict every 5 minute candle direction. The objective is to identify situations where the market price of a Polymarket binary contract is sufficiently mispriced versus a calibrated probability estimate after fees, spread, latency, fill risk, and adverse selection.

## Market Definition

Each 5 minute market resolves on whether BTC price is above or below a predefined start or strike reference at expiry. For every market, model the probability:

```text
P_up = Pr(BTC_expiry > BTC_reference | information_at_time_t)
P_down = 1 - P_up
fair_yes_up = P_up
fair_yes_down = 1 - P_up
```

All predictions must be timestamped with an information cutoff. No feature may use trades, orderbook states, oracle prices, or Binance/Coinbase candles that occur after the decision timestamp.

## Baseline Probability Model

Start with a micro-price random-walk baseline that converts current BTC distance to the reference into a probability using short-horizon volatility.

Inputs at decision time `t`:

```text
S_t = BTC mid price from reference exchange basket
K = market reference/strike price
tau = seconds until market expiry
sigma_tau = forecast volatility over tau
z = (ln(S_t / K)) / sigma_tau
P_up_baseline = Phi(z)
```

Volatility forecast:

```text
sigma_tau = sqrt(max(tau, tau_floor) / 300) * realized_vol_5m
```

Where `realized_vol_5m` is estimated from trailing 1 second or trade-level BTC mid returns over recent windows. Use a robust blend:

```text
realized_vol_5m = median(
  ewma_vol_60s_scaled,
  ewma_vol_180s_scaled,
  rolling_vol_300s
)
```

Clamp probabilities away from 0 and 1, for example `[0.01, 0.99]`, because oracle, reference, and data imperfections are material near expiry.

Baseline variants to compare:

- `coin_flip`: constant `P_up = 0.5`, only for sanity checks.
- `distance_only`: logistic regression on normalized distance to strike.
- `random_walk_vol`: normal CDF model above.
- `exchange_orderbook_microprice`: same as random walk, but `S_t` uses microprice instead of mid.

## Feature List

Features should be computed at multiple decision times within each market: from open, then every second or every orderbook event, until expiry minus a safety buffer.

Core state:

- Seconds to expiry.
- Log distance to strike/reference.
- Distance in basis points.
- Distance in units of forecast volatility.
- Current Polymarket best bid, best ask, midpoint, and spread for both Up and Down contracts.
- Polymarket implied probability from midpoint and from executable bid/ask.
- Edge versus baseline probability at bid/ask.

BTC price and volatility:

- BTC mid return over 1s, 3s, 5s, 15s, 30s, 60s, 180s, and 300s.
- Realized volatility over 30s, 60s, 180s, and 300s.
- Volatility acceleration: short-window vol divided by long-window vol.
- High-low range over 30s, 60s, and 300s.
- Trend slope over 15s, 60s, and 180s.
- Time since last local high and local low.

Reference exchange orderbook:

- Best bid, best ask, midpoint, and microprice.
- Top-of-book spread.
- Depth imbalance at 1 bp, 2 bps, 5 bps, and 10 bps.
- Trade aggressor imbalance over 5s, 15s, and 60s.
- Signed volume over 5s, 15s, and 60s.
- Large trade count and large trade imbalance.

Polymarket microstructure:

- Up and Down top-of-book sizes.
- Up and Down depth within 1c, 2c, 5c, and 10c.
- Orderbook imbalance between Yes-Up and Yes-Down.
- Spread width and spread percentile by time-to-expiry bucket.
- Last trade price, trade side estimate, and trade recency.
- Polymarket price momentum over 5s, 15s, and 60s.
- Book staleness: seconds since last Polymarket book update.

Market lifecycle:

- Market age.
- Expiry bucket: `0-15s`, `15-30s`, `30-60s`, `60-120s`, `120-300s`.
- Open/close transition flags.
- Whether BTC is within tight bands around strike: 1 bp, 2 bps, 5 bps, 10 bps.

Risk context:

- Recent realized slippage in same market.
- Recent fill probability by order type and queue position.
- Current bot inventory if later portfolio simulation is included.
- Correlation with other active 5m BTC markets, if overlapping products exist.

## Calibration Model

The baseline probability must be calibrated before it becomes a trading signal.

Primary calibration target:

```text
y = 1 if market resolves Up else 0
```

Candidate models:

- Platt scaling on baseline logit.
- Isotonic regression by time-to-expiry bucket.
- Logistic regression using baseline logit plus selected features.
- Gradient boosted trees for nonlinear effects, constrained by rigorous walk-forward validation.

Recommended first production research model:

```text
logit(P_up_calibrated) =
  beta_0
  + beta_1 * logit(P_up_baseline)
  + beta_2 * btc_momentum_15s
  + beta_3 * btc_momentum_60s
  + beta_4 * volatility_acceleration
  + beta_5 * exchange_depth_imbalance_5bp
  + beta_6 * polymarket_implied_edge
  + bucket_effect(time_to_expiry)
```

Then apply isotonic calibration to the logistic model output within broad time-to-expiry buckets if enough data exists. Keep the simpler Platt-scaled baseline as a benchmark.

Validation rules:

- Use walk-forward splits by date, never random row splits.
- Keep entire markets in the same split.
- Include high-volatility and low-volatility days in out-of-sample tests.
- Report calibration separately by time-to-expiry bucket and distance-to-strike bucket.
- Reject any model whose out-of-sample calibration curve is worse than the random-walk baseline after transaction costs.

Calibration metrics:

- Brier score.
- Log loss.
- Expected calibration error.
- Reliability plots by probability bucket.
- Calibration slope and intercept.
- Resolution and sharpness.

## Strategy Rules

The bot should trade only against executable prices. Model fair value as `P_up_calibrated` and compare it to the actual price needed to enter.

Definitions:

```text
buy_up_edge = P_up_calibrated - ask_up
buy_down_edge = (1 - P_up_calibrated) - ask_down
sell_up_edge = bid_up - P_up_calibrated
sell_down_edge = bid_down - (1 - P_up_calibrated)
```

Initial strategy is long-only on underpriced outcomes:

- Buy Up when `buy_up_edge >= min_edge`.
- Buy Down when `buy_down_edge >= min_edge`.
- Do not short in version 1 unless inventory and borrowing mechanics are explicitly modeled.
- Prefer the side with the larger net edge if both pass.
- Use limit orders at current best ask or one tick inside the spread only when replay confirms realistic fill probability.
- Cancel stale unfilled orders after a short timeout, for example 1-3 seconds.
- Stop entering new positions inside the final expiry safety window unless the backtest proves edge survives latency and oracle uncertainty.

Minimum edge must include:

```text
min_edge = transaction_cost
         + expected_slippage
         + adverse_selection_buffer
         + model_uncertainty_buffer
         + required_profit_margin
```

Start with conservative thresholds:

- Minimum net edge: 3 cents.
- Minimum required expected value per filled share: 2 cents after all costs.
- Maximum spread to enter: 4 cents, unless crossing is explicitly justified by edge.
- Maximum order notional per market: small fixed research cap, then optimize only after stability is proven.
- Maximum total open risk across overlapping markets: capped as a percentage of bankroll.

Sizing:

- Use fractional Kelly only after stable calibration exists.
- Initial research sizing should be fixed notional per signal or capped Kelly with severe shrinkage.
- Example: `size = min(max_notional, bankroll * 0.002, shrunk_kelly_notional)`.
- Set size to zero when model probability is outside calibrated support.

Exit rules:

- Version 1 can hold to resolution if entry edge is the main source of expected value.
- Also test market-making exits: close when expected value becomes negative after spread, or when price reaches target profit.
- Avoid forced exits in the last seconds unless replay shows fills are realistic.

## No-Trade Filters

Hard filters:

- Missing or stale BTC price feed.
- Missing or stale Polymarket orderbook.
- Unknown or unverified market reference price, strike, or expiry.
- Market resolution metadata mismatch.
- Time synchronization uncertainty above threshold.
- Contract spread wider than configured maximum.
- Top-of-book size below minimum tradable size.
- Predicted edge below `min_edge`.
- Inside final expiry safety window.
- Probability outside calibrated support for the current bucket.

Market condition filters:

- BTC within a tiny band around strike near expiry where oracle noise dominates.
- Sudden volatility spike beyond training distribution.
- Exchange spread unusually wide.
- Exchange orderbook depth unusually thin.
- Polymarket book staleness high or update rate abnormal.
- Last trade far from current book, suggesting crossed/stale book.
- Polymarket implied probabilities for Up and Down violate consistency beyond tolerance.
- Major exchange outage, index disruption, or data feed gap.

Portfolio filters:

- Existing exposure in the same market already at cap.
- Daily loss limit reached.
- Consecutive model-error drawdown limit reached.
- Too many unresolved positions in correlated markets.

## Orderbook Replay

Backtests must replay historical orderbook and trade events in chronological order. Candle-only backtests are acceptable only for model prototyping and must not be used for go/no-go trading decisions.

Required data streams:

- Polymarket orderbook snapshots and deltas for both Up and Down contracts.
- Polymarket trades with timestamp, price, size, and side if available.
- BTC reference exchange trades and orderbook, preferably Binance and Coinbase or the exact oracle-relevant source.
- Market metadata: open time, expiry, reference price, resolution source, final outcome.
- System timestamps and capture latency if collected internally.

Replay requirements:

- Normalize all timestamps to UTC with nanosecond or millisecond precision.
- Build a deterministic event loop.
- At each decision event, expose only state known at or before that timestamp.
- Reconstruct best bid/ask and depth after every orderbook delta.
- Validate book consistency: no negative sizes, crossed books flagged, sequence gaps recorded.
- Align BTC prices using last-known state with staleness limits.
- Record decisions, submitted orders, fills, cancels, inventory, and PnL as separate event logs.

Latency model:

- Add configurable decision latency, order submission latency, exchange acknowledgement latency, and cancel latency.
- Test at least p50, p90, and pessimistic latency assumptions.
- Any signal that disappears under p90 latency should not count toward go/no-go.

## Fill Simulation

The fill simulator must be conservative. It should assume the bot joins behind visible size unless historical queue position is known.

Crossing the spread:

- If buying at current ask, fill immediately up to displayed ask size after latency if that ask is still available.
- If price moves before order arrival, fill only if the order limit is marketable at arrival.
- Partial fills must be supported.

Passive orders:

- Estimate queue position from displayed size at the price level when the order arrives.
- Fill only after subsequent trade volume at that price exceeds estimated queue ahead.
- Reduce queue ahead on cancels only with a conservative assumption, for example no benefit from cancels unless order-level data exists.
- Apply partial fills as queue is consumed.
- Cancel requests take effect only after cancel latency.

Adverse selection:

- Track post-fill fair value drift over 1s, 5s, 15s, and to expiry.
- Penalize fills that occur mainly when price moves against the bot.
- Compare passive fill PnL against a model that charges an adverse selection buffer by time-to-expiry bucket.

Fees and costs:

- Include all Polymarket fees, if any, plus blockchain, relayer, or settlement costs relevant to actual execution.
- Include spread paid, slippage, failed order costs if applicable, and capital lockup.
- Report gross and net metrics separately.

## Backtest Experiments

Phase 1: data and label audit

- Verify market metadata and outcomes.
- Compare reference price and final resolution source.
- Measure data gaps and timestamp drift.
- Produce baseline market counts by day, time, volatility regime, and data quality.

Phase 2: probability model

- Train baseline and calibrated models.
- Run walk-forward validation.
- Report calibration and ranking metrics by bucket.
- Compare against Polymarket midpoint as a probability forecast.

Phase 3: signal-only expected value

- Evaluate entries at observed bid/ask without fill constraints.
- Attribute edge by feature bucket, time-to-expiry, and distance-to-strike.
- Remove signals that rely on impossible execution.

Phase 4: full orderbook replay

- Add latency, queue, partial fills, cancels, and costs.
- Test crossing-only, passive-only, and hybrid execution.
- Run sensitivity tests for latency, fill assumptions, spread limits, and edge thresholds.

Phase 5: paper trading shadow test

- Run live data capture and decision logging without orders.
- Compare predicted fills versus observed market prints.
- Recompute all metrics on paper decisions before enabling capital.

## Metrics

Model metrics:

- Brier score.
- Log loss.
- Calibration slope and intercept.
- Expected calibration error.
- ROC AUC and precision by edge bucket, used only as secondary diagnostics.
- Probability stability under small timestamp perturbations.

Trading metrics:

- Net PnL.
- Net return on capital.
- Expected value per trade and per filled share.
- Hit rate by edge bucket.
- Average win, average loss, payoff ratio.
- Sharpe-like return metric by day.
- Maximum drawdown.
- Daily loss distribution.
- Turnover and capital utilization.
- Fill rate and partial fill rate.
- Cancel rate.
- Slippage versus decision price.
- Adverse selection after fill.
- PnL by time-to-expiry bucket.
- PnL by distance-to-strike bucket.
- PnL by volatility regime.
- PnL by execution type: crossed, passive, hybrid.

Robustness metrics:

- Performance under p50, p90, and pessimistic latency.
- Performance after doubling estimated slippage.
- Performance after halving passive fill rate.
- Performance excluding the best 1 percent of trades.
- Performance excluding the best day and best week.
- Performance by month or walk-forward fold.

Operational research metrics:

- Data gap rate.
- Stale book rate.
- Sequence gap count.
- Percentage of markets excluded by filters.
- Percentage of signals rejected by no-trade rules.

## Go/No-Go Criteria

A strategy may proceed from research to paper trading only if all are true:

- Out-of-sample calibrated model improves Brier score and log loss versus the random-walk baseline and Polymarket midpoint benchmark.
- Reliability plots show no severe overconfidence in the traded probability ranges.
- Full orderbook replay is profitable after fees, slippage, latency, and conservative fills.
- Positive net EV persists under p90 latency.
- Positive net EV persists after halving passive fill assumptions or doubling slippage.
- Profit is not dominated by one day, one market condition, or the best 1 percent of trades.
- Maximum drawdown is acceptable relative to expected bankroll and position caps.
- No-trade filters remove stale, inconsistent, and near-oracle-noise situations without eliminating all edge.
- Paper trading reproduces backtest fill rates and slippage within agreed tolerances.

Proceed from paper trading to limited live capital only if:

- At least 2-4 weeks of paper trading show positive expected value by the same metrics.
- Live data capture has no unresolved timestamp, market metadata, or orderbook reconstruction issues.
- Real-time decisions match offline replay of the same captured data.
- Risk caps, daily stop, exposure limits, and kill switch are implemented and tested.

No-go if any are true:

- Calibration is unstable across folds.
- Apparent profit disappears under conservative fill assumptions.
- PnL depends primarily on final seconds around strike without robust oracle modeling.
- Data quality issues prevent deterministic replay.
- The model cannot beat a simple no-trade benchmark after costs.
- Expected value is positive only before fees, spread, or latency.

## Open Research Questions

- Which BTC source best matches the Polymarket resolution oracle for each market?
- Does Polymarket pricing lead or lag exchange price moves at 5 minute horizons?
- Is the edge primarily predictive, liquidity provision, or stale-orderbook capture?
- How often do final-second markets resolve contrary to exchange mid because of oracle/index details?
- Are there systematic user-flow patterns near expiry that create recurring mispricings?
- What is the realistic queue position and fill priority model for the Polymarket venue used?

## First Implementation Milestones

1. Build market metadata and outcome dataset.
2. Build BTC price and volatility feature store with strict timestamp cutoffs.
3. Build Polymarket orderbook reconstruction and validation.
4. Implement baseline random-walk probability model.
5. Add walk-forward calibration.
6. Implement signal-only backtest.
7. Implement event-driven orderbook replay.
8. Add conservative fill simulation.
9. Produce go/no-go report with metrics and sensitivity tests.
