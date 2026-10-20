// Audience: the pure logic of Audience › Submissions (the sidebar fold, a row, the status words, the filters, the actions, the
// empty state). The submissions are what people send through the forms whose destination is the Audience (the default for a form):
// entries of an internal type, read here instead of among the workspace's content. No DOM and no fetch, so `npm test` covers it
// (audience.test.mjs). The API: routes/groups/audience_controller.py; the word for an entry status is the backend's `state_of`.

import { withReturn } from "./entryBack.ts";
import { type Badge, excerpt, newBadgeText } from "./socialInbox.ts";

export const AUDIENCE_PATH = "/workspace/audience";
export const SUBMISSIONS_PATH = `${AUDIENCE_PATH}/submissions`;
export const PAGE_SIZE = 50;

export type SubmissionState = "new" | "suspicious" | "handled";
export type ActionKey = "handled" | "reopen" | "delete";

export interface AudienceForm {
  slug: string;
  name: string;
  icon?: string | null;
  /** Submissions waiting: new plus suspicious. */
  new: number;
}

export interface AudienceSummary {
  submissions: { show: boolean; new: number; forms: AudienceForm[] };
  /** A signup form exists (`submission.kind: signup`): Subscribers, in a later release, draws on it. */
  signups: { show: boolean; forms: AudienceForm[] };
  can: { act?: boolean; fullIp?: boolean };
}

export interface SubmissionField {
  key: string;
  label: string;
  type?: string | null;
  value: unknown;
}

export interface Submission {
  id: string;
  form: AudienceForm;
  title: string;
  state: SubmissionState | string;
  status: string;
  fields: SubmissionField[];
  verdict: { flagged: boolean; reasons: string[] };
  source: {
    ip?: string | null;
    ipMasked?: boolean;
    userAgent?: string | null;
    referrer?: string | null;
    receivedAt?: string | null;
    lastReceivedAt?: string | null;
    count?: number;
  };
  createdAt: string;
  /** The entry editor, /workspace/entries/{id}. */
  path: string;
}

// ── routes ────────────────────────────────────────────────────────────────────────────────────────────────────────

/** One form's submissions (its entry type's slug); no slug is every form. */
export function submissionsPath(slug?: string | null): string {
  return slug ? `${SUBMISSIONS_PATH}/${encodeURIComponent(slug)}` : SUBMISSIONS_PATH;
}

/** Whether a page path is an Audience submissions page (the sidebar fold stays open on it). */
export function isSubmissionsPath(path: string): boolean {
  return path === SUBMISSIONS_PATH || path.startsWith(`${SUBMISSIONS_PATH}/`);
}

/** The form a submissions page path names, or null on the all-forms page. */
export function formOfPath(path: string): string | null {
  if (!path.startsWith(`${SUBMISSIONS_PATH}/`)) return null;
  const slug = path.slice(SUBMISSIONS_PATH.length + 1).split(/[/?#]/)[0] ?? "";
  try {
    return decodeURIComponent(slug) || null;
  } catch {
    return null;
  }
}

// ── the sidebar ───────────────────────────────────────────────────────────────────────────────────────────────────

export interface SubmissionsNavChild {
  /** The form's slug (the page marks its link so an action can update the count). */
  slug: string;
  href: string;
  label: string;
  icon: string;
  /** The waiting-count badge text ("" for none, "99+" past 99). */
  badge: string;
  badgeLabel: string;
}

export interface SubmissionsNav {
  label: string;
  href: string;
  /** Everything waiting across the forms: the badge on the fold's own row. */
  badge: string;
  badgeLabel: string;
  children: SubmissionsNavChild[];
}

/** The sidebar's Submissions fold under Audience, or null — nothing is drawn — until a form sends its submissions to the
 *  Audience. One child per Audience message form (its name and icon) with its waiting count. */
export function submissionsNav(summary: AudienceSummary | null | undefined): SubmissionsNav | null {
  const forms = summary?.submissions?.forms ?? [];
  if (!summary?.submissions?.show || forms.length === 0) return null;
  const badge = (n: number) => ({ badge: newBadgeText(n), badgeLabel: `${n} new` });
  return {
    label: "Submissions",
    href: SUBMISSIONS_PATH,
    ...badge(summary.submissions.new),
    children: forms.map((f) => ({ slug: f.slug, href: submissionsPath(f.slug), label: f.name, icon: f.icon || "✉️", ...badge(f.new) })),
  };
}

/** The Audience heading is drawn when Social or Submissions has something (Subscribers joins them later). */
export function showAudienceGroup(parts: (object | null | undefined)[]): boolean {
  return parts.some((p) => p != null);
}

// ── a row ─────────────────────────────────────────────────────────────────────────────────────────────────────────

const STATE_BADGE: Record<string, Badge> = {
  new: { label: "New", tone: "new", title: "Waiting for you" },
  suspicious: { label: "Suspicious", tone: "warn", title: "The spam protection held it for review" },
  handled: { label: "Handled", tone: "muted", title: "Dealt with" },
};

/** The status badge: New, Suspicious (with the reasons as its tooltip when given) or Handled. */
export function stateBadge(state: string, reasons: string[] = []): Badge {
  const base = STATE_BADGE[state] ?? { label: state || "Unknown", tone: "neutral" as const };
  return state === "suspicious" && reasons.length > 0 ? { ...base, title: reasons.join("; ") } : base;
}

/** A submitted value as text: a list joined, a boolean yes/no, anything else as a string. */
export function fieldText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map(fieldText).filter(Boolean).join(", ");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value).trim();
}

