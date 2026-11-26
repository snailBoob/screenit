export const venueName = {
  binance: "Binance Futures",
  hyperliquid: "Hyperliquid",
};
export const opName = {
  gt: "Greater than",
  gte: "Greater than or equal to",
  lt: "Less than",
  lte: "Less than or equal to",
  eq: "Equal to",
  between: "Inside range",
  abs_gt: "Absolute value greater than",
  outside: "Outside range",
  cross_up: "Crosses above",
  cross_down: "Crosses below",
};
const num = Number.isFinite;
export function matches(value, c) {
  if (!num(value)) return false;
  switch (c.op) {
    case "gt":
      return value > c.value;
    case "lt":
      return value < c.value;
    case "gte":
      return value >= c.value;
    case "lte":
      return value <= c.value;
    case "eq":
      return value === c.value;
    case "between":
      return value >= c.value && value <= c.upper;
    case "abs_gt":
      return Math.abs(value) > c.value;
    default:
      return false;
  }
}
export function visible(rows, s) {
  const q = s.search.trim().toLowerCase(),
    fav = new Set(s.favorites),
    { dir, key } = s.sort;
  return rows
    .filter(
      (r) =>
        (!q ||
          r.symbol.toLowerCase().includes(q) ||
          r.label?.toLowerCase().includes(q)) &&
        (!s.favoritesOnly || fav.has(`${s.exchange}:${r.symbol}`)) &&
        s.filters.every((c) => matches(r.metrics[c.metric], c)),
    )
    .sort((a, b) => {
      const tie = a.symbol.localeCompare(b.symbol);
      if (key === "symbol") return dir === "asc" ? tie : -tie;
      const x = a.metrics[key],
        y = b.metrics[key];
      if (!num(x)) return num(y) ? 1 : tie;
      if (!num(y)) return -1;
      return (dir === "asc" ? x - y : y - x) || tie;
    });
}
export function move(keys, from, to) {
  const arr = [...keys];
  const i = arr.indexOf(from),
    j = arr.indexOf(to);
  if (i < 0 || j < 0 || i === j) return arr;
  arr.splice(i, 1);
  arr.splice(j, 0, from);
  return arr;
}
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);
export function rebase(base, remote, patch) {
  const keep = {},
    conflicts = [];
  for (const [k, v] of Object.entries(patch)) {
    if (eq(remote[k], v)) continue;
    if (eq(remote[k], base[k])) keep[k] = v;
    else conflicts.push(k);
  }
  return { keep, conflicts };
}
export async function api(path, method = "GET", data) {
  const r = await fetch("/api/" + path, {
    method,
    cache: "no-store",
    headers: data ? { "Content-Type": "application/json" } : {},
    body: data ? JSON.stringify(data) : undefined,
  });
  const obj = await r.json();
  if (!r.ok) {
    const e = new Error(obj.error || `Request failed (${r.status})`);
    e.code = r.status;
    e.payload = obj;
    throw e;
  }
  return obj;
}
export class Workspace {
  constructor(doc, changed, inform, send = api) {
    this.doc = doc;
    this.pending = {};
    this.changed = changed;
    this.inform = inform;
    this.send = send;
    this.busy = false;
    this.timer = null;
  }
  get value() {
    return { ...this.doc.settings, ...this.inflight, ...this.pending };
  }
  set(changes) {
    Object.assign(this.pending, changes);
    this.changed();
    this.schedule(120);
  }
  schedule(ms) {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.flush(), ms);
  }
  receive(d) {
    if (
      !this.busy &&
      !Object.keys(this.pending).length &&
      d.revision > this.doc.revision
    ) {
      this.doc = d;
      this.changed();
    }
  }
  async flush() {
    if (this.busy || !Object.keys(this.pending).length) return;
    this.busy = true;
    this.inflight = this.pending;
    this.pending = {};
    let delay = 0;
    try {
      this.doc = await this.send("settings", "PATCH", {
        revision: this.doc.revision,
        changes: this.inflight,
      });
    } catch (e) {
      const all = { ...this.inflight, ...this.pending };
      if (e.code === 409) {
        const { keep, conflicts } = rebase(
          this.doc.settings,
          e.payload.settings,
          all,
        );
        this.doc = e.payload;
        this.pending = keep;
        if (conflicts.length)
          this.inform(
            "Changed elsewhere: " +
              conflicts.join(", ") +
              ". The server version has been kept.",
          );
      } else if (e.code >= 400 && e.code < 500) {
        this.inform(e.message);
      } else {
        this.pending = all;
        delay = 3000;
        this.inform("Storage is unavailable. Retrying automatically.");
      }
    } finally {
      this.inflight = null;
      this.busy = false;
      this.changed();
      if (Object.keys(this.pending).length) this.schedule(delay);
    }
  }
}
const directional = new Set(['change', 'changeUsd', 'oiChange', 'oiDelta', 'volChange', 'volChangeUsd', 'volumeDelta']);
export function metricTone(key, value) {
  if (!num(value)) return 'missing';
  const group = key.split(':',1)[0];
  if (group === 'rvol') return value >= 10 ? 'pos' : value >= 5 ? 'bright' : 'neutral';
  if (group === 'correlation') return value >= 0.7 ? 'pos' : value <= -0.7 ? 'neg' : 'neutral';
  // Wire values are percentage points per hour, not fractional rates.
  if (group === 'funding' && Math.abs(value) < 0.005) return 'neutral';
  if (group === 'funding' || directional.has(group)) return value > 0 ? 'pos' : value < 0 ? 'neg' : 'neutral';
  return '';
}

const largePrice = new Intl.NumberFormat('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
const smallPrice = new Intl.NumberFormat('en-US', {minimumFractionDigits:2, maximumFractionDigits:4});
function price(a) {
  if (a >= 100) return largePrice.format(a);
  if (a >= 1) return smallPrice.format(a);
  return a.toFixed(a >= .01 ? 4 : a >= .0001 ? 6 : a >= .000001 ? 8 : a >= 1e-10 ? 10 : 2);
}
function compact(a, count) {
  for (const [size, suffix] of [[1e12,'T'],[1e9,'B'],[1e6,'M'],[1e3,'K']])
    if (a >= size && !(count && size === 1e12)) return (a/size).toFixed(2) + suffix;
  return count || a === 0 ? String(Math.round(a)) : a.toFixed(2);
}
export function fmt(v, unit, key = '') {
  if (!num(v)) return '—';
  const group = key.split(':',1)[0], a = Math.abs(v), signed = directional.has(group) || group === 'funding' || unit === 'corr';
  const sign = v < 0 ? '-' : v > 0 && signed ? '+' : '';
  if (group === 'funding') {
    if (a > 0 && a < 1e-8) return (v > 0 ? '<+' : '>−') + '0.00000001%';
    return sign + a.toFixed(a ? Math.max(4, Math.min(8, 2-Math.floor(Math.log10(a)))) : 4) + '%';
  }
  if (unit === 'usd') return sign + '$' + (group === 'price' || group === 'changeUsd' ? price(a) : compact(a, false));
  if (unit === 'count') return sign + compact(a, true);
  return sign + a.toFixed(2) + (unit === 'pct' ? '%' : unit === 'ratio' ? 'x' : '');
}
