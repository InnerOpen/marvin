/**
 * Dictation — the browser's own speech recognition (Web Speech API) typing into a text box until stopped.
 *
 * Shared by the bubble and the Ask page. Chrome, Edge and Safari have it; Firefox doesn't, and there the
 * mic button stays hidden. Recognition runs in the browser (Chrome sends the audio to its own speech
 * service), costs nothing and needs no server support. The text lands in the input and is never sent on
 * its own: the user reads it, fixes it, and sends.
 *
 * Kept free of the DOM and of runtime imports so it runs under `node --test` (dictation.test.mjs): the
 * recognition constructor and the input are passed in.
 */

/** The slice of `SpeechRecognition` this uses. */
export interface RecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((ev: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((ev: { error: string }) => void) | null;
  start(): void;
  stop(): void;
}

export type RecognitionCtor = new () => RecognitionLike;

/** The browser's speech recognition, or null where there is none (Firefox). */
export function speechRecognition(win: unknown): RecognitionCtor | null {
  const w = win as
    | { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor }
    | null
    | undefined;
  return w?.SpeechRecognition ?? w?.webkitSpeechRecognition ?? null;
}

/** The input's text while dictating: what was typed before, then everything heard so far. */
export function dictatedText(before: string, results: ArrayLike<ArrayLike<{ transcript: string }>>): string {
  let heard = "";
  for (let i = 0; i < results.length; i++) heard += results[i][0].transcript;
  const base = before.trim() ? before.replace(/\s*$/, " ") : "";
  return base + heard.trimStart();
}

/** A recognition error as something to tell the user, or null for one that needs no message. */
export function dictationError(code: string): string | null {
  switch (code) {
    case "aborted":
      return null; // stopped on purpose
    case "no-speech":
      return "Didn't hear anything — try again.";
    case "not-allowed":
    case "service-not-allowed":
      return "Microphone access is blocked for this site.";
    case "audio-capture":
      return "No microphone found.";
    case "network":
      return "Speaking needs a connection to the browser's speech service.";
    default:
      return `Listening stopped (${code}).`;
  }
}

export interface DictationTarget {
  /** BCP 47 language to listen for, e.g. navigator.language. */
  lang: string;
  /**
   * Ask the browser for one long session. Desktop Chrome honours it; Android's Chrome repeats earlier words in
   * that mode, so the bubble passes false there and relies on the restarts alone.
   */
  continuous?: boolean;
  read(): string;
  write(text: string): void;
  /** Listening started (true) or ended (false) — once each per dictation, however many sessions it took. */
  onState(listening: boolean): void;
  onError(message: string): void;
  /** Clock for the silence limit (tests pass their own). */
  now?: () => number;
}

export interface Dictation {
  /** Start listening, or stop when already listening. */
  toggle(): void;
  /** Stop listening; words still being recognised land in the input. */
  stop(): void;
  /** Stop listening and drop anything still being recognised: the text was just sent and cleared. */
  cancel(): void;
  readonly listening: boolean;
}

/** Stop on our own after this long without hearing anything. */
export const DICTATION_SILENCE_MS = 20_000;
/** Errors that a new session would only repeat. */
const FATAL = new Set(["not-allowed", "service-not-allowed", "audio-capture", "network", "language-not-supported"]);

/**
 * Dictation into `target` until the user stops it. Browsers end a recognition session at a pause (Chrome even
 * mid-sentence), so when one ends on its own a new session starts, continuing from the text as it is then. It
 * gives up after DICTATION_SILENCE_MS without a word, or on an error a new session would repeat.
 */
export function createDictation(Recognition: RecognitionCtor, target: DictationTarget): Dictation {
  const now = target.now ?? Date.now;
  let rec: RecognitionLike | null = null;
  let active = false; // between the user's start and the end of the last session
  let wanted = false; // the user hasn't stopped it
  let lastHeard = 0;
  let heardAny = false;
  let fatal = false;
  // The browser delivers its last results just after stop(); after cancel() they would refill a cleared input.
  let muted = false;

  function session() {
    const before = target.read();
    const r = new Recognition();
    rec = r;
    r.lang = target.lang || "en-US";
    r.interimResults = true;
    r.continuous = target.continuous ?? true;
    r.onresult = (ev) => {
      if (muted) return;
      lastHeard = now();
      heardAny = true;
      target.write(dictatedText(before, ev.results));
    };
    r.onstart = () => {
      if (active) return;
      active = true;
      target.onState(true);
    };
    r.onerror = (ev) => {
      if (FATAL.has(ev.error)) {
        fatal = true;
        const message = dictationError(ev.error);
        if (message) target.onError(message);
      }
    };
    r.onend = () => {
      if (rec !== r) return;
      rec = null;
      const silent = now() - lastHeard > DICTATION_SILENCE_MS;
      if (wanted && !fatal && !silent) {
        session();
        return;
      }
      if (wanted && silent && !heardAny) target.onError(dictationError("no-speech") as string);
      wanted = false;
      if (active) {
        active = false;
        target.onState(false);
      }
    };
    r.start();
  }

  function stop() {
    wanted = false;
    rec?.stop();
  }

  function cancel() {
    muted = true;
    stop();
  }

  return {
    toggle() {
      if (wanted || rec) {
        stop();
        return;
      }
      wanted = true;
      muted = false;
      fatal = false;
      heardAny = false;
      lastHeard = now();
      session();
    },
    stop,
    cancel,
    get listening() {
      return active;
    },
  };
}
