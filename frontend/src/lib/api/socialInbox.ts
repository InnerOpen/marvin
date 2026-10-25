/**
 * Social (routes/groups/social_inbox_controller.py): the comments, replies and mentions the engagement poll kept, a person's
 * actions on them, a network's rules and replies, and its auto-reply switch. Reading, marking seen, like, hide, rules and "Make a
 * rule" are EDITOR and above; reply, delete, message and the auto-reply switch are ADMIN and above (the summary's `can` says which
 * of them the caller may use). Plain fetchApi until the SDK release carries them. Pass authToken in SSR (from Astro.cookies); omit
 * it in the browser.
 */

import type { AutoReplyMode, Filters, InboxItem, InboxSummary } from "../socialInbox";
import { apiQuery } from "../socialInbox";
import type { Rule } from "../socialSpace";
import { fetchApi } from "./client";

const BASE = "/api/groups/social-inbox";

export interface InboxList {
  items: InboxItem[];
  total: number;
  limit: number;
  offset: number;
  /** New items in the whole workspace, whatever the filters. */
  new: number;
  /** Items per bucket, and "unsorted" (of the listed integration, whatever the other filters). */
  buckets?: Record<string, number>;
}

export interface ActionResult {
  ok: boolean;
  /** The item afterwards; null once it is deleted. */
  item: InboxItem | null;
  messageId?: string | null;
}

export interface ReplyResult {
  replied: boolean;
  private: boolean;
  replyId?: string | null;
  url?: string | null;
  item: InboxItem;
}

export interface RuleResult {
  id: string;
  slug: string;
  keywords: string[];
  /** The entry editor, e.g. /workspace/entries/{id}. The rule is a draft until published. */
  path: string;
}

const post = <T>(path: string, body?: unknown) =>
  fetchApi<T>(`${BASE}${path}`, { method: "POST", ...(body === undefined ? {} : { body: JSON.stringify(body) }) });

/** `visit`: a Social page asks, so the workspace's Social plumbing (the rule type, the engine's task) is made first. */
export const getSummary = (authToken?: string, visit = false) =>
  fetchApi<InboxSummary>(`${BASE}/summary${visit ? "?visit=true" : ""}`, {}, authToken);

export const listItems = (filters: Filters, offset = 0, authToken?: string) =>
  fetchApi<InboxList>(`${BASE}?${apiQuery(filters, offset)}`, {}, authToken);

export const markSeen = (body: { ids?: string[]; all?: boolean; integration?: string }) =>
  post<{ changed: number }>("/seen", body);

export const reply = (id: string, text: string, isPrivate: boolean) =>
  post<ReplyResult>(`/${encodeURIComponent(id)}/reply`, { text, private: isPrivate });

export const like = (id: string) => post<ActionResult>(`/${encodeURIComponent(id)}/like`);

export const hide = (id: string, hidden: boolean) => post<ActionResult>(`/${encodeURIComponent(id)}/hide`, { hidden });
/** Move an item to the inbox's Trash (Marvin only) or restore it. */
export const trash = (id: string, trashed: boolean) => post<ActionResult>(`/${encodeURIComponent(id)}/trash`, { trashed });

/** Sort an item into a bucket, or clear it (null). Marvin never overwrites a person's choice. */
export const sortItem = (id: string, bucket: string | null) => post<ActionResult>(`/${encodeURIComponent(id)}/bucket`, { bucket });

export const remove = (id: string) => fetchApi<ActionResult>(`${BASE}/${encodeURIComponent(id)}`, { method: "DELETE" });

export const message = (id: string, text: string) => post<ActionResult>(`/${encodeURIComponent(id)}/message`, { text });

export const makeRule = (id: string, replyText = "") =>
  post<RuleResult>(`/${encodeURIComponent(id)}/rule`, { reply: replyText });

export const listReplies = (query: string, authToken?: string) =>
  fetchApi<InboxList>(`${BASE}/replies?${query}`, {}, authToken);

export const listRules = (integration: string | null, authToken?: string) =>
  fetchApi<{ rules: Rule[] }>(
    `${BASE}/rules${integration ? `?integration=${encodeURIComponent(integration)}` : ""}`,
    {},
    authToken,
  );

/** A new blank rule as a draft, for a network (its slug goes in `networks`) or, with null, for every network. */
export const createRule = (integration: string | null) => post<Rule>("/rules", { integration });

export const setRulePublished = (id: string, published: boolean) =>
  fetchApi<Rule>(`${BASE}/rules/${encodeURIComponent(id)}/published`, {
    method: "PUT",
    body: JSON.stringify({ published }),
  });

export const setAutoReply = (slug: string, mode: AutoReplyMode) =>
  fetchApi<{ integration: string; autoReply: AutoReplyMode }>(
    `${BASE}/integrations/${encodeURIComponent(slug)}/auto-reply`,
    {
      method: "PUT",
      body: JSON.stringify({ mode }),
    },
  );
