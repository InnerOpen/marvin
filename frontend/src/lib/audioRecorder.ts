// The pure parts of the audio recorder (components/AudioRecorder.astro): which format to ask MediaRecorder for, what to
// name the file it makes, the facts kept with a take, and the level meter's sums. Pure, so node can test them. What it shares with
// the video recorder (the take's name and clock, the device list, the upload) is in lib/recording.ts.

import { type DeviceWords, containerOf, safeBaseName } from "./recording.ts";

export { TRUNCATION_TOLERANCE_SECONDS, containerOf, formatClock, looksTruncated, stampedName } from "./recording.ts";

/** Asked for in this order. WebM/Opus first: Chrome, Firefox and Safari 18.4+ make it, and Safari 26.0–26.1 cut MP4
 * recordings short (WebKit 299164). MP4/AAC is what older Safari makes; Ogg/Opus covers Firefox builds without WebM. */
export const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/mp4;codecs=mp4a.40.2", "audio/mp4", "audio/ogg;codecs=opus"];

/** The containers a recorder makes, under the names browsers give them. */
const CONTAINER_OF: Record<string, string> = { webm: "webm", mp4: "mp4", ogg: "ogg", wav: "wav", wave: "wav", "x-wav": "wav" };
/** The file extension for each container. MP4 sound is `.m4a`: the server files `.mp4` as a video. */
const EXTENSION_OF: Record<string, string> = { webm: "webm", mp4: "m4a", ogg: "ogg", wav: "wav" };
/** For a type the browser didn't name: WebM is what every MediaRecorder but an old Safari's makes by default. */
const FALLBACK_CONTAINER = "webm";

/** A sample at or past this (of full scale, 1.0) counts as clipped: the converter has run out of room. */
export const CLIP_LEVEL = 0.99;

/** The first candidate the browser says it can record, or "" to let it choose. */
export function pickMimeType(isSupported: (type: string) => boolean): string {
  return MIME_CANDIDATES.find((type) => isSupported(type)) ?? "";
}

/** The recording as a named File. Its type is always `audio/<container>` without the codecs, whatever the browser said
 * (Firefox can call a sound-only take `video/webm`): the server takes that part type for a `.webm` (services/assets). */
export function fileFor(blob: Blob, mimeType: string, baseName: string): File {
  const container = CONTAINER_OF[containerOf(mimeType || blob.type)] ?? FALLBACK_CONTAINER;
  return new File([blob], `${safeBaseName(baseName)}.${EXTENSION_OF[container]}`, { type: `audio/${container}` });
}

export interface Level {
  /** The largest sample, 0 to 1 (can pass 1). */
  peak: number;
  /** Root mean square, 0 to 1: how loud it sounds, rather than its tallest spike. */
  rms: number;
  clipped: boolean;
}

/** Peak, RMS and clipping of one analyser frame (AnalyserNode.getFloatTimeDomainData). */
export function levelOf(samples: ArrayLike<number>): Level {
  let peak = 0;
  let sumOfSquares = 0;
  for (let i = 0; i < samples.length; i++) {
    const s = samples[i];
    peak = Math.max(peak, Math.abs(s));
    sumOfSquares += s * s;
  }
  const rms = samples.length ? Math.sqrt(sumOfSquares / samples.length) : 0;
  return { peak, rms, clipped: peak >= CLIP_LEVEL };
}

/** A level in decibels below full scale, to one decimal; null for silence (minus infinity has no JSON). */
export function toDbfs(level: number): number | null {
  if (!(level > 0)) return null;
  return Math.round(20 * Math.log10(level) * 10) / 10;
}

/** The quietest level the meter shows; below it the bar is empty. */
export const METER_FLOOR_DB = -60;

/** Where a level sits on the meter, 0 to 1, on a decibel scale (a linear bar would hide everything but shouting). */
export function meterPosition(level: number, floorDb: number = METER_FLOOR_DB): number {
  const db = toDbfs(level);
  if (db === null) return 0;
  return Math.min(1, Math.max(0, (db - floorDb) / -floorDb));
}

/** Pause can be trusted except in WebKit, where it leaves stray or huge chunks and lets sound through (WebKit 243837,
 * 279432). Every iOS browser is WebKit. */
