// Dictation (dictation.ts) with a scripted recognition in place of the browser's. Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { createDictation, DICTATION_SILENCE_MS, dictatedText, dictationError, speechRecognition } from "./dictation.ts";

const results = (...phrases) => phrases.map((p) => [{ transcript: p }]);

/** A recognition class whose instances the test drives; `made` holds every instance. */
function fakeRecognition() {
  const made = [];
  class Fake {
    constructor() {
      this.started = false;
      this.stopped = false;
      made.push(this);
    }
    start() {
      this.started = true;
      this.onstart?.();
    }
    stop() {
      this.stopped = true;
      this.onend?.();
    }
  }
  return { Fake, made };
}

function target(initial = "") {
  const t = { value: initial, states: [], errors: [], lang: "en-GB" };
  return Object.assign(t, {
    read: () => t.value,
    write: (text) => (t.value = text),
    onState: (on) => t.states.push(on),
    onError: (msg) => t.errors.push(msg),
  });
}

describe("speechRecognition", () => {
  test("finds the standard or the webkit constructor, else null (Firefox)", () => {
    const Std = class {};
    const Webkit = class {};
    assert.equal(speechRecognition({ SpeechRecognition: Std, webkitSpeechRecognition: Webkit }), Std);
    assert.equal(speechRecognition({ webkitSpeechRecognition: Webkit }), Webkit);
    assert.equal(speechRecognition({}), null);
    assert.equal(speechRecognition(undefined), null);
  });
});

describe("dictatedText", () => {
  test("appends what is heard to what was typed, with one space between", () => {
    assert.equal(dictatedText("Summarise", results(" this page")), "Summarise this page");
    assert.equal(dictatedText("Summarise   ", results("this page")), "Summarise this page");
  });

  test("joins streamed results and starts clean on an empty input", () => {
    assert.equal(dictatedText("", results("what is", " in this PDF")), "what is in this PDF");
    assert.equal(dictatedText("  ", results(" hello")), "hello");
  });
});

describe("dictationError", () => {
  test("a deliberate stop says nothing; known failures say what to do", () => {
    assert.equal(dictationError("aborted"), null);
    assert.match(dictationError("not-allowed"), /blocked/);
    assert.match(dictationError("network"), /connection/);
    assert.match(dictationError("weird-thing"), /weird-thing/);
  });
});

describe("createDictation", () => {
  test("toggle listens, writes results into the input, toggle again stops", () => {
    const { Fake, made } = fakeRecognition();
    const t = target("Hi");
    const d = createDictation(Fake, t);

    d.toggle();
    assert.equal(d.listening, true);
    assert.equal(made[0].lang, "en-GB");
    assert.equal(made[0].interimResults, true);
    assert.equal(made[0].continuous, true);
    made[0].onresult({ results: results("there") });
    assert.equal(t.value, "Hi there");

    d.toggle();
    assert.equal(made[0].stopped, true);
    assert.equal(d.listening, false);
    assert.deepEqual(t.states, [true, false]);
    assert.equal(made.length, 1); // stopping didn't start another
  });

  test("a session the browser ends at a pause is followed by another, until the user stops", () => {
    const { Fake, made } = fakeRecognition();
    const t = target("");
    const d = createDictation(Fake, t);
    d.toggle();
    made[0].onresult({ results: results("I think you stop") });
    made[0].onend(); // Chrome ending mid-sentence
    assert.equal(made.length, 2);
    made[1].onresult({ results: results("too soon") });
    assert.equal(t.value, "I think you stop too soon");
    assert.equal(d.listening, true);
    assert.deepEqual(t.states, [true]); // one start for the user, however many sessions

    d.toggle();
    assert.deepEqual(t.states, [true, false]);
    assert.equal(made.length, 2);
  });

  test("gives up after a long silence, saying so only when nothing was heard", () => {
    let clock = 0;
    const { Fake, made } = fakeRecognition();
    const t = target("");
    const d = createDictation(Fake, Object.assign(t, { now: () => clock }));
    d.toggle();
    clock = DICTATION_SILENCE_MS + 1;
    made.at(-1).onend();
    assert.equal(d.listening, false);
    assert.deepEqual(t.errors, ["Didn't hear anything — try again."]);
  });

  test("cancel (on send) drops results that arrive after it; stop keeps them", () => {
    const { Fake, made } = fakeRecognition();
    const t = target("");
    const d = createDictation(Fake, t);
    d.toggle();
    made[0].onresult({ results: results("talk talk talk") });
    d.cancel();
    t.value = ""; // the input is cleared as the message goes
    made[0].onresult({ results: results("talk talk talk") }); // Chrome's late final result
    assert.equal(t.value, "");
    assert.equal(d.listening, false);

    d.toggle(); // a new dictation hears again
    made[1].onresult({ results: results("again") });
    d.stop();
    made[1].onresult({ results: results("again, finished") });
    assert.equal(t.value, "again, finished");
  });

  test("an error a new session would repeat ends it with a message", () => {
    const { Fake, made } = fakeRecognition();
    const t = target();
    const d = createDictation(Fake, t);
    d.toggle();
    made[0].onerror({ error: "no-speech" }); // not fatal: the next session may hear something
    made[0].onerror({ error: "not-allowed" });
    made[0].onend();
    assert.equal(made.length, 1);
    assert.equal(d.listening, false);
    assert.deepEqual(t.errors, ["Microphone access is blocked for this site."]);
  });

  test("continuous can be turned off (Android) and restarts carry the dictation", () => {
    const { Fake, made } = fakeRecognition();
    const t = target("");
    createDictation(Fake, Object.assign(t, { continuous: false })).toggle();
    assert.equal(made[0].continuous, false);
    made[0].onresult({ results: results("one") });
    made[0].onend();
    made[1].onresult({ results: results("two") });
    assert.equal(t.value, "one two");
  });
});
