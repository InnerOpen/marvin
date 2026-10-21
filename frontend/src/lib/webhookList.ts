// The outgoing Webhooks page's list: how each webhook starts (the Mode filter), what the card says (the host, never the
// URL's path or query: those can carry a token), and the adapter for the shared list kit (organizedList.ts).
// Pure, so `npm test` covers it (webhookList.test.mjs).

import type { Choice, ListAdapter } from "./organizedList.ts";
import { menuHtml, switchHtml } from "./organizedListHtml.ts";

/** A webhook as the list API returns it (camelCase), as far as the list needs. */
export interface WebhookRow {
  id: string;
  name: string;
  url: string;
  enabled: boolean;
  method?: string | null;
  webhookType?: string | null;
  scheduledTime?: string | null;
  sourceIntegrationId?: string | null;
  sourceBlueprint?: string | null;
  /** Why it needs a look (the server decides): "unreachable_address"; null/absent: it doesn't. */
  attention?: string | null;
}

export type ModeKind = "event" | "schedule" | "manual";

export const MODE_OPTIONS: Choice[] = [
  { value: "event", label: "When something happens" },
  { value: "schedule", label: "On a schedule" },
  { value: "manual", label: "Called by a workflow" },
];

/** How a webhook fires: event-driven ones when a subscribed event happens, "workflow" ones only when a workflow step
 * sends them (never on their own), the rest (generic, user, entries) on a schedule. */
export function modeKind(w: WebhookRow): ModeKind {
  const type = w.webhookType ?? (w as any).webhook_type ?? "generic";
  if (type === "event_driven") return "event";
  if (type === "workflow") return "manual";
  return "schedule";
}

/** The URL's host (with a port, if it has one) and nothing else: no scheme, path, query or credentials. "" if it isn't a URL. */
export function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return "";
  }
}

const ATTENTION_REASONS: Record<string, string> = {
  unreachable_address: "Points at a local or private address the server can't reach",
};

/** The reason a flagged webhook needs a look, in words ("" when it doesn't). */
export function attentionReason(w: WebhookRow): string {
  return w.attention ? (ATTENTION_REASONS[w.attention] ?? "Needs a look") : "";
}

const esc = (s: unknown): string =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string,
  );

export function attentionHtml(w: WebhookRow): string {
  const why = attentionReason(w);
  return why ? `<div class="wh-attention" title="${esc(why)}"><strong>Needs a look</strong> · ${esc(why)}</div>` : "";
}

/** "POST · hooks.example.com · event-driven" (or "scheduled <when>"); `when` formats a scheduled time. */
export function webhookSummary(w: WebhookRow, when: (iso: string) => string = (iso) => iso): string {
  const mode = modeKind(w);
  const how =
    mode === "event"
      ? "when something happens"
      : mode === "manual"
        ? "called by a workflow"
        : w.scheduledTime
          ? `scheduled ${when(w.scheduledTime)}`
          : "not scheduled";
  return [w.method || "POST", hostOf(w.url), how].filter(Boolean).join(" · ");
}

/** The adapter for the shared list kit. */
export function webhookAdapter(): ListAdapter<WebhookRow> {
  return {
    id: (w) => w.id,
    name: (w) => w.name,
    search: (w) => [hostOf(w.url)],
    source: (w) => ({ integrationId: w.sourceIntegrationId ?? null, blueprint: w.sourceBlueprint ?? null }),
    enabled: (w) => w.enabled,
    attention: (w) => !!w.attention,
    facets: { mode: modeKind },
  };
}

/** One compact webhook card: name, method · host · mode, On/Off switch, Test and Edit, Delete under ⋯. The page attaches
 * the handlers by class (js-toggle, js-test, js-delete); Edit is a link. */
export function webhookCardHtml(w: WebhookRow, options: { linked: boolean; when?: (iso: string) => string }): string {
  return `<article class="org-card wh-card${w.enabled ? "" : " off"}${options.linked ? " linked" : ""}" data-id="${esc(w.id)}" data-name="${esc(w.name)}">
    <div class="org-card-main">
      <div class="org-card-title"><strong>${esc(w.name)}</strong></div>
      <div class="org-card-sub">${w.enabled ? "" : "Off · "}${esc(webhookSummary(w, options.when))}</div>
      ${attentionHtml(w)}
    </div>
    <div class="org-card-actions">
      ${switchHtml({ on: w.enabled, cls: "js-toggle", label: w.name })}
      <button type="button" class="org-btn js-test"${w.enabled ? "" : ' disabled title="Switch the webhook on to test it"'}>Test</button>
      <a class="org-btn primary" href="/automation/webhooks/${esc(w.id)}">Edit</a>
      ${menuHtml([{ cls: "js-delete", label: "Delete", danger: true }])}
    </div>
  </article>`;
}
