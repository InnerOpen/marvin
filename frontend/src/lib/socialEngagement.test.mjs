// The Social engagement card on the Integrations page (socialEngagement.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { missingSlugs, socialSet, socialTask, taskState } from "./socialEngagement.ts";

const bp = (slug, kind, extra = {}) => ({ slug, name: slug, kind, source: "core", category: "Social", applied: false, available: true, ...extra });
const catalog = [
  { ...bp("articles", "collection"), category: "Editorial" },
  bp("social-engagement", "scheduled_task"),
  bp("social-replies", "collection"),
  bp("social-auto-reply", "entry_type", { applied: true }),
  bp("social-reply-log", "entry_type"),
  bp("social-auto-reply-rules", "collection"),
  { ...bp("ig-auto-reply", "entry_type"), source: "instagram" },
];

describe("socialSet", () => {
  test("only core's Social blueprints, types first, then collections, then the task", () => {
    assert.deepEqual(socialSet(catalog).map((b) => b.slug), [
      "social-auto-reply",
      "social-reply-log",
      "social-replies",
      "social-auto-reply-rules",
      "social-engagement",
    ]);
  });
});

describe("missingSlugs", () => {
  test("lists what is not installed yet, none once everything is", () => {
    assert.deepEqual(missingSlugs(socialSet(catalog)), ["social-reply-log", "social-replies", "social-auto-reply-rules", "social-engagement"]);
    assert.deepEqual(missingSlugs(socialSet(catalog).map((b) => ({ ...b, applied: true }))), []);
  });
});

describe("socialTask / taskState", () => {
  const tasks = [
    { id: "t0", taskType: "cleanup" },
    { id: "t1", taskType: "social_engagement", enabled: false, taskConfig: { rehearsal: true, announce: true } },
  ];

  test("finds the task by its type, in either casing", () => {
    assert.equal(socialTask(tasks).id, "t1");
    assert.equal(socialTask([{ id: "t2", task_type: "social_engagement" }]).id, "t2");
    assert.equal(socialTask([{ id: "t0", taskType: "cleanup" }]), undefined);
  });

  test("a new task is disabled and in rehearsal, and links to its page", () => {
    const state = taskState(tasks[1]);
    assert.deepEqual([state.enabled, state.rehearsal, state.announce], [false, true, true]);
    assert.equal(state.label, "Disabled, rehearsal on (nothing is sent)");
    assert.equal(state.href, "/workspace/scheduled-tasks/t1");
  });

  test("rehearsal is off only when the config says false; announce is on unless it says false", () => {
    const live = taskState({ id: "t", enabled: true, task_config: { rehearsal: false, announce: false } });
    assert.deepEqual([live.enabled, live.rehearsal, live.announce], [true, false, false]);
    assert.equal(live.label, "Enabled, rehearsal off (replies are sent)");
    assert.equal(taskState({ id: "t", task_config: { rehearsal: "false" } }).rehearsal, false);
    assert.equal(taskState({ id: "t" }).rehearsal, true);
    assert.equal(taskState({ id: "t", task_config: {} }).announce, true);
  });
});
