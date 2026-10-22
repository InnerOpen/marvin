// An integration's Playbook on its card (playbookBlueprint.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { playbookCardNote, updateConfirmText } from "./playbookBlueprint.ts";

const row = (extra) => ({ kind: "playbook", applied: true, installedId: "p 1", installedStatus: "draft", ...extra });

describe("playbookCardNote", () => {
  test("a new Playbook is a draft to review, linking to its editor", () => {
    assert.deepEqual(playbookCardNote(row()), { text: "Draft: review and publish", href: "/workspace/settings/ai-playbooks/p%201" });
  });
  test("published and archived read as what they are", () => {
    assert.equal(playbookCardNote(row({ installedStatus: "published" }))?.text, "Published");
    assert.equal(playbookCardNote(row({ installedStatus: "archived" }))?.text, "Archived");
  });
  test("nothing for a row that is not an added Playbook", () => {
    assert.equal(playbookCardNote(row({ applied: false })), null);
    assert.equal(playbookCardNote(row({ kind: "workflow" })), null);
  });
  test("an unknown id has no link", () => {
    assert.equal(playbookCardNote(row({ installedId: null }))?.href, null);
  });
});

describe("updateConfirmText", () => {
  test("a Playbook says its history is kept and a published one changes for agents at once", () => {
    const text = updateConfirmText("playbook", "buttondown-newsletter-issue");
    assert.match(text, /stays in its history/);
    assert.match(text, /agents use the new version at once/);
  });
  test("a workflow keeps whether it is on", () => {
    assert.match(updateConfirmText("workflow", "Flow"), /switched on stays/);
  });
});
