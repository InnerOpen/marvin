// What both recorders share (recording.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { MICROPHONE_WORDS } from "./audioRecorder.ts";
import {
  createStopwatch,
  deviceError,
  deviceOptions,
  readStored,
  recordButtons,
  recordingFactsOf,
  safeBaseName,
  uploadFields,
  writeStored,
} from "./recording.ts";
import { CAMERA_WORDS } from "./videoRecorder.ts";

describe("createStopwatch", () => {
  const fakeClock = () => {
    let ms = 0;
    return { now: () => ms, advance: (s) => (ms += s * 1000) };
  };

  test("test_stopwatch_counts_from_start", () => {
    const clock = fakeClock();
    const watch = createStopwatch(clock.now);
    watch.start();
    clock.advance(2.5);
    assert.equal(watch.elapsed(), 2.5);
    assert.equal(watch.running(), true);
  });

  test("test_stopwatch_pause_leaves_out_the_time_paused", () => {
    const clock = fakeClock();
    const watch = createStopwatch(clock.now);
    watch.start();
    clock.advance(3);
    watch.pause();
    clock.advance(10);
    watch.resume();
    clock.advance(1);
    assert.equal(watch.elapsed(), 4);
  });

  test("test_stopwatch_stop_holds_the_take_length", () => {
    const clock = fakeClock();
    const watch = createStopwatch(clock.now);
    watch.start();
    clock.advance(7);
    watch.stop();
    clock.advance(60);
    assert.equal(watch.elapsed(), 7);
    assert.equal(watch.running(), false);
  });

  test("test_stopwatch_start_and_reset_begin_from_nought", () => {
    const clock = fakeClock();
    const watch = createStopwatch(clock.now);
    watch.start();
    clock.advance(5);
    watch.stop();
    watch.start();
    clock.advance(1);
    assert.equal(watch.elapsed(), 1, "a retake starts its clock again");
    watch.reset();
    assert.equal(watch.elapsed(), 0);
  });

  test("test_stopwatch_resume_while_running_changes_nothing", () => {
    const clock = fakeClock();
    const watch = createStopwatch(clock.now);
    watch.start();
    clock.advance(2);
    watch.resume();
    clock.advance(2);
    assert.equal(watch.elapsed(), 4);
  });
});

describe("deviceOptions", () => {
  const devices = [
    { kind: "audioinput", deviceId: "mic-a", label: "Studio mic" },
    { kind: "videoinput", deviceId: "cam-a", label: "" },
    { kind: "audiooutput", deviceId: "spk", label: "Speakers" },
    { kind: "videoinput", deviceId: "cam-b", label: "USB camera" },
  ];

  test("test_device_options_lists_only_the_kind_asked_for", () => {
    assert.deepEqual(
      deviceOptions(devices, "videoinput", "Camera", "cam-b").map((o) => o.value),
      ["cam-a", "cam-b"],
    );
  });

  test("test_device_options_names_an_unlabelled_device_by_its_place", () => {
    const [first, second] = deviceOptions(devices, "videoinput", "Camera", "");
    assert.equal(first.label, "Camera 1");
    assert.equal(second.label, "USB camera");
  });

  test("test_device_options_selects_the_device_in_use", () => {
    assert.deepEqual(
      deviceOptions(devices, "videoinput", "Camera", "cam-b").map((o) => o.selected),
      [false, true],
    );
    assert.equal(deviceOptions(devices, "audioinput", "Microphone", "mic-a")[0].selected, true);
  });

  test("test_device_options_empty_when_there_is_none", () => {
    assert.deepEqual(deviceOptions([], "videoinput", "Camera", ""), []);
  });
});

describe("deviceError", () => {
  const named = (name, message = "") => new DOMException(message, name);

  test("test_device_error_refused_camera_says_allow_the_camera", () => {
    assert.match(deviceError(named("NotAllowedError"), CAMERA_WORDS), /Allow the camera for this site/);
  });

  test("test_device_error_missing_or_overconstrained_says_none_found", () => {
    assert.equal(deviceError(named("NotFoundError"), CAMERA_WORDS), CAMERA_WORDS.missing);
    assert.equal(deviceError(named("OverconstrainedError"), CAMERA_WORDS), CAMERA_WORDS.missing);
  });

  test("test_device_error_busy_device", () => {
    assert.equal(deviceError(named("NotReadableError"), CAMERA_WORDS), CAMERA_WORDS.busy);
  });

  test("test_device_error_other_errors_keep_their_message", () => {
    assert.equal(deviceError(new Error("boom"), CAMERA_WORDS), "boom");
    assert.equal(deviceError("??", CAMERA_WORDS), CAMERA_WORDS.failed);
  });

  test("test_device_error_microphone_words_are_the_audio_recorders_as_before", () => {
    assert.equal(
      deviceError(named("NotAllowedError"), MICROPHONE_WORDS),
      "The microphone was refused. Allow it for this site in the browser's settings, then try again.",
    );
    assert.equal(
      deviceError(named("NotFoundError"), MICROPHONE_WORDS),
      "No microphone was found. Plug one in, or pick another, then try again.",
    );
    assert.equal(
      deviceError(named("NotReadableError"), MICROPHONE_WORDS),
      "The microphone is busy with another app. Close it, then try again.",
    );
  });
});

