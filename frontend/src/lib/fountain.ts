/**
 * Fountain, the plain-text screenplay format (fountain.io/syntax), read for a preview: the text a person writes becomes the elements it means
 * (title page, scene headings, action, dialogue, transitions, sections), so a long text field can show the screenplay it holds.
 *
 * It follows the format's own rules and nothing else: a slip in the writing reads as it would anywhere (a lower-case name is action, a
 * transition with no colon is action), which is also what shows the slip. Pure: no DOM, no network.
 */

export type DialogueLine = { kind: "dialogue" | "parenthetical" | "lyrics"; text: string };

export type DialogueBlock = { kind: "dialogue"; character: string; extension: string; dual: boolean; lines: DialogueLine[] };

export type FountainBlock =
  | { kind: "title"; pairs: { key: string; value: string }[] }
  | { kind: "scene"; text: string; number: string }
  | { kind: "action"; text: string }
  | { kind: "dialogue"; character: string; extension: string; dual: boolean; lines: DialogueLine[] }
  | { kind: "dual"; left: DialogueBlock; right: DialogueBlock }
  | { kind: "lyrics"; text: string }
  | { kind: "transition"; text: string }
  | { kind: "centered"; text: string }
  | { kind: "section"; depth: number; text: string }
  | { kind: "synopsis"; text: string }
  | { kind: "note"; text: string }
  | { kind: "break" };

const SCENE = /^(?:INT|EXT|EST|INT\.?\/EXT|INT\/EXT|I\/E)(?:\.|\s)/i;
const TITLE_KEY = /^([A-Za-z][A-Za-z0-9 _-]*):[ \t]*(.*)$/;
const INDENTED = /^(?: {3,}|\t)/;

const isBlank = (line: string): boolean => line.length === 0 || (line.trim() === "" && line !== "  ");

/** A name in capitals, which is what makes a line a speaker: at least one letter and no lower case outside the extension in brackets. */
function isCue(text: string): boolean {
  const name = text.replace(/\([^)]*\)/g, "").replace(/\^\s*$/, "").trim();
  return /[A-Z]/.test(name) && name === name.toUpperCase() && !/^[!#=>~.@]/.test(name) && !/^\[\[/.test(name);
}

function titlePage(lines: string[]): { pairs: { key: string; value: string }[]; used: number } | null {
  const first = lines[0]?.match(TITLE_KEY);
  // "CUT TO:" is a transition, not a title page: a title page's first key has a value, or an indented one under it
  if (!first || !(first[2].trim() || (lines[1] && INDENTED.test(lines[1])))) return null;
  const pairs: { key: string; value: string }[] = [];
  let used = 0;
  for (const line of lines) {
    if (isBlank(line)) break;
    const key = line.match(TITLE_KEY);
    if (key && !INDENTED.test(line)) pairs.push({ key: key[1].trim(), value: key[2].trim() });
    else if (INDENTED.test(line) && pairs.length) pairs[pairs.length - 1].value = [pairs[pairs.length - 1].value, line.trim()].filter(Boolean).join("\n");
    else return null; // a line that is neither: this is not a title page, it is action that starts with a word and a colon
    used++;
  }
  return pairs.length ? { pairs, used } : null;
}

