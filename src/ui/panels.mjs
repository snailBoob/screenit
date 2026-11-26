import { $, el, btn, input, line } from "./elements.mjs";
import { move } from "./model.mjs";
import { alertPanel } from "./alert-panel.mjs";
import { conditionFields, describe, valid } from "./rule-fields.mjs";

export function panels(context) {
  const { cat, s, set, toast, formatName } = context,
    alerts = alertPanel(context);
  const dialog = $("#panel"),
    body = $("#panel-body");
  let mode = "";
  const buttons = (...bs) => {
    const n = el("div", null, "tabs");
    n.append(...bs);
    return n;
  };
  const anchor = () => {
    if (!dialog.open) return;
    const rect = $("#" + mode).getBoundingClientRect();
    dialog.style.top = rect.bottom + 4 + "px";
    dialog.style.right =
      Math.max(
        12,
        Math.min(innerWidth - dialog.offsetWidth - 12, innerWidth - rect.right),
      ) + "px";
  };
  const show = (title, m) => {
    mode = m;
    dialog.dataset.view = m;
    $("#panel-title").textContent = title;
    body.replaceChildren();
    if (!dialog.open) dialog.show();
    for (const id of ["filters", "columns"])
      $("#" + id).setAttribute("aria-expanded", String(id === m));
    anchor();
  };
  $("#close").onclick = () => dialog.close();
  $("#filter-switch").onclick = () => set({filtersEnabled: !s().filtersEnabled});
  dialog.onclose = () => {
    for (const id of ["filters", "columns"])
      $("#" + id).setAttribute("aria-expanded", "false");
  };
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && dialog.open) dialog.close();
  });
  document.addEventListener("pointerdown", (e) => {
    if (dialog.open && !dialog.contains(e.target) && !e.target.closest(".tool"))
      dialog.close();
  });
  window.addEventListener("resize", anchor);
  const report = (e) => {
    const n = el("p", e.message, "neg");
    n.setAttribute("role", "alert");
    body.prepend(n);
    toast(e.message);
  };
  function filters() {
    show("Filters", "filters");
    const base = s().filters, exchange = s().exchange;
    function apply(next) {
      if (exchange !== s().exchange || JSON.stringify(base) !== JSON.stringify(s().filters)) {
        filters();
        report(
          new Error("Filters changed elsewhere. The server version is shown."),
        );
        return;
      }
      set({ filters: next });
      filters();
    }
    if (base.length) {
      const active = el("div", null, "filter-active");
      base.forEach((c, i) => {
        const li = el("div", null, "filter-item");
        li.append(
          el("span", describe(c)),
          btn(
            "×",
            () => apply(base.filter((_, j) => i !== j)),
            "remove-x",
            "Remove filter: " + describe(c),
          ),
        );
        active.append(li);
      });
      active.append(btn("Clear all", () => apply([]), "clear-filters"));
      body.append(active);
    }
    const c = { metric: "change:1h", op: "gt", value: 0 };
    const atLimit = base.length >= cat.maxFilters;
    const add = btn(
      "Add Filter",
      () => {
        if (valid(c)) apply([...base, { ...c }]);
      },
      "primary",
    );
    add.disabled = atLimit || !valid(c);
    if (atLimit) add.title = `Maximum ${cat.maxFilters} filters per exchange.`;
    body.append(
      conditionFields(cat, c, { onChange: () => (add.disabled = atLimit || !valid(c)) }),
      add,
    );
  }
  function columns() {
    const scroll =
      dialog.open && mode === "columns"
        ? (body.querySelector(".colgroups")?.scrollTop ?? 0)
        : 0;
    show("Column Visibility", "columns");
    const conf = s(),
      all = ["trend", "symbol", ...cat.metrics.map((m) => m.id)];
    const apply = (keys) => {
      if (JSON.stringify(conf.columns) !== JSON.stringify(s().columns)) {
        columns();
        report(
          new Error(
            "Columns changed elsewhere. The server version has been kept.",
          ),
        );
        return;
      }
      set({ columns: keys });
      columns();
    };
    const actions = buttons(
      btn("All", () => apply(all)),
      btn("Defaults", () => apply(cat.defaultColumns)),
      btn("Core only", () =>
        apply([
          "trend",
          "symbol",
          ...cat.metrics.filter((m) => m.group === "Core").map((m) => m.id),
        ]),
      ),
    );
    actions.className = "col-actions";
    const groups = el("div", null, "colgroups"),
      sections = new Map();
    for (const key of ["trend", "symbol", ...cat.metrics.map((m) => m.id)]) {
      const group = cat.metrics.find((m) => m.id === key)?.group || "Core",
        win = key.split(":")[1];
      if (!sections.has(group)) {
        const sec = el("section", null, "colsection"),
          title = line(el("span", group)),
          checks = el("div", null, "checks");
        const keys = cat.metrics
          .filter((m) => m.group === group)
          .map((m) => m.id);
        if (win) {
          const full = keys.every((k) => conf.columns.includes(k));
          title.append(
            btn(full ? "Hide All" : "Show All", () =>
              apply(
                full
                  ? conf.columns.filter((k) => !keys.includes(k))
                  : [...new Set([...conf.columns, ...keys])],
              ),
            ),
          );
        }
        sec.append(title, checks);
        groups.append(sec);
        sections.set(group, checks);
      }
      const label = el("label"),
        on = input("checkbox");
      on.checked = conf.columns.includes(key);
      on.disabled = key === "symbol";
      on.setAttribute("aria-label", formatName(key));
      on.onchange = () =>
        apply(
          on.checked
            ? [...conf.columns, key]
            : conf.columns.filter((k) => k !== key),
        );
      label.append(
        on,
        document.createTextNode(
          win ||
            { oi: "OI $", funding: "Funding/h", mcap: "MCAP", rvol: "RVOL" }[
              key
            ] ||
            formatName(key),
        ),
      );
      sections.get(group).append(label);
    }
    const list = el("div", null, "list");
    function item(k, selected) {
      const r = el("div", null, "list-row line"),
        on = input("checkbox");
      on.checked = selected;
      on.disabled = k === "symbol";
      on.onchange = () =>
        apply(
          on.checked ? [...s().columns, k] : s().columns.filter((x) => x !== k),
        );
      const lab = el("label");
      lab.append(on, document.createTextNode(formatName(k)));
      r.append(lab);
      if (selected) {
        const i = conf.columns.indexOf(k),
          a = btn(
            "↑",
            () => apply(move(conf.columns, k, conf.columns[i - 1])),
            "mini",
            "Move earlier: " + formatName(k),
          ),
          b = btn(
            "↓",
            () => apply(move(conf.columns, k, conf.columns[i + 1])),
            "mini",
            "Move later: " + formatName(k),
          );
        a.disabled = i === 0;
        b.disabled = i === conf.columns.length - 1;
        r.append(buttons(a, b));
      }
      return r;
    }
    for (const k of conf.columns) list.append(item(k, true));
    const order = el("details", null, "col-order");
    order.append(el("summary", "Column order"), list);
    groups.append(order);
    body.append(groups, actions);
    groups.scrollTop = scroll;
  }
  const toggle = (fn, v) => () => {
    if (dialog.open && mode === v) dialog.close();
    else fn();
  };
  return {
    filters: toggle(filters, "filters"),
    columns: toggle(columns, "columns"),
    alerts: async () => {
      await alerts.open();
      anchor();
    },
    poll: alerts.poll,
  };
}
