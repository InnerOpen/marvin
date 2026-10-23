// The Social inbox page's pure logic (pages/workspace/social.astro): what a row says, which actions an item offers this
// caller, the filters and their URL, the reply form's defaults, and what the empty state tells a workspace. No DOM and no
// fetch, so `npm test` covers it (socialInbox.test.mjs). The API: routes/groups/social_inbox_controller.py.

export const SOCIAL_INBOX_PATH = "/workspace/social";
/** Where a workspace connects a network (Social has no setup of its own). */
export const INTEGRATIONS_HREF = "/workspace/settings/integrations";

export type ItemKind = "comment" | "reply" | "mention" | "message" | "story_reply" | "story_mention" | "reaction" | "live_comment";

/** Kinds that arrive in the account's direct messages: answered by a message, never by a rule or a comment reply. */
export const DIRECT_KINDS: ReadonlySet<string> = new Set(["message", "story_reply", "story_mention", "reaction"]);

/** Something an item arrived with: a picture, a shared post and its caption. */
export interface Attachment {
  type?: string | null;
  url?: string | null;
  title?: string | null;
}
export type ItemStatus = "new" | "seen" | "replied" | "hidden" | "liked";

/** The Status filter's Trash: items a person moved out of the inbox (restorable). Not a status: the API's `trashed`. */
export const TRASH = "trash";
export type ActionKey = "reply" | "like" | "hide" | "delete" | "message";

/** The reply recorded on an item (the item is the reply log): a rule's or a person's, live or rehearsal. */
export interface InboxReply {
  mode?: string | null;
  rehearsal?: boolean;
  replyId?: string | null;
  /** What was sent, or would have been in a rehearsal. */
  text?: string | null;
  /** The rule entry's slug that fired; none for a person's reply. */
  rule?: string | null;
  /** That rule's entry (the editor is /workspace/entries/{id}). */
  ruleEntryId?: string | null;
  note?: string | null;
  at?: string | null;
  /** The person who replied from the inbox; none for a rule's reply. */
  by?: string | null;
  byName?: string | null;
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
  attachments?: Attachment[] | null;
  trashedAt?: string | null;
  createdAt: string;
  firstSeenAt?: string;
  url?: string | null;
  status: ItemStatus | string;
  reply?: InboxReply | null;
  actions: string[];
  replyModes: string[];
}

/** What the caller's role may do (the API's `can`). */
export type Can = Partial<
  Record<
    "seen" | "like" | "hide" | "trash" | "rule" | "rules" | "publish" | "auto_reply" | "reply" | "delete" | "message",
    boolean
  >
>;

export type AutoReplyMode = "off" | "rehearsal" | "on";

/** A connected social network: an enabled integration that offers a `social.*` capability. */
export interface SocialNetwork {
  slug: string;
  name: string;
  /** The plugin's slug: what its logo is served under. */
  provider: string;
  network: string;
  capabilities?: string[];
  readsComments?: boolean;
  canReply?: boolean;
  autoReply: AutoReplyMode | string;
  /** Items of this network still new. */
  new: number;
}

export interface InboxSummary {
  /** Whether Social appears at all (an enabled integration offers a `social.*` capability). */
  show: boolean;
  new: number;
  integrations: SocialNetwork[];
  can: Can;
}

export const KINDS: { value: ItemKind; label: string }[] = [
  { value: "comment", label: "Comments" },
  { value: "reply", label: "Replies" },
  { value: "mention", label: "Mentions" },
  { value: "message", label: "Messages" },
  { value: "story_reply", label: "Story replies" },
  { value: "story_mention", label: "Story mentions" },
  { value: "reaction", label: "Reactions" },
  { value: "live_comment", label: "Live comments" },
];

export const STATUSES: { value: ItemStatus | typeof TRASH; label: string }[] = [
  { value: "new", label: "New" },
  { value: "seen", label: "Seen" },
  { value: "replied", label: "Replied" },
  { value: "liked", label: "Liked" },
  { value: "hidden", label: "Hidden" },
  { value: "trash", label: "Trash" },
];

const KIND_LABEL: Record<string, string> = {
  comment: "Comment",
  reply: "Reply",
  mention: "Mention",
  message: "Message",
  story_reply: "Story reply",
  story_mention: "Story mention",
  reaction: "Reaction",
  live_comment: "Live comment",
};

const ATTACHMENT_LABEL: Record<string, string> = {
  ig_post: "The shared post",
  ig_reel: "The shared reel",
  reel: "The shared reel",
  share: "The shared post",
  story: "The story",
  story_mention: "The story",
  image: "The picture",
  video: "The video",
  audio: "The voice message",
};

