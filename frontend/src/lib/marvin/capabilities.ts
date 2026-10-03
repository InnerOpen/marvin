/**
 * Marvin — pluggable capability registry.
 *
 * Marvin (the Paranoid Android) is a command surface, not just RAG. Each capability is a
 * self-contained skill: give it slash-command aliases (or mark it the default free-text
 * handler) and a run() that returns rendered HTML. Adding a skill = push one object onto
 * CAPABILITIES (or call registerCapability); the bubble discovers it automatically and it
 * shows up in /help. Future skills — publish, rebuild, test, review — dispatch to their
 * existing endpoints the same way.
 */

import DOMPurify from "dompurify";
import { marked } from "marked";
import { getRunProgress, getThread, NEW_THREAD, type RunProgress } from "@/lib/api/aiAgents";
import { askWorkspace, listAgents, runAgent, runAgentAs, sendChat } from "@/lib/api/aiBubble";
import { listAgentTools } from "@/lib/api/aiTools";
import { getActiveContext } from "@/lib/marvin/context";
import {
  askThreadHref,
  clearPending,
  learnWhileInFlight,
  loadPending,
  newRunId,
  ownsPending,
  PENDING_RUN_TIMEOUT_MS,
  type PendingRun,
  type RecoveryDeps,
  recoverPendingRun,
  rememberThread,
  savePending,
  scoped,
  threadFor,
} from "@/lib/marvin/pending";

export interface MarvinResult {
  /** Safe HTML for Marvin's reply. Escape ALL dynamic content with esc(). */
  html: string;
  /**
   * The server execution behind an agent reply. The bubble keeps it with the turn so a reply that
   * is recovered after a navigation is never shown twice.
   */
  executionId?: string;
  /** The agent run paused for the user's approval rather than answering. */
  parked?: boolean;
}

export interface Capability {
  id: string;
  label: string;
  /** One-line description shown in /help. */
  hint: string;
  /** Slash-command aliases that route to this capability, e.g. ['ask']. */
  commands: string[];
  /** If true, handles free-text input that matched no slash command. Only one should be default. */
  isDefault?: boolean;
  /** If true, the command runs with no argument (e.g. /tools). Skips the "give me something" guard. */
  noArg?: boolean;
  /** Execute the skill. `arg` is the text after the command (or the whole input for the default). */
  run(arg: string): Promise<MarvinResult>;
}

export type MarvinRegister = "auto" | "professional" | "playful";

/**
 * Tone register for the NEXT agent run, set by whoever triggered it (e.g. the entry editor's
 * "Review & suggest" asks for 'professional' so findings come back plain rather than in
 * character). One-shot: consumed by the run, so a typed follow-up isn't silently affected.
 */
let pendingRegister: MarvinRegister | undefined;

export function setPendingRegister(register: MarvinRegister | undefined): void {
  pendingRegister = register;
}

function takeRegister(): MarvinRegister | undefined {
  const r = pendingRegister;
  pendingRegister = undefined;
  return r;
}

/** Escape untrusted text before putting it in innerHTML (attributes, inline chips, etc.). */
export function esc(s: unknown): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Render Marvin's answer (markdown from the model) to sanitized HTML for innerHTML.
 * The model output is untrusted (prompt-injectable via workspace content), so we sanitize with
 * DOMPurify after marked — never inject raw model HTML.
 */
export function renderMarkdown(text: unknown): string {
  const raw = marked.parse(String(text ?? ""), { async: false }) as string;
  return DOMPurify.sanitize(raw);
}

function entityHref(type: string, id: string): string | null {
  if (type === "entry") return `/workspace/entries/${id}`;
  if (type === "resource") return `/workspace/resources/${id}`;
  return null;
}

interface Thumb {
  url: string;
  alt: string;
  entryId?: string;
  title?: string;
}

/**
 * Deterministic thumbnail source: pull image assets (with real urls) out of the agent's tool
 * results — get_entry (`assets`) and find_entries (`entries[].assets`) — rather than trusting the
 * model to embed image URLs. Deduped by asset id; each thumb links to its parent entry.
 */