export function canPauseReliably(userAgent: string): boolean {
  if (/iPhone|iPad|iPod/.test(userAgent)) return false;
  const isSafari = /Safari\//.test(userAgent) && !/Chrome\/|Chromium\/|Edg\/|Firefox\/|OPR\//.test(userAgent);
  return !isSafari;
}

/** What a microphone gave (MediaStreamTrack.getSettings()): the video recorder keeps the same facts of its microphone. */
export interface MicrophoneSettings {
  sampleRate?: number;
  channelCount?: number;
  echoCancellation?: boolean;
  noiseSuppression?: boolean;
  autoGainControl?: boolean;
}

/** What the microphone gave, plus the device's label, and the format recorded. */
export interface RecordingSettings extends MicrophoneSettings {
  mimeType: string;
  deviceLabel?: string;
}

/** What the take came to: its length (decoded when the browser could, else the dialog's clock) and loudest moment. */
export interface RecordingStats {
  durationSeconds: number;
  peak: number;
  clipped: boolean;
}

const round1 = (n: number) => Math.round(n * 10) / 10;

/** A microphone's facts as kept under `recording`, by either recorder. The constraints are what the browser applied, not what
 * was asked: it may ignore a request. */
export function microphoneFacts(settings: MicrophoneSettings): Record<string, unknown> {
  return {
    sample_rate: settings.sampleRate ?? null,
    channels: settings.channelCount ?? null,
    constraints: {
      echo_cancellation: settings.echoCancellation ?? null,
      noise_suppression: settings.noiseSuppression ?? null,
      auto_gain_control: settings.autoGainControl ?? null,
    },
  };
}

/** The facts kept in the asset's metadata, under `recording` (snake_case, like the rest of an asset's metadata). */
export function recordingMetadata(settings: RecordingSettings, stats: RecordingStats): { recording: Record<string, unknown> } {
  return {
    recording: {
      source: "browser",
      mime: settings.mimeType,
      device: settings.deviceLabel || null,
      ...microphoneFacts(settings),
      duration_seconds: round1(stats.durationSeconds),
      peak_dbfs: toDbfs(stats.peak),
      clipped: stats.clipped,
    },
  };
}

/** What the dialog says when the microphone would not open. */
export const MICROPHONE_WORDS: DeviceWords = {
  refused: "The microphone was refused. Allow it for this site in the browser's settings, then try again.",
  missing: "No microphone was found. Plug one in, or pick another, then try again.",
  busy: "The microphone is busy with another app. Close it, then try again.",
  failed: "The microphone could not be opened.",
};

/** One card of the script the recorder shows to read from: a label ("Words") and the text. */
export interface CueCard {
  label: string;
  text: string;
}

/** The most cards the recorder shows, and the longest text on one: it is for reading aloud, not for a whole chapter. */
export const MAX_CUE_CARDS = 3;
export const MAX_CUE_CHARS = 4000;

/** The cards to show: those with text, trimmed and in order, at most `MAX_CUE_CARDS`; a card with nothing to read is left out, not shown empty. */
export function cueCards(raw: ReadonlyArray<{ label?: string | null; text?: string | null }> | null | undefined): CueCard[] {
  return (raw ?? [])
    .map((c) => ({ label: (c.label ?? "").trim(), text: (c.text ?? "").trim().slice(0, MAX_CUE_CHARS) }))
    .filter((c) => c.text)
    .slice(0, MAX_CUE_CARDS);
}

/** The sizes of the text to read from, as a factor of the default; the person steps through them with A- and A+ and the choice is kept. */
export const CUE_SCALES = [0.8, 1, 1.25, 1.6, 2, 2.5] as const;

/** The scale after a step up (1) or down (-1), kept within `CUE_SCALES`. */
export function stepCueScale(current: number, direction: 1 | -1): number {
  const at = CUE_SCALES.reduce((best, scale, i) => (Math.abs(scale - current) < Math.abs(CUE_SCALES[best] - current) ? i : best), 0);
  return CUE_SCALES[Math.min(CUE_SCALES.length - 1, Math.max(0, at + direction))];
}

/** A remembered scale (text from storage), or the default when there is none or it is not one of the sizes. */
export function storedCueScale(value: string | null | undefined): number {
  const found = CUE_SCALES.find((scale) => String(scale) === String(value));
  return found ?? 1;
}

