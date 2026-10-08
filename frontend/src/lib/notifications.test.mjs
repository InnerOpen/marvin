// Settings → Automation → Notifications helpers (notifications.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { buildUpdate, channelKinds, draftFrom, kindsSummary, reminderHours, takes } from "./notifications.ts";

const ALL = ["workflow_failed", "scheduled_task_failed", "integration_attention"];

describe("a channel's kinds", () => {
  test("every kind ticked is null, so a kind added later is taken too", () => {
    assert.equal(channelKinds(["integration_attention", "workflow_failed", "scheduled_task_failed"], ALL), null);
  });
  test("otherwise the ticked ones, in the page's order", () => {
    assert.deepEqual(channelKinds(["integration_attention", "workflow_failed"], ALL), [
      "workflow_failed",
      "integration_attention",
    ]);
    assert.deepEqual(channelKinds([], ALL), []);
  });
  test("takes", () => {
    assert.equal(takes(null, "anything"), true);
    assert.equal(takes(["workflow_failed"], "workflow_failed"), true);
    assert.equal(takes(["workflow_failed"], "integration_attention"), false);
  });
  test("in words", () => {
    const labels = { workflow_failed: "Workflow failed", integration_attention: "Integration needs attention" };
    assert.equal(kindsSummary(null, labels), "Every kind");
    assert.equal(kindsSummary([], labels), "None");
    assert.equal(
      kindsSummary(["workflow_failed", "integration_attention"], labels),
      "Workflow failed, Integration needs attention",
    );
  });
});

describe("reminderHours", () => {
  test("whole hours from 0 to 720; anything else keeps what it was", () => {
    assert.equal(reminderHours("6", 24), 6);
    assert.equal(reminderHours("0", 24), 0);
    assert.equal(reminderHours("-3", 24), 0);
    assert.equal(reminderHours("9999", 24), 720);
    assert.equal(reminderHours("", 24), 24);
  });
});

describe("buildUpdate", () => {
  const route = {
    id: "r1",
    integrationId: "i1",
    action: "send_message",
    args: { channel: "#ops", priority: " " },
    enabled: true,
    kinds: ["scheduled_task_failed"],
    label: "Ops → Send message",
    problem: null,
    lastDelivery: null,
  };

  test("every owner and admin sends recipients null; a list is parsed", () => {
    const base = {
      types: {},
      emailEnabled: true,
      recipientsText: "a@x.test, A@x.test",
      emailKinds: null,
      routes: [],
      reminderHours: 24,
    };
    assert.equal(buildUpdate({ ...base, everyAdmin: true }).email.recipients, null);
    assert.deepEqual(buildUpdate({ ...base, everyAdmin: false }).email.recipients, ["a@x.test"]);
  });

  test("push goes in only when the page shows it (the server has Web Push)", () => {
    const base = {
      types: {},
      emailEnabled: true,
      everyAdmin: true,
      recipientsText: "",
      emailKinds: null,
      routes: [],
      reminderHours: 24,
    };
    assert.equal("push" in buildUpdate(base), false);
    assert.equal("push" in buildUpdate({ ...base, push: null }), false);
    assert.deepEqual(buildUpdate({ ...base, push: { enabled: false, kinds: ["workflow_failed"] } }).push, {
      enabled: false,
      kinds: ["workflow_failed"],
    });
  });

  test("routes keep their id and kinds, empty arguments left out; a new route has no id", () => {
    const update = buildUpdate({
      types: { ai_operation_failed: true },
      emailEnabled: false,
      everyAdmin: true,
      recipientsText: "",
      emailKinds: ["workflow_failed"],
      routes: [draftFrom(route), { integrationId: "i2", action: "notify", args: {}, enabled: false, kinds: null }],
      reminderHours: 0,
    });
    assert.deepEqual(update, {
      types: { ai_operation_failed: true },
      email: { enabled: false, recipients: null, kinds: ["workflow_failed"] },
      routes: [
        {
          id: "r1",
          integrationId: "i1",
          action: "send_message",
          enabled: true,
          kinds: ["scheduled_task_failed"],
          args: { channel: "#ops" },
        },
        { integrationId: "i2", action: "notify", enabled: false, kinds: null, args: {} },
      ],
      integrationReminderHours: 0,
    });
  });

  test("a draft is a copy: editing it leaves the saved route alone", () => {
    const draft = draftFrom(route);
    draft.args.channel = "#other";
    draft.kinds?.push("workflow_failed");
    assert.equal(route.args.channel, "#ops");
    assert.deepEqual(route.kinds, ["scheduled_task_failed"]);
  });
});
