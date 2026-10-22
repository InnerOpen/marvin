// Playbooks (Settings › AI › Playbooks): the pure logic of the page and its editor: the row and status words, the Agent Skills
// checks on the standard fields, the "long body" warning, and the entry a form turns into. A Playbook is an entry of the internal
// `playbook` type (backend: services/playbooks, routes/groups/playbooks_controller.py); the list comes from that route and the
// editor saves through the ordinary entries API. No DOM and no fetch, so `npm test` covers it (playbooks.test.mjs).

import { excerpt, timeAgo } from "./socialInbox.ts";

export const PLAYBOOKS_PATH = "/workspace/settings/ai-playbooks";
export const NEW_PLAYBOOK_PATH = `${PLAYBOOKS_PATH}/new`;
// The Agent Skills limits on the standard fields. They mirror the backend's (services/playbooks/skill_md.py NAME_MAX,
// DESCRIPTION_MAX, COMPATIBILITY_MAX), which enforces them on import and in the entry schema: change both together.
export const NAME_MAX = 64;
export const DESCRIPTION_MAX = 1024;
export const COMPATIBILITY_MAX = 500;
/** The Agent Skills spec's advice for a SKILL.md body: past this it is long for an agent to carry. A warning, never a block. */
export const BODY_LINES_ADVISED = 500;
/** The same pattern the backend holds (services/playbooks/skill_md.py NAME_PATTERN): words of a-z and 0-9 joined by single hyphens. */
export const NAME_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/;

export interface PlaybookItem {
  id: string;
  name: string;
  description: string;
  status: string;
  manualOnly?: boolean;
  updatedAt?: string | null;
  /** When an agent last loaded it; null when not lately. */
  lastUsedAt?: string | null;
  /** Set when an integration shipped it: which one, and whether that integration has since been removed. */
  fromIntegration?: { source: string; name: string; integrationId?: string | null; removed?: boolean } | null;
  /** Set on a copy of a system Playbook: where it came from and whether the original has changed since. */
  copiedFrom?: PlaybookCopiedFrom | null;
}

export interface PlaybookCopiedFrom {
  name: string;
  label?: string;
  /** The version it was copied at. */
  version?: string;
  /** The original's installed version now; null when it is gone. */
  currentVersion?: string | null;
  upstreamChanged?: boolean;
}

export interface PlaybookForm {
  name: string;
  description: string;
  license: string;
  compatibility: string;
  allowedTools: string;
  manualOnly: boolean;
  body: string;
  /** On a proposed change: the name of the published Playbook it would replace (publishing it updates that one). */
  replaces?: string;
}

export const EMPTY_FORM: PlaybookForm = { name: "", description: "", license: "", compatibility: "", allowedTools: "", manualOnly: false, body: "" };

export function editorPath(id: string): string {
  return `${PLAYBOOKS_PATH}/${encodeURIComponent(id)}`;
}

// ── status ─────────────────────────────────────────────────────────────────────────────────────────────────────────

/** The word for an entry status on this page: only a published Playbook steers an agent, so everything else reads as a draft. */
export function statusLabel(status: string | null | undefined): string {
  if (status === "published") return "Published";
  if (status === "archived") return "Archived";
  return "Draft";
}

/** The pill's modifier class (global.css `.pill.published` / `.pill.draft`): published is the one that is live. */
export function statusTone(status: string | null | undefined): "published" | "draft" | "" {
  if (status === "published") return "published";
  return status === "archived" ? "" : "draft";
}

export function statusHint(status: string | null | undefined): string {
  if (status === "published") return "Agents can find and load this Playbook.";
  return "Agents cannot see this Playbook until it is published.";
}

// ── the list ───────────────────────────────────────────────────────────────────────────────────────────────────────

export interface PlaybookRow {
  id: string;
  href: string;
  name: string;
  summary: string;
  label: string;
  tone: "published" | "draft" | "";
  manualOnly: boolean;
  /** "Used 3 d ago", or "Not used lately". */
  used: string;
  /** "From Buttondown" / "From a removed integration" for an integration's Playbook; null for a person's. */
  origin: string | null;
  /** "Copied from System · Marvin 1.42.0" on a copy of a system Playbook; null otherwise. */
  copied: string | null;
  /** "System Playbook changed: 1.40.0 → 1.42.0" when the original changed since the copy; null otherwise. */
  upstream: string | null;
  /** Where "View it" goes (the original's read-only page) when there is an upstream hint. */
  upstreamHref: string | null;
}

