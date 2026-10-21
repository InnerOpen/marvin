// Playbooks (Settings › AI › Playbooks): the pure logic of the page and its editor: the row and status words, the Agent Skills
// checks on the standard fields, the "long body" warning, and the entry a form turns into. A Playbook is an entry of the internal
// `playbook` type (backend: services/playbooks, routes/groups/playbooks_controller.py); the list comes from that route and the
// editor saves through the ordinary entries API. No DOM and no fetch, so `npm test` covers it (playbooks.test.mjs).

import { excerpt } from "./socialInbox.ts";

export const PLAYBOOKS_PATH = "/workspace/settings/ai-playbooks";
export const NEW_PLAYBOOK_PATH = `${PLAYBOOKS_PATH}/new`;
export const NAME_MAX = 64;
export const DESCRIPTION_MAX = 1024;
export const COMPATIBILITY_MAX = 500;
/** The Agent Skills spec's advice for a SKILL.md body: past this it is long for an agent to carry. A warning, never a block. */
export const BODY_LINES_ADVISED = 500;
/** The same pattern the backend's field schema holds (services/playbooks NAME_PATTERN): words of a-z and 0-9 joined by single hyphens. */
export const NAME_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/;

export interface PlaybookItem {
  id: string;
  name: string;
  description: string;
  status: string;
  manualOnly?: boolean;
  updatedAt?: string | null;
}

export interface PlaybookForm {
  name: string;
  description: string;
  license: string;
  compatibility: string;
  allowedTools: string;
  manualOnly: boolean;
  body: string;
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
}

export function playbookRow(item: PlaybookItem): PlaybookRow {
  return {
    id: item.id,
    href: editorPath(item.id),
    name: item.name,
    summary: excerpt(item.description ?? "", 140),
    label: statusLabel(item.status),
    tone: statusTone(item.status),
    manualOnly: item.manualOnly === true,
  };
}

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
