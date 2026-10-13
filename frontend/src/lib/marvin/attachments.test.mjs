// Attachment state (attachments.ts): the bubble's chips per agent, in session storage. Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  attachmentIcon,
  attachmentIds,
  forgetAttachments,
  loadAttachments,
  MAX_ATTACHMENTS,
  roomFor,
  saveAttachments,
  turnAttachments,
  withAttachment,
  withoutAttachment,
} from "./attachments.ts";

function memoryStore() {
  const data = new Map();
  return {
    data,
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
  };
}

const file = (id, mimeType = "application/pdf") => ({ id, name: `${id}.bin`, mimeType });
const KEY = "marvin.attachments:ws1";

describe("adding and removing", () => {
  test("adds at the end, once per file, up to the cap", () => {
    let list = [];
    for (const id of ["a", "b", "a", "c", "d", "e"]) list = withAttachment(list, file(id));
    assert.deepEqual(attachmentIds(list), ["a", "b", "c", "d"]);
    assert.equal(list.length, MAX_ATTACHMENTS);
    assert.equal(roomFor(list), 0);
  });

  test("removes by id and makes room again", () => {
    const list = withoutAttachment([file("a"), file("b")], "a");
    assert.deepEqual(attachmentIds(list), ["b"]);
    assert.equal(roomFor(list), MAX_ATTACHMENTS - 1);
  });
});

describe("storage", () => {
  test("each agent keeps its own list", () => {
    const store = memoryStore();
    saveAttachments(store, KEY, "marvin", [file("a")]);
    saveAttachments(store, KEY, "workshop", [file("b"), file("c")]);
    assert.deepEqual(attachmentIds(loadAttachments(store, KEY, "marvin")), ["a"]);
    assert.deepEqual(attachmentIds(loadAttachments(store, KEY, "workshop")), ["b", "c"]);
    assert.deepEqual(loadAttachments(store, KEY, "nobody"), []);
  });

  test("an emptied list drops its agent, and the key once none are left", () => {
    const store = memoryStore();
    saveAttachments(store, KEY, "marvin", [file("a")]);
    saveAttachments(store, KEY, "marvin", []);
    assert.equal(store.data.has(KEY), false);
  });

  test("clearing the conversation forgets every agent's files", () => {
    const store = memoryStore();
    saveAttachments(store, KEY, "marvin", [file("a")]);
    forgetAttachments(store, KEY);
    assert.deepEqual(loadAttachments(store, KEY, "marvin"), []);
  });

  test("corrupt or foreign data reads as no attachments", () => {
    const store = memoryStore();
    store.setItem(KEY, "not json");
    assert.deepEqual(loadAttachments(store, KEY, "marvin"), []);
    store.setItem(KEY, JSON.stringify({ marvin: [{ id: 1 }, file("ok"), "x"] }));
    assert.deepEqual(attachmentIds(loadAttachments(store, KEY, "marvin")), ["ok"]);
  });
});

describe("turnAttachments", () => {
  test("reads the files stored on a thread's user turn", () => {
    assert.deepEqual(turnAttachments({ attachments: [file("a"), { id: "broken" }] }), [file("a")]);
    assert.deepEqual(turnAttachments(null), []);
    assert.deepEqual(turnAttachments({ sources: [] }), []);
  });
});

test("attachmentIcon tells images from documents", () => {
  assert.equal(attachmentIcon("image/png"), "🖼");
  assert.equal(attachmentIcon("application/pdf"), "📄");
});
