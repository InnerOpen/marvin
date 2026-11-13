/**
 * What kind of file an upload asks for, read from its `accept`: MIME patterns ("audio/*", "image/png") or extensions (".mp3"), as the
 * input's comma-separated string or a list. A wizard's gallery upload and upload step, and the drop zone's Record button, go by it.
 */

export type FileKind = "audio" | "image" | "file";

const EXTENSIONS: Record<Exclude<FileKind, "file">, RegExp> = {
  audio: /\.(mp3|wav|m4a|aac|ogg|oga|opus|weba|webm|flac)$/i,
  image: /\.(png|jpe?g|gif|webp|avif|svg|heic)$/i,
};

const partsOf = (accept: string | string[] | null | undefined): string[] =>
  (Array.isArray(accept) ? accept : String(accept ?? "").split(",")).map((p) => p.trim().toLowerCase()).filter(Boolean);

function partKind(part: string): FileKind {
  for (const kind of ["audio", "image"] as const) {
    if (part.startsWith(`${kind}/`) || (part.startsWith(".") && EXTENSIONS[kind].test(part))) return kind;
  }
  return "file";
}

/** The one kind every part of `accept` names; "file" when it is empty or mixed. */
export function acceptKind(accept: string | string[] | null | undefined): FileKind {
  const kinds = new Set(partsOf(accept).map(partKind));
  return kinds.size === 1 ? [...kinds][0] : "file";
}

/** Whether any part of `accept` takes a sound (so a recording can stand in for a picked file). */
export function acceptsAudio(accept: string | string[] | null | undefined): boolean {
  return partsOf(accept).some((p) => partKind(p) === "audio");
}

/** Whether a file is of a kind: by its type, or by its name when the browser gave a vague type (a .webm sound reads as video/webm). */
export function isKind(file: { type?: string; name?: string }, kind: FileKind): boolean {
  if (kind === "file") return true;
  return (file.type ?? "").startsWith(`${kind}/`) || EXTENSIONS[kind].test(file.name ?? "");
}

/** Whether an asset already in the library is of a kind: by its type, or by the ending of its name or of its file's address (an upload
 *  kept under a typed name has no ending of its own, and a recorded .webm reads as video/webm). */
export function assetIsKind(asset: { mimeType?: string | null; name?: string | null; publicUrl?: string | null }, kind: FileKind): boolean {
  const path = String(asset.publicUrl ?? "").split(/[?#]/)[0];
  return isKind({ type: asset.mimeType ?? "", name: asset.name ?? "" }, kind) || isKind({ name: path }, kind);
}
