/**
 * The Social inbox (routes/groups/social_inbox_controller.py): the comments, replies and mentions the Social engagement task
 * kept, and a person's actions on them. Reading, marking seen, like, hide and "Make a rule" are EDITOR and above; reply,
 * delete and message are ADMIN and above (the summary's `can` says which of them the caller may use). Plain fetchApi until the
 * SDK release carries them. Pass authToken in SSR (from Astro.cookies); omit it in the browser.
 */

import type { Filters, InboxItem, InboxSummary } from "../socialInbox";
import { apiQuery } from "../socialInbox";
import { fetchApi } from "./client";

const BASE = "/api/groups/social-inbox";

export interface InboxList {
  items: InboxItem[];
  total: number;
  limit: number;
  offset: number;
  /** New items in the whole workspace, whatever the filters. */
  new: number;
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
  /** In the social-reply-log, so the poll never answers this comment. */
  logged: boolean;
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

export const getSummary = (authToken?: string) => fetchApi<InboxSummary>(`${BASE}/summary`, {}, authToken);

export const listItems = (filters: Filters, offset = 0, authToken?: string) =>
  fetchApi<InboxList>(`${BASE}?${apiQuery(filters, offset)}`, {}, authToken);

export const markSeen = (body: { ids?: string[]; all?: boolean; integration?: string }) =>
  post<{ changed: number }>("/seen", body);

export const reply = (id: string, text: string, isPrivate: boolean) =>
  post<ReplyResult>(`/${encodeURIComponent(id)}/reply`, { text, private: isPrivate });

export const like = (id: string) => post<ActionResult>(`/${encodeURIComponent(id)}/like`);

export const hide = (id: string, hidden: boolean) => post<ActionResult>(`/${encodeURIComponent(id)}/hide`, { hidden });

export const remove = (id: string) => fetchApi<ActionResult>(`${BASE}/${encodeURIComponent(id)}`, { method: "DELETE" });

export const message = (id: string, text: string) => post<ActionResult>(`/${encodeURIComponent(id)}/message`, { text });

export const makeRule = (id: string, replyText = "") =>
  post<RuleResult>(`/${encodeURIComponent(id)}/rule`, { reply: replyText });
