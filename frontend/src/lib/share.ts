/**
 * Share to Marvin: what the Share page (pages/share.astro) makes of a share the service worker kept
 * (src/pwa/sw-logic.js, in the SHARE_CACHE) — the uploads' names and slugs, and the entry or link resource it
 * drafts. Pure; the page does the reading, the uploads (the normal asset upload) and the creates.
 */

export const SHARE_CACHE = "marvin-share";

export interface SharedFile {
  name: string;
  type: string;
  size: number;
}

export interface Share {
  title: string;
  text: string;
  url: string | null;
  files: SharedFile[];
  dropped: number;
  createdAt: number;
}

const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isShareId(id: unknown): id is string {
  return typeof id === "string" && ID.test(id);
}

/** Where a share's parts live in the cache (the worker's shareKeys). */
export function shareKeys(id: string, origin: string) {
  return { meta: `${origin}/__share/${id}/meta.json`, file: (i: number) => `${origin}/__share/${id}/file-${i}` };
}

const str = (value: unknown, max: number) => (typeof value === "string" ? value.slice(0, max) : "");

/** An http(s) URL, or null. */
export function httpUrl(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const url = new URL(value.trim());
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

/** The worker's record of a share, checked again here (it is only ever shown as text and plain links). */
export function readShare(raw: unknown): Share | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const files = Array.isArray(r.files) ? r.files : [];
  return {
    title: str(r.title, 300),
    text: str(r.text, 5000),
    url: httpUrl(r.url),
    files: files
      .filter((f): f is Record<string, unknown> => Boolean(f) && typeof f === "object")
      .map((f) => ({ name: str(f.name, 255) || "shared-file", type: str(f.type, 100), size: Number(f.size) || 0 })),
    dropped: Math.max(0, Number(r.dropped) || 0),
    createdAt: Number(r.createdAt) || 0,
  };
}

export type FileKind = "image" | "video" | "pdf" | "file";

export function fileKind(type: string): FileKind {
  if (type.startsWith("image/")) return "image";
  if (type.startsWith("video/")) return "video";
  if (type === "application/pdf") return "pdf";
  return "file";
}

function stem(filename: string): string {
  const base = filename.split(/[\\/]/).pop() ?? "";
  const dot = base.lastIndexOf(".");
  return (dot > 0 ? base.slice(0, dot) : base).trim();
}

export function slugify(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60)
    .replace(/-+$/, "");
}

/** An asset's display name: its file name without the extension ("IMG_2041.jpg" → "IMG_2041"). */
export function assetName(filename: string): string {
  return stem(filename).slice(0, 200) || "Shared file";
}

/** A slug for an upload, unique enough with the caller's random suffix (asset slugs are unique per workspace). */
export function assetSlug(filename: string, suffix: string): string {
  return `${slugify(stem(filename)) || "shared"}-${suffix}`;
}

const BODY_KEYS = ["body", "content", "notes", "note", "text", "description"];
const LONG_TEXT = ["markdown", "textarea", "richtext"];

/** The entry type's field the shared text goes into: a body/content/notes field, else its first long-text one. */
export function bodyFieldOf(schemaJson: unknown): string | null {
  const fields = (schemaJson as { fields?: unknown } | null)?.fields;
  if (!Array.isArray(fields)) return null;
  const usable = fields.filter(
    (f): f is { key: string; type?: string } =>
      Boolean(f) && typeof f.key === "string" && (!f.type || ["text", ...LONG_TEXT].includes(String(f.type))),
  );
  for (const key of BODY_KEYS) {
    const hit = usable.find((f) => f.key.toLowerCase() === key);
    if (hit) return hit.key;
  }
  return usable.find((f) => LONG_TEXT.includes(String(f.type)))?.key ?? null;
}

/** The entry's title: the shared title, else the text's first line, else the link's site, else a stand-in. */
export function entryTitle(share: Pick<Share, "title" | "text" | "url">): string {
  const line =
    share.text
      .split(/\r?\n/)
      .find((l) => l.trim())
      ?.trim() ?? "";
  const host = share.url ? new URL(share.url).hostname.replace(/^www\./, "") : "";
  const title = share.title.trim() || (line && !httpUrl(line) ? line : "") || host || "Shared from another app";
  return title.length > 120 ? `${title.slice(0, 119)}…` : title;
}

/** The text for the body field: what was shared, with the link under it unless the text has it already. */
export function entryBody(share: Pick<Share, "text" | "url">): string {
  const text = share.text.trim();
  if (!share.url || text.includes(share.url) || text.includes(share.url.replace(/\/$/, ""))) return text;
  return text ? `${text}\n\n${share.url}` : share.url;
}

/** The draft entry "New entry with these" creates (camelCase, as the API takes it). */
export function entryDraft(share: Share, entryTypeId: string, bodyField: string | null, assetIds: string[]) {
  const body = entryBody(share);
  return {
    entryTypeId,
    title: entryTitle(share),
    status: "draft",
    ...(bodyField && body ? { dataJson: { [bodyField]: body } } : {}),
    ...(!bodyField && body ? { description: body.slice(0, 2000) } : {}),
    ...(assetIds.length ? { assetIds } : {}),
  };
}

/** The link resource "Add as resource" creates, or null without a link. */
export function resourceDraft(share: Share, suffix: string) {
  if (!share.url) return null;
  const name = entryTitle(share);
  const text = share.text.trim();
  return {
    name,
    slug: `${slugify(name) || "link"}-${suffix}`,
    resourceType: "link",
    url: share.url,
    ...(text && text !== share.url ? { description: text.slice(0, 2000) } : {}),
  };
}

/** "3 photos", "2 files" — what the page says it got. */
export function filesSummary(files: SharedFile[]): string {
  if (!files.length) return "";
  const kinds = new Set(files.map((f) => fileKind(f.type)));
  const word =
    kinds.size === 1 && kinds.has("image") ? "photo" : kinds.size === 1 && kinds.has("video") ? "video" : "file";
  return `${files.length} ${word}${files.length === 1 ? "" : "s"}`;
}
