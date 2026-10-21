// Playbooks (playbooks.ts): the row and status words, the Agent Skills checks, the long-body warning and form <-> entry.
// Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  actionsFor,
  bodyLines,
  EMPTY_FORM,
  editorPath,
  entryPayload,
  exportFilename,
  formFromEntry,
  isValid,
  lengthWarning,
  listSummary,
  NO_USES_NOTE,
  playbookRow,
  sortedItems,
  statusLabel,
  statusTone,
  useRow,
  usedLabel,
  validate,
} from "./playbooks.ts";

const ok = { name: "release-notes", description: "How we write release notes.", compatibility: "" };

describe("status words", () => {
  test("published is live; everything else reads as a draft", () => {
    assert.equal(statusLabel("published"), "Published");
    for (const s of ["draft", "inbox", "needs_review", "approved", undefined]) assert.equal(statusLabel(s), "Draft");
    assert.equal(statusLabel("archived"), "Archived");
    assert.equal(statusTone("published"), "published");
    assert.equal(statusTone("draft"), "draft");
  });
});

describe("the list", () => {
  test("a row links to the editor and trims a long description", () => {
    const row = playbookRow({ id: "a b", name: "n", description: "x ".repeat(200), status: "draft", manualOnly: true });
    assert.equal(row.href, "/workspace/settings/ai-playbooks/a%20b");
    assert.ok(row.summary.length <= 141 && row.summary.endsWith("…"));
    assert.equal(row.label, "Draft");
    assert.equal(row.manualOnly, true);
  });

  test("published first, then drafts, then archived", () => {
    const items = [
      { id: "1", name: "a", description: "", status: "draft" },
      { id: "2", name: "b", description: "", status: "archived" },
      { id: "3", name: "c", description: "", status: "published" },
      { id: "4", name: "0", description: "", status: "draft" },
    ];
    assert.deepEqual(sortedItems(items).map((i) => i.id), ["3", "4", "1", "2"]);
  });

  test("the summary counts what is live", () => {
    assert.equal(listSummary([]), "No Playbooks yet");
    assert.equal(listSummary([{ id: "1", name: "a", description: "", status: "published" }]), "1 Playbook, 1 published");
    assert.equal(
      listSummary([
        { id: "1", name: "a", description: "", status: "published" },
        { id: "2", name: "b", description: "", status: "draft" },
      ]),
      "2 Playbooks, 1 published",
    );
  });

  test("editorPath", () => assert.equal(editorPath("x"), "/workspace/settings/ai-playbooks/x"));
});

describe("validate (the Agent Skills spec)", () => {
  test("a good name and description pass", () => {
    assert.deepEqual(validate(ok), {});
    assert.ok(isValid(validate(ok)));
  });

  test("a name is lowercase letters, digits and single hyphens", () => {
    for (const name of ["Release", "release_notes", "release notes", "-a", "a-", "a--b", "é", "a/b"]) {
      assert.ok(validate({ ...ok, name }).name, name);
    }
    for (const name of ["a", "0", "release-notes-2", "a1-b2"]) assert.equal(validate({ ...ok, name }).name, undefined, name);
  });

  test("a name is required and at most 64 characters", () => {
    assert.ok(validate({ ...ok, name: "  " }).name);
    assert.equal(validate({ ...ok, name: "a".repeat(64) }).name, undefined);
    assert.match(validate({ ...ok, name: "a".repeat(65) }).name, /64/);
  });

  test("a description is non-empty and at most 1024 characters", () => {
    assert.ok(validate({ ...ok, description: "   " }).description);
    assert.equal(validate({ ...ok, description: "d".repeat(1024) }).description, undefined);
    assert.match(validate({ ...ok, description: "d".repeat(1025) }).description, /1024/);
  });

  test("compatibility is at most 500 characters", () => {
    assert.equal(validate({ ...ok, compatibility: "c".repeat(500) }).compatibility, undefined);
    assert.ok(validate({ ...ok, compatibility: "c".repeat(501) }).compatibility);
  });
});

describe("the body length warning", () => {
  const lines = (n) => Array.from({ length: n }, (_, i) => `line ${i}`).join("\n");

  test("counts lines, ignoring trailing blank lines", () => {
    assert.equal(bodyLines(""), 0);
    assert.equal(bodyLines(null), 0);
    assert.equal(bodyLines("a"), 1);
    assert.equal(bodyLines("a\r\nb\n\n\n"), 2);
  });

  test("warns past 500 lines and never at or under it", () => {
    assert.equal(lengthWarning(lines(500)), null);
    assert.match(lengthWarning(lines(501)), /501 lines/);
    assert.match(lengthWarning(lines(501)), /still save/);
  });

  test("a long body does not make the form invalid", () => {
    assert.ok(isValid(validate(ok)));
  });
});

