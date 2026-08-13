---
name: tickflow
description: Use TickFlow read-only market-data tools for A-share, Hong Kong, US, ETF, index, and supported futures research.
version: 1.1.0
---

# TickFlow market data

Use the TickFlow plugin tools when the task needs current quotes, historical K-lines, instrument metadata,
market universes, financial statements, or market depth. These tools are read-only and do not place orders.

## Tool selection

- Use `plugin__tickflow__tickflow_get_quotes` for the latest quote of explicitly named symbols.
- Use `plugin__tickflow__tickflow_get_klines` for historical K-lines and adjustment-aware analysis.
- Use `plugin__tickflow__tickflow_get_intraday` only for the current trading day's minute bars.
- Use `plugin__tickflow__tickflow_get_financials` for income, balance-sheet, cash-flow, metrics, or share records.
- Use `plugin__tickflow__tickflow_get_instruments` to verify symbol identity and exchange metadata.
- Use `plugin__tickflow__tickflow_list_universes` and `plugin__tickflow__tickflow_get_universe` to discover symbol pools.
- Use `plugin__tickflow__tickflow_get_depth` for five-level market depth when supported.

## Query rules

1. Use canonical `code.market` symbols, such as `600519.SH`, `00700.HK`, or `AAPL.US`.
2. Prefer one batch call over repeated calls for multiple symbols.
3. Keep the requested symbol set, K-line count, and date range no larger than the task needs, even when the account limit is higher.
4. Use `forward` adjustment for return-oriented historical analysis unless the user requests another basis.
5. Use `forward_additive` when the user explicitly wants prices aligned with common Chinese quote software.
6. For a financial trend, set `latest=false` and provide a bounded start or end date. For a snapshot, keep `latest=true`.
7. Inspect `cache.status` on every successful result. `retrieved_at` is the original API fetch time and `served_at` is the current Tool response time. Use timestamps inside `data` when stating when a market value was observed.
8. State the market, symbol, period, adjustment basis, data time, and whether the result came from cache in conclusions. Never present cached or historical data as newly fetched live data.
9. Do not claim that a market-data result is investment advice or a guaranteed future outcome.

## Account limits

- Real-time quotes by explicit symbols: 300 requests/minute and 500 symbols/request.
- Daily K-lines (`1d`, `1w`, `1M`, `1Q`, `1Y`): batch 120 requests/minute with 200 symbols/request; single-symbol 300 requests/minute.
- Minute K-lines (`1m`, `5m`, `15m`, `30m`, `60m`): batch 60 requests/minute with 200 symbols/request; single-symbol 120 requests/minute; up to 10000 bars and 365 days of history.
- Current-day intraday bars: batch 60 requests/minute with 200 symbols/request; single-symbol 120 requests/minute.
- Five-level market depth: batch 60 requests/minute with 200 symbols/request; single-symbol 120 requests/minute.
- Financial data: 120 requests/minute and 100 symbols/request.

The K-line and depth tools automatically use the single-symbol endpoint for one symbol and the batch endpoint for multiple symbols.

## Shared cache

All TickFlow Tool results share the workspace cache at `.cache/tickflow/responses.sqlite3`. A valid cached response is returned before API credentials or the network client are used. Cache entries are keyed by the complete normalized operation and request and never contain the API key.

- Explicit historical K-line ranges ending before the current bar do not expire automatically.
- Moving K-line queries expire at the current period policy; current-day intraday data expires at the next minute boundary.
- Real-time quotes expire after 10 seconds and market depth expires after 5 seconds.
- Financials, instruments, and universes expire after 24 hours.

## Credentials and failures

The plugin reads the API key named `TickFlow` from the workspace `.auth/api-keys/aliases.json` store.
Never request, display, copy, or persist the secret. If the alias is missing, authentication fails, access is denied,
or TickFlow rate-limits the request, report the returned error directly and ask the user to remediate that condition.
