// The service worker's decisions (sw-logic.js): what is cached, what never is, and where a notification may
// lead. Run with `npm test` — plain `node --test`.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

import {
  acceptedType,
  approvalOf,
  approvalOutcome,
  approvalRequest,
  cacheable,
  cacheNames,
  httpUrl,
  isShareTarget,
  notificationFromPush,
  parsePush,
  SHARE_CACHE,
  SHARE_MAX_FILES,
  SHARE_TTL_MS,
  safeTarget,
  shareExpired,
  shareFrom,
  shareIdOf,
  shareKeys,
  sharePageUrl,
  staleCaches,
  strategy,
  switchRequest,
  workspaceOf,
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

describe("Share to Marvin", () => {
  const ID = "6f1c2a8e-3b4d-4e5f-8a9b-0c1d2e3f4a5b";

  test("only a same-origin POST to the share target is taken", () => {
    assert.ok(isShareTarget(req("/share-target", { method: "POST" }), ORIGIN));
    assert.ok(!isShareTarget(req("/share-target"), ORIGIN));
    assert.ok(!isShareTarget(req("/share-target/x", { method: "POST" }), ORIGIN));
    assert.ok(!isShareTarget(req("/share-target", { method: "POST", origin: "https://evil.example" }), ORIGIN));
    assert.ok(!isShareTarget({ url: "nonsense", method: "POST" }, ORIGIN));
  });

  test("images, videos and PDFs come along; the rest is dropped and counted; at most SHARE_MAX_FILES", () => {
    const files = [
      { name: "a.jpg", type: "image/jpeg", size: 10 },
      { name: "b.mp4", type: "video/mp4", size: 20 },
      { name: "c.pdf", type: "application/pdf", size: 30 },
      { name: "d.exe", type: "application/x-msdownload", size: 40 },
      { name: "e.html", type: "text/html", size: 50 },
    ];
    const s = shareFrom({ title: " Trip ", text: "notes", url: "", files }, 1000);
    assert.deepEqual(
      s.files.map((f) => f.name),
      ["a.jpg", "b.mp4", "c.pdf"],
    );
    assert.equal(s.dropped, 2);
    assert.equal(s.title, "Trip");
    assert.equal(s.createdAt, 1000);
    const many = Array.from({ length: 15 }, (_, i) => ({ name: `${i}.png`, type: "image/png", size: 1 }));
    const capped = shareFrom({ files: many });
    assert.equal(capped.files.length, SHARE_MAX_FILES);
    assert.equal(capped.dropped, 15 - SHARE_MAX_FILES);
    assert.ok(acceptedType("IMAGE/PNG") && !acceptedType("image") && !acceptedType(undefined));
  });

  test("the link: the url field, else the first http(s) URL in the text — never another scheme", () => {
    assert.equal(shareFrom({ url: "https://e.com/a" }).url, "https://e.com/a");
    assert.equal(shareFrom({ text: "look at this https://e.com/b, nice" }).url, "https://e.com/b");
    assert.equal(shareFrom({ url: "javascript:alert(1)", text: "no link" }).url, null);
    assert.equal(shareFrom({ url: "data:text/html,x" }).url, null);
    assert.equal(httpUrl("http://e.com"), "http://e.com/");
    assert.equal(httpUrl("file:///etc/passwd"), null);
  });

  test("its parts live under its id in the share cache, which outlives a new build but not its hour", () => {
    const keys = shareKeys(ID, ORIGIN);
    assert.equal(shareIdOf(keys.meta), ID);
    assert.equal(shareIdOf(keys.file(3)), ID);
    assert.equal(shareIdOf(`${ORIGIN}/__share/../x/meta.json`), null);
    assert.deepEqual(staleCaches([SHARE_CACHE, "marvin-shell-v1"], "v2"), ["marvin-shell-v1"]);
    const now = 10 * SHARE_TTL_MS;
    assert.ok(!shareExpired({ createdAt: now - 1000 }, now));
    assert.ok(shareExpired({ createdAt: now - SHARE_TTL_MS - 1 }, now));
    assert.ok(shareExpired(null, now) && shareExpired({ createdAt: "x" }, now));
  });

  test("then the Share page, for that share or with why not", () => {
    assert.equal(sharePageUrl(ORIGIN, ID), `${ORIGIN}/share?id=${ID}`);
    assert.equal(sharePageUrl(ORIGIN, "", "unreadable"), `${ORIGIN}/share?error=unreadable`);
  });
});

test("the worker template has every marker the build fills in", () => {
  const source = readFileSync(new URL("./sw.js", import.meta.url), "utf8");
  for (const marker of ["__MARVIN_SW_VERSION__", "__MARVIN_SW_PRECACHE__", "/* __MARVIN_SW_LOGIC__ */"])
    assert.ok(source.includes(marker), marker);
});

describe("notifications open in their workspace", () => {
  const WS = "3f2c1b6e-0d4a-4c1e-9b7a-2e5f8c9d0a11";
  const OTHER = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d";

  test("a push names its workspace in the notification's data; a malformed one is dropped", () => {
    assert.equal(notificationFromPush({ url: "/x", workspace: WS }, ORIGIN).options.data.workspace, WS);
    assert.equal(notificationFromPush({ url: "/x", workspace: "../admin" }, ORIGIN).options.data.workspace, undefined);
    assert.equal(workspaceOf(42), null);
  });

  test("switching happens only when the workspace differs from the current one", () => {
    const request = switchRequest(WS, OTHER);
    assert.equal(request.url, "/api/self/workspaces/current");
    assert.equal(request.init.method, "PUT");
    assert.deepEqual(JSON.parse(request.init.body), { workspace: WS });
    assert.equal(switchRequest(WS, WS.toUpperCase()), null);
    assert.equal(switchRequest(null, OTHER), null);
    assert.notEqual(switchRequest(WS, null), null); // current unknown: switch to be sure
  });

  test("an approval that can't be decided opens its conversation in the conversation's workspace", () => {
    const fromServer = approvalOutcome("approve", false, { workspace: WS }, "/a", ORIGIN);
    assert.equal(fromServer.workspace, WS);
    const fromPush = approvalOutcome("approve", false, null, "/a", ORIGIN, "", OTHER);
    assert.equal(fromPush.workspace, OTHER);
    assert.equal(fromPush.options.data.workspace, OTHER);
  });
});
