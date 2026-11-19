// Moments in a sound or video: the time a page opens at, transcript markers and their buttons (mediaTime.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

import {
  assetHref,
  clampTime,
  escapeHtml,
  firstMarkerSeconds,
  hasTimeMarkers,
  parseMediaTime,
  startTimeFrom,
  timedParts,
  timedTextHtml,
} from "./mediaTime.ts";

describe("parseMediaTime", () => {
  test("seconds, with or without an s", () => {
    assert.equal(parseMediaTime("65"), 65);
    assert.equal(parseMediaTime("65s"), 65);
    assert.equal(parseMediaTime(" 65.5 "), 65.5);
    assert.equal(parseMediaTime("0"), 0);
  });
  test("a clock: m:ss and h:mm:ss", () => {
    assert.equal(parseMediaTime("1:05"), 65);
    assert.equal(parseMediaTime("0:01:05"), 65);
    assert.equal(parseMediaTime("1:02:03"), 3723);
    assert.equal(parseMediaTime("90:00"), 5400);
  });
  test("units: 1m5s, 1h2m3s, 2m", () => {
    assert.equal(parseMediaTime("1m5s"), 65);
    assert.equal(parseMediaTime("1h2m3s"), 3723);
    assert.equal(parseMediaTime("2m"), 120);
  });
  test("garbage is no time", () => {
    for (const raw of [
      null,
      undefined,
      "",
      "  ",
      "abc",
      "-5",
      "1:60",
      "1:61:00",
      "1:2:3:4",
      "Infinity",
      "NaN",
      "1e3",
      "5x",
      "m",
      "h",
      ":05",
      "1:",
    ]) {
      assert.equal(parseMediaTime(raw), null, String(raw));
    }
  });
});

describe("startTimeFrom", () => {
  test("the t query parameter", () => {
    assert.equal(startTimeFrom({ search: "?t=65", hash: "" }), 65);
    assert.equal(startTimeFrom({ search: "?x=1&t=1%3A05", hash: "" }), 65);
  });
  test("a #t= hash when the query has none", () => {
    assert.equal(startTimeFrom({ search: "", hash: "#t=0:01:05" }), 65);
    assert.equal(startTimeFrom({ search: "?t=nope", hash: "#t=30" }), 30);
  });
  test("neither: null, so the page behaves as it always did", () => {
    assert.equal(startTimeFrom({ search: "", hash: "" }), null);
    assert.equal(startTimeFrom({ search: "?t=", hash: "#top" }), null);
    assert.equal(startTimeFrom({}), null);
  });
});

describe("clampTime", () => {
  test("inside the media's length", () => {
    assert.equal(clampTime(65, 120), 65);
    assert.equal(clampTime(500, 120), 120);
    assert.equal(clampTime(-3, 120), 0);
  });
  test("a length not known yet (a browser recording's Infinity or NaN) is left to the browser", () => {
    assert.equal(clampTime(500, Number.POSITIVE_INFINITY), 500);
    assert.equal(clampTime(500, Number.NaN), 500);
  });
});

describe("markers", () => {
  const transcript =
    "Speech in take 3, as text with where each part starts:\n[0:00:00] Hello there.\n[0:01:05] The middle.\n[1:02:03] Late.\n";

  test("the first marker's seconds", () => {
    assert.equal(firstMarkerSeconds(transcript), 0);
    assert.equal(firstMarkerSeconds("s on.\n[0:01:05] The middle.\n[1:02:03] Late."), 65);
    assert.equal(firstMarkerSeconds("[12:00:00] long"), 43200);
  });
  test("no marker: null; a time in words or a malformed one is not a marker", () => {
    assert.equal(firstMarkerSeconds("met at 1:05 for coffee"), null);
    assert.equal(firstMarkerSeconds("[0:1:05] [0:61:00] [1:05]"), null);
    assert.equal(firstMarkerSeconds(null), null);
    assert.equal(hasTimeMarkers("plain description"), false);
    assert.equal(hasTimeMarkers(transcript), true);
  });
  test("text cut into words and markers, in order", () => {
    assert.deepEqual(timedParts("a [0:00:02] b\n[0:00:09] c"), [
      { text: "a " },
      { marker: "[0:00:02]", seconds: 2 },
      { text: " b\n" },
      { marker: "[0:00:09]", seconds: 9 },
      { text: " c" },
    ]);
    assert.deepEqual(timedParts("no times"), [{ text: "no times" }]);
    assert.deepEqual(timedParts(""), []);
  });
});

