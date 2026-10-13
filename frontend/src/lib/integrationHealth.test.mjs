// Alerts & health page words (integrationHealth.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  duration,
  failureLine,
  pageCount,
  pageHref,
  pageParam,
  relative,
  reminderText,
  resolutionLabel,
  retryState,
} from "./integrationHealth.ts";

const NOW = new Date("2026-10-05T12:00:00Z");
const at = (minutes) => new Date(NOW.getTime() + minutes * 60_000).toISOString();

describe("duration / relative", () => {
  test("reads at the right scale", () => {
    assert.equal(duration(45), "45s");
    assert.equal(duration(7 * 60), "7 min");
    assert.equal(duration(5 * 3600), "5h");
    assert.equal(duration(5 * 3600 + 12 * 60), "5h 12m");
    assert.equal(duration(3 * 86400 + 4 * 3600), "3d 4h");
    assert.equal(duration(null), "");
  });

  test("past, future and now", () => {
    assert.equal(relative(at(-3), NOW), "3 min ago");
    assert.equal(relative(at(120), NOW), "in 2h");
    assert.equal(relative(at(0), NOW), "just now");
    assert.equal(relative(null, NOW), "");
    assert.equal(relative("not a date", NOW), "");
  });
});

describe("resolutionLabel", () => {
  test("names how it ended", () => {
    assert.equal(resolutionLabel("manual", "Ada"), "Resolved by Ada");
    assert.equal(resolutionLabel("manual"), "Resolved by an admin");
    assert.equal(resolutionLabel("check"), "A health check passed");
    assert.equal(resolutionLabel("action"), "An action succeeded");
    assert.equal(resolutionLabel(null), "Resolved");
  });
});

describe("reminderText", () => {
  const open = { status: "open", reminderHours: 24, notifiedAt: at(-60) };

  test("reminder still ahead", () => {
    assert.equal(reminderText({ ...open, remindAfter: at(23 * 60) }, NOW), "Announced 1h ago · reminds on a failure after 23h");
  });

  test("window passed: the next failure reminds", () => {
    assert.equal(reminderText({ ...open, remindAfter: at(-1) }, NOW), "Announced 1h ago · reminds on the next failure");
  });

  test("reminders off, and resolved alerts", () => {
    assert.equal(reminderText({ ...open, reminderHours: 0, remindAfter: null }, NOW), "Announced 1h ago · reminders off");
    assert.equal(reminderText({ ...open, status: "resolved" }, NOW), "");
  });
});

describe("retryState", () => {
  const retry = { status: "pending", attempt: 1, maxAttempts: 3, nextAttemptAt: at(4), automationEnabled: true };

  test("pending: the next retry and when", () => {
    assert.deepEqual(retryState(retry, NOW), { text: "Retry 2 of 3 · in 4 min", tone: "muted" });
    assert.equal(retryState({ ...retry, nextAttemptAt: at(-1) }, NOW).text, "Retry 2 of 3 · due now (within a minute)");
  });

  test("parked, running, and a disabled workflow", () => {
    assert.deepEqual(retryState({ ...retry, status: "parked", nextAttemptAt: null }, NOW), {
      text: "Waiting for the connection to recover",
      tone: "warn",
    });
    assert.equal(retryState({ ...retry, status: "running", attempt: 2 }, NOW).text, "Retry 2 of 3 running now");
    assert.equal(retryState({ ...retry, automationEnabled: false }, NOW).text, "Retry 2 of 3 · waits until the workflow is enabled");
  });
});

describe("failureLine", () => {
  test("provider · code — outcome", () => {
    assert.equal(
      failureLine({ providerName: "Square", code: "rate_limited", outcome: "retried, succeeded on retry 1" }),
      "Square · rate_limited — retried, succeeded on retry 1",
    );
    assert.equal(failureLine({ integrationSlug: "shop", outcome: "sent to review" }), "shop — sent to review");
  });
});

describe("paging", () => {
  test("page count", () => {
    assert.equal(pageCount(0, 25), 1);
    assert.equal(pageCount(26, 25), 2);
  });

  test("hrefs keep the other list's page", () => {
    assert.equal(pageHref("?history=2", "handled", 3, "handled"), "?history=2&handled=3#handled");
    assert.equal(pageHref("?history=2&handled=3", "handled", 1), "?history=2");
    assert.equal(pageHref("", "history", 1), "?");
  });

  test("page params", () => {
    assert.equal(pageParam("3"), 3);
    assert.equal(pageParam("0"), 1);
    assert.equal(pageParam("x"), 1);
    assert.equal(pageParam(null), 1);
  });
});
