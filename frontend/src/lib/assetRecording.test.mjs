// What an asset's page says about a recording: its Transcript and its facts (assetRecording.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { assetNamed, audioFacts, formatLength, languageName, recordingFacts, splitForMore, transcriptOf, transcriptQuery, videoFacts } from "./assetRecording.ts";

describe("transcriptQuery", () => {
  test("the Transcripts whose source is the recording's id or, in older ones, its slug", () => {
    assert.deepEqual(transcriptQuery({ id: "a1", slug: "take-3" }), {
      spec: { entry_type: "transcript", where: [{ field: "source", op: "in", value: ["a1", "take-3"] }] },
      limit: 5,
    });
  });
  test("no slug: the id alone", () => {
    assert.deepEqual(transcriptQuery({ id: "a1", slug: "" }).spec.where, [{ field: "source", op: "in", value: ["a1"] }]);
  });
});

describe("transcriptOf", () => {
  test("its language, length (number-like text too) and the two text files", () => {
    const entry = { id: "e1", title: "Take 3", dataJson: { source: "a1", paragraphs: "p-id", timestamped: "t-slug", language: "en", duration_seconds: "83.4" } };
    assert.deepEqual(transcriptOf(entry), { id: "e1", title: "Take 3", language: "en", seconds: 83.4, paragraphs: "p-id", timestamped: "t-slug" });
  });
  test("one with neither text file shows nothing", () => {
    assert.equal(transcriptOf({ id: "e1", dataJson: { language: "en" } }), null);
    assert.equal(transcriptOf(null), null);
  });
  test("missing facts are null, an untitled one is a Transcript", () => {
    assert.deepEqual(transcriptOf({ id: "e1", title: " ", dataJson: { timestamped: "t" } }), { id: "e1", title: "Transcript", language: null, seconds: null, paragraphs: null, timestamped: "t" });
  });
});

test("assetNamed: a field's asset by id or slug", () => {
  const assets = [{ id: "1", slug: "one" }, { id: "2", slug: "two" }];
  assert.equal(assetNamed(assets, "2")?.slug, "two");
  assert.equal(assetNamed(assets, "one")?.id, "1");
  assert.equal(assetNamed(assets, "three"), null);
  assert.equal(assetNamed(assets, null), null);
});

test("languageName: a code by its name; anything else as it is", () => {
  assert.equal(languageName("en"), "English");
  assert.equal(languageName("de"), "German");
  assert.equal(languageName("Klingon spoken fast"), "Klingon spoken fast");
});

test("formatLength: a clock", () => {
  assert.equal(formatLength(7), "0:07");
  assert.equal(formatLength(83.4), "1:23");
  assert.equal(formatLength(3725), "1:02:05");
});

describe("splitForMore", () => {
  test("short text is shown whole", () => {
    assert.deepEqual(splitForMore("  Hello.\n\nBye. ", 100), { head: "Hello.\n\nBye.", rest: "" });
  });
  test("long text is cut at a paragraph's end in the second half", () => {
    const body = `${"a".repeat(60)}\n\n${"b".repeat(60)}`;
    assert.deepEqual(splitForMore(body, 100), { head: "a".repeat(60), rest: "b".repeat(60) });
  });
  test("else at a space, never inside a word", () => {
    const { head, rest } = splitForMore("one two three four five six", 12);
    assert.equal(head, "one two");
    assert.equal(rest, "three four five six");
  });
});

describe("videoFacts", () => {
  test("length, size, fps, sound", () => {
    assert.deepEqual(videoFacts({ video: { duration_seconds: 42.2, width: 1080, height: 1920, fps: 29.97, has_audio: true } }), ["0:42", "1080 × 1920", "29.97 fps", "with sound"]);
    assert.deepEqual(videoFacts({ video: { duration_seconds: 5, width: 640, height: 480, fps: null, has_audio: false } }), ["0:05", "640 × 480", "no sound"]);
  });
  test("other plain values follow; none at all is nothing", () => {
    assert.deepEqual(videoFacts({ video: { has_audio: false, codec: "h264", streams: [1] } }), ["no sound", "codec h264"]);
    assert.deepEqual(videoFacts({}), []);
    assert.deepEqual(videoFacts({ video: "yes" }), []);
    assert.deepEqual(videoFacts(null), []);
  });
});

test("audioFacts: whatever an audio block holds", () => {
  assert.deepEqual(audioFacts({ audio: { seconds: 61, sample_rate: 44100, channels: 1, codec: "opus", loud: true } }), ["1:01", "44.1 kHz", "mono", "codec opus", "loud yes"]);
  assert.deepEqual(audioFacts({ video: {} }), []);
});

describe("recordingFacts", () => {
  test("the audio recorder's: device, microphone settings, length, peak, clipped", () => {
    const recording = {
      source: "browser",
      mime: "audio/webm;codecs=opus",
      device: "USB Mic",
      sample_rate: 48000,
      channels: 1,
      constraints: { echo_cancellation: false, noise_suppression: true, auto_gain_control: null },
      duration_seconds: 12.3,
      peak_dbfs: -3.14,
      clipped: false,
    };
    assert.deepEqual(recordingFacts({ recording }), [
      "recorded in the browser",
      "microphone USB Mic",
      "48 kHz",
      "mono",
      "echo cancellation off",
      "noise suppression on",
      "0:12",
      "peak -3.1 dBFS",
      "not clipped",
    ]);
  });
  test("the video recorder's: camera, microphone, size, frame rate, gain", () => {
    const recording = {
      source: "browser",
      kind: "video",
      camera: "FaceTime HD",
      microphone: "Built-in",
      width: 1280,
      height: 720,
      frame_rate: 30,
      sample_rate: 48000,
      channels: 2,
      constraints: { echo_cancellation: true, noise_suppression: true, auto_gain_control: true },
      gain: 1.5,
      duration_seconds: 65,
      peak_dbfs: 0,
      clipped: true,
      stopped: "button",
    };
    assert.deepEqual(recordingFacts({ recording }), [
      "recorded in the browser",
      "camera FaceTime HD",
      "microphone Built-in",
      "1280 × 720",
      "30 fps",
      "48 kHz",
      "stereo",
      "echo cancellation on",
      "noise suppression on",
      "auto gain on",
      "gain 1.5",
      "1:05",
      "peak 0 dBFS",
      "clipped",
      "stopped button",
    ]);
  });
  test("all unknown is nothing; no recording is nothing", () => {
    const blank = { source: null, device: null, sample_rate: null, channels: null, constraints: { echo_cancellation: null }, duration_seconds: 0, peak_dbfs: null, clipped: null };
    assert.deepEqual(recordingFacts({ recording: blank }), []);
    assert.deepEqual(recordingFacts({ recording: "browser" }), []);
    assert.deepEqual(recordingFacts({}), []);
    assert.deepEqual(recordingFacts(undefined), []);
  });
});