describe("form <-> entry", () => {
  const entry = {
    status: "draft",
    slug: "release-notes",
    dataJson: { name: "x", description: "d", license: "MIT", compatibility: "c", allowed_tools: "a b", manual_only: true, body: "# hi" },
  };

  test("the form reads the slug as the name", () => {
    assert.deepEqual(formFromEntry(entry), {
      name: "release-notes",
      description: "d",
      license: "MIT",
      compatibility: "c",
      allowedTools: "a b",
      manualOnly: true,
      body: "# hi",
    });
    assert.deepEqual(formFromEntry(null), EMPTY_FORM);
  });

  test("the payload names the entry after the Playbook and leaves empty optionals out", () => {
    const p = entryPayload({ ...EMPTY_FORM, name: " release-notes ", description: " d ", allowedTools: "  a   b ", body: "x" }, "type-1", "draft");
    assert.deepEqual(p, {
      entryTypeId: "type-1",
      title: "release-notes",
      slug: "release-notes",
      status: "draft",
      dataJson: { name: "release-notes", description: "d", manual_only: false, allowed_tools: "a b", body: "x" },
    });
  });

  test("an update sends no type and, without a status, none either", () => {
    const p = entryPayload({ ...EMPTY_FORM, name: "n", description: "d" }, null);
    assert.equal("entryTypeId" in p, false);
    assert.equal("status" in p, false);
  });

  test("round trip", () => {
    const form = formFromEntry(entry);
    assert.deepEqual(formFromEntry({ slug: form.name, dataJson: entryPayload(form, null).dataJson }), form);
  });
});

describe("actions", () => {
  test("a new Playbook saves as a draft or publishes at once", () => {
    assert.deepEqual(actionsFor(undefined, true).map((a) => a.key), ["save", "publish"]);
  });
  test("a draft publishes; a published one unpublishes", () => {
    assert.deepEqual(actionsFor("draft", false).map((a) => a.key), ["save", "publish"]);
    assert.deepEqual(actionsFor("published", false).map((a) => a.key), ["save", "unpublish"]);
    assert.deepEqual(actionsFor("draft", false, false).map((a) => a.key), ["save"]); // an editor drafts, never publishes
    assert.deepEqual(actionsFor(undefined, true, false).map((a) => a.key), ["save"]);
    assert.deepEqual(actionsFor("published", false, false), []); // a live Playbook is an Admin's to change
  });
});

describe("used recently", () => {
  const now = new Date("2026-10-21T12:00:00Z");

  test("the list says when a Playbook was last used, or that it was not", () => {
    assert.equal(usedLabel("2026-10-21T09:00:00Z", now), "Used 3 h ago");
    assert.equal(usedLabel("2026-10-18T12:00:00Z", now), "Used 3 d ago");
    assert.equal(usedLabel(null, now), "Not used lately");
    assert.equal(usedLabel(undefined, now), "Not used lately");
    const row = playbookRow({ id: "a", name: "n", description: "", status: "published", lastUsedAt: "2026-10-21T11:59:30Z" }, now);
    assert.equal(row.used, "Used just now");
  });

  test("a use shows the agent, when, and a link to the conversation when there is one", () => {
    const row = useRow({ executionId: "e1", agentSlug: "marvin", agentName: "Marvin", usedAt: "2026-10-21T11:00:00Z", threadId: "t 1" }, now);
    assert.deepEqual(row, { key: "e1", agent: "Marvin", when: "1 h ago", href: "/workspace/settings/ai-ask?thread=t%201" });
  });

  test("a run with no conversation has no link, and a missing agent name falls back to the slug", () => {
    const row = useRow({ executionId: "e2", agentSlug: "scribe", usedAt: "2026-10-20T12:00:00Z" }, now);
    assert.equal(row.href, null);
    assert.equal(row.agent, "scribe");
    assert.equal(useRow({ executionId: "e3" }, now).agent, "An agent");
    assert.equal(useRow({ executionId: "e3" }, now).when, "earlier");
  });

  test("the empty note explains itself", () => {
    assert.match(NO_USES_NOTE, /Not used lately/);
  });
});

describe("exportFilename", () => {
  test("reads the name the server gave the zip", () => {
    assert.equal(exportFilename('attachment; filename="tidy-notes.zip"', "x"), "tidy-notes.zip");
  });
  test("falls back to the Playbook's name when there is no header", () => {
    assert.equal(exportFilename(null, "tidy-notes"), "tidy-notes.zip");
    assert.equal(exportFilename("attachment", "tidy-notes"), "tidy-notes.zip");
  });
});

test("a proposed change keeps the Playbook it replaces through the form and back", () => {
  const form = formFromEntry({ slug: "n-change", status: "inbox", dataJson: { description: "d", body: "b", replaces: "n" } });
  assert.equal(form.replaces, "n");
  assert.equal(entryPayload(form, null).dataJson.replaces, "n");
  assert.equal("replaces" in formFromEntry({ slug: "n", dataJson: {} }), false);
  assert.equal("replaces" in entryPayload({ ...EMPTY_FORM, name: "n", description: "d" }, null).dataJson, false);
});
