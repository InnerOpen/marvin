// Automation results (automationResults.ts): the states and tiles, a row, the action buttons, filters, the empty state and the one line
// the entry editor shows. Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  actionButtons,
  actionError,
  apiQuery,
  connectionOptions,
  DASHBOARD_LINKS,
  detailLines,
  emptyNotice,
  entryLine,
  filtersToQuery,
  hasFilters,
  NO_FILTERS,
  openEntryHref,
  parseFilters,
  resultRow,
  showResults,
  standing,
  stateBadge,
  stateOf,
  stateTiles,
} from "./automationResults.ts";

const NOW = new Date("2026-10-20T12:00:00Z");
const ENTRY = "11111111-2222-4333-8444-555555555555";

const result = (extra = {}) => ({
  id: "r1",
  status: "in_flight",
  noReply: false,
  entry: { id: ENTRY, title: "Launch notes", slug: "launch-notes" },
  connection: { slug: "automation", name: "Marketing flows", provider: "flow" },
  workflow: { id: "w1", name: "Hand off published posts", slug: "hand-off" },
  target: "marvin/new-entry",
  remoteId: "812",
  remoteUrl: "https://flows.example.test/run/812",
  message: null,
  sentAt: "2026-10-20T11:00:00Z",
  finishedAt: null,
  attempt: 1,
  dismissed: false,
  canRetry: false,
  ...extra,
});

describe("the Automation hub's link", () => {
  test("Results is listed only once a hand-off has been kept", () => {
    assert.equal(showResults({ show: true }), true);
    assert.equal(showResults({ show: false }), false);
  });

  test("a summary that could not be read lists nothing rather than guessing", () => {
    assert.equal(showResults(null), false);
    assert.equal(showResults(undefined), false);
  });
});

describe("states and badges", () => {
  test("an in-flight result the backend flags as having no reply is in the No reply state", () => {
    assert.equal(stateOf(result({ noReply: true })), "no_reply");
    assert.equal(stateOf(result()), "in_flight");
  });

  test("a settled result is never No reply, even if the flag were set", () => {
    assert.equal(stateOf(result({ status: "failed", noReply: true })), "failed");
    assert.equal(stateOf(result({ status: "succeeded" })), "succeeded");
  });

  test("each state has a badge in Marvin's words", () => {
    assert.deepEqual(
      ["in_flight", "failed", "succeeded"].map((status) => stateBadge(result({ status })).label),
      ["In flight", "Failed", "Succeeded"],
    );
    assert.equal(stateBadge(result({ noReply: true })).label, "No reply");
  });

  test("a failure and a late hand-off are drawn as needing attention, in different tones", () => {
    assert.equal(stateBadge(result({ status: "failed" })).tone, "bad");
    assert.equal(stateBadge(result({ noReply: true })).tone, "warn");
  });

  test("a dismissed failure reads Dismissed and goes quiet", () => {
    const badge = stateBadge(result({ status: "failed", dismissed: true }));
    assert.equal(badge.label, "Dismissed");
    assert.equal(badge.tone, "muted");
  });
});

describe("the tiles", () => {
  const counts = { show: true, inFlight: 2, noReply: 1, failed: 3, succeeded: 40, attention: 4 };

  test("four tiles in the order In flight, No reply, Failed, Succeeded carry the workspace's counts", () => {
    const tiles = stateTiles(counts);
    assert.deepEqual(tiles.map((t) => [t.value, t.label, t.count]), [
      ["in_flight", "In flight", 2],
      ["no_reply", "No reply", 1],
      ["failed", "Failed", 3],
      ["succeeded", "Succeeded", 40],
    ]);
  });

  test("the tile of the active filter is marked and the others are not", () => {
    assert.deepEqual(stateTiles(counts, "failed").filter((t) => t.active).map((t) => t.value), ["failed"]);
  });

  test("missing counts read as zero rather than blank", () => {
    assert.deepEqual(stateTiles(null).map((t) => t.count), [0, 0, 0, 0]);
  });
});

describe("a row", () => {
  test("shows the entry, the connection and target, and says an in-flight one is waiting", () => {
    const row = resultRow(result());
    assert.equal(row.title, "Launch notes");
    assert.equal(row.connection, "Marketing flows");
    assert.equal(row.target, "marvin/new-entry");
    assert.equal(row.text, "Waiting to hear back");
    assert.equal(row.at, "2026-10-20T11:00:00Z");
    assert.equal(row.unread, false);
  });

  test("a settled row shows the message and the time it finished", () => {
    const row = resultRow(result({ status: "failed", message: "Workflow not found", finishedAt: "2026-10-20T11:30:00Z" }));
    assert.equal(row.text, "Workflow not found");
    assert.equal(row.at, "2026-10-20T11:30:00Z");
    assert.equal(row.unread, true);
  });

  test("a long message is cut at a word with an ellipsis", () => {
    const row = resultRow(result({ status: "failed", message: "word ".repeat(100) }));
    assert.ok(row.text.endsWith("…"));
    assert.ok(row.text.length <= 141);
  });

  test("a failure and a late hand-off are bold, a dismissed failure and a success are not", () => {
    assert.equal(resultRow(result({ status: "failed" })).unread, true);
    assert.equal(resultRow(result({ noReply: true })).unread, true);
    assert.equal(resultRow(result({ status: "failed", dismissed: true })).unread, false);
    assert.equal(resultRow(result({ status: "succeeded" })).unread, false);
  });

  test("a hand-off that is not about an entry says so, and one with no connection leaves it blank", () => {
    const row = resultRow(result({ entry: null, connection: null }));
    assert.equal(row.title, "Not about an entry");
    assert.equal(row.connection, "");
  });
});

