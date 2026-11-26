import { btn, el } from "./elements.mjs";

const PAGE = 499;
const up = "#00ff9c",
  down = "#ff305a";
function chartPalette() {
  const styles = getComputedStyle(document.documentElement);
  const color = name => styles.getPropertyValue(name).trim();
  return { background: color('--bg'), grid: color('--edge'), border: color('--edge-strong'), label: color('--dim') };
}
const tvInterval = {'1m':'1','5m':'5','15m':'15','1h':'60','4h':'240','1d':'D'};
function binanceWidget(symbol,interval){
  const url=new URL('https://www.tradingview-widget.com/embed-widget/advanced-chart/');
  const palette = chartPalette();
  url.searchParams.set('locale','en');
  url.hash=encodeURIComponent(JSON.stringify({symbol:`BINANCE:${symbol}.P`,interval:tvInterval[interval],autosize:true,timezone:'Etc/UTC',theme:document.documentElement.dataset.theme||'dark',style:'1',allow_symbol_change:false,hide_side_toolbar:true,hide_top_toolbar:false,hide_legend:false,hide_volume:false,save_image:false,details:false,hotlist:false,backgroundColor:palette.background,gridColor:palette.grid,watchlist:[],compareSymbols:[],studies:[],withdateranges:false,width:'100%',height:'100%'}));
  const frame=el('iframe');frame.title=`${symbol} TradingView Advanced Chart`;frame.referrerPolicy='no-referrer';frame.src=url.href;return frame;
}
const candle = (b) => ({
  time: b.t / 1000,
  open: b.o,
  high: b.h,
  low: b.l,
  close: b.c,
});
const volume = (b) => ({
  time: b.t / 1000,
  value: b.v,
  color: b.c >= b.o ? "#086547" : "#863043",
});
const date = (t) =>
  new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ");

