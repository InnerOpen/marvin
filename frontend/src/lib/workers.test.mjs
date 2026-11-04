// The Workers page's view of the queue (workers.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { ago, summarize } from "./workers.ts";

const NOW = Date.parse("2026-11-04T12:00:00Z");
const iso = (secondsAgo) => new Date(NOW - secondsAgo * 1000).toISOString();
const job = (title, data, createdSecondsAgo = 30) => ({ id: title, slug: title, title, createdAt: iso(createdSecondsAgo), dataJson: data });
const kind = (k, data = {}) => ({ id: k, slug: k, title: k, dataJson: { kind: k, mode: "docker", image: "img", timeout_seconds: 600, ...data } });
const beat = (secondsAgo, extra = {}) => ({ id: "w", slug: "w", title: "Worker dispatcher", dataJson: { host: "host-a", last_seen: iso(secondsAgo), modes: "docker", jobs_started: 7, ...extra } });

describe("summarize", () => {
  test("counts jobs by status", () => {
    const v = summarize([job("a", { kind: "k", status: "done" }), job("b", { kind: "k", status: "failed" }), job("c", { kind: "k", status: "done" })], [kind("k")], [beat(10)], NOW);
    assert.deepEqual([v.counts.done, v.counts.failed, v.counts.queued], [2, 1, 0]);
  });

  test("a dispatcher is healthy while it keeps reporting, and not after three quiet minutes", () => {
    assert.equal(summarize([], [], [beat(60)], NOW).workers[0].healthy, true);
    assert.equal(summarize([], [], [beat(400)], NOW).workers[0].healthy, false);
    const w = summarize([], [], [beat(60)], NOW).workers[0];
    assert.deepEqual([w.name, w.modes, w.jobsDone, w.role], ["host-a", "docker", 7, "worker"]);
  });

  test("queued jobs with nobody watching are called out", () => {
    const v = summarize([job("a", { kind: "k", status: "queued" })], [kind("k")], [beat(900)], NOW);
    assert.match(v.warnings[0], /1 job is queued and no worker has reported/);
    assert.equal(summarize([job("a", { kind: "k", status: "queued" })], [kind("k")], [beat(20)], NOW).warnings.length, 0);
  });

  test("no dispatcher at all says how to start one", () => {
    assert.match(summarize([], [], [], NOW).warnings[0], /No dispatcher or runner has reported yet/);
  });

  test("a job claimed longer ago than its kind allows (plus the grace) is stuck; a fresh one is not", () => {
    const stale = job("a", { kind: "k", status: "running", claimed_at: iso(600 + 121) });
    const fresh = job("b", { kind: "k", status: "running", claimed_at: iso(30) });
    const v = summarize([stale, fresh], [kind("k")], [beat(10)], NOW);
    assert.deepEqual(v.jobs.map((j) => j.stuck), [true, false]);
    assert.match(v.warnings.join(" "), /1 job has run past the time allowed/);
  });

  test("a queued job for an unregistered kind is flagged, a kind's mode defaults to kubernetes", () => {
    const v = summarize([job("a", { kind: "mystery", status: "queued" })], [{ id: "x", slug: "x", title: "x", dataJson: { kind: "k" } }], [beat(5)], NOW);
    assert.equal(v.jobs[0].unknownKind, true);
    assert.match(v.warnings.join(" "), /nobody registered/);
    assert.equal(v.kinds[0].mode, "kubernetes");
    assert.equal(v.kinds[0].timeoutSeconds, 3600);
  });
});

const runner = (secondsAgo, kinds, extra = {}) => ({
  id: "r", slug: "r", title: "Runner",
  dataJson: { role: "runner", host: "box-1", status: "busy", current_job: "audio-cut-5", tags: "ffmpeg", last_seen: iso(secondsAgo), jobs_done: 3, kinds, ...extra },
});
const audioCut = {
  kind: "audio-cut", description: "Stitch a story's lines", produces: ["audio/mpeg"], needs: ["ffmpeg"], accepts: [],
  inputs: { story: { type: "string", required: true, description: "the story's slug" }, source: { type: "asset", required: false, accepts: ["audio/*"] } },
};

describe("workers and what they can do", () => {
  test("a runner is listed with its status, current job, what it has and how much it has done", () => {
    const [w] = summarize([], [], [runner(30, [audioCut])], NOW).workers;
    assert.deepEqual([w.role, w.status, w.currentJob, w.tags, w.kinds, w.jobsDone, w.healthy], ["runner", "busy", "audio-cut-5", "ffmpeg", ["audio-cut"], 3, true]);
  });

  test("a kind's contract is what a worker advertised: what it takes, which are needed, what it accepts, gives and needs", () => {
    const [c] = summarize([], [], [runner(30, [audioCut])], NOW).capabilities;
    assert.equal(c.kind, "audio-cut");
    assert.equal(c.description, "Stitch a story's lines");
    assert.deepEqual(c.inputs.map((i) => [i.name, i.type, i.required]), [["story", "string", true], ["source", "asset", false]]);
    assert.deepEqual(c.inputs[1].accepts, ["audio/*"]);
    assert.deepEqual([c.produces, c.needs, c.offeredBy], [["audio/mpeg"], ["ffmpeg"], ["box-1"]]);
  });

  test("a runner that has stopped reporting no longer counts as offering the kind", () => {
    const [c] = summarize([], [], [runner(900, [audioCut])], NOW).capabilities;
    assert.deepEqual(c.offeredBy, []);
  });

  test("a job-kind record no worker has advertised still lists, with nobody offering it", () => {
    const v = summarize([], [kind("pdf-split")], [runner(30, [audioCut])], NOW);
    assert.deepEqual(v.capabilities.map((c) => [c.kind, c.offeredBy.length]), [["audio-cut", 1], ["pdf-split", 0]]);
  });

  test("a queued job whose kind no running worker offers is called out, while another kind that is offered is not", () => {
    const jobs = [job("a", { kind: "pdf-split", status: "queued" }), job("b", { kind: "audio-cut", status: "queued" })];
    const v = summarize(jobs, [kind("pdf-split")], [runner(30, [audioCut])], NOW);
    assert.equal(v.warnings.filter((w) => /pdf-split/.test(w) && /no running worker offers it/.test(w)).length, 1);
    assert.equal(v.warnings.some((w) => /audio-cut/.test(w)), false);
  });

  test("a live worker that has not listed its kinds (an older dispatcher) might offer anything, so no kind is called uncovered", () => {
    const v = summarize([job("a", { kind: "pdf-split", status: "queued" })], [kind("pdf-split")], [beat(10)], NOW);
    assert.equal(v.warnings.length, 0);
  });

  test("a dispatcher counts as offering the kinds it can launch", () => {
    const [c] = summarize([], [kind("k")], [beat(10, { kinds: [{ kind: "k", description: "launched in docker mode" }] })], NOW).capabilities;
    assert.deepEqual(c.offeredBy, ["host-a"]);
  });
});

describe("ago", () => {
  test("reads short", () => {
    assert.deepEqual([ago(5), ago(200), ago(7200), ago(200000), ago(null)], ["5 s", "3 min", "2 h", "2 d", "never"]);
  });
});
