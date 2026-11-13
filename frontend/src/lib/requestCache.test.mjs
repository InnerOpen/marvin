import assert from "node:assert/strict";
import { test } from "node:test";
import { createRequestCache, readOnce } from "./requestCache.ts";

/** A loader that counts its calls and answers `value` (or fails with `error`). */
function counter(value, error) {
  const loader = async () => {
    loader.calls += 1;
    if (error) throw error;
    return value;
  };
  loader.calls = 0;
  return loader;
}

test("repeated reads in one request go to the API once", async () => {
  const request = { apiCache: createRequestCache() };
  const load = counter({ id: "u1" });
  const first = await readOnce(request, "/api/self", "t", load);
  const second = await readOnce(request, "/api/self", "t", load);
  assert.equal(load.calls, 1);
  assert.deepEqual(first, { id: "u1" });
  assert.deepEqual(second, { id: "u1" });
});

test("callers arriving while the read is in flight share it", async () => {
  const request = { apiCache: createRequestCache() };
  const load = counter([1, 2, 3]);
  const answers = await Promise.all([1, 2, 3].map(() => readOnce(request, "/api/platform/entry-types", "t", load)));
  assert.equal(load.calls, 1);
  for (const answer of answers) assert.deepEqual(answer, [1, 2, 3]);
});

test("separate requests read separately", async () => {
  const load = counter({ id: "u1" });
  await readOnce({ apiCache: createRequestCache() }, "/api/self", "t", load);
  await readOnce({ apiCache: createRequestCache() }, "/api/self", "t", load);
  assert.equal(load.calls, 2);
});

test("a request without a cache (a POST, the browser) always reads", async () => {
  const load = counter({ id: "u1" });
  await readOnce({}, "/api/self", "t", load);
  await readOnce(undefined, "/api/self", "t", load);
  assert.equal(load.calls, 2);
});

test("different paths and different tokens are different reads", async () => {
  const request = { apiCache: createRequestCache() };
  const load = counter("x");
  await readOnce(request, "/api/self", "t", load);
  await readOnce(request, "/api/self/workspaces", "t", load);
  await readOnce(request, "/api/self", "other", load);
  await readOnce(request, "/api/self", undefined, load);
  assert.equal(load.calls, 4);
});

test("a failed read is not kept: every caller in flight gets the error, the next caller asks again", async () => {
  const request = { apiCache: createRequestCache() };
  const failing = counter(null, new Error("403"));
  const tries = await Promise.allSettled([readOnce(request, "/api/groups/ai-settings", "t", failing), readOnce(request, "/api/groups/ai-settings", "t", failing)]);
  assert.deepEqual(tries.map((t) => t.status), ["rejected", "rejected"]);
  assert.equal(tries[0].reason.message, "403");
  assert.equal(failing.calls, 1);
  const working = counter({ ok: true });
  assert.deepEqual(await readOnce(request, "/api/groups/ai-settings", "t", working), { ok: true });
  assert.equal(working.calls, 1);
});

test("a loader that throws before its promise starts is a failed read, not a crash", async () => {
  const request = { apiCache: createRequestCache() };
  await assert.rejects(
    readOnce(request, "/api/self", "t", () => {
      throw new Error("no API");
    }),
    /no API/,
  );
  const load = counter({ id: "u1" });
  assert.deepEqual(await readOnce(request, "/api/self", "t", load), { id: "u1" });
});

test("each caller gets its own copy: one sorting its answer doesn't reorder another's", async () => {
  const request = { apiCache: createRequestCache() };
  const load = counter([{ name: "b" }, { name: "a" }]);
  const mine = await readOnce(request, "/api/platform/entry-types", "t", load);
  mine.sort((x, y) => x.name.localeCompare(y.name));
  mine[0].name = "changed";
  const theirs = await readOnce(request, "/api/platform/entry-types", "t", load);
  assert.deepEqual(theirs, [{ name: "b" }, { name: "a" }]);
});

test("an answer of null or nothing is shared like any other", async () => {
  const request = { apiCache: createRequestCache() };
  const none = counter(null);
  assert.equal(await readOnce(request, "/api/self/workspaces/current", "t", none), null);
  assert.equal(await readOnce(request, "/api/self/workspaces/current", "t", none), null);
  assert.equal(none.calls, 1);
});
