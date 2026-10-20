// The Social inbox page's pure logic (pages/workspace/social.astro): what a row says, which actions an item offers this
// caller, the filters and their URL, the reply form's defaults, and what the empty state tells a workspace. No DOM and no
// fetch, so `npm test` covers it (socialInbox.test.mjs). The API: routes/groups/social_inbox_controller.py.

export const SOCIAL_INBOX_PATH = "/workspace/social";
/** The Social engagement card on Settings → Integrations (where the task that fills the inbox is set up). */
export const SETTINGS_CARD_HREF = "/workspace/settings/integrations#social-engagement";

export type ItemKind = "comment" | "reply" | "mention";
export type ItemStatus = "new" | "seen" | "replied" | "hidden" | "liked";
export type ActionKey = "reply" | "like" | "hide" | "delete" | "message";

export interface InboxReply {
  logSlug?: string | null;
  logEntryId?: string | null;
  mode?: string | null;
  rehearsal?: boolean;
  replyId?: string | null;
  at?: string | null;
  by?: string | null;
}

export interface InboxItem {
  id: string;
  integration: string;
  network: string;
  kind: ItemKind | string;
  postId?: string | null;
  postUrl?: string | null;
  author: { id?: string | null; handle?: string | null; name?: string | null };
  text: string;
  createdAt: string;
  firstSeenAt?: string;
  url?: string | null;
  status: ItemStatus | string;
  reply?: InboxReply | null;
  actions: string[];
  replyModes: string[];
}

/** What the caller's role may do (the API's `can`). */
export type Can = Partial<Record<"seen" | "like" | "hide" | "rule" | "reply" | "delete" | "message", boolean>>;

export interface InboxEngine {
  state: "missing" | "disabled" | "enabled" | string;
  taskId?: string | null;
  rehearsal?: boolean;
  announce?: boolean;
}

export interface InboxSummary {
  available: boolean;
  new: number;
  integrations: { slug: string; name: string; network: string }[];
  engine: InboxEngine;
  can: Can;
}

export const KINDS: { value: ItemKind; label: string }[] = [
  { value: "comment", label: "Comments" },
  { value: "reply", label: "Replies" },
  { value: "mention", label: "Mentions" },
];

export const STATUSES: { value: ItemStatus; label: string }[] = [
  { value: "new", label: "New" },
  { value: "seen", label: "Seen" },
  { value: "replied", label: "Replied" },
  { value: "liked", label: "Liked" },
  { value: "hidden", label: "Hidden" },
];

const KIND_LABEL: Record<string, string> = { comment: "Comment", reply: "Reply", mention: "Mention" };

export function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? kind;
}

// ── a row ─────────────────────────────────────────────────────────────────────────────────────────────────────────

/** The author as a row shows them: their handle (with an @), else their name, else their id. */
export function authorLabel(author: InboxItem["author"] | undefined): string {
  const handle = (author?.handle ?? "").trim();
  if (handle) return handle.startsWith("@") ? handle : `@${handle}`;
  return (author?.name ?? "").trim() || (author?.id ?? "").trim() || "Someone";
}

/** One line of the text: whitespace collapsed, cut at a word with an ellipsis once past `max` characters. */
export function excerpt(text: string, max = 140): string {
  const flat = (text ?? "").replace(/\s+/g, " ").trim();
  if (flat.length <= max) return flat;
  const cut = flat.slice(0, max);
  const endsAtWord = /[\s,.;:!?-]/.test(flat[max] ?? " "); // the limit fell between words: keep every word before it
  const atWord = cut.lastIndexOf(" ");
  const kept = endsAtWord || atWord <= max * 0.6 ? cut : cut.slice(0, atWord);
  return `${kept.replace(/[\s,.;:!?-]+$/, "")}…`;
}

