// The packages helpers (packageFile.ts): reading a file, naming, describing a preview. Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { describeResult, fileNameFor, parseManifestText, slugFor } from "./packageFile.ts";

describe("parseManifestText", () => {
  const good = { slug: "story-kit", name: "Story kit", blueprints: [{ kind: "workflow" }] };

  test("a package file is read as it is", () => {
    assert.deepEqual(parseManifestText(JSON.stringify(good)), good);
  });

  test("what is not a package says so, in words", () => {
    assert.throws(() => parseManifestText("{nope"), /not valid JSON/);
    assert.throws(() => parseManifestText("[1]"), /JSON object/);
    assert.throws(() => parseManifestText('{"slug":"a","name":"A"}'), /list of blueprints/);
    assert.throws(() => parseManifestText('{"blueprints":[]}'), /slug, a name/);
  });
});

describe("naming", () => {
  test("a slug from a name, and the download's file name", () => {
    assert.equal(slugFor("  Story Kit! 2 "), "story-kit-2");
    assert.equal(slugFor("!!!"), "");
    assert.equal(slugFor("x".repeat(100)).length, 64);
    assert.equal(fileNameFor("story-kit"), "story-kit.marvin-package.json");
  });
});

describe("describeResult", () => {
  test("a preview says what will happen, an install what did", () => {
    assert.equal(describeResult({ created: 3, existing: 1, blocked: 1 }, true), "3 will be created, 1 already here, 1 blocked");
    assert.equal(describeResult({ created: 3, existing: 0, blocked: 0 }, false), "3 created");
    assert.equal(describeResult({ created: 0, existing: 0, blocked: 0 }, true), "nothing to do");
  });
});
