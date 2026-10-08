// Uploads waiting for a connection (uploadQueue.ts), with an in-memory store. Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { discard, enqueue, isRetryable, MAX_QUEUED, queueNote, replay } from "./uploadQueue.ts";

function memoryStore() {
  let index = [];
  const files = new Map();
  return {
    files,
    readIndex: async () => [...index],
    writeIndex: async (list) => {
      index = [...list];
    },
    putFile: async (id, file) => void files.set(id, file),
    getFile: async (id) => files.get(id) ?? null,
    deleteFile: async (id) => void files.delete(id),
  };
}

const WS = "ws-1";
const fields = { slug: "heron-x1", name: "heron" };
let n = 0;
const add = (store, workspace = WS) =>
  enqueue(store, { workspace, fileName: "heron.jpg", type: "image/jpeg", size: 3, fields }, "blob", {
    id: `u${++n}`,
    now: n,
  });

describe("isRetryable", () => {
  test("offline, a dropped connection or a passing server error waits", () => {
    assert.equal(isRetryable(new Error("anything"), false), true);
    assert.equal(isRetryable(new TypeError("Failed to fetch"), true), true);
    assert.equal(isRetryable(new TypeError("Load failed"), true), true); // Safari
    assert.equal(isRetryable({ statusCode: 503 }, true), true);
  });

  test("an answer that won't change is final", () => {
    for (const status of [400, 401, 403, 409, 413, 415, 422])
      assert.equal(isRetryable({ statusCode: status }, true), false);
    assert.equal(isRetryable(new Error("Invalid JSON in metadata field."), true), false);
  });
});

describe("the queue", () => {
  test("keeps the file and its fields, up to the limit", async () => {
    const store = memoryStore();
    const item = await add(store);
    assert.equal(item.workspace, WS);
    assert.equal(store.files.get(item.id), "blob");
    for (let i = 1; i < MAX_QUEUED; i++) await add(store);
    assert.equal(await add(store), null);
  });

  test("replay sends what waits for this workspace and keeps the rest", async () => {
    const store = memoryStore();
    const mine = await add(store);
    const theirs = await add(store, "ws-2");
    const sent = [];

    const result = await replay(store, { workspace: WS, online: true, upload: async (item) => sent.push(item.id) });

    assert.deepEqual(sent, [mine.id]);
    assert.deepEqual(
      result.waiting.map((u) => u.id),
      [theirs.id],
    );
    assert.deepEqual(
      (await store.readIndex()).map((u) => u.id),
      [theirs.id],
    );
    assert.equal(store.files.has(mine.id), false);
  });

  test("a passing failure waits again; a refusal is dropped and reported", async () => {
    const store = memoryStore();
    const flaky = await add(store);
    const refused = await add(store);
    const upload = async (item) => {
      throw item.id === flaky.id
        ? new TypeError("Failed to fetch")
        : Object.assign(new Error("Too large"), { statusCode: 413 });
    };

    const result = await replay(store, { workspace: WS, online: true, upload });

    assert.deepEqual(
      result.waiting.map((u) => u.id),
      [flaky.id],
    );
    assert.deepEqual(
      result.failed.map((f) => [f.upload.id, f.error]),
      [[refused.id, "Too large"]],
    );
    assert.deepEqual(
      (await store.readIndex()).map((u) => u.id),
      [flaky.id],
    );
  });

  test("offline, nothing is tried", async () => {
    const store = memoryStore();
    await add(store);
    const result = await replay(store, {
      workspace: WS,
      online: false,
      upload: async () => assert.fail("tried offline"),
    });
    assert.equal(result.waiting.length, 1);
  });

  test("discard drops one or all", async () => {
    const store = memoryStore();
    const a = await add(store);
    await add(store);
    assert.equal(await discard(store, a.id), 1);
    assert.equal(await discard(store), 1);
    assert.deepEqual(await store.readIndex(), []);
  });
});

test("queueNote says what waits and where", () => {
  const item = (workspace) => ({ workspace });
  assert.equal(queueNote([], WS), null);
  assert.equal(queueNote([item(WS), item(WS)], WS), "2 uploads waiting for a connection");
  assert.equal(
    queueNote([item(WS), item("ws-2")], WS),
    "1 upload waiting for a connection; 1 upload waiting for another workspace — switch to it to send",
  );
});
