// Playbooks (playbooks.ts): the row and status words, the Agent Skills checks, the long-body warning and form <-> entry.
// Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  actionsFor,
  alsoGives,
  copiedLabel,
  offNames,
  pickerGroups,
  sourceLine,
  switchTitle,
  systemGroups,
  systemPath,
  systemRow,
  upstreamHint,
  usedPlaybookHref,
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
  originLabel,
  fromIntegration,
  fromIntegrationId,
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

describe("integration Playbooks", () => {
  const from = (extra = {}) => ({ source: "buttondown", name: "Buttondown", integrationId: "i1", removed: false, ...extra });
  test("the row says which integration shipped it, or that it was removed", () => {
    assert.equal(originLabel({ fromIntegration: from() }), "From Buttondown");
    assert.equal(originLabel({ fromIntegration: from({ removed: true, integrationId: null }) }), "From a removed integration");
    assert.equal(originLabel({}), null);
    assert.equal(playbookRow({ id: "a", name: "n", description: "", status: "draft", fromIntegration: from() }).origin, "From Buttondown");
    assert.equal(playbookRow({ id: "a", name: "n", description: "", status: "draft" }).origin, null);
  });
  test("the card's link narrows the list to one integration", () => {
    const items = [
      { id: "1", name: "a", status: "draft", fromIntegration: from() },
      { id: "2", name: "b", status: "draft", fromIntegration: from({ integrationId: "i2" }) },
      { id: "3", name: "c", status: "draft" },
    ];
    assert.equal(fromIntegrationId("integration:i1"), "i1");
    assert.equal(fromIntegrationId("workflow:x"), null);
    assert.equal(fromIntegrationId(null), null);
    assert.deepEqual(fromIntegration(items, "i1").map((i) => i.id), ["1"]);
    assert.equal(fromIntegration(items, null).length, 3);
  });
});


// ── system Playbooks ──────────────────────────────────────────────────────────────────────────────────────────────

const ALT = { name: "marvin-alt-text", description: "Use when writing alt text.", label: "System · Marvin", version: "1.42.0", manualOnly: false, state: "on", enabled: true, suggestedCopyName: "alt-text" };
const RULE = { name: "social-auto-reply-rule", description: "Use for an auto-reply rule.", label: "System · Social", version: "1.42.0", manualOnly: true, state: "on", enabled: true };
const S3 = { name: "s3-workspace-bucket", description: "Use for bucket setup.", label: "System · S3 storage", version: "0.5.0", manualOnly: true, state: "off", detail: "Off for this workspace", enabled: false, allowedTools: "get_entry" };

