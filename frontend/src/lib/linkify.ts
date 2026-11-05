// An approval's message is plain text a workflow wrote, and it may name an address ("watch it first: https://..."). Cards show it as
// text, so the address was not clickable. This splits a message into text and web addresses (http and https only), leaving the
// rendering to the page, which escapes everything it prints.

export interface MessagePart {
  text: string;
  /** set for a web address */
  href?: string;
}

const ADDRESS = /https?:\/\/[^\s<>"']+/g;
/** what a sentence puts after an address but is not part of it */
const TRAILING = /[.,;:!?)\]]+$/;

/** How a link card names an address: the site, and the rest of the address in short (no scheme, no `www.`, no query), for the card's two lines. */
export function describeAddress(address: string): { host: string; path: string } {
  try {
    const url = new URL(address);
    const path = url.pathname === "/" ? "" : url.pathname.replace(/^\//, "").replace(/\/$/, "");
    return { host: url.host.replace(/^www\./, ""), path };
  } catch {
    return { host: address, path: "" };
  }
}

export function messageParts(message: string | null | undefined): MessagePart[] {
  const text = message ?? "";
  const parts: MessagePart[] = [];
  let at = 0;
  for (const match of text.matchAll(ADDRESS)) {
    const start = match.index ?? 0;
    const raw = match[0];
    const address = raw.replace(TRAILING, "");
    if (start > at) parts.push({ text: text.slice(at, start) });
    parts.push({ text: address, href: address });
    if (address.length < raw.length) parts.push({ text: raw.slice(address.length) });
    at = start + raw.length;
  }
  if (at < text.length) parts.push({ text: text.slice(at) });
  return parts;
}
