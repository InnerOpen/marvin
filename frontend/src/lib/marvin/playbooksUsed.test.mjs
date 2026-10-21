// The "Used:" line under an Ask reply (playbooksUsed.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { playbookNames, usedHtml } from "./playbooksUsed.ts";

const bench = { id: "1", name: "bench-note-voice" };

describe("usedHtml", () => {
  test("names the Playbooks first, then the tools", () => {
    const html = usedHtml(["load_playbook", "find_entries"], [bench]);
    assert.equal(
      html,
      '<span>Used:</span> <span class="playbook-used" title="Playbook">bench-note-voice</span> <code>find_entries</code>',
    );
  });

  test("a Playbook still in effect shows even when the turn called no tool", () => {
    assert.match(usedHtml([], [bench]), /bench-note-voice/);
  });

  test("load_playbook stays in the tool list when no Playbook is named", () => {
    assert.equal(usedHtml(["load_playbook"], []), "<span>Used:</span> <code>load_playbook</code>");
  });

  test("says nothing when there is nothing to say", () => {
    assert.equal(usedHtml([], []), "");
    assert.equal(usedHtml(undefined, undefined), "");
    assert.equal(usedHtml(null, [{ id: "1", name: "  " }]), "");
  });

  test("each tool and Playbook once, and everything is escaped", () => {
    const html = usedHtml(["a", "a", "<b>"], [{ id: "1", name: "<script>x</script>" }, { id: "2", name: "<script>x</script>" }]);
    assert.equal((html.match(/playbook-used/g) ?? []).length, 1);
    assert.ok(!html.includes("<script>") && !html.includes("<b>"));
    assert.equal((html.match(/<code>a<\/code>/g) ?? []).length, 1);
  });
});

describe("playbookNames", () => {
  test("keeps order, drops blanks and repeats", () => {
    assert.deepEqual(playbookNames([bench, { id: "2" }, { id: "3", name: "bench-note-voice" }, { id: "4", name: "z" }]), ["bench-note-voice", "z"]);
    assert.deepEqual(playbookNames(null), []);
  });
});
