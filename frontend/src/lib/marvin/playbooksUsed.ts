// The "Used: …" line under an Ask reply: the Playbooks that steered it, then the tools it called. It is drawn by the UI from the
// reply's `playbooks` (the run response's field, or the stored turn's `metaJson.playbooks`), never written into the model's text.
// Pure, so `npm test` covers it (playbooksUsed.test.mjs). Shared by the Ask page and the bubble.

// Not `esc` from capabilities.ts: that module imports this one (and the DOM libraries), so it would be a cycle and `npm test` could not load it.
import { escapeHtml as esc } from "../askThreads.ts";

export interface UsedPlaybook {
  id: string;
  name?: string | null;
}


/** Playbook names in the order given, each once; entries without a name are skipped. */
export function playbookNames(playbooks: UsedPlaybook[] | null | undefined): string[] {
  const names: string[] = [];
  for (const p of playbooks ?? []) {
    const name = (p?.name ?? "").trim();
    if (name && !names.includes(name)) names.push(name);
  }
  return names;
}

/**
 * The inside of the "Used:" line ("" when there is nothing to say): `<span>Used:</span>`, the Playbook names, then the tool names
 * as `<code>`. `load_playbook` is left out of the tools when the Playbooks are named, as it would only say it twice.
 */
export function usedHtml(tools: string[] | null | undefined, playbooks?: UsedPlaybook[] | null): string {
  const names = playbookNames(playbooks);
  const used = [...new Set(tools ?? [])].filter((t) => !(names.length && t === "load_playbook"));
  if (!names.length && !used.length) return "";
  const books = names.map((n) => `<span class="playbook-used" title="Playbook">${esc(n)}</span>`);
  return `<span>Used:</span> ${[...books, ...used.map((t) => `<code>${esc(t)}</code>`)].join(" ")}`;
}
