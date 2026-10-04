/**
 * The tones editor (components/ToneEditor.astro, on AI settings): the workspace's default tone, which
 * tones the pickers offer, and its own tones — name, instructions and a persona rule (how far the
 * Persona's character reaches). Preview (on each row, built-ins too) and the form's Preview prompt show the
 * result in parts — from the Persona, from the tone, which wins — through the shared lib/promptPreview.
 *
 * Every change saves the whole list at once (PUT /api/groups/ai-settings/tones) and re-renders from the
 * server's answer, so the page never drifts from what's stored. Built-ins can be hidden but not edited;
 * a tone that agents default to can't be deleted (the server answers 409 naming them).
 */

import { type ToneInput, previewTone, saveTones } from "@/lib/api/aiTones";
import { promptPreviewHtml, promptPreviewMessage, tonePreviewView } from "@/lib/promptPreview";
import { PERSONA_RULES, type PersonaRule, type Tone, type TonesState } from "@/lib/tones";

const esc = (s: unknown) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!,
  );

const ruleLabel = (rule: PersonaRule) => PERSONA_RULES.find((r) => r.value === rule)?.label ?? rule;
const EXCERPT_CHARS = 140;
const MAX_DESCRIPTION_CHARS = 200;

function excerpt(text: string): string {
  return text.length > EXCERPT_CHARS ? `${text.slice(0, EXCERPT_CHARS - 1)}…` : text;
}

/** The message to show for a failed save: the 409's own message, else the error text. */
function errorText(err: any): string {
  const detail = err?.body?.detail;
  if (detail && typeof detail === "object" && typeof detail.message === "string") return detail.message;
  return String(err?.message || err);
}

const toInput = (t: Tone): ToneInput => ({
  slug: t.slug,
  name: t.name,
  instructions: t.instructions,
  persona: t.persona,
  description: t.description ?? null,
});

function rowHtml(t: Tone, state: TonesState): string {
  const isDefault = t.slug === state.defaultTone;
  const about = t.description || (t.builtin ? "" : excerpt(t.instructions));
  const used = t.usedBy.length ? `<span class="tone-used">Default for ${t.usedBy.map(esc).join(", ")}</span>` : "";
  const preview = `<button type="button" class="button secondary small" data-act="preview" aria-expanded="false">Preview</button>`;
  const actions = t.builtin
    ? `<span class="tone-badge">Built-in</span>${preview}`
    : `${preview}<button type="button" class="button secondary small" data-act="edit">Edit</button>
       <button type="button" class="button secondary small" data-act="delete"${t.usedBy.length ? ` title="Agents default to this tone"` : ""}>Delete</button>`;
  return `<li class="tone-row${t.hidden ? " is-hidden" : ""}" data-slug="${esc(t.slug)}">
    <label class="tone-default" title="Workspace default">
      <input type="radio" name="tone-default" value="${esc(t.slug)}"${isDefault ? " checked" : ""}${t.hidden ? " disabled" : ""} />
    </label>
    <div class="tone-main">
      <div class="tone-name"><strong>${esc(t.name)}</strong> <code>${esc(t.slug)}</code>
        <span class="tone-badge">${esc(ruleLabel(t.persona))}</span>${isDefault ? `<span class="tone-badge is-default">Default</span>` : ""}</div>
      ${about ? `<div class="tone-about">${esc(about)}</div>` : ""}${used}
    </div>
    <label class="tone-shown" title="Offer this tone in the Ask page, agent and bubble pickers">
      <input type="checkbox" data-act="shown"${t.hidden ? "" : " checked"}${isDefault ? " disabled" : ""} /> Show
    </label>
    <div class="tone-actions">${actions}</div>
    <div class="prompt-preview tone-row-preview" data-row-preview hidden aria-live="polite"></div>
  </li>`;
}

