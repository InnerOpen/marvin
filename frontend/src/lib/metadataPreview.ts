// The "Current Metadata" preview under a metadata JSON editor (asset, resource, collection and site
// settings pages), redrawn as the JSON is edited. Keys and values are whatever anyone with edit access
// saved, so they go in as text nodes, never as markup.

function el(tag: string, className: string, text?: string): HTMLElement {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** `<div class="metadata-preview">`: a title and a `<dl>` with one key/value item per entry. */
export function metadataPreview(entries: [string, unknown][]): HTMLElement {
  const list = el("dl", "metadata-preview-list");
  for (const [key, value] of entries) {
    const display = typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);
    const item = el("div", "metadata-preview-item");
    item.append(el("dt", "", key), el("dd", "", display));
    list.append(item);
  }
  const preview = el("div", "metadata-preview");
  preview.append(el("p", "metadata-preview-title", "Current Metadata:"), list);
  return preview;
}

/**
 * Keep the preview in step with `editor`: replace the one inside the editor's closest `scope` ancestor, or
 * put a new one after `anchor()`. It goes away while the JSON is empty, invalid or has no keys.
 */
export function bindMetadataPreview(
  editor: HTMLTextAreaElement,
  scope: string,
  anchor: () => Element | null | undefined,
): void {
  editor.addEventListener("input", () => {
    const current = editor.closest(scope)?.querySelector(".metadata-preview");
    let entries: [string, unknown][] = [];
    try {
      const parsed = JSON.parse(editor.value);
      if (parsed !== null) entries = Object.entries(parsed);
    } catch {
      // Invalid (or empty) JSON: no preview.
    }

    if (!entries.length) {
      current?.remove();
      return;
    }
    const preview = metadataPreview(entries);
    if (current) current.replaceWith(preview);
    else anchor()?.after(preview);
  });
}