function collectThumbs(steps: any[]): Thumb[] {
  const out: Thumb[] = [];
  const seen = new Set<string>();
  const add = (a: any, entryId?: string, title?: string) => {
    if (a?.assetType !== "image" || !a.url || seen.has(a.id)) return;
    seen.add(a.id);
    out.push({ url: a.url, alt: a.altText || a.filename || title || "", entryId, title });
  };
  for (const s of steps) {
    let r: any;
    try {
      r = typeof s.result === "string" ? JSON.parse(s.result) : s.result;
    } catch {
      continue;
    }
    if (!r) continue;
    if (Array.isArray(r.assets)) for (const a of r.assets) add(a, r.id, r.title); // get_entry
    if (Array.isArray(r.entries)) {
      for (const e of r.entries) if (Array.isArray(e.assets)) for (const a of e.assets) add(a, e.id, e.title); // find_entries
    }
    if (Array.isArray(r.results)) {
      // search_content: entry hits carry DB-hydrated image refs; link to the entity.
      for (const hit of r.results)
        if (Array.isArray(hit.assets))
          for (const a of hit.assets) add(a, hit.entityType === "entry" ? hit.entityId : undefined, hit.title);
    }
  }
  return out;
}

/** Render a thumbnail strip (each linked to its entry) from collected image assets. */
function thumbsHtml(steps: any[], cap = 12): string {
  const thumbs = collectThumbs(steps);
  if (!thumbs.length) return "";
  const items = thumbs.slice(0, cap).map((t) => {
    const img = `<img src="${esc(t.url)}" alt="${esc(t.alt)}" title="${esc(t.title || "")}" loading="lazy" />`;
    const href = t.entryId ? entityHref("entry", t.entryId) : null;
    return href ? `<a class="mv-thumb" href="${esc(href)}">${img}</a>` : `<span class="mv-thumb">${img}</span>`;
  });
  return `<div class="mv-thumbs">${items.join("")}</div>`;
}

// ── Built-in skill: Agent (tool-calling loop) ────────────────────────────────
// The default free-text handler. Give Marvin a goal; it decides which of its tools to use
// (search, browse, list types, compose a draft), chaining as many as needed, then answers.
// The conversation is a server thread per agent (the Ask page lists the same threads): the server
// replays it as the agent's memory, and the answer is stored there even if this page is gone by
// the time it arrives (see @/lib/marvin/pending).
const agent: Capability = {
  id: "agent",
  label: "Agent",
  hint: "Give me a goal — I search, browse, and draft to get it done.",
  commands: ["agent", "do"],
  isDefault: true,
  async run(arg: string): Promise<MarvinResult> {
    return runBubbleAgent(getActiveAgent(), arg, takeRegister());
  },
};

/** The server's answer when a message names a thread that no longer exists (deleted on the Ask page). */
const THREAD_GONE = /^No thread '/;
const HTTP_NOT_FOUND = 404;

async function runBubbleAgent(
  slug: string,
  arg: string,
  register: MarvinRegister | undefined,
  retried = false,
): Promise<MarvinResult> {
  // Pending until the answer is in hand: if this page goes away mid-run, the next one picks the
  // answer up from the server (resumePendingRun).
  const run: PendingRun = {
    clientRunId: newRunId(),
    agent: slug,
    message: arg,
    sentAt: Date.now(),
    threadId: threadFor(slug),
  };
  savePending(run);
  const stopLearning = learnWhileInFlight(run, pendingDeps(run));
  const ref = { threadId: run.threadId ?? NEW_THREAD, clientRunId: run.clientRunId };
  let res: any;
  try {
    // Ground the run in whatever the current page declared (see @/lib/marvin/context), so
    // "review and suggest" works without naming the entity. Null when the page declared no
    // context or the user dismissed it — then this is a plain, unscoped ask.
    res =
      slug === "marvin"
        ? await runAgent(arg, getActiveContext(), ref, register)
        : await runAgentAs(slug, arg, getActiveContext(), ref, register);
  } catch (err: any) {
    stopLearning();
    // The call can fail while the run carries on server-side (the SDK stops waiting after two
    // minutes; a proxy may drop a long request) — then wait for the answer instead of reporting
    // an error that isn't one.
    if (ownsPending(run) && (await serverStillHas(run))) {
      const recovered = await resumePendingRun(loadPending() ?? run);
      if (recovered) return recovered;
    }
    if (ownsPending(run)) clearPending();
    const msg = String(err?.message || err);
    // The SDK reports a 404 as "Resource not found: <path>", hiding the server's "No thread" detail.
    const threadGone = THREAD_GONE.test(msg) || err?.statusCode === HTTP_NOT_FOUND;
    if (run.threadId && !retried && threadGone) {
      rememberThread(slug, null);
      return runBubbleAgent(slug, arg, register, true);
    }
    // The agent needs a tool-capable provider; degrade to a helpful hint rather than snark.
    if (/tool.?call|tool-capable|does not support/i.test(msg)) {
      return {
        html: `<div class="mv-answer">This workspace's AI provider can't run the full agent (no tool-calling). Try <code>/ask</code> for a quick answer from your content instead.</div>`,
      };
    }
    throw err; // let the bubble show its standard error
  }
  stopLearning();
  // A "Clear" pressed meanwhile already started a new conversation: don't re-attach this thread.
  if (ownsPending(run)) {
    clearPending();
    if (res?.threadId) rememberThread(slug, res.threadId);
  }
  if (res?.stoppedReason === "awaiting_approval") {
    return {
      html: parkedHtml(
        res.threadId,
        (res.pending ?? []).map((c: any) => c.tool),
      ),
      parked: true,
    };
  }
  return {
    html: agentReplyHtml(res?.answer ?? "(no answer — the void stares back)", res?.steps ?? []),
    executionId: res?.executionId,
  };
}

