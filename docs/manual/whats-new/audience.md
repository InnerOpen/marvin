# Audience

Audience is where a workspace keeps the people who write to it, apart from the content it publishes. It has three parts, and each is drawn only while something feeds it:

| Part | Fed by | Where |
|---|---|---|
| **Social** | a connected network that works with Social | `/workspace/social` (see [Social](social.md)) |
| **Submissions** | a form that sends its submissions to the Audience (the default for a form) | `/workspace/audience/submissions` |
| **Subscribers** | a signup form | coming in the next release |

In the sidebar they sit under the **Audience** heading, in that order: **Social**, then **Submissions**. The heading is drawn when Social or Submissions has something. The Audience pages are for editors and above; a lower role sees no group.

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

Editors and above can read and act. The submitter's **IP address is shown whole to admins and above; an editor sees it with its last part hidden** (`203.0.113.x`). This hides it in the Audience pages only: the entry itself, which anyone in the workspace can read through the entries API, still carries the address in `metadata.submission`.

### What stays the same

A submission is still an entry of the form's type, made by the same public route: `inbox` when clean, `needs_review` when the spam protection holds it, with the protection's reasons, IP, user agent and referrer on `metadata_json.submission`. The `form_submission_received` and entry events fire as before, the *Same person = same …* match and the notification setting work as before, and a workflow that names the form (`entry_type: contact`) still finds its entries. There is no separate submissions table and no spam score: the verdict is the list of reasons.

## Where a form's submissions go {#destination}

Two settings on a submittable entry type (Entry types › the form › Submission settings, stored as `capabilities.submission.destination` and `capabilities.submission.kind`):

- **Submissions go to** ... **Audience** (the default): people writing to you, kept out of your content. **Entries**: content to review and publish, such as testimonials; this is how forms always worked.
- **A submission is a** ... **Message** (the default): someone writing to you, listed under Submissions. **Signup**: newsletter signups, listed under Subscribers (shown only for the Audience destination).

**Internal is one flag.** A type is internal only when `capabilities.listed` is false: its entries stay out of All entries, the status lists (Inbox, Needs review, Archive and the rest), their counts and the sidebar badge, search, the AI index, the dashboard's pipeline and publishing, and are found by naming the type (`entry_type: contact` in a query or a workflow), by the entry itself, and in the Trash. The destination does not decide that by itself; it sets the flag as a **default** when you change it: choosing **Audience** sets *Show in content lists* off, choosing **Entries** sets it on (a new form that doesn't say is an Audience form, so it starts off). After that the switch (on the entry type editor, under Capabilities) is yours: a form with destination **Audience** that you switch to listed shows its entries in both Audience and the content lists. The Content model list marks every unlisted type **Internal**, with what uses it in a tooltip. Audience › Submissions lists the forms whose destination is Audience whether or not they are listed.

**A smart collection can gather internal entries.** Smart collections leave internal entries out unless their rules name the type, but a collection's **Listed** rule (`listed: "unlisted"`, **Unlisted only** in the builder) gathers the entries of every internal type at once, submissions included, and combines with status, tag and date rules (for example the unlisted drafts tagged `follow-up`). It is for your own use in the app: a collection that is **Visible to sites** still never serves internal entries through the publishing API. See [Collections](collections.md#the-listed-rule).

A form that never stored the setting has the default destination (Audience), so **every existing form is an Audience form**: a migration (`a1d7c35e9f20`) set `listed: false` on every existing submittable type that doesn't say `entries` (and on the Social types, see [Social](social.md#internal-entry-types)), and took their entries out of the smart collections that held them (the Inbox folder's count would otherwise keep counting them) and out of the AI index. Changing the flag or the destination later does the same at once. To keep a form's submissions among your entries, set its destination to **Entries**.

A **signup** form is unlisted too, but Subscribers isn't there yet, so its submissions are not listed anywhere in Audience until the next release. They are still entries a workflow can find by type (the Buttondown signup workflow queries by type, and keeps working).

On the dashboard, a line **New form submissions (Audience)** counts the new and suspicious submissions of the Audience forms, linking to Submissions; the entry-inbox lines count only the entries that are still listed, so nothing is counted twice. The installed app's icon badge counts the entry inbox as before and doesn't include Audience submissions.

## Subscribers {#subscribers}

Coming in the next release: one row per newsletter signup (a form with kind **Signup**), with its status as the mailing-list integration mirrors it, and a count per status. Until then the **Signup** kind marks the form and the Audience API reports that one exists.

## API {#api}

Under `/api/groups/audience` (EDITOR and above):

| Method and path | Notes |
|---|---|
| `GET /summary` | `submissions: {show, new, forms[{slug, name, icon, new}]}`, `signups: {show, forms}`, `can: {act, fullIp}`. A part has `show: false` until something feeds it. |
| `GET /submissions` | `form`, `status` (repeat for several: `new`, `suspicious`, `handled`), `q`, `since`, `until`, `limit` (50, at most 200), `offset`. Newest first; `{items, total, limit, offset, new}`. Each item has `fields` (labelled), `verdict {flagged, reasons}`, `source {ip, ipMasked, userAgent, referrer, receivedAt, lastReceivedAt, count}`, `state`, `status`, `path`. |
| `GET /submissions/{id}` | One, as in the list. 404 for an entry that isn't a submission of an Audience message form. |
| `POST /submissions/{id}/handled` | Archive it. |
| `POST /submissions/{id}/reopen` | Back to the inbox (not spam / reopen). |
| `DELETE /submissions/{id}` | To the Trash. |

An action is an ordinary status change of the entry, so `entry_updated` and the status events fire as in the entry editor.
