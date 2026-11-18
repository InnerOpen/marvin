// The pure parts of the video recorder (components/VideoRecorder.astro): which format to ask MediaRecorder for, how hard to
// squeeze the take so ten minutes still fit one upload, when a take stops itself, what to name the file and the facts kept
// with it. What it shares with the audio recorder is in lib/recording.ts. Pure, so node can test them.

import { type DeviceWords, containerOf, safeBaseName } from "./recording.ts";
import { UPLOAD_LIMIT_BYTES } from "./uploadLimit.ts";

/** Asked for in this order: MP4 where the browser makes it (Safari, recent Chrome), which plays everywhere; else WebM, VP9
 * before VP8 (smaller at the same look). A bare `video/webm` lets an older browser choose its own codecs. */
export const VIDEO_MIME_CANDIDATES = [
  "video/mp4",
  "video/webm;codecs=vp9,opus",
  "video/webm;codecs=vp8,opus",
  "video/webm",
];

/** The longest take: ten minutes, then it stops itself. */
export const MAX_VIDEO_SECONDS = 600;
/** Asked of the recorder so a ten-minute take (about 85 MB) stays under what one upload carries. A browser treats it as a
 * target, not a promise, so the size is watched too (`stopReason`). */
export const VIDEO_BITS_PER_SECOND = 1_000_000;
export const AUDIO_BITS_PER_SECOND = 128_000;
/** A take stops itself at this share of the upload limit, leaving room for the last chunk and the form's other fields. */
export const SIZE_GUARD = 0.95;
/** What the camera is asked for: 720p at 30 frames, which the bitrate above carries well. It is a wish; the camera gives what it has. */
export const IDEAL_WIDTH = 1280;
export const IDEAL_HEIGHT = 720;
export const IDEAL_FRAME_RATE = 30;
/** Seconds counted down before a take starts, when the person asks for a count-down. */
export const COUNTDOWN_SECONDS = 3;

const BITS_PER_BYTE = 8;
const EXTENSION_OF: Record<string, string> = { mp4: "mp4", webm: "webm" };
/** For a type the browser didn't name: WebM is what Chrome and Firefox make by default. */
const FALLBACK_CONTAINER = "webm";

/** The first candidate the browser says it can record, or "" to let it choose. */
export function pickVideoMimeType(isSupported: (type: string) => boolean): string {
  return VIDEO_MIME_CANDIDATES.find((type) => isSupported(type)) ?? "";
}

/** The size a take of `seconds` comes to at the bitrates asked for. */
export function expectedBytes(
  seconds: number,
  videoBps = VIDEO_BITS_PER_SECOND,
  audioBps = AUDIO_BITS_PER_SECOND,
): number {
  return Math.ceil(((videoBps + audioBps) * seconds) / BITS_PER_BYTE);
}

/** Why a running take must stop by itself now, or null to keep going: it has run the longest a take may, or it is about to be
 * too big to upload. */
export function stopReason(
  elapsedSeconds: number,
  bytes: number,
  limits: { maxSeconds?: number; maxBytes?: number } = {},
): "time" | "size" | null {
  const maxSeconds = limits.maxSeconds ?? MAX_VIDEO_SECONDS;
  const maxBytes = limits.maxBytes ?? Math.floor(UPLOAD_LIMIT_BYTES * SIZE_GUARD);
  if (elapsedSeconds >= maxSeconds) return "time";
  if (bytes >= maxBytes) return "size";
  return null;
}

/** What the dialog says when a take stopped by itself. */
export function stoppedWords(reason: "time" | "size" | null, maxSeconds = MAX_VIDEO_SECONDS): string {
  if (reason === "time") return `It stopped at ${Math.round(maxSeconds / 60)} minutes, the longest a take can be. `;
  if (reason === "size") return "It stopped because it was about as big as one upload can carry. ";
  return "";
}