function formHtml(t: Tone | null, state: TonesState): string {
  const rules = PERSONA_RULES.map(
    (
      r,
    ) => `<label class="tone-rule"><input type="radio" name="tone-persona" value="${r.value}"${(t?.persona ?? "frame") === r.value ? " checked" : ""} />
      <span><strong>${esc(r.label)}</strong> <small class="hint">${esc(r.hint)}</small></span></label>`,
  ).join("");
  const instructions = t?.instructions ?? "";
  return `<div class="tone-form" data-slug="${esc(t?.slug ?? "")}">
    <h4>${t ? `Edit “${esc(t.name)}”` : "New tone"}</h4>
    <label class="form-field"><span class="label">Name</span>
      <input class="input" name="tone-name" maxlength="${state.maxNameChars}" required value="${esc(t?.name ?? "")}" placeholder="e.g. Board report" /></label>
    <label class="form-field"><span class="label">Description <small class="hint">(optional, shown in pickers)</small></span>
      <input class="input" name="tone-description" maxlength="${MAX_DESCRIPTION_CHARS}" value="${esc(t?.description ?? "")}" placeholder="e.g. Terse, numbers first" /></label>
    <label class="form-field"><span class="label">Instructions</span>
      <textarea class="input" name="tone-instructions" rows="4" maxlength="${state.maxInstructionsChars}"
        placeholder="e.g. Lead with the numbers. Short sentences, no adjectives, no emoji.">${esc(instructions)}</textarea>
      <small class="hint"><span data-count>${instructions.length}</span> / ${state.maxInstructionsChars} characters. Sent with every agent step, so shorter is cheaper.</small></label>
    <fieldset class="form-field tone-rules"><legend class="label">Your Persona's character</legend>${rules}</fieldset>
    <div class="tone-form-actions">
      <button type="button" class="button small" data-act="save">Save tone</button>
      <button type="button" class="button secondary small" data-act="preview">Preview prompt</button>
      <button type="button" class="button secondary small" data-act="cancel">Cancel</button>
    </div>
    <div class="prompt-preview" data-form-preview hidden aria-live="polite"></div>
  </div>`;
}

