// Admin › System Playbooks: grouping and wording for the page (pure, so `npm test` covers it). The data is
// lib/api/admin/systemPlaybooks.ts; the rows read like the workspace's System section (lib/playbooks.ts `systemGroups`).

import type { AdminSystemPlaybook } from "./api/admin/systemPlaybooks.ts";

export interface AdminSystemGroup {
  /** "System · Marvin", "System · S3 storage". */
  label: string;
  /** The version the group's Playbooks ship with (the package's); "" when mixed or unknown. */
  version: string;
  rows: AdminSystemRow[];
}

export interface AdminSystemRow extends AdminSystemPlaybook {
  /** "Off in every workspace" / "Off in 2 workspaces" / "" when none switched it off. */
  offNote: string;
  /** Badges the row shows: "Manual only", "Allowed tools: get_entry". */
  badges: string[];
}

export function offNote(item: Pick<AdminSystemPlaybook, "serverOff" | "workspacesOff">): string {
  if (item.serverOff) return "Off in every workspace";
  if (item.workspacesOff > 0) return `Off in ${item.workspacesOff} workspace${item.workspacesOff === 1 ? "" : "s"}`;
  return "";
}

export function badgesFor(item: Pick<AdminSystemPlaybook, "manualOnly" | "allowedTools">): string[] {
  return [...(item.manualOnly ? ["Manual only"] : []), ...(item.allowedTools ? [`Allowed tools: ${item.allowedTools}`] : [])];
}

/** The page's groups: by label in the order the API gives them (core first, then each plugin). */
export function adminGroups(items: AdminSystemPlaybook[]): AdminSystemGroup[] {
  const groups: AdminSystemGroup[] = [];
  for (const item of items) {
    let group = groups.find((g) => g.label === item.label);
    if (!group) groups.push((group = { label: item.label, version: item.version, rows: [] }));
    else if (group.version !== item.version) group.version = "";
    group.rows.push({ ...item, offNote: offNote(item), badges: badgesFor(item) });
  }
  return groups;
}

export function summary(items: AdminSystemPlaybook[], skipped: number): string {
  const n = items.length;
  const off = items.filter((i) => i.serverOff).length;
  const parts = [`${n} system Playbook${n === 1 ? "" : "s"}`];
  if (off) parts.push(`${off} switched off`);
  if (skipped) parts.push(`${skipped} couldn't load`);
  return parts.join(", ");
}

export const SWITCH_TITLE = {
  on: "Switch this Playbook off in every workspace",
  off: "Switch this Playbook back on (workspaces that switched it off themselves keep it off)",
};
