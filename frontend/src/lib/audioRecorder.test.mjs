// The audio recorder's pure parts (audioRecorder.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  MIME_CANDIDATES,
  canPauseReliably,
  containerOf,
  fileFor,
  formatClock,
  levelOf,
  looksTruncated,
  meterPosition,
  pickMimeType,
  recordingMetadata,
  toDbfs,
} from "./audioRecorder.ts";

describe("pickMimeType", () => {
  test("WebM/Opus when the browser makes it", () => {
    assert.equal(pickMimeType(() => true), "audio/webm;codecs=opus");
  });
  test("MP4/AAC on a Safari without WebM", () => {
    assert.equal(pickMimeType((t) => t.startsWith("audio/mp4")), "audio/mp4;codecs=mp4a.40.2");
  });
  test("Ogg/Opus on a Firefox without WebM", () => {
    assert.equal(pickMimeType((t) => t.startsWith("audio/ogg")), "audio/ogg;codecs=opus");
  });
  test("empty, so the browser chooses, when it claims none", () => {
    assert.equal(pickMimeType(() => false), "");
  });
  test("asks in the listed order", () => {
    const asked = [];
    pickMimeType((t) => {
      asked.push(t);
      return false;
    });
    assert.deepEqual(asked, MIME_CANDIDATES);
  });
});

describe("containerOf", () => {
  test("the container, without the kind or the codecs", () => {
    assert.equal(containerOf("audio/webm;codecs=opus"), "webm");
    assert.equal(containerOf("VIDEO/WebM"), "webm");
    assert.equal(containerOf("audio/mp4; codecs=mp4a.40.2"), "mp4");
  });
  test("empty for no type", () => {
    assert.equal(containerOf(""), "");
  });
});

describe("fileFor", () => {
  const blob = new Blob(["x"]);
  test("WebM is a .webm sent as audio/webm, without the codecs", () => {
    const f = fileFor(blob, "audio/webm;codecs=opus", "Take");
    assert.deepEqual([f.name, f.type], ["take.webm", "audio/webm"]);
  });
  test("a sound-only take the browser called video/webm is still sent as audio", () => {
    assert.equal(fileFor(blob, "video/webm;codecs=vp8,opus", "t").type, "audio/webm");
  });
  test("MP4 is a .m4a, never a .mp4 the server would call a video", () => {
    const f = fileFor(blob, "audio/mp4;codecs=mp4a.40.2", "t");
    assert.deepEqual([f.name, f.type], ["t.m4a", "audio/mp4"]);
  });
  test("Ogg and WAV keep their own extensions", () => {
    assert.equal(fileFor(blob, "audio/ogg;codecs=opus", "t").name, "t.ogg");
    assert.deepEqual([fileFor(blob, "audio/x-wav", "t").name, fileFor(blob, "audio/x-wav", "t").type], ["t.wav", "audio/wav"]);
  });
  test("the blob's own type stands in for a missing one", () => {
    assert.equal(fileFor(new Blob(["x"], { type: "audio/ogg" }), "", "t").name, "t.ogg");
  });
  test("an unknown type is filed as WebM, MediaRecorder's usual default", () => {
    assert.equal(fileFor(blob, "", "t").name, "t.webm");
  });
  test("the name is safe for a path and the SDK", () => {
    assert.equal(fileFor(blob, "audio/webm", "Café / Line 7 · take 3").name, "cafe-line-7-take-3.webm");
    assert.equal(fileFor(blob, "audio/webm", " ·· ").name, "recording.webm");
  });
  test("the bytes are the blob's", async () => {
    assert.equal(await fileFor(new Blob(["sound"]), "audio/webm", "t").text(), "sound");
  });
});

describe("levelOf", () => {
  test("peak and RMS of a frame", () => {
    const level = levelOf(new Float32Array([0.5, -0.5, 0.5, -0.5]));
    assert.equal(level.peak, 0.5);
    assert.equal(level.rms, 0.5);
    assert.equal(level.clipped, false);
  });
  test("a negative spike counts toward the peak", () => {
    assert.equal(levelOf([0.1, -0.8, 0.2]).peak, 0.8);
  });
  test("full scale is clipped", () => {
    assert.equal(levelOf([0, 0.995, 0]).clipped, true);
    assert.equal(levelOf([0, -1.2, 0]).clipped, true);
  });
  test("an empty or silent frame is zero, not NaN", () => {
    assert.deepEqual(levelOf([]), { peak: 0, rms: 0, clipped: false });
    assert.deepEqual(levelOf(new Float32Array(8)), { peak: 0, rms: 0, clipped: false });
  });
});

