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

/** The words of an asset field's upload dialog for a kind of file: what it is called, the line under the title, and the line in the drop box. */
export function uploadWords(kind: AcceptKind, multiple: boolean, role: string | null): { noun: string; open: string; intro: string; drop: string } {
  // No role: the field is not an entry's own (a guided setup's file box), so nothing is attached on a save.
  const attached = role ? `It is uploaded now, chosen here, and attached as ${role} when you save.` : "It is uploaded to your assets now and chosen here.";
  if (kind === "audio") {
    return {
      noun: "sound",
      open: multiple ? "Upload or record sounds…" : "Upload or record a sound…",
      intro: `A new sound for this field: record one, or upload a file. ${attached}`,
      drop: multiple ? "Sounds; several at once, each becomes an asset." : "One sound.",
    };
  }
  if (kind === "image") {
    return {
      noun: "picture",
      open: multiple ? "Upload pictures…" : "Upload a picture…",
      intro: `A new picture for this field: it opens in the cropper first (crop, rotate, brightness, contrast). ${attached}`,
      drop: multiple ? "Pictures; several at once, each becomes an asset." : "One picture.",
    };
  }
  if (kind === "video") {
    return {
      noun: "video",
      open: multiple ? "Upload videos…" : "Upload a video…",
      intro: `A new video for this field. ${attached}`,
      drop: multiple ? "Videos; several at once, each becomes an asset." : "One video.",
    };
  }
  return {
    noun: "asset",
    open: multiple ? "Upload assets…" : "Upload an asset…",
    intro: `A new asset for this field: a picture opens in the cropper first (crop, rotate, brightness, contrast). ${attached}`,
    drop: multiple ? "Pictures, sounds, videos or documents; several at once, each becomes an asset." : "One picture, sound, video or document.",
  };
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