/** The numbers shown in turn before a take starts: 3, 2, 1. */
export function countdownFrom(seconds = COUNTDOWN_SECONDS): number[] {
  const whole = Math.max(0, Math.floor(seconds));
  return Array.from({ length: whole }, (_, i) => whole - i);
}

/** The take as a named File: `video/mp4` as `.mp4`, else `video/webm` as `.webm`, without the codecs (the server goes by the
 * part's type and the name's ending). */
export function videoFileFor(blob: Blob, mimeType: string, baseName: string): File {
  const found = containerOf(mimeType || blob.type);
  const container = EXTENSION_OF[found] ? found : FALLBACK_CONTAINER;
  return new File([blob], `${safeBaseName(baseName)}.${EXTENSION_OF[container]}`, { type: `video/${container}` });
}

/** The camera and microphone picked. A device remembered from an earlier visit is asked for as `ideal`: its id may be stale (a
 * browser can rotate them, the camera may be unplugged), and `exact` would then fail as if there were no camera at all. One
 * picked just now is `exact`, so a camera that can't open says so instead of quietly giving another. */
export function videoConstraints(choice: {
  cameraId?: string;
  microphoneId?: string;
  remembered?: boolean;
}): MediaStreamConstraints {
  const want = (id?: string) => (id ? { deviceId: choice.remembered ? { ideal: id } : { exact: id } } : {});
  return {
    video: {
      ...want(choice.cameraId),
      width: { ideal: IDEAL_WIDTH },
      height: { ideal: IDEAL_HEIGHT },
      frameRate: { ideal: IDEAL_FRAME_RATE },
    },
    audio: { ...want(choice.microphoneId) },
  };
}

/** The devices kept between visits. */
export interface DeviceChoice {
  cameraId: string;
  microphoneId: string;
  countdown: boolean;
}

/** A remembered choice (text from storage), or the defaults when there is none or it is not ours. */
export function parseDeviceChoice(stored: string | null | undefined): DeviceChoice {
  const none: DeviceChoice = { cameraId: "", microphoneId: "", countdown: false };
  if (!stored) return none;
  try {
    const raw = JSON.parse(stored) as Partial<Record<keyof DeviceChoice, unknown>>;
    return {
      cameraId: typeof raw?.cameraId === "string" ? raw.cameraId : "",
      microphoneId: typeof raw?.microphoneId === "string" ? raw.microphoneId : "",
      countdown: raw?.countdown === true,
    };
  } catch {
    return none;
  }
}

/** What the dialog says when the camera or its microphone would not open. */
export const CAMERA_WORDS: DeviceWords = {
  refused:
    "The camera or microphone was refused. Allow the camera for this site (and its microphone) in the browser's settings, then try again.",
  missing: "No camera or microphone was found. Plug one in, or pick another, then try again.",
  busy: "The camera or microphone is busy with another app (a call, another tab). Close it, then try again.",
  failed: "The camera could not be opened.",
};

/** What the camera and microphone gave (MediaStreamTrack.getSettings() and labels) and the format recorded. */
export interface VideoSettings {
  mimeType: string;
  camera?: string;
  microphone?: string;
  width?: number;
  height?: number;
  frameRate?: number;
}

const round1 = (n: number) => Math.round(n * 10) / 10;

/** The facts kept in the asset's metadata, under `recording` (snake_case, like the audio recorder's). */
export function videoRecordingMetadata(
  settings: VideoSettings,
  stats: { durationSeconds: number; stopped?: "time" | "size" | null },
): { recording: Record<string, unknown> } {
  return {
    recording: {
      source: "browser",
      kind: "video",
      mime: settings.mimeType,
      camera: settings.camera || null,
      microphone: settings.microphone || null,
      width: settings.width ?? null,
      height: settings.height ?? null,
      frame_rate: settings.frameRate ? round1(settings.frameRate) : null,
      duration_seconds: round1(stats.durationSeconds),
      stopped: stats.stopped ?? null,
    },
  };
}
