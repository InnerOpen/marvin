// Social as its own space: the pure logic of the sidebar group (Audience › Social), the network pages
// (/workspace/social/<integration>: Inbox · Rules · Replies, with the auto-reply switch in the header), a network's rules and its
// replies. No DOM and no fetch, so `npm test` covers it (socialSpace.test.mjs). The API: routes/groups/social_inbox_controller.py;
// the inbox's own logic: socialInbox.ts.

import {
  type AutoReplyMode,
  authorLabel,
  type Badge,
  type Can,
  excerpt,
  type InboxItem,
  type InboxReply,
  type InboxSummary,
  newBadgeText,
  SOCIAL_INBOX_PATH,
  type SocialNetwork,
} from "./socialInbox.ts";

// ── routes and tabs ───────────────────────────────────────────────────────────────────────────────────────────────

export type Tab = "inbox" | "rules" | "replies";
export const TABS: { value: Tab; label: string }[] = [
  { value: "inbox", label: "Inbox" },
  { value: "rules", label: "Rules" },
  { value: "replies", label: "Replies" },
];

/** A network's page, optionally on a tab (the inbox is the page itself). */
export function networkPath(slug: string, tab: Tab = "inbox"): string {
  const base = `${SOCIAL_INBOX_PATH}/${encodeURIComponent(slug)}`;
  return tab === "inbox" ? base : `${base}?tab=${tab}`;
}

/** The tab a page URL asks for (anything unknown is the inbox). */
export function parseTab(search: URLSearchParams): Tab {
  const tab = (search.get("tab") ?? "").trim();
  return TABS.some((t) => t.value === tab) ? (tab as Tab) : "inbox";
}

export function tabLinks(slug: string, active: Tab): { value: Tab; label: string; href: string; current: boolean }[] {
  return TABS.map((t) => ({ ...t, href: networkPath(slug, t.value), current: t.value === active }));
}

export function findNetwork(summary: InboxSummary | null | undefined, slug: string): SocialNetwork | null {
  return summary?.integrations.find((n) => n.slug === slug) ?? null;
}

/** Whether a page path is Social's (the sidebar group stays open on it). */
export function isSocialPath(path: string): boolean {
  return path === SOCIAL_INBOX_PATH || path.startsWith(`${SOCIAL_INBOX_PATH}/`);
}

// ── the sidebar group ─────────────────────────────────────────────────────────────────────────────────────────────

export interface SocialNavChild {
  href: string;
  label: string;
  /** The integration's provider slug (its logo); none for the all-networks Inbox. */
  provider: string | null;
  /** The new-count badge text ("" for none, "99+" past 99). */
  badge: string;
  /** Aria label for the badge. */
  badgeLabel: string;
}

export interface SocialNav {
  label: string;
  /** New items across every network: the badge on the group's own row. */
  badge: string;
  children: SocialNavChild[];
}

/** The sidebar's Social group under Audience, or null — nothing is drawn — unless an enabled integration offers a `social.*`
 *  capability. Children: the all-networks Inbox with its new count, then one entry per connected network. */
export function socialNav(summary: InboxSummary | null | undefined): SocialNav | null {
  if (!summary?.show || summary.integrations.length === 0) return null;
  const badge = (n: number) => ({ badge: newBadgeText(n), badgeLabel: `${n} new` });
  return {
    label: "Social",
    badge: newBadgeText(summary.new),
    children: [
      { href: SOCIAL_INBOX_PATH, label: "Inbox", provider: null, ...badge(summary.new) },
      ...summary.integrations.map((n) => ({
        href: networkPath(n.slug),
        label: n.name,
        provider: n.provider,
        ...badge(n.new),
      })),
    ],
  };
}

// ── the auto-reply switch ─────────────────────────────────────────────────────────────────────────────────────────

export interface ModeOption {
  value: AutoReplyMode;
  label: string;
  /** The one line under the switch. */
  help: string;
}

