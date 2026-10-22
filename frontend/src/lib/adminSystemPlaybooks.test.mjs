// Admin › System Playbooks (adminSystemPlaybooks.ts): grouping and wording. Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { adminGroups, badgesFor, offNote, summary } from "./adminSystemPlaybooks.ts";

const item = (over = {}) => ({
  name: "marvin-alt-text",
  description: "Use when writing alt text.",
  label: "System · Marvin",
  source: "core",
  version: "1.42.0",
  manualOnly: false,
  allowedTools: "",
  warnings: [],
  files: 1,
  serverOff: false,
  workspacesOff: 0,
  ...over,
});

describe("adminGroups", () => {
  test("groups by source label and keeps the version when the group shares one", () => {
    const groups = adminGroups([item(), item({ name: "marvin-other" }), item({ name: "s3-workspace-bucket", label: "System · S3 storage", source: "plugin", version: "0.5.0", manualOnly: true })]);
    assert.deepEqual(groups.map((g) => [g.label, g.version, g.rows.map((r) => r.name)]), [
      ["System · Marvin", "1.42.0", ["marvin-alt-text", "marvin-other"]],
      ["System · S3 storage", "0.5.0", ["s3-workspace-bucket"]],
    ]);
  });

  test("a group whose Playbooks disagree on the version shows none", () => {
    assert.equal(adminGroups([item(), item({ name: "b", version: "1.0.0" })])[0].version, "");
  });
});

describe("rows", () => {
  test("say how widely a Playbook is switched off", () => {
    assert.equal(offNote({ serverOff: true, workspacesOff: 3 }), "Off in every workspace");
    assert.equal(offNote({ serverOff: false, workspacesOff: 1 }), "Off in 1 workspace");
    assert.equal(offNote({ serverOff: false, workspacesOff: 4 }), "Off in 4 workspaces");
    assert.equal(offNote({ serverOff: false, workspacesOff: 0 }), "");
  });

  test("badges name manual-only and allowed tools", () => {
    assert.deepEqual(badgesFor({ manualOnly: true, allowedTools: "get_entry" }), ["Manual only", "Allowed tools: get_entry"]);
    assert.deepEqual(badgesFor({ manualOnly: false, allowedTools: "" }), []);
  });

  test("the summary counts what is there, switched off and couldn't load", () => {
    assert.equal(summary([item()], 0), "1 system Playbook");
    assert.equal(summary([item(), item({ serverOff: true })], 2), "2 system Playbooks, 1 switched off, 2 couldn't load");
    assert.equal(summary([], 0), "0 system Playbooks");
  });
});