/** An item's attachments as links: only http(s) addresses, each with a label; `picture` when it can show as an image. */
export function attachmentLinks(item: Pick<InboxItem, "attachments">): { href: string; label: string; picture: boolean }[] {
  return (item.attachments ?? [])
    .filter((a) => /^https?:\/\//i.test((a.url ?? "").trim()))
    .map((a) => ({
      href: (a.url ?? "").trim(),
      label: ATTACHMENT_LABEL[a.type ?? ""] ?? "Attachment",
      picture: ["ig_post", "share", "image", "story", "story_mention"].includes(a.type ?? ""),
    }));
}

/** What a row says for an item with no text of its own: a shared post's caption, else what it carried. */
export function itemText(item: Pick<InboxItem, "text" | "attachments" | "kind">): string {
  if ((item.text ?? "").trim()) return item.text;
  const first = (item.attachments ?? [])[0];
  if (first?.title) return first.title;
  if (first) return `(${(ATTACHMENT_LABEL[first.type ?? ""] ?? "an attachment").replace(/^The /, "a ")})`;
  return item.kind === "mention" ? "(mentioned you)" : "";
}

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

/** How an item was answered: sent (a rule's or a person's) or only rehearsed. None when it wasn't. */
export function replyBadge(reply: InboxReply | null | undefined): Badge | null {
  if (!reply || !reply.at) return null;
  const mode = reply.mode ? ` (${reply.mode})` : "";
  if (reply.rehearsal) {
    return { label: `Rehearsal${mode}`, tone: "warn", title: "Recorded as a reply it would send; nothing was sent" };
  }
  return {
    label: `Sent${mode}`,
    tone: "good",
    title: reply.by ? "Sent by a person from the inbox" : "Sent under a rule",
  };
}

/** The nav's "new" count badge: nothing for zero, "99+" past 99. */
export function newBadgeText(count: number | null | undefined): string {
  const n = Math.max(0, Math.floor(count ?? 0));
  return n === 0 ? "" : n > 99 ? "99+" : String(n);
}

// ── actions ───────────────────────────────────────────────────────────────────────────────────────────────────────

export interface ActionButton {
  key: ActionKey | "rule" | "trash";
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
export function actionButtons(item: Pick<InboxItem, "actions" | "status"> & { kind?: string; trashedAt?: string | null }, can: Can): ActionButton[] {
  const offered = new Set(item.actions);
  const buttons: ActionButton[] = ORDER.filter((key) => offered.has(key) && can[key] === true).map((key) => ({
    key,
    label: key === "hide" && item.status === "hidden" ? "Unhide" : key === "message" && DIRECT_KINDS.has(item.kind ?? "") ? "Reply" : ACTION_LABEL[key],
    ...(key === "delete" ? { destructive: true } : {}),
    ...(NEEDS_TEXT.has(key) ? { needsText: true } : {}),
  }));
  // Trash is Marvin's own (nothing changes on the network): Restore when it is already there.
  if (can.trash === true) buttons.push({ key: "trash", label: item.trashedAt ? "Restore" : "Trash" });
  // A rule made from a direct message answers direct messages (by a message back); a reaction has nothing to answer.
  if (can.rule === true && item.kind !== "reaction") buttons.push({ key: "rule", label: "Make a rule" });
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
  if (clean(filters.status) === TRASH) q.set("trashed", "true");
  else if (clean(filters.status)) q.set("status", clean(filters.status));
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

// ── the empty state ───────────────────────────────────────────────────────────────────────────────────────────────

export interface Notice {
  title: string;
  body: string;
  link?: { href: string; label: string };
}

/** What the page says when there is nothing to list. Social has no setup: the inbox fills on its own (about every 5 minutes) from
 *  every connected network that reads comments, whatever its auto-reply is set to. With no connected network the words send the
 *  workspace to Integrations; for one network they say whether it can be read. */
export function emptyNotice(summary: InboxSummary | null, filtered: boolean, network?: SocialNetwork | null): Notice {
  if (filtered)
    return { title: "Nothing matches these filters", body: "Clear a filter or change the search to see more." };
  if (summary && !summary.show) {
    return {
      title: "No social network is connected",
      body: "Social shows the comments, replies and mentions of your connected networks. Connect Instagram, Facebook, Mastodon or Bluesky and it appears.",
      link: { href: INTEGRATIONS_HREF, label: "Open Integrations" },
    };
  }
  if (network && network.readsComments === false) {
    return {
      title: `${network.name} can't be read for comments`,
      body: "This network can post, but its plugin doesn't offer reading comments, so there is no inbox to fill.",
    };
  }
  return {
    title: "Nothing here yet",
    body: "New comments, replies and mentions appear within about 5 minutes of the next check, and stay for 30 days.",
  };
}

/** A caller-facing message for a failed call: the API's own sentence when it sent one. */
export function errorMessage(e: unknown): string {
  const message = e instanceof Error ? e.message : String(e ?? "");
  return message.trim() || "Something went wrong.";
}
