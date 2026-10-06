/**
 * Events hub: what sends an event type and what reacts to it (the connections API,
 * `/api/platform/event-types/…` and `/api/admin/event-types/…`). Types and the pure helpers the event page,
 * the Events catalog and the admin Events page share. Run the tests with `npm test`.
 */

export type ReactionKind = "workflow" | "integration_action" | "email" | "webhook" | "builtin";
export type SenderKind = "marvin" | "workflow" | "incoming_webhook" | "scheduled_task";

export interface InstalledBy {
  integrationId: string;
  name: string;
  provider: string;
  blueprint?: string | null;
}

export interface EventReaction {
  kind: ReactionKind;
  id?: string | null;
  name: string;
  enabled: boolean;
  detail?: string | null;
  triggerType?: string | null;
  managedAt?: string | null;
  installedBy?: InstalledBy | null;
}

export interface EventSender {
  kind: SenderKind;
  id?: string | null;
  name: string;
  enabled: boolean;
  detail?: string | null;
  viaWorkflowId?: string | null;
  viaWorkflowName?: string | null;
  managedAt?: string | null;
  installedBy?: InstalledBy | null;
}

export interface EventTypeRef {
  eventType: string;
  name: string;
}

export interface EventLogRow {
  id: string;
  eventId: string;
  eventType: string;
  occurredAt: string;
  messageTitle: string;
  messageBody?: string | null;
}

export interface EventConnections {
  eventType: string;
  name: string;
  description: string;
  category: string;
  senders: EventSender[];
  reactions: EventReaction[];
  audited: boolean;
  recent: EventLogRow[];
  leadsTo: EventTypeRef[];
  causedBy: EventTypeRef[];
}

export interface EventConnectionCounts {
  eventType: string;
  senders: number;
  reactions: number;
  activeReactions: number;
  builtinReactions: number;
  lastOccurredAt?: string | null;
}

export interface WorkspaceEventReactions {
  workspaceId: string;
  workspaceName?: string | null;
  workspaceSlug?: string | null;
  reactions: EventReaction[];
}

export interface AdminEventConnections extends Omit<EventConnections, "audited" | "recent"> {
  workspaces: WorkspaceEventReactions[];
}

export interface Group<K, T> {
  kind: K;
  label: string;
  rows: T[];
}

const REACTION_ORDER: [ReactionKind, string][] = [
  ["workflow", "Workflows"],
  ["integration_action", "Integration actions"],
  ["email", "Emails"],
  ["webhook", "Webhooks"],
  ["builtin", "Built-in"],
];

const SENDER_ORDER: [SenderKind, string][] = [
  ["marvin", "Marvin"],
  ["workflow", "Workflows"],
  ["incoming_webhook", "Incoming webhooks"],
  ["scheduled_task", "Scheduled tasks"],
];

function groupBy<K extends string, T extends { kind: K }>(order: [K, string][], rows: T[]): Group<K, T>[] {
  return order
    .map(([kind, label]) => ({ kind, label, rows: rows.filter((r) => r.kind === kind) }))
    .filter((g) => g.rows.length > 0);
}

/** The reactions by kind, in display order (workflows first, built-in last); empty kinds left out. */
export function groupReactions(reactions: EventReaction[]): Group<ReactionKind, EventReaction>[] {
  return groupBy(REACTION_ORDER, reactions);
}

/** The senders by kind: Marvin's own lines first, then the workspace's workflows, incoming webhooks and tasks. */
export function groupSenders(senders: EventSender[]): Group<SenderKind, EventSender>[] {
  return groupBy(SENDER_ORDER, senders);
}

/** The system email template's row (Marvin's own invitation / reset / welcome email), not a subscription. */
export function isSystemEmail(r: EventReaction): boolean {
  return r.kind === "email" && r.detail === "System template";
}

/**
 * Whether the event page offers its own controls (edit / disconnect) for a reaction. Emails, webhooks and
 * integration actions are connected on the event page; workflows, built-ins, the system email and anything an
 * integration installed are managed where they live, so the page only links there.
 */
export function managedHere(r: EventReaction): boolean {
  if (r.installedBy) return false;
  if (isSystemEmail(r)) return false;
  return r.kind === "email" || r.kind === "webhook" || r.kind === "integration_action";
}

/** One line on the system email row: why it does or doesn't send. */
export function systemEmailNote(r: EventReaction): string {
  return r.enabled
    ? "Marvin's built-in email for this event. It sends unless you connect your own template of this type."
    : "Marvin's built-in email for this event. Not sent: your own template replaces it, or it's switched off.";
}

/** The catalog list's state for one event type. */
export type DotState = "active" | "off" | "none";

