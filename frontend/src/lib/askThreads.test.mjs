// The Ask page's threads panel grouping (askThreads.ts). Run with `npm test` — plain `node --test`,
// which strips askThreads.ts's types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { activityOf, groupThreads, handOffNote } from "./askThreads.ts";

const thread = (id, agentSlug, minute, over = {}) => ({
  id,
  agentSlug,
  title: id,
  createdBy: "u1",
  parentThreadId: null,
  parentTitle: null,
  status: "open",
  totalTokens: 0,
  lastMessageAt: `2026-10-01T12:${String(minute).padStart(2, "0")}:00`,
  createdAt: null,
  ...over,
});
const child = (id, agentSlug, minute, parent) =>
  thread(id, agentSlug, minute, { parentThreadId: parent.id, parentTitle: parent.title });
const shape = (groups) => groups.map((g) => [g.thread.id, g.children.map((c) => c.id)]);

describe("groupThreads", () => {
  test("nests hand-offs under their parent across agents, newest first", () => {
    const route = thread("route", "marvin", 10);
    const ask = thread("ask", "ask", 20);
    const rows = [ask, route, child("mail", "studio-mail", 11, route), child("cat", "cataloguer", 12, route)];
    assert.deepEqual(shape(groupThreads(rows)), [
      ["ask", []],
      ["route", ["cat", "mail"]],
    ]);
  });

  test("orders a row by its latest activity, its hand-offs included", () => {
    const route = thread("route", "marvin", 10);
    const rows = [thread("ask", "ask", 20), route, child("cat", "cataloguer", 30, route)];
    assert.deepEqual(
      groupThreads(rows).map((g) => g.thread.id),
      ["route", "ask"],
    );
  });

  test("with an agent, that agent's hand-off threads are rows of their own", () => {
    const route = thread("route", "marvin", 10);
    const rows = [child("cat", "cataloguer", 12, route), thread("direct", "cataloguer", 5)];
    assert.deepEqual(shape(groupThreads(rows, "cataloguer")), [
      ["cat", []],
      ["direct", []],
    ]);
  });

  test("with the router agent, its hand-offs still nest under it", () => {
    const route = thread("route", "marvin", 10);
    const rows = [child("cat", "cataloguer", 12, route), route];
    assert.deepEqual(shape(groupThreads(rows, "marvin")), [["route", ["cat"]]]);
  });

  test("a hand-off whose parent is not a row is shown on its own, not dropped", () => {
    const rows = [thread("orphan", "cataloguer", 3, { parentThreadId: "gone", parentTitle: "Old" })];
    assert.deepEqual(shape(groupThreads(rows)), [["orphan", []]]);
  });

  test("returns no rows for no threads", () => {
    assert.deepEqual(groupThreads([]), []);
  });
});

describe("activityOf", () => {
  test("reads a naive timestamp as UTC and falls back to createdAt", () => {
    assert.equal(activityOf(thread("a", "ask", 0)), Date.UTC(2026, 9, 1, 12, 0));
    assert.equal(
      activityOf(thread("b", "ask", 0, { lastMessageAt: null, createdAt: "2026-10-01T12:05:00+00:00" })),
      Date.UTC(2026, 9, 1, 12, 5),
    );
  });

  test("is 0 without any timestamp", () => {
    assert.equal(activityOf(thread("a", "ask", 0, { lastMessageAt: null })), 0);
  });
});

describe("handOffNote", () => {
  test("names the parent thread of a hand-off", () => {
    const route = thread("route", "marvin", 10, { title: "Catalogue the new mugs" });
    assert.equal(handOffNote(child("cat", "cataloguer", 12, route)), "from a hand-off in “Catalogue the new mugs”");
  });

  test("still says it is a hand-off when the parent is untitled", () => {
    assert.equal(handOffNote(thread("cat", "cataloguer", 1, { parentThreadId: "p" })), "from a hand-off");
  });

  test("is null for a top-level thread", () => {
    assert.equal(handOffNote(thread("route", "marvin", 1)), null);
  });
});
