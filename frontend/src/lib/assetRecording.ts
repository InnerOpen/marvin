// What an asset's page says about a recording besides the file itself: its Transcript (an entry of type `transcript` whose `source`
// names the recording: its id, or its slug in the older ones) and the facts kept in its metadata — `video` (what describe-video measured:
// {duration_seconds, width, height, fps, has_audio}), `audio` when something writes one (shown as whatever it holds) and `recording`
// (what the browser's recorders kept: device, microphone settings, peak, clipped). Pure, so `npm test` covers it (assetRecording.test.mjs).

type Meta = Record<string, unknown> | null | undefined;

/** The entries query (POST /api/platform/entries/query) for the Transcripts of this recording, newest first. */
export function transcriptQuery(asset: { id: string; slug?: string | null }): { spec: Record<string, unknown>; limit: number } {
  const names = [asset.id, asset.slug].filter((v): v is string => typeof v === "string" && v.trim() !== "");
  return { spec: { entry_type: "transcript", where: [{ field: "source", op: "in", value: names }] }, limit: 5 };
}

export interface TranscriptRef {
  id: string;
  title: string;
  language: string | null;
  seconds: number | null;
  /** the asset (id or slug) holding the words in paragraphs, and the one with a time per phrase */
  paragraphs: string | null;
  timestamped: string | null;
}

const text = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);

/** A number, or number-like text ("83.4"); null for anything else. */
export function numberOf(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v !== "string" || !v.trim()) return null;
  const n = Number(v.trim());
  return Number.isFinite(n) ? n : null;
}

/** A Transcript entry (as the query returns it) as what the page shows; null when it has neither text file to show or download. */
export function transcriptOf(entry: { id?: string; title?: string | null; dataJson?: Record<string, unknown> | null } | null | undefined): TranscriptRef | null {
  if (!entry?.id) return null;
  const data = entry.dataJson ?? {};
  const paragraphs = text(data.paragraphs);
  const timestamped = text(data.timestamped);
  if (!paragraphs && !timestamped) return null;
  return { id: entry.id, title: text(entry.title) ?? "Transcript", language: text(data.language), seconds: numberOf(data.duration_seconds), paragraphs, timestamped };
}

/** The one of `assets` a field names, by id or by slug. */
export function assetNamed<T extends { id: string; slug?: string | null }>(assets: readonly T[], ref: string | null): T | null {
  return ref ? (assets.find((a) => a.id === ref || a.slug === ref) ?? null) : null;
}

/** A length as a clock: 7 → "0:07", 83.4 → "1:23", 3725 → "1:02:05". */
export function formatLength(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

/** A language code as its English name ("en" → "English"); anything that is not a code stays as it is. */
export function languageName(code: string): string {
  try {
    const name = new Intl.DisplayNames(["en"], { type: "language", fallback: "none" }).of(code);
    return name ?? code;
  } catch {
    return code;
  }
}

/** Long text as what is shown at first and the rest behind "Show more": cut at a paragraph's end when one falls in the second half
 * of `limit`, else at a space, so a word is never split. Short text is all head. */
export function splitForMore(body: string, limit = 700): { head: string; rest: string } {
  const trimmed = body.trim();
  if (trimmed.length <= limit) return { head: trimmed, rest: "" };
  const window = trimmed.slice(0, limit);
  const paragraph = window.lastIndexOf("\n\n");
  const space = window.search(/\s\S*$/);
  const cut = paragraph >= limit / 2 ? paragraph : space > 0 ? space : limit;
  return { head: trimmed.slice(0, cut).trimEnd(), rest: trimmed.slice(cut).trimStart() };
}

const obj = (v: unknown): Record<string, unknown> | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null);
const round = (n: number, places = 1) => Number(n.toFixed(places)).toString();
const humanKey = (k: string) => k.replace(/_/g, " ");

