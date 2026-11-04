// An approval can show what the question is about: a picture, or a sound (a recorded take). Both arrive as the asset's URL
// (the step's `image`), so the page tells them apart by the file's extension, ignoring any query string.

const AUDIO_EXTENSIONS = ["mp3", "wav", "ogg", "m4a", "aac", "flac", "webm"];

export function isAudioUrl(url: string | null | undefined): boolean {
  if (!url) return false;
  const path = url.split(/[?#]/)[0].toLowerCase();
  return AUDIO_EXTENSIONS.some((ext) => path.endsWith(`.${ext}`));
}