/** The list's "used recently" words for a Playbook. */
export function usedLabel(lastUsedAt: string | null | undefined, now: Date = new Date()): string {
  const when = timeAgo(lastUsedAt, now);
  return when ? `Used ${when}` : "Not used lately";
}

export function playbookRow(item: PlaybookItem, now: Date = new Date()): PlaybookRow {
  return {
    id: item.id,
    href: editorPath(item.id),
    name: item.name,
    summary: excerpt(item.description ?? "", 140),
    label: statusLabel(item.status),
    tone: statusTone(item.status),
    manualOnly: item.manualOnly === true,
    used: usedLabel(item.lastUsedAt, now),
    origin: originLabel(item),
    copied: copiedLabel(item),
    upstream: upstreamHint(item),
    upstreamHref: item.copiedFrom?.upstreamChanged ? systemPath(item.copiedFrom.name) : null,
  };
}

/** "Copied from System · Marvin 1.42.0" for a copy of a system Playbook. */
export function copiedLabel(item: Pick<PlaybookItem, "copiedFrom">): string | null {
  const from = item.copiedFrom;
  if (!from) return null;
  return `Copied from ${[from.label || "a system Playbook", from.version].filter(Boolean).join(" ")}`;
}

/** The hint on a copy whose original changed ("1.40.0 → 1.42.0"); null when it hasn't, or the original is gone. */
export function upstreamHint(item: Pick<PlaybookItem, "copiedFrom">): string | null {
  const from = item.copiedFrom;
  if (!from?.upstreamChanged) return null;
  const range = from.version && from.currentVersion && from.version !== from.currentVersion ? `: ${from.version} → ${from.currentVersion}` : "";
  return `The system Playbook changed${range}. Your copy is unchanged.`;
}

/** Where an integration's Playbook came from, in words. A Playbook of a removed integration stays (a published one keeps working). */
export function originLabel(item: Pick<PlaybookItem, "fromIntegration">): string | null {
  const from = item.fromIntegration;
  if (!from) return null;
  return from.removed ? "From a removed integration" : `From ${from.name || from.source}`;
}

/** `?from=integration:<id>` (the footprint's link): the id it names, or null. */
export function fromIntegrationId(param: string | null | undefined): string | null {
  const match = /^integration:(.+)$/.exec(param ?? "");
  return match ? match[1] : null;
}

/** The Playbooks of one integration (the card's "What it installed" link), or all of them when none is named. */
export function fromIntegration(items: PlaybookItem[], integrationId: string | null): PlaybookItem[] {
  return integrationId ? items.filter((i) => i.fromIntegration?.integrationId === integrationId) : items;
}

// ── used recently (the editor page) ───────────────────────────────────────────────────────────────────────────────

/** One run that loaded the Playbook (GET /groups/playbooks/{id}/uses). */
export interface PlaybookUse {
  executionId: string;
  agentSlug?: string | null;
  agentName?: string | null;
  usedAt?: string | null;
  /** The Ask conversation the run belongs to, when the viewer may open it. */
  threadId?: string | null;
}

export interface UseRow {
  key: string;
  agent: string;
  when: string;
  /** Where to open the run; null when there is no conversation to open (or it is someone else's). */
  href: string | null;
}

const ASK_PAGE_PATH = "/workspace/settings/ai-ask";

export function useRow(use: PlaybookUse, now: Date = new Date()): UseRow {
  return {
    key: use.executionId,
    agent: use.agentName || use.agentSlug || "An agent",
    when: timeAgo(use.usedAt, now) || "earlier",
    href: use.threadId ? `${ASK_PAGE_PATH}?thread=${encodeURIComponent(use.threadId)}` : null,
  };
}

export const NO_USES_NOTE = "Not used lately. Agents load a Playbook when a request matches it, and each use will show here.";

