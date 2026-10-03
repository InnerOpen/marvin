// The update banner's "What's new" list (whatsNew.ts). Run with `npm test` — plain `node --test`,
// which strips whatsNew.ts's types itself. Plain JS so `astro check` leaves it alone.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { changesUrl, formatItem, prepareReleases, safeCommitUrl, visibleSections } from "./whatsNew.ts";

const item = (summary, over = {}) => ({ scope: null, summary, commit: null, commitUrl: null, ...over });
const section = (title, ...summaries) => ({ title, items: summaries.map((s) => item(s)) });
const release = (version, ...sections) => ({ version, date: "2026-10-03", sections });
const titles = (sections) => sections.map((s) => s.title);

describe("visibleSections", () => {
  test("drops chores and other developer-facing sections", () => {
    const r = release(
      "1.0.0-rc.2",
      section("Chores", "bump"),
      section("Features", "a"),
      section("Continuous Integration", "ci"),
    );
    assert.deepEqual(titles(visibleSections(r)), ["Features"]);
  });

  test("orders features, then fixes, then performance, then the rest", () => {
    const r = release(
      "1.0.0-rc.2",
      section("Bug Fixes", "f"),
      section("Something New", "x"),
      section("Performance Improvements", "p"),
      section("Features", "a"),
    );
    assert.deepEqual(titles(visibleSections(r)), [
      "Features",
      "Bug Fixes",
      "Performance Improvements",
      "Something New",
    ]);
  });

  test("hides documentation when the release changed anything else", () => {
    const r = release("1.0.0-rc.2", section("Documentation", "manual"), section("Features", "a"));
    assert.deepEqual(titles(visibleSections(r)), ["Features"]);
  });

  test("keeps documentation for a docs-only release", () => {
    const r = release("1.0.0-rc.2", section("Documentation", "manual"), section("Chores", "bump"));
    assert.deepEqual(titles(visibleSections(r)), ["Documentation"]);
  });

  test("skips empty sections", () => {
    assert.deepEqual(visibleSections(release("1.0.0-rc.2", section("Features"))), []);
  });
});

describe("prepareReleases", () => {
  test("drops a release with nothing user-facing and keeps the API's order", () => {
    const out = prepareReleases([
      release("1.0.0-rc.3", section("Bug Fixes", "f")),
      release("1.0.0-rc.2", section("Chores", "bump")),
      release("1.0.0-rc.1", section("Features", "a")),
    ]);
    assert.deepEqual(
      out.map((r) => r.version),
      ["1.0.0-rc.3", "1.0.0-rc.1"],
    );
  });

  test("an empty response is an empty list", () => {
    assert.deepEqual(prepareReleases([]), []);
  });
});

describe("formatItem", () => {
  test("shortens the commit and keeps the scope", () => {
    const sha = "dffdd8682c5877d2a0207edef66ad28aa0ba6923";
    const url = `https://github.com/InnerOpen/marvin/commit/${sha}`;
    assert.deepEqual(formatItem(item("Group the nav", { scope: "admin", commit: sha, commitUrl: url })), {
      scope: "admin",
      summary: "Group the nav",
      shortCommit: "dffdd86",
      commitUrl: url,
    });
  });

  test("an item without scope or commit has nulls", () => {
    assert.deepEqual(formatItem({ summary: "Initial release" }), {
      scope: null,
      summary: "Initial release",
      shortCommit: null,
      commitUrl: null,
    });
  });
});

describe("safeCommitUrl", () => {
  test("only https links survive", () => {
    assert.equal(safeCommitUrl("https://github.com/x/commit/abc"), "https://github.com/x/commit/abc");
    assert.equal(safeCommitUrl("javascript:alert(1)"), null);
    assert.equal(safeCommitUrl(null), null);
  });
});

describe("changesUrl", () => {
  test("asks for changes after the rendered backend version and frontend commit", () => {
    assert.equal(
      changesUrl({ backend: "1.0.0-rc.155", frontend: "6bc32ecc0702" }),
      "/api/app/changes?since=1.0.0-rc.155&since_commit=6bc32ecc0702",
    );
  });

  test("leaves out versions the page couldn't tell", () => {
    assert.equal(
      changesUrl({ backend: "unknown", frontend: "dev" }, "https://api.example"),
      "https://api.example/api/app/changes",
    );
  });

  test("works without a rendered version", () => {
    assert.equal(changesUrl(undefined), "/api/app/changes");
  });
});
