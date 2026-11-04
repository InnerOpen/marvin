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
    assert.equal(summarize([], [], [beat(60)], NOW).dispatchers[0].healthy, true);
    assert.equal(summarize([], [], [beat(400)], NOW).dispatchers[0].healthy, false);
    const d = summarize([], [], [beat(60)], NOW).dispatchers[0];
    assert.deepEqual([d.name, d.modes, d.jobsStarted], ["host-a", "docker", 7]);
  });

  test("queued jobs with nobody watching are called out", () => {
    const v = summarize([job("a", { kind: "k", status: "queued" })], [kind("k")], [beat(900)], NOW);
    assert.match(v.warnings[0], /1 job is queued and no dispatcher/);
    assert.equal(summarize([job("a", { kind: "k", status: "queued" })], [kind("k")], [beat(20)], NOW).warnings.length, 0);
  });

  test("no dispatcher at all says how to start one", () => {
    assert.match(summarize([], [], [], NOW).warnings[0], /No dispatcher has reported yet/);
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

describe("ago", () => {
  test("reads short", () => {
    assert.deepEqual([ago(5), ago(200), ago(7200), ago(200000), ago(null)], ["5 s", "3 min", "2 h", "2 d", "never"]);
  });
});
