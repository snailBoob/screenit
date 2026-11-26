import {
  api,
  fmt,
  metricTone,
  move,
  opName,
  venueName,
  visible,
  matches,
  Workspace,
} from "./model.mjs";
import { $, btn, el, localTime, svg } from "./elements.mjs";
import { spark } from "./charts.mjs";
import { InstrumentChart } from "./instrument-chart.mjs";
import { panels } from "./panels.mjs";
import { enableTablePan } from "./table-pan.mjs";

let w,
  cat,
  meta,
  dialogs,
  venue = "",
  snap,
  channel,
  marketSeq = 0,
  expanded = null,
  chart = null,
  toastTimer,
  needsRender = false,
  lastUi = "",
  refreshing = false;
let previousCells = new Map();
const venueSnapshots = new Map();
const trends = new Map(), pendingTrends = new Set();
function trendFor(symbol) {
  const key = venue + '/' + symbol, cached = trends.get(key);
  if ((!cached || cached.until <= Date.now()) && pendingTrends.size < 3 && !pendingTrends.has(key)) {
    pendingTrends.add(key);
    api('trend?' + new URLSearchParams({exchange:venue, symbol})).then(({end, points}) => {
      trends.set(key, {points, until:end + 1800000});
    }).catch(() => trends.set(key, {points:[], until:Date.now()+30000})).finally(() => {
      pendingTrends.delete(key);
      requestRender();
    });
  }
  return cached?.points ?? [];
}
const rowHeight = 37,
  chartHeight = 401;
