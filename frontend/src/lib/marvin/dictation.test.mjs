// Dictation (dictation.ts) with a scripted recognition in place of the browser's. Run with `npm test`.

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { createDictation, dictatedText, dictationError, speechRecognition } from "./dictation.ts";

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
    made[0].onresult({ results: results("there") });
    assert.equal(t.value, "Hi there");

    d.toggle();
    assert.equal(made[0].stopped, true);
    assert.equal(d.listening, false);
    assert.deepEqual(t.states, [true, false]);
    assert.equal(made.length, 1); // stopping didn't start another
  });

  test("each start builds on the text as it is then", () => {
    const { Fake, made } = fakeRecognition();
    const t = target("");
    const d = createDictation(Fake, t);
    d.toggle();
    made[0].onresult({ results: results("first") });
    d.toggle();
    t.value = "first, edited";
    d.toggle();
    made[1].onresult({ results: results("second") });
    assert.equal(t.value, "first, edited second");
  });

  test("errors reach the user, except a deliberate abort", () => {
    const { Fake, made } = fakeRecognition();
    const t = target();
    createDictation(Fake, t).toggle();
    made[0].onerror({ error: "aborted" });
    made[0].onerror({ error: "no-speech" });
    assert.deepEqual(t.errors, ["Didn't hear anything — try again."]);
  });
});
