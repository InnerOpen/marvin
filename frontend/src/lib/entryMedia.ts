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

/** The asset an entry leads with: its featured or hero one, else the first. A recording wins over nothing but not over a picture the author chose. */
export function leadAsset<T extends PlacedAsset>(assets: T[] | null | undefined): T | undefined {
  return assets?.find((a) => a.role === "featured" || a.role === "hero") ?? assets?.[0];
}

export function thumbOf(assets: PlacedAsset[] | null | undefined, title: string): EntryThumb | null {
  const asset = leadAsset(assets);
  if (!asset?.publicUrl) return null;
  const kind = (asset.mimeType ?? "").toLowerCase().startsWith("audio/") ? "audio" : "image";
  return { kind, url: asset.publicUrl, alt: asset.altText ?? title, focalPoint: asset.focalPoint };
}
