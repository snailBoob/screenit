const { chromium } = require("playwright-core");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const assert = require("node:assert/strict");
const { once } = require("node:events");
const { setTimeout: delay } = require("node:timers/promises");
const root = path.resolve(__dirname, "../.."),
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "screenit-e2e-"));
const price = path.join(tmp, "price");
fs.writeFileSync(price, "90");
let srv, serverExit, b, base;
const errors = [];
async function fixture() {
  srv = spawn("python3", ["-m", "tests.e2e.fixture", tmp], {
    cwd: root,
    stdio: ["ignore", "pipe", "inherit"],
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });
  serverExit = once(srv, "exit");
  const text = await Promise.race([
    once(srv.stdout, "data").then(([c]) => String(c).trim()),
    serverExit.then(() => {
      throw Error("Fixture exited before readiness");
    }),
  ]);
  assert.match(text, /^\d+$/);
  base = "http://127.0.0.1:" + text;
}
async function stop() {
  if (srv && srv.exitCode === null) {
    srv.kill("SIGTERM");
    await serverExit;
  }
  srv = null;
}
async function until(fn, label, ms = 7000) {
  const end = Date.now() + ms;
  do {
    if (await fn()) return;
    await delay(60);
  } while (Date.now() < end);
  throw Error("Timeout: " + label);
}
const read = async (key) => (await fetch(base + "/api/" + key)).json();
async function tab(width, height) {
  const ctx = await b.newContext({ viewport: { width, height } });
  const p = await ctx.newPage();
  p.setDefaultTimeout(6000);
  p.on("pageerror", (e) => errors.push(e.message));
  await p.goto(base);
  return [ctx, p];
}
(async () => {
  await fixture();
  b = await chromium.launch({ headless: true });
  let [ctx, p] = await tab(1440, 900);
  await p.getByRole("button", { name: "Chart BTCUSDT" }).waitFor();
  assert.equal(await p.locator("html").getAttribute("lang"), "en");
  assert.match(await p.locator('#asof').innerText(), /^Updated \d\d:\d\d:\d\d$/);
  const row = p
    .getByRole("row")
    .filter({ has: p.getByRole("button", { name: "Chart BTCUSDT" }) });
  const firstValue = await row.locator('[data-metric="price"]').innerText();
  assert.match(await p.locator('#connection').innerText(), / · Updating$/);
  const icons = await row.locator('.ctl svg, .sym .coin').elementHandles();
  // The row is stable; its metric cells are replaced on every tick. Resolve
  // the live cell and read its style in the same browser turn.
  const color = (metric) => row.evaluate((tr, key) => getComputedStyle(tr.querySelector(`[data-metric="${key}"]`)).color, metric);
  assert.equal(await color('funding'), 'rgb(128, 128, 128)', 'small positive hourly funding is neutral');
  fs.writeFileSync(price + ".next", "93");
  fs.renameSync(price + ".next", price);
  await until(
    async () =>
      (await row.locator('[data-metric="price"]').innerText()) !== firstValue,
    "price changes on the open page without a reload",
    4000,
  );
  await until(async () => (await color('price')) === 'rgb(212, 212, 212)', 'a price returns to neutral after its tick');
  assert.match(await p.locator('#connection').innerText(), / · (Streaming|Live snapshot)$/);
  assert.equal(icons.length, 3);
  for (const icon of icons) assert.ok(await icon.evaluate(n => n.isConnected), 'left icon survives a live price update');
  await p.getByRole("button", { name: "Favorite BTCUSDT" }).click();
  await p.route("https://www.tradingview-widget.com/**", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: '<html lang="en"></html>',
    }),
  );
  await p.getByRole("button", { name: "Chart BTCUSDT" }).click();
  const widget = p.locator(".chartbox iframe");
  await widget.waitFor();
  const options = JSON.parse(
    decodeURIComponent(new URL(await widget.getAttribute("src")).hash.slice(1)),
  );
  assert.equal(options.symbol, "BINANCE:BTCUSDT.P");
  assert.equal(options.hide_top_toolbar, false);
  const intervals = ["1m", "5m", "15m", "1H", "4H", "1D"];
  assert.deepEqual(
    await p.locator(".chartbox button").allTextContents(),
    intervals,
  );
  let releaseStream;
  const heldStream = new Promise(resolve => {releaseStream = resolve;});
  await p.route('**/market/stream?exchange=hyperliquid', async route => {
    await heldStream;
    await route.continue();
  }, {times:1});
  await p.locator('[data-ex="hyperliquid"]').click();
  try {
    await p.getByRole("button", { name: "Chart BTC", exact: true }).waitFor();
  } finally {releaseStream();}
  await p.getByRole("button", { name: "Chart BTC", exact: true }).click();
  await p.getByRole("img", { name: /BTC candlestick chart/ }).waitFor();
  assert.deepEqual(
    await p.locator(".chartbox button").allTextContents(),
    intervals,
  );
  const host = p.locator(".chart-host"),
    plot = host.locator("canvas").first();
  await p.waitForFunction(
    () => Number(document.querySelector(".chart-host")?.dataset.from) > 0,
  );
  await plot.scrollIntoViewIfNeeded();
  const box = await plot.boundingBox(),
    x = box.x + box.width * 0.5,
    y = box.y + box.height * 0.5;
  const range = () =>
    host.evaluate((h) => [Number(h.dataset.from), Number(h.dataset.to)]);
  const [start, end] = await range();
  const span = end - start;
  await p.mouse.move(x, y);
  await p.mouse.wheel(0, -450);
  await until(async () => {
    const [a, b] = await range();
    return b - a < span;
  }, "wheel zooms the date axis");
  const drag = async () => {
    await p.mouse.move(box.x + box.width * 0.2, y);
    await p.mouse.down();
    await p.mouse.move(box.x + box.width * 0.8, y, { steps: 12 });
    await p.mouse.up();
  };
  await drag();
  await until(
    async () => (await range())[1] < end - 3600,
    "drag reveals earlier candles",
  );
  const oldRange = await range(),
    latest = Number(await host.getAttribute("data-latest-time"));
  fs.writeFileSync(path.join(tmp, "clock"), String((latest + 900) * 1000));
  await until(
    async () => Number(await host.getAttribute("data-latest-time")) > latest,
    "next live candle while viewing history",
    9000,
  );
  assert.deepEqual(
    await range(),
    oldRange,
    "new candle must not move the historical viewport",
  );
  let historyResponse;
  const listener = (r) => {
    if (
      !historyResponse &&
      r.url().includes("/api/candles?") &&
      r.url().includes("before=")
    )
      historyResponse = r;
  };
  p.on("response", listener);
  for (let i = 0; i < 14 && !historyResponse; i++) await drag();
  await until(() => historyResponse, "older candles requested");
  assert.equal(historyResponse.status(), 200);
  const oldPage = (await historyResponse.json()).candles;
  assert.ok(
    oldPage.length &&
      oldPage.at(-1).t <
        Number(new URL(historyResponse.url()).searchParams.get("before")),
  );
  await drag();
  assert.ok((await range())[0] < oldPage.at(-1).t / 1000, "older page visible");
  p.off("response", listener);
  await p.getByRole("button", { name: "1H", exact: true }).click();
  await until(
    async () => (await read("settings")).settings.chartInterval === "1h",
    "chart interval autosave",
  );
  await p.locator('[data-ex="binance"]').click();
  await p.getByRole("button", { name: "Chart BTCUSDT" }).click();
  await widget.waitFor();
  assert.equal(
    JSON.parse(
      decodeURIComponent(
        new URL(await widget.getAttribute("src")).hash.slice(1),
      ),
    ).interval,
    "60",
  );
  await p.locator("#filters").click();
  await p.getByLabel("Threshold").click();
  await p.keyboard.type('2');
  assert.equal(await p.getByLabel("Threshold").inputValue(), '2');
  await p.getByRole("button", { name: "Add filter" }).click();
  const filterSwitch = p.getByRole('switch', {name:'Apply filters'});
  await filterSwitch.click();
  await p.getByRole('button', {name:'Chart ETHUSDT'}).waitFor();
  assert.equal(await p.locator('#filter-count.paused').innerText(), '1');
  const addFilter = p.getByRole('button', {name:'Add Filter', exact:true});
  for (let i = 1; i < 9; i++) await addFilter.click();
  assert.ok(await addFilter.isDisabled());
  await until(async () => (await read('settings')).settings.filters.length === 9, 'nine filters saved');
  const saved = await read('settings');
  const overflow = await fetch(base + "/api/settings", {
    method: "PATCH", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({revision:saved.revision, changes:{filters:[...saved.settings.filters, saved.settings.filters[0]]}}),
  });
  assert.equal(overflow.status, 400);
  const removeFilter = p.getByRole('button', {name:/Remove filter:/}).last();
  for (let i = 9; i > 1; i--) await removeFilter.click();
  assert.ok(await addFilter.isEnabled());
  await filterSwitch.click();
  await p.getByRole('button', {name:'Chart ETHUSDT'}).waitFor({state:'hidden'});
  await p.getByRole("button", { name: "Close" }).click();
  await until(
    async () => (await read("settings")).settings.filters[0]?.value === 2,
    "filter saved",
  );
  assert.equal(
    await p.getByRole("button", { name: "Chart ETHUSDT" }).count(),
    0,
  );
  await p.locator("#columns").click();
  await p.getByRole("button", { name: "Core only" }).click();
  await p.getByRole("button", { name: "Close" }).click();
  await until(
    async () => (await read("settings")).settings.columns.includes("mcap"),
    "column autosave",
  );
  await p.getByRole("button", { name: "Sort by: Price" }).click();
  await p.locator("#open-alerts").click();
  await p.locator('#search').click();
  assert.ok(await p.locator('#alert-panel').isHidden());
  await p.locator("#open-alerts").click();
  await p.getByRole("button", { name: "New alert", exact: true }).click();
  assert.equal(
    await p.getByRole("button", { name: "Create Alert" }).isDisabled(),
    true,
  );
  assert.equal(
    await p.getByLabel("Metric", { exact: true }).inputValue(),
    "price",
  );
  assert.equal(
    await p
      .getByRole("switch", { name: "Repeat", exact: true })
      .getAttribute("aria-checked"),
    "false",
  );
  await p.getByRole("switch", { name: "Repeat", exact: true }).click();
  assert.equal(
    await p.getByLabel("Cooldown", { exact: true }).inputValue(),
    "300000",
  );
  await p.getByLabel("Cooldown", { exact: true }).selectOption("60000");
  await p.getByLabel("Sound", { exact: true }).selectOption("ding");
  assert.equal(await p.getByPlaceholder('Server URL').count(), 0);
  await p.getByRole('switch',{name:'Use ntfy'}).click();
  await p.getByPlaceholder('Server URL').fill(fs.readFileSync(path.join(tmp,'ntfy-url'),'utf8'));
  await p.getByPlaceholder('Topic').fill('price-test');
  const arrow = await p.locator('#collapse-alerts').boundingBox(), preview = await p.locator('.trigger-preview').boundingBox();
  assert.ok(preview.x > arrow.x + arrow.width, 'collapse arrow clears the form');
  await p.getByLabel("Name", { exact: true }).fill("Price threshold");
  await p.getByLabel("Instrument", { exact: true }).fill("BTCUSDT");
  await p
    .locator(".symbol-results")
    .getByRole("button", { name: "BTCUSDT", exact: true })
    .click();
  await p.getByLabel("Metric", { exact: true }).selectOption("price");
  await p.getByLabel("Comparison", { exact: true }).selectOption("cross_up");
  await p.getByLabel("Threshold", { exact: true }).click();
  await p.keyboard.type('100');
  assert.equal(await p.getByLabel("Threshold", { exact: true }).inputValue(), '100');
  await p.getByRole("button", { name: "Create alert" }).click();
  await p
    .locator(".rule-card")
    .getByText("Price threshold", { exact: true })
    .waitFor();
  const persisted = (await read("alerts")).rules[0];
  assert.equal(persisted.sound, "ding");
  assert.equal(persisted.cooldownMs, 60000);
  assert.equal((await read("history")).events.length, 0);
  await p.getByRole("button", { name: "Close alerts" }).click();
  if (process.env.SCREENIT_SHOTS) {
    fs.mkdirSync(process.env.SCREENIT_SHOTS, { recursive: true });
    await p.screenshot({
      path: path.join(process.env.SCREENIT_SHOTS, "desktop.png"),
    });
  }
  await ctx.close();
  await delay(420);
  fs.writeFileSync(price + ".next", "120");
  fs.renameSync(price + ".next", price);
  await until(
    async () => (await read("history")).events[0]?.delivery === "sent",
    "background alert delivered",
  );
  assert.match(
    fs.readFileSync(path.join(tmp, "delivered"), "utf8"),
    /\/price-test BTCUSDT — PRICE crossed above 100/,
  );
  await stop();
  await fixture();
  [ctx, p] = await tab(390, 844);
  await p.getByRole("button", { name: "Chart BTCUSDT" }).waitFor();
  assert.equal(
    await p
      .getByRole("button", { name: "Favorite BTCUSDT" })
      .getAttribute("aria-pressed"),
    "true",
  );
  assert.equal((await read("settings")).settings.sort.key, "price");
  assert.equal(
    await p.getByRole("button", { name: "Chart ETHUSDT" }).count(),
    0,
  );
  assert.equal(
    await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    true,
  );
  if (process.env.SCREENIT_SHOTS)
    await p.screenshot({
      path: path.join(process.env.SCREENIT_SHOTS, "mobile.png"),
    });
  await p.locator("#open-alerts").click();
  await p.getByRole("button", { name: "History", exact: true }).click();
  await p.getByText("Sent", { exact: true }).waitFor();
  assert.equal((await read("history")).events.length, 1);
  await p.getByRole("button", { name: "Close alerts" }).click();
  await p
    .getByRole("combobox", { name: "Exchange" })
    .selectOption("hyperliquid");
  await p.getByRole("button", { name: "Chart BTC", exact: true }).waitFor();
  await p.getByRole("button", { name: "Chart xyz:NVDA" }).waitFor();
  assert.ok(await p.locator('#filter-count').isHidden());
  await p.locator("#filters").click();
  await p.getByLabel('Threshold').fill('4');
  await p.getByRole('button',{name:'Add filter'}).click();
  await p.getByRole("button", { name: "Close", exact: true }).click();
  await until(
    async () => (await read("settings")).settings.hyperliquidFilters[0]?.value === 4,
    "Hyperliquid filter saved",
  );
  await p.reload();
  await p.getByRole('button',{name:'Chart BTC',exact:true}).waitFor();
  assert.equal(await p.getByRole('button',{name:'Chart xyz:NVDA'}).count(),0);
  await p.getByRole('combobox',{name:'Exchange'}).selectOption('binance');
  await until(async () => (await read('settings')).settings.exchange==='binance','Binance selected');
  assert.equal((await read('settings')).settings.filters[0].value,2);
  const A = { metric: "change:1h", op: "gt", value: 2 },
    B = { metric: "oi", op: "gt", value: 999 };
  const seed = await fetch(base + "/api/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      revision: (await read("settings")).revision,
      changes: { filters: [A, B] },
    }),
  });
  assert.equal(seed.status, 200);
  await p.reload();
  await p.locator("#filters").click();
  await p.getByText("OI $ > 999", { exact: true }).waitFor();
  const concurrent = await fetch(base + "/api/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      revision: (await read("settings")).revision,
      changes: { filters: [B] },
    }),
  });
  assert.equal(concurrent.status, 200);
  await p.waitForFunction(
    () => document.querySelector("#filter-count")?.textContent === "1",
    null,
    { timeout: 15000 },
  );
  await p.getByRole("button", { name: "Clear all" }).click();
  await p
    .getByRole("alert")
    .filter({ hasText: /elsewhere/i })
    .waitFor();
  assert.deepEqual((await read("settings")).settings.filters, [B]);
  assert.deepEqual(errors, []);
  await ctx.close();
  console.log(
    "PASS desktop/mobile: chart, autosave, filters, favorites, columns, sorting, two simultaneous workspaces preserve concurrent filter edits, HIP-3, restart, cross alert while browser closed, delivery to loopback ntfy, no duplicate.",
  );
})()
  .catch((e) => {
    console.error(e);
    process.exitCode = 1;
  })
  .finally(async () => {
    if (b) await b.close();
    await stop();
    fs.rmSync(tmp, { recursive: true, force: true });
  });
