// The one sound or video playing on a page. A play button (PlayButton.astro) and a small video (InlineVideo.astro) both claim it when
// they start, so starting one stops whichever was playing, a sound or a video. Both components' scripts import this module, and a page
// bundles it once, so they share it.

type Playing = { media: HTMLMediaElement; stop: () => void };

let current: Playing | null = null;

/** `media` is starting: stop whatever else is playing, and remember how to stop this one. */
export function claim(media: HTMLMediaElement, stop: () => void): void {
  if (current && current.media !== media) current.stop();
  current = { media, stop };
}

/** `media` stopped by itself (paused, ended, failed): nothing is playing now, unless something else already took over. */
export function release(media: HTMLMediaElement): void {
  if (current?.media === media) current = null;
}
