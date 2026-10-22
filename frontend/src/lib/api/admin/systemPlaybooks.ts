/**
 * Admin System Playbooks API (routes/admin/system_playbooks_controller.py): the Playbooks Marvin and its plugins give every workspace,
 * with the platform switch. Super admins only.
 */

import { fetchApi } from "../client";

export interface AdminSystemPlaybook {
  name: string;
  description: string;
  /** "System · Marvin", "System · Social", "System · <plugin>". */
  label: string;
  /** "core" or "plugin". */
  source: string;
  version: string;
  manualOnly: boolean;
  /** Set when it narrows an agent's tools while loaded (rarely right). */
  allowedTools: string;
  warnings: string[];
  files: number;
  /** The platform switch: off in every workspace. */
  serverOff: boolean;
  /** How many workspaces switched it off themselves. */
  workspacesOff: number;
}

export interface AdminSystemPlaybooks {
  items: AdminSystemPlaybook[];
  /** What couldn't be loaded, each with the reason. */
  skipped: { name: string; label: string; reason: string }[];
}

export const listSystemPlaybooks = (authToken?: string) => fetchApi<AdminSystemPlaybooks>("/api/admin/system-playbooks", {}, authToken);

export const switchSystemPlaybookForPlatform = (name: string, enabled: boolean) =>
  fetchApi<AdminSystemPlaybook>(`/api/admin/system-playbooks/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify({ enabled }) });
