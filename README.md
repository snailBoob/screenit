# SCREENIT. 1.1.6

A local perpetual futures screener for Binance USDⓈ-M and Hyperliquid, including HIP-3. One shared workspace, server-side autosave and background alerts. No exchange account or trading credentials required.

## Run

**Docker:** The public image is `ghcr.io/snailboob/screenit:1.1.6` (Linux amd64 and arm64). To download it directly, run `docker pull ghcr.io/snailboob/screenit:1.1.6`. No registry login is required.

**Mac (Apple Silicon or Intel):** Start [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/). Place `compose.yaml` in `~/Docker/screenit` and preserve your `data/`, `.env` and `compose.override.yaml`.

From Terminal:

```sh
cd ~/Docker/screenit && docker compose pull && docker compose up -d --wait && open http://localhost:8080
```

**Synology DS918+:** On the Mac run `sh scripts/build-ds918.sh` from the updated source directory. The script builds and checks `linux/amd64` and exports the image to `~/Downloads/screenit-ds918-1.1.6/`. For a first-time migration, `sh scripts/export-mac-data.sh` copies the stopped Mac workspace into the export. If the workspace is already on the NAS, keep it. Follow the [NAS project and storage instructions](deploy/ds918/INSTALL.md): put `compose.yaml` in `/Docker/screenit`, beside the existing `data/` folder. No public image registry is required.

For an existing Docker Desktop installation in `~/Docker/screenit`, run `sh scripts/mac-storage.sh` once to keep the workspace in `~/Docker/screenit/data`. The migration stops Screenit before copying its SQLite files, keeps the original volume, and creates a local `compose.override.yaml`. Keep both `data/` and that override when updating the app. The host data directory survives container and volume removal.

For a standalone installation, use Python 3.11 or later:

```sh
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt
.venv/bin/python -m src.app
```

Under **Alerts → + Add → Use ntfy**, enter a **Server URL** and a **Topic** for this alert. The switch is off by default. Subscribe to that server and topic in ntfy. History, browser notifications and ntfy share the same title and message, for example `High volume` / `BTCUSDT — RVOL is above 2`.

## Live updates

The server maintains public WebSocket connections to Binance and Hyperliquid, including HIP-3 contexts. Open browsers receive Server-Sent Events and reconnect automatically. A new connection receives a complete snapshot, followed by price updates. The footer shows **Streaming** for exchange updates and **Live snapshot** for the HTTP fallback. Data follows each exchange's publication cadence; slower metrics retain their original timestamps. An expanded chart fetches fresh candles independently of the price stream.

## Workspace

- Choose an exchange, search by native symbol, and star contracts to add them to Favorites. `xyz:NVDA` and `NVDAUSDT` are separate instruments. The market summary covers the selected venue; the result count reflects your filters.
- Choose **Columns** to set the metrics and time windows. Reorder columns using the arrows or drag their headers; click a header to sort. Missing values sort last in either direction.
- In **Filters**, choose a metric, comparison and threshold (two bounds for a range). Click **Add Filter**. Active rules appear at the top of the popover; remove one with **×** or use **Clear all**. Each exchange has its own saved filters. Existing filters stay on Binance when upgrading; Hyperliquid starts empty. Contracts must match every active filter on the selected exchange. Click an instrument for an OHLC chart with six intervals.
- The six interval shortcuts are shared between instruments. Binance embeds TradingView's Advanced Chart with its native toolbar, indicators, price styles and navigation; opening it requires access to TradingView. Hyperliquid has the interval shortcuts overlaid on a local candlestick and volume chart with wheel/pinch zoom, horizontal drag and price-axis scaling. This chart uses [TradingView Lightweight Charts™](https://www.tradingview.com/lightweight-charts/) (Copyright © 2026 TradingView, Inc., Apache License 2.0).
- **Alerts → + Add** lets you choose an exchange and select symbols from search, or leave the selection empty for all instruments. Selecting multiple symbols creates one rule per symbol. The name is optional. Conditions within a group use AND; groups use OR. The preview summarizes the trigger before creation. Absolute price and dollar price change require a single selected instrument. **Repeat** reveals the cooldown (1, 5, 15 or 30 minutes, 1 or 4 hours). **Sound** applies to browser playback. Server-side evaluation and ntfy delivery continue when the browser is closed. Browser notifications require a secure browser context and permission.
- Valid edits save automatically. If two browsers edit the same setting, Screenit reports the conflict and keeps the server version. Alert history shows the latest 500 events, marked **Queued**, **Sent** or **Failed**.

## Data definitions