describe("toDbfs", () => {
  test("full scale is 0 dB, half is about -6", () => {
    assert.equal(toDbfs(1), 0);
    assert.equal(toDbfs(0.5), -6);
  });
  test("silence is null", () => {
    assert.equal(toDbfs(0), null);
  });
});

describe("meterPosition", () => {
  test("full scale fills the meter, the floor empties it, halfway in dB is halfway", () => {
    assert.equal(meterPosition(1), 1);
    assert.equal(meterPosition(0.001), 0);
    assert.equal(meterPosition(10 ** (-30 / 20)), 0.5);
  });
  test("silence and past full scale stay inside the meter", () => {
    assert.equal(meterPosition(0), 0);
    assert.equal(meterPosition(1.5), 1);
  });
});

describe("formatClock", () => {
  test("minutes and seconds", () => {
    assert.equal(formatClock(0), "0:00");
    assert.equal(formatClock(7.9), "0:07");
    assert.equal(formatClock(125), "2:05");
  });
  test("hours past an hour", () => {
    assert.equal(formatClock(3725), "1:02:05");
  });
  test("nonsense reads as zero", () => {
    assert.equal(formatClock(-3), "0:00");
    assert.equal(formatClock(Number.POSITIVE_INFINITY), "0:00");
  });
});

describe("canPauseReliably", () => {
  const chrome = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36";
  const firefox = "Mozilla/5.0 (X11; Linux x86_64; rv:144.0) Gecko/20100101 Firefox/144.0";
  const safari = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.1 Safari/605.1.15";
  const iosChrome = "Mozilla/5.0 (iPhone; CPU iPhone OS 26_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/141.0 Mobile/15E148 Safari/604.1";
  test("Chrome and Firefox pause", () => {
    assert.equal(canPauseReliably(chrome), true);
    assert.equal(canPauseReliably(firefox), true);
  });
  test("Safari, and any browser on iOS, does not", () => {
    assert.equal(canPauseReliably(safari), false);
    assert.equal(canPauseReliably(iosChrome), false);
  });
});

describe("looksTruncated", () => {
  test("a take decoded well short of the clock", () => {
    assert.equal(looksTruncated(22, 60), true);
  });
  test("a second or so of difference is the clock's own slack", () => {
    assert.equal(looksTruncated(59.4, 60), false);
  });
  test("unknown when the browser couldn't decode it", () => {
    assert.equal(looksTruncated(null, 60), false);
    assert.equal(looksTruncated(Number.POSITIVE_INFINITY, 60), false);
  });
});

describe("recordingMetadata", () => {
  test("the facts, under `recording`", () => {
    const meta = recordingMetadata(
      { mimeType: "audio/webm;codecs=opus", deviceLabel: "USB mic", sampleRate: 48000, channelCount: 1, echoCancellation: false, noiseSuppression: true, autoGainControl: false },
      { durationSeconds: 12.437, peak: 0.5, clipped: false },
    );
    assert.deepEqual(meta, {
      recording: {
        source: "browser",
        mime: "audio/webm;codecs=opus",
        device: "USB mic",
        sample_rate: 48000,
        channels: 1,
        constraints: { echo_cancellation: false, noise_suppression: true, auto_gain_control: false },
        duration_seconds: 12.4,
        peak_dbfs: -6,
        clipped: false,
      },
    });
  });
  test("what the browser didn't report is null, not missing", () => {
    const { recording } = recordingMetadata({ mimeType: "audio/mp4" }, { durationSeconds: 3, peak: 0, clipped: false });
    assert.equal(recording.device, null);
    assert.equal(recording.sample_rate, null);
    assert.equal(recording.peak_dbfs, null);
    assert.deepEqual(recording.constraints, { echo_cancellation: null, noise_suppression: null, auto_gain_control: null });
  });
});
