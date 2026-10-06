// Events hub helpers (eventConnections.ts): grouping, what the event page manages itself, the catalog's
// per-type state, dates, links and the builder's ?trigger=. Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  countsTitle,
  dotState,
  eventLogHref,
  formatWhen,
  groupReactions,
  groupSenders,
  isConnected,
  isSystemEmail,
  managedHere,
  newWorkflowHref,
  parseApiDate,
  systemEmailNote,
  triggerableEvents,
  triggerFromQuery,
} from "./eventConnections.ts";

const square = { integrationId: "i1", name: "Square", provider: "square", blueprint: "sell_online" };
const r = (kind, name, extra = {}) => ({ kind, name, enabled: true, ...extra });
const counts = (extra = {}) => ({
  eventType: "entry_published",
  senders: 1,
  reactions: 0,
  activeReactions: 0,
  builtinReactions: 0,
  lastOccurredAt: null,
  ...extra,
});
const NOW = new Date("2026-10-06T12:00:00Z");

describe("groupReactions", () => {
  test("fixed order, workflows first and built-in last; empty kinds left out", () => {
    const groups = groupReactions([
      r("builtin", "Queues a site rebuild"),
      r("webhook", "Rebuild hook"),
      r("workflow", "Email an issue"),
      r("email", "Welcome"),
      r("workflow", "Summarize"),
    ]);
    assert.deepEqual(
      groups.map((g) => [g.kind, g.label, g.rows.map((x) => x.name)]),
      [
        ["workflow", "Workflows", ["Email an issue", "Summarize"]],
        ["email", "Emails", ["Welcome"]],
        ["webhook", "Webhooks", ["Rebuild hook"]],
        ["builtin", "Built-in", ["Queues a site rebuild"]],
      ],
    );
  });

  test("nothing in, nothing out", () => {
    assert.deepEqual(groupReactions([]), []);
  });
});

describe("groupSenders", () => {
  test("Marvin's own lines first, then workflows, incoming webhooks, scheduled tasks", () => {
    const groups = groupSenders([
      r("scheduled_task", "Nightly publish"),
      r("incoming_webhook", "Pages hook"),
      r("marvin", "Publishing an entry"),
      r("workflow", "Turn on Sell online"),
    ]);
    assert.deepEqual(
      groups.map((g) => g.label),
      ["Marvin", "Workflows", "Incoming webhooks", "Scheduled tasks"],
    );
  });
});

describe("managedHere", () => {
  test("emails, webhooks and integration actions people connected are managed on the event page", () => {
    assert.equal(managedHere(r("email", "Notify", { detail: "To the workspace admins" })), true);
    assert.equal(managedHere(r("webhook", "Hook")), true);
    assert.equal(managedHere(r("integration_action", "Slack", { detail: "post_message" })), true);
  });

  test("workflows, built-ins, the system email and anything an integration installed are not", () => {
    assert.equal(managedHere(r("workflow", "Mine")), false);
    assert.equal(managedHere(r("builtin", "Indexes it")), false);
    assert.equal(managedHere(r("email", "Invitation", { detail: "System template" })), false);
    assert.equal(managedHere(r("integration_action", "Square", { installedBy: square })), false);
    assert.equal(managedHere(r("workflow", "Square sync", { installedBy: square })), false);
  });
});

describe("system email", () => {
  test("is the email row whose detail is 'System template'", () => {
    assert.equal(isSystemEmail(r("email", "Invitation", { detail: "System template" })), true);
    assert.equal(isSystemEmail(r("email", "Mine", { detail: "To the workspace admins" })), false);
    assert.equal(isSystemEmail(r("webhook", "x", { detail: "System template" })), false);
  });

  test("its note says whether it sends", () => {
    assert.match(systemEmailNote(r("email", "Invitation", { detail: "System template" })), /sends unless you connect/);
    assert.match(
      systemEmailNote(r("email", "Invitation", { detail: "System template", enabled: false })),
      /Not sent: your own template replaces it/,
    );
  });
});

