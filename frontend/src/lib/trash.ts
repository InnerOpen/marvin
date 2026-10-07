/**
 * Wording for the Trash (pure, so `npm test` covers it). The API calls live in lib/api/trash.ts.
 */

/** The auto-empty choices, in days; 0 = never (kept until someone empties the Trash). */
export const AUTO_EMPTY_CHOICES = [0, 7, 30, 90] as const;

/** "Never" or "30 days". */
export function autoEmptyLabel(days: number): string {
  if (!days) return "Never";
  return `${days} ${days === 1 ? "day" : "days"}`;
}

/** The line the Trash view shows under its title. */
export function autoEmptyNote(effectiveDays: number): string {
  if (!effectiveDays) return "Items in the Trash are kept until you empty the Trash.";
  return `Items in the Trash are deleted forever after ${autoEmptyLabel(effectiveDays)}.`;
}

/** The Empty trash confirmation — everything in the Trash: entries, assets and resources. */
export function emptyTrashPrompt(count: number): string {
  return `Permanently delete ${count} ${count === 1 ? "item" : "items"}? Files are removed from storage. This can't be undone.`;
}

/** The kinds of thing the Trash holds, as its tabs name them. */
export type TrashTab = "entries" | "assets" | "resources";

/** "Delete forever" confirmation for one item. */
export function deleteForeverPrompt(kind: "entry" | "asset" | "resource"): string {
  if (kind === "asset") return "Delete this asset forever? Its file is removed from storage. This can't be undone.";
  return `Delete this ${kind} forever? This can't be undone.`;
}

/** The bulk-restore failure line: "2 of 5 assets could not be restored." */
export function restoreFailedMessage(failed: number, total: number, tab: TrashTab): string {
  return `${failed} of ${total} ${tab} could not be restored.`;
}

/** Where a trashed entry goes back to on Restore (mirrors restore_status in services/entries/entry_service.py). */
export function restoresTo(metadataJson: Record<string, unknown> | null | undefined): string {
  const record = (metadataJson?.trash ?? null) as { previous_status?: unknown } | null;
  const previous = typeof record?.previous_status === "string" ? record.previous_status : "";
  const known = ["inbox", "draft", "needs_review", "approved", "archived"];
  return known.includes(previous) ? previous : "draft";
}

/** When the entry was moved to the Trash (ISO), if recorded. */
export function trashedAt(metadataJson: Record<string, unknown> | null | undefined): string | null {
  const record = (metadataJson?.trash ?? null) as { trashed_at?: unknown } | null;
  return typeof record?.trashed_at === "string" ? record.trashed_at : null;
}
