// What an entry's media slot shows in a list or card: its picture, or, when the asset it leads with is a recording, a play button, or,
// when it is a video, the video small, played where it is (InlineVideo.astro).
// The slot used to take the first asset's URL as an <img> whatever the asset was, so a voice line got a broken picture, and so did a
// transcript (a text file) or a JSON or PDF file: only a picture is drawn as one.

import { isVideoAsset, videoPosterOf } from "./videoAsset.ts";

export interface EntryThumb {
  kind: "image" | "audio" | "video";
  url: string;
  alt: string;
  focalPoint?: string | null;
  /** A video's still before it plays, when its metadata names one (videoAsset.ts). */
  poster?: string | null;
}

interface PlacedAsset {
  id?: string | null;
  slug?: string | null;
  metadataJson?: Record<string, unknown> | null;
  role?: string | null;
  publicUrl?: string | null;
  mimeType?: string | null;
  altText?: string | null;
  focalPoint?: string | null;
}

const isImage = (a: PlacedAsset) => !a.mimeType || a.mimeType.toLowerCase().startsWith("image/"); // an asset that says nothing is taken for a picture

/**
 * The asset an entry leads with: its featured or hero one (a picture the author chose), else its latest take (a recording is
 * attached each time it is made again, so the last "audio" one is the current take), else the first picture, else the first video, else
 * the first asset.
 */
export function leadAsset<T extends PlacedAsset>(assets: T[] | null | undefined): T | undefined {
  const chosen = assets?.find((a) => a.role === "featured" || a.role === "hero");
  if (chosen) return chosen;
  const takes = assets?.filter((a) => a.role === "audio") ?? [];
  if (takes.length) return takes[takes.length - 1];
  return assets?.find(isImage) ?? assets?.find(isVideoAsset) ?? assets?.[0];
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
  if (isVideoAsset(asset)) return { kind: "video", url: asset.publicUrl, alt: asset.altText ?? title, focalPoint: asset.focalPoint, poster: videoPosterOf(asset, assets ?? []) };
  const kind = (asset.mimeType ?? "").toLowerCase().startsWith("audio/") ? "audio" : isImage(asset) ? "image" : null;
  return kind ? { kind, url: asset.publicUrl, alt: asset.altText ?? title, focalPoint: asset.focalPoint } : null; // a text, JSON or PDF file has no picture to show
}
