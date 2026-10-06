// Event Log audit coverage: which event types the workspace's log records (GET/PATCH /api/groups/audit-settings).
// Pure helpers for the Audit coverage panel on workspace/events.astro; tested in auditSettings.test.mjs.

/** One catalog event type and whether this workspace's Event Log records it. */
export interface AuditEventSetting {
  eventType: string;
  name: string;
  category: string;
  /** The catalog default. */
  defaultAudited: boolean;
  /** What this workspace records: its override if it has one, otherwise the default. */
  audited: boolean;
  /** A security event: always recorded, can't be switched off. */
  locked: boolean;
}

/** An event type the Event Log leaves out (GET /api/groups/audit-settings/excluded, any member). */
export interface AuditExcludedEvent {
  eventType: string;
  name: string;
  category: string;
}

/** `{eventType: true | false | null}`: record, skip, or back to the catalog default. */
export type AuditOverrides = Record<string, boolean | null>;

/** The admin changed this type from its default (locked types never differ). */
export function isOverridden(row: Pick<AuditEventSetting, "audited" | "defaultAudited" | "locked">): boolean {
  return !row.locked && row.audited !== row.defaultAudited;
}

/** Rows grouped by category, keeping the order the API sends (categories in display order). */
export function groupByCategory<T extends { category: string }>(rows: T[]): { category: string; rows: T[] }[] {
  const groups = new Map<string, T[]>();
  for (const row of rows) {
    const list = groups.get(row.category);
    if (list) list.push(row);
    else groups.set(row.category, [row]);
  }
  return [...groups].map(([category, list]) => ({ category, rows: list }));
}

/** The text the filter box matches: name, machine name (with and without underscores) and category. */
export function searchText(row: Pick<AuditEventSetting, "eventType" | "name" | "category">): string {
  return `${row.name} ${row.eventType} ${row.eventType.replace(/_/g, " ")} ${row.category}`.toLowerCase();
}

/** Whether a row's search text matches the filter box (every word, any order). */
export function matchesFilter(text: string, query: string): boolean {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return words.every((w) => text.includes(w));
}

/** The panel's summary line. */
export function excludedSummary(count: number): string {
  if (count === 0) return "every event type recorded";
  return `${count} event type${count === 1 ? "" : "s"} excluded from this log`;
}

/** The override to send for a switch: null when the new value is the default (so no override is stored). */
export function overrideFor(row: Pick<AuditEventSetting, "defaultAudited">, audited: boolean): boolean | null {
  return audited === row.defaultAudited ? null : audited;
}
