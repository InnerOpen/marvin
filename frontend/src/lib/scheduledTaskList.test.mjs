// The Scheduled tasks page's list (scheduledTaskList.ts): the Schedule filter's buckets, how a schedule reads, the adapter
// for the shared list kit (Marvin's own last, Needs attention) and the card. Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { organize } from "./organizedList.ts";
import {
  historyHtml,
  SCHEDULE_OPTIONS,
  scheduleBucket,
  scheduleText,
  scheduledTaskAdapter,
  scheduledTaskCardHtml,
} from "./scheduledTaskList.ts";

const cron = (expr, tz) => ({ scheduleType: "cron", scheduleConfig: { cronExpression: expr, timezone: tz } });
const every = (secs) => ({ scheduleType: "interval", scheduleConfig: { intervalSeconds: secs } });
const task = (extra = {}) => ({ id: "t", name: "T", enabled: true, ...every(3600), ...extra });
const NOW = new Date("2026-10-21T12:00:00Z");

describe("the Schedule filter", () => {
  test("offers hourly, daily, weekly and other", () => {
    assert.deepEqual(
      SCHEDULE_OPTIONS.map((o) => o.value),
      ["hourly", "daily", "weekly", "other"],
    );
  });

  test("intervals: exactly an hour, a day, a week; anything else is other", () => {
    assert.equal(scheduleBucket(task(every(3600))), "hourly");
    assert.equal(scheduleBucket(task(every(86400))), "daily");
    assert.equal(scheduleBucket(task(every(604800))), "weekly");
    assert.equal(scheduleBucket(task(every(900))), "other");
    assert.equal(scheduleBucket(task(every(7200))), "other");
  });

  test("cron: one minute of every hour, one time of every day, one time of one weekday", () => {
    assert.equal(scheduleBucket(task(cron("5 * * * *"))), "hourly");
    assert.equal(scheduleBucket(task(cron("0 3 * * *"))), "daily");
    assert.equal(scheduleBucket(task(cron("30 7 * * 1"))), "weekly");
    assert.equal(scheduleBucket(task(cron("0 9 * * mon"))), "weekly");
  });

  test("cron: anything fancier, and one-off runs, are other", () => {
    assert.equal(scheduleBucket(task(cron("*/15 * * * *"))), "other");
    assert.equal(scheduleBucket(task(cron("0 */2 * * *"))), "other");
    assert.equal(scheduleBucket(task(cron("0 3 1 * *"))), "other");
    assert.equal(scheduleBucket(task(cron("0 9 * * 1-5"))), "other");
    assert.equal(scheduleBucket(task({ scheduleType: "once", scheduleConfig: { runAt: "2026-11-01T00:00:00Z" } })), "other");
    assert.equal(scheduleBucket(task({ scheduleConfig: null })), "other");
  });
});

describe("how a schedule reads", () => {
  test("intervals and common cron shapes in words", () => {
    assert.equal(scheduleText(task(every(3600))), "Every hour");
    assert.equal(scheduleText(task(every(7200))), "Every 2 hours");
    assert.equal(scheduleText(task(every(86400))), "Every day");
    assert.equal(scheduleText(task(every(900))), "Every 15 minutes");
    assert.equal(scheduleText(task(cron("5 * * * *"))), "Every hour at :05");
    assert.equal(scheduleText(task(cron("0 3 * * *", "Europe/London"))), "Every day at 03:00 (Europe/London)");
    assert.equal(scheduleText(task(cron("30 7 * * 1"))), "Every Monday at 07:30");
  });

  test("the stored schedule's own keys are snake_case", () => {
    const stored = { scheduleType: "cron", scheduleConfig: { cron_expression: "0 3 * * *" } };
    assert.equal(scheduleBucket(task(stored)), "daily");
    assert.equal(scheduleText(task({ scheduleType: "interval", scheduleConfig: { interval_seconds: 7200 } })), "Every 2 hours");
  });

  test("what it can't put in words is shown as it is", () => {
    assert.equal(scheduleText(task(cron("*/15 * * * *"))), "Cron: */15 * * * *");
    assert.equal(scheduleText(task({ scheduleConfig: null })), "No schedule");
  });
});

