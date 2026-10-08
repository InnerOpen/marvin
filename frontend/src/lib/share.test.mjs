// Share to Marvin (share.ts): what the Share page makes of a share — names and slugs for the uploads, the
// entry or link resource it drafts, and what it trusts from the worker's record. Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  assetName,
  assetSlug,
  bodyFieldOf,
  entryBody,
  entryDraft,
  entryTitle,
  fileKind,
  filesSummary,
  isShareId,
  readShare,
  resourceDraft,
  shareKeys,
} from "./share.ts";
import { shareKeys as workerKeys, SHARE_CACHE as WORKER_CACHE } from "../pwa/sw-logic.js";
import { SHARE_CACHE } from "./share.ts";

const ID = "6f1c2a8e-3b4d-4e5f-8a9b-0c1d2e3f4a5b";
const share = (over = {}) => ({ title: "", text: "", url: null, files: [], dropped: 0, createdAt: 1, ...over });

test("the page reads the cache the worker writes, at the same keys", () => {
  assert.equal(SHARE_CACHE, WORKER_CACHE);
  const ours = shareKeys(ID, "https://m.example");
  const theirs = workerKeys(ID, "https://m.example");
  assert.equal(ours.meta, theirs.meta);
  assert.equal(ours.file(2), theirs.file(2));
  assert.ok(isShareId(ID) && !isShareId("../x") && !isShareId(""));
});

describe("readShare", () => {
  test("keeps only http(s) links and bounded strings", () => {
    for (const url of ["javascript:alert(1)", "data:text/html,x", "ftp://x.example/a", "not a url"]) {
      assert.equal(readShare({ url }).url, null, url);
    }
    assert.equal(readShare({ url: "https://example.com/a?b=1" }).url, "https://example.com/a?b=1");
    const r = readShare({
      title: "T".repeat(999),
      files: [{ name: "a.png", type: "image/png", size: "12" }, null, "x"],
    });
    assert.equal(r.title.length, 300);
    assert.deepEqual(r.files, [{ name: "a.png", type: "image/png", size: 12 }]);
    assert.equal(readShare(null), null);
  });
});

describe("uploads", () => {
  test("names and slugs from the file name", () => {
    assert.equal(assetName("IMG_2041.jpg"), "IMG_2041");
    assert.equal(assetName("folder/Holiday photo.png"), "Holiday photo");
    assert.equal(assetName(".jpg"), ".jpg");
    assert.equal(assetName(""), "Shared file");
    assert.equal(assetSlug("Holiday Photo (1).JPG", "ab12cd"), "holiday-photo-1-ab12cd");
    assert.equal(assetSlug("ñandú.png", "x1"), "nandu-x1");
    assert.equal(assetSlug("??.png", "x1"), "shared-x1");
  });

  test("kinds and the summary line", () => {
    assert.deepEqual(["image/png", "video/mp4", "application/pdf", "text/plain"].map(fileKind), [
      "image",
      "video",
      "pdf",
      "file",
    ]);
    assert.equal(filesSummary([{ type: "image/png" }, { type: "image/jpeg" }]), "2 photos");
    assert.equal(filesSummary([{ type: "video/mp4" }]), "1 video");
    assert.equal(filesSummary([{ type: "image/png" }, { type: "application/pdf" }]), "2 files");
  });
});

describe("the entry", () => {
  test("the body field: a body/content/notes field, else the first long text, else none", () => {
    const f = (...fields) => ({ fields });
    assert.equal(bodyFieldOf(f({ key: "summary", type: "text" }, { key: "Body", type: "markdown" })), "Body");
    assert.equal(bodyFieldOf(f({ key: "notes", type: "textarea" })), "notes");
    assert.equal(bodyFieldOf(f({ key: "story", type: "markdown" }, { key: "price", type: "number" })), "story");
    assert.equal(bodyFieldOf(f({ key: "content", type: "number" }, { key: "price", type: "number" })), null);
    assert.equal(bodyFieldOf(null), null);
    assert.equal(bodyFieldOf({ fields: "nope" }), null);
  });

  test("title: shared title, the text's first line, the link's site, a stand-in", () => {
    assert.equal(entryTitle(share({ title: "Spring sale", text: "x" })), "Spring sale");
    assert.equal(entryTitle(share({ text: "\nFirst line\nsecond" })), "First line");
    assert.equal(
      entryTitle(share({ text: "https://www.example.com/a", url: "https://www.example.com/a" })),
      "example.com",
    );
    assert.equal(entryTitle(share()), "Shared from another app");
    assert.equal(entryTitle(share({ title: "x".repeat(200) })).length, 120);
  });

  test("body: the text with the link under it, once", () => {
    assert.equal(entryBody(share({ text: "Look", url: "https://e.com/a" })), "Look\n\nhttps://e.com/a");
    assert.equal(entryBody(share({ text: "Look https://e.com/a", url: "https://e.com/a" })), "Look https://e.com/a");
    assert.equal(entryBody(share({ url: "https://e.com/" })), "https://e.com/");
  });

  test("the draft: a draft of the type, the body in its field (else the description), the uploads attached", () => {
    const s = share({ title: "Trip", text: "Notes", url: "https://e.com/" });
    assert.deepEqual(entryDraft(s, "t1", "body", ["a1", "a2"]), {
      entryTypeId: "t1",
      title: "Trip",
      status: "draft",
      dataJson: { body: "Notes\n\nhttps://e.com/" },
      assetIds: ["a1", "a2"],
    });
    assert.deepEqual(entryDraft(share({ title: "Only a title" }), "t1", "body", []), {
      entryTypeId: "t1",
      title: "Only a title",
      status: "draft",
    });
    assert.equal(entryDraft(s, "t1", null, []).description, "Notes\n\nhttps://e.com/");
  });
});

test("the link resource: only with a link", () => {
  assert.equal(resourceDraft(share({ text: "no link" }), "x"), null);
  assert.deepEqual(resourceDraft(share({ title: "Docs", url: "https://docs.example/", text: "read this" }), "ab12"), {
    name: "Docs",
    slug: "docs-ab12",
    resourceType: "link",
    url: "https://docs.example/",
    description: "read this",
  });
});