function mount(root: HTMLElement): void {
  let state: TonesState = JSON.parse(root.dataset.state || "null");
  const list = root.querySelector<HTMLElement>("[data-tone-list]")!;
  const formBox = root.querySelector<HTMLElement>("[data-tone-form]")!;
  const addBtn = root.querySelector<HTMLButtonElement>("[data-act=add]")!;
  const status = root.querySelector<HTMLElement>("[data-tone-status]")!;

  const custom = () => state.tones.filter((t) => !t.builtin);
  const hidden = () => state.tones.filter((t) => t.hidden).map((t) => t.slug);

  function say(text: string, kind: "" | "success" | "error" = "") {
    status.textContent = text;
    status.className = `save-status ${kind}`.trim();
  }

  function render() {
    list.innerHTML = state.tones.map((t) => rowHtml(t, state)).join("");
    addBtn.disabled = custom().length >= state.maxCustomTones;
    addBtn.title = addBtn.disabled ? `A workspace can have at most ${state.maxCustomTones} tones.` : "";
  }

  async function save(next: { tones?: ToneInput[]; hidden?: string[]; defaultTone?: string }): Promise<boolean> {
    say("Saving…");
    try {
      state = await saveTones({
        tones: next.tones ?? custom().map(toInput),
        hidden: next.hidden ?? hidden(),
        ...(next.defaultTone ? { defaultTone: next.defaultTone } : {}),
      });
      render();
      say("Saved", "success");
      return true;
    } catch (err) {
      render(); // undo the optimistic radio/checkbox change
      say(errorText(err), "error");
      return false;
    }
  }

  function readForm(): ToneInput & { slug?: string } {
    const box = formBox.querySelector<HTMLElement>(".tone-form")!;
    const val = (name: string) =>
      box.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[name="${name}"]`)!.value.trim();
    const persona = (box.querySelector<HTMLInputElement>('[name="tone-persona"]:checked')?.value ??
      "frame") as PersonaRule;
    return {
      ...(box.dataset.slug ? { slug: box.dataset.slug } : {}),
      name: val("tone-name"),
      instructions: val("tone-instructions"),
      description: val("tone-description") || null,
      persona,
    };
  }

  function openForm(t: Tone | null) {
    formBox.innerHTML = formHtml(t, state);
    formBox.hidden = false;
    const area = formBox.querySelector<HTMLTextAreaElement>('[name="tone-instructions"]')!;
    const count = formBox.querySelector<HTMLElement>("[data-count]")!;
    area.addEventListener("input", () => {
      count.textContent = String(area.value.length);
    });
    formBox.querySelector<HTMLInputElement>('[name="tone-name"]')!.focus();
  }

  function closeForm() {
    formBox.hidden = true;
    formBox.innerHTML = "";
  }

  addBtn.addEventListener("click", () => openForm(null));
  // The editor sits inside the AI settings form: Enter in a tone field must not submit that form.
  formBox.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.target as HTMLElement).tagName === "INPUT") e.preventDefault();
  });

  formBox.addEventListener("click", async (e) => {
    const act = (e.target as HTMLElement).closest<HTMLElement>("[data-act]")?.dataset.act;
    if (!act) return;
    if (act === "cancel") return closeForm();
    const draft = readForm();
    if (act === "preview") {
      const box = formBox.querySelector<HTMLElement>("[data-form-preview]")!;
      try {
        const out = await previewTone({ name: draft.name, instructions: draft.instructions, persona: draft.persona });
        box.innerHTML = promptPreviewHtml(tonePreviewView(out));
        box.hidden = false;
      } catch (err) {
        say(errorText(err), "error");
      }
    }
    if (act === "save") {
      const rest = custom().map(toInput);
      const i = draft.slug ? rest.findIndex((t) => t.slug === draft.slug) : -1;
      if (i >= 0) rest[i] = draft;
      else rest.push(draft);
      if (await save({ tones: rest })) closeForm();
    }
  });

  list.addEventListener("change", (e) => {
    const input = e.target as HTMLInputElement;
    const slug = input.closest<HTMLElement>(".tone-row")?.dataset.slug;
    if (!slug) return;
    if (input.name === "tone-default") void save({ defaultTone: slug });
    if (input.dataset.act === "shown") {
      const rest = hidden().filter((s) => s !== slug);
      void save({ hidden: input.checked ? rest : [...rest, slug] });
    }
  });

  /** A row's Preview: the saved tone's parts under the row, without opening the editor; again to close. */
  async function toggleRowPreview(row: HTMLElement, button: HTMLElement, slug: string) {
    const box = row.querySelector<HTMLElement>("[data-row-preview]")!;
    const opening = box.hidden;
    box.hidden = !opening;
    button.setAttribute("aria-expanded", String(opening));
    if (!opening) return;
    box.innerHTML = promptPreviewMessage("Loading…");
    try {
      box.innerHTML = promptPreviewHtml(tonePreviewView(await previewTone({ slug })));
    } catch (err) {
      box.innerHTML = promptPreviewMessage(errorText(err), true);
    }
  }

  list.addEventListener("click", (e) => {
    const button = (e.target as HTMLElement).closest<HTMLElement>("[data-act]");
    const act = button?.dataset.act;
    const row = (e.target as HTMLElement).closest<HTMLElement>(".tone-row");
    const slug = row?.dataset.slug;
    const tone = state.tones.find((t) => t.slug === slug);
    if (tone && act === "preview") return void toggleRowPreview(row!, button!, tone.slug);
    if (!tone || tone.builtin) return;
    if (act === "edit") openForm(tone);
    if (act === "delete" && confirm(`Delete the tone “${tone.name}”?`)) {
      void save({
        tones: custom()
          .filter((t) => t.slug !== tone.slug)
          .map(toInput),
        hidden: hidden().filter((s) => s !== tone.slug),
      });
    }
  });

  render();
}

export function mountToneEditors(): void {
  document.querySelectorAll<HTMLElement>("[data-tone-editor]").forEach((root) => {
    if (root.dataset.mounted) return;
    root.dataset.mounted = "1";
    mount(root);
  });
}
