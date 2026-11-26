export const $ = (s) => document.querySelector(s);
export function el(tag, text, cls) {
  const n = document.createElement(tag);
  if (text != null) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
export function btn(text, fn, cls, title) {
  const b = el("button", text, cls);
  b.type = "button";
  b.onclick = fn;
  if (title) {
    b.title = title;
    b.setAttribute("aria-label", title);
  }
  return b;
}
export function field(name, input) {
  const l = el("label", name, "field");
  input.setAttribute("aria-label", name);
  l.append(input);
  return l;
}
export function select(items, value) {
  const n = el("select");
  for (const x of items) {
    const o = el("option", x.label ?? x);
    o.value = x.id ?? x;
    n.append(o);
  }
  n.value = value;
  return n;
}
export function input(type, value = "", placeholder = "") {
  const n = el("input");
  n.type = type;
  n.value = value;
  n.placeholder = placeholder;
  if (type === "number") {
    n.step = "any";
    n.addEventListener('focus', () => n.select());
    n.addEventListener('click', () => n.select());
  }
  return n;
}
export function line(...kids) {
  const n = el("div", null, "line");
  n.append(...kids);
  return n;
}
export function svg(tag, attrs = {}) {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  return e;
}
export const localTime = (stamp) =>
  new Date(stamp).toLocaleTimeString("en-US", {
    hour: "2-digit",
    hourCycle: "h23",
    minute: "2-digit",
    second: "2-digit",
  });