export const MODES: ModeOption[] = [
  {
    value: "off",
    label: "Off",
    help: "Nothing is answered. The network is still read, so the inbox fills and workflows can start on new comments.",
  },
  {
    value: "rehearsal",
    label: "Rehearsal",
    help: "Published rules are run as a dry run: Marvin records the reply it would send on each comment and sends nothing.",
  },
  { value: "on", label: "On", help: "Published rules reply on their own, as written, once per comment." },
];

export function modeOf(network: Pick<SocialNetwork, "autoReply"> | null | undefined): AutoReplyMode {
  const mode = network?.autoReply;
  return mode === "rehearsal" || mode === "on" ? mode : "off";
}

export function modeHelp(mode: string): string {
  return (MODES.find((m) => m.value === mode) ?? MODES[0]).help;
}

export interface Switch {
  options: ModeOption[];
  value: AutoReplyMode;
  /** Only an admin can change it (the API's `can.auto_reply`), and only on a network that can reply. */
  editable: boolean;
  /** Why it can't be changed, when it can't. */
  note: string | null;
  help: string;
}

export function autoReplySwitch(network: SocialNetwork, can: Can): Switch {
  const value = modeOf(network);
  const canReply = network.canReply !== false;
  const editable = can.auto_reply === true && canReply;
  return {
    options: canReply ? MODES : MODES.filter((m) => m.value === "off"),
    value,
    editable,
    note: !canReply
      ? `${network.name} can't send replies, so auto-reply stays off.`
      : can.auto_reply === true
        ? null
        : "Only a workspace admin can change this.",
    help: modeHelp(value),
  };
}

// ── rules ─────────────────────────────────────────────────────────────────────────────────────────────────────────

export interface Rule {
  id: string;
  slug: string;
  title: string;
  status: string;
  published: boolean;
  keywords: string[];
  reply: string;
  networks: string[];
  allNetworks: boolean;
  post: string;
  replyAs: string;
  alsoLike: boolean;
  kinds: string[];
  path: string;
}

/** The list in the order the engine reads it: rules for one post, then for one network, then for every network; the oldest first
 *  within each (the API's order). The first rule that fits a comment is the one that answers. */
export function orderRules(rules: Rule[]): Rule[] {
  const rank = (r: Rule) => (r.post ? 0 : 1) * 2 + (r.allNetworks ? 1 : 0);
  return rules
    .map((r, i) => ({ r, i }))
    .sort((a, b) => rank(a.r) - rank(b.r) || a.i - b.i)
    .map((x) => x.r);
}

/** "Applies to": every network, this network (when the page is a network's), or the networks it names. */
export function ruleScope(rule: Pick<Rule, "allNetworks" | "networks" | "post">, slug: string | null): string {
  const where = rule.allNetworks
    ? "All networks"
    : slug && rule.networks.includes(slug)
      ? "This network"
      : rule.networks.join(", ");
  return rule.post ? `${where} · one post` : where;
}

export function ruleBadges(rule: Pick<Rule, "published" | "allNetworks">): Badge[] {
  const badges: Badge[] = [
    rule.published
      ? { label: "Published", tone: "good", title: "Answers comments under it" }
      : { label: "Draft", tone: "muted", title: "Does nothing until it is published" },
  ];
  return badges;
}

/** A rule's row title: its keywords, or a nudge while it has none. */
export function ruleTitle(rule: Pick<Rule, "keywords" | "title">): string {
  return rule.keywords.length > 0 ? rule.keywords.join(", ") : "No keywords yet";
}

export function ruleReplyLine(rule: Pick<Rule, "reply">): string {
  return excerpt(rule.reply, 120) || "No reply written yet";
}

export interface PublishAction {
  label: string;
  /** What the button asks for: publish (true) or take back to a draft (false). */
  publish: boolean;
  /** Publishing is the approval of the reply text. */
  note: string | null;
}

