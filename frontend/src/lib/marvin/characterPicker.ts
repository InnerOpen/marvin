/**
 * Marvin — the bubble-character picker (components/CharacterPicker.astro): upload a pack, pick each
 * state's animation, remove it — and, where a library is offered, choose a library pack, an own
 * upload, or none.
 *
 * One picker per character, all talking to the same endpoint shape under `data-api`:
 *   POST {api} (files) uploads/replaces, PUT {api}/states {state, file} assigns, DELETE {api} removes,
 *   PUT {api}/library {pack} switches to a library pack (only where a library is offered).
 * Used for the workspace's character (AI settings), each agent's (Settings → Agents) and each library
 * pack's (Admin → Character library). Changes save as they're made: an upload stores files, so it can't
 * wait for a form's "Save". The root fires `character-change` (detail: the character, or null) after each.
 */

import { fetchApi } from "@/lib/api/client";
import { CHARACTER_STATES, type CharacterState, fallbacksOf, imageFor } from "@/lib/marvin/character";

const STATE_LABELS: Record<CharacterState, string> = {
  idle: "Idle",
  idle_variant: "Idle fidget",
  peek_left: "Peek left",
  peek_right: "Peek right",
  peek_top: "Peek top",
  peek_bottom: "Peek bottom",
  greeting: "Greeting",
  thinking: "Thinking",
  working: "Working",
  waiting: "Waiting for approval",
  success: "Success",
  error: "Error",
  move_left: "Dragging left",
  move_right: "Dragging right",
};

const SOURCE_NONE = "";
const SOURCE_OWN = "own";
const LIBRARY_PREFIX = "library:";

type CharacterFile = { name: string; url: string };
export type StoredCharacter = {
  library?: string | null;
  name?: string | null;
  states: Partial<Record<CharacterState, string>>;
  files: CharacterFile[];
  missing?: string[];
};
type UploadResult = StoredCharacter & {
  ignored: string[];
  idleGuessed: boolean;
  cleared: string[];
  /** The upload was one character sheet, built into these animations: "16-pose sheet (height 108)". */
  builtFrom?: string | null;
};

/** "Built 14 animations from a ChatGPT pet sheet (height 96)." — or null for an ordinary upload. */
export function builtFromLine(res: { builtFrom?: string | null; files: unknown[] }): string | null {
  return res.builtFrom ? `Built ${res.files.length} animations from a ${res.builtFrom}.` : null;
}

