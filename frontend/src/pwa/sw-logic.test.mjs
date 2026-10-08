// The service worker's decisions (sw-logic.js): what is cached, what never is, and where a notification may
// lead. Run with `npm test` — plain `node --test`.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

import {
  cacheable,
  cacheNames,
  notificationFromPush,
  parsePush,
  safeTarget,
  staleCaches,
  strategy,
} from "./sw-logic.js";

const ORIGIN = "https://marvin.example.com";
const req = (path, { method = "GET", mode = "cors", origin = ORIGIN } = {}) => ({
  url: `${origin}${path}`,
  method,
  mode,
});

describe("strategy", () => {
  test("page loads go to the network (never cached), with the offline page as the fallback", () => {
    assert.equal(strategy(req("/workspace/entries", { mode: "navigate" }), ORIGIN), "navigate");
    assert.equal(strategy(req("/", { mode: "navigate" }), ORIGIN), "navigate");
  });

  test("API calls, whatever their shape, are never handled", () => {
    assert.equal(strategy(req("/api/self/push"), ORIGIN), "network");
    assert.equal(strategy(req("/api/auth/logout", { method: "POST", mode: "navigate" }), ORIGIN), "network");
    assert.equal(strategy(req("/api/entries", { mode: "navigate" }), ORIGIN), "network");
  });

  test("only static files are cache-first", () => {
    assert.equal(strategy(req("/_astro/AppLayout.Bx1.css"), ORIGIN), "asset");
    assert.equal(strategy(req("/icons/icon-192.png"), ORIGIN), "asset");
    assert.equal(strategy(req("/offline.html"), ORIGIN), "asset");
    assert.equal(strategy(req("/version.json"), ORIGIN), "network");
    assert.equal(strategy(req("/manifest.webmanifest"), ORIGIN), "network");
    assert.equal(strategy(req("/_astro/x.js", { origin: "https://cdn.example" }), ORIGIN), "network");
    assert.equal(strategy(req("/_astro/x.js", { method: "POST" }), ORIGIN), "network");
  });
});

test("cacheable: only whole, same-origin, successful responses", () => {
  assert.ok(cacheable({ ok: true, status: 200, type: "basic" }));
  assert.ok(!cacheable({ ok: true, status: 206, type: "basic" }));
  assert.ok(!cacheable({ ok: true, status: 200, type: "opaque" }));
  assert.ok(!cacheable({ ok: false, status: 404, type: "basic" }));
  assert.ok(!cacheable(null));
});

test("cache names are per build, and activate clears only Marvin's older ones", () => {
  const { shell, assets } = cacheNames("v2");
  assert.deepEqual(staleCaches([shell, assets, "marvin-shell-v1", "marvin-assets-v1", "someone-else"], "v2"), [
    "marvin-shell-v1",
    "marvin-assets-v1",
  ]);
});

describe("notifications", () => {
  test("a notification only ever opens this origin", () => {
    assert.equal(safeTarget("/workspace/entries/1", ORIGIN), `${ORIGIN}/workspace/entries/1`);
    for (const bad of [
      "https://evil.example/x",
      "//evil.example/x",
      "javascript:alert(1)",
      "data:text/html,x",
      "",
      null,
      42,
    ]) {
      assert.equal(safeTarget(bad, ORIGIN), `${ORIGIN}/`, String(bad));
    }
  });

  test("notificationFromPush takes the server's fields, bounded, and nothing else", () => {
    const n = notificationFromPush(
      {
        title: "T".repeat(500),
        body: "Hi",
        url: "https://evil.example",
        tag: "approval:1",
        badge: 3,
        icon: "https://evil.example/x.png",
      },
      ORIGIN,
    );
    assert.equal(n.title.length, 120);
    assert.equal(n.options.body, "Hi");
    assert.equal(n.options.data.url, `${ORIGIN}/`);
    assert.equal(n.options.tag, "approval:1");
    assert.equal(n.options.icon, "/icons/icon-192.png");
    assert.equal(n.badge, 3);
    assert.equal(notificationFromPush({}, ORIGIN).title, "Marvin");
    assert.equal(notificationFromPush({ badge: -1 }, ORIGIN).badge, null);
  });

  test("parsePush: JSON, or plain text as the body", () => {
    assert.deepEqual(parsePush('{"title":"x"}'), { title: "x" });
    assert.deepEqual(parsePush("hello"), { body: "hello" });
    assert.deepEqual(parsePush(""), {});
  });
});

test("the worker template has every marker the build fills in", () => {
  const source = readFileSync(new URL("./sw.js", import.meta.url), "utf8");
  for (const marker of ["__MARVIN_SW_VERSION__", "__MARVIN_SW_PRECACHE__", "/* __MARVIN_SW_LOGIC__ */"])
    assert.ok(source.includes(marker), marker);
});
