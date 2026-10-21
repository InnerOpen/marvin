// The Workflows page's list: how each workflow starts (the Starts filter), its one-line trigger summary, and the
// adapter that feeds the shared list kit (organizedList.ts). Pure, so `npm test` covers it (workflowList.test.mjs).

import type { Choice, ListAdapter } from "./organizedList.ts";
import { menuHtml, switchHtml } from "./organizedListHtml.ts";

/** A workflow as the list API returns it (camelCase), as far as the list needs. */
export interface WorkflowRow {
  id: string;
  name: string;
  slug?: string;
  enabled: boolean;
  sourceRecipe?: string | null;
  sourceIntegrationId?: string | null;
  sourceBlueprint?: string | null;
  definition?: any;
}

export type StartsKind = "event" | "schedule" | "webhook" | "manual";

export const STARTS_OPTIONS: Choice[] = [
  { value: "event", label: "When something happens" },
  { value: "schedule", label: "On a schedule" },
  { value: "webhook", label: "From a webhook" },
  { value: "manual", label: "By hand" },
];

/** How a workflow starts. Chained and on-error workflows start when something happens; MCP tools are run by hand. */
export function triggerKind(wf: WorkflowRow): StartsKind {
  switch (wf.definition?.trigger?.type) {
    case "schedule":
      return "schedule";
    case "incoming_webhook":
      return "webhook";
    case "manual":
    case "mcp":
      return "manual";
    default:
      return "event";
  }
}

export function humanInterval(secs: number): string {
  if (!secs) return "—";
  const [n, unit] =
    secs % 86400 === 0
      ? [secs / 86400, "day"]
      : secs % 3600 === 0
        ? [secs / 3600, "hour"]
        : [Math.max(1, Math.round(secs / 60)), "minute"];
  return `${n} ${unit}${n === 1 ? "" : "s"}`;
}

export const prettyEvent = (event: string): string => event.replace(/_/g, " ");

/** Name lookups a summary needs (the page reads them from the options it loaded). */
export interface NameLookup {
  webhookName(ref: string | undefined): string;
  automationName(ref: string | undefined): string;
}

/** "run manually", "every 1 day", "entry published", "after Nightly"… */
export function triggerSummary(wf: WorkflowRow, names: NameLookup): string {
  const t = wf.definition?.trigger ?? {};
  switch (t.type) {
    case "manual":
      return "run manually";
    case "mcp":
      return "MCP tool";
    case "schedule":
      return `every ${humanInterval(t.schedule_config?.interval_seconds)}`;
    case "chained":
      return `after ${names.automationName(t.automation)}`;
    case "on_error":
      return `if ${names.automationName(t.automation)} fails`;
    case "incoming_webhook":
      return `${names.webhookName(t.webhook)} received`;
    default:
      return prettyEvent(t.event || "—");
  }
}

/** The adapter for the shared list kit. Needs-attention flags arrive with the last-run data (a later ticket): add
 * `attention` here and pass `statusOptions({ attention: true })` to the filter bar. */
export function workflowAdapter(names: NameLookup): ListAdapter<WorkflowRow> {
  return {
    id: (wf) => wf.id,
    name: (wf) => wf.name,
    search: (wf) => [wf.slug ?? "", triggerSummary(wf, names)],
    source: (wf) => ({
      integrationId: wf.sourceIntegrationId ?? null,
      blueprint: wf.sourceBlueprint ?? null,
      recipe: wf.sourceRecipe ?? null,
    }),
    enabled: (wf) => wf.enabled,
    facets: { starts: triggerKind },
  };
}

const esc = (s: unknown): string =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string,
  );

/** One compact workflow card: name, one-line trigger, On/Off switch, Run and Edit, the rest under ⋯. The page
 * attaches the handlers by class (js-run, js-edit, js-toggle, js-dryrun, js-history, js-copy, js-delete) and fills
 * `.wf-history`. `details` is the When / If / Then flow, tucked under "Steps". */
export function workflowCardHtml(
  wf: WorkflowRow,
  options: { summary: string; details: string; linked: boolean },
): string {
  return `<article class="org-card wf-card${wf.enabled ? "" : " off"}${options.linked ? " linked" : ""}" data-id="${esc(wf.id)}">
    <div class="org-card-main">
      <div class="org-card-title"><strong>${esc(wf.name)}</strong></div>
      <div class="org-card-sub">${wf.enabled ? "" : "Off · "}${esc(options.summary)}</div>
      <details class="wf-steps"><summary>Steps</summary>${options.details}</details>
      <div class="wf-history" hidden></div>
    </div>
    <div class="org-card-actions">
      ${switchHtml({ on: wf.enabled, cls: "js-toggle", label: wf.name })}
      <button type="button" class="org-btn primary js-run"${wf.enabled ? "" : ' disabled title="Switch the workflow on to run it"'}>Run</button>
      <button type="button" class="org-btn js-edit">Edit</button>
      ${menuHtml([
        { cls: "js-dryrun", label: "Dry run", title: "Preview the plan — resolve inputs, execute nothing" },
        { cls: "js-history", label: "Runs" },
        {
          cls: "js-copy",
          label: "Copy JSON",
          title:
            "Copy the name, slug and definition as JSON — paste it into New workflow → Edit as JSON, here or in another workspace",
        },
        { cls: "js-delete", label: "Delete", danger: true },
      ])}
    </div>
  </article>`;
}