describe("the open result", () => {
  test("lists the connection, target, workflow, run, and when it was sent, and counts attempts past the first", () => {
    const lines = detailLines(result({ attempt: 3 }), NOW);
    assert.deepEqual(lines.map((l) => l.label), ["Connection", "Target", "Workflow", "Run", "Sent", "Attempts"]);
    assert.equal(lines.find((l) => l.label === "Sent")?.value, "1 h ago");
    assert.equal(lines.find((l) => l.label === "Attempts")?.value, "3");
  });

  test("leaves out what is not there", () => {
    const lines = detailLines(result({ connection: null, target: null, workflow: null, remoteId: null }), NOW);
    assert.deepEqual(lines.map((l) => l.label), ["Sent"]);
  });

  test("a failure says Failed and when, a success Finished", () => {
    assert.equal(detailLines(result({ status: "failed", finishedAt: "2026-10-20T11:50:00Z" }), NOW).at(-1)?.label, "Failed");
    assert.equal(detailLines(result({ status: "succeeded", finishedAt: "2026-10-20T11:50:00Z" }), NOW).at(-1)?.label, "Finished");
  });

  test("standing says where it is in a sentence", () => {
    assert.equal(standing(result(), NOW), "Waiting to hear back, sent 1 h ago");
    assert.equal(standing(result({ noReply: true, sentAt: "2026-10-18T12:00:00Z" }), NOW), "No reply since it was sent 2 d ago");
    assert.equal(standing(result({ status: "failed", finishedAt: "2026-10-20T11:55:00Z" }), NOW), "Failed 5 min ago");
    assert.equal(standing(result({ status: "succeeded", finishedAt: "2026-10-20T11:59:30Z" }), NOW), "Finished just now");
  });

  test("Open entry goes to the entry editor and comes back to this page", () => {
    assert.equal(openEntryHref(result(), "/automation/results?status=failed"), `/workspace/entries/${ENTRY}?return=%2Fautomation%2Fresults%3Fstatus%3Dfailed`);
  });

  test("a result with no entry has no Open entry link", () => {
    assert.equal(openEntryHref(result({ entry: null }), "/automation/results"), null);
  });
});

describe("Retry and Dismiss", () => {
  test("an admin sees Retry and Dismiss on a failure the backend says can be retried", () => {
    const keys = actionButtons(result({ status: "failed", canRetry: true }), { act: true }).map((b) => b.key);
    assert.deepEqual(keys, ["retry", "dismiss"]);
  });

  test("a failure that cannot be retried offers only Dismiss", () => {
    assert.deepEqual(actionButtons(result({ status: "failed", canRetry: false }), { act: true }).map((b) => b.key), ["dismiss"]);
  });

  test("a failure already dismissed offers Retry but not Dismiss again", () => {
    assert.deepEqual(actionButtons(result({ status: "failed", canRetry: true, dismissed: true }), { act: true }).map((b) => b.key), ["retry"]);
  });

  test("nothing is offered on a result that did not fail", () => {
    assert.deepEqual(actionButtons(result({ status: "in_flight", canRetry: true }), { act: true }), []);
    assert.deepEqual(actionButtons(result({ status: "succeeded" }), { act: true }), []);
  });

  test("an editor, who may read but not act, sees no buttons", () => {
    assert.deepEqual(actionButtons(result({ status: "failed", canRetry: true }), { act: false }), []);
    assert.deepEqual(actionButtons(result({ status: "failed", canRetry: true }), undefined), []);
  });

  test("a refused retry shows the backend's reason as it is", () => {
    const refused = Object.assign(new Error("The workflow “Hand off” is switched off. Turn it on to retry."), { status: 409 });
    assert.equal(actionError(refused), "The workflow “Hand off” is switched off. Turn it on to retry.");
  });

  test("a forbidden answer says retrying is for admins, and an empty error still says something", () => {
    assert.equal(actionError(Object.assign(new Error("Forbidden"), { status: 403 })), "Retrying and dismissing are for admins.");
    assert.equal(actionError(new Error("  ")), "Something went wrong.");
  });
});