describe("readStored and writeStored", () => {
  const memory = () => {
    const map = new Map();
    return { getItem: (k) => map.get(k) ?? null, setItem: (k, v) => map.set(k, v) };
  };
  const refusing = () => {
    throw new DOMException("denied", "SecurityError");
  };

  test("test_stored_value_round_trips", () => {
    const store = memory();
    writeStored(() => store, "k", "v");
    assert.equal(
      readStored(() => store, "k"),
      "v",
    );
  });

  test("test_stored_value_tolerates_refused_storage", () => {
    assert.equal(readStored(refusing, "k"), null);
    assert.doesNotThrow(() => writeStored(refusing, "k", "v"));
    const throwingMethods = { getItem: refusing, setItem: refusing };
    assert.equal(
      readStored(() => throwingMethods, "k"),
      null,
    );
    assert.doesNotThrow(() => writeStored(() => throwingMethods, "k", "v"));
  });
});

describe("recordingFactsOf", () => {
  const file = new File(["x"], "take.webm");
  const other = new File(["y"], "picked.webm");
  const recorderOf = (made, facts) => ({ metadataOf: (f) => (f === made ? facts : null) });

  test("test_recording_facts_come_from_whichever_recorder_made_the_file", () => {
    const audio = recorderOf(other, { recording: { kind: "audio" } });
    const video = recorderOf(file, { recording: { kind: "video" } });
    assert.deepEqual(recordingFactsOf(file, [audio, video]), { recording: { kind: "video" } });
  });

  test("test_recording_facts_null_for_a_picked_file_or_no_recorder", () => {
    assert.equal(recordingFactsOf(file, [undefined, null, {}]), null);
    assert.equal(recordingFactsOf(file, [recorderOf(other, { a: 1 })]), null);
  });
});

describe("recordButtons", () => {
  test("test_record_buttons_sound_only_zone_keeps_its_plain_record", () => {
    assert.deepEqual(recordButtons(true, false), [{ kind: "audio", label: "Record…", again: "Record again…" }]);
  });

  test("test_record_buttons_video_only_zone_records_video", () => {
    assert.deepEqual(
      recordButtons(false, true).map((b) => [b.kind, b.label]),
      [["video", "Record video…"]],
    );
  });

  test("test_record_buttons_both_name_what_each_records", () => {
    assert.deepEqual(
      recordButtons(true, true).map((b) => [b.kind, b.label, b.again]),
      [
        ["audio", "Record audio…", "Record audio again…"],
        ["video", "Record video…", "Record video again…"],
      ],
    );
  });

  test("test_record_buttons_none_for_a_zone_that_takes_neither", () => {
    assert.deepEqual(recordButtons(false, false), []);
  });
});

describe("uploadFields", () => {
  const file = new File(["x"], "take.webm", { type: "video/webm" });

  test("test_upload_fields_send_the_file_slug_name_and_recording_facts", () => {
    const fields = uploadFields({
      file,
      slug: "line-1-take-1",
      name: "Line 1 · take 1",
      metadata: { recording: { kind: "video" } },
    });
    assert.deepEqual(
      fields.map(([k]) => k),
      ["file", "slug", "name", "metadata"],
    );
    assert.equal(fields[0][1], file);
    assert.deepEqual(JSON.parse(fields[3][1]), { recording: { kind: "video" } });
  });

  test("test_upload_fields_leave_out_blank_texts_and_trim_the_rest", () => {
    const fields = uploadFields({ file, slug: "s", name: "n", altText: "  ", description: " A take ", metadata: null });
    assert.deepEqual(fields.slice(3), [["description", "A take"]]);
  });

  test("test_upload_fields_keep_alt_text", () => {
    const fields = uploadFields({ file, slug: "s", name: "n", altText: "Me, waving" });
    assert.deepEqual(fields.slice(3), [["alt_text", "Me, waving"]]);
  });
});

test("test_safe_base_name_strips_accents_and_marks", () => {
  assert.equal(safeBaseName("Café · take 2"), "cafe-take-2");
  assert.equal(safeBaseName("···"), "recording");
});
