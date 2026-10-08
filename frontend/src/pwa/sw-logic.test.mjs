// The service worker's decisions (sw-logic.js): what is cached, what never is, and where a notification may
// lead. Run with `npm test` — plain `node --test`.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

import {
  approvalOf,
  approvalOutcome,
  approvalRequest,
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

describe("Approve / Deny on an AI approval", () => {
  const ID = "0b6c1f7e-6a43-4b8e-9d41-2f0c9a7d5e11";
  const TOKEN = "tok_abcdefghijklmnopqrstuvwxyz-0123456789";

  test("a well-formed approval gets the two buttons and keeps its id and token", () => {
    const n = notificationFromPush(
      { title: "Waiting", url: `/workspace/settings/ai-ask?thread=${ID}`, approval: { id: ID, token: TOKEN } },
      ORIGIN,
    );
    assert.deepEqual(
      n.options.actions.map((a) => a.action),
      ["approve", "deny"],
    );
    assert.deepEqual(n.options.data.approval, { id: ID, token: TOKEN });
  });

  test("anything else gets no buttons: a plain push, a malformed id or token, extra fields dropped", () => {
    assert.equal(notificationFromPush({ title: "x" }, ORIGIN).options.actions, undefined);
    for (const bad of [
      { id: "../../admin", token: TOKEN },
      { id: ID, token: "short" },
      { id: ID, token: "has spaces in it, not base64url" },
      { id: ID },
      "string",
      null,
    ]) {
      const n = notificationFromPush({ approval: bad }, ORIGIN);
      assert.equal(n.options.actions, undefined, JSON.stringify(bad));
      assert.equal(n.options.data.approval, undefined);
    }
    assert.deepEqual(approvalOf({ id: ID, token: TOKEN, extra: "x" }), { id: ID, token: TOKEN });
  });

  test("a button posts the token, without cookies, to that approval's decision", () => {
    const data = { url: `${ORIGIN}/x`, approval: { id: ID, token: TOKEN } };
    const approve = approvalRequest("approve", data, ORIGIN);
    assert.equal(approve.url, `${ORIGIN}/api/self/push/approvals/${ID}/approve`);
    assert.equal(approve.init.method, "POST");
    assert.equal(approve.init.credentials, "omit");
    assert.deepEqual(JSON.parse(approve.init.body), { token: TOKEN });
    assert.equal(approvalRequest("deny", data, ORIGIN).url, `${ORIGIN}/api/self/push/approvals/${ID}/deny`);
  });

  test("a plain tap, an unknown button or no approval opens the page instead", () => {
    const data = { approval: { id: ID, token: TOKEN } };
    assert.equal(approvalRequest("", data, ORIGIN), null);
    assert.equal(approvalRequest("delete", data, ORIGIN), null);
    assert.equal(approvalRequest("approve", {}, ORIGIN), null);
    assert.equal(approvalRequest("approve", { approval: { id: "x", token: TOKEN } }, ORIGIN), null);
  });

  test("success: the server's line, the badge, the conversation on tap, nothing opened", () => {
    const o = approvalOutcome(
      "approve",
      true,
      { message: "Approved — moved 78 entries to the Trash", url: `/workspace/settings/ai-ask?thread=${ID}`, badge: 4 },
      `${ORIGIN}/`,
      ORIGIN,
      `approval:${ID}`,
    );
    assert.equal(o.title, "Approved — moved 78 entries to the Trash");
    assert.equal(o.badge, 4);
    assert.equal(o.open, false);
    assert.equal(o.options.tag, `approval:${ID}`);
    assert.equal(o.options.data.url, `${ORIGIN}/workspace/settings/ai-ask?thread=${ID}`);
  });

  test("failure: says why and opens the conversation; a foreign link in the answer is ignored", () => {
    const thread = `${ORIGIN}/workspace/settings/ai-ask?thread=${ID}`;
    const o = approvalOutcome("approve", false, { detail: "This approval was already decided." }, thread, ORIGIN);
    assert.equal(o.title, "Couldn't approve: This approval was already decided.");
    assert.equal(o.open, true);
    assert.equal(o.url, thread);
    assert.equal(o.badge, null);
    assert.equal(approvalOutcome("deny", false, null, thread, ORIGIN).title, "Couldn't deny: Marvin didn't answer.");
    assert.equal(approvalOutcome("approve", true, { url: "https://evil.example/" }, thread, ORIGIN).url, `${ORIGIN}/`);
  });
});

test("the worker template has every marker the build fills in", () => {
  const source = readFileSync(new URL("./sw.js", import.meta.url), "utf8");
  for (const marker of ["__MARVIN_SW_VERSION__", "__MARVIN_SW_PRECACHE__", "/* __MARVIN_SW_LOGIC__ */"])
    assert.ok(source.includes(marker), marker);
});
