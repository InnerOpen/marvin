# Audience

Audience is where a workspace keeps the people who write to it, apart from the content it publishes. It has three parts, and each is drawn only while something feeds it:

| Part | Fed by | Where |
|---|---|---|
| **Social** | a connected network that works with Social | `/workspace/social` (see [Social](social.md)) |
| **Submissions** | a form that sends its submissions to the Audience (the default for a form) | `/workspace/audience/submissions` |
| **Subscribers** | a signup form (a form whose submissions are marked **Signup**) | `/workspace/audience/subscribers` |

In the sidebar they sit under the **Audience** heading, in that order: **Social**, **Submissions**, then **Subscribers**. The heading is drawn when any of them has something. The Audience pages are for editors and above; a lower role sees no group.

## Submissions {#submissions}

Submissions are what people send you through your forms: a contact form, a workshop enquiry, a question. A form is a submittable entry type ([Forms and submission protection](forms-and-submission-protection.md)), and each form decides where its submissions go (see [Where a form's submissions go](#destination)). A form that sends them to the Audience gets its own entry under **Submissions** in the sidebar, with the form's name and icon and how many submissions are waiting (new plus suspicious). **All submissions** (`/workspace/audience/submissions`) lists every form's; each form also has its own page (`/workspace/audience/submissions/<form slug>`).

A row is compact on every screen: who wrote it (a name field if the form has one, else an email, else the entry's title), a one-line excerpt of what they wrote, the form, when, and a status badge. Tap a row to open it. Nothing is stacked into cards on a phone.

| Badge | Means | Entry status |
|---|---|---|
| **New** | waiting for you | `inbox` |
| **Suspicious** | the spam protection held it for review; the reasons are in the badge's tooltip and in the open submission | `needs_review` |
| **Handled** | dealt with | `archived`, or any other status (a workflow may move it) |

Filter by **form**, **status** and **search** (the name, the email, any submitted text). Newest first; **Show more** pages on.

An open submission shows every field with the form's labels, the **spam check** (passed, or held for review with the reasons) and **where it came from**: the IP address, the page it was sent from, the browser, and how many times the same person has sent it (when the form's *Same person = same …* folds repeats into one entry). Only what was recorded is shown (the workspace's Submission Protection decides whether client info is captured). The actions:

- **Mark handled** archives it.
- **Not spam** (on a suspicious one) and **Reopen** (on a handled one) put it back to New.
- **Delete** moves it to the Trash, where it can be restored (a trashed submission shows in the Trash like any internal entry).
- **Open as entry** opens the entry in the normal editor; its Back link, save and Move to Trash come back to this page.

Editors and above can read and act. The submitter's **IP address is shown whole to admins and above; an editor sees it with its last part hidden** (`203.0.113.x`). The same rule holds everywhere the entry's metadata is read: see [Submitter IP addresses](#ip).

### What stays the same

A submission is still an entry of the form's type, made by the same public route: `inbox` when clean, `needs_review` when the spam protection holds it, with the protection's reasons, IP, user agent and referrer on `metadata_json.submission`. The `form_submission_received` and entry events fire as before, the *Same person = same …* match and the notification setting work as before, and a workflow that names the form (`entry_type: contact`) still finds its entries. There is no separate submissions table and no spam score: the verdict is the list of reasons.

## Where a form's submissions go {#destination}

Two settings on a submittable entry type (Entry types › the form › Submission settings, stored as `capabilities.submission.destination` and `capabilities.submission.kind`):

- **Submissions go to** ... **Audience** (the default): people writing to you, kept out of your content. **Entries**: content to review and publish, such as testimonials; this is how forms always worked.
- **A submission is a** ... **Message** (the default): someone writing to you, listed under Submissions (when the destination is Audience). **Signup**: newsletter signups, listed under Subscribers, whatever the destination.

**Internal is one flag.** A type is internal only when `capabilities.listed` is false: its entries stay out of All entries, the status lists (Inbox, Needs review, Archive and the rest), their counts and the sidebar badge, search, the AI index, the dashboard's pipeline and publishing, and are found by naming the type (`entry_type: contact` in a query or a workflow), by the entry itself, and in the Trash. The destination does not decide that by itself; it sets the flag as a **default** when you change it: choosing **Audience** sets *Show in content lists* off, choosing **Entries** sets it on (a new form that doesn't say is an Audience form, so it starts off). After that the switch (on the entry type editor, under Capabilities) is yours: a form with destination **Audience** that you switch to listed shows its entries in both Audience and the content lists. The Content model list marks every unlisted type **Internal**, with what uses it in a tooltip. Audience › Submissions lists the forms whose destination is Audience whether or not they are listed.

**A smart collection can gather internal entries.** Smart collections leave internal entries out unless their rules name the type, but a collection's **Listed** rule (`listed: "unlisted"`, **Unlisted only** in the builder) gathers the entries of every internal type at once, submissions included, and combines with status, tag and date rules (for example the unlisted drafts tagged `follow-up`). It is for your own use in the app: a collection that is **Visible to sites** still never serves internal entries through the publishing API. See [Collections](collections.md#the-listed-rule).

A form that never stored the setting has the default destination (Audience), so **every existing form is an Audience form**: a migration (`a1d7c35e9f20`) set `listed: false` on every existing submittable type that doesn't say `entries` (and on the Social types, see [Social](social.md#internal-entry-types)), and took their entries out of the smart collections that held them (the Inbox folder's count would otherwise keep counting them) and out of the AI index. Changing the flag or the destination later does the same at once. To keep a form's submissions among your entries, set its destination to **Entries**.

A **signup** form is unlisted too (when its destination is Audience, the default), and its entries are read under [Subscribers](#subscribers), not Submissions. They are still entries a workflow can find by type: the Buttondown workflows query by type and by the stored subscriber id, and keep working.

On the dashboard, a line **New form submissions (Audience)** counts the new and suspicious submissions of the Audience forms, linking to Submissions, and **Newsletter signups that need a look (Audience)** counts the signups with a problem, linking to Subscribers filtered to them. A pending signup is routine (the reader hasn't confirmed) and isn't a to-do, so only problems are counted there; the sidebar badge counts both. The entry-inbox lines count only the entries that are still listed, so nothing is counted twice. The installed app's icon badge counts the entry inbox as before and doesn't include Audience submissions.

## Subscribers {#subscribers}

Subscribers lists your newsletter signups: the entries of a form whose submission **kind** is **Signup** (Entry types › the form › Submission settings › *A submission is a*). It is drawn in the sidebar, after Submissions, only while such a form exists, with a badge for what is waiting (pending plus problems). The page is `/workspace/audience/subscribers`; editors and above.

A signup is an entry whose status mirrors the mailing list, as the Buttondown integration keeps it:

| Status | Means | Entry status |
|---|---|---|
| **Pending** | asked to join, hasn't confirmed yet | `inbox` (or any status that isn't one of the next three) |
| **Confirmed** | confirmed in the mailing list | `published` |
| **Unsubscribed** | left the list | `archived` |
| **Needs a look** | the mailing list refused it, or the spam protection held it; the review reason is on the row and in the badge's tooltip | `needs_review` |

At the top, a count per status (tap one to filter to it). Under them, a note: when a mailing-list integration acts on the signups (Buttondown, or any connected integration whose workflows or blueprint name the signup form) it says that integration handles subscribing and unsubscribing, and that a status here follows it; with none connected it says signups are still collected and listed here and hints to connect one. Then the filters (**signup form** when there are several, **status**, **from** and **to** dates, and a **search** over the email and name) and the rows, newest first: the name (else the email), the email beside a name, the form, when they signed up and a status badge. A problem shows its reason under the name. **Show more** pages on. Tap a row on any screen to open it; nothing is stacked into cards on a phone.

An open signup shows every field the form collected, where it came from (IP address, page and browser, when recorded; the IP is partly hidden below admin, see [Submitter IP addresses](#ip)), its **history** (signed up, confirmed, unsubscribed, reopened, needing a look, from the event log) and two actions:

- **Open as entry** opens the entry in the normal editor; Back, save and Move to Trash come back to this page.
- **Delete** moves the signup to the Trash, where it can be restored. It does **not** unsubscribe the reader: subscribing and unsubscribing stay with the mailing-list integration's workflows and webhook (for Buttondown: the subscribe workflow, and the confirm and unsubscribe workflows that its webhook runs).

### Setting a form up as a signup form {#signup-setup}

Applying the Buttondown integration's content sets this on its signup type for you (the *Signup form* item: `kind: signup`, `destination: audience`, and the `email` field the signup reads). By hand: Entry types › the form › Submission settings › **A submission is a › Signup**. A workspace that applied Buttondown before Subscribers existed is marked by an upgrade (migration `c4e8a2d19f57`): it reads the signup type from Buttondown's workflows (the subscribe workflow's `entry.entry_type` condition, else the confirm and unsubscribe workflows' entry steps, else the plugin's default `newsletter` when a Buttondown connection exists) and sets `kind: signup` and, where none is stored, `destination: audience`; a `kind` or `destination` someone already chose is left alone. The same upgrade removes the plugin's two old smart collections, *Confirmed subscribers* and *Unsubscribed*, where they are still exactly what the plugin created (smart, private, one signup type, one status); a renamed, public or edited one is yours and stays. Subscribers replaces them.

## Submitter IP addresses {#ip}

A form submission records where it came from on the entry (`metadata_json.submission`: IP address, user agent, referrer). An **admin or above sees the IP whole; every other member sees it with its last part hidden** (`203.0.113.x`, and the first three groups of an IPv6 address). This holds on every path that hands an entry's metadata to a member, not only the Audience pages:

- the entries API (a list, one entry, the entries search, a collection's entries, and the editor's metadata box);
- the assistants' and MCP's `get_entry`, and `find_entries` with `include_metadata`;
- the snapshot diff (a restore's before and after);
- the Event Log's detail for a form submission event (its payload carries the address).

Saving an entry never overwrites the stored address with the masked form a member read: whatever a non-admin sends back for `metadata.submission.ip_address` is replaced by what was recorded (an admin may change it). The publishing API, which serves a site rather than a member, never carries the address at all. Workspace exports are admin-only and carry it whole. The legacy Forms submissions list (editors and above) is a separate older table and still shows it.

## API {#api}

Under `/api/groups/audience` (EDITOR and above):

| Method and path | Notes |
|---|---|
| `GET /summary` | `submissions: {show, new, forms[{slug, name, icon, new}]}`, `signups: {show, forms[{slug, name, icon, new}], pending, confirmed, unsubscribed, problem, waiting}` (`waiting` = pending + problem; `new` on a form is the same for that form), `can: {act, fullIp}`. A part has `show: false` until something feeds it. |
| `GET /submissions` | `form`, `status` (repeat for several: `new`, `suspicious`, `handled`), `q`, `since`, `until`, `limit` (50, at most 200), `offset`. Newest first; `{items, total, limit, offset, new}`. Each item has `fields` (labelled), `verdict {flagged, reasons}`, `source {ip, ipMasked, userAgent, referrer, receivedAt, lastReceivedAt, count}`, `state`, `status`, `path`. |
| `GET /submissions/{id}` | One, as in the list. 404 for an entry that isn't a submission of an Audience message form. |
| `POST /submissions/{id}/handled` | Archive it. |
| `POST /submissions/{id}/reopen` | Back to the inbox (not spam / reopen). |
| `DELETE /submissions/{id}` | To the Trash. |
| `GET /subscribers` | `form`, `status` (repeat for several: `pending`, `confirmed`, `unsubscribed`, `problem`), `q` (email, name or title), `since`, `until`, `limit` (50, at most 200), `offset`. Newest first; `{items, total, limit, offset, counts{pending, confirmed, unsubscribed, problem}, forms, integrations[{slug, name, provider}], can}`. `counts` follow the form filter only. Each item has `email`, `name`, `form`, `status`, `entryStatus`, `reason` and `reviewReasons` (a problem's), `signedUpAt`, `path`. |
| `GET /subscribers/{id}` | One in full, `{subscriber}`: the item plus `fields` (labelled), `source {ip, ipMasked, userAgent, referrer, …}` and `history[{label, at}]`. 404 for an entry that isn't a signup form's. |
| `DELETE /subscribers/{id}` | To the Trash (`{subscriber: null}`). Does not unsubscribe anyone. |

An action is an ordinary status change of the entry, so `entry_updated` and the status events fire as in the entry editor.
