# Decisions

| ID | Decision | Why |
|---|---|---|
| D01 | One loopback service, Python stdlib HTTP/SQLite and a local ES-module UI. | One trusted local workspace; no account system, broker or build-time dependency in the runtime image. |
| D02 | Exchange-native identifiers and one versioned metric catalog; I/O isolated from metric calculations. | HIP-3 names can contain colons. Prices, units, time windows and funding periods must have the same meaning in filters and alerts. |
| D03 | Separate venue polling, historical enrichment and notification delivery. | An unavailable venue or slow notification service must not block the other market or the UI. |
| D04 | Durable compare-and-swap settings updates, rule revisions and a transactional local alert outbox. | Restarts retain state and browser tabs cannot silently overwrite conflicting edits. At-least-once external delivery has an acknowledged duplicate window. |
| D05 | Do not backfill unavailable metrics with proxies except documented Hyperliquid quote-volume estimates. | Missing history must not produce false signals. Live figures are a snapshot, not permanent symbol counts. |
| D06 | Offline tests use a simulated exchange and a real local ntfy receiver; live checks read only public venue data. | Deterministic trigger, restart and duplicate checks without touching production notifications. |
| D07 | Derive all activity windows from exchange minute candles including the forming minute. Only finalized consecutive history is a valid baseline; gaps are unknown. | Matches the observed Binance screener windows; HTTP, SSE and alerts share the same projection. |
| D08 | Import a locally built linux/amd64 image on the DS918+, with explicit LAN bind and a private writable host directory. | Keep Mac image tags independent and the persisted workspace outside both images. |
