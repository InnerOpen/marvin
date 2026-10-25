# Comment buckets: sort every inbox item by what it needs

Sketch, 2026-10-25. **Approved 2026-10-25** with the decisions below; building phase 1 first. Idea from the `ig-reply` skill in Jake Schincariol's
instagram-agent-skill: sort comments before answering, answer in value order, stop when the value stops.

## Why

The Social inbox lists items newest first and auto-reply rules match keywords. Nothing tells you which of 40 new
comments is a customer asking to buy, and which is "🔥". The Library's **Triage new comments** recipe already sorts
with AI (question / praise / complaint / spam), but its answer lives only inside that workflow run: the inbox, the
rules and other workflows never see it, and each comment costs its own AI call.

## The buckets

Six, network-agnostic, so they live in core (the design rule: general capability in core, a network's "how" in its
plugin — no plugin changes at all):

| bucket | what it is | what Marvin does with it |
| --- | --- | --- |
| `keyword` | it hit a published rule's keyword | the rule answers, as today |
| `lead` | describes a problem the business solves, asks price/availability/how to buy | top of the inbox; notify |
| `question` | a question others likely share | inbox; **Save as idea** (a post that answers it) |
| `feedback` | disagrees, complains, adds substance | inbox; never auto-replied |
| `support` | praise, emoji, tags, thanks | optional auto-like; no reply needed |
| `noise` | spam, pitches, bait, bots | collapsed; optional auto-hide where the network offers it |

`complaint` from the recipe folds into `feedback`, and `praise` into `support`.

## How an item gets its bucket

1. **Free, in the engine:** `keyword` when a rule's keyword hit (the engine already knows); `support` when the text is
   only emoji / tags / under ~4 words of thanks. No AI, no setting.
2. **AI, opt-in:** the rest, batched once per engine run (one structured call for up to N new items, not one per item),
   through the workspace's AI provider and its limits. Switch: **Settings → Social → Sort comments with AI**, off by
   default, with the note that comments are sent to the AI provider (same wording as the recipe today). Text is passed
   as data to classify, never as instructions. A failed or skipped call leaves the bucket empty; nothing else changes.
3. **A person:** re-sort from the inbox; a person's choice always wins and is never overwritten.

Stored on the item: `bucket`, `bucket_source` (`rule` | `heuristic` | `ai` | `person`), `bucket_at`. One migration.

Order inside a run: sort, then announce, so `social_comment_received` carries `${event.bucket}` and a workflow can
filter on it without its own AI step.

## What it changes

- **Inbox:** bucket chips with counts ("2 leads · 5 questions · 18 support"), a **Needs you** view ordered
  lead → question → feedback → keyword-unanswered, `support` and `noise` collapsed. A bucket badge on each row.
- **Rules:** an optional `buckets` field: a rule answers only items in those buckets. Examples: auto-like `support`;
  never auto-reply `noise` or `feedback`. Keywords keep working alone when `buckets` is empty.
- **Save as idea** on a `question` (and any item): a draft entry of a chosen type, the comment as its brief, linked
  back. The "Instagram: save shared posts as ideas" workflow is the same move by hand today.
- **Triage new comments** recipe: rewritten to use `${event.bucket}` (no AI step of its own), or retired.
- **Assistant:** `search`/inbox tools can filter by bucket ("show me today's leads").

## Phases

1. **No AI:** the fields + migration, `keyword` and `support` heuristics, person re-sort, inbox chips and Needs you,
   `${event.bucket}`. Useful alone (keyword hits and emoji are most of a busy thread).
2. **AI sorting**, opt-in, batched, with a per-run cap and the AI limits; `lead` / `question` / `feedback` / `noise`.
3. **Rules by bucket**, auto-like `support`, auto-hide `noise`, **Save as idea**; the recipe updated.

## Decisions (Jared, 2026-10-25)

- **Fixed bucket names**, not editable per workspace — rules and workflows rely on them.
- **`lead` is a filter**, not a notification by default.
- **AI cap 20 items per run** is fine (one batched call, only when there are new items).
- **A person's re-sort is an override only** — it doesn't feed examples back into the prompt.
- Social is core (`services/integrations/social*.py`); plugins only implement the `social.*` contract, so buckets are
  core with no plugin changes.

## Review

**Phase 1 built (2026-10-25):** `social_buckets.py` (the six names, the free `keyword` / `support` sorting), `bucket`,
`bucket_source`, `bucket_at` on items (migration `c3a7e1d95b28`), sorting on first store for polls and webhooks,
`${event.bucket}` on the new-comment trigger (with bucket choices in conditions), `POST /{id}/bucket` (EDITOR; a person's
choice is never overwritten), `?bucket=` and `buckets` counts on the list, inbox chips, row badges and the **Needs** picker.
A rule's keyword sorts by the engine's own match, so a DM counts only for a rule that names DMs and was published before it.
Full run: SQLite with plugins 6,770, Postgres 6,770, no plugins 6,751 — the only failures were two exact-list tests (the
event's fields, the `can` map), now naming `bucket` / `sort`; frontend 1,175; astro check 34 (baseline).

**Phase 2 built (2026-10-25):** `social_ai_sort.py` — an unregistered `SortCommentsOperation` through `run_operation`
(budget, provider, default model, AI execution, source `scheduled`). The engine now reads every network first, sorts once,
then announces and answers, so `${event.bucket}` has the AI's answer. Opt-in `ai_sort` on the engine task (`PUT /ai-sort`,
ADMIN; `aiSort` on the summary; the switch on Settings › Social). Answers are validated per line (one bad bucket doesn't void
the batch); left-out items are marked `bucket_source = ai` and never re-sent; an answer with no `items` marks nothing.
Not built: the **Needs you** view (the chips cover it for now).

**Phase 3 built (2026-10-25), revised by Jared's question "can auto-replies fire on an AI guess alone?":** AI narrows, never
triggers. Rules gain **Only these buckets** (`buckets`) but keep keywords required; a bucket miss on a keyword hit is held
(`bucket`, with a note) and re-checked once the item is sorted. Auto-hide `noise` was dropped (the engine still can't hide;
the existing door tests guard it). Auto-like `support` is opt-in (`like_support`, networks whose auto-reply is on, 20 per
network per run, each once). **Save as idea** (`POST /{id}/idea`, `idea_entry_id`, migration `d8f2b6c4e1a7`).


**Fix (2026-10-25):** sorting a held item no longer sends a reply. The phase 3 re-check made a person's sort (organizing
the inbox) act as an approval, up to 7 days late; removed. A bucket miss stays held; the note says to reply by hand.
