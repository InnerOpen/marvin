// The share links a workflow left on an entry (the One-tap share links recipe): `metadata_json.share_links`,
// {label: a network's composer URL}, and the post they carry (`share_text`). The entry page shows them as buttons.
// Metadata is free-form JSON anyone who can edit the entry may type, so only https and mailto links are kept.
// Pure, so it's tested with plain `node --test` (see shareLinks.test.mjs).

export interface ShareLink {
  label: string;
  href: string;
}

const SAFE = /^(https:\/\/|mailto:)/i;

export function shareLinks(metadata: unknown): { links: ShareLink[]; text: string | null } {
  const meta = metadata && typeof metadata === "object" && !Array.isArray(metadata) ? (metadata as Record<string, unknown>) : {};
  const raw = meta.share_links && typeof meta.share_links === "object" && !Array.isArray(meta.share_links) ? meta.share_links : {};
  const links = Object.entries(raw as Record<string, unknown>)
    .filter((pair): pair is [string, string] => typeof pair[1] === "string" && SAFE.test(pair[1]))
    .map(([label, href]) => ({ label, href }));
  const text = typeof meta.share_text === "string" && meta.share_text.trim() ? meta.share_text.trim() : null;
  return { links, text };
}