describe("timedTextHtml", () => {
  test("each marker is a button that plays from its time, labelled for a screen reader", () => {
    assert.equal(
      timedTextHtml("[0:01:05] The middle.\n[1:02:03] Late."),
      '<button type="button" class="seek-mark" data-seek-to="65" aria-label="Play from 1:05">[0:01:05]</button> The middle.\n' +
        '<button type="button" class="seek-mark" data-seek-to="3723" aria-label="Play from 1:02:03">[1:02:03]</button> Late.',
    );
  });
  test("a transcript's words can never put markup on the page", () => {
    const html = timedTextHtml(`[0:00:01] <script>alert("x")</script> & <img src=x onerror='y'>`);
    assert.ok(!html.includes("<script") && !html.includes("<img"));
    assert.ok(
      html.includes("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; &lt;img src=x onerror=&#39;y&#39;&gt;"),
    );
    assert.equal((html.match(/<button /g) ?? []).length, 1);
  });
  test("text without markers is only escaped", () => {
    assert.equal(timedTextHtml("Tom & Jerry"), "Tom &amp; Jerry");
    assert.equal(escapeHtml(`<>"'&`), "&lt;&gt;&quot;&#39;&amp;");
  });
});

describe("assetHref", () => {
  test("a time opens the asset's view page there; none opens the page an asset link always opened", () => {
    assert.equal(assetHref("a1", 65), "/workspace/assets/a1/view?t=65");
    assert.equal(assetHref("a1", 65.9), "/workspace/assets/a1/view?t=65");
    assert.equal(assetHref("a1", 0), "/workspace/assets/a1/view?t=0");
    assert.equal(assetHref("a1"), "/workspace/assets/a1");
    assert.equal(assetHref("a1", null), "/workspace/assets/a1");
    assert.equal(assetHref("a/1"), "/workspace/assets/a%2F1");
  });
});

// The pages themselves: the player they cue is marked, and the transcript and description go through TimedText (so through
// timedTextHtml's escaping), never through a set:html of their own.
describe("the asset pages", () => {
  const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
  const view = read("pages/workspace/assets/[id]/view.astro");
  const edit = read("pages/workspace/assets/[id].astro");
  const transcript = read("components/AssetTranscript.astro");
  const timed = read("components/TimedText.astro");

  test("the view page marks its audio and video player, cues it from the URL and shows a timed description through TimedText", () => {
    assert.match(view, /<video controls preload="metadata" data-seek-player>/);
    assert.match(view, /<audio controls preload="metadata" data-seek-player>/);
    assert.match(view, /wireMediaSeek\(\)/);
    assert.match(view, /hasTimeMarkers\(asset\.description\) \? <TimedText text=\{asset\.description\} \/>/);
  });
  test("the edit page's preview player opens at ?t= too", () => {
    assert.equal((edit.match(/data-seek-player/g) ?? []).length, 2);
    assert.match(edit, /wireMediaSeek\(\)/);
  });
  test("the Transcript block shows its words through TimedText", () => {
    assert.match(transcript, /<TimedText text=\{body\.head\} \/>/);
    assert.match(transcript, /<TimedText text=\{body\.rest\} \/>/);
    assert.ok(!transcript.includes("set:html"));
  });
  test("TimedText's only HTML is timedTextHtml's", () => {
    assert.deepEqual(timed.match(/set:html=\{[^}]*\}/g), ["set:html={timedTextHtml(text)}"]);
  });
});
