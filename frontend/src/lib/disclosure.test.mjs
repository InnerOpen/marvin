// Collapsed raw-JSON fields on the entry editor (disclosure.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { keysHint, rememberDisclosures } from "./disclosure.ts";

describe("keysHint", () => {
  test("is empty for nothing to show", () => {
    for (const v of [null, undefined, {}, [], "x", 3]) assert.equal(keysHint(v), "");
  });

  test("counts the keys and names the first few", () => {
    assert.equal(keysHint({ featured: true }), "1 key: featured");
    assert.equal(keysHint({ a: 1, b: 2, c: 3, d: 4 }), "4 keys: a, b, c, …");
  });
});

/** A <details data-remember> stand-in: open flag, dataset and a toggle listener. */
function details(name, open = false) {
  const el = { open, dataset: { remember: name }, listeners: [] };
  el.addEventListener = (type, fn) => el.listeners.push([type, fn]);
  el.toggle = () => {
    el.open = !el.open;
    for (const [type, fn] of el.listeners) if (type === "toggle") fn();
  };
  return el;
}

const rootOf = (...els) => ({ querySelectorAll: () => els });

function memoryStorage(initial = {}) {
  const data = { ...initial };
  return { data, getItem: (k) => data[k] ?? null, setItem: (k, v) => (data[k] = v) };
}

describe("rememberDisclosures", () => {
  test("restores a remembered open panel and saves a toggle", () => {
    const store = memoryStorage({ "marvin.disclosure.meta": "open" });
    const meta = details("meta");
    const data = details("data");
    rememberDisclosures(rootOf(meta, data), store);
    assert.equal(meta.open, true);
    assert.equal(data.open, false);
    data.toggle();
    assert.equal(store.data["marvin.disclosure.data"], "open");
  });

  test("keeps a panel the server opened (an error to show) even if remembered closed", () => {
    const meta = details("meta", true);
    rememberDisclosures(rootOf(meta), memoryStorage({ "marvin.disclosure.meta": "closed" }));
    assert.equal(meta.open, true);
  });

  test("does nothing without storage, and survives storage that throws", () => {
    const el = details("meta");
    rememberDisclosures(rootOf(el), null);
    assert.equal(el.open, false);
    const broken = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    };
    rememberDisclosures(rootOf(el), broken);
    assert.doesNotThrow(() => el.toggle());
  });
});