/** The publish / unpublish button for a rule, for a caller who may (the API's `can.publish`); null for anyone else. */
export function publishAction(rule: Pick<Rule, "published">, can: Can): PublishAction | null {
  if (can.publish !== true) return null;
  return rule.published
    ? { label: "Unpublish", publish: false, note: "It stops answering and goes back to a draft." }
    : { label: "Publish", publish: true, note: "Publishing approves the reply text: it is sent as written." };
}

export const NEW_RULE_LABEL = "New rule";
export const NEW_RULE_ALL_LABEL = "New rule for every network";

/** The explanation above a network's rules. */
export function rulesLede(network: Pick<SocialNetwork, "name">): string {
  return `The rules for ${network.name}, then the ones for every network. A rule for one post answers first, then one for this network, then one for every network; the oldest first.`;
}

export function rulesEmpty(network: Pick<SocialNetwork, "name">, can: Can): { title: string; body: string } {
  return {
    title: "No rules yet",
    body:
      can.rule === true
        ? `A rule is a keyword and the reply it triggers. Start one for ${network.name}; it stays a draft until you publish it.`
        : "A rule is a keyword and the reply it triggers. An editor can start one.",
  };
}

// ── replies ───────────────────────────────────────────────────────────────────────────────────────────────────────

export interface ReplyRow {
  who: string;
  /** What was sent (or would have been), one line. */
  line: string;
  live: boolean;
  badge: Badge;
  /** "by rule <slug>" / "by <name>". */
  by: string;
  at: string | null;
  /** The rule entry in the editor, when a rule sent it. */
  ruleHref: string | null;
}

export function replyBy(reply: Pick<InboxReply, "by" | "byName" | "rule">): string {
  if (reply.by) return `by ${(reply.byName ?? "").trim() || "a person"}`;
  return reply.rule ? `by rule ${reply.rule}` : "by a rule";
}

/** One row of the Replies view: who it answered, what was sent, live or rehearsal, by whom, and when. Null for an item with no reply. */
export function replyRow(item: Pick<InboxItem, "author" | "reply">): ReplyRow | null {
  const reply = item.reply;
  if (!reply || !reply.at) return null;
  const live = !reply.rehearsal;
  const mode = reply.mode ? ` (${reply.mode})` : "";
  return {
    who: authorLabel(item.author),
    line: excerpt(reply.text ?? "", 120) || "(no text recorded)",
    live,
    badge: live
      ? { label: `Live${mode}`, tone: "good", title: "Sent" }
      : { label: `Rehearsal${mode}`, tone: "warn", title: "A dry run: nothing was sent" },
    by: replyBy(reply),
    at: reply.at,
    ruleHref: reply.ruleEntryId ? `/workspace/entries/${reply.ruleEntryId}` : null,
  };
}

export function repliesEmpty(network: Pick<SocialNetwork, "name" | "autoReply">): { title: string; body: string } {
  return {
    title: "No replies yet",
    body:
      modeOf(network) === "off"
        ? `Auto-reply is off for ${network.name}, so nothing is answered. Replies you send from the inbox show here.`
        : `Replies to ${network.name} comments, sent or rehearsed, show here with the rule that fired.`,
  };
}

/** The Replies view's filter: all, live only, or rehearsals only — the API's `rehearsal` parameter. */
export type ReplyFilter = "all" | "live" | "rehearsal";
export const REPLY_FILTERS: { value: ReplyFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "live", label: "Live" },
  { value: "rehearsal", label: "Rehearsal" },
];

export function repliesQuery(slug: string, filter: ReplyFilter, offset = 0, limit = 50): string {
  const q = new URLSearchParams({ integration: slug, limit: String(limit) });
  if (filter === "live") q.set("rehearsal", "false");
  if (filter === "rehearsal") q.set("rehearsal", "true");
  if (offset > 0) q.set("offset", String(offset));
  return q.toString();
}

export function parseReplyFilter(search: URLSearchParams): ReplyFilter {
  const value = (search.get("show") ?? "").trim();
  return value === "live" || value === "rehearsal" ? value : "all";
}
