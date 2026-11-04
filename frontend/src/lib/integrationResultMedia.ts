// Audio and pictures in an integration action's result, for the Run action panel: a result such as ElevenLabs'
// `synthesize` carries the sound as base64 inside JSON, which is no use to read. These helpers find the media so the panel
// can play or show it and offer "Save as asset", and give back the JSON with the bytes replaced by a short note.
// The shapes are the ones the workflow executor keeps (services/automation/actions/media.py): `audio_b64` (+ `mime`),
// `images: [{image_b64}]` and a top-level `image_b64`.

export interface ResultMedia {
  kind: "audio" | "image";
  mime: string;
  base64: string;
  /** What the result says about how it was made (voice, model, duration...), kept on the saved asset. */
  details: Record<string, unknown>;
}

const DEFAULT_AUDIO_MIME = "audio/mpeg";
const KEPT_DETAILS = ["duration_seconds", "characters", "voice_id", "model"] as const;
const EXTENSIONS: Record<string, string> = {
  "audio/mpeg": "mp3",
  "audio/mp3": "mp3",
  "audio/wav": "wav",
  "audio/ogg": "ogg",
  "audio/flac": "flac",
  "audio/aac": "aac",
  "audio/webm": "webm",
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/webp": "webp",
};

const isText = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);

/** The picture's type from its first bytes: a result carries no mime for images. */
export function sniffImageMime(base64: string): string {
  if (base64.startsWith("/9j/")) return "image/jpeg";
  if (base64.startsWith("UklGR")) return "image/webp";
  return "image/png";
}

function audioMime(raw: unknown): string {
  const mime = isText(raw) ? raw.split(";")[0].trim().toLowerCase() : "";
  return mime.startsWith("audio/") ? mime : DEFAULT_AUDIO_MIME;
}

function detailsOf(result: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(KEPT_DETAILS.filter((k) => result[k] != null).map((k) => [k, result[k]]));
}

/** Every playable or showable item in a result, in the order a person would read them. */
export function mediaIn(result: unknown): ResultMedia[] {
  if (!isRecord(result)) return [];
  const found: ResultMedia[] = [];
  if (isText(result.audio_b64)) {
    found.push({ kind: "audio", mime: audioMime(result.mime), base64: result.audio_b64, details: detailsOf(result) });
  }
  const pictures = [...(Array.isArray(result.images) ? result.images : []), result];
  for (const item of pictures) {
    if (isRecord(item) && isText(item.image_b64)) {
      found.push({ kind: "image", mime: sniffImageMime(item.image_b64), base64: item.image_b64, details: {} });
    }
  }
  return found;
}

const sizeNote = (base64: string) => `(${Math.max(1, Math.round((base64.length * 3) / 4 / 1024))} KB, shown above)`;

/** The result as JSON text with each media payload swapped for its size, so the panel doesn't print megabytes of base64. */
export function withoutMediaBytes(result: unknown): unknown {
  if (Array.isArray(result)) return result.map(withoutMediaBytes);
  if (!isRecord(result)) return result;
  return Object.fromEntries(
    Object.entries(result).map(([key, value]) => [
      key,
      (key === "audio_b64" || key === "image_b64") && isText(value) ? sizeNote(value) : withoutMediaBytes(value),
    ]),
  );
}

export function mediaExtension(mime: string): string {
  return EXTENSIONS[mime] ?? mime.split("/")[1] ?? "bin";
}

/** The browser-side file for an upload, from the base64 a result carries. */
export function mediaFile(item: ResultMedia, baseName: string): File {
  const bytes = Uint8Array.from(atob(item.base64), (c) => c.charCodeAt(0));
  return new File([bytes], `${baseName}.${mediaExtension(item.mime)}`, { type: item.mime });
}

/** A URL-safe asset slug from an action's name: lowercase words joined by dashes, then a short random tail so two takes never collide. */
export function assetSlug(label: string, tail: string): string {
  const words = label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return `${words || "result"}-${tail}`;
}
