// Where an event's subject lives in the admin — the event log, the dashboard's activity list and the
// activity toaster link an event's entity (and a workflow run's trigger) through this one map.
// Pure, so it's tested with plain `node --test` (see eventEntity.test.mjs).

type Route = (id: string) => string;

const enc = encodeURIComponent;

/** Entity type (as event_log.entity_type stores it) → its admin page. Types not listed have none. */
const ROUTES: Record<string, Route> = {
  entry: (id) => `/workspace/entries/${enc(id)}`,
  asset: (id) => `/workspace/assets/${enc(id)}`,
  collection: (id) => `/workspace/collections/${enc(id)}`,
  resource: (id) => `/workspace/resources/${enc(id)}`,
  entry_type: (id) => `/workspace/entry-types/${enc(id)}`,
  scheduled_task: (id) => `/workspace/scheduled-tasks/${enc(id)}`,
  automation: (id) => `/automation/workflows?workflow=${enc(id)}`,
  webhook: (id) => `/automation/webhooks/${enc(id)}`,
  incoming_webhook: () => "/automation/incoming-webhooks",
  integration: () => "/workspace/settings/integrations",
  api_client: () => "/publishing/clients",
  secret: () => "/workspace/settings/environment?tab=secrets",
  variable: () => "/workspace/settings/environment?tab=variables",
  member: () => "/workspace/members",
  invitation: () => "/workspace/invites",
  workspace: () => "/workspace/settings/general",
  ai_execution: () => "/workspace/settings/ai-executions",
};

/** How a type reads in a list ("scheduled_task" → "Scheduled task", "automation" → "Workflow"). */
const LABELS: Record<string, string> = {
  automation: "Workflow",
  api_client: "API client",
  ai_execution: "AI run",
  incoming_webhook: "Incoming webhook",
};

/** The admin page for an entity, or null when there is none (unknown type, or no id). */
export function entityHref(type: string | null | undefined, id: string | null | undefined): string | null {
  if (!type || !id) return null;
  const route = Object.hasOwn(ROUTES, type) ? ROUTES[type] : undefined;
  return route ? route(String(id)) : null;
}

/** A type's display name; unknown types are humanized from their name. */
export function entityTypeLabel(type: string | null | undefined): string {
  if (!type) return "";
  if (Object.hasOwn(LABELS, type)) return LABELS[type];
  const words = type.replace(/[._]/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export type EntityLink = { label: string; href: string | null; shortId: string | null };

/** What a row shows for one subject: its type (or name, when known), a link if it has a page, a short id. */
export function entityLink(
  type: string | null | undefined,
  id: string | null | undefined,
  name?: string | null,
): EntityLink | null {
  if (!type) return null;
  return {
    label: name ? `${entityTypeLabel(type)} '${name}'` : entityTypeLabel(type),
    href: entityHref(type, id),
    shortId: id ? String(id).slice(0, 8) : null,
  };
}