async function serverStillHas(run: PendingRun): Promise<boolean> {
  try {
    return (await getRunProgress(run.clientRunId)).status !== "failed";
  } catch {
    return false; // unknown to the server: the request never got there, or it already said why
  }
}

/** Hears every progress poll of the bubble's agent runs — the bubble character, to show the agent at work. */
let progressListener: ((progress: RunProgress) => void) | undefined;

export function onRunProgress(listener: ((progress: RunProgress) => void) | undefined): void {
  progressListener = listener;
}

function pendingDeps(run: PendingRun): RecoveryDeps {
  const listener = progressListener;
  return {
    // Only when someone listens: otherwise in-flight polling stops as soon as the ids are known.
    onProgress: listener,
    getRunProgress: (id) => getRunProgress(id),
    getThread: (id) => getThread(id),
    sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    now: () => Date.now(),
    onUpdate: (next) => {
      if (ownsPending(next)) savePending(next);
    },
    isCancelled: () => !ownsPending(run),
  };
}

/**
 * Recover the answer to an agent run whose response this page never got — it was sent from a
 * previous page, or the call failed while the server carried on. Null when "Clear" abandoned it
 * meanwhile; throws when the run failed, so the bubble shows its usual error.
 */
export async function resumePendingRun(run: PendingRun): Promise<MarvinResult | null> {
  const outcome = await recoverPendingRun(run, pendingDeps(run));
  if (outcome.kind === "cancelled" || outcome.kind === "wait" || !ownsPending(run)) return null;
  clearPending();
  if (outcome.kind === "failed") throw new Error(outcome.error);
  if (outcome.threadId) rememberThread(run.agent, outcome.threadId);
  if (outcome.kind === "reply") {
    const m = outcome.message;
    return { html: agentReplyHtml(m.content, m.stepsJson ?? []), executionId: m.executionId ?? undefined };
  }
  if (outcome.kind === "parked") return { html: parkedHtml(outcome.threadId, outcome.tools), parked: true };
  const where = `<a href="${esc(askThreadHref(outcome.threadId))}">${outcome.threadId ? "the conversation on the Ask page" : "the Ask page"}</a>`;
  return {
    html: outcome.timedOut
      ? `<div class="mv-answer">Still no answer after ${PENDING_RUN_TIMEOUT_MS / 60_000} minutes, so I've stopped waiting. It may yet finish — check ${where}.</div>`
      : `<div class="mv-answer">I lost track of that request — the server no longer knows about it (restarted, or it never got there). Check ${where}, or ask again.</div>`,
  };
}

/**
 * An "ask first" tool paused the run. Approving happens on the Ask page, where the thread shows
 * the pending calls; the bubble just says so instead of waiting on a decision it can't take.
 */
function parkedHtml(threadId: string, tools: string[]): string {
  const what = [...new Set(tools)].map((t) => `<code>${esc(t)}</code>`).join(", ");
  return `<div class="mv-answer">I need your go-ahead first${what ? ` (${what})` : ""}. <a href="${esc(askThreadHref(threadId))}">Approve or deny it on the Ask page</a> — the answer will be in that conversation.</div>`;
}