/** The text as Fountain's elements, in order. Empty for text with nothing in it. */
export function parseFountain(source: string): FountainBlock[] {
  const text = String(source ?? "").replace(/\r\n?/g, "\n").replace(/\/\*[\s\S]*?\*\//g, ""); // a boneyard (/* ... */) is not part of the script
  const all = text.split("\n");
  const out: FountainBlock[] = [];

  let start = 0;
  while (start < all.length && isBlank(all[start])) start++;
  const title = titlePage(all.slice(start));
  if (title) {
    out.push({ kind: "title", pairs: title.pairs });
    start += title.used;
  }

  const blocks: string[][] = [];
  let current: string[] = [];
  for (const line of all.slice(start)) {
    if (isBlank(line)) {
      if (current.length) blocks.push(current);
      current = [];
    } else current.push(line);
  }
  if (current.length) blocks.push(current);

  for (const lines of blocks.filter((l) => l.some((row) => row.trim()))) {
    if (lines[0].trimStart().startsWith("[[") && lines.join("\n").trimEnd().endsWith("]]") && !lines.join("\n").slice(2).includes("]]\n")) {
      out.push({ kind: "note", text: lines.join("\n").trim().slice(2, -2).trim() });
      continue;
    }
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      const text = line.trim();
      const before = out[out.length - 1];
      const afterHeading = i === 0 || (before && ["section", "synopsis", "scene", "break"].includes(before.kind));
      let m: RegExpMatchArray | null;
      if (/^={3,}\s*$/.test(text)) {
        out.push({ kind: "break" });
        i++;
      } else if ((m = text.match(/^(#{1,6})\s*(.*)$/))) {
        out.push({ kind: "section", depth: m[1].length, text: m[2] });
        i++;
      } else if ((m = text.match(/^=(?!=)\s*(.*)$/))) {
        out.push({ kind: "synopsis", text: m[1] });
        i++;
      } else if (text.startsWith("~")) {
        const sung: string[] = [];
        while (i < lines.length && lines[i].trim().startsWith("~")) sung.push(lines[i++].trim().replace(/^~\s*/, ""));
        out.push({ kind: "lyrics", text: sung.join("\n") });
      } else if (afterHeading && (/^\.(?!\.)./.test(text) || (SCENE.test(text) && !/^\.\./.test(text)))) {
        const forced = text.startsWith(".");
        const number = text.match(/\s#([^#\n]+)#\s*$/);
        const heading = (forced ? text.slice(1) : text).replace(/\s#([^#\n]+)#\s*$/, "").trim();
        out.push({ kind: "scene", text: heading, number: number ? number[1] : "" });
        i++;
      } else if ((m = text.match(/^>\s*(.+?)\s*<$/))) {
        out.push({ kind: "centered", text: m[1] });
        i++;
      } else if (lines.length === 1 && i === 0 && (/^>(?!.*<$)/.test(text) || (text === text.toUpperCase() && /TO:$/.test(text)))) {
        out.push({ kind: "transition", text: text.replace(/^>\s*/, "") });
        i++;
      } else if (i === 0 && lines.length > 1 && !text.startsWith("!") && (text.startsWith("@") || isCue(text))) {
        const forced = text.startsWith("@");
        const raw = (forced ? text.slice(1) : text).trim();
        const dual = /\^\s*$/.test(raw);
        const bare = raw.replace(/\^\s*$/, "").trim();
        const ext = bare.match(/\s*(\([^)]*\))\s*$/);
        const body: DialogueLine[] = [];
        for (const row of lines.slice(1)) {
          const t = row.trim();
          if (/^\(.*\)$/.test(t)) body.push({ kind: "parenthetical", text: t });
          else if (t.startsWith("~")) body.push({ kind: "lyrics", text: t.replace(/^~\s*/, "") });
          else body.push({ kind: "dialogue", text: row === "  " ? "" : t });
        }
        const speech: DialogueBlock = { kind: "dialogue", character: ext ? bare.slice(0, ext.index).trim() : bare, extension: ext ? ext[1] : "", dual, lines: body };
        // a cue ending in ^ plays beside the speech before it: the two are one block, drawn in two columns
        if (dual && before?.kind === "dialogue" && !before.dual) out[out.length - 1] = { kind: "dual", left: before, right: speech };
        else out.push(speech);
        i = lines.length;
      } else {
        const rest = lines.slice(i);
        const forced = rest[0].trimStart().startsWith("!");
        if (forced) rest[0] = rest[0].replace(/^(\s*)!/, "$1");
        out.push({ kind: "action", text: rest.join("\n").replace(/^\n+|\n+$/g, "") });
        i = lines.length;
      }
    }
  }
  return out;
}

const ESCAPES: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const escape = (text: string): string => text.replace(/[&<>"']/g, (c) => ESCAPES[c]);

/** One piece of writing as HTML: emphasis (`*italic*`, `**bold**`, `***both***`, `_underline_`) read, everything else escaped. Notes are handled by `inline`. */
function emphasis(text: string): string {
  const kept: string[] = [];
  let work = escape(text).replace(/\\([*_\\])/g, (_all, c: string) => `\u0000${kept.push(c) - 1}\u0000`);
  work = work
    .replace(/\*{3}(?=\S)([^\n]+?)(?<=\S)\*{3}/g, "<b><i>$1</i></b>")
    .replace(/\*{2}(?=\S)([^\n]+?)(?<=\S)\*{2}/g, "<b>$1</b>")
    .replace(/\*(?=\S)([^\n*]+?)(?<=\S)\*/g, "<i>$1</i>")
    .replace(/_(?=\S)([^\n_]+?)(?<=\S)_/g, "<u>$1</u>");
  return work.replace(/\u0000(\d+)\u0000/g, (_all, n: string) => kept[Number(n)]).replace(/\n/g, "<br>");
}

/** Writing with its notes (`[[ ... ]]`) shown quietly, since they are about the script and not in it. */
export function inline(text: string): string {
  return String(text ?? "")
    .split(/(\[\[[\s\S]*?\]\])/g)
    .map((part) => (part.startsWith("[[") && part.endsWith("]]") ? `<span class="ft-note">${escape(part.slice(2, -2).trim())}</span>` : emphasis(part)))
    .join("");
}

function dialogueHtml(b: DialogueBlock): string {
  const lines = b.lines.map((l) => `<p class="ft-${l.kind === "dialogue" ? "line" : l.kind === "parenthetical" ? "paren" : "lyrics"}">${inline(l.text)}</p>`).join("");
  return `<div class="ft-dialogue"><p class="ft-cue">${escape(b.character)}${b.extension ? ` <span class="ft-ext">${escape(b.extension)}</span>` : ""}</p>${lines}</div>`;
}

/** The screenplay as HTML for a preview. Every piece of the text is escaped; the markup is this function's own. */
export function fountainToHtml(source: string): string {
  const blocks = parseFountain(source);
  if (!blocks.length) return "";
  const html = blocks.map((b): string => {
    switch (b.kind) {
      case "title": {
        const head = b.pairs.filter((p) => /^(title|credit|author|authors|source)$/i.test(p.key));
        const rest = b.pairs.filter((p) => !head.includes(p));
        const title = b.pairs.find((p) => /^title$/i.test(p.key));
        const lines = head.filter((p) => p !== title).map((p) => `<p class="ft-title-line">${inline(p.value)}</p>`).join("");
        const facts = rest.map((p) => `<p class="ft-title-fact"><span>${escape(p.key)}</span> ${inline(p.value)}</p>`).join("");
        return `<div class="ft-titlepage">${title ? `<h1 class="ft-title">${inline(title.value)}</h1>` : ""}${lines}${facts}</div>`;
      }
      case "scene":
        return `<p class="ft-scene">${emphasis(b.text)}${b.number ? `<span class="ft-scene-no">${escape(b.number)}</span>` : ""}</p>`;
      case "action":
        return `<p class="ft-action">${inline(b.text)}</p>`;
      case "dialogue":
        return dialogueHtml(b);
      case "dual":
        return `<div class="ft-dual">${dialogueHtml(b.left)}${dialogueHtml(b.right)}</div>`;
      case "lyrics":
        return `<p class="ft-lyrics ft-sung">${inline(b.text)}</p>`;
      case "transition":
        return `<p class="ft-transition">${emphasis(b.text)}</p>`;
      case "centered":
        return `<p class="ft-centered">${inline(b.text)}</p>`;
      case "section":
        return `<p class="ft-section ft-depth-${b.depth}">${emphasis(b.text)}</p>`;
      case "synopsis":
        return `<p class="ft-synopsis">${inline(b.text)}</p>`;
      case "note":
        return `<p class="ft-note-block">${escape(b.text)}</p>`;
      case "break":
        return `<hr class="ft-break">`;
    }
  });
  return `<div class="ft-page">${html.join("")}</div>`;
}

// ── a toolbar's edits ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

export type FountainTool = "scene" | "action" | "dual" | "character" | "parenthetical" | "transition" | "centered" | "section" | "synopsis" | "lyrics" | "break" | "note" | "bold" | "italic" | "underline";

/** What the text and its selection are after a toolbar button: the new text, and the part to leave selected so typing replaces the placeholder. */
export interface FountainEdit {
  value: string;
  start: number;
  end: number;
}

const INLINE: Partial<Record<FountainTool, [string, string, string]>> = {
  note: ["[[", "]]", "note"],
  bold: ["**", "**", "bold"],
  italic: ["*", "*", "italic"],
  underline: ["_", "_", "underlined"],
};

/** The blank lines a paragraph needs between itself and what comes before it (none at the very start), given the text before it. */
const breaksBefore = (before: string): string => (before === "" || before.endsWith("\n\n") ? "" : before.endsWith("\n") ? "\n" : "\n\n");
/** The same after it: a blank line before the next paragraph, and room to keep writing at the end of the text. */
const breaksAfter = (after: string): string => (after.startsWith("\n\n") ? "" : after.startsWith("\n") ? "\n" : "\n\n");

const oneLine = (text: string): string => text.replace(/\s*\n\s*/g, " ").trim();

/** The element's text for a tool, given the selected words (or none): where inside it the placeholder sits, so it can be selected. */
function elementFor(tool: FountainTool, picked: string): { text: string; from: number; to: number } {
  const words = oneLine(picked);
  const slot = (before: string, fill: string, after = "") => ({ text: before + fill + after, from: before.length, to: before.length + fill.length });
  switch (tool) {
    case "scene": {
      if (/^(?:INT|EXT|EST|INT\.?\/EXT|INT\/EXT|I\/E)[. ]/i.test(words)) return slot("", words.toUpperCase());
      return slot("INT. ", (words || "PLACE").toUpperCase(), " - DAY");
    }
    case "character": {
      // the selection, when there is one, is what is said; the name is left to type
      const said = picked.trim() || "Dialogue.";
      return { text: `NAME\n${said}`, from: 0, to: 4 };
    }
    case "transition": {
      const text = words ? words.toUpperCase().replace(/:?$/, ":") : "CUT TO:";
      return { text, from: 0, to: words ? text.length : 3 };
    }
    case "action": {
      // forced action: a ! makes a line action even when it looks like a heading or a name; a selection keeps its own lines
      const kept = picked.trim() || "Action line";
      return { text: `!${kept}`, from: 1, to: 1 + kept.length };
    }
    case "centered":
      return slot("> ", words || "TEXT", " <");
    case "section":
      return slot("# ", words || "ACT I");
    case "synopsis":
      return slot("= ", words || "What happens here.");
    case "lyrics":
      return slot("~", words || "A line of the song");
    case "parenthetical":
      return slot("(", words || "delivery", ")");
    case "break":
      return { text: "===", from: 3, to: 3 };
    default:
      return { text: "", from: 0, to: 0 };
  }
}

/** The paragraph around a position: where it starts and ends (the blank lines either side), so an edit can read the speech the cursor is in. */
function paragraphAround(value: string, at: number): { start: number; end: number } {
  const before = value.lastIndexOf("\n\n", Math.max(0, at - 1));
  const after = value.indexOf("\n\n", at);
  return { start: before < 0 ? 0 : before + 2, end: after < 0 ? value.length : after };
}

/** Dual dialogue: in a speech, the speaker's cue gets (or loses) a ^ so it plays beside the speech before it; anywhere else, a second speaker is written in. */
function dualEdit(value: string, from: number, to: number): FountainEdit {
  const { start, end } = paragraphAround(value, from);
  const paragraph = value.slice(start, end);
  const cueEnd = paragraph.indexOf("\n");
  const cue = cueEnd < 0 ? paragraph : paragraph.slice(0, cueEnd);
  if (cueEnd > 0 && cue.trim() && isCue(cue.trim())) {
    const marked = /\s*\^\s*$/.test(cue);
    const newCue = marked ? cue.replace(/\s*\^\s*$/, "") : `${cue.trimEnd()} ^`;
    const next = value.slice(0, start) + newCue + value.slice(start + cue.length);
    const shift = newCue.length - cue.length;
    return { value: next, start: Math.max(start, from + (from > start + cue.length ? shift : 0)), end: Math.max(start, to + (to > start + cue.length ? shift : 0)) };
  }
  const before = value.slice(0, to);
  const after = value.slice(to);
  const lead = breaksBefore(before);
  const text = "NAME ^\nDialogue.";
  const at = before.length + lead.length;
  return { value: before + lead + text + breaksAfter(after) + after, start: at, end: at + 4 };
}

/**
 * A toolbar button's edit: the text with the element written in at the selection, the selection's words used in it, and a placeholder selected for
 * typing over. A paragraph element (a scene heading, a speaker, a transition, a centered line, a section, a synopsis, lyrics, a page break) starts its
 * own paragraph, with a blank line either side, since Fountain reads elements by their blank lines; a parenthetical starts its own line; a note,
 * bold, italic and underline wrap the selection where it stands.
 */
export function applyFountain(tool: FountainTool, value: string, start: number, end: number): FountainEdit {
  const from = Math.max(0, Math.min(start, end, value.length));
  const to = Math.min(value.length, Math.max(start, end));
  const before = value.slice(0, from);
  const after = value.slice(to);
  const picked = value.slice(from, to);

  const wrap = INLINE[tool];
  if (wrap) {
    const [open, close, placeholder] = wrap;
    const inner = picked || placeholder;
    const at = before.length + open.length;
    return { value: before + open + inner + close + after, start: at, end: at + inner.length };
  }

  if (tool === "dual") return dualEdit(value, from, to);

  const element = elementFor(tool, picked);
  const lead = tool === "parenthetical" ? (before === "" || before.endsWith("\n") ? "" : "\n") : breaksBefore(before);
  const trail = tool === "parenthetical" ? (after.startsWith("\n") || after === "" ? "" : "\n") : breaksAfter(after);
  const at = before.length + lead.length;
  const next = before + lead + element.text + trail + after;
  return element.from === element.to && tool === "break" ? { value: next, start: at + element.text.length + trail.length, end: at + element.text.length + trail.length } : { value: next, start: at + element.from, end: at + element.to };
}
