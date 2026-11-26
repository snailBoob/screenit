import { el, svg } from "./elements.mjs";
export function spark(series) {
  const vals = series.filter(Number.isFinite);
  if (vals.length < 2) return el("span", "—", "missing");
  const lo = Math.min(...vals),
    range = Math.max(...vals) - lo || 1;
  const image = svg("svg", {
    viewBox: "0 0 76 23",
    class: 'spark ' + (vals.length !== series.length || vals.at(-1) === vals[0] ? 'neutral' : vals.at(-1) > vals[0] ? 'pos' : 'neg'),
    role: "img",
    "aria-label": `24-hour trend, ${vals.length} observations`,
  });
  let last = false,
    path = "";
  series.forEach((v, i) => {
    if (!Number.isFinite(v)) {
      last = false;
      return;
    }
    path += `${last ? "L" : "M"}${(1 + (74 * i) / (series.length - 1)).toFixed(2)} ${(21 - (19 * (v - lo)) / range).toFixed(2)} `;
    last = true;
  });
  image.append(
    svg("path", {
      d: path,
      fill: "none",
      stroke: 'currentColor',
      "stroke-width": 1.5,
    }),
  );
  return image;
}