/** Published first, then drafts, then archived; by name within each (the API already orders by name). */
export function sortedItems(items: PlaybookItem[]): PlaybookItem[] {
  const rank = (s: string) => (s === "published" ? 0 : s === "archived" ? 2 : 1);
  return [...items].sort((a, b) => rank(a.status) - rank(b.status) || a.name.localeCompare(b.name));
}

export function listSummary(items: PlaybookItem[]): string {
  if (items.length === 0) return "No Playbooks yet";
  const live = items.filter((i) => i.status === "published").length;
  const n = items.length;
  return `${n} Playbook${n === 1 ? "" : "s"}, ${live} published`;
}

export const EMPTY_NOTICE = {
  title: "No Playbooks yet",
  body: "A Playbook is a written procedure an agent follows when a task calls for it: how you write a release note, triage a bug, answer a returns email. Write one, publish it, and agents can find it.",
};

// ── the Agent Skills checks ────────────────────────────────────────────────────────────────────────────────────────

export type FieldErrors = Partial<Record<"name" | "description" | "compatibility", string>>;

/** The checks the Agent Skills spec puts on the standard fields. Empty when the form may be saved. */
export function validate(form: Pick<PlaybookForm, "name" | "description" | "compatibility">): FieldErrors {
  const errors: FieldErrors = {};
  const name = form.name.trim();
  if (!name) errors.name = "Give the Playbook a name.";
  else if (name.length > NAME_MAX) errors.name = `The name can be at most ${NAME_MAX} characters (it is ${name.length}).`;
  else if (!NAME_PATTERN.test(name)) {
    errors.name = "Use lowercase letters, digits and single hyphens, such as release-notes. It cannot start or end with a hyphen.";
  }
  const description = form.description.trim();
  if (!description) errors.description = "Say what the Playbook does and when to use it: agents read this to decide whether to load it.";
  else if (description.length > DESCRIPTION_MAX) {
    errors.description = `The description can be at most ${DESCRIPTION_MAX} characters (it is ${description.length}).`;
  }
  if (form.compatibility.trim().length > COMPATIBILITY_MAX) {
    errors.compatibility = `Compatibility can be at most ${COMPATIBILITY_MAX} characters.`;
  }
  return errors;
}

export function isValid(errors: FieldErrors): boolean {
  return Object.keys(errors).length === 0;
}

// ── the body ───────────────────────────────────────────────────────────────────────────────────────────────────────

export function bodyLines(body: string | null | undefined): number {
  const text = (body ?? "").replace(/\s+$/, "");
  return text === "" ? 0 : text.split(/\r\n|\r|\n/).length;
}

/** The advice shown beside a long body, or null. Saving is never blocked by it. */
export function lengthWarning(body: string | null | undefined): string | null {
  const lines = bodyLines(body);
  if (lines <= BODY_LINES_ADVISED) return null;
  return `This body is ${lines} lines. Agents do best with about ${BODY_LINES_ADVISED} or fewer: consider moving detail into a reference file. You can still save it.`;
}

// ── form <-> entry ─────────────────────────────────────────────────────────────────────────────────────────────────

interface EntryLike {
  status?: string | null;
  slug?: string | null;
  dataJson?: Record<string, unknown> | null;
}

const text = (value: unknown): string => (typeof value === "string" ? value : "");

/** The editor's form from a saved Playbook entry. The name is the entry's slug (what an agent asks for it by). */
export function formFromEntry(entry: EntryLike | null | undefined): PlaybookForm {
  const data = entry?.dataJson ?? {};
  return {
    name: text(entry?.slug) || text(data.name),
    description: text(data.description),
    license: text(data.license),
    compatibility: text(data.compatibility),
    allowedTools: text(data.allowed_tools),
    manualOnly: data.manual_only === true,
    body: text(data.body),
    ...(text(data.replaces) ? { replaces: text(data.replaces) } : {}),
  };
}

