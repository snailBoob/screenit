# Screenit v1 — approved product requirements

Source: owner discussion and local build approval, 2026-11-24. This register owns the scope and acceptance IDs. Orion was inspected as a reference, not a runtime dependency. Its four presets and account system are expressly excluded.

| Requirement | Complete when | Acceptance |
|---|---|---|
| `market-coverage` | Discover active Binance USDⓈ-M perpetuals, Hyperliquid main and deployed HIP-3 perps; keep venue and instrument identities distinct, handle an unavailable exchange independently. | `feed-check` |
| `market-metrics` | Supply timestamped price, turnover, funding, OI, windowed activity and OHLC charts where source data permits. Unknowns and insufficient history stay unavailable, never silently zero. Document formulae and coverage. | `metric-check` |
| `screen-workspace` | User can search, filter by metric and range, sort, favorite, change column order/visibility, choose time windows, see sparklines and expand an interval chart on desktop and mobile. | `screen-check` |
| `durable-workspace` | One workspace, no login or presets. Valid complete edits autosave on the server, survive reopening and restart; concurrent stale writes cannot silently overwrite another browser. | `store-check` |
| `background-alerts` | Rules target one instrument or an exchange, support AND/OR, thresholds, crossings, ranges and repeat policy. Without a browser, record a valid trigger and delivery state. Missing/stale observations cannot trigger or invent a crossing. | `alert-check` |
| `notify-topic` | Optionally publish the alert title and matched conditions to the server and topic selected on that rule. Surface delivery failure and bound retries. Never send real notifications in the test suite. | `notify-check` |
| `local-container` | One local service, durable volume, no broker, no database account or external UI assets. Tested local HTTP/browser flows; Docker start is a separate deploy-host check as approved. | `runtime-check`, `browser-check` |

Architecture/data contracts are reviewed against `contract-check`; independent integration review uses `review-check`. No trades, broker account, named preset collection or remote deployment is in scope.

0.1.3 adds cumulative live-minute windows and explicit gap recovery on both venues; venue-specific OI value, quantity and notional-volume comparisons; provider-identified market caps; and a Mac-built linux/amd64 export for the owner's DS918+. NAS access is limited to the trusted LAN/VPN. The Synology uses a separate persisted workspace unless the stopped Mac database is copied across.
