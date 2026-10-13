/**
 * Prompt previews — what the model is sent, in parts labelled by where each comes from. Three places show one:
 * a tone (AI settings → Tones, the row's Preview and the editor's Preview prompt), the Character (AI settings →
 * Persona, with the workspace default tone) and an agent (Agents → Edit → Preview prompt). They all render
 * through `promptPreviewHtml` so they read the same; styles are `.prompt-preview*` in styles/global.css.
 *
 * Pure: each builder turns an API answer into a `PromptPreviewView`, the renderer turns that into HTML for the
 * caller's box. The runtime import is relative so `node --test` can load this file (promptPreview.test.mjs).
 */

import { type TonePreview, previewSections } from "./tones.ts";

/** One labelled piece of the prompt, in prompt order. */
export interface PromptPart {
  /** Where the text comes from, e.g. "From this tone". */
  label: string;
  /** Linked words after the label, e.g. "Persona" → the Persona section. */
  labelLink?: { text: string; href: string };
  /** A plain-words aside after the label, e.g. "how it delivers". */
  hint?: string;
  text: string;
  /** Shown in place of the text when there is none. */
  emptyNote?: string;
  /** Long background text (the workspace preamble, the roster) starts folded. */
  folded?: boolean;
  /** The precedence rule: shown as "Which wins", not as prompt text in a box. */
  isRule?: boolean;
}

export interface PromptPreviewView {
  /** One line on top: the persona rule, or which tone applies. */
  summary?: string;
  parts: PromptPart[];
  /** Plain lines after the parts, e.g. the tools summary. */
  notes?: string[];
  /** The whole prompt text, exactly as sent. */
  full: string;
  tokensNote: string;
}

/** POST /api/ai/agents/{slug}/preview-prompt. */
export interface AgentPromptPreview {
  system: string;
  tokens: number;
  kind: "persona" | "model";
  /** The workspace preamble ("" for a model agent). */
  workspace: string;
  instructions: string;
  /** `instructions` is its kind's default: the agent has none of its own. */
  defaultInstructions: boolean;
  tone: TonePreview;
  toneSource: "agent" | "workspace";
  /** The agents it may hand off or refer to ("" when it can do neither). */
  roster: string;
  toolCount: number;
  askFirstCount: number;
  toolCategories: { id: string; label: string; count: number }[];
}

export const PERSONA_HREF = "/workspace/settings/ai-workflow#persona-section";

const esc = (s: unknown) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!,
  );

/**
 * The Character, tone and "which wins" parts of a tone preview. `toneLabel` says which tone this is where it is
 * shown; `characterHere` is for the Persona section itself, where "your Persona" would point at the same page.
 */
export function toneParts(
  p: TonePreview,
  opts: { toneLabel: string; toneHint?: string; characterHere?: boolean },
): PromptPart[] {
  const s = previewSections(p);
  const character: PromptPart = opts.characterHere
    ? {
        label: "From the Character field",
        hint: "who your assistant is",
        text: s.character,
        emptyNote: s.characterNote,
      }
    : {
        label: "From your",
        labelLink: { text: "Persona", href: PERSONA_HREF },
        hint: "who your assistant is",
        text: s.character,
        emptyNote: s.characterNote,
      };
  const parts: PromptPart[] = [
    character,
    { label: opts.toneLabel, hint: opts.toneHint ?? "how it delivers", text: s.fromTone, emptyNote: s.fromToneNote },
  ];
  if (s.rule) parts.push({ label: "Which wins", text: s.rule, isRule: true });
  return parts;
}

/** A tone on its own: its row's Preview, or the tone editor's Preview prompt. */
export function tonePreviewView(p: TonePreview): PromptPreviewView {
  return {
    summary: p.personaSummary,
    parts: toneParts(p, { toneLabel: "From this tone" }),
    full: p.clause.trim(),
    tokensNote: `About ${p.tokens} tokens on every agent step (with this workspace's character).`,
  };
}

