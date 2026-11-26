import { el, btn, select, input } from "./elements.mjs";

const base = {
  price: "Price",
  oi: "OI $",
  funding: "Funding/h (%)",
  rvol: "RVOL",
  mcap: "MCAP",
};
const series = {
  change: "CHG %",
  changeUsd: "CHG $",
  volume: "Vol",
  trades: "Trd",
  volatility: "Vlt",
  oiChange: "OI CHG %",
  oiDelta: "OI Δ$",
  volumeDelta: "Vol Δ",
  volChange: "VOL CHG %",
  volChangeUsd: "VOL CHG $",
  correlation: "COR",
};
const ops = {
  gt: ">",
  gte: ">=",
  lt: "<",
  lte: "<=",
  eq: "=",
  between: "between",
  abs_gt: "|x| >",
};
const triggers = {
  cross_up: "Crosses Above",
  cross_down: "Crosses Below",
  gt: "Is Above",
  lt: "Is Below",
  between: "Is Between",
  outside: "Is Outside",
};
export const single = (k) => k === "price" || k.startsWith("changeUsd:");
export function label(k, alert = false) {
  const [key, w] = k.split(":");
  const str = w ? `${series[key]} (${w})` : base[k];
  return alert ? str.replace(" (%)", "").toUpperCase() : str;
}
export function describe(c, alert = false) {
  const range = c.op === "between" || c.op === "outside";
  const value = (n) =>
    !alert
      ? String(n ?? "…")
      : n == null
        ? "…"
        : single(c.metric) || ["oi", "mcap"].includes(c.metric)
          ? "$" +
            n.toLocaleString("en-US", {
              minimumFractionDigits: 2,
              maximumFractionDigits: 8,
            })
          : String(n) +
            (/%/.test(label(c.metric)) || c.metric === "funding" ? "%" : "");
  const op = alert
    ? { cross_up: ">", cross_down: "<", outside: "outside", ...ops }[c.op]
    : ops[c.op];
  return `${label(c.metric, alert)} ${op} ${value(c.value)}${range ? " - " + value(c.upper) : ""}`;
}
export function named(n, name) {
  n.setAttribute("aria-label", name);
  return n;
}
export function valid(c) {
  return (
    Number.isFinite(c.value) &&
    (!["between", "outside"].includes(c.op) ||
      (Number.isFinite(c.upper) && c.upper >= c.value))
  );
}
export function conditionFields(
  cat,
  c,
  { alert = false, one = false, onChange, remove } = {},
) {
  const box = el("div", null, alert ? "trigger-fields" : "filter-fields");
  const met = named(
    select(
      cat.metrics.map((m) => ({
        id: m.id,
        label:
          label(m.id, alert) +
          (alert && single(m.id) && !one ? " (single symbol only)" : ""),
      })),
      c.metric,
    ),
    "Metric",
  );
  for (const opt of met.options)
    opt.disabled = alert && !one && single(opt.value);
  const opts = alert ? triggers : ops;
  const op = named(
    select(
      Object.entries(opts).map(([id, label]) => ({ id, label })),
      c.op,
    ),
    "Comparison",
  );
  const v = named(input("number", c.value ?? "", "Value"), "Threshold"),
    u = named(input("number", c.upper ?? c.value ?? "", "Max"), "Upper bound");
  const sep = el("span", "-", "range-dash");
  function sync() {
    const range = ["between", "outside"].includes(op.value);
    box.classList.toggle("range", range);
    u.hidden = u.disabled = sep.hidden = !range;
    if (range && c.upper === undefined) u.value = v.value;
    Object.assign(c, {
      metric: met.value,
      op: op.value,
      value: v.value === "" ? null : v.valueAsNumber,
    });
    if (range) c.upper = u.value === "" ? null : u.valueAsNumber;
    else delete c.upper;
    onChange?.();
  }
  met.onchange = op.onchange = sync;
  v.oninput = u.oninput = sync;
  const range = ["between", "outside"].includes(c.op);
  box.classList.toggle("range", range);
  u.hidden = u.disabled = sep.hidden = !range;
  const values = el("div", null, "thresholds");
  values.append(v, sep, u);
  box.append(met, op, values);
  if (remove) box.append(btn("×", remove, "remove-x", "Remove condition"));
  return box;
}
