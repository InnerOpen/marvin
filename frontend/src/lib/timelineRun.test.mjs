import assert from "node:assert/strict";
import { test } from "node:test";
import { followed, startedRun } from "./timelineRun.ts";

const run = (state, extra = {}) => ({ executionId: "run-1", automationSlug: "render-preview", state, stepsTotal: 3, stepsOk: 0, stepsFailed: 0, waitingOn: [], ...extra });
const job = (status, finished = false) => ({ entryId: "e-1", slug: "job-1", kind: "render", status, finished });

test("the run button follows the run its click started: the id the answer gave", () => {
  assert.equal(startedRun({ status: "started", ok: true, execution_id: "run-1" }), "run-1");
  assert.equal(startedRun({ status: "started", ok: true, execution_id: null }), null);
  assert.equal(startedRun(undefined), null);
});

test("while the run or its job goes on, the words say where it is and the polling continues", () => {
  assert.deepEqual(followed(run("starting"), "Render"), { text: "Render: starting…", finished: false, url: null, ask: false });
  assert.equal(followed(run("running", { stepsOk: 1 }), "Render").text, "Render: running: 1 of 3 steps done…");
  const working = followed(run("working", { job: job("running") }), "Render");
  assert.deepEqual([working.text, working.finished], ["Render: working: the render job is running…", false]);
});

test("a run waiting for an approval says so and points at where to answer it", () => {
  const waiting = followed(run("waiting", { waitingOn: [{ approvalId: "ap-1", message: "Render it?", approvers: "editor" }] }), "Render");
  assert.deepEqual([waiting.finished, waiting.ask], [false, true]);
  assert.match(waiting.text, /^Render: waiting on you/);
});

test("done stops the polling and carries the video the job made", () => {
  const done = followed(run("done", { job: job("done", true) }), "Render", { dataJson: { status: "done", result: { url: "https://cdn/v.mp4" } } });
  assert.deepEqual(done, { text: "Render: done.", finished: true, url: "https://cdn/v.mp4", ask: false });
  assert.deepEqual(followed(run("done"), "Render"), { text: "Render: done.", finished: true, url: null, ask: false });
});

test("failed stops the polling and says why: the job's last log line, else the run's error", () => {
  const byJob = followed(run("failed", { error: "The render job it started failed.", job: job("failed", true) }), "Render", { dataJson: { status: "failed", log: "start\nthe still of beat 2 is missing" } });
  assert.deepEqual([byJob.finished, byJob.text], [true, "Render failed: the still of beat 2 is missing"]);
  assert.equal(followed(run("failed", { error: "no such entry" }), "Render").text, "Render failed: no such entry");
});

test("a run that is not on record ends the following", () => {
  assert.deepEqual(followed(null, "Render"), { text: "Render: started, but its run is not on record. Look under Workers.", finished: true, url: null, ask: false });
});
