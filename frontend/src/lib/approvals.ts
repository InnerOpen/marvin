/**
 * Ask first: what an approval card shows and what deciding it sends — shared by the Ask page and the bubble
 * (agents v2 slice C2).
 *
 * A paused run's `pending` is flat: the agent's own asks first, then any a specialist it handed off to
 * asked for (path ids like `c1/c7`, tagged `via`). The card groups them by who asked, so "via Workshop"
 * reads once over that specialist's calls. Deciding sends one decision per id; a missing id is a deny
 * server-side, but the card always sends them all. Kept free of the DOM and of runtime imports (types
 * only) so it runs under `node --test` (approvals.test.mjs).
 */

import type { PendingCall } from "@/lib/api/aiAgents";

export type Decision = "approve" | "deny";
export type Decisions = Record<string, Decision>;

export interface ApprovalGroup {
  /** The specialist that asked; null for the agent's own asks. */
  via: string | null;
  viaName: string | null;
  /** Every specialist between the conversation and the ask, outermost first (empty for own asks). */
  viaChain: string[];
  childThreadId: string | null;
  calls: PendingCall[];
}

/** Group a flattened `pending` by who asked: own asks first, then each specialist in order of first appearance. */
export function groupPending(pending: readonly PendingCall[] | null | undefined): ApprovalGroup[] {
  const own: ApprovalGroup = { via: null, viaName: null, viaChain: [], childThreadId: null, calls: [] };
  const specialists = new Map<string, ApprovalGroup>();
  for (const call of pending ?? []) {
    if (!call.via) {
      own.calls.push(call);
      continue;
    }
    // Two hand-offs to the same specialist park on one child thread; key by it so they share a group.
    const key = call.childThreadId || call.via;
    let group = specialists.get(key);
    if (!group) {
      group = {
        via: call.via,
        viaName: call.viaName || call.via,
        viaChain: call.viaChain?.length ? [...call.viaChain] : [call.via],
        childThreadId: call.childThreadId ?? null,
        calls: [],
      };
      specialists.set(key, group);
    }
    group.calls.push(call);
  }
  return [...(own.calls.length ? [own] : []), ...specialists.values()];
}

/**
 * "via Workshop", or "via Workshop → Materials" when hand-offs nest. `nameOf` maps a slug to a display
 * name (the innermost specialist's own name comes with the call).
 */
export function viaText(
  group: Pick<ApprovalGroup, "via" | "viaName" | "viaChain">,
  nameOf: (slug: string) => string = (s) => s,
): string {
  if (!group.via) return "";
  const chain = group.viaChain.length ? group.viaChain : [group.via];
  const names = chain.map((slug, i) => (i === chain.length - 1 ? group.viaName || nameOf(slug) : nameOf(slug)));
  return `via ${names.join(" → ")}`;
}

/** The decisions a card sends: every listed call approved when checked, denied otherwise (or all denied). */
export function decisionsFrom(choices: readonly { id: string; checked: boolean }[], denyAll = false): Decisions {
  const out: Decisions = {};
  for (const c of choices) out[c.id] = !denyAll && c.checked ? "approve" : "deny";
  return out;
}

/** A one-line arguments summary for a card row or a live step. */
export function argsPreview(args: unknown, max = 90): string {
  if (!args || typeof args !== "object") return "";
  const parts = Object.entries(args as Record<string, unknown>).map(
    ([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`,
  );
  const text = parts.join(", ");
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** "Approved run_workflow · denied mcp__x__send" — what a decided card says it did. */
export function decidedSummary(pending: readonly PendingCall[], decisions: Decisions): string {
  const tools = (want: Decision) => [
    ...new Set(pending.filter((c) => (decisions[c.id] ?? "deny") === want).map((c) => c.tool)),
  ];
  const approved = tools("approve");
  const denied = tools("deny");
  const parts = [
    approved.length ? `Approved ${approved.join(", ")}` : "",
    denied.length ? `${approved.length ? "denied" : "Denied"} ${denied.join(", ")}` : "",
  ];
  return parts.filter(Boolean).join(" · ");
}

// ── The bubble's inline card ─────────────────────────────────────────────────
// When a bubble run parks, the reply is a card: one checkbox per call grouped by who asked, "Approve
// selected" / "Deny all", and "Open on Ask page" only while the Ask page is switched on — with it off,
// the bubble is the only place to decide. The card is kept with its transcript turn as data and
// re-rendered from it, so a decided card stays decided across navigations.

export interface ApprovalCard {
  /** Unique per card: how a click finds its transcript turn. */
  cardId: string;
  /** The thread the run is parked on (the bubble's own conversation). */
  threadId: string;
  /** The agent that conversation is with. */
  agent: string;
  pending: PendingCall[];
  /** The Ask page on this thread, or null while the Ask page is switched off. */
  askHref: string | null;
  /** Set once decided; "superseded" when a new message abandoned it server-side. */
  decided?: Decisions | "superseded";
}

type Esc = (s: unknown) => string;

/** The card for a parked run, or its decided form. */
export function approvalCardHtml(card: ApprovalCard, esc: Esc): string {
  const done = card.decided !== undefined;
  const disabled = done ? " disabled" : "";
  const groups = groupPending(card.pending)
    .map((g) => {
      const head = g.via ? `<div class="mv-approval-via"><span class="mv-chip">${esc(viaText(g))}</span></div>` : "";
      const rows = g.calls
        .map((c) => {
          const checked =
            !done || (card.decided !== "superseded" && card.decided?.[c.id] === "approve") ? " checked" : "";
          const detail = c.preview ? c.preview.summary : argsPreview(c.arguments, 60);
          return (
            `<li><label><input type="checkbox" data-call-id="${esc(c.id)}"${checked}${disabled} /> <code>${esc(c.tool)}</code>` +
            `${detail ? ` <span class="mv-approval-args">${esc(detail)}</span>` : ""}</label></li>`
          );
        })
        .join("");
      return `${head}<ul class="mv-approval-list">${rows}</ul>`;
    })
    .join("");
  const ask = card.askHref ? `<a class="mv-approval-open" href="${esc(card.askHref)}">Open on Ask page ↗</a>` : "";
  let foot: string;
  if (card.decided === "superseded")
    foot = `<div class="mv-approval-done">Not decided — a newer message took its place.</div>`;
  else if (done)
    foot = `<div class="mv-approval-done">${esc(decidedSummary(card.pending, card.decided as Decisions))}</div>`;
  else
    foot =
      `<div class="mv-approval-actions"><button type="button" class="mv-btn" data-mv-approve>Approve selected</button>` +
      `<button type="button" class="mv-btn secondary" data-mv-deny>Deny all</button>${ask}</div>`;
  return (
    `<div class="mv-approval${done ? " resolved" : ""}" data-card-id="${esc(card.cardId)}">` +
    `<div class="mv-approval-title">I need your go-ahead first:</div>${groups}${foot}` +
    `${done && ask ? `<div class="mv-approval-actions">${ask}</div>` : ""}</div>`
  );
}
