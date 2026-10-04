/**
 * Integration provider marks: the official logo when the provider ships one Marvin accepted
 * (`hasLogo`), otherwise its emoji `icon`. The logo is 32px tall on a white rounded tile in both themes
 * (brand rules: minimum sizes, black-only marks; wordmarks keep their aspect ratio up to 80px wide), never
 * more prominent than Marvin's own branding, and decorative (`alt=""`) — the name is always beside it.
 * If the image fails to load, `installLogoFallback()` swaps the tile for the emoji.
 *
 * Styles: `.int-mark`, `.int-mark-img`, `.int-mark-emoji`, `.int-named` in styles/global.css (global, so
 * marks rendered from client-side HTML strings pick them up too).
 */

export interface MarkSource {
  slug: string;
  icon?: string | null;
  hasLogo?: boolean | null;
}

/** Same-origin path (through the frontend's /api proxy). The endpoint is public, so <img> needs no auth. */
export function logoUrl(slug: string): string {
  return `/api/groups/integrations/providers/${encodeURIComponent(slug)}/logo`;
}

function esc(s: unknown): string {
  return String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string,
  );
}

/** The mark as an HTML string (for client-rendered UI). Empty when there is neither logo nor emoji. */
export function markHtml(p: MarkSource | null | undefined): string {
  if (!p) return "";
  if (p.hasLogo) {
    return `<span class="int-mark" data-emoji="${esc(p.icon ?? "")}"><img class="int-mark-img" src="${esc(logoUrl(p.slug))}" alt="" height="32" decoding="async" /></span>`;
  }
  return p.icon ? `<span class="int-mark-emoji" aria-hidden="true">${esc(p.icon)}</span>` : "";
}

function fallBack(img: HTMLImageElement): void {
  const tile = img.closest<HTMLElement>(".int-mark");
  if (!tile) return;
  const emoji = tile.dataset.emoji;
  if (!emoji) {
    tile.remove();
    return;
  }
  const span = document.createElement("span");
  span.className = "int-mark-emoji";
  span.setAttribute("aria-hidden", "true");
  span.textContent = emoji;
  tile.replaceWith(span);
}

let installed = false;

/** Swap broken logos for the emoji — now (images that already failed) and from here on. Idempotent. */
export function installLogoFallback(): void {
  if (typeof document === "undefined") return;
  if (!installed) {
    installed = true;
    // `error` doesn't bubble; capture it at the document so images added later are covered too.
    document.addEventListener(
      "error",
      (e) => {
        const t = e.target;
        if (t instanceof HTMLImageElement && t.classList.contains("int-mark-img")) fallBack(t);
      },
      true,
    );
  }
  for (const img of document.querySelectorAll<HTMLImageElement>("img.int-mark-img")) {
    if (img.complete && img.naturalWidth === 0) fallBack(img);
  }
}