| Metric | Definition and coverage |
|---|---|
| Price and daily volume | Binance uses last trade price and rolling quote volume. Hyperliquid uses mark price and rolling notional volume. USD stablecoin quotes are displayed without FX conversion. |
| Price change | Binance `CHG % (1d)` uses the exchange ticker's rolling 24-hour price change, available without candle history. Other percentage changes use minute candles: compare the forming minute's close with the first minute's open on Binance and close on Hyperliquid. `CHG $` uses the venue ticker price × the candle window's percentage change / 100. Both inputs must be available. |
| OHLC and trend | The latest exchange candle may still be open. Each sparkline has its own scale, with up to 24 hours of half-hour samples. Missing data leaves gaps. |
| Volume, trades and delta | For 5m: four finalized consecutive exchange minutes plus the forming minute, replaced on every revision. Longer windows use the same rule. Binance signed delta = twice taker-buy quote volume minus total quote volume. Hyperliquid estimated minute turnover = base volume × close; no signed taker split is published. `VOL (1d)` is the venue's rolling ticker turnover. |
| Volume change and RVOL | Binance compares the live total with the preceding equal number of finalized minutes (no deliberate display delay). Hyperliquid compares rolling daily notional turnover now vs the recorded observation in the matching historical minute. Absolute change works with a zero prior total; percentage requires a positive denominator. RVOL = five-minute turnover / (turnover in 1440 consecutive exchange minutes / 288). |
| Volatility and BTC correlation | Each window contains one exchange candle per minute, including the forming minute. Volatility is the sample standard deviation of consecutive close-to-close log returns, in percent. BTC correlation uses Pearson's coefficient on aligned simple returns against BTC on the same venue. A 15-minute window therefore has 14 returns. Missing input leaves the affected window unavailable; a constant series has no correlation. |
| Open interest | Binance collects current exchange OI at its own timestamp and values it with a recent ticker. Stored observations and exchange five-minute history provide the nearest available historical quantity (max 150s from the historical target). `OI qty Δ$` values the change in quantity at the current valuation. On Hyperliquid `OI value Δ$` includes price changes: current quantity × mark minus previous quantity × previous mark. `OI CHG %` compares quantities. Context history for HL is collected locally and persists across restarts. |
| Funding and market cap | Funding is percent per hour. Market caps use CoinGecko's exchange-specific contract→coin IDs and batched USD market cap (not FDV). The same coin on two venues shares the same cap; ambiguous or unmapped contracts show a dash. For supported mapped US stocks, an optional Finnhub key enables company capitalization. No company cap is inferred for ETFs, indices or commodities. Caps are refreshed hourly and stored locally. The tooltip names the source and shows its timestamp (retrieval time for Finnhub); after two hours without a recent value the metric is unavailable. |

Minute candles stream independently of the browser. Paced REST workers seed short history across the market and backfill longer windows, including up to two days for Binance volume comparisons. The footer shows the app version. The live status reads Updating while the selected exchange is loading initial five-minute data or waiting for filter data. Longer windows and infrequently traded symbols may take longer. Explicit zero-trade candles count as zero activity; missing history stays `—` until repaired. A price update never renews the source time of older activity, OI or market cap. Cells, filters and background alerts consume the same server observations. Absolute ticker values need not match another provider's differently timed snapshots.

SQLite stores workspace settings, rules, alert state and the delivery queue. Market history is stored separately. A trigger and its queue entry are written together. Delivery is attempted up to five times. If ntfy receives a message but the server loses the acknowledgement, an external duplicate is possible.

With **Repeat** on, a level such as **Is Above** fires again on a fresh matching observation after each cooldown, even if the value never dropped below the threshold. **Crosses Above/Below** requires another actual crossing after the cooldown. The cooldown is per rule and symbol, defaults to five minutes, and survives a restart. With **Repeat** off, each symbol fires only once.

On a Mac, alerts require Docker Desktop to be running and the computer to be awake. Use `docker compose start` after a stop. Avoid `docker compose down -v` if you want to keep your workspace. In the 24h trend column, a grey line means the half-hour history is incomplete or the first and last prices are equal; a dash means fewer than two usable observations.

## Configuration

| Variable | Purpose |
|---|---|
| `SCREENIT_HOST_PORT` | Compose host port; default 8080. |
| `SCREENIT_DATA`, `SCREENIT_PORT`, `SCREENIT_BIND` | Standalone data directory, port and bind address; defaults: `data/`, 8080 and `127.0.0.1`. |
| `SCREENIT_NTFY_TOKEN` | Optional token sent only to the exact destination set in `SCREENIT_NTFY_TRUSTED_URL` (full server and topic URL). |
| `SCREENIT_ALLOWED_HOSTS` | Additional trusted Host names, comma-separated. |
| `SCREENIT_MARKET_CAP` | Set to `0` to disable all market cap providers. |
| `SCREENIT_COINGECKO_KEY` | Optional CoinGecko Demo API key (server only). Anonymous access is subject to provider limits. |
| `SCREENIT_FINNHUB_KEY` | Optional Finnhub API key for supported equity profiles. Store it locally in `.env`, outside the image. |
| `SCREENIT_POLL_SECONDS` | Delay between full REST refreshes; default 30 seconds, minimum 10. Independent of streaming quotes. |

## Verification

`GET /api/health` returns service and exchange status. Frontend assets are served locally. Node and Chromium are only needed for development tests.

```sh
python3 scripts/verify.py
npm ci
npx playwright-core install chromium
node tests/e2e/browser.cjs
```

The browser test starts a temporary app, real SQLite storage and a loopback ntfy receiver. Linux must have the system libraries Chromium requires. For a separate read-only public feed check, run `python3 scripts/live_smoke.py`.

## License

Original Screenit code is available under the [MIT License](LICENSE). TradingView Lightweight Charts is distributed under [Apache-2.0](src/ui/lightweight-charts-license.txt); the Inter font is distributed under the [SIL Open Font License](src/ui/inter-license.txt). Exchange data, third-party marks and hosted chart services are not licensed by this project.
