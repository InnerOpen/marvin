// The video recorder's pure parts (videoRecorder.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { recordingMetadata } from "./audioRecorder.ts";
import { UPLOAD_LIMIT_BYTES } from "./uploadLimit.ts";
import {
  DEFAULT_MIC_GAIN,
  MAX_MIC_GAIN,
  MAX_VIDEO_SECONDS,
  MIN_MIC_GAIN,
  NO_PROCESSING,
  SIZE_GUARD,
  VIDEO_MIME_CANDIDATES,
  clampMicGain,
  countdownFrom,
  expectedBytes,
  microphoneConstraints,
  parseDeviceChoice,
  pickVideoMimeType,
  processingHeld,
  stopReason,
  stoppedWords,
  videoConstraints,
  videoFileFor,
  videoRecordingMetadata,
} from "./videoRecorder.ts";

describe("pickVideoMimeType", () => {
  test("test_pick_prefers_h264_aac_mp4_where_supported", () => {
    assert.equal(
      pickVideoMimeType(() => true),
      "video/mp4;codecs=avc1,mp4a.40.2",
    );
  });

  test("test_pick_takes_the_browsers_own_mp4_before_webm", () => {
    assert.equal(
      pickVideoMimeType((t) => t === "video/mp4" || t.startsWith("video/webm")),
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
    assert.deepEqual(c.audio, { autoGainControl: false, echoCancellation: false, noiseSuppression: false });
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

  test("test_constraints_carry_the_processing_ticked", () => {
    const processing = { autoGainControl: true, echoCancellation: false, noiseSuppression: true };
    const c = videoConstraints({ microphoneId: "mic", processing });
    assert.deepEqual(c.audio, { deviceId: { exact: "mic" }, ...processing });
  });
});

describe("microphoneConstraints", () => {
  test("test_microphone_constraints_default_to_no_processing", () => {
    assert.deepEqual(microphoneConstraints({}), NO_PROCESSING);
  });

  test("test_microphone_constraints_match_the_audio_of_the_full_request", () => {
    const choice = { cameraId: "cam", microphoneId: "mic", remembered: true, processing: { ...NO_PROCESSING, echoCancellation: true } };
    assert.deepEqual(microphoneConstraints(choice), videoConstraints(choice).audio);
  });
});

describe("processingHeld", () => {
  const asked = { autoGainControl: false, echoCancellation: true, noiseSuppression: false };

  test("test_processing_held_when_the_track_reports_what_was_asked", () => {
    assert.equal(processingHeld(asked, { ...asked, deviceId: "x" }), true);
  });

  test("test_processing_not_held_when_the_browser_ignored_a_change", () => {
    assert.equal(processingHeld(asked, { ...asked, echoCancellation: false }), false);
  });

  test("test_processing_unreported_settings_pass", () => {
    assert.equal(processingHeld(asked, {}), true);
  });
});

describe("clampMicGain", () => {
  test("test_mic_gain_kept_within_the_slider", () => {
    assert.equal(clampMicGain(1.5), 1.5);
    assert.equal(clampMicGain(9), MAX_MIC_GAIN);
    assert.equal(clampMicGain(0), MIN_MIC_GAIN);
    assert.equal(clampMicGain("0.75"), 0.75);
  });

  test("test_mic_gain_default_for_junk", () => {
    for (const junk of [undefined, null, "", "loud", NaN, Infinity, {}]) assert.equal(clampMicGain(junk), DEFAULT_MIC_GAIN);
  });
});

describe("parseDeviceChoice", () => {
  const defaults = { processing: { ...NO_PROCESSING }, micGain: 1 };

  test("test_device_choice_round_trips", () => {
    const choice = {
      cameraId: "c",
      microphoneId: "m",
      countdown: true,
      processing: { autoGainControl: true, echoCancellation: false, noiseSuppression: true },
      micGain: 1.4,
    };
    assert.deepEqual(parseDeviceChoice(JSON.stringify(choice)), choice);
  });

  test("test_device_choice_kept_before_the_mic_settings_still_reads", () => {
    const old = { cameraId: "c", microphoneId: "m", countdown: true };
    assert.deepEqual(parseDeviceChoice(JSON.stringify(old)), { ...old, ...defaults });
  });

  test("test_device_choice_bad_mic_settings_fall_back_one_by_one", () => {
    const stored = { cameraId: "c", processing: { echoCancellation: "yes", noiseSuppression: true }, micGain: 40 };
    const choice = parseDeviceChoice(JSON.stringify(stored));
    assert.deepEqual(choice.processing, { autoGainControl: false, echoCancellation: false, noiseSuppression: true });
    assert.equal(choice.micGain, MAX_MIC_GAIN);
  });

  test("test_device_choice_defaults_for_nothing_or_junk", () => {
    const none = { cameraId: "", microphoneId: "", countdown: false, ...defaults };
    assert.deepEqual(parseDeviceChoice(null), none);
    assert.deepEqual(parseDeviceChoice("{not json"), none);
    assert.deepEqual(parseDeviceChoice("42"), none);
    assert.deepEqual(parseDeviceChoice('{"cameraId": 7, "countdown": "yes"}'), none);
  });
});

describe("videoRecordingMetadata", () => {
  test("test_metadata_keeps_devices_size_length_and_the_microphone", () => {
    const facts = videoRecordingMetadata(
      {
        mimeType: "video/webm;codecs=vp9,opus",
        camera: "USB camera",
        microphone: "Studio mic",
        width: 1280,
        height: 720,
        frameRate: 29.97,
        sampleRate: 48000,
        channelCount: 1,
        echoCancellation: false,
        noiseSuppression: true,
        autoGainControl: false,
        gain: 1.5,
      },
      { durationSeconds: 12.34, stopped: null, peak: 0.5, clipped: false },
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
        sample_rate: 48000,
        channels: 1,
        constraints: { echo_cancellation: false, noise_suppression: true, auto_gain_control: false },
        gain: 1.5,
        duration_seconds: 12.3,
        peak_dbfs: -6,
        clipped: false,
        stopped: null,
      },
    });
  });

  test("test_metadata_microphone_facts_match_the_audio_recorders", () => {
    const mic = { sampleRate: 44100, channelCount: 2, echoCancellation: true, noiseSuppression: false, autoGainControl: true };
    const video = videoRecordingMetadata({ mimeType: "video/mp4", ...mic }, { durationSeconds: 1 }).recording;
    const audio = recordingMetadata({ mimeType: "audio/mp4", ...mic }, { durationSeconds: 1, peak: 0, clipped: false }).recording;
    for (const key of ["sample_rate", "channels", "constraints"]) assert.deepEqual(video[key], audio[key], key);
  });

  test("test_metadata_clipped_take_and_no_gain", () => {
    const { recording } = videoRecordingMetadata({ mimeType: "", gain: null }, { durationSeconds: 3, peak: 1, clipped: true });
    assert.equal(recording.peak_dbfs, 0);
    assert.equal(recording.clipped, true);
    assert.equal(recording.gain, null);
  });

  test("test_metadata_unknowns_are_null", () => {
    const { recording } = videoRecordingMetadata({ mimeType: "" }, { durationSeconds: 600, stopped: "time" });
    assert.equal(recording.camera, null);
    assert.equal(recording.width, null);
    assert.equal(recording.frame_rate, null);
    assert.equal(recording.stopped, "time");
    assert.equal(recording.sample_rate, null);
    assert.deepEqual(recording.constraints, { echo_cancellation: null, noise_suppression: null, auto_gain_control: null });
    assert.equal(recording.gain, null);
    assert.equal(recording.peak_dbfs, null, "no meter, no level");
    assert.equal(recording.clipped, null);
  });

  test("test_metadata_silent_take_has_no_level", () => {
    assert.equal(videoRecordingMetadata({ mimeType: "" }, { durationSeconds: 1, peak: 0, clipped: false }).recording.peak_dbfs, null);
  });
});
