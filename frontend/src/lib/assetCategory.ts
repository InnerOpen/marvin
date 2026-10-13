/** The Assets page's type buckets, from a MIME type. */
export type AssetCategory = "image" | "video" | "audio" | "document" | "other";

export function getMimeCategory(mimeType: string): AssetCategory {
  if (mimeType.startsWith("image/")) return "image";
  if (mimeType.startsWith("video/")) return "video";
  if (mimeType.startsWith("audio/")) return "audio";
  if (mimeType.includes("pdf")) return "document";
  return "other";
}