// One chart instance per expanded instrument/interval. Its canvas, gestures
// and viewport are independent of the constantly rearranging market table.
export class InstrumentChart {
  constructor(exchange, symbol, interval, intervals, choose) {
    this.key = JSON.stringify([exchange, symbol, interval]);
    this.params = { exchange, symbol, interval };
    this.data = [];
    this.abort = new AbortController();
    this.row = el("tr");
    this.cell = el("td", null, "chartcell");
    this.row.append(this.cell);
    this.box = el("div", null, "chartbox");
    this.box.dataset.venue=exchange;
    this.cell.append(this.box);
    const bar = el("div", null, "chart-toolbar"),
      periods = el("div", null, "tabs");
    for (const i of intervals) {
      const b = btn(i.endsWith('m')?i:i.toUpperCase(), () => choose(i));
      b.setAttribute("aria-pressed", String(i === interval));
      periods.append(b);
    }
    bar.append(periods);this.box.append(bar);
    if(exchange==='binance'){this.box.append(binanceWidget(symbol,interval));return;}
    this.status = el("span", "Loading candles…", "chart-message");
    this.host = el("div", null, "chart-host");
    this.host.setAttribute("role", "img");
    this.host.setAttribute(
      "aria-label",
      `${symbol} candlestick chart, interval ${interval}`,
    );
    this.box.append(this.status,this.host);
    this.surface = el("div");
    Object.assign(this.surface.style, { width: "100%", height: "100%" });
    this.host.attachShadow({ mode: "open" }).append(this.surface);
    const interacting=()=>{this.interacted=true;};
    this.host.addEventListener('pointerdown',interacting);this.host.addEventListener('wheel',interacting,{passive:true});
    // Wait until the row is in the document so chart layout uses the real width.
    this.startFrame = requestAnimationFrame(() => this.mount());
  }
  size(width, cols) {
    this.box.style.width = `${width}px`;
    this.cell.colSpan = cols + 2;
  }
  async mount() {
    try {
      const {
        createChart,
        CandlestickSeries,
        HistogramSeries,
        ColorType,
        CrosshairMode,
      } = await import("./lightweight-charts-5-3-0.mjs");
      if (this.abort.signal.aborted) return;
      const palette = chartPalette();
      this.graph = createChart(this.surface, {
        autoSize: true,
        layout: {
          background: { type: ColorType.Solid, color: palette.background },
          textColor: palette.label,
          fontSize: 11,
          attributionLogo: true,
        },
        grid: {
          vertLines: { color: palette.grid },
          horzLines: { color: palette.grid },
        },
        crosshair: { mode: CrosshairMode.Normal },
        localization: { locale: "en-US" },
        rightPriceScale: {
          borderColor: palette.border,
          scaleMargins: { top: 0.08, bottom: 0.23 },
        },
        timeScale: {
          timeVisible: true,
          secondsVisible: false,
          rightOffset: 0,
          barSpacing: 6,
          borderColor: palette.border,
          fixRightEdge: false,
        },
        handleScale: {
          mouseWheel: true,
          pinch: true,
          axisPressedMouseMove: { price: true, time: true },
        },
        handleScroll: {
          mouseWheel: true,
          pressedMouseMove: true,
          horzTouchDrag: true,
          vertTouchDrag: true,
        },
        kineticScroll: { mouse: false, touch: true },
      });
      this.prices = this.graph.addSeries(CandlestickSeries, {
        upColor: palette.background === '#ffffff' ? '#08734a' : up,
        downColor: palette.background === '#ffffff' ? '#b22240' : down,
        borderVisible: false,
        wickUpColor: up,
        wickDownColor: down,
      });
      this.vol = this.graph.addSeries(HistogramSeries, {
        priceScaleId: "volume",
        priceFormat: { type: "volume" },
        lastValueVisible: true,
        priceLineVisible: false,
      });
      this.vol
        .priceScale()
        .applyOptions({ scaleMargins: { top: 0.83, bottom: 0 } });
      this.graph
        .timeScale()
        .subscribeVisibleLogicalRangeChange((range) =>
          this.rangeChanged(range),
        );
      await this.refresh();
      if (!this.abort.signal.aborted)
        this.timer = setInterval(() => {
          if (this.host.isConnected && !document.hidden) void this.refresh();
        }, 5500);
    } catch (e) {
      if (!this.abort.signal.aborted)
        this.status.textContent = "Chart unavailable: " + e.message;
    }
  }
  async page(limit, before) {
    const params = new URLSearchParams({
      ...this.params,
      limit: String(limit),
    });
    if (before) params.set("before", String(before));
    const res = await fetch("/api/candles?" + params, {
      signal: this.abort.signal,
      cache: "no-store",
    });
    if (!res.ok) throw Error("Could not load candles");
    const { candles } = await res.json();
    const sorted = new Map();
    for (const b of candles) {
      if (
        Number.isSafeInteger(b.t) &&
        [b.o, b.h, b.l, b.c, b.v].every(Number.isFinite) &&
        (!before || b.t < before)
      )
        sorted.set(b.t, b);
    }
    return [...sorted.values()].sort((a, b) => a.t - b.t);
  }
  fullSeries() {
    this.prices.setData(this.data.map(candle));
    this.vol.setData(this.data.map(volume));
  }
  async refresh() {
    if (this.loading) return;
    this.loading = true;
    try {
      const initial = this.data.length === 0,
        bars = await this.page(initial ? ({'15m':2881,'5m':2017,'1m':721}[this.params.interval]??PAGE) : 4);
      if (this.abort.signal.aborted) return;
      if (!bars.length) {
        this.status.textContent = "No candle data available.";
        return;
      }
      if (initial) {
        this.data = bars;
        const px = bars.at(-1).c;
        const precision = Math.max(
          2,
          Math.min(12, 4 - Math.floor(Math.log10(px))),
        );
        this.prices.applyOptions({
          priceFormat: { type: "price", precision, minMove: 10 ** -precision },
        });
        this.fullSeries();
        this.graph.timeScale().fitContent();
      } else {
        // The venue may have closed the previous bar and opened a new one.
        // Only update the tail; never fitContent()/reset the user's viewport.
        for (const b of bars) {
          const t = this.data.at(-1).t;
          if (b.t < t) continue;
          if (b.t === t) this.data[this.data.length - 1] = b;
          else this.data.push(b);
          this.prices.update(candle(b));
          this.vol.update(volume(b));
        }
      }
      this.host.dataset.latestTime = String(this.data.at(-1).t / 1000);
      if (!this.moreBusy) this.status.textContent = "";
    } catch (e) {
      if (!this.abort.signal.aborted)
        this.status.textContent = "Candle feed unavailable. Retrying…";
    } finally {
      this.loading = false;
    }
  }
  rangeChanged(range) {
    if (!range || !this.data.length || this.abort.signal.aborted) return;
    const time = this.graph.timeScale().getVisibleRange();
    if (time) {
      this.host.setAttribute(
        "aria-description",
        `Visible range: ${date(time.from)} to ${date(time.to)} UTC`,
      );
      this.host.dataset.from = time.from;
      this.host.dataset.to = time.to;
    }
    if (
      range.from < 25 &&
      this.interacted &&
      !this.moreBusy &&
      !this.exhausted &&
      Date.now() >= (this.retryAt || 0)
    )
      void this.older();
  }
  async older() {
    this.moreBusy = true;
    this.status.textContent = "Loading history…";
    try {
      const old = await this.page(PAGE, this.data[0].t);
      if (this.abort.signal.aborted) return;
      if (!old.length) {
        this.exhausted = true;
        this.status.textContent = "Start of available history";
        return;
      }
      // Capture the current view *after* I/O, so gestures during the fetch win.
      const ts = this.graph.timeScale(),
        r = ts.getVisibleLogicalRange();
      this.data = [...old, ...this.data];
      this.fullSeries();
      if (r)
        ts.setVisibleLogicalRange({
          from: r.from + old.length,
          to: r.to + old.length,
        });
      this.status.textContent = "";
    } catch (e) {
      if (!this.abort.signal.aborted) {
        this.status.textContent = "Older candles unavailable";
        this.retryAt = Date.now() + 10000;
      }
    } finally {
      this.moreBusy = false;
    }
  }
  destroy() {
    this.abort.abort();
    cancelAnimationFrame(this.startFrame);
    clearInterval(this.timer);
    this.graph?.remove();
    this.row.remove();
  }
}
