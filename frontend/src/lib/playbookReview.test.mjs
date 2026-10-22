// The review panel's logic (playbookReview.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { githubLink, importError, integrationNote, sourceView, NO_NARROWING_NOTE, NOT_A_MARVIN_TOOL, reviewFromMetadata, reviewView, sizeLabel, warningLabel } from "./playbookReview.ts";

const review = (over = {}) => ({
  tools: [],
  narrowsTools: false,
  links: [],
  files: [],
  scripts: [],
  skipped: [],
  warnings: [],
  warningsOmitted: 0,
  extraKeys: [],
  disclaimer: "Not a guarantee.",
  ...over,
});

describe("reviewFromMetadata", () => {
  test("a Playbook that was not imported has no review", () => {
    assert.equal(reviewFromMetadata(null), null);
    assert.equal(reviewFromMetadata({}), null);
    assert.equal(reviewFromMetadata({ importReview: "x" }), null);
  });
  test("a stored review is read with defaults for what is missing", () => {
    const out = reviewFromMetadata({ importReview: { tools: [], files: [], scripts: ["a.sh"] } });
    assert.deepEqual(out?.scripts, ["a.sh"]);
    assert.deepEqual(out?.warnings, []);
    assert.match(out?.disclaimer ?? "", /not a guarantee/i);
  });
});

describe("reviewView", () => {
  test("a clean review says nothing is flagged but still asks for a read", () => {
    const v = reviewView(review());
    assert.equal(v.tone, "ok");
    assert.match(v.headline, /Nothing flagged/);
    assert.equal(v.toolsNote, "It asks for no particular tools.");
  });
  test("tools Marvin lacks are marked; a Marvin spelling shows what it matched", () => {
    const v = reviewView(
      review({
        tools: [
          { name: "find_entries", tool: "find_entries", available: true },
          { name: "marvin_get_entry", tool: "get_entry", available: true },
          { name: "Bash(git:*)", tool: null, available: false },
        ],
        narrowsTools: true,
      }),
    );
    assert.deepEqual(v.tools.map((t) => [t.name, t.missing, t.note]), [
      ["find_entries", false, "available"],
      ["marvin_get_entry", false, "Marvin's get_entry"],
      ["Bash(git:*)", true, NOT_A_MARVIN_TOOL],
    ]);
    assert.equal(v.toolsNote, "");
    assert.match(v.headline, /1 tool Marvin lacks/);
  });
  test("when no tool resolves the panel says the list narrows nothing", () => {
    const v = reviewView(review({ tools: [{ name: "Read", tool: null, available: false }], narrowsTools: false }));
    assert.equal(v.toolsNote, NO_NARROWING_NOTE);
  });
  test("links: files outside the import are broken, urls are web links", () => {
    const v = reviewView(
      review({
        links: [
          { target: "https://example.com", kind: "url", found: null, line: 2 },
          { target: "references/a.md", kind: "file", found: true, line: 3 },
          { target: "references/b.md", kind: "file", found: false, line: 4 },
        ],
      }),
    );
    assert.deepEqual(v.links.map((l) => [l.note, l.broken]), [["web link", false], ["file in this Playbook", false], ["file not in the import", true]]);
    assert.match(v.headline, /1 linked file not in the import/);
  });
  test("scripts are flagged unsupported and explained", () => {
    const v = reviewView(review({ scripts: ["scripts/run.sh"], files: [{ path: "scripts/run.sh", size: 2048, script: true, referenced: false }] }));
    assert.equal(v.tone, "attention");
    assert.match(v.scriptsNote, /does not run scripts/);
    assert.deepEqual(v.files[0], { path: "scripts/run.sh", size: "2.0 KB", script: true, note: "script: unsupported, never run" });
    assert.match(v.headline, /1 script file/);
  });
  test("warnings carry a label, a place and the line, and count the ones left out", () => {
    const v = reviewView(
      review({ warnings: [{ kind: "secret_word", file: "SKILL.md", line: 7, excerpt: "paste the API key" }], warningsOmitted: 3, disclaimer: "Not a guarantee." }),
    );
    assert.deepEqual(v.warnings, [{ label: "Mentions secrets or credentials", where: "SKILL.md, line 7", excerpt: "paste the API key" }]);
    assert.equal(v.warningsMore, "3 more warnings not shown.");
    assert.match(v.headline, /4 warnings/);
    assert.equal(v.disclaimer, "Not a guarantee.");
  });
  test("unused files are said to be unmentioned", () => {
    const v = reviewView(review({ files: [{ path: "x.md", size: 10, script: false, referenced: false }] }));
    assert.equal(v.files[0].note, "not mentioned in the instructions");
  });
});

test("labels and sizes", () => {
  assert.equal(warningLabel("sends_data"), "Sends data to another URL or host");
  assert.equal(warningLabel("other"), "Worth a look");
  assert.equal(sizeLabel(10), "10 B");
  assert.equal(sizeLabel(5 * 1048576), "5.0 MB");
});

describe("importError", () => {
  test("uses the backend's reason", () => {
    assert.equal(importError({ responseBody: JSON.stringify({ detail: "The name 'x' is already used." }) }), "The name 'x' is already used.");
    assert.equal(importError({ body: { detail: "Too big." } }), "Too big.");
  });
  test("falls back to the error's message, then a plain line", () => {
    assert.equal(importError(new Error("boom")), "boom");
    assert.equal(importError(null), "The import failed.");
  });
});

describe("sourceView", () => {
  const SHA = "0123456789abcdef0123456789abcdef01234567";
  test("a GitHub import names the repo, folder and pinned commit, and links to that commit", () => {
    const v = sourceView({ kind: "github", repo: "o/r", path: "skills/my skill", commit: SHA, url: "https://github.com/o/r/tree/main/x" });
    assert.deepEqual(v, {
      label: "o/r, skills/my skill",
      commit: "0123456",
      fullCommit: SHA,
      href: `https://github.com/o/r/tree/${SHA}/skills/my%20skill`,
    });
    assert.equal(sourceView({ kind: "github", repo: "o/r", path: "", commit: SHA })?.href, `https://github.com/o/r/tree/${SHA}`);
  });
  test("an upload, or a source that is not a pinned GitHub one, shows nothing", () => {
    assert.equal(sourceView({ kind: "zip", filename: "a.zip" }), null);
    assert.equal(sourceView(undefined), null);
    assert.equal(sourceView({ kind: "github", repo: "o/r", commit: "main" }), null);
    assert.equal(sourceView({ kind: "github", repo: "javascript:alert(1)//x", commit: SHA }), null);
  });
  test("the review view carries it", () => {
    const review = reviewFromMetadata({ importReview: { tools: [], files: [], source: { kind: "github", repo: "o/r", path: "a", commit: SHA } } });
    assert.equal(reviewView(review).source?.commit, "0123456");
  });
});

test("githubLink trims and ignores an empty field", () => {
  assert.equal(githubLink("  https://github.com/o/r \n"), "https://github.com/o/r");
  assert.equal(githubLink("   "), null);
});

describe("integrationNote", () => {
  test("a Playbook an integration shipped says which one", () => {
    assert.equal(integrationNote({ kind: "integration", provider: "buttondown", name: "Buttondown" }), "Installed by the Buttondown integration.");
    assert.equal(integrationNote({ kind: "integration", provider: "mastodon" }), "Installed by the mastodon integration.");
    assert.equal(integrationNote({ kind: "integration" }), "Installed by an integration.");
  });
  test("an import says nothing", () => {
    assert.equal(integrationNote({ kind: "zip" }), null);
    assert.equal(integrationNote(undefined), null);
  });
});
