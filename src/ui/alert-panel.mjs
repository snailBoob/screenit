import { $, el, btn, select, input, line } from "./elements.mjs";
import { api } from "./model.mjs";
import {
  conditionFields,
  describe,
  named,
  single,
  valid,
} from "./rule-fields.mjs";
import { browserFeedback, play, unlock } from "./alert-delivery.mjs";

const fresh = () => ({ metric: "price", op: "cross_up", value: 0 });
const cooldowns = [
  ["1 min", 60000],
  ["5 min", 300000],
  ["15 min", 900000],
  ["30 min", 1800000],
  ["1 hr", 3600000],
  ["4 hr", 14400000],
];
const sounds = ["None", "Boop", "Bell", "Ding", "Alert", "Chime"];
function toggle(name, on, fn) {
  const b = btn("", fn, "rule-toggle", name);
  b.setAttribute("role", "switch");
  b.setAttribute("aria-checked", String(on));
  return b;
}
export function alertPanel({ cat, s, set, rows, count, toast }) {
  const panel = $("#alert-panel"),
    heading = $("#alert-actions"),
    tabbar = $("#alert-tabs"),
    form = $("#alert-form"),
    list = $("#alert-list"),
    notify = $("#alert-notifications");
  document.addEventListener("pointerdown", unlock, { once: true });
  let tab = "active",
    rules = [],
    events = [],
    draft = null,
    symbols = [],
    assets = [],
    assetsSeq = 0,
    pollSeq = 0,
    lastEvent = null,
    queue = Promise.resolve(),
    pendingEdit = null,
    saving = false,
    confirmId = null;
  function close() {
    panel.close();
    $("#open-alerts").setAttribute("aria-expanded", "false");
    draft = null;
    assetsSeq++;
    confirmId = null;
  }
  $("#collapse-alerts").onclick = close;
  document.addEventListener('pointerdown',e=>{
    if(panel.open && !panel.contains(e.target) && !e.target.closest('#open-alerts'))close();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && panel.open && !$("#panel").open) close();
  });
  function setTab(t) {
    tab = t;
    draft = null;
    confirmId = null;
    form.replaceChildren();
    renderList();
  }
  heading.append(btn("+ Add", () => openForm(null), "", "New alert"));
  function notifications() {
    const allowed =
      window.isSecureContext &&
      "Notification" in window &&
      Notification.permission !== "denied";
    const enabled =
      allowed &&
      Notification.permission === "granted" &&
      s().browserNotifications;
    const sw = toggle("Browser notifications", enabled, async () => {
      if (!enabled) {
        const permission = await Notification.requestPermission();
        set({ browserNotifications: permission === "granted" });
      } else set({ browserNotifications: false });
      notifications();
    });
    sw.disabled = !allowed;
    notify.replaceChildren(
      el(
        "p",
        "Alerts run on the server, even when your browser is closed.",
        "operation-note",
      ),
      line(el("span", "Browser notifications"), sw),
    );
    if (!allowed)
      notify.append(
        el(
          "p",
          !window.isSecureContext
            ? "Browser notifications require HTTPS or localhost."
            : "Notifications blocked. Enable them in your browser settings.",
          "permission-note",
        ),
      );
  }
  function renderList() {
    if (!panel.open) return;
    tabbar.replaceChildren(
      btn(
        `Active (${rules.filter((r) => r.enabled).length}/${rules.length})`,
        () => setTab("active"),
        tab === "active" ? "active" : "",
      ),
      btn(
        `History (${events.length})`,
        () => setTab("history"),
        tab === "history" ? "active" : "",
        "History",
      ),
    );
    notifications();
    list.replaceChildren();
    if (tab === "history") {
      if (!events.length)
        list.append(el("p", "No alerts triggered yet", "aside-empty"));
      for (const e of events) {
        const n = el("article", null, "history-item");
        n.append(
          line(
            el("strong", e.ruleName),
            el(
              "small",
              { sent: "Sent", failed: "Failed", pending: "Queued", off: "" }[e.delivery],
            ),
          ),
          el("p", e.message, "break"),
          el("small", (e.exchange === 'binance' ? 'Binance' : 'Hyperliquid') + ' · ' + new Date(e.at).toLocaleString("en-US")),
        );
        list.append(n);
      }
      return;
    }
    if (!rules.length)
      list.append(el("p", "No alerts configured", "aside-empty"));
    for (const r of rules) {
      const card = el("article", null, "rule-card"),
        text = el("div", null, "rule-card-text"),
        top = el("div", null, "rule-card-title");
      top.append(
        el(
          "span",
          r.exchange === "binance" ? "BIN" : "HL",
          "exchange-badge " + r.exchange,
        ),
        el("strong", r.symbol || "All symbols"),
      );
      if (r.name) top.append(el("span", r.name, "custom-name"));
      text.append(
        top,
        el(
          "p",
          r.groups
            .map((g) => g.map((c) => describe(c, true)).join(" AND "))
            .join(" OR "),
        ),
      );
      if (r.repeat === "rearm") text.append(el("small", "• Repeating"));
      card.append(
        text,
        btn("✎", () => openForm(r), "icon", "Edit alert"),
        toggle(
          r.enabled ? "Pause alert" : "Resume alert",
          r.enabled,
          async () => {
            try {
              await api("alerts/" + r.id, "PUT", { ...r, enabled: !r.enabled });
              await poll();
            } catch (e) {
              toast(e.message);
            }
          },
        ),
        btn(
          "×",
          () => {
            confirmId = r.id;
            renderList();
          },
          "remove-x",
          "Delete alert",
        ),
      );
      if (confirmId === r.id) {
        card.replaceChildren(
          el("span", "Delete this alert?"),
          btn("Delete", async () => {
            try {
              await api(`alerts/${r.id}?revision=${r.revision}`, "DELETE");
              confirmId = null;
              await poll();
            } catch (e) {
              toast(e.message);
            }
          }),
          btn("Cancel", () => {
            confirmId = null;
            renderList();
          }),
        );
      }
      list.append(card);
    }
  }
  async function poll() {
    const seq = ++pollSeq;
    try {
      const [a, h] = await Promise.all([api("alerts"), api("history")]);
      if (seq !== pollSeq) return;
      browserFeedback(s().browserNotifications, h.events, lastEvent);
      lastEvent = Math.max(lastEvent ?? 0, h.events[0]?.id ?? 0);
      const changed =
        JSON.stringify([rules, events]) !== JSON.stringify([a.rules, h.events]);
      rules = a.rules;
      events = h.events;
      count(rules.filter((r) => r.enabled).length);
      if (changed && panel.open) renderList();
    } catch (e) {
      if (panel.open) toast(e.message);
    }
  }
  async function open() {
    if (panel.open) {
      close();
      return;
    }
    panel.show();
    $("#open-alerts").setAttribute("aria-expanded", "true");
    tab = "active";
    draft = null;
    form.replaceChildren();
    renderList();
    await poll();
  }
  function openForm(rule) {
    unlock();
    tab = "active";
    confirmId = null;
    draft = rule
      ? structuredClone(rule)
      : {
          name: "",
          exchange: s().exchange,
          symbol: null,
          enabled: true,
          repeat: "once",
          cooldownMs: 300000,
          sound: "",
          groups: [[fresh()]],
        };
    symbols = draft.symbol ? [draft.symbol] : [];
    renderList();
    loadAssets();
    paintForm();
  }
  function loadAssets() {
    const ex = draft.exchange,
      i = ++assetsSeq;
    assets = [];
    if (ex === s().exchange && rows().length) {
      assets = rows().map((r) => r.symbol);
      return;
    }
    api("market?exchange=" + ex)
      .then((snap) => {
        if (i === assetsSeq) assets = snap.rows.map((r) => r.symbol);
      })
      .catch((e) => toast(e.message));
  }
  function payload() {
    const doc = structuredClone(draft);
    doc.name = doc.name.trim();
    doc.symbol = symbols.length === 1 ? symbols[0] : null;
    if (symbols.length > 1) doc.symbols = [...symbols];
    return doc;
  }
  function issue() {
    if (draft.ntfy) {
      try {
        const u = new URL(draft.ntfy.server);
        if (!/^https?:\/\/[^\s\\?#]+$/.test(draft.ntfy.server) || u.username || u.password) throw Error();
      } catch { return 'Enter a valid Server URL.'; }
      if (!/^[A-Za-z0-9_-]{1,64}$/.test(draft.ntfy.topic)) return 'Enter a valid Topic.';
    }
    if (
      symbols.length !== 1 &&
      draft.groups.some((g) => g.some((c) => single(c.metric)))
    )
      return "Select one symbol to use Price or CHG $.";
    if (draft.groups.some((g) => g.some((c) => !valid(c))))
      return "Enter a valid value or range.";
    return "";
  }
  function saveEdit() {
    if (!draft?.id || issue() || draft.conflicted) return;
    const target = draft,
      doc = payload();
    pendingEdit = doc;
    queue = queue.then(async () => {
      if (doc !== pendingEdit || target.conflicted) return;
      doc.revision = target.revision;
      try {
        const res = await api("alerts/" + doc.id, "PUT", doc);
        target.revision = res.rule.revision;
        await poll();
      } catch (e) {
        if (e.code === 409) target.conflicted = true;
        toast(
          e.code === 409
            ? "This alert changed elsewhere. Reopen it to continue."
            : e.message,
        );
      }
    });
  }
  function paintForm() {
    if (!draft) {
      form.replaceChildren();
      return;
    }
    const r = draft;
    form.replaceChildren();
    const wrap = el("div", null, "orion-alert-form");
    form.append(wrap);
    const exchange = el("div", null, "exchange-pick");
    for (const [id, title] of [
      ["binance", "Binance"],
      ["hyperliquid", "Hyperliquid"],
    ]) {
      const b = btn(
        title,
        () => {
          if (r.exchange === id) return;
          r.exchange = id;
          symbols = [];
          loadAssets();
          paintForm();
          saveEdit();
        },
        id,
      );
      b.setAttribute("aria-pressed", r.exchange === id);
      exchange.append(b);
    }
    wrap.append(line(el("span", "Exchange"), exchange));
    const name = named(input("text", r.name, "Alert name (optional)"), "Name");
    name.maxLength = 90;
    name.oninput = () => {
      r.name = name.value;
    };
    name.onchange = saveEdit;
    wrap.append(name);
    const picker = el("div", null, "symbol-picker"),
      tags = el("div", null, "symbol-tags"),
      search = named(
        input(
          "text",
          "",
          symbols.length ? "Add more..." : "Symbol (empty = all)",
        ),
        "Instrument",
      ),
      suggest = el("div", null, "symbol-results");
    search.autocomplete = "off";
    for (const sym of symbols)
      tags.append(
        el("span", sym),
        btn(
          "×",
          () => {
            symbols = symbols.filter((x) => x !== sym);
            paintForm();
            saveEdit();
          },
          "",
          "Remove " + sym,
        ),
      );
    const pick = (sym) => {
      symbols = r.id ? [sym] : [...symbols, sym];
      paintForm();
      saveEdit();
    };
    function options() {
      suggest.replaceChildren();
      const q = search.value.trim().toUpperCase();
      if (!q) return;
      for (const sym of assets
        .filter((x) => !symbols.includes(x) && x.toUpperCase().includes(q))
        .slice(0, 20)) {
        const b = btn(sym, () => pick(sym));
        b.onmousedown = (e) => e.preventDefault();
        suggest.append(b);
      }
    }
    search.oninput = options;
    search.onfocus = options;
    search.onblur = () => suggest.replaceChildren();
    search.onkeydown = (e) => {
      if (e.key === "Enter" && suggest.firstElementChild) {
        e.preventDefault();
        suggest.firstElementChild.click();
      }
    };
    picker.append(tags, search, suggest);
    wrap.append(picker);
    const preview = el("div", null, "trigger-preview"),
      warn = el("p", null, "rule-warning"),
      actions = el("div", null, "rule-form-actions");
    const create = btn(
      "Create Alert",
      async () => {
        if (issue() || saving) return;
        saving = true;
        create.disabled = true;
        try {
          await api("alerts", "POST", payload());
          draft = null;
          form.replaceChildren();
          await poll();
        } catch (e) {
          toast(e.message);
          create.disabled = false;
        } finally {
          saving = false;
        }
      },
      "create-rule",
    );
    function summary() {
      warn.textContent = issue();
      warn.hidden = !warn.textContent;
      create.disabled = !!warn.textContent || saving;
      const scope =
        symbols.length === 0
          ? "All symbols"
          : symbols.length === 1
            ? symbols[0]
            : `${symbols.length} symbols`;
      preview.replaceChildren(el("span", `Triggers when (${scope}):`));
      r.groups.forEach((g, i) =>
        preview.append(
          el(
            "div",
            (i ? "OR  " : "•   ") +
              g.map((c) => describe(c, true)).join(" AND "),
          ),
        ),
      );
    }
    r.groups.forEach((g, i) => {
      if (i) wrap.append(el("div", "OR", "logic-divider or"));
      const section = el("section", null, "rule-group"),
        head = el("div", null, "group-title");
      head.append(el("span", `Group ${i + 1}`));
      if (r.groups.length > 1)
        head.append(
          btn(
            "×",
            () => {
              r.groups.splice(i, 1);
              paintForm();
              saveEdit();
            },
            "remove-x",
            "Remove group",
          ),
        );
      section.append(head);
      const content = el("div", null, "group-fields");
      section.append(content);
      g.forEach((c, j) => {
        if (j) content.append(el("div", "AND", "logic-divider"));
        content.append(
          conditionFields(cat, c, {
            alert: true,
            one: symbols.length === 1,
            onChange: () => {
              summary();
            },
            remove:
              g.length > 1
                ? () => {
                    g.splice(j, 1);
                    paintForm();
                    saveEdit();
                  }
                : null,
          }),
        );
      });
      content.addEventListener("change", saveEdit);
      const add = btn(
        "+ Add AND condition",
        () => {
          g.push(fresh());
          paintForm();
          saveEdit();
        },
        "add-condition",
      );
      add.disabled = g.length >= 8;
      content.append(add);
      wrap.append(section);
    });
    const addGroup = btn(
      "+ Add OR group",
      () => {
        r.groups.push([fresh()]);
        paintForm();
        saveEdit();
      },
      "add-group",
    );
    addGroup.disabled = r.groups.length >= 8;
    wrap.append(addGroup, preview);
    wrap.append(
      line(
        el("span", "Repeat"),
        toggle("Repeat", r.repeat === "rearm", () => {
          r.repeat = r.repeat === "rearm" ? "once" : "rearm";
          r.cooldownMs ??= 300000;
          paintForm();
          saveEdit();
        }),
      ),
    );
    if (r.repeat === "rearm") {
      const cool = named(
        select(
          cooldowns.map(([label, ms]) => ({ id: String(ms), label })),
          String(r.cooldownMs ?? 300000),
        ),
        "Cooldown",
      );
      cool.onchange = () => {
        r.cooldownMs = Number(cool.value);
        saveEdit();
      };
      wrap.append(line(el("span", "Cooldown"), cool));
    }
    const sound = named(
      select(
        sounds.map((label) => ({
          id: label === "None" ? "" : label.toLowerCase(),
          label,
        })),
        r.sound || "",
      ),
      "Sound",
    );
    sound.onchange = () => {
      r.sound = sound.value;
      unlock();
      play(r.sound);
      saveEdit();
    };
    wrap.append(line(el("span", "Sound"), sound));
    wrap.append(line(el('span','Use ntfy'), toggle('Use ntfy', !!r.ntfy, () => {
      r.ntfy = r.ntfy ? null : {server:'', topic:''};
      paintForm(); saveEdit();
    })));
    if (r.ntfy) for (const [key,label] of [['server','Server URL'],['topic','Topic']]) {
      const field = named(input(key === 'server' ? 'url' : 'text', r.ntfy[key], label), label);
      field.maxLength = key === 'server' ? 500 : 64;
      field.oninput = () => { r.ntfy[key] = field.value.trim(); summary(); };
      field.onchange = saveEdit;
      wrap.append(field);
    }
    wrap.append(warn);
    if (!r.id) actions.append(create);
    actions.append(
      btn(r.id ? "Done" : "Cancel", async () => {
        if (r.id && issue()) { toast(issue()); return; }
        await queue;
        draft = null;
        form.replaceChildren();
        await poll();
      }),
    );
    wrap.append(actions);
    summary();
  }
  return { open, close, poll };
}