/** "just now", "5 min ago", "3 h ago", "2 d ago"; past a month, the date. A time in the future (clock skew) is "just now". */
export function timeAgo(iso: string | null | undefined, now: Date = new Date()): string {
  const then = iso ? new Date(iso) : null;
  if (!then || Number.isNaN(then.getTime())) return "";
  const seconds = Math.max(0, Math.floor((now.getTime() - then.getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  if (days < 31) return `${days} d ago`;
  return then.toISOString().slice(0, 10);
}

export type Tone = "neutral" | "new" | "good" | "warn" | "muted";

export interface Badge {
  label: string;
  tone: Tone;
  title?: string;
}

const STATUS_BADGE: Record<string, Badge> = {
  new: { label: "New", tone: "new" },
  seen: { label: "Seen", tone: "muted" },
  replied: { label: "Replied", tone: "good" },
  liked: { label: "Liked", tone: "neutral" },
  hidden: { label: "Hidden", tone: "warn" },
};

export function statusBadge(status: string): Badge {
  return STATUS_BADGE[status] ?? { label: status, tone: "neutral" };
}

export interface ReplyBadge extends Badge {
  /** The social-reply-log entry in the entry editor, when there is one. */
  href: string | null;
}

/** How an item was answered: sent (a rule's or a person's) or only rehearsed. None when it wasn't. */
export function replyBadge(reply: InboxReply | null | undefined): ReplyBadge | null {
  if (!reply || (!reply.at && !reply.logSlug)) return null;
  const mode = reply.mode ? ` (${reply.mode})` : "";
  const href = reply.logEntryId ? `/workspace/entries/${reply.logEntryId}` : null;
  if (reply.rehearsal) {
    return {
      label: `Rehearsal${mode}`,
      tone: "warn",
      title: "Logged as a reply it would send; nothing was sent",
      href,
    };
  }
  return {
    label: `Sent${mode}`,
    tone: "good",
    title: reply.by ? "Sent by a person from the inbox" : "Sent under a rule",
    href,
  };
}

/** The nav's "new" count badge: nothing for zero, "99+" past 99. */
export function newBadgeText(count: number | null | undefined): string {
  const n = Math.max(0, Math.floor(count ?? 0));
  return n === 0 ? "" : n > 99 ? "99+" : String(n);
}

// ── actions ───────────────────────────────────────────────────────────────────────────────────────────────────────

export interface ActionButton {
  key: ActionKey | "rule";
  label: string;
  /** Can't be undone (the page asks first). */
  destructive?: boolean;
  /** Opens a text box before it runs. */
  needsText?: boolean;
}

const ACTION_LABEL: Record<ActionKey, string> = {
  reply: "Reply",
  like: "Like",
  hide: "Hide",
  delete: "Delete",
  message: "Message",
};
const NEEDS_TEXT = new Set<string>(["reply", "message"]);
const ORDER: ActionKey[] = ["reply", "like", "hide", "delete", "message"];

/** The buttons for one item: what its network offers, limited to what the caller's role may do, "Make a rule" last. An item
 *  that is hidden offers Unhide in place of Hide. Opening the item on its network is a link, not a button (`openHref`). */
export function actionButtons(item: Pick<InboxItem, "actions" | "status">, can: Can): ActionButton[] {
  const offered = new Set(item.actions);
  const buttons: ActionButton[] = ORDER.filter((key) => offered.has(key) && can[key] === true).map((key) => ({
    key,
    label: key === "hide" && item.status === "hidden" ? "Unhide" : ACTION_LABEL[key],
    ...(key === "delete" ? { destructive: true } : {}),
    ...(NEEDS_TEXT.has(key) ? { needsText: true } : {}),
  }));
  if (can.rule === true) buttons.push({ key: "rule", label: "Make a rule" });
  return buttons;
}

/** The item on its network, when it has a link. Only an http(s) address is ever linked. */
export function openHref(item: Pick<InboxItem, "url">): string | null {
  const url = (item.url ?? "").trim();
  return /^https?:\/\//i.test(url) ? url : null;
}

export interface ReplyForm {
  /** Which modes the toggle shows: only those the network offers. */
  modes: ("private" | "public")[];
  /** The mode preselected: private whenever the network offers it. */
  mode: "private" | "public";
  /** The toggle is only worth showing with both modes. */
  showToggle: boolean;
}

export function replyForm(replyModes: string[]): ReplyForm {
  const modes = (["private", "public"] as const).filter((m) => replyModes.includes(m));
  return {
    modes: [...modes],
    mode: modes.includes("private") ? "private" : (modes[0] ?? "private"),
    showToggle: modes.length > 1,
  };
}

/** The reply as it is sent: trimmed, or null when there is nothing to send. */
export function replyText(raw: string): string | null {
  const text = (raw ?? "").trim();
  return text ? text : null;
}

/** What the page asks before a destructive action. */
export function confirmText(key: ActionKey | "rule", item: Pick<InboxItem, "network" | "author">): string {
  const who = authorLabel(item.author);
  if (key === "delete")
    return `Delete ${who}'s comment on ${item.network}? This removes it from the network and can't be undone.`;
  return "";
}

/** Replying again to an item that already has a sent reply is allowed, but the page checks first. */
export function replyAgainText(item: Pick<InboxItem, "reply">): string | null {
  const badge = replyBadge(item.reply);
  return badge && badge.tone === "good" ? "This comment was already answered. Send another reply?" : null;
}

// ── filters ───────────────────────────────────────────────────────────────────────────────────────────────────────

export interface Filters {
  integration: string;
  kind: string;
  status: string;
  q: string;
}

export const NO_FILTERS: Filters = { integration: "", kind: "", status: "", q: "" };
export const PAGE_SIZE = 50;

const clean = (v: string | null | undefined) => (v ?? "").trim();

/** The filters out of a page URL's query (anything unknown for a kind or status is dropped). */
export function parseFilters(search: URLSearchParams): Filters {
  const kind = clean(search.get("kind"));
  const status = clean(search.get("status"));
  return {
    integration: clean(search.get("integration")),
    kind: KINDS.some((k) => k.value === kind) ? kind : "",
    status: STATUSES.some((s) => s.value === status) ? status : "",
    q: clean(search.get("q")),
  };
}

/** The page URL's query for these filters (empty ones left out), so a filtered view can be bookmarked. */
export function filtersToQuery(filters: Filters): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (clean(value)) q.set(key, clean(value));
  const text = q.toString();
  return text ? `?${text}` : "";
}

/** The API's query for a page of results. */
export function apiQuery(filters: Filters, offset = 0, limit = PAGE_SIZE): string {
  const q = new URLSearchParams();
  if (clean(filters.integration)) q.set("integration", clean(filters.integration));
  if (clean(filters.kind)) q.set("kind", clean(filters.kind));
  if (clean(filters.status)) q.set("status", clean(filters.status));
  if (clean(filters.q)) q.set("q", clean(filters.q));
  q.set("limit", String(limit));
  if (offset > 0) q.set("offset", String(offset));
  return q.toString();
}

export function hasFilters(filters: Filters): boolean {
  return Object.values(filters).some((v) => clean(v));
}

/** The integration filter's options: each connected integration, named with its network when the name doesn't say. */
export function integrationOptions(integrations: InboxSummary["integrations"]): { value: string; label: string }[] {
  return integrations.map((i) => ({
    value: i.slug,
    label: i.name.toLowerCase().includes(i.network.toLowerCase()) ? i.name : `${i.name} (${i.network})`,
  }));
}

// ── the empty state and the task note ─────────────────────────────────────────────────────────────────────────────

export interface Notice {
  title: string;
  body: string;
  link?: { href: string; label: string };
}

const REHEARSAL =
  "Replies start in rehearsal: the task logs what it would send and sends nothing until you switch rehearsal off.";

/** What the page says when there is nothing to list: the inbox fills from the Social engagement task, which starts disabled and
 *  in rehearsal, so the words depend on whether that task exists, is on, or has just not found anything yet. */
export function emptyNotice(summary: InboxSummary | null, filtered: boolean): Notice {
  if (filtered)
    return { title: "Nothing matches these filters", body: "Clear a filter or change the search to see more." };
  const engine = summary?.engine;
  if (summary && !summary.available) {
    return {
      title: "No social network is connected",
      body: "The inbox shows comments, replies and mentions from your connected networks. Connect Instagram, Facebook, Mastodon or Bluesky first.",
      link: { href: "/workspace/settings/integrations", label: "Open Integrations" },
    };
  }
  if (engine?.state === "missing") {
    return {
      title: "Set up Social engagement first",
      body: `This inbox fills from the Social engagement task, which isn't in this workspace yet. ${REHEARSAL}`,
      link: { href: SETTINGS_CARD_HREF, label: "Open the Social engagement card" },
    };
  }
  if (engine?.state === "disabled") {
    return {
      title: "The Social engagement task is switched off",
      body: `This inbox fills from the Social engagement task, which checks your networks every 5 minutes, and it is disabled. ${REHEARSAL}`,
      link: { href: SETTINGS_CARD_HREF, label: "Open the Social engagement card" },
    };
  }
  return {
    title: "Nothing here yet",
    body: `New comments, replies and mentions appear within about 5 minutes of the Social engagement task's next check. ${
      engine?.rehearsal === false ? "Replies are being sent." : REHEARSAL
    }`,
  };
}

/** A line above the list when items exist but nothing new will arrive (the task is off or missing); null when all is well. */
export function engineNote(engine: InboxEngine | null | undefined): Notice | null {
  if (!engine || engine.state === "enabled") return null;
  return {
    title: engine.state === "missing" ? "Social engagement isn't set up" : "The Social engagement task is switched off",
    body: "These are the items it kept earlier; nothing new arrives until it runs.",
    link: { href: SETTINGS_CARD_HREF, label: "Open the Social engagement card" },
  };
}

/** A caller-facing message for a failed call: the API's own sentence when it sent one. */
export function errorMessage(e: unknown): string {
  const message = e instanceof Error ? e.message : String(e ?? "");
  return message.trim() || "Something went wrong.";
}