/** An agent answer as bubble HTML: the answer, image thumbnails, drafts it composed, tools it used. */
function agentReplyHtml(answer: string, steps: any[]): string {
  let html = `<div class="mv-answer">${renderMarkdown(answer)}</div>`;

  // Deterministic thumbnail strip from the tool results' image assets (real urls, not guessed).
  html += thumbsHtml(steps);

  // Surface any drafts the agent composed as clickable links.
  const drafts: string[] = [];
  for (const s of steps) {
    if (s.tool !== "compose_entry") continue;
    try {
      const r = typeof s.result === "string" ? JSON.parse(s.result) : s.result;
      if (r?.editUrl) drafts.push(`<a href="${esc(r.editUrl)}">${esc(r.title || "New draft")}</a>`);
    } catch {
      /* ignore unparseable tool result (a thread stores results truncated) */
    }
  }
  if (drafts.length) {
    html += `<div class="mv-sources"><span>Drafts:</span> ${drafts.join(" · ")}</div>`;
  }

  // Show which tools were used, as a subtle trace of the agent's work.
  if (steps.length) {
    const tools = [...new Set(steps.map((s) => s.tool))];
    html += `<div class="mv-sources"><span>Used:</span> ${tools.map((t) => `<code>${esc(t)}</code>`).join(" ")}</div>`;
  }
  return html;
}

// ── Built-in skill: Ask (RAG) ────────────────────────────────────────────────
const ask: Capability = {
  id: "ask",
  label: "Ask",
  hint: "Quick answer from your workspace content, with sources (read-only, no tools).",
  commands: ["ask"],
  async run(arg: string): Promise<MarvinResult> {
    const exec: any = await askWorkspace(arg);
    const out = exec?.outputJson ?? exec?.output_json ?? {};
    const answer = out.answer ?? "(no answer — the void stares back)";
    const retrieved: any[] = out.retrieved_sources ?? [];

    let html = `<div class="mv-answer">${renderMarkdown(answer)}</div>`;
    const seen = new Set<string>();
    const links: string[] = [];
    for (const s of retrieved) {
      const key = `${s.entity_type}:${s.entity_id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const href = entityHref(s.entity_type, s.entity_id);
      const label = esc(s.title || key);
      links.push(href ? `<a href="${esc(href)}">${label}</a>` : label);
    }
    if (links.length) {
      html += `<div class="mv-sources"><span>Sources:</span> ${links.join(" · ")}</div>`;
    }
    return { html };
  },
};

// ── Built-in skill: Chat (plain completion — no tools, no RAG) ───────────────
// Ungrounded conversation with the model, like the Ollama CLI. Works on ANY model, including
// text-only ones (gemma, phi) that can't run the tool-calling agent. Not grounded in workspace
// content — use /ask for that, /agent (default) to actually do things.
const chat: Capability = {
  id: "chat",
  label: "Chat",
  hint: "Just talk to the model — no tools, no content lookup. Works on any model.",
  commands: ["chat"],
  async run(arg: string): Promise<MarvinResult> {
    const res = await sendChat(arg);
    const reply = res?.reply ?? "(no reply — the silence is deafening)";
    return { html: `<div class="mv-answer">${renderMarkdown(reply)}</div>` };
  },
};

// ── Built-in skill: Tools (what the agent can reach) ─────────────────────────
// Transparency, not a mode you drive: lists the tools the /agent loop actually binds for you —
// built-in registry tools plus any allowlisted external MCP tools — so "did my server wire in?"
// has an honest answer. You never call these directly; the agent picks from them.
const tools: Capability = {
  id: "tools",
  label: "Tools",
  hint: "See the tools I can reach right now (built-in + your external MCP servers).",
  commands: ["tools"],
  noArg: true,
  async run(): Promise<MarvinResult> {
    const all = await listAgentTools();
    if (!all.length) {
      return { html: `<div class="mv-tools">No tools are enabled. Bleak, but on brand.</div>` };
    }
    // Group: built-ins first, then one group per external MCP server.
    const groups = new Map<string, typeof all>();
    const label = (t: (typeof all)[number]) => (t.source === "external" ? t.server || "External MCP" : "Built-in");
    for (const t of all) {
      const k = label(t);
      (groups.get(k) ?? groups.set(k, []).get(k)!).push(t);
    }
    // Built-in group renders first; external servers follow in insertion order.
    const ordered = [...groups.entries()].sort(([a], [b]) => (a === "Built-in" ? -1 : b === "Built-in" ? 1 : 0));
    const short = (d: string) => (d.length > 90 ? `${d.slice(0, 87).trimEnd()}…` : d);
    const sections = ordered
      .map(([name, ts]) => {
        const rows = ts
          .map(
            (t) =>
              `<li><code>${esc(t.name)}</code> <span title="${esc(t.description)}">${esc(short(t.description))}</span></li>`,
          )
          .join("");
        return `<div class="mv-tools-group"><span class="mv-tools-head">${esc(name)}</span><ul>${rows}</ul></div>`;
      })
      .join("");
    return {
      html: `<div class="mv-tools">Here's what I can reach right now — I pick from these when you give me a goal:${sections}</div>`,
    };
  },
};