function parseData<T>(raw: string | undefined, fallback: T): T {
  try {
    return (JSON.parse(raw || "null") as T) ?? fallback;
  } catch {
    return fallback;
  }
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** The picker's source choice — a radio group of cards (none, each library pack, own upload) — or null
 * where no library is offered (a library pack's own editor). */
function sourceChoice(root: HTMLElement) {
  const options = [...root.querySelectorAll<HTMLInputElement>(".character-source-option")];
  if (!options.length) return null;
  return {
    get value(): string {
      return options.find((o) => o.checked)?.value ?? SOURCE_NONE;
    },
    set value(v: string) {
      for (const o of options) o.checked = o.value === v;
    },
    addEventListener(_type: "change", listener: () => void) {
      for (const o of options) o.addEventListener("change", listener);
    },
  };
}

function sourceOf(c: StoredCharacter | null): string {
  if (!c) return SOURCE_NONE;
  return c.library ? `${LIBRARY_PREFIX}${c.library}` : SOURCE_OWN;
}

/** The "Own upload" card shows the uploaded idle animation once there is one. */
function showOwnArt(root: HTMLElement, idle: string | undefined): void {
  const art = root.querySelector<HTMLElement>(".character-own-art");
  if (!art) return;
  const img = idle ? Object.assign(document.createElement("img"), { src: idle, alt: "" }) : null;
  if (img) {
    img.className = art.className;
    art.replaceWith(img);
  } else if (art.tagName === "IMG") {
    const glyph = Object.assign(document.createElement("span"), { textContent: "⬆", className: art.className });
    glyph.setAttribute("aria-hidden", "true");
    art.replaceWith(glyph);
  }
}

/** Wire up one picker; its markup comes from CharacterPicker.astro. */
export function mountCharacterPicker(root: HTMLElement): void {
  const api = root.dataset.api!;
  const removeConfirm = root.dataset.removeConfirm || "Remove this character? Its uploaded files are deleted.";
  const q = <T extends HTMLElement>(cls: string) => root.querySelector<T>(`.${cls}`)!;
  const source = sourceChoice(root);
  const preview = q<HTMLImageElement>("character-preview");
  const own = q<HTMLElement>("character-own");
  const grid = q<HTMLElement>("character-grid");
  const report = q<HTMLElement>("character-report");
  const unassigned = q<HTMLElement>("character-unassigned");
  const status = q<HTMLElement>("character-status");
  const input = q<HTMLInputElement>("character-files");
  const remove = q<HTMLButtonElement>("character-remove");
  let current = parseData<StoredCharacter | null>(root.dataset.character, null);

  function setStatus(text: string, kind: "" | "success" | "error" = "") {
    status.textContent = text;
    status.className = `character-status ${kind}`.trim();
  }

  async function call<T>(label: string, run: () => Promise<T>): Promise<T | null> {
    setStatus(label);
    try {
      const res = await run();
      setStatus("Saved", "success");
      return res;
    } catch (err) {
      setStatus(`Error: ${err instanceof Error ? err.message : String(err)}`, "error");
      return null;
    }
  }

  const json = (method: string, body: unknown): RequestInit => ({
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  function stateRow(c: StoredCharacter, state: CharacterState): HTMLElement {
    const row = el("div", "character-row");
    const mine = c.states[state];
    const src = imageFor(c.states, state);
    const thumb = el("img", mine ? "character-thumb" : "character-thumb borrowed");
    thumb.alt = "";
    if (src) thumb.src = src;
    const select = el("select", "input");
    select.setAttribute("aria-label", `${STATE_LABELS[state]} animation`);
    if (state !== "idle") {
      const chain = fallbacksOf(state)
        .map((s) => STATE_LABELS[s])
        .join(", then ");
      select.append(new Option(`— default (falls back to ${chain})`, ""));
    }
    // By name: names are unique within a character, and every kind of store knows them.
    for (const f of c.files) select.append(new Option(f.name, f.name, false, f.url === mine));
    if (mine && !c.files.some((f) => f.url === mine)) select.append(new Option("(an image URL)", "", false, true));
    select.addEventListener("change", () => void assign(state, select.value || null));
    row.append(thumb, el("span", "character-state", STATE_LABELS[state]), select);
    return row;
  }

  function render(c: StoredCharacter | null, keepSource = false) {
    current = c;
    if (source && !keepSource) source.value = sourceOf(c);
    const idle = c?.states.idle;
    const isOwn = !!c && !c.library;
    // With choice cards the cards preview each option; the separate preview is for a pack's own editor.
    preview.hidden = !idle || !!source;
    if (idle) preview.src = idle;
    if (source) showOwnArt(root, isOwn ? idle : undefined);
    // With a library on offer, the editor is for an own upload only; without, it's always there.
    own.hidden = !!source && source.value !== SOURCE_OWN;
    remove.hidden = !isOwn || !!source || root.dataset.removable === "false";
    grid.hidden = !isOwn;
    unassigned.hidden = true;
    if (!isOwn || !c) {
      grid.replaceChildren();
    } else {
      grid.replaceChildren(...CHARACTER_STATES.map((state) => stateRow(c, state)));
      const used = new Set(Object.values(c.states));
      const spare = c.files.filter((f) => !used.has(f.url)).map((f) => f.name);
      if (spare.length) {
        unassigned.textContent = `Not used by any state: ${spare.join(", ")}`;
        unassigned.hidden = false;
      }
    }
    root.dispatchEvent(new CustomEvent("character-change", { detail: c, bubbles: true }));
  }

  function reportUpload(res: UploadResult) {
    const lines: string[] = [];
    const built = builtFromLine(res);
    if (built) lines.push(built);
    if (res.idleGuessed) {
      const idle = res.files.find((f) => f.url === res.states.idle);
      lines.push(
        `No file was named for Idle, so ${idle?.name ?? "the first image"} plays as Idle — pick another below.`,
      );
    }
    const missing = (res.missing ?? []).map((k) => STATE_LABELS[k as CharacterState] ?? k);
    if (missing.length) lines.push(`No animation for: ${missing.join(", ")} — these fall back.`);
    if (res.ignored.length) lines.push(`Skipped (not a GIF, WebP or PNG): ${res.ignored.join(", ")}`);
    if (res.cleared.length) {
      const files = res.cleared.length === 1 ? "1 file" : `${res.cleared.length} files`;
      lines.push(`Removed a solid background from ${files}: ${res.cleared.join(", ")}`);
    }
    report.replaceChildren(...lines.map((l) => el("li", undefined, l)));
    report.hidden = !lines.length;
  }

  async function assign(state: CharacterState, file: string | null) {
    const res = await call("Saving…", () => fetchApi<StoredCharacter>(`${api}/states`, json("PUT", { state, file })));
    if (res) render(res);
  }

  async function removeCharacter(): Promise<boolean> {
    if (!current) return true;
    if ((await call("Removing…", () => fetchApi(api, { method: "DELETE" }))) === null) return false;
    report.hidden = true;
    render(null);
    return true;
  }

  q<HTMLButtonElement>("character-upload").addEventListener("click", () => input.click());
  input.addEventListener("change", async () => {
    const files = [...(input.files ?? [])];
    input.value = "";
    if (!files.length) return;
    const body = new FormData();
    for (const f of files) body.append("files", f);
    const res = await call("Uploading…", () => fetchApi<UploadResult>(api, { method: "POST", body }));
    if (!res) return;
    render(res);
    reportUpload(res);
  });
  remove.addEventListener("click", () => {
    if (confirm(removeConfirm)) void removeCharacter();
  });

  source?.addEventListener("change", async () => {
    const choice = source.value;
    const ownFiles = !!current && !current.library;
    if (choice === SOURCE_OWN) {
      render(current, true); // nothing saved until an upload: the current character plays meanwhile
      return;
    }
    if (ownFiles && !confirm(removeConfirm)) {
      source.value = sourceOf(current);
      return;
    }
    if (choice === SOURCE_NONE) {
      if (!(await removeCharacter())) source.value = sourceOf(current);
      return;
    }
    const pack = choice.slice(LIBRARY_PREFIX.length);
    const res = await call("Saving…", () => fetchApi<StoredCharacter>(`${api}/library`, json("PUT", { pack })));
    report.hidden = true;
    render(res ?? current);
  });

  render(current);
}

export function mountCharacterPickers(scope: ParentNode = document): void {
  for (const root of scope.querySelectorAll<HTMLElement>(".character-picker:not([data-mounted])")) {
    root.dataset.mounted = "";
    mountCharacterPicker(root);
  }
}
