// Which assets an asset field takes: its `accept`, written like a file input's (`application/pdf`, `audio/*`, `.pdf,.html`).
// Pure, so the field's picker script, its server render and the tests share it.

/** The tokens of an accept string, lowercased and trimmed; empty when the field takes anything. */
export function acceptTokens(accept: string | null | undefined): string[] {
  return String(accept ?? "").split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);
}

/** Whether an asset suits an `accept`: a `type/*` token matches the type, `type/sub` the exact type (parameters ignored), `.ext` the name's ending.
 *  Nothing accepted means everything fits. An asset with no known type fits only by its name's ending. */
export function matchesAccept(accept: string | null | undefined, asset: { mimeType?: string | null; name?: string | null }): boolean {
  const tokens = acceptTokens(accept);
  if (tokens.length === 0) return true;
  const mime = String(asset.mimeType ?? "").split(";")[0].trim().toLowerCase();
  const name = String(asset.name ?? "").trim().toLowerCase();
  return tokens.some((t) => {
    if (t.startsWith(".")) return name.endsWith(t);
    if (t.endsWith("/*")) return mime.startsWith(t.slice(0, -1));
    return mime === t;
  });
}

/** What a field's upload dialog lets the person pick: its own `accept`, else the usual kinds of file. */
export function uploadAccept(accept: string | null | undefined, fallback = "image/*,video/*,audio/*,.pdf,.doc,.docx,.svg"): string {
  return acceptTokens(accept).length ? acceptTokens(accept).join(",") : fallback;
}

/** What kind of file a field takes, from its `accept`: sounds only, pictures only, video only, or "any" (several kinds, documents, nothing said).
 *  The upload dialog words itself by it (a sound field is not a picture field). */
export type AcceptKind = "audio" | "image" | "video" | "any";

export function kindOfAccept(accept: string | null | undefined): AcceptKind {
  const families = new Set(acceptTokens(accept).map((t) => (t.startsWith(".") ? "any" : t.split("/")[0])));
  if (families.size !== 1) return "any";
  const only = [...families][0];
  return only === "audio" || only === "image" || only === "video" ? only : "any";
}

// ---- What an upload surface offers -------------------------------------------------------------------------------------------------
// Every place that takes a file (an asset field and its dialog, the Upload page, a guided drop zone) offers the same things, in the
// same order and words, decided only by what it accepts: upload, then Record audio…, then Record video….

/** The families of file an accept can name. A document is anything that is not a sound, a video or a picture (PDF, JSON, text…). */
export type FileFamily = "audio" | "video" | "image" | "document";
export type Recorder = "audio" | "video";

const AUDIO_EXTENSIONS = new Set([".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".weba", ".flac"]);
const VIDEO_EXTENSIONS = new Set([".mp4", ".m4v", ".mov", ".mkv", ".avi"]);
const IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".heic"]);
/** `.webm` holds sound or video: it goes with whichever of the two the rest of the accept names, else counts as both. */
const EITHER_EXTENSIONS = new Set([".webm"]);
const FAMILY_ORDER: FileFamily[] = ["audio", "video", "image", "document"];
const IMAGE_WORD = "images";
/** How a document type is named in a hint ("PDF files only"); a type not here is named as written. */
const DOCUMENT_NAMES: Record<string, string> = {
  "application/pdf": "PDF",
  ".pdf": "PDF",
  "application/json": "JSON",
  ".json": "JSON",
  "text/html": "HTML",
  ".html": "HTML",
  ".htm": "HTML",
  "text/*": "text",
  "text/plain": "text",
  ".txt": "text",
  "text/markdown": "Markdown",
  ".md": "Markdown",
  ".doc": "Word",
  ".docx": "Word",
  "application/msword": "Word",
};

function familyOf(token: string): FileFamily | "either" {
  for (const family of ["audio", "video", "image"] as const) if (token.startsWith(`${family}/`)) return family;
  if (EITHER_EXTENSIONS.has(token)) return "either";
  if (AUDIO_EXTENSIONS.has(token)) return "audio";
  if (VIDEO_EXTENSIONS.has(token)) return "video";
  if (IMAGE_EXTENSIONS.has(token)) return "image";
  return "document";
}

/** The families an accept names, in a fixed order; null when it takes anything (no accept). */
export function acceptFamilies(accept: string | null | undefined): FileFamily[] | null {
  const tokens = acceptTokens(accept);
  if (!tokens.length) return null;
  const found = new Set<FileFamily | "either">(tokens.map(familyOf));
  if (found.delete("either") && !found.has("audio") && !found.has("video")) {
    found.add("audio");
    found.add("video");
  }
  return FAMILY_ORDER.filter((f) => found.has(f));
}

/** What a place that takes files offers, from its accept alone. */
export interface UploadChoices {
  /** The upload button's words ("Upload an audio file"); a surface adds "…" where it opens a dialog. */
  upload: string;
  /** The line under "Click to upload or drag and drop": what goes here ("Audio files only", "Any file"). */
  hint: string;
  /** The recorders offered, audio before video. */
  record: Recorder[];
}