describe("catalog state", () => {
  test("dot: active when something runs, off when every reaction is switched off, none otherwise", () => {
    assert.equal(dotState(undefined), "none");
    assert.equal(dotState(counts()), "none");
    assert.equal(dotState(counts({ builtinReactions: 3 })), "none", "built-ins alone aren't the workspace's");
    assert.equal(dotState(counts({ reactions: 2, activeReactions: 1 })), "active");
    assert.equal(dotState(counts({ reactions: 2, activeReactions: 0 })), "off");
  });

  test("connected: any reaction, switched off or not", () => {
    assert.equal(isConnected(undefined), false);
    assert.equal(isConnected(counts()), false);
    assert.equal(isConnected(counts({ reactions: 1 })), true);
  });

  test("tooltip names both directions, counted", () => {
    assert.equal(
      countsTitle(
        counts({
          senders: 3,
          reactions: 3,
          activeReactions: 2,
          builtinReactions: 2,
          lastOccurredAt: "2026-10-06T09:00:00",
        }),
        NOW,
      ),
      "Sent by 3 senders · 3 reactions (1 switched off) · 2 built-in · last 3 hours ago",
    );
    assert.equal(countsTitle(counts({ senders: 0 }), NOW), "Nothing sends it yet · No reactions in this workspace");
    assert.equal(
      countsTitle(counts({ senders: 1, reactions: 1, activeReactions: 1 }), NOW),
      "Sent by 1 sender · 1 reaction",
    );
    assert.equal(countsTitle(undefined), "");
  });
});

describe("dates", () => {
  test("API datetimes without a zone are UTC; microseconds are trimmed", () => {
    assert.equal(parseApiDate("2026-10-06T09:00:00.123456").toISOString(), "2026-10-06T09:00:00.123Z");
    assert.equal(parseApiDate("2026-10-06T09:00:00+02:00").toISOString(), "2026-10-06T07:00:00.000Z");
    assert.equal(parseApiDate("2026-10-06T09:00:00Z").toISOString(), "2026-10-06T09:00:00.000Z");
  });

  test("formatWhen: relative, then the date", () => {
    assert.equal(formatWhen("2026-10-06T11:59:30Z", NOW), "just now");
    assert.equal(formatWhen("2026-10-06T11:55:00Z", NOW), "5 min ago");
    assert.equal(formatWhen("2026-10-06T11:00:00Z", NOW), "1 hour ago");
    assert.equal(formatWhen("2026-10-04T12:00:00Z", NOW), "2 days ago");
    assert.equal(formatWhen("2026-08-01T12:00:00Z", NOW), "2026-08-01");
    assert.equal(formatWhen("not a date", NOW), "not a date");
  });
});

describe("links", () => {
  test("a recent event opens in the Event Log; a new workflow opens the builder on the event", () => {
    assert.equal(eventLogHref("a b"), "/workspace/events?event=a%20b");
    assert.equal(newWorkflowHref("entry_published"), "/automation/workflows?trigger=entry_published");
  });
});

describe("builder ?trigger=", () => {
  const options = {
    triggers: ["flat"],
    triggerGroups: { Entries: ["entry_published", "entry_updated"], Site: ["site_deployment_completed"] },
  };

  test("triggerable events come from the groups, else the flat list", () => {
    assert.deepEqual(triggerableEvents(options), ["entry_published", "entry_updated", "site_deployment_completed"]);
    assert.deepEqual(triggerableEvents({ triggers: ["a"] }), ["a"]);
    assert.deepEqual(triggerableEvents(null), []);
  });

  test("only an event the builder can trigger on is taken", () => {
    const events = triggerableEvents(options);
    assert.equal(triggerFromQuery("?trigger=entry_updated", events), "entry_updated");
    assert.equal(triggerFromQuery("?trigger=user_signup", events), null);
    assert.equal(triggerFromQuery("?workflow=x", events), null);
    assert.equal(triggerFromQuery("", events), null);
  });
});
