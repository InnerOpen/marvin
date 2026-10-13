/**
 * A searchable picker for an integration action input with an `x-marvin-options` hint, used by the
 * Run action form and the workflow step editor. Free text is always possible: "Type a value…" in the
 * list, an empty list, or a failed load (the message is shown and the text box stays). The text box
 * (`.opt-value`) carries the value in every state, so forms read it like any other input.
 *
 * Styles: `.opt-picker` in styles/global.css.
 */

import { listInputOptions } from "./api/integrations";
import { filterOptions, findOption, type InputOption } from "./integrationOptions";

const CUSTOM = "\u0000custom";
const SEARCH_FROM = 8; // show the search box once the list is longer than this

export interface OptionPickerOptions {
  integrationId: string;
  actionKey: string;
  input: string;
  value?: unknown;
  required?: boolean;
  /** Attributes for the value input, so an existing form's reader finds it (e.g. data-key/data-kind). */
  dataset?: Record<string, string>;
  placeholder?: string;
  /** Called with the chosen option's own value (number stays number) or the typed text. */
  onChange?: (value: string | number | boolean) => void;
}

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function optionPicker(o: OptionPickerOptions): HTMLElement {
  const root = document.createElement("div");
  root.className = "opt-picker";
  root.innerHTML = `
    <div class="opt-row">
      <input type="search" class="input opt-search" placeholder="Search…" aria-label="Search the list" hidden />
      <select class="input opt-select" hidden></select>
      <button type="button" class="opt-refresh" title="Reload the list" aria-label="Reload the list">↻</button>
    </div>
    <input type="text" class="input opt-value" autocomplete="off" />
    <small class="opt-status hint"></small>`;
  const search = root.querySelector(".opt-search") as HTMLInputElement;
  const select = root.querySelector(".opt-select") as HTMLSelectElement;
  const refresh = root.querySelector(".opt-refresh") as HTMLButtonElement;
  const text = root.querySelector(".opt-value") as HTMLInputElement;
  const status = root.querySelector(".opt-status") as HTMLElement;

  text.value = o.value === undefined || o.value === null ? "" : String(o.value);
  text.placeholder = o.placeholder ?? "Type a value";
  text.required = Boolean(o.required);
  for (const [k, v] of Object.entries(o.dataset ?? {})) text.dataset[k] = v;

  let options: InputOption[] = [];
  let chosen: InputOption | undefined;

  const showText = (show: boolean) => {
    text.hidden = !show;
  };

  function fill(list: InputOption[]) {
    const current = chosen ? String(chosen.value) : text.hidden ? "" : CUSTOM;
    select.replaceChildren();
    const add = (value: string, label: string, title?: string) => {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      if (title) opt.title = title;
      select.appendChild(opt);
    };
    // Keep the current choice visible even when the search filters it out.
    if (chosen && !list.includes(chosen)) list = [chosen, ...list];
    add("", list.length ? "— Choose —" : "No matches");
    for (const item of list) add(String(item.value), item.label, item.label === String(item.value) ? undefined : String(item.value));
    add(CUSTOM, "Type a value…");
    select.value = [...select.options].some((op) => op.value === current) ? current : "";
  }

  function render() {
    chosen = findOption(options, text.value);
    if (!options.length) {
      select.hidden = search.hidden = true;
      showText(true);
      return;
    }
    select.hidden = false;
    search.hidden = options.length <= SEARCH_FROM;
    showText(!chosen && text.value !== "");
    fill(filterOptions(options, search.value));
  }

  async function load() {
    refresh.disabled = true;
    status.textContent = "Loading options…";
    status.classList.remove("is-error");
    try {
      options = await listInputOptions(o.integrationId, o.actionKey, o.input);
      status.textContent = options.length
        ? options.length >= 500
          ? "Showing the first 500 — search, or type a value."
          : ""
        : "Nothing to choose from — type a value.";
    } catch (e) {
      options = [];
      status.textContent = `${message(e)} — type a value instead.`;
      status.classList.add("is-error");
    } finally {
      refresh.disabled = false;
      render();
    }
  }

  select.addEventListener("change", () => {
    if (select.value === CUSTOM) {
      chosen = undefined;
      showText(true);
      text.focus();
      return;
    }
    chosen = options.find((op) => String(op.value) === select.value);
    text.value = chosen ? String(chosen.value) : "";
    showText(false);
    o.onChange?.(chosen ? chosen.value : "");
  });
  search.addEventListener("input", () => fill(filterOptions(options, search.value)));
  text.addEventListener("input", () => {
    chosen = undefined;
    o.onChange?.(text.value);
  });
  refresh.addEventListener("click", () => void load());

  showText(true);
  void load();
  return root;
}
