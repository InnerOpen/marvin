---
name: social-auto-reply-rule
description: Use when someone asks for an auto-reply rule on a social network, to answer comments that mention a word or question automatically. Picks the match words, the network and the reply, writes the rule as a draft for a person to publish, and says how to test it in rehearsal before it answers anyone.
---

# An auto-reply rule

A rule answers comments for you: when a comment contains one of its words, Marvin sends the reply you wrote, once per
comment. The reply goes out exactly as written, so the rule is only as good as its words and its text. For what the
rules and the switch do, call `read_doc` with `path` `whats-new/social.md` and `section` `rules`, then `auto-reply`.
This Playbook is the procedure for writing one well.

If this workspace has a voice or style Playbook in your list, load it for the tone of the reply. For writing posts on a
particular network, load that network's own Playbook if it has one.

## You draft, a person publishes

Write the rule yourself and save it as a draft with `create_draft` (entry type `social-auto-reply`; use
`get_entry_type` first to see the fields), or change a draft with `update_draft`. Never use `compose_entry` or
`revise_entry` for this: they hand the writing to another AI that never loads Playbooks.

Publishing the rule is the approval of its text, and drafts never answer anyone. So say in your reply that nothing
happens until a person reads the draft and publishes it. A network's auto-reply switch is an admin's call too: you can't
turn it on, and you never tell anyone it is on unless you have seen it.

## 1. Ask what the rule is for

You need three things. If the request doesn't give them, ask once, all together:

- **What people write**: the words or questions the rule should catch ("price", "where to buy", "shipping").
- **Which network**, or every network. A rule for one network is more specific and wins over one for all of them.
- **What the reply should do**: answer the question, point to a page, or move the conversation somewhere private.

## 2. Choose the match words

- Use words people actually type. Several short ones beat one long phrase: `price, cost, how much`.
- A word matches as a whole word in any case ("price" catches "What's the PRICE?" but not "priceless"). A phrase such as
  `how much` works too.
- Keep them specific. A word that shows up in half the comments ("love", "thanks") answers things it shouldn't.
  Say which comments a word would catch that you don't want to answer.
- The rule needs at least one word and a reply.

## 3. Write the reply

1. It answers the likely question in the first sentence. A person who asked "how much?" gets the price or where to find it.
2. Short: a line or two. Comments are quick and a long reply reads as a form letter.
3. **No links** unless the request asks for one. When it does, use the entry's own `url` from the tools, not a guessed address.
4. No promises you can't keep ("we'll message you today") and no claims about stock, dates or prices unless the person
   gave them to you or an entry states them.
5. It reads as one reply to one comment. It is sent again to everyone who matches, so nothing in it should depend on who
   asked.

`references/examples.md` has sample rules, words to avoid and when not to write a rule at all.

## 4. Fill in the rule

- `keywords`: the words from step 2, comma-separated.
- `reply`: the text from step 3.
- `networks`: the integration slug of the network, or empty for every network.
- `reply_as`: leave the default (private) unless the request says public, or both. A public reply is seen by everyone.
- Leave `also_like` and `kinds` alone unless asked.

Save it as a draft and give the person the review link the tool returns, exactly as it came back.

## 5. Test it in rehearsal first

Tell the person how to try it before it answers anyone:

1. Publish the rule.
2. Set the network's auto-reply to **rehearsal** (the switch on the network's page). Marvin works out what it would send
   and records it on each comment as a rehearsal. Nothing is posted.
3. Read the **Rehearsal** items in that network's inbox. Check the right comments matched, and that the text reads well
   on each.
4. When it is right, switch to **on**. Unpublish the rule to stop it.

## Before you finish

- Does every word in `keywords` mean what you meant?
- Would the reply make sense to anyone who matches, not just the person who asked for the rule?
- Did you say it is a draft and nothing answers until it is published and the network's switch is on?