describe("system Playbooks", () => {
  test("a row says what a person needs: label, version, badges, the state's sentence and the copy name", () => {
    const row = systemRow(ALT);
    assert.equal(row.href, "/workspace/settings/ai-playbooks/system/marvin-alt-text");
    assert.deepEqual([row.label, row.version, row.manualOnly, row.on, row.note, row.suggestedName], ["System · Marvin", "1.42.0", false, true, "", "alt-text"]);
    const off = systemRow(S3);
    assert.deepEqual([off.on, off.enabled, off.note, off.allowedTools, off.serverOff], [false, false, "Off for this workspace", "get_entry", false]);
  });

  test("the platform's switch shows as off with the workspace's own switch still its own", () => {
    const row = systemRow({ ...ALT, state: "off_server", detail: "Off for this platform", enabled: true });
    assert.deepEqual([row.serverOff, row.enabled, row.note], [true, true, "Off for this platform"]);
    assert.match(switchTitle(row), /whole platform/);
    assert.match(switchTitle({ enabled: true, serverOff: false }), /off for this workspace/);
    assert.match(switchTitle({ enabled: false, serverOff: false }), /on for this workspace/);
  });

  test("groups follow the labels in the order they first appear", () => {
    const groups = systemGroups([ALT, RULE, S3, { ...ALT, name: "marvin-other" }]);
    assert.deepEqual(groups.map((g) => [g.label, g.rows.map((r) => r.name)]), [
      ["System · Marvin", ["marvin-alt-text", "marvin-other"]],
      ["System · Social", ["social-auto-reply-rule"]],
      ["System · S3 storage", ["s3-workspace-bucket"]],
    ]);
    assert.deepEqual(systemGroups([]), []);
  });

  test("a system name is a path, escaped", () => {
    assert.equal(systemPath("a b"), "/workspace/settings/ai-playbooks/system/a%20b");
    assert.equal(sourceLine(ALT), "System · Marvin, 1.42.0");
    assert.equal(sourceLine({ label: "System · Social" }), "System · Social");
  });

  test("a copy says where it came from and hints when the original changed", () => {
    const copy = { id: "1", name: "alt-text", description: "", status: "draft", copiedFrom: { name: "marvin-alt-text", label: "System · Marvin", version: "1.40.0", currentVersion: "1.42.0", upstreamChanged: true } };
    assert.equal(copiedLabel(copy), "Copied from System · Marvin 1.40.0");
    assert.equal(upstreamHint(copy), "The system Playbook changed: 1.40.0 → 1.42.0. Your copy is unchanged.");
    const row = playbookRow(copy);
    assert.deepEqual([row.copied, row.upstreamHref], ["Copied from System · Marvin 1.40.0", "/workspace/settings/ai-playbooks/system/marvin-alt-text"]);
    const quiet = { ...copy, copiedFrom: { ...copy.copiedFrom, upstreamChanged: false } };
    assert.equal(upstreamHint(quiet), null);
    assert.equal(playbookRow(quiet).upstreamHref, null);
    assert.equal(upstreamHint({ copiedFrom: { name: "x", upstreamChanged: true, version: "1", currentVersion: "1" } }), "The system Playbook changed. Your copy is unchanged.");
    assert.equal(copiedLabel({ id: "2", name: "mine", description: "", status: "draft" }), null);
  });

  test("the agent picker lists yours, then a System group per label, and marks the ones switched off", () => {
    const own = [
      { id: "1", name: "house-voice", description: "Voice.", status: "published" },
      { id: "2", name: "wip", description: "", status: "draft" },
    ];
    const groups = pickerGroups(own, [ALT, S3, { ...RULE, state: "off_server" }]);
    assert.deepEqual(groups.map((g) => g.label), ["Yours", "System · Marvin", "System · S3 storage", "System · Social"]);
    assert.deepEqual(groups[0].entries.map((e) => e.name), ["house-voice"]);
    assert.deepEqual(groups.flatMap((g) => g.entries.filter((e) => e.off).map((e) => e.name)), ["s3-workspace-bucket", "social-auto-reply-rule"]);
    assert.deepEqual(pickerGroups([], []), []);
  });

  test("names typed into an agent's settings are flagged when the system Playbook is off", () => {
    assert.deepEqual(offNames("house-voice\ns3-workspace-bucket, marvin-alt-text", [ALT, S3]), ["s3-workspace-bucket"]);
    assert.deepEqual(offNames("", [S3]), []);
  });

  test("a run's trace links a system Playbook and leaves a workspace one alone", () => {
    assert.equal(usedPlaybookHref({ id: "system:marvin-alt-text", name: "marvin-alt-text" }), "/workspace/settings/ai-playbooks/system/marvin-alt-text");
    assert.equal(usedPlaybookHref({ id: "5c0d", name: "house-voice" }), null);
    assert.equal(usedPlaybookHref({ id: "system:x" }), null);
  });

  test("the integration card names what a provider gives every workspace", () => {
    assert.equal(alsoGives([]), null);
    assert.equal(alsoGives(undefined), null);
    assert.equal(alsoGives([{ name: "s3-workspace-bucket" }]).text, "Also gives every workspace: s3-workspace-bucket (System Playbook, read-only)");
    assert.equal(alsoGives([{ name: "a" }, { name: "b" }]).text, "Also gives every workspace: a, b (System Playbooks, read-only)");
  });
});
