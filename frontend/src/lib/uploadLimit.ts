/**
 * The most one upload can carry. Cloudflare, which sits in front of Marvin, refuses a request body over 100 MB with its own 413 page (a
 * browser still sending may then see the request hang or fail with nothing readable), and Marvin's own ASSET_MAX_FILE_SIZE is 100 MB too. The
 * form's other fields ride in the same body, so the check keeps a little under the line. A file over it is refused in the browser, at once,
 * with a message that says what to do.
 */
export const UPLOAD_LIMIT_BYTES = 99 * 1000 * 1000;

const megabytes = (bytes: number): string => `${(bytes / 1e6).toFixed(bytes >= 1e7 ? 0 : 1)} MB`;

/** Why this file cannot be uploaded as it is, or null when it can. */
export function uploadTooBig(file: { name: string; size: number }): string | null {
  if (file.size <= UPLOAD_LIMIT_BYTES) return null;
  return `${file.name} is ${megabytes(file.size)}; an upload can carry about ${megabytes(UPLOAD_LIMIT_BYTES)}. Make the file smaller first (an overlay loop rarely needs more than a few MB: shorten it, lower its resolution or compress it with a higher CRF), then upload it again.`;
}
