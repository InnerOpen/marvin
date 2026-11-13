import assert from "node:assert/strict";
import { test } from "node:test";
import { runKey, runLine } from "./runState.ts";

const run = (state, extra = {}) => ({ executionId: "run-1", automationSlug: "make-stills", state, stepsTotal: 7, stepsOk: 0, stepsFailed: 0, waitingOn: [], ...extra });
const asked = (message = "Keep this still?") => ({ approvalId: "ap-1", message, approvers: message === null ? "admin" : "editor" });

test("a run that has not begun, or is going, is busy and says how far it has got", () => {
  assert.deepEqual(runLine(run("starting")), { text: "Starting…", tone: "busy", over: false });
  assert.deepEqual(runLine(run("running", { stepsOk: 3 })), { text: "Running: 3 of 7 steps done…", tone: "busy", over: false });
});

test("a run over several entries has more steps than the workflow: it says running, without a count that reads wrong", () => {
  assert.equal(runLine(run("running", { stepsOk: 12 })).text, "Running…");
  assert.equal(runLine(run("running", { stepsTotal: 0, stepsOk: 2 })).text, "Running…");
});

test("a run at an approval waits on the reader, or on an admin when the question is not theirs to read", () => {
  assert.deepEqual(runLine(run("waiting", { waitingOn: [asked()] })), { text: "Waiting on you: it asks a question.", tone: "ask", over: false });
  assert.deepEqual(runLine(run("waiting", { waitingOn: [asked(null)] })), { text: "Waiting for an admin to answer its question.", tone: "ask", over: false });
});

test("a run that ended while its worker job has not is working, and names the job", () => {
  const job = (status) => ({ entryId: "e-1", slug: "job-1", kind: "render", status, finished: false });
  assert.deepEqual(runLine(run("working", { job: job("queued") })), { text: "Working: the render job is waiting for a worker…", tone: "busy", over: false });
  assert.equal(runLine(run("working", { job: job("running") })).text, "Working: the render job is running…");
});

test("done, failed and cancelled are over: nothing more to wait for", () => {
  assert.deepEqual(runLine(run("done", { stepsOk: 7 })), { text: "Done.", tone: "ok", over: true });
  assert.equal(runLine(run("done", { job: { entryId: "e-1", slug: "job-1", kind: "render", status: "done", finished: true } })).text, "Done: the render job finished.");
  assert.deepEqual(runLine(run("failed", { error: "the still of beat 2 is missing" })), { text: "Failed: the still of beat 2 is missing", tone: "bad", over: true });
  assert.equal(runLine(run("failed")).text, "Failed. The workflow’s runs say why.");
  assert.deepEqual(runLine(run("cancelled")), { text: "Stopped: this run will not go on.", tone: "bad", over: true });
});

test("what the page drew changes with the state and with what it waits on, not with a step count", () => {
  assert.equal(runKey(run("running", { stepsOk: 1 })), runKey(run("running", { stepsOk: 4 })));
  assert.notEqual(runKey(run("running")), runKey(run("waiting", { waitingOn: [asked()] })));
  assert.notEqual(runKey(run("waiting", { waitingOn: [asked()] })), runKey(run("waiting", { waitingOn: [{ ...asked(), approvalId: "ap-2" }] })));
});
