// The Custom events page's list: events grouped by what sends them (a workflow, a webhook, nothing yet), read from
// the event-connections counts, and the card each one is drawn as. Feeds the shared list kit (organizedList.ts).
// Pure, so `npm test` covers it (customEventList.test.mjs).

import type { CustomEvent } from "./api/customEvents.ts";
import type { Choice, ListAdapter } from "./organizedList.ts";
import { menuHtml } from "./organizedListHtml.ts";

const esc = (s: unknown): string =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string,
  );

export type SenderGroup = "workflow" | "webhook" | "none";

/** The page's sections, in order. */
export const SENDER_GROUPS: Choice[] = [
  { value: "workflow", label: "Sent by a workflow" },
  { value: "webhook", label: "Sent by a webhook" },
  { value: "none", label: "Nothing sends it yet" },
];

/** Which section an event is in, from the kinds of sender the connections counts name for it. Only a workflow (or the
 * incoming webhook that starts one) can send a custom event, so Marvin's own and scheduled senders are ignored. An event
 * a webhook-started workflow sends is "by a webhook": the more specific of the two. */
export function senderGroup(kinds: readonly string[] | undefined): SenderGroup {
  if (kinds?.includes("incoming_webhook")) return "webhook";
  if (kinds?.includes("workflow")) return "workflow";
  return "none";
}

/** `senderKinds` maps an event type (`custom.<name>`) to its sender kinds (GET /api/platform/event-types/connections). */
export function customEventAdapter(senderKinds: Record<string, string[]>): ListAdapter<CustomEvent> {
  return {
    id: (e) => e.name,
    name: (e) => e.title || e.name,
    search: (e) => [e.name, e.eventType, e.description ?? ""],
    source: () => undefined,
    enabled: () => true,
    groups: { choices: SENDER_GROUPS, of: (e) => senderGroup(senderKinds[e.eventType]) },
  };
}

export function customEventCardHtml(e: CustomEvent): string {
  const fields = e.fields.length
    ? e.fields
        .map(
          (f) =>
            `<span class="chip" title="${esc(f.description || "")}">${esc(f.key)} <span class="muted">${esc(f.type)}</span></span>`,
        )
        .join("")
    : `<span class="hint">No fields: the event just happens.</span>`;
  const used = e.usedBy.length
    ? `Used by ${e.usedBy.map((n) => esc(n)).join(", ")}`
    : "No workflow uses it yet.";
  return `<article class="org-card ce-card" data-name="${esc(e.name)}">
    <div class="org-card-main">
      <div class="org-card-title"><strong>${esc(e.title || e.name)}</strong> <code class="slug">${esc(e.eventType)}</code></div>
      ${e.description ? `<div class="org-card-sub">${esc(e.description)}</div>` : ""}
      <div class="chips">${fields}</div>
      <div class="hint">${used}</div>
      <span class="hint error" data-status></span>
    </div>
    <div class="org-card-actions">
      <a class="org-btn" href="/automation/events/${encodeURIComponent(e.eventType)}">Reactions</a>
      <button type="button" class="org-btn js-edit">Edit</button>
      ${menuHtml([{ cls: "js-delete", label: "Remove", danger: true }])}
    </div>
  </article>`;
}
