// A text file in the asset library (a transcript, a script, a CSV, JSON) previews as text. Browsers will not show every text type in a frame
// (Chrome downloads text/markdown and text/csv), so the page reads the start of the file itself and prints it, escaped, in a read-only block.

/** Types shown as text: any `text/*` except HTML (which has its own preview), JSON, XML and YAML, and anything `+json` or `+xml`. */
export function isTextMime(mime: string | null | undefined): boolean {
  const type = (mime ?? "").split(";")[0].trim().toLowerCase();
  if (!type || type === "text/html") return false;
  if (type.startsWith("text/")) return true;
  return ["application/json", "application/xml", "application/yaml", "application/x-yaml", "application/csv", "application/x-ndjson"].includes(type) || /\+(json|xml)$/.test(type);
}

export const TEXT_PREVIEW_LIMIT = 200_000; // characters: a long transcript is a few tens of thousands; the full file is one click away

export interface TextPreview {
  text: string;
  /** the file goes on past what is shown */
  truncated: boolean;
}

/** The start of the file at `url` as text, at most `limit` characters; null when it cannot be read. */
export async function fetchTextPreview(url: string, limit: number = TEXT_PREVIEW_LIMIT, fetcher: typeof fetch = fetch): Promise<TextPreview | null> {
  try {
    const response = await fetcher(url);
    if (!response.ok) return null;
    const text = await response.text();
    return text.length > limit ? { text: text.slice(0, limit), truncated: true } : { text, truncated: false };
  } catch {
    return null;
  }
}
