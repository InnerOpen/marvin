/**
 * Collapsed raw-JSON fields on the entry editor (`<details class="json-disclosure">`). A collapsed
 * field still submits — a closed <details> only hides its content — so the form and the JSON sync
 * keep working whatever the user has open.
 */

const STORAGE_PREFIX = "marvin.disclosure.";
const HINT_KEYS = 3;

type KeyValueStore = Pick<Storage, "getItem" | "setItem">;

function browserStorage(): KeyValueStore | null {
  try {
    return window.localStorage;
  } catch {
    return null; // private mode / blocked storage: just don't remember
  }
}

/**
 * What a collapsed summary says about the JSON inside, so set metadata is noticed without opening it:
 * "" when empty, else e.g. "2 keys: seo_title, featured" (the first few names).
 */
export function keysHint(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const keys = Object.keys(value);
  if (!keys.length) return "";
  const shown = keys.slice(0, HINT_KEYS).join(", ");
  const more = keys.length > HINT_KEYS ? ", …" : "";
  return `${keys.length} ${keys.length === 1 ? "key" : "keys"}: ${shown}${more}`;
}

/**
 * Remember each `<details data-remember="name">`'s open state in this browser. One the server rendered
 * `open` (it has an error to show) stays open and isn't overwritten until the user toggles it.
 */
export function rememberDisclosures(
  root: ParentNode = document,
  storage: KeyValueStore | null = browserStorage(),
): void {
  if (!storage) return;
  root.querySelectorAll<HTMLDetailsElement>("details[data-remember]").forEach((el) => {
    const key = STORAGE_PREFIX + el.dataset.remember;
    if (!el.open) {
      try {
        el.open = storage.getItem(key) === "open";
      } catch {
        /* unreadable storage: keep the default */
      }
    }
    el.addEventListener("toggle", () => {
      try {
        storage.setItem(key, el.open ? "open" : "closed");
      } catch {
        /* full or blocked storage: not worth surfacing */
      }
    });
  });
}