const UPLOAD_LABELS: Record<string, [string, string]> = {
  audio: ["Upload an audio file", "Upload audio files"],
  video: ["Upload a video", "Upload videos"],
  image: ["Upload an image", "Upload images"],
  any: ["Upload any file", "Upload files"],
  mixed: ["Upload a file", "Upload files"],
};

const capitalized = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const listed = (words: string[]) =>
  words.length < 2 ? (words[0] ?? "") : `${words.slice(0, -1).join(", ")} or ${words.at(-1)}`;

function hintFor(accept: string | null | undefined, families: FileFamily[] | null): string {
  if (!families) return "Any file";
  const documents = [
    ...new Set(
      acceptTokens(accept)
        .filter((t) => familyOf(t) === "document")
        .map((t) => DOCUMENT_NAMES[t] ?? t),
    ),
  ];
  // Kinds of file share one "files" ("audio or video files", "PDF or JSON files"); pictures are "images" ("images or video files").
  const fileKinds = [...(["audio", "video"] as const).filter((f) => families.includes(f)), ...documents];
  const parts = [
    ...(families.includes("image") ? [IMAGE_WORD] : []),
    ...(fileKinds.length ? [`${listed(fileKinds)} files`] : []),
  ];
  return `${capitalized(listed(parts))} only`;
}

/** What a place that accepts `accept` offers: its upload button, the hint under the drop zone and the recorders. `multiple`: it takes
 *  several files at once (an asset list, the Upload page's batch). */
export function uploadChoices(accept: string | null | undefined, multiple = false): UploadChoices {
  const families = acceptFamilies(accept);
  const single = families?.length === 1 && families[0] !== "document" ? families[0] : null;
  const labels = UPLOAD_LABELS[!families ? "any" : (single ?? "mixed")];
  const record: Recorder[] = !families
    ? ["audio", "video"]
    : (["audio", "video"] as const).filter((r) => families.includes(r));
  const hint = hintFor(accept, families);
  return { upload: labels[multiple ? 1 : 0], hint: multiple ? `${hint}; several at once` : hint, record };
}

/** The recorders' button words, the same on every surface. */
export const RECORD_LABELS: Record<Recorder, string> = { audio: "Record audio…", video: "Record video…" };
/** The drop zone's first line, the same on every surface. */
export const DROP_LINE = "Click to upload or drag and drop";

/** Whether a picked or dropped file suits the accept (a file input's accept doesn't stop a drop, nor "All files" in a picker). */
export function fileFits(accept: string | null | undefined, file: { name: string; type: string }): boolean {
  return matchesAccept(accept, { mimeType: file.type, name: file.name });
}

/** The one message for a file of the wrong type, the same everywhere: "clip.mov can't go here: audio files only." */
export function wrongFileMessage(accept: string | null | undefined, fileName: string): string {
  const hint = uploadChoices(accept).hint;
  const isAcronym = /^[A-Z]{2}/.test(hint); // "PDF files only" stays as it is; "Audio files only" reads "audio files only"
  return `${fileName} can't go here: ${isAcronym ? hint : `${hint.charAt(0).toLowerCase()}${hint.slice(1)}`}.`;
}

/** Whether a place could take a video recorded from the camera (its choices offer Record video…). */
export function acceptsVideo(accept: string | null | undefined): boolean {
  return uploadChoices(accept).record.includes("video");
}

/** Whether a place could take a sound recorded from the microphone (its choices offer Record audio…). */
export function recordsAudio(accept: string | null | undefined): boolean {
  return uploadChoices(accept).record.includes("audio");
}

/** The line under an asset field's upload dialog title, from its accept like everything else the dialog offers: what is new here, the
 *  ways in, the cropper for a picture, and what happens on a save (no role: a guided setup's file box, attached by nothing). */
export function uploadIntro(accept: string | null | undefined, role: string | null): string {
  const families = acceptFamilies(accept);
  const single = families?.length === 1 ? families[0] : null;
  const noun = single === "audio" ? "audio file" : single === "video" ? "video" : single === "image" ? "image" : "file";
  const ways = uploadChoices(accept).record.length ? "upload one, or record one" : "upload one";
  const cropper =
    !families || families.includes("image")
      ? " An image opens in the cropper first (crop, rotate, brightness, contrast)."
      : "";
  const attached = role
    ? `It is uploaded now, chosen here, and attached as ${role} when you save.`
    : "It is uploaded to your assets now and chosen here.";
  return `A new ${noun} for this field: ${ways}.${cropper} ${attached}`;
}

/** The choices the schema editor offers for a field's `accept` (label, accept string). */
export const ACCEPT_PRESETS: { label: string; accept: string }[] = [
  { label: "Anything", accept: "" },
  { label: "Pictures", accept: "image/*" },
  { label: "Sounds", accept: "audio/*" },
  { label: "Video", accept: "video/*" },
  { label: "PDF", accept: "application/pdf" },
  { label: "Web page (HTML)", accept: "text/html,.html" },
  { label: "Text or Fountain", accept: "text/*,.fountain,.md,.txt" },
];