/** The Character box: the character as the workspace default tone places it. */
export function characterPreviewView(p: TonePreview): PromptPreviewView {
  const tone = p.toneName || p.toneSlug || "the default tone";
  return {
    summary: `With the workspace default tone, ${tone} — ${p.personaSummary}`,
    parts: toneParts(p, { toneLabel: `From the default tone (${tone})`, characterHere: true }),
    full: p.clause.trim(),
    tokensNote: `About ${p.tokens} tokens on every agent step that uses the default tone. Unsaved changes above are included.`,
  };
}

/** The tools line: how many are bound and in which matrix rows; their definitions are not shown. */
export function toolsNote(p: AgentPromptPreview): string {
  if (p.kind === "model") return "No tools: a model agent is plain chat.";
  if (!p.toolCount) return "No tools are bound for you: every row of its matrix blocks.";
  const rows = p.toolCategories.map((c) => `${c.label} (${c.count})`).join(", ");
  const ask = p.askFirstCount ? `, ${p.askFirstCount} of them ask first` : "";
  return `${p.toolCount} tools, as you would run it from Ask${ask}: ${rows}. Their definitions are sent too and aren't shown here.`;
}

/** An agent: everything its system prompt holds, in prompt order. */
export function agentPreviewView(p: AgentPromptPreview): PromptPreviewView {
  const tone = p.tone.toneName || p.tone.toneSlug;
  const where = p.toneSource === "agent" ? "this agent's default tone" : "the workspace default tone";
  const parts: PromptPart[] = [];
  if (p.workspace) {
    parts.push({
      label: "Workspace context",
      hint: "added to every agent with tools: what the workspace holds and which tool answers what",
      text: p.workspace,
      folded: true,
    });
  }
  parts.push(
    p.defaultInstructions
      ? { label: "Default instructions", hint: "this agent has none of its own", text: p.instructions }
      : { label: "From this agent", hint: "its instructions", text: p.instructions },
  );
  parts.push(...toneParts(p.tone, { toneLabel: `From the tone ${tone}`, toneHint: `how it delivers — ${where}` }));
  if (p.roster) {
    parts.push({ label: "Other agents", hint: "who it can hand off to or suggest", text: p.roster, folded: true });
  }
  return {
    summary: `Tone: ${tone} (${where}). ${p.tone.personaSummary}`,
    parts,
    notes: [toolsNote(p)],
    full: p.system,
    tokensNote: `About ${p.tokens} tokens of system prompt on every step, before the conversation and what the user is looking at.`,
  };
}

function partHtml(part: PromptPart): string {
  if (part.isRule) return `<p class="prompt-preview-rule"><strong>${esc(part.label)}:</strong> ${esc(part.text)}</p>`;
  const link = part.labelLink ? ` <a href="${esc(part.labelLink.href)}">${esc(part.labelLink.text)}</a>` : "";
  const hint = part.hint ? ` <small class="prompt-part-hint">— ${esc(part.hint)}</small>` : "";
  const label = `${esc(part.label)}${link}${hint}`;
  const body = part.text
    ? `<pre>${esc(part.text)}</pre>`
    : `<p class="prompt-part-empty">${esc(part.emptyNote ?? "Nothing.")}</p>`;
  if (part.folded) {
    return `<details class="prompt-part"><summary class="prompt-part-label">${label}</summary>${body}</details>`;
  }
  return `<div class="prompt-part"><div class="prompt-part-label">${label}</div>${body}</div>`;
}

/** The preview's HTML, for a `.prompt-preview` box. */
export function promptPreviewHtml(v: PromptPreviewView): string {
  const summary = v.summary ? `<p class="prompt-preview-summary">${esc(v.summary)}</p>` : "";
  const notes = (v.notes ?? []).map((n) => `<p class="prompt-preview-note">${esc(n)}</p>`).join("");
  return `${summary}${v.parts.map(partHtml).join("")}${notes}
    <details class="prompt-preview-full"><summary>Full prompt text</summary><pre>${esc(v.full)}</pre></details>
    <small class="prompt-preview-tokens">${esc(v.tokensNote)}</small>`;
}

/** A one-line status in the box (loading, or why the preview failed). */
export function promptPreviewMessage(text: string, isError = false): string {
  return `<p class="prompt-preview-note${isError ? " is-error" : ""}">${esc(text)}</p>`;
}
