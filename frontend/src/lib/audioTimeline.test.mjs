// The audio cut's timeline on a job entry (audioTimeline.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { findTimeline, rowAt, timecode } from "./audioTimeline.ts";

const result = {
  url: "https://a/cut.mp3",
  seconds: 12.5,
  timeline: [
    { shot: "b02", start: 6, sounds: [{ id: "waves", start: 3, end: 9 }], lines: [{ id: "line-02-1", speaker: "narrator", text: "Tonight.", start: 6.1, end: 8 }] },
    { shot: "b01", start: 0, sounds: [], lines: [{ id: "line-01-1", speaker: "narrator", text: "The captain ordered a feast.", start: 0.3, end: 2.4 }] },
  ],
};

describe("findTimeline", () => {
  test("finds the audio and flattens lines and sounds in time order, whatever the field is called", () => {
    const t = findTimeline({ kind: "audio-cut", status: "done", result });
    assert.equal(t?.url, "https://a/cut.mp3");
    assert.equal(t?.seconds, 12.5);
    assert.deepEqual(t?.rows.map((r) => [r.kind, r.id, r.start]), [["line", "line-01-1", 0.3], ["sound", "waves", 3], ["line", "line-02-1", 6.1]]);
    assert.equal(t?.rows[0].speaker, "narrator");
  });

  test("an entry without a timeline, or with an empty one, has none", () => {
    assert.equal(findTimeline({ status: "queued" }), null);
    assert.equal(findTimeline({ result: { url: "https://a/x.mp3", timeline: [] } }), null);
    assert.equal(findTimeline({ result: { timeline: result.timeline } }), null); // no audio to play
    assert.equal(findTimeline(null), null);
  });

  test("odd rows are skipped, not fatal", () => {
    const t = findTimeline({ r: { url: "u", timeline: [null, { shot: "x", lines: [{ text: "no start" }, { text: "ok", start: 1 }] }] } });
    assert.deepEqual(t?.rows.map((r) => r.text), ["ok"]);
  });
});

describe("timecode and rowAt", () => {
  test("reads like a player", () => {
    assert.equal(timecode(41.04), "0:41.0");
    assert.equal(timecode(75.5), "1:15.5");
    assert.equal(timecode(5), "0:05.0");
  });

  test("the playing row is the one whose span holds the time; a gap has none", () => {
    const rows = findTimeline({ r: result }).rows;
    assert.equal(rowAt(rows, 1), 0);
    assert.equal(rowAt(rows, 2.9), -1);
    assert.equal(rowAt(rows, 7), 2); // the later of the overlapping sound and line is the line
  });
});
