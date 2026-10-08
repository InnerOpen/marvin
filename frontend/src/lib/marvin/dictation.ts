/**
 * Dictation — the browser's own speech recognition (Web Speech API) typing into a text box.
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
      return "Dictation needs a connection to the browser's speech service.";
    default:
      return `Dictation stopped (${code}).`;
  }
}

export interface DictationTarget {
  /** BCP 47 language to listen for, e.g. navigator.language. */
  lang: string;
  read(): string;
  write(text: string): void;
  /** Listening started (true) or ended (false). */
  onState(listening: boolean): void;
  onError(message: string): void;
}

export interface Dictation {
  /** Start listening, or stop when already listening. */
  toggle(): void;
  stop(): void;
  readonly listening: boolean;
}

/** Dictation into `target` with the browser's recognition. One utterance per start; results stream in as heard. */
export function createDictation(Recognition: RecognitionCtor, target: DictationTarget): Dictation {
  let rec: RecognitionLike | null = null;
  let listening = false;

  function start() {
    const before = target.read();
    rec = new Recognition();
    rec.lang = target.lang || "en-US";
    rec.interimResults = true;
    rec.continuous = false;
    rec.onresult = (ev) => target.write(dictatedText(before, ev.results));
    rec.onstart = () => {
      listening = true;
      target.onState(true);
    };
    rec.onend = () => {
      listening = false;
      rec = null;
      target.onState(false);
    };
    rec.onerror = (ev) => {
      const message = dictationError(ev.error);
      if (message) target.onError(message);
    };
    rec.start();
  }

  return {
    toggle() {
      if (listening || rec) rec?.stop();
      else start();
    },
    stop() {
      rec?.stop();
    },
    get listening() {
      return listening;
    },
  };
}
