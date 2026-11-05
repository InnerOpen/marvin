// The Workers page's view of the queue (workers.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { runGuide } from "./workerCommands.ts";
import { ago, groupByImage, imageLabel, needsLook, summarize, workerSetup } from "./workers.ts";

const NOW = Date.parse("2026-11-04T12:00:00Z");
const iso = (secondsAgo) => new Date(NOW - secondsAgo * 1000).toISOString();
const job = (title, data, createdSecondsAgo = 30) => ({ id: title, slug: title, title, createdAt: iso(createdSecondsAgo), dataJson: data });
const kind = (k, data = {}) => ({ id: k, slug: k, title: k, dataJson: { kind: k, mode: "docker", image: "img", timeout_seconds: 600, ...data } });
const beat = (secondsAgo, extra = {}) => ({ id: "w", slug: "w", title: "Worker dispatcher", dataJson: { host: "host-a", last_seen: iso(secondsAgo), modes: "docker", jobs_started: 7, ...extra } });

describe("summarize", () => {
  test("a finished job keeps its whole log and a link to its result only when it holds a real one", () => {
    const [done, failed] = summarize([job("a", { kind: "k", status: "done", url: "https://x.test/cut.mp3", log: "ok" }), job("b", { kind: "k", status: "failed", url: "javascript:alert(1)", log: "line one\nline two" })], [kind("k")], [beat(10)], NOW).jobs;
    assert.equal(done.resultUrl, "https://x.test/cut.mp3");
    assert.equal(failed.resultUrl, "");
    assert.equal(failed.log, "line one\nline two");
  });

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

const typeWith = (slug, keys) => ({ slug, schemaJson: { fields: keys.map((key) => ({ key })) } });

describe("workerSetup", () => {
  test("names the record types a workspace lacks, in the order they are set up", () => {
    const got = workerSetup([typeWith("page", ["body"]), typeWith("job", ["kind", "args", "status", "result", "log"])]);
    assert.deepEqual(got.missing, ["job-kind", "worker"]);
    assert.deepEqual(got.misfit, []);
  });
  test("is empty once all three are there with the fields workers use", () => {
    const got = workerSetup([
      typeWith("worker", ["role", "host", "last_seen", "kinds", "tags"]),
      typeWith("job-kind", ["kind", "mode", "image", "timeout_seconds"]),
      typeWith("job", ["kind", "args", "status", "result", "log", "attempts"]),
    ]);
    assert.deepEqual(got, { missing: [], misfit: [] });
  });
  test("a same-named type without the fields (a job board's `job`) is a misfit, not set up", () => {
    const got = workerSetup([typeWith("job", ["title", "salary"]), typeWith("job-kind", []), typeWith("worker", [])]);
    assert.deepEqual(got.missing, []);
    assert.deepEqual(got.misfit[0], { slug: "job", lacks: ["kind", "args", "status", "result", "log"] });
    assert.equal(got.misfit.length, 3);
  });
});

describe("runGuide", () => {
  const guide = runGuide("https://api.example.com", "studio");

  test("fills in this Marvin and workspace, and leaves the token a placeholder", () => {
    const all = [...guide.first, ...guide.options.flatMap((o) => o.blocks)].map((b) => b.code).join("\n");
    assert.match(all, /--pin studio/);
    assert.match(all, /MARVIN_API_URL=https:\/\/api\.example\.com/);
    assert.match(all, /<the token above>/);
    assert.doesNotMatch(all, /eyJ|Bearer/);
  });
  test("covers a process, Docker, Podman and Kubernetes or OpenShift", () => {
    assert.deepEqual(guide.options.map((o) => o.id), ["process", "docker", "podman", "kubernetes"]);
    assert.ok(guide.options.every((o) => o.blocks.length > 0 && o.blurb));
  });
  test("Podman runs podman and tells the dispatcher to use it; Docker runs docker", () => {
    const code = (id) => guide.options.find((o) => o.id === id).blocks.map((b) => b.code).join("\n");
    assert.match(code("podman"), /podman run/);
    assert.match(code("podman"), /WORKER_CONTAINER_CLI=podman/);
    assert.doesNotMatch(code("docker"), /podman/);
  });
  test("OpenShift gets oc, Kubernetes kubectl", () => {
    const code = guide.options.find((o) => o.id === "kubernetes").blocks.map((b) => b.code).join("\n");
    assert.match(code, /kubectl create secret/);
    assert.match(code, /oc create secret/);
  });
});

describe("needsLook", () => {
  const count = (jobs, workers) => needsLook(summarize(jobs, [kind("k")], workers, NOW));

  test("a workspace that never used workers counts nothing", () => {
    assert.equal(count([], []), 0);
  });

  test("a job that failed in the last day counts; an older one does not", () => {
    assert.equal(count([job("a", { kind: "k", status: "failed" }, 600), job("b", { kind: "k", status: "failed" }, 3 * 86400), job("c", { kind: "k", status: "done" })], [beat(10)]), 1);
  });

  test("queued jobs count only when workers have reported before and none is running now", () => {
    const queued = [job("a", { kind: "k", status: "queued" }), job("b", { kind: "k", status: "queued" })];
    assert.equal(count(queued, [beat(10)]), 0);
    assert.equal(count(queued, [beat(900)]), 2);
    assert.equal(count(queued, []), 0);
  });

  test("a stuck job and a job for an unregistered kind each count once", () => {
    assert.equal(count([job("a", { kind: "k", status: "running", claimed_at: iso(99999) }, 100000), job("b", { kind: "nope", status: "queued" })], [beat(10)]), 2);
  });
});

describe("which image a worker runs", () => {
  test("a heartbeat that names its image shows it, with the release and the commit", () => {
    const [w] = summarize([], [], [beat(10, { image: "screenplay-studio-worker", version: "v35", revision: "1b702bf" })], NOW).workers;
    assert.deepEqual([w.image, w.version, w.revision], ["screenplay-studio-worker", "v35", "1b702bf"]);
    assert.equal(imageLabel(w), "screenplay-studio-worker:v35 (1b702bf)");
  });

  test("an older worker, or one that was not told, says nothing; partial names still read", () => {
    const [old] = summarize([], [], [beat(10)], NOW).workers;
    assert.equal(imageLabel(old), "");
    assert.equal(imageLabel({ image: "w", version: "", revision: "" }), "w");
    assert.equal(imageLabel({ image: "", version: "v2", revision: "" }), "v2");
    assert.equal(imageLabel({ image: "", version: "", revision: "abc" }), "revision abc");
  });
});

describe("workers grouped under their image", () => {
  const w = (name, secondsAgo, extra = {}) => ({ id: name, slug: name, title: name, dataJson: { host: name, last_seen: iso(secondsAgo), ...extra } });
  const view = (rows) => summarize([], [], rows, NOW);

  test("workers that run the same image and release sit together, the unreported ones last", () => {
    const { groups } = view([
      w("runner", 10, { image: "studio", version: "v35.1", revision: "abc" }),
      w("transcriber", 12, { image: "studio", version: "v35.1", revision: "abc" }),
      w("old-box", 20),
    ]);
    assert.deepEqual(groups.map((g) => [g.title, g.workers.map((x) => x.name).sort()]), [["studio:v35.1", ["runner", "transcriber"]], ["Image not reported", ["old-box"]]]);
    assert.deepEqual(groups[0].revisions, ["abc"]);
    assert.equal(groups[0].running, 2);
  });

  test("a half-finished update shows: each release names the other as also running", () => {
    const { groups } = view([w("a", 10, { image: "studio", version: "v35.1" }), w("b", 10, { image: "studio", version: "v35" }), w("c", 10, { image: "other", version: "v1" })]);
    const byKey = Object.fromEntries(groups.map((g) => [g.key, g]));
    assert.deepEqual(byKey["studio:v35.1"].alsoRunning, ["v35"]);
    assert.deepEqual(byKey["studio:v35"].alsoRunning, ["v35.1"]);
    assert.deepEqual(byKey["other:v1"].alsoRunning, []);  // a different image is not a different release of this one
  });

  test("a worker that stopped does not count as a release running elsewhere, and a group says how many of its workers run", () => {
    const { groups } = view([w("a", 10, { image: "studio", version: "v35.1" }), w("b", 900, { image: "studio", version: "v35" }), w("c", 900, { image: "studio", version: "v35.1" })]);
    const newer = groups.find((g) => g.key === "studio:v35.1");
    assert.deepEqual([newer.workers.length, newer.running, newer.alsoRunning], [2, 1, []]);  // v35 is not running any more
  });

  test("different builds of one release are listed, and a worker that only names a version still groups", () => {
    const { groups } = view([w("a", 10, { image: "studio", version: "v1", revision: "aaa" }), w("b", 10, { image: "studio", version: "v1", revision: "bbb-dirty" }), w("c", 10, { version: "v9" })]);
    assert.deepEqual(groups.find((g) => g.key === "studio:v1").revisions, ["aaa", "bbb-dirty"]);
    assert.ok(groups.some((g) => g.key === "v9"));
  });

  test("no workers means no groups", () => {
    assert.deepEqual(groupByImage([]), []);
  });
});