const NAME_KEY = /^(full[_ -]?name|your[_ -]?name|name|first[_ -]?name|contact[_ -]?name)$/i;
const EMAIL_KEY = /e-?mail/i;

function textOf(item: Pick<Submission, "fields">, test: (f: SubmissionField) => boolean): { key: string; text: string } | null {
  for (const f of item.fields ?? []) {
    const text = fieldText(f.value);
    if (text && test(f)) return { key: f.key, text };
  }
  return null;
}

/** Who wrote it: a name field when the form has one, else an email field, else the entry's title. */
export function whoOf(item: Pick<Submission, "fields" | "title">): string {
  const name = textOf(item, (f) => NAME_KEY.test(f.key) || NAME_KEY.test(f.label ?? ""));
  if (name) return name.text;
  const email = textOf(item, (f) => f.type === "email" || EMAIL_KEY.test(f.key));
  return email?.text || (item.title ?? "").trim() || "Someone";
}

/** One line of what they wrote: the first long-text field, else the first other text that isn't the name or email shown as who,
 *  else every other value in a row; cut with an ellipsis. */
export function excerptOf(item: Pick<Submission, "fields" | "title">, max = 140): string {
  const name = textOf(item, (f) => NAME_KEY.test(f.key) || NAME_KEY.test(f.label ?? ""));
  const email = textOf(item, (f) => f.type === "email" || EMAIL_KEY.test(f.key));
  const skip = new Set([name?.key, email?.key].filter(Boolean) as string[]);
  const rest = (item.fields ?? []).filter((f) => !skip.has(f.key) && fieldText(f.value));
  const long = rest.find((f) => f.type === "textarea" || f.type === "richtext" || f.type === "markdown");
  const chosen = long ?? rest[0];
  if (chosen) return excerpt(fieldText(chosen.value), max);
  // only a name and an email: show the email beside a name
  return name && email ? excerpt(email.text, max) : "";
}

export interface Row {
  id: string;
  who: string;
  text: string;
  form: string;
  formIcon: string;
  at: string;
  badge: Badge;
  /** New or suspicious: drawn bold with a dot. */
  unread: boolean;
}

/** One compact row: who, a text excerpt, the form, when, and the status badge. */
export function submissionRow(item: Submission): Row {
  return {
    id: item.id,
    who: whoOf(item),
    text: excerptOf(item),
    form: item.form?.name ?? "",
    formIcon: item.form?.icon || "✉️",
    at: item.createdAt,
    badge: stateBadge(item.state, item.verdict?.reasons ?? []),
    unread: item.state === "new" || item.state === "suspicious",
  };
}

// ── the open submission ───────────────────────────────────────────────────────────────────────────────────────────

export interface ActionButton {
  key: ActionKey;
  label: string;
  /** Moves it to the Trash (the page asks first; the Trash restores it). */
  destructive?: boolean;
  /** The label says what it does to this one: "Not spam" on a suspicious submission, "Reopen" on a handled one. */
  hint?: string;
}

/** The buttons for one submission, for a caller who may act (the API's `can.act`): handled while it is open, "Not spam" on a
 *  suspicious one, "Reopen" on a handled one, and Delete. None for a caller who may not. */
export function actionButtons(item: Pick<Submission, "state">, can: AudienceSummary["can"] | undefined): ActionButton[] {
  if (can?.act !== true) return [];
  const buttons: ActionButton[] = [];
  if (item.state === "suspicious") buttons.push({ key: "reopen", label: "Not spam", hint: "Clears it back to New" });
  if (item.state !== "handled") buttons.push({ key: "handled", label: "Mark handled", hint: "Archives it" });
  if (item.state === "handled") buttons.push({ key: "reopen", label: "Reopen", hint: "Back to New" });
  buttons.push({ key: "delete", label: "Delete", destructive: true, hint: "Moves it to the Trash" });
  return buttons;
}

export function confirmText(key: ActionKey): string {
  return key === "delete" ? "Move this submission to the Trash? You can restore it from the Trash." : "";
}

/** "Open as entry": the entry editor, with Back, save and Move to Trash returning to this page. */
export function openAsEntryHref(item: Pick<Submission, "path">, returnTo: string): string {
  return withReturn(item.path, returnTo);
}