function icon(name) {
  const n = svg("svg", { "aria-hidden": "true" });
  n.append(svg("use", { href: "/icons.svg#" + name }));
  return n;
}
const s = () => {
  const conf = w.value;
  return conf.exchange === 'hyperliquid' ? {...conf, filters: conf.hyperliquidFilters, filtersEnabled: conf.hyperliquidFiltersEnabled} : conf;
};
const txt = (id, v) => {
  $(id).textContent = v;
};
function toast(msg) {
  txt("#notice", msg);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => txt("#notice", ""), 6000);
}
function requestRender() {
  if (!needsRender) {
    needsRender = true;
    requestAnimationFrame(() => {
      needsRender = false;
      render();
    });
  }
}
async function market() {
  const ex = s().exchange,
    id = ++marketSeq;
  try {
    const next = await api("market?exchange=" + ex);
    if (id !== marketSeq || ex !== s().exchange) return;
    snap = next;
  } catch {
    if (id !== marketSeq) return;
    snap = {
      ...(snap || { rows: [] }),
      status: "stale",
      message: "Cannot reach the server.",
    };
  }
  requestRender();
}
function set(ch) {
  if (
    "search" in ch ||
    "favoritesOnly" in ch ||
    "filters" in ch ||
    "filtersEnabled" in ch ||
    "exchange" in ch
  )
    $(".table-scroll").scrollTop = 0;
  if ('filters' in ch && s().exchange === 'hyperliquid') {
    const {filters, ...rest} = ch;
    w.set({...rest, hyperliquidFilters: filters});
  } else if ('filtersEnabled' in ch && s().exchange === 'hyperliquid') {
    w.set({hyperliquidFiltersEnabled: ch.filtersEnabled});
  } else w.set(ch);
}
function follow(ex) {
  channel?.close();
  channel = null;
  ++marketSeq;
  if(document.hidden) return;
  if (!window.EventSource) {
    channel = null;
    void market();
    return;
  }
  const source = (channel = new EventSource(
    "/api/market/stream?exchange=" + encodeURIComponent(ex),
  ));
  source.addEventListener("snapshot", (event) => {
    if (source !== channel) return;
    ++marketSeq;
    snap = JSON.parse(event.data);
    requestRender();
  });
  source.addEventListener("quotes", (event) => {
    if (source !== channel || !snap?.rows) return;
    ++marketSeq;
    const { quotes, ...state } = JSON.parse(event.data);
    for (const row of snap.rows) {
      const tick = Object.hasOwn(quotes, row.symbol) && quotes[row.symbol];
      if (!tick || tick[0] <= row.at) continue;
      const [at, values] = tick;
      row.metricAt ??= {};
      for (const key of Object.keys(row.metrics)) row.metricAt[key] ??= row.at;
      for (const [key, val] of Object.entries(values)) {
        if (at >= (row.metricAt[key] ?? 0)) {
          row.metrics[key] = val;
          row.metricAt[key] = at;
        }
      }
      row.at = at;
    }
    Object.assign(snap, state);
    requestRender();
  });
  source.addEventListener('windows', (event) => {
    if (source !== channel || !snap?.rows) return;
    ++marketSeq;
    const {windows,fiveReady}=JSON.parse(event.data);
    for (const row of snap.rows) {
      if (!Object.hasOwn(windows,row.symbol)) continue;
      const [values,times]=windows[row.symbol]; row.metricAt??={};
      for (const [key,value] of Object.entries(values)) {
        if (value===null) {delete row.metrics[key];delete row.metricAt[key];}
        else {row.metrics[key]=value;row.metricAt[key]=times[key];}
      }
    }
    snap.fiveReady=fiveReady;requestRender();
  });
  source.onerror = () => {
    if (source !== channel) return;
    if(source.readyState===EventSource.CLOSED){
      channel=null;
      void market();
      return;
    }
    snap = {
      ...snap,
      status: "stale",
      message: "Live connection interrupted. Reconnecting",
    };
    requestRender();
  };
}
function update() {
  if (venue !== s().exchange) {
    if (snap?.rows?.length) venueSnapshots.set(venue, snap);
    venue = s().exchange;
    previousCells.clear();
    expanded = null;
    chart?.destroy();
    chart = null;
    $(".table-scroll").scrollTop = 0;
    const cached = venueSnapshots.get(venue);
    snap = cached ? {...cached, status: "connecting", message: ""} : { status: "warming", rows: [] };
    follow(venue);
  }
  requestRender();
}
function formatName(id) {
  return (
    meta.get(id)?.label || { symbol: "Symbol", trend: "24h trend" }[id] || id
  );
}
function condLabel(c) {
  return `${formatName(c.metric)} · ${opName[c.op].toLowerCase()} ${c.value}${c.upper !== undefined ? " – " + c.upper : ""}`;
}
const shortNames = {
  change: "Chg %",
  changeUsd: "Chg $",
  volume: "Vol",
  trades: "Trd",
  volatility: "Vlt",
  oiChange: "OI chg %",
  oiDelta: "OI Δ$",
  volumeDelta: "Vol Δ",
  volChange: "Vol chg %",
  volChangeUsd: "Vol chg $",
  correlation: "Cor",
};
function colLabel(k) {
  const [a, b] = k.split(":");
  return b
    ? `${a==='oiDelta' ? (venue==='hyperliquid' ? 'OI value Δ$' : 'OI qty Δ$') : shortNames[a]} (${b})`
    : { oi: "OI $", funding: "Funding/h", rvol: "RVOL", mcap: "MCAP" }[k] ||
        formatName(k);
}
function header(conf) {
  const tr = el("tr");
  const fave = btn(
    null,
    () => set({ favoritesOnly: !s().favoritesOnly }),
    "icon-btn star",
    "Favorites only",
  );
  fave.id = "favorites";
  fave.append(icon("star"));
  fave.setAttribute("aria-pressed", String(conf.favoritesOnly));
  const ctl = el("th", null, "ctl");
  ctl.append(fave);
  tr.append(el("th", null, "ctl"), ctl);
  for (const key of conf.columns) {
    const h = el(
      "th",
      null,
      key === "symbol" ? "sym" : key === "trend" ? "trend" : "",
    );
    if (!h.className) {
      const [group, win] = key.split(":");
      const width =
        {
          price: 115,
          oi: 100,
          funding: 144,
          change: win === "5m" ? 150 : 147,
          volume: 126,
          oiChange: 168,
          volatility: 137,
          trades: 139,
        }[group] || 145;
      h.style.minWidth = width + "px";
    }
    h.scope = "col";
    if (key !== 'trend' && key !== 'symbol') {
      h.draggable = true;
      h.ondragstart = e => {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('application/x-screenit-column', key);
      };
      h.ondragover = e => {
        if (!e.dataTransfer.types.includes('application/x-screenit-column')) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
      };
      h.ondrop = e => {
        const source = e.dataTransfer.getData('application/x-screenit-column');
        if (!s().columns.includes(source) || source===key) return;
        e.preventDefault();
        set({columns: move(s().columns,source,key)});
      };
    }
    if (key === "trend") {
      h.textContent = "24h trend";
      h.title = "Each trend uses its own scale. Gaps indicate missing data.";
    } else {
      const current = key === conf.sort.key;
      h.setAttribute(
        "aria-sort",
        current
          ? conf.sort.dir === "asc"
            ? "ascending"
            : "descending"
          : "none",
      );
      h.append(
        btn(
          colLabel(key),
          () =>
            set({
              sort: {
                key,
                dir: current && s().sort.dir === "desc" ? "asc" : "desc",
              },
            }),
          "",
          `Sort by: ${formatName(key)}`,
        ),
      );
      const control = h.firstElementChild;
      if (h.draggable) {
        const grip = el('span','⋮⋮','grip');
        grip.title = 'Drag to reorder';
        control.prepend(grip);
      }
      const arrows = el("span", null, "sortmarks");
      arrows.setAttribute("aria-hidden", "true");
      arrows.append(
        el("i", "▲", current && conf.sort.dir === "asc" ? "on" : ""),
        el("i", "▼", current && conf.sort.dir === "desc" ? "on" : ""),
      );
      control.append(arrows);
    }
    tr.append(h);
  }
  $("#head").replaceChildren(tr);
}
function star(row, conf) {
  const id = conf.exchange + ":" + row.symbol,
    on = conf.favorites.includes(id);
  const b = btn(
    null,
    () =>
      set({
        favorites: s().favorites.includes(id)
          ? s().favorites.filter((k) => k !== id)
          : [...s().favorites, id],
      }),
    "icon-btn star",
    `Favorite ${row.symbol}`,
  );
  b.append(icon("star"));
  b.setAttribute("aria-pressed", String(on));
  return b;
}
const scheme = matchMedia('(prefers-color-scheme: light)');
const nextTheme = {system:'dark', dark:'light', light:'system'};
let selectionKey, priorMatches = new Map(), graceTimer;
function displayRows(list,conf) {
  const now=Date.now(), minute=Math.floor(now/60000), key=JSON.stringify([conf.exchange,conf.filters,conf.search,conf.favoritesOnly,conf.favorites]);
  if(key!==selectionKey){priorMatches.clear();selectionKey=key;}
  const next=new Map();let waiting=false,held=false;
  const candidates=list.map(r=>{
    let missing=false;
    for(const c of conf.filters){
      const v=r.metrics[c.metric];
      if(!Number.isFinite(v)&&c.metric.endsWith(':5m'))missing=true;
      else if(!matches(v,c))return r;
    }
    if(!missing)return r;
    waiting=true;const old=priorMatches.get(r.symbol);
    if(old && old.minute===minute-1 && now%60000<15000){
      next.set(r.symbol,old);held=true;
      return {...old.row,updating:true};
    }
    return r;
  });
  const rows=visible(candidates,conf);
  for(const r of rows)if(!r.updating){
    const stamps=conf.filters.filter(c=>c.metric.endsWith(':5m')).map(c=>r.metricAt?.[c.metric]??r.at);
    if(stamps.length)next.set(r.symbol,{minute:Math.floor(Math.min(...stamps)/60000),row:{...r,metrics:{...r.metrics},metricAt:{...r.metricAt}}});
  }
  priorMatches=next;clearTimeout(graceTimer);
  if(held)graceTimer=setTimeout(requestRender,15001-now%60000);
  return {rows,waiting};
}
function render() {
  if (!w || !meta) return;
  const conf = s(),
    list = snap?.rows || [],
    {rows:filtered,waiting} = displayRows(list, conf.filtersEnabled ? conf : {...conf, filters: []});
  const theme=conf.theme??'dark', effective=theme==='system'?(scheme.matches?'light':'dark'):theme;
  if(document.documentElement.dataset.theme!==effective){document.documentElement.dataset.theme=effective;chart?.destroy();chart=null;}
  const themeButton=$('#theme');
  if(themeButton.dataset.mode!==theme){themeButton.dataset.mode=theme;themeButton.querySelector('use').setAttribute('href',`/icons.svg#theme-${theme}`);}
  themeButton.title=`Theme: ${theme}. Switch to ${nextTheme[theme]}`;
  themeButton.setAttribute('aria-label',themeButton.title);
  $("#venue-select").value = conf.exchange;
  for (const b of document.querySelectorAll("[data-ex]"))
    b.setAttribute("aria-pressed", String(b.dataset.ex === conf.exchange));
  if ($("#search").value !== conf.search) $("#search").value = conf.search;
  txt(
    "#saved",
    w.busy || Object.keys(w.pending).length ? "Saving" : "",
  );
  txt("#filter-count", conf.filters.length);
  $("#filter-count").hidden = !conf.filters.length;
  $("#filter-count").classList.toggle("paused", !conf.filtersEnabled);
  $("#filter-switch").setAttribute("aria-checked", String(conf.filtersEnabled));
  const hs = JSON.stringify([conf.exchange, conf.columns, conf.sort, conf.favoritesOnly]);
  if (hs !== lastUi) {
    lastUi = hs;
    header(conf);
  }
  const tbody = $("#rows");
  const existing = new Map(Array.from(tbody.rows, row => [row.dataset.instrument, row]));
  const leading = [], trailing = [];
  let fragment = leading,
    showChart = false;
  const scroller = $(".table-scroll"),
    openIdx = expanded ? filtered.findIndex((r) => r.symbol === expanded) : -1;
  if (
    chart &&
    (openIdx < 0 ||
      chart.key !== JSON.stringify([venue, expanded, conf.chartInterval]))
  ) {
    chart.destroy();
    chart = null;
  }
  const offset = (i) =>
    i * rowHeight + (openIdx >= 0 && i > openIdx ? chartHeight : 0);
  const indexAt = (y) =>
    Math.max(
      0,
      Math.floor(
        (openIdx < 0 || y <= (openIdx + 1) * rowHeight
          ? y
          : Math.max((openIdx + 1) * rowHeight - 1, y - chartHeight)) /
          rowHeight,
      ),
    );
  const first = Math.min(
      filtered.length,
      Math.max(0, indexAt(scroller.scrollTop) - 6),
    ),
    end = Math.min(
      filtered.length,
      indexAt(scroller.scrollTop + scroller.clientHeight) + 6,
    );
  function pad(height) {
    if (!height) return;
    const tr = el("tr"),
      td = el("td", null, "pad");
    td.colSpan = conf.columns.length + 2;
    td.style.height = height + "px";
    tr.setAttribute("aria-hidden", "true");
    tr.append(td);
    fragment.push(tr);
  }
  pad(offset(first));
  const cells = new Map(), frameTime = performance.now();
  for (const r of filtered.slice(first, end)) {
    const toggle = () => {
      expanded = expanded === r.symbol ? null : r.symbol;
      requestRender();
    };
    const id = venue + '/' + r.symbol;
    const row = existing.get(id) || el('tr');
    if (!row.cells.length) {
      row.dataset.instrument = id;
      const chartCell = el("td", null, "ctl"), starCell = el("td", null, "ctl");
      const toggleButton = btn(null, toggle, "icon-btn", "Chart " + r.symbol);
      toggleButton.append(icon("chart"));
      chartCell.append(toggleButton);
      starCell.append(star(r, conf));
      row.append(chartCell, starCell);
    }
    row.cells[0].firstChild.setAttribute('aria-expanded', String(expanded === r.symbol));
    row.cells[1].firstChild.setAttribute('aria-pressed', String(conf.favorites.includes(venue + ':' + r.symbol)));
    let index = 2;
    for (const k of conf.columns) {
      const prior = row.cells[index++];
      if (k === 'symbol' && prior?.className === 'sym') {
        prior.firstChild.setAttribute('aria-expanded', String(expanded === r.symbol));
        continue;
      }
      const td = el("td");
      if (k === "symbol") {
        td.className = "sym";
        const b = btn(r.symbol, toggle, "", `Open ${r.symbol}`);
        b.setAttribute("aria-expanded", String(expanded === r.symbol));
        const base = r.symbol
          .replace(/^.*:/, "")
          .replace(/(USDT|USDC|USD)$/, "");
        const known = ["BTC", "ETH", "SOL"].includes(base);
        const badge = el(
          "span",
          known ? null : base.slice(0, 2),
          "coin " + (known ? base.toLowerCase() : ""),
        );
        if (known) badge.append(icon(base.toLowerCase()));
        badge.setAttribute("aria-hidden", "true");
        b.prepend(badge);
        td.append(b);
      } else if (k === "trend") {
        td.className = "trend";
        if (!matchMedia('(max-width:767px)').matches) td.append(spark(trendFor(r.symbol)));
      } else {
        const val = r.metrics[k];
        td.dataset.metric = k;
        const text = fmt(val, meta.get(k)?.unit, k);
        td.textContent = text;
        td.className = metricTone(k, val);
        if (!Number.isFinite(val)) td.title = 'No recent source data';
        else {
          const details=[];
          if (k==='mcap' && r.capSource) details.push(r.capSource);
          if (venue==='hyperliquid' && k.startsWith('volume:') && k!=='volume:1d') details.push('Estimated from base volume × minute close');
          if (k.startsWith('oiDelta:')) details.push(venue==='hyperliquid' ? 'Change in position value, including price changes' : 'Change in quantity at the current valuation');
          if (r.metricAt?.[k]) details.push('Observed: ' + localTime(r.metricAt[k]));
          if (details.length) td.title=details.join(' · ');
          const id = `${r.symbol}\t${k}`, old = previousCells.get(id);
          let until = old?.until ?? 0, flash = old?.flash;
          if (old && old.val !== val && old.text !== text) {
            until = frameTime + 500;
            flash = val > old.val ? 'tick-up' : 'tick-down';
          }
          if (until > frameTime) {
            td.classList.add(flash);
            td.style.animationDuration = (until-frameTime) + 'ms';
          }
          cells.set(id, {val, text, until, flash});
        }
      }
      if (prior) prior.replaceWith(td); else row.append(td);
    }
    while (row.cells.length > index) row.lastChild.remove();
    fragment.push(row);
    if (expanded === r.symbol) {
      if (!chart)
        chart = new InstrumentChart(
          venue,
          expanded,
          conf.chartInterval,
          cat.intervals,
          (i) => set({ chartInterval: i }),
        );
      chart.size(Math.max(1, scroller.clientWidth), conf.columns.length);
      showChart = true;
      fragment = trailing;
    }
  }
  pad(offset(filtered.length) - offset(end));
  previousCells = cells;
  if (!filtered.length && list.length && !waiting) {
    const tr = el("tr"),
      td = el(
        "td",
        "No instruments match your search and filters.",
        "empty",
      );
    td.colSpan = conf.columns.length + 2;
    tr.append(td);
    fragment.push(tr);
  }
  const pivot = showChart ? chart.row : null;
  const keep = new Set([...leading, pivot, ...trailing]);
  for (const row of Array.from(tbody.rows)) if (!keep.has(row)) row.remove();
  if (pivot && pivot.parentNode !== tbody) tbody.append(pivot);
  let anchor = pivot;
  for (const row of leading.reverse()) {
    if (row.parentNode !== tbody || row.nextSibling !== anchor) tbody.insertBefore(row, anchor);
    anchor = row;
  }
  anchor = pivot;
  for (const row of trailing) {
    if (row !== anchor.nextSibling) anchor.after(row);
    anchor = row;
  }

  txt("#result", `${filtered.length}/${list.length} Symbols`);
  const state = snap?.status;
  const updating = waiting || (Number.isInteger(snap?.fiveReady) && snap.fiveReady < list.length);
  $("#dot").className = state === "live" ? "live" : "";
  txt(
    "#connection",
    venueName[venue] +
      " · " +
      ({
        live: updating ? "Updating" : snap?.transport === "stream" ? "Streaming" : "Live snapshot",
        stale: "Stale",
        warming: "Loading data",
        error: "Disconnected",
      }[state] || "Connecting"),
  );
  txt("#coverage", (snap?.message || "").replace(/(?:…|\.{3})$/, ""));
  txt("#asof", snap?.asOf ? "Updated " + localTime(snap.asOf) : "");
}
async function refresh() {
  if (refreshing || !w || document.hidden) return;
  refreshing = true;
  try {
    await Promise.allSettled([
      channel && channel.readyState === EventSource.CONNECTING ? market() : Promise.resolve(),
      api("settings").then((d) => w.receive(d)),
      dialogs.poll(),
    ]);
  } finally {
    refreshing = false;
  }
}
async function boot() {
  try {
    const [catalog, doc] = await Promise.all([api("catalog"), api("settings")]);
    cat = catalog;
    meta = new Map(cat.metrics.map((m) => [m.id, m]));
    w = new Workspace(doc, update, toast);
    dialogs = panels({
      cat,
      s,
      set,
      toast,
      formatName,
      condLabel,
      rows: () => snap?.rows || [],
      count: (n) => {
        txt("#nalerts", n);
        $("#nalerts").hidden = !n;
      },
    });
    $('#theme').onclick=()=>set({theme:nextTheme[s().theme??'dark']});
    scheme.addEventListener('change',requestRender);
    $("#search").oninput = (e) => set({ search: e.target.value });
    $("#venue-select").onchange = (e) => set({ exchange: e.target.value });
    for (const b of document.querySelectorAll("[data-ex]"))
      b.onclick = () => set({ exchange: b.dataset.ex });
    $(".table-scroll").addEventListener("scroll", requestRender, {
      passive: true,
    });
    enableTablePan($(".table-scroll"));
    window.addEventListener("resize", requestRender);
    new ResizeObserver(requestRender).observe($(".table-scroll"));
    $("#filters").onclick = dialogs.filters;
    $("#columns").onclick = dialogs.columns;
    $("#open-alerts").onclick = dialogs.alerts;
    update();
    const other = venue === 'binance' ? 'hyperliquid' : 'binance';
    api('market?exchange=' + other).then(data => {
      if (!data.rows?.length || venueSnapshots.has(other)) return;
      venueSnapshots.set(other, data);
      if (venue === other && snap.status === 'warming' && !snap.rows.length) {
        snap = {...data, status: 'connecting', message: ''};
        requestRender();
      }
    }).catch(() => {});
    void dialogs.poll();
    setInterval(refresh, 6500);
    // Tabs without an SSE slot still receive current market data. Don't let
    // overlapping requests queue up if the link is slow.
    let polling=false;
    setInterval(async()=>{
      if(channel || document.hidden || polling)return;
      polling=true;
      try{await market();}finally{polling=false;}
    },2000);
    document.addEventListener('visibilitychange',()=>follow(s().exchange));
    window.addEventListener("pageshow", (e) => {
      if (e.persisted) follow(s().exchange);
    });
    window.addEventListener("pagehide", () => {
      channel?.close();
      if (!w.busy && Object.keys(w.pending).length)
        fetch("/api/settings", {
          method: "PATCH",
          keepalive: true,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            revision: w.doc.revision,
            changes: w.pending,
          }),
        }).catch(() => {});
    });
  } catch {
    txt("#connection", "Reconnecting");
    txt("#coverage", "Cannot reach the server.");
    setTimeout(boot, 2500);
  }
}
void boot();
