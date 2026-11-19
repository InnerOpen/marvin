// Whether an asset is a video to play small where it is shown (InlineVideo.astro), and the still it shows before it plays. An approval's
// media is only a URL, so approvalMedia.ts goes by its extension (a .webm is a recorded take there); an asset says its type, so this goes by
// the type first: a video/* file is a video, unless it is a sound kept in a video container (a .webm take picked from disk reads as
// video/webm) — a take in the `audio` role, or one the audio recorder made. Pure, so `npm test` covers it (videoAsset.test.mjs).

import { isVideoUrl } from "./approvalMedia.ts";

export interface VideoLike {
  id?: string | null;
  slug?: string | null;
  role?: string | null;
  mimeType?: string | null;
  publicUrl?: string | null;
  metadataJson?: Record<string, unknown> | null;
}

const recordingKind = (asset: VideoLike): unknown => {
  const recording = asset.metadataJson?.recording;
  return recording && typeof recording === "object" ? (recording as Record<string, unknown>).kind : undefined;
};

/** Whether the asset is a video: its type says video (and it is not a sound in a video container), or it says no type and its file ends .mp4/.m4v/.mov. */
export function isVideoAsset(asset: VideoLike | null | undefined): boolean {
  if (!asset?.publicUrl) return false;
  const kind = recordingKind(asset);
  if (kind === "video") return true;
  if (kind === "audio" || asset.role === "audio") return false;
  const mime = (asset.mimeType ?? "").trim().toLowerCase();
  if (mime) return mime.startsWith("video/");
  return isVideoUrl(asset.publicUrl);
}

const isUrl = (s: string) => /^(https?:)?\/\//i.test(s) || s.startsWith("/");

/**
 * The still a video shows before it plays: the picture its metadata names under `poster` (a URL, or the id or slug of another asset that
 * is a picture, found among `siblings`: the entry's other assets, the rows of the list). Null when it names none, so the video's own
 * first frame shows (preload="metadata").
 */
export function videoPosterOf(asset: VideoLike | null | undefined, siblings: readonly VideoLike[] = []): string | null {
  const meta = asset?.metadataJson ?? {};
  const named = [meta.poster, meta.poster_asset_id, meta.poster_id].find((v): v is string => typeof v === "string" && v.trim() !== "")?.trim();
  if (!named) return null;
  if (isUrl(named)) return named;
  const hit = siblings.find((s) => (s.id === named || s.slug === named) && s.publicUrl && (s.mimeType ?? "").toLowerCase().startsWith("image/"));
  return hit?.publicUrl ?? null;
}

/** The src a small player loads: `#t=0.001` asks Safari on a phone to draw the first frame (it shows nothing with preload="metadata" alone). */
export function firstFrameSrc(url: string): string {
  return url.includes("#") ? url : `${url}#t=0.001`;
}