/** "48 kHz", "mono"/"stereo"/"6 channels". */
function rate(v: unknown): string | null {
  const n = numberOf(v);
  return n ? `${round(n / 1000)} kHz` : null;
}
function channels(v: unknown): string | null {
  const n = numberOf(v);
  return n === 1 ? "mono" : n === 2 ? "stereo" : n ? `${n} channels` : null;
}
function size(w: unknown, h: unknown): string | null {
  const [a, b] = [numberOf(w), numberOf(h)];
  return a && b ? `${a} × ${b}` : null;
}
function fps(v: unknown): string | null {
  const n = numberOf(v);
  return n ? `${round(n, 2)} fps` : null;
}
function length(v: unknown): string | null {
  const n = numberOf(v);
  return n !== null && n > 0 ? formatLength(n) : null;
}
/** Any other plain value, as "key value" (true/false as yes/no); objects and lists are left to the metadata list below. */
function plain(key: string, v: unknown): string | null {
  if (v === null || v === undefined || v === "" || typeof v === "object") return null;
  return `${humanKey(key)} ${typeof v === "boolean" ? (v ? "yes" : "no") : String(v)}`;
}

const VIDEO_KEYS = new Set(["duration_seconds", "width", "height", "fps", "has_audio"]);
const AUDIO_KNOWN = new Set(["duration_seconds", "seconds", "sample_rate", "channels"]);

/** describe-video's facts: length, size, fps, sound or none, then any other plain value it holds. */
export function videoFacts(meta: Meta): string[] {
  const v = obj(meta?.video);
  if (!v) return [];
  const out = [length(v.duration_seconds), size(v.width, v.height), fps(v.fps)];
  if (typeof v.has_audio === "boolean") out.push(v.has_audio ? "with sound" : "no sound");
  for (const [k, value] of Object.entries(v)) if (!VIDEO_KEYS.has(k)) out.push(plain(k, value));
  return out.filter((s): s is string => Boolean(s));
}

/** An `audio` block, when one is there: its length, rate and channels read as such, anything else as it stands. */
export function audioFacts(meta: Meta): string[] {
  const a = obj(meta?.audio);
  if (!a) return [];
  const out = [length(a.duration_seconds ?? a.seconds), rate(a.sample_rate), channels(a.channels)];
  for (const [k, value] of Object.entries(a)) if (!AUDIO_KNOWN.has(k)) out.push(plain(k, value));
  return out.filter((s): s is string => Boolean(s));
}

const RECORDING_KEYS = new Set([
  ...["source", "kind", "mime", "device", "camera", "microphone", "width", "height", "frame_rate", "sample_rate", "channels"],
  ...["constraints", "gain", "duration_seconds", "peak_dbfs", "clipped", "stopped"],
]);
const CONSTRAINTS: [string, string][] = [
  ["echo_cancellation", "echo cancellation"],
  ["noise_suppression", "noise suppression"],
  ["auto_gain_control", "auto gain"],
];

/** What the browser's recorders kept under `recording` (the audio one names the `device`; the video one its `camera` and
 * `microphone`, the picture's size and frame rate, and the gain): where it came from, the devices, the microphone's settings as
 * the browser applied them, the length, the loudest moment and whether it clipped. Empty when there is no `recording`. */
export function recordingFacts(meta: Meta): string[] {
  const r = obj(meta?.recording);
  if (!r) return [];
  const out: (string | null)[] = [r.source === "browser" ? "recorded in the browser" : plain("source", r.source)];
  const device = text(r.device);
  if (device) out.push(`microphone ${device}`);
  const camera = text(r.camera);
  if (camera) out.push(`camera ${camera}`);
  const mic = text(r.microphone);
  if (mic) out.push(`microphone ${mic}`);
  out.push(size(r.width, r.height), fps(r.frame_rate), rate(r.sample_rate), channels(r.channels));
  const constraints = obj(r.constraints);
  if (constraints) {
    for (const [key, label] of CONSTRAINTS) if (typeof constraints[key] === "boolean") out.push(`${label} ${constraints[key] ? "on" : "off"}`);
  }
  const gain = numberOf(r.gain);
  if (gain !== null) out.push(`gain ${round(gain, 2)}`);
  out.push(length(r.duration_seconds));
  const peak = numberOf(r.peak_dbfs);
  if (peak !== null) out.push(`peak ${round(peak)} dBFS`);
  if (typeof r.clipped === "boolean") out.push(r.clipped ? "clipped" : "not clipped");
  if (r.stopped !== null && r.stopped !== undefined && r.stopped !== "") out.push(plain("stopped", r.stopped));
  for (const [k, value] of Object.entries(r)) if (!RECORDING_KEYS.has(k)) out.push(plain(k, value));
  return out.filter((s): s is string => Boolean(s));
}
