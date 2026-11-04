// What an entry's media slot shows in a list or card: its picture, or, when the asset it leads with is a recording, a play button.
// The slot used to take the first asset's URL as an <img> whatever the asset was, so a voice line got a broken picture.

export interface EntryThumb {
  kind: "image" | "audio";
  url: string;
  alt: string;
  focalPoint?: string | null;
}

interface PlacedAsset {
  role?: string | null;
  publicUrl?: string | null;
  mimeType?: string | null;
  altText?: string | null;
  focalPoint?: string | null;
}

/**
 * The asset an entry leads with: its featured or hero one (a picture the author chose), else its latest take (a recording is
 * attached each time it is made again, so the last "audio" one is the current take), else the first.
 */
export function leadAsset<T extends PlacedAsset>(assets: T[] | null | undefined): T | undefined {
  const chosen = assets?.find((a) => a.role === "featured" || a.role === "hero");
  if (chosen) return chosen;
  const takes = assets?.filter((a) => a.role === "audio") ?? [];
  return takes.length ? takes[takes.length - 1] : assets?.[0];
}

/**
 * A recording that rides along with a picture: an actor's voice sample sits beside the actor's picture, which leads, so the picture
 * would hide it. The first audio asset, when the entry's lead is a picture; null when the lead is itself the recording (the slot
 * already plays that) or the entry has none.
 */
export function extraSound(assets: PlacedAsset[] | null | undefined, title: string): EntryThumb | null {
  if (!thumbOf(assets, title) || thumbOf(assets, title)?.kind === "audio") return null;
  const sound = assets?.find((a) => (a.mimeType ?? "").toLowerCase().startsWith("audio/") && a.publicUrl);
  return sound ? { kind: "audio", url: sound.publicUrl as string, alt: sound.altText ?? title, focalPoint: null } : null;
}

export function thumbOf(assets: PlacedAsset[] | null | undefined, title: string): EntryThumb | null {
  const asset = leadAsset(assets);
  if (!asset?.publicUrl) return null;
  const kind = (asset.mimeType ?? "").toLowerCase().startsWith("audio/") ? "audio" : "image";
  return { kind, url: asset.publicUrl, alt: asset.altText ?? title, focalPoint: asset.focalPoint };
}