describe("filters", () => {
  test("a status, connection, entry and search are read from the address", () => {
    const f = parseFilters(new URLSearchParams(`status=failed&connection=automation&entry=${ENTRY}&q=%20launch%20`));
    assert.deepEqual(f, { status: "failed", connection: "automation", entry: ENTRY, q: "launch" });
  });

  test("an unknown status and a malformed entry id are ignored", () => {
    const f = parseFilters(new URLSearchParams("status=exploded&entry=not-an-id"));
    assert.deepEqual(f, NO_FILTERS);
  });

  test("the dashboard's two links open the page already filtered", () => {
    assert.equal(parseFilters(new URL(`http://x${DASHBOARD_LINKS.failed.href}`).searchParams).status, "failed");
    assert.equal(parseFilters(new URL(`http://x${DASHBOARD_LINKS.noReply.href}`).searchParams).status, "no_reply");
  });

  test("the page's query string omits what is empty and round-trips", () => {
    assert.equal(filtersToQuery(NO_FILTERS), "");
    const f = { status: "no_reply", connection: "", entry: "", q: "launch" };
    assert.equal(filtersToQuery(f), "?status=no_reply&q=launch");
    assert.deepEqual(parseFilters(new URLSearchParams(filtersToQuery(f))), f);
  });

  test("the API query carries the filters and the page size, with entry as entry_id", () => {
    const q = new URLSearchParams(apiQuery({ status: "no_reply", connection: "automation", entry: ENTRY, q: "x" }, 0, 25));
    assert.equal(q.get("status"), "no_reply");
    assert.equal(q.get("connection"), "automation");
    assert.equal(q.get("entry_id"), ENTRY);
    assert.equal(q.get("q"), "x");
    assert.equal(q.get("limit"), "25");
    assert.equal(q.has("offset"), false);
  });

  test("a later page adds its offset", () => {
    assert.equal(new URLSearchParams(apiQuery(NO_FILTERS, 50)).get("offset"), "50");
  });

  test("the Failed view leaves out dismissed failures so the list matches the tile, and other views keep them", () => {
    assert.equal(new URLSearchParams(apiQuery({ ...NO_FILTERS, status: "failed" })).get("include_dismissed"), "false");
    assert.equal(new URLSearchParams(apiQuery({ ...NO_FILTERS, status: "succeeded" })).has("include_dismissed"), false);
    assert.equal(new URLSearchParams(apiQuery(NO_FILTERS)).has("include_dismissed"), false);
  });

  test("hasFilters is true for any one filter", () => {
    assert.equal(hasFilters(NO_FILTERS), false);
    assert.equal(hasFilters({ ...NO_FILTERS, connection: "automation" }), true);
    assert.equal(hasFilters({ ...NO_FILTERS, entry: ENTRY }), true);
  });

  test("the connection filter lists each connection by its name", () => {
    assert.deepEqual(connectionOptions([{ slug: "automation", name: "Marketing flows", provider: "flow" }]), [{ value: "automation", label: "Marketing flows" }]);
    assert.deepEqual(connectionOptions(null), []);
  });
});

describe("the empty state", () => {
  test("a filter that matches nothing says so", () => {
    assert.equal(emptyNotice({ show: true }, true).title, "Nothing matches these filters");
  });

  test("before any hand-off the page says nothing has been handed off and where one comes from", () => {
    const notice = emptyNotice({ show: false }, false);
    assert.equal(notice.title, "Nothing has been handed off yet");
    assert.equal(notice.link?.href, "/automation/workflows");
  });

  test("once there are results an empty list is just empty", () => {
    assert.equal(emptyNotice({ show: true }, false).title, "Nothing here yet");
  });
});

describe("the entry editor's line", () => {
  test("an in-flight hand-off reads Sent to the connection, in flight", () => {
    const line = entryLine(result());
    assert.equal(line.text, "Sent to Marketing flows · in flight");
    assert.equal(line.tone, "new");
  });

  test("one with no reply reads no reply yet, in a warning tone", () => {
    const line = entryLine(result({ noReply: true }));
    assert.equal(line.text, "Sent to Marketing flows · no reply yet");
    assert.equal(line.tone, "warn");
  });

  test("a finished one reads done", () => {
    assert.equal(entryLine(result({ status: "succeeded" })).text, "Sent to Marketing flows · done");
  });

  test("a failure reads the connection's name and why", () => {
    const line = entryLine(result({ status: "failed", message: "Workflow not found" }));
    assert.equal(line.text, "Marketing flows failed: Workflow not found");
    assert.equal(line.tone, "bad");
  });

  test("a dismissed failure says so and goes quiet", () => {
    const line = entryLine(result({ status: "failed", message: "boom", dismissed: true }));
    assert.equal(line.text, "Marketing flows failed: boom (dismissed)");
    assert.equal(line.tone, "muted");
  });

  test("carries the run's link when the other side gave one, and a link to the Results page filtered to this entry", () => {
    const line = entryLine(result());
    assert.equal(line.runUrl, "https://flows.example.test/run/812");
    assert.equal(line.href, `/automation/results?entry=${ENTRY}`);
    assert.equal(entryLine(result({ remoteUrl: null })).runUrl, null);
  });

  test("a result whose connection is gone still reads sensibly", () => {
    assert.equal(entryLine(result({ connection: null })).text, "Sent · in flight");
    assert.equal(entryLine(result({ connection: null, status: "failed", message: "boom" })).text, "The hand-off failed: boom");
  });
});