export interface Line {
  label: string;
  value: string;
}

/** What the spam protection made of it, in words. */
export function verdictText(item: Pick<Submission, "verdict" | "state">): { tone: "good" | "warn"; text: string } {
  const reasons = item.verdict?.reasons ?? [];
  if (item.verdict?.flagged || reasons.length > 0) {
    const why = reasons.length > 0 ? `: ${reasons.join("; ")}` : "";
    return item.state === "suspicious"
      ? { tone: "warn", text: `Held for review${why}` }
      : { tone: "warn", text: `Was held for review${why}` };
  }
  return { tone: "good", text: "Passed the spam checks" };
}

/** Where it came from: IP (partly hidden for an editor), referrer, user agent, repeats. Only what was recorded. */
export function sourceLines(item: Pick<Submission, "source">): Line[] {
  const s = item.source ?? {};
  const lines: Line[] = [];
  if (s.ip) lines.push({ label: s.ipMasked ? "IP (partly hidden)" : "IP address", value: s.ip });
  if (s.referrer) lines.push({ label: "From page", value: s.referrer });
  if (s.userAgent) lines.push({ label: "Browser", value: s.userAgent });
  if ((s.count ?? 1) > 1) lines.push({ label: "Sent", value: `${s.count} times by the same person` });
  return lines;
}

// ── filters ───────────────────────────────────────────────────────────────────────────────────────────────────────

export interface Filters {
  /** A form's slug; "" is every form (a form's own page fixes it). */
  form: string;
  status: SubmissionState | "";
  q: string;
}

export const NO_FILTERS: Filters = { form: "", status: "", q: "" };

export const STATES: { value: SubmissionState; label: string }[] = [
  { value: "new", label: "New" },
  { value: "suspicious", label: "Suspicious" },
  { value: "handled", label: "Handled" },
];

const clean = (v: string | null | undefined) => (v ?? "").trim();

export function parseFilters(search: URLSearchParams, form = ""): Filters {
  const status = clean(search.get("status"));
  return {
    form: form || clean(search.get("form")),
    status: STATES.some((s) => s.value === status) ? (status as SubmissionState) : "",
    q: clean(search.get("q")).slice(0, 200),
  };
}

/** The page's own query string for a view (`form` stays out of it on a form's own page: it is in the path). */
export function filtersToQuery(filters: Filters, formInPath = false): string {
  const q = new URLSearchParams();
  if (!formInPath && clean(filters.form)) q.set("form", clean(filters.form));
  if (clean(filters.status)) q.set("status", clean(filters.status));
  if (clean(filters.q)) q.set("q", clean(filters.q));
  const text = q.toString();
  return text ? `?${text}` : "";
}

/** The API's query for a page of results. */
export function apiQuery(filters: Filters, offset = 0, limit = PAGE_SIZE): string {
  const q = new URLSearchParams();
  if (clean(filters.form)) q.set("form", clean(filters.form));
  if (clean(filters.status)) q.set("status", clean(filters.status));
  if (clean(filters.q)) q.set("q", clean(filters.q));
  q.set("limit", String(limit));
  if (offset > 0) q.set("offset", String(offset));
  return q.toString();
}

export function hasFilters(filters: Pick<Filters, "status" | "q"> & { form?: string }, ignoreForm = false): boolean {
  return Boolean(clean(filters.status) || clean(filters.q) || (!ignoreForm && clean(filters.form)));
}

/** The form filter's options: each Audience message form. */
export function formOptions(summary: AudienceSummary | null | undefined): { value: string; label: string }[] {
  return (summary?.submissions?.forms ?? []).map((f) => ({ value: f.slug, label: f.name }));
}

// ── the empty state ───────────────────────────────────────────────────────────────────────────────────────────────

export interface Notice {
  title: string;
  body: string;
  link?: { href: string; label: string };
}

/** What the page says when there is nothing to list: a filter that matches nothing; a form with no submissions yet; no form at
 *  all (then the sidebar draws no Submissions either, and this page says how one appears). */
export function emptyNotice(summary: AudienceSummary | null, filtered: boolean, form?: AudienceForm | null): Notice {
  if (filtered) return { title: "Nothing matches these filters", body: "Clear a filter or change the search to see more." };
  if (summary && !summary.submissions.show) {
    return {
      title: "No form sends its submissions here yet",
      body: "A form sends what people write to you to the Audience by default. Make a submittable entry type under Entry types, and its submissions appear here.",
      link: { href: "/workspace/entry-types", label: "Open Entry types" },
    };
  }
  if (form) {
    return { title: `No ${form.name} submissions yet`, body: `When someone sends the ${form.name} form, it shows here, newest first.` };
  }
  return { title: "Nothing here yet", body: "When someone sends one of your forms, it shows here, newest first." };
}

export function errorMessage(e: unknown): string {
  const message = e instanceof Error ? e.message : String(e ?? "");
  return message.trim() || "Something went wrong.";
}