describe("the list", () => {
  const adapter = scheduledTaskAdapter();
  const items = [
    task({ id: "a", name: "Mine" }),
    task({ id: "b", name: "Marvin Housekeeping", system: true }),
    task({ id: "c", name: "Sync", sourceIntegrationId: "int-1", sourceBlueprint: "acme/sync" }),
    task({ id: "d", name: "Left behind", sourceBlueprint: "gone/x" }),
    task({ id: "e", name: "Broken", attention: "last_run_failed", enabled: true, lastStatus: "failed" }),
  ];
  const integrations = { "int-1": { name: "Acme" } };
  const keys = (filters = {}, options = {}) => organize(items, adapter, integrations, filters, options).sections.map((s) => s.key);

  test("Yours, the integration, the removed ones, and Marvin's own last", () => {
    assert.deepEqual(keys(), ["yours", "integration:int-1", "removed", "system"]);
  });

  test("Needs attention shows the flagged ones", () => {
    const result = organize(items, adapter, integrations, { status: "attention" }, {});
    assert.deepEqual(result.sections.flatMap((s) => s.items.map((i) => i.id)), ["e"]);
  });

  test("the Schedule filter picks a bucket", () => {
    const mixed = [task({ id: "h", name: "H" }), task({ id: "d", name: "D", ...every(86400) })];
    const result = organize(mixed, adapter, {}, { schedule: "daily" }, {});
    assert.deepEqual(result.sections.flatMap((s) => s.items.map((i) => i.id)), ["d"]);
  });

  test("search finds a task by its type or schedule", () => {
    const one = [task({ id: "p", name: "Nightly", taskType: "prune_event_logs" })];
    assert.equal(organize(one, adapter, {}, {}, { query: "prune_event" }).shown, 1);
    assert.equal(organize(one, adapter, {}, {}, { query: "every hour" }).shown, 1);
    assert.equal(organize(one, adapter, {}, {}, { query: "zzz" }).shown, 0);
  });
});

describe("the card", () => {
  const html = (t, options = {}) => scheduledTaskCardHtml(t, { canManage: true, linked: false, now: NOW, ...options });

  test("an admin's card has the switch, Run now, Runs, Edit and Delete", () => {
    const out = html(task({ name: "Nightly" }));
    for (const cls of ["js-toggle", "js-run", "js-history", "js-edit", "js-delete"]) assert.match(out, new RegExp(cls));
  });

  test("an editor's card is read-only: no switch, no Run now, no Edit or Delete, but history", () => {
    const out = html(task(), { canManage: false });
    for (const cls of ["js-toggle", "js-run", "js-edit", "js-delete"]) assert.doesNotMatch(out, new RegExp(cls));
    assert.match(out, /js-history/);
  });

  test("Marvin's own: history only, whoever looks", () => {
    const out = html(task({ system: true }));
    for (const cls of ["js-toggle", "js-run", "js-edit", "js-delete"]) assert.doesNotMatch(out, new RegExp(cls));
    assert.match(out, /js-history/);
  });

  test("a switched-off task is dimmed and says so; Run now is disabled", () => {
    const out = html(task({ enabled: false }));
    assert.match(out, /org-card[^"]*\boff\b/);
    assert.match(out, /Off · /);
    assert.match(out, /js-run[^>]*disabled/);
  });

  test("the last run, and a failure marked", () => {
    assert.match(html(task()), /Not run yet/);
    const failed = html(task({ lastRunAt: "2026-10-21T10:00:00Z", lastStatus: "failed", attention: "last_run_failed" }));
    assert.match(failed, /Last run 2 h ago · failed/);
    assert.match(failed, /Needs a look/);
    assert.match(html(task({ lastRunAt: "2026-10-21T11:00:00Z", lastStatus: "success" })), /Last run 1 h ago · succeeded/);
  });

  test("a task's name is escaped", () => {
    assert.doesNotMatch(html(task({ name: "<img src=x>" })), /<img/);
  });

  test("a linked card is marked", () => {
    assert.match(html(task(), { linked: true }), /linked/);
  });
});

describe("the history", () => {
  test("each run: when, outcome, how long, what it did or why it failed", () => {
    const out = historyHtml(
      [
        { id: "1", status: "failed", executedAt: "2026-10-21T10:00:00Z", durationMs: 1500, errorMessage: "boom <b>" },
        { id: "2", status: "success", executedAt: "2026-10-21T09:00:00Z", output: "3 files deleted" },
      ],
      NOW,
    );
    assert.match(out, /failed/);
    assert.match(out, /1\.5 s/);
    assert.match(out, /boom &lt;b&gt;/);
    assert.match(out, /3 files deleted/);
  });

  test("no runs", () => {
    assert.match(historyHtml([], NOW), /No runs yet/);
  });
});
