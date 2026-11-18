// An approval can show what the question is about: a picture, a sound (a recorded take) or a video (a generated moving shot).
// All arrive as the asset's URL (the step's `image`), so the page tells them apart by the file's extension, ignoring any query
// string. A .webm stays audio: that is what a recorded take is.

const AUDIO_EXTENSIONS = ["mp3", "wav", "ogg", "m4a", "aac", "flac", "webm"];
const VIDEO_EXTENSIONS = ["mp4", "m4v", "mov"];

function extensionIn(url: string | null | undefined, extensions: string[]): boolean {
  if (!url) return false;
  const path = url.split(/[?#]/)[0].toLowerCase();
  return extensions.some((ext) => path.endsWith(`.${ext}`));
}

export function isAudioUrl(url: string | null | undefined): boolean {
  return extensionIn(url, AUDIO_EXTENSIONS);
}

export function isVideoUrl(url: string | null | undefined): boolean {
  return extensionIn(url, VIDEO_EXTENSIONS);
}

/** How an approval card shows its media: a player for a sound or a video, else the picture. */
export function mediaKind(url: string | null | undefined): "audio" | "video" | "image" {
  return isVideoUrl(url) ? "video" : isAudioUrl(url) ? "audio" : "image";
}