/** What to send to the entries API for a form: the name is the title and the slug; a field left empty is left out. */
export function entryPayload(form: PlaybookForm, entryTypeId: string | null, status?: string) {
  const name = form.name.trim();
  const dataJson: Record<string, unknown> = { name, description: form.description.trim(), manual_only: form.manualOnly };
  const optional: Array<[string, string]> = [
    ["license", form.license.trim()],
    ["compatibility", form.compatibility.trim()],
    ["allowed_tools", form.allowedTools.trim().replace(/\s+/g, " ")],
  ];
  for (const [key, value] of optional) if (value) dataJson[key] = value;
  dataJson.body = form.body;
  if (form.replaces) dataJson.replaces = form.replaces; // a proposed change stays one when it is saved here
  return {
    ...(entryTypeId ? { entryTypeId } : {}),
    title: name,
    slug: name,
    dataJson,
    ...(status ? { status } : {}),
  };
}

/**
 * The buttons the editor offers for a Playbook in `status`. Publishing, unpublishing and changing a published Playbook are an
 * Admin's (the API refuses an editor with a 403): `canPublish` false leaves an editor with drafts only, and nothing on a live one.
 */
export function actionsFor(
  status: string | null | undefined,
  isNew: boolean,
  canPublish = true,
): Array<{ key: "save" | "publish" | "unpublish"; label: string; primary: boolean }> {
  if (!canPublish) return status === "published" ? [] : [{ key: "save", label: "Save draft", primary: true }];
  if (isNew) return [{ key: "save", label: "Save draft", primary: false }, { key: "publish", label: "Save and publish", primary: true }];
  if (status === "published") return [{ key: "save", label: "Save", primary: true }, { key: "unpublish", label: "Unpublish", primary: false }];
  return [{ key: "save", label: "Save draft", primary: false }, { key: "publish", label: "Publish", primary: true }];
}

/** The file name for an exported Playbook: the one in the response's Content-Disposition, else `<name>.zip`. */
export function exportFilename(contentDisposition: string | null, name: string): string {
  const found = /filename="([^"]+)"/.exec(contentDisposition ?? "");
  return found ? found[1] : `${name}.zip`;
}

// ── system Playbooks (shipped by Marvin and its plugins; read-only, read from the packages) ─────────────────────────────

export const SYSTEM_PATH = `${PLAYBOOKS_PATH}/system`;

export function systemPath(name: string): string {
  return `${SYSTEM_PATH}/${encodeURIComponent(name)}`;
}

/** What the System section and the read-only page get from `GET /groups/playbooks/system[/{name}]`. */
export interface SystemPlaybookItem {
  name: string;
  description: string;
  /** "System · Marvin", "System · Social", "System · <plugin>". */
  label: string;
  version?: string;
  manualOnly?: boolean;
  allowedTools?: string;
  /** "on" | "off" (this workspace) | "off_server" (the platform) | "hidden" (your Playbook has the name) | "replaced" (your published copy). */
  state: string;
  detail?: string;
  /** This workspace's own switch, whatever the platform's is. */
  enabled?: boolean;
  suggestedCopyName?: string;
  fileCount?: number;
}

export interface SystemPlaybookRead extends SystemPlaybookItem {
  source: string;
  fingerprint?: string;
  body: string;
  files: { path: string; text: string }[];
  warnings: string[];
}

export interface SystemRow {
  name: string;
  href: string;
  summary: string;
  label: string;
  version: string;
  manualOnly: boolean;
  allowedTools: string;
  /** The sentence for any state but "on": "Off for this platform", "Hidden: your Playbook x has this name"; "" when it is on. */
  note: string;
  on: boolean;
  /** The switch is the workspace's own: it can be on while the platform's is off. */
  enabled: boolean;
  /** The platform switched it off: this workspace's switch changes nothing until it is back. */
  serverOff: boolean;
  /** What Copy proposes as the name ("" when the suggestion is taken). */
  suggestedName: string;
}

export function systemRow(item: SystemPlaybookItem): SystemRow {
  return {
    name: item.name,
    href: systemPath(item.name),
    summary: excerpt(item.description ?? "", 140),
    label: item.label,
    version: item.version ?? "",
    manualOnly: item.manualOnly !== false,
    allowedTools: (item.allowedTools ?? "").trim(),
    note: item.state === "on" ? "" : (item.detail ?? ""),
    on: item.state === "on",
    enabled: item.enabled !== false,
    serverOff: item.state === "off_server",
    suggestedName: item.suggestedCopyName ?? "",
  };
}

