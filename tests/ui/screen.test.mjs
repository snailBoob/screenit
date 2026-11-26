import test from "node:test";
import assert from "node:assert/strict";
import {
  visible,
  matches,
  metricTone,
  move,
  Workspace,
  rebase,
} from "../../src/ui/model.mjs";

test('market signals use the unrounded value, in the units actually sent by the feed', () => {
  for (const sign of [-1,1]) {
    const on = sign > 0 ? 'pos' : 'neg';
    assert.equal(metricTone('funding', sign * 0.004999), 'neutral');
    assert.equal(metricTone('funding', sign * 0.005), on);
    assert.equal(metricTone('correlation:1h', sign * 0.6999), 'neutral');
    assert.equal(metricTone('correlation:1h', sign * 0.7), on);
  }
  assert.deepEqual([null, 0, 4.999, 5, 9.999, 10].map(v => metricTone('rvol',v)),
    ['missing','neutral','neutral','bright','bright','pos']);
});

test("unknown last in both sort directions, excludes unknown from filters; exchange-native favorites", () => {
  const rs = ["xyz:A", "B", "C"].map((symbol, i) => ({
    symbol,
    metrics: { price: [2, null, 5][i] },
  }));
  const s = {
    exchange: "hyperliquid",
    search: "",
    favorites: ["hyperliquid:xyz:A"],
    favoritesOnly: false,
    filters: [],
    sort: { key: "price", dir: "desc" },
  };
  assert.deepEqual(
    visible(rs, s).map((x) => x.symbol),
    ["C", "xyz:A", "B"],
  );
  assert.deepEqual(
    visible(rs, { ...s, sort: { ...s.sort, dir: "asc" } }).map((x) => x.symbol),
    ["xyz:A", "C", "B"],
  );
  assert.deepEqual(
    visible(rs, { ...s, favoritesOnly: true }).map((x) => x.symbol),
    ["xyz:A"],
  );
  assert.equal(
    visible(rs, { ...s, filters: [{ metric: "price", op: "lt", value: 4 }] })
      .length,
    1,
  );
});
test("operator boundaries and reorder", () => {
  assert.ok(matches(-3, { op: "abs_gt", value: 2 }));
  assert.ok(matches(3, { op: "between", value: -3, upper: 3 }));
  assert.equal(matches(null, { op: "eq", value: 0 }), false);
  assert.deepEqual(move(["price", "symbol", "trend"], "trend", "price"), [
    "trend",
    "price",
    "symbol",
  ]);
});
test("conflict keeps only independent edits and reports colliding settings", () => {
  assert.deepEqual(
    rebase(
      { search: "", chartInterval: "1h" },
      { search: "BTC", chartInterval: "1h" },
      { search: "ETH", chartInterval: "1d" },
    ),
    { keep: { chartInterval: "1d" }, conflicts: ["search"] },
  );
});
test("in-flight autosave preserves a newer user edit", async () => {
  let finish;
  const initial = { revision: 1, settings: { search: "" } };
  const w = new Workspace(
    initial,
    () => {},
    () => {},
    () => new Promise((resolve) => (finish = resolve)),
  );
  w.set({ search: "B" });
  const job = w.flush();
  w.set({ search: "BTC" });
  finish({ revision: 2, settings: { search: "B" } });
  await job;
  assert.equal(w.value.search, "BTC");
  assert.equal(w.doc.revision, 2);
  clearTimeout(w.timer);
});
