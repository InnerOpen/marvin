// The pure parts both recorders share (components/AudioRecorder.astro, components/VideoRecorder.astro): the name of a take, its
// clock, the list of devices to pick from, the words for a device the browser would not open, a remembered choice, and what an
// upload of the take sends. Pure, so node can test them; lib/audioRecorder.ts and lib/videoRecorder.ts hold what is each one's own.

const FALLBACK_NAME = "recording";
const SECONDS_PER_MINUTE = 60;
const SECONDS_PER_HOUR = 3600;
/** Seconds a take may be shorter, once decoded, than the dialog's own clock said before it looks cut short. */
export const TRUNCATION_TOLERANCE_SECONDS = 1;

/** `audio/webm;codecs=opus` -> `webm`: the container, whatever the `audio/` or `video/` in front and the codecs after. */
export function containerOf(mimeType: string): string {
  const essence = mimeType.split(";")[0].trim().toLowerCase();
  return essence.includes("/") ? essence.split("/")[1] : "";
}

/** A name for a recording nobody named: "recording-2026-11-16-1932", so a list of them is told apart (not twelve "recording.webm"). */
export function stampedName(now: Date = new Date()): string {
  const two = (n: number) => String(n).padStart(2, "0");
  return `${FALLBACK_NAME}-${now.getFullYear()}-${two(now.getMonth() + 1)}-${two(now.getDate())}-${two(now.getHours())}${two(now.getMinutes())}`;
}

/** A name with nothing a path or the SDK would object to: "Line 7 · take 3" -> "line-7-take-3". */
export function safeBaseName(baseName: string): string {
  const slug = baseName
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug || FALLBACK_NAME;
}

/** `m:ss`, or `h:mm:ss` past an hour. */
export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
  const h = Math.floor(whole / SECONDS_PER_HOUR);
  const m = Math.floor((whole % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE);
  const s = whole % SECONDS_PER_MINUTE;
  const ss = String(s).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

/** True when the decoded take is clearly shorter than the time recorded (Safari 26.0–26.1 cut MP4 takes short). */
export function looksTruncated(decodedSeconds: number | null, recordedSeconds: number): boolean {
  if (decodedSeconds === null || !Number.isFinite(decodedSeconds)) return false;
  return recordedSeconds - decodedSeconds > TRUNCATION_TOLERANCE_SECONDS;
}

/** The clock of a take: it counts only time spent recording (what came before the last pause, plus the stretch since). */
export interface Stopwatch {
  /** From nought, running. */
  start(): void;
  /** Held where it is; `resume` runs it on from there. */
  pause(): void;
  resume(): void;
  /** Held where it is for good: `elapsed` stays the take's length. */
  stop(): void;
  /** Back to nought, held. */
  reset(): void;
  elapsed(): number;
  running(): boolean;
}

/** A stopwatch on a clock of milliseconds (`performance.now` in the page; a fake one in tests). */
export function createStopwatch(now: () => number): Stopwatch {
  let before = 0;
  let since: number | null = null;
  const elapsed = () => before + (since === null ? 0 : (now() - since) / 1000);
  const hold = () => {
    before = elapsed();
    since = null;
  };
  return {
    start() {
      before = 0;
      since = now();
    },
    pause: hold,
    resume() {
      if (since === null) since = now();
    },
    stop: hold,
    reset() {
      before = 0;
      since = null;
    },
    elapsed,
    running: () => since !== null,
  };
}

/** One choice in a device list. */
export interface DeviceOption {
  value: string;
  label: string;
  selected: boolean;
}

/** The devices of a kind (`audioinput`, `videoinput`) as choices, the one in use selected. A browser names a device only once
 * the page may use it; before that each is "Microphone 1", "Camera 2". */
export function deviceOptions(
  devices: ReadonlyArray<{ kind: string; deviceId: string; label?: string }>,
  kind: string,
  noun: string,
  current: string,
): DeviceOption[] {
  return devices
    .filter((d) => d.kind === kind)
    .map((d, i) => ({ value: d.deviceId, label: d.label || `${noun} ${i + 1}`, selected: d.deviceId === current }));
}

/** What to tell the person when a device would not open, by the error's name. */
export interface DeviceWords {
  refused: string;
  missing: string;
  busy: string;
  failed: string;
}

/** Why getUserMedia (or the recorder) failed, in the person's words: a refusal, no such device, a device another app holds. */
export function deviceError(e: unknown, words: DeviceWords): string {
  const name = typeof e === "object" && e !== null && "name" in e ? String((e as { name: unknown }).name) : "";
  if (name === "NotAllowedError") return words.refused;
  if (name === "NotFoundError" || name === "OverconstrainedError") return words.missing;
  if (name === "NotReadableError") return words.busy;
  return e instanceof Error ? e.message : words.failed;
}

/** The parts of `localStorage` a recorder uses. */
export type KeyValueStore = Pick<Storage, "getItem" | "setItem">;

/** A remembered value, or null. Storage can be refused (a private window, a sandboxed frame), even just reading `localStorage`:
 * then nothing is remembered, and nothing breaks. */
export function readStored(store: () => KeyValueStore, key: string): string | null {
  try {
    return store().getItem(key);
  } catch {
    return null;
  }
}

/** Remember a value, when the browser lets the page. */
export function writeStored(store: () => KeyValueStore, key: string, value: string): void {
  try {
    store().setItem(key, value);
  } catch {
    /* not remembered: the next visit starts from the default */
  }
}

/** What a recorder answers to: the facts it kept for a file it made. */
export type FactsSource = { metadataOf?: (f: File) => Record<string, unknown> | null } | null | undefined;

/** The recording facts of a file from whichever recorder on the page made it; null for a file picked from disk. */
export function recordingFactsOf(file: File, recorders: ReadonlyArray<FactsSource>): Record<string, unknown> | null {
  for (const recorder of recorders) {
    const facts = recorder?.metadataOf?.(file);
    if (facts) return facts;
  }
  return null;
}

/** One file going up as an asset (`POST /api/platform/assets/upload`): a take as a picked file, with its recording facts as metadata. */
export interface AssetUpload {
  file: File;
  slug: string;
  name: string;
  altText?: string;
  description?: string;
  metadata?: Record<string, unknown> | null;
}

/** The form fields of an asset upload, in order; empty texts and no metadata are left out rather than sent blank. */
export function uploadFields(upload: AssetUpload): [string, string | File][] {
  const fields: [string, string | File][] = [
    ["file", upload.file],
    ["slug", upload.slug],
    ["name", upload.name],
  ];
  const alt = upload.altText?.trim();
  const description = upload.description?.trim();
  if (alt) fields.push(["alt_text", alt]);
  if (description) fields.push(["description", description]);
  if (upload.metadata) fields.push(["metadata", JSON.stringify(upload.metadata)]);
  return fields;
}