// ── Active agent (which named agent free text goes to) ───────────────────────
const AGENT_KEY = "marvin.agent";

export function getActiveAgent(): string {
  try {
    return sessionStorage.getItem(scoped(AGENT_KEY)) || "marvin";
  } catch {
    return "marvin";
  }
}

export function setActiveAgent(slug: string): void {
  try {
    if (slug === "marvin") sessionStorage.removeItem(scoped(AGENT_KEY));
    else sessionStorage.setItem(scoped(AGENT_KEY), slug);
  } catch {
    /* storage unavailable — the switch lasts for this page only */
  }
}

// ── Built-in skill: Agents (list) ────────────────────────────────────────────
const agents: Capability = {
  id: "agents",
  label: "Agents",
  hint: "List the agents you can talk to; switch with /use <slug>.",
  commands: ["agents"],
  noArg: true,
  async run(): Promise<MarvinResult> {
    const list = await listAgents();
    const active = getActiveAgent();
    const rows = list
      .filter((a) => a.enabled)
      .map((a) => {
        const flags = [a.kind, a.allowWrites ? "" : "read-only", a.isSystem ? "built-in" : ""]
          .filter(Boolean)
          .join(" · ");
        const desc = a.description ? `<br><span class="mv-muted">${esc(a.description)}</span>` : "";
        return `<li><code>${esc(a.slug)}</code>${a.slug === active ? " <strong>(active)</strong>" : ""} — ${esc(a.name)}<span class="mv-muted"> · ${esc(flags)}</span>${desc}</li>`;
      })
      .join("");
    return {
      html: `<div class="mv-help">Agents:<ul>${rows}</ul>Switch with <code>/use &lt;slug&gt;</code>; <code>/use marvin</code> goes back to the default.</div>`,
    };
  },
};

// ── Built-in skill: Use (switch the active agent) ────────────────────────────
const use: Capability = {
  id: "use",
  label: "Use agent",
  hint: "Route free text to a named agent, e.g. /use workshop.",
  commands: ["use"],
  async run(arg: string): Promise<MarvinResult> {
    const slug = arg.trim().toLowerCase();
    const list = await listAgents();
    const hit = list.find((a) => a.slug === slug && a.enabled);
    if (!hit) {
      return {
        html: `<div class="mv-answer">No agent called <code>${esc(slug)}</code>. <code>/agents</code> lists them.</div>`,
      };
    }
    setActiveAgent(slug);
    const mode = hit.allowWrites ? "" : ", read-only";
    return {
      html: `<div class="mv-answer">Talking to <strong>${esc(hit.name)}</strong> (<code>${esc(slug)}</code>${mode}). Free text goes there until <code>/use marvin</code>.</div>`,
    };
  },
};

// ── Registry ─────────────────────────────────────────────────────────────────
export const CAPABILITIES: Capability[] = [agent, ask, chat, tools, agents, use];

/** Register a new skill at runtime (e.g. from a plugin bundle). */
export function registerCapability(cap: Capability): void {
  CAPABILITIES.push(cap);
}

/**
 * Route raw input to a capability.
 *   "/cmd args"  → the capability whose commands include `cmd`
 *   "/help"|"/?" → help flag
 *   free text    → the default capability
 */
export function resolveCapability(input: string): { cap: Capability | null; arg: string; help?: boolean } {
  const trimmed = input.trim();
  if (trimmed.startsWith("/")) {
    const [cmd, ...rest] = trimmed.slice(1).split(/\s+/);
    if (cmd === "help" || cmd === "?") return { cap: null, arg: "", help: true };
    const cap = CAPABILITIES.find((c) => c.commands.includes(cmd.toLowerCase())) ?? null;
    return { cap, arg: rest.join(" ") };
  }
  return { cap: CAPABILITIES.find((c) => c.isDefault) ?? null, arg: trimmed };
}

/** Rendered /help listing every registered skill. */
export function helpHtml(): string {
  const rows = CAPABILITIES.map((c) => `<li><code>/${esc(c.commands[0] ?? c.id)}</code> — ${esc(c.hint)}</li>`).join(
    "",
  );
  return `<div class="mv-help">Brain the size of a planet, and here's what they let me do:<ul>${rows}</ul>Or just type a question and I'll do my best. It won't be enough.</div>`;
}
