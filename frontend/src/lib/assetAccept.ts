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