/** The System section's groups: one per label (Marvin, Social, each plugin), in the order the labels first appear. */
export function systemGroups(items: SystemPlaybookItem[]): { label: string; rows: SystemRow[] }[] {
  const groups: { label: string; rows: SystemRow[] }[] = [];
  for (const item of items) {
    let group = groups.find((g) => g.label === item.label);
    if (!group) groups.push((group = { label: item.label, rows: [] }));
    group.rows.push(systemRow(item));
  }
  return groups;
}

export const SYSTEM_INTRO =
  "Procedures Marvin and its plugins give every workspace. They are read-only and update with the release that ships them: switch one off here, or copy it to make your own.";

/** The switch's title, and what it does. */
export function switchTitle(row: Pick<SystemRow, "enabled" | "serverOff">): string {
  if (row.serverOff) return "Switched off for the whole platform by an admin";
  return row.enabled ? "Switch this Playbook off for this workspace" : "Switch this Playbook on for this workspace";
}

/** A system Playbook's own page: the use list's empty note. */
export const NO_SYSTEM_USES_NOTE = "Not used lately in this workspace. Agents load it when a request matches it (or when someone names it, if it is manual-only).";

/** What the read-only page shows about where a Playbook comes from: "System · Marvin, 1.42.0". */
export function sourceLine(item: Pick<SystemPlaybookItem, "label" | "version">): string {
  return [item.label, item.version].filter(Boolean).join(", ");
}

/** The copy dialog's error for a refused name (409: taken) or a bad one (400), in the API's own words; a fallback otherwise. */
export function copyError(error: unknown): string {
  const text = error instanceof Error ? error.message : String(error ?? "");
  return text || "The copy failed. Try again.";
}

// ── the agent settings' picker ─────────────────────────────────────────────────────────────────────────────────────

export interface PickerEntry {
  name: string;
  /** Switched off here or for the platform: shown, not offered. */
  off: boolean;
  manualOnly: boolean;
  title: string;
}

/** What an agent's Playbook picker lists: the workspace's published Playbooks ("Yours"), then a "System" group per label. */
export function pickerGroups(own: PlaybookItem[], system: SystemPlaybookItem[]): { label: string; entries: PickerEntry[] }[] {
  const groups: { label: string; entries: PickerEntry[] }[] = [];
  const mine = own
    .filter((p) => p.status === "published")
    .map((p) => ({ name: p.name, off: false, manualOnly: p.manualOnly === true, title: excerpt(p.description ?? "", 120) }));
  if (mine.length) groups.push({ label: "Yours", entries: mine });
  for (const item of system) {
    let group = groups.find((g) => g.label === item.label);
    if (!group) groups.push((group = { label: item.label, entries: [] }));
    group.entries.push({
      name: item.name,
      off: item.state === "off" || item.state === "off_server",
      manualOnly: item.manualOnly !== false,
      title: excerpt(item.description ?? "", 120),
    });
  }
  return groups;
}

/** The names in an agent's chosen or always-load text that are system Playbooks switched off: the form marks them "(off)". */
export function offNames(text: string, system: SystemPlaybookItem[]): string[] {
  const off = new Set(system.filter((i) => i.state === "off" || i.state === "off_server").map((i) => i.name));
  return text
    .split(/[\n,]+/)
    .map((n) => n.trim())
    .filter((n) => off.has(n));
}

/** Where a name in a run's "Used:" line goes: a system Playbook's read-only page (its id is `system:<name>`), else nowhere. */
export function usedPlaybookHref(playbook: { id: string; name?: string | null }): string | null {
  const name = (playbook.name ?? "").trim();
  return playbook.id?.startsWith("system:") && name ? systemPath(name) : null;
}

/** The integration card's line for the system Playbooks a provider gives every workspace; null when it gives none. */
export function alsoGives(playbooks: { name: string }[] | null | undefined): { text: string; names: string[] } | null {
  const names = (playbooks ?? []).map((p) => p.name).filter(Boolean);
  if (!names.length) return null;
  return { text: `Also gives every workspace: ${names.join(", ")} (System ${names.length === 1 ? "Playbook" : "Playbooks"}, read-only)`, names };
}
