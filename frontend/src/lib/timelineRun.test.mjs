import assert from "node:assert/strict";
import { test } from "node:test";
import { jobFor, runState } from "./timelineRun.ts";

const at = (s) => new Date(1_700_000_000_000 + s * 1000).toISOString();
const job = (s, args, extra = {}) => ({ createdAt: at(s), dataJson: { status: "queued", args, ...extra } });
const since = 1_700_000_000_000 + 100 * 1000;

test("the job this click started is the newest one since it that names the entry", () => {
  const jobs = [job(10, { story: "granny" }), job(105, { story: "other" }), job(101, { story: "granny", quality: "draft" }), job(103, { story: "granny", quality: "draft" })];
  assert.equal(jobFor(jobs, "granny", since)?.createdAt, at(103));
  assert.equal(jobFor(jobs, "nobody", since), null);
});

test("a job made a few seconds before the click still counts (clocks differ), one from long before does not", () => {
  assert.equal(jobFor([job(80, { story: "g" })], "g", since)?.createdAt, at(80));
  assert.equal(jobFor([job(20, { story: "g" })], "g", since), null);
});

test("the state is told in words, and only done or failed stops the polling", () => {
  assert.deepEqual(runState(null, "Render"), { text: "Render: starting…", finished: false, url: null });
  assert.equal(runState(job(0, {}, { status: "queued" }), "Render").finished, false);
  assert.match(runState(job(0, {}, { status: "running" }), "Render").text, /making it/);
  const done = runState(job(0, {}, { status: "done", result: { url: "https://cdn/v.mp4" } }), "Render");
  assert.deepEqual([done.finished, done.url], [true, "https://cdn/v.mp4"]);
  const failed = runState(job(0, {}, { status: "failed", log: "start\nthe still of beat 2 is missing" }), "Render");
  assert.deepEqual([failed.finished, failed.text], [true, "Render failed: the still of beat 2 is missing"]);
});