export function dotState(c: EventConnectionCounts | undefined): DotState {
  if (!c || c.reactions === 0) return "none";
  return c.activeReactions > 0 ? "active" : "off";
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** The catalog chip's tooltip: both directions, counted. */
export function countsTitle(c: EventConnectionCounts | undefined, now: Date = new Date()): string {
  if (!c) return "";
  const off = c.reactions - c.activeReactions;
  const parts = [
    c.senders ? `Sent by ${plural(c.senders, "sender")}` : "Nothing sends it yet",
    c.reactions
      ? `${plural(c.reactions, "reaction")}${off ? ` (${off} switched off)` : ""}`
      : "No reactions in this workspace",
  ];
  if (c.builtinReactions) parts.push(`${c.builtinReactions} built-in`);
  if (c.lastOccurredAt) parts.push(`last ${formatWhen(c.lastOccurredAt, now)}`);
  return parts.join(" · ");
}

/** "connected" in the catalog: something in the workspace reacts to it (switched off or not). */
export function isConnected(c: EventConnectionCounts | undefined): boolean {
  return !!c && c.reactions > 0;
}

/** API datetimes may carry microseconds and no zone; read them as UTC. */
export function parseApiDate(iso: string): Date {
  const trimmed = iso.replace(/(\.\d{3})\d+/, "$1");
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(trimmed) ? trimmed : `${trimmed}Z`);
}

/** "just now", "5 min ago", "3 hours ago", "2 days ago", then the date. */
export function formatWhen(iso: string, now: Date = new Date()): string {
  const d = parseApiDate(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const secs = Math.round((now.getTime() - d.getTime()) / 1000);
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${plural(hours, "hour")} ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${plural(days, "day")} ago`;
  return d.toISOString().slice(0, 10);
}

/** Where a recent event opens: its row in the workspace Event Log. */
export function eventLogHref(eventId: string): string {
  return `/workspace/events?event=${encodeURIComponent(eventId)}`;
}

/** The workflow builder, opened on a new workflow triggered by `eventType`. */
export function newWorkflowHref(eventType: string): string {
  return `/automation/workflows?trigger=${encodeURIComponent(eventType)}`;
}

/** The builder's `?trigger=` value, if it's an event the builder can trigger on. */
export function triggerFromQuery(search: string, triggerable: Iterable<string>): string | null {
  const value = new URLSearchParams(search).get("trigger");
  if (!value) return null;
  return new Set(triggerable).has(value) ? value : null;
}

/** Every event a workflow can trigger on, from the builder options (grouped, or the flat list). */
export function triggerableEvents(
  options: { triggers?: string[]; triggerGroups?: Record<string, string[]> } | null | undefined,
): string[] {
  const groups = options?.triggerGroups;
  if (groups && Object.keys(groups).length) return Object.values(groups).flat();
  return options?.triggers ?? [];
}

const RECIPIENTS: Record<string, string> = {
  admins: "To the workspace admins",
  specific: "To specific addresses",
  event_field: "To an address in the event",
};

const pick = (row: any, camel: string, snake: string) => row?.[camel] ?? row?.[snake];

export interface SubscriptionLists {
  webhooks?: any[];
  emailSubscriptions?: any[];
  emailTemplates?: any[];
  integrationSubscriptions?: any[];
  /** The email-templates event-connections row for this type (a system template the event sends), if any. */
  systemEmail?: any | null;
}

/**
 * A platform event type (sign-ups, workspaces) has no workspace connections view, but a workspace can still
 * connect emails, webhooks and integration actions to it. Its "What happens" list is built from those lists,
 * in the API's row shape.
 */
export function reactionsFromSubscriptions(eventType: string, lists: SubscriptionLists): EventReaction[] {
  const out: EventReaction[] = [];
  for (const s of lists.integrationSubscriptions ?? []) {
    if (pick(s, "eventType", "event_type") !== eventType) continue;
    out.push({
      kind: "integration_action",
      id: s.id,
      name: pick(s, "integrationName", "integration_name") ?? s.provider ?? "Integration",
      enabled: s.enabled !== false,
      detail: s.action ?? null,
      managedAt: "/workspace/settings/integrations",
    });
  }
  const templates = new Map((lists.emailTemplates ?? []).map((t: any) => [t.id, t]));
  for (const s of lists.emailSubscriptions ?? []) {
    if (pick(s, "eventType", "event_type") !== eventType) continue;
    const templateId = pick(s, "templateId", "template_id");
    out.push({
      kind: "email",
      id: s.id,
      name: templates.get(templateId)?.name ?? "Email template",
      enabled: s.enabled !== false,
      detail: RECIPIENTS[pick(s, "recipientType", "recipient_type") ?? ""] ?? null,
      managedAt: `/workspace/settings/email/${templateId}`,
    });
  }
  const system = lists.systemEmail;
  const systemTemplate = pick(system, "systemTemplate", "system_template");
  if (systemTemplate?.id) {
    out.push({
      kind: "email",
      id: systemTemplate.id,
      name: systemTemplate.name ?? "System email",
      enabled: !pick(system, "hasWorkspaceOverride", "has_workspace_override"),
      detail: "System template",
      managedAt: `/workspace/settings/email?customize=${systemTemplate.id}`,
    });
  }
  for (const w of lists.webhooks ?? []) {
    const events: string[] = pick(w, "subscribedEvents", "subscribed_events") ?? [];
    if (pick(w, "webhookType", "webhook_type") !== "event_driven" || !events.includes(eventType)) continue;
    out.push({
      kind: "webhook",
      id: w.id,
      name: w.name,
      enabled: w.enabled !== false,
      managedAt: `/automation/webhooks/${w.id}`,
    });
  }
  return out;
}
