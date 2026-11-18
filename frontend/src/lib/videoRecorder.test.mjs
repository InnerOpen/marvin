// The video recorder's pure parts (videoRecorder.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { UPLOAD_LIMIT_BYTES } from "./uploadLimit.ts";
import {
  MAX_VIDEO_SECONDS,
  SIZE_GUARD,
  VIDEO_MIME_CANDIDATES,
  countdownFrom,
  expectedBytes,
  parseDeviceChoice,
  pickVideoMimeType,
  stopReason,
  stoppedWords,
  videoConstraints,
  videoFileFor,
  videoRecordingMetadata,
} from "./videoRecorder.ts";

describe("pickVideoMimeType", () => {
  test("test_pick_prefers_mp4_where_supported", () => {
    assert.equal(
      pickVideoMimeType(() => true),
      "video/mp4",
    );
  });

  test("test_pick_falls_back_vp9_then_vp8_then_plain_webm", () => {
    const only =
      (...ok) =>
      (t) =>
        ok.includes(t);
    assert.equal(pickVideoMimeType(only("video/webm;codecs=vp9,opus", "video/webm")), "video/webm;codecs=vp9,opus");
    assert.equal(pickVideoMimeType(only("video/webm;codecs=vp8,opus", "video/webm")), "video/webm;codecs=vp8,opus");
    assert.equal(pickVideoMimeType(only("video/webm")), "video/webm");
  });

  test("test_pick_empty_lets_the_browser_choose", () => {
    assert.equal(
      pickVideoMimeType(() => false),
      "",
    );
  });

  test("test_candidates_are_all_video", () => {
    assert.ok(VIDEO_MIME_CANDIDATES.every((t) => t.startsWith("video/")));
  });
});

describe("the ten-minute and size limits", () => {
  test("test_a_full_length_take_at_the_asked_bitrate_fits_one_upload", () => {
    assert.ok(expectedBytes(MAX_VIDEO_SECONDS) < UPLOAD_LIMIT_BYTES * SIZE_GUARD);
  });

  test("test_stop_reason_none_while_short_and_small", () => {
    assert.equal(stopReason(30, 5_000_000), null);
  });

  test("test_stop_reason_time_at_ten_minutes", () => {
    assert.equal(stopReason(MAX_VIDEO_SECONDS - 0.1, 0), null);
    assert.equal(stopReason(MAX_VIDEO_SECONDS, 0), "time");
  });

  test("test_stop_reason_size_near_the_upload_limit", () => {
    assert.equal(stopReason(60, Math.floor(UPLOAD_LIMIT_BYTES * SIZE_GUARD)), "size");
    assert.equal(stopReason(60, UPLOAD_LIMIT_BYTES * 0.5), null);
  });

  test("test_stop_reason_takes_its_own_limits", () => {
    assert.equal(stopReason(5, 0, { maxSeconds: 5 }), "time");
    assert.equal(stopReason(1, 100, { maxBytes: 100 }), "size");
  });

  test("test_stopped_words_say_why", () => {
    assert.match(stoppedWords("time"), /10 minutes/);
    assert.match(stoppedWords("size"), /upload/);
    assert.equal(stoppedWords(null), "");
  });
});

describe("countdownFrom", () => {
  test("test_countdown_three_two_one", () => {
    assert.deepEqual(countdownFrom(), [3, 2, 1]);
  });

  test("test_countdown_nothing_for_zero_or_less", () => {
    assert.deepEqual(countdownFrom(0), []);
    assert.deepEqual(countdownFrom(-2), []);
  });
});

describe("videoFileFor", () => {
  const blob = new Blob(["x"]);

  test("test_video_file_mp4_named_and_typed_without_codecs", () => {
    const file = videoFileFor(blob, "video/mp4;codecs=avc1.64001F,mp4a.40.2", "Intro · take 2");
    assert.equal(file.name, "intro-take-2.mp4");
    assert.equal(file.type, "video/mp4");
  });

  test("test_video_file_webm", () => {
    const file = videoFileFor(blob, "video/webm;codecs=vp9,opus", "Clip");
    assert.equal(file.name, "clip.webm");
    assert.equal(file.type, "video/webm");
  });

  test("test_video_file_unknown_type_falls_back_to_webm", () => {
    assert.equal(videoFileFor(blob, "", "x").type, "video/webm");
    assert.equal(videoFileFor(blob, "video/x-matroska", "x").name, "x.webm");
  });

  test("test_video_file_reads_the_blob_type_when_the_recorder_said_nothing", () => {
    assert.equal(videoFileFor(new Blob(["x"], { type: "video/mp4" }), "", "x").name, "x.mp4");
  });
});

describe("videoConstraints", () => {
  test("test_constraints_default_devices_ask_for_720p", () => {
    const c = videoConstraints({});
    assert.equal(c.video.deviceId, undefined);
    assert.deepEqual(c.video.width, { ideal: 1280 });
    assert.deepEqual(c.audio, {});
  });

  test("test_constraints_remembered_devices_are_ideal", () => {
    const c = videoConstraints({ cameraId: "cam", microphoneId: "mic", remembered: true });
    assert.deepEqual(c.video.deviceId, { ideal: "cam" });
    assert.deepEqual(c.audio.deviceId, { ideal: "mic" });
  });

  test("test_constraints_picked_devices_are_exact", () => {
    const c = videoConstraints({ cameraId: "cam", microphoneId: "mic" });
    assert.deepEqual(c.video.deviceId, { exact: "cam" });
    assert.deepEqual(c.audio.deviceId, { exact: "mic" });
  });
});

describe("parseDeviceChoice", () => {
  test("test_device_choice_round_trips", () => {
    const choice = { cameraId: "c", microphoneId: "m", countdown: true };
    assert.deepEqual(parseDeviceChoice(JSON.stringify(choice)), choice);
  });

  test("test_device_choice_defaults_for_nothing_or_junk", () => {
    const none = { cameraId: "", microphoneId: "", countdown: false };
    assert.deepEqual(parseDeviceChoice(null), none);
    assert.deepEqual(parseDeviceChoice("{not json"), none);
    assert.deepEqual(parseDeviceChoice("42"), none);
    assert.deepEqual(parseDeviceChoice('{"cameraId": 7, "countdown": "yes"}'), none);
  });
});

describe("videoRecordingMetadata", () => {
  test("test_metadata_keeps_devices_size_and_length", () => {
    const facts = videoRecordingMetadata(
      {
        mimeType: "video/webm;codecs=vp9,opus",
        camera: "USB camera",
        microphone: "Studio mic",
        width: 1280,
        height: 720,
        frameRate: 29.97,
      },
      { durationSeconds: 12.34, stopped: null },
    );
    assert.deepEqual(facts, {
      recording: {
        source: "browser",
        kind: "video",
        mime: "video/webm;codecs=vp9,opus",
        camera: "USB camera",
        microphone: "Studio mic",
        width: 1280,
        height: 720,
        frame_rate: 30,
        duration_seconds: 12.3,
        stopped: null,
      },
    });
  });

  test("test_metadata_unknowns_are_null", () => {
    const { recording } = videoRecordingMetadata({ mimeType: "" }, { durationSeconds: 600, stopped: "time" });
    assert.equal(recording.camera, null);
    assert.equal(recording.width, null);
    assert.equal(recording.frame_rate, null);
    assert.equal(recording.stopped, "time");
  });
});
