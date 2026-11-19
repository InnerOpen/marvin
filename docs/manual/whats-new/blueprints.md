# Blueprints

A blueprint describes something a workspace could have (a collection, an entry type, fields on an entry type, a scheduled task, an event subscription, an incoming webhook or a workflow) and creates nothing until you apply it.

## What it does

A **blueprint** is a declarative description of one piece of workspace structure. Core ships a small catalog of them; an installed [integration](integrations.md) contributes its own through the SDK's `ContentBlueprint`, because a provider may only ever declare content, never create it. One schema (`src/marvin/schemas/platform/blueprints.py`) serves both the core catalog and what an integration brings.

Each blueprint has a `kind`, a `slug`, `name`, one-line `description`, a `category`, a `source` (`core` or a provider slug), optional `requires`, optional `parameters`, and a `payload` in the shape the creating code expects. A payload that carries `group_id` or `id` is rejected: scoping is the core's job.

| `kind` | Creates | Payload |
| --- | --- | --- |
| `collection` | A collection (smart collections are materialised at once) | A collection body |
| `entry_type` | An entry type | An entry-type body. `"capabilities_json": {"offer_in_new": false}` keeps a type nobody makes by hand out of the New menu and Quick create (it stays listed; set only when the type is created, an update never changes it) |
| `entry_fields` | Fields on an existing entry type, and optionally its form settings | `{"entry_type": "<slug>", "fields": [<schema field>, …], "submission": {"destination"?, "kind"?}?}`; only fields whose `key` is missing are appended, existing fields are never changed. `submission` is the one hook on a form's settings: `destination` (`audience` \| `entries`) and/or `kind` (`message` \| `signup`), nothing else, set on a submittable type only for the keys it doesn't already store (a choice someone made stays; choosing a destination sets *Show in content lists* as the editor does). A blueprint that only sets these declares `fields: []`. A Marvin before this hook ignores the block (and rejects an empty `fields` list, so a provider that wants to stay valid there also declares a field) |
| `scheduled_task` | A scheduled task, switched off | A scheduled-task body |
| `event_subscription` | An event → integration action wiring, switched off | `event_type`, `action`, `args` |
| `incoming_webhook` | An [incoming webhook](incoming-webhooks.md), switched off and without a token | `name`, `description`, `signature_scheme`, `signature_header`, `signing_secret_ref`, `signature_url`, `signature_config`; a `token` is refused |
| `workflow` | A [workflow](workflows.md), switched off, authored by whoever applies it | `{"name": …, "definition": {trigger, conditions, actions}}`; the definition must pass structural validation |
| `playbook` | A [Playbook](playbooks.md#from-an-integration), as a **draft** with its reference files (integrations only) | `{"skill_md": "<SKILL.md text>", "files": {"references/x.md": "<text>"}}`. Text files only (`.md .txt .json .csv .yaml`), no scripts, relative paths; `SKILL.md` at most 64 KB, at most 20 files of 64 KB, 256 KB in all. The SKILL.md `name` is the slug and starts with the provider's slug (underscores as hyphens). Never required, no parameters. Marvin checks all of it again; one that fails is skipped with a warning and the provider's other content still loads |
| `wizard` | Nothing: a **guided setup** kept in a [package](workflows.md)'s manifest (packages only), listed under *Guided setups* | `{"title": …, "steps": [...]}`: step kinds `option`, `choose` (also `picture`, `subtitle`, `create.upload`, `multiple` with `assets`; `selection` shows a multi-select's picks), `form`, `upload`, `list`, `gallery`, `run`, `review`; `button` puts a button on an entry type's pages that opens the setup on that entry (`{entry_type, label, key, step?, also?}`); `when` shows a step only on a choice; `${name}` reads a choice made earlier. See [Guided setups](guided-setups.md) and `services/blueprints/wizards.py` |
| `view` | Nothing: a **view** of an entry kept in a package's manifest (packages only); an entry of its type gets a button that opens it, and with `"sidebar": true` the sidebar a link to it; with `picker` its page lists the entries as cards | `{"kind": "timeline", "title": …, "entry_type": …, "unit": …, "spine": {…}, "lanes": [...], "actions": [...]}`: the one kind, `timeline`, lays an entry's children out as time (a story's beats, with lines and sounds in lanes; with `unit` in minutes, hours or days, an agenda or a plan). See `services/blueprints/views.py` |

**Required vs suggested.** `required` defaults to `False` and is meant to be set sparingly: `True` only when the source cannot work without it, such as an entry type an action reads or writes. Everything else is a suggestion. Core blueprints are never required.

**Parameters.** Core names nobody's content. Where a blueprint needs a slug from the workspace, it asks for it: a `BlueprintParameter` has a `key`, a `label`, a `kind`, `required`, `default` and `help`. `entry_type`, `collection` and `integration` render as dropdowns of what the workspace has and are validated against it; `text` and `number` are free input. An `integration` parameter lists the workspace's connections of the declaring provider and defaults to the connection whose card you are on (through the API: the workspace's only connection of that provider). `{{key}}` placeholders are substituted through slug, name, description and payload, so `all-{{entry_type}}` applies once per type. A lone `{{key}}` yields the value itself rather than a string.

**Core catalog** (`src/marvin/services/blueprints/catalog.py`): smart collections.

| Slug | Category | Rule it demonstrates |
| --- | --- | --- |
| `recently-published` | Editorial | `statuses: [published]`, `published_within_days: 30` |
| `new-this-week` | Editorial | `created_within_days: 7` |
| `all-{{entry_type}}` | Editorial | `entry_types` (asks which type) |
| `published-{{entry_type}}` | Editorial | `entry_types` + `statuses` (asks which type) |
| `all-images` | Media | `target_type: asset`, `asset_types: [image]` |
| `vector-artwork` | Media | `target_type: asset`, `mime_types: [image/svg+xml]` |

**Social is not a blueprint set.** Core used to offer one (the entry types `social-auto-reply` and `social-reply-log`, the smart collections `social-auto-reply-rules` and `social-replies`, the scheduled task `social-engagement`), applied from a card on Settings → Integrations. It is retired: Marvin makes the rule type and the engine's task itself when a social network is connected ([Social → What Marvin makes](social.md#what-marvin-makes)), the reply log is the inbox item, and the two collections are not recreated. In a workspace that applied the set nothing is deleted; the migration removes the two collections only when they are still as the blueprint made them and empty, else just takes them off the sidebar.

Status buckets are deliberately absent: every workspace already gets the locked inbox/drafts/needs-review/approved/published/archive collections.

## Where

- **Integrations page** (`/workspace/settings/integrations`): each connected integration's card lists that provider's blueprints under **Content**, split into **Needed to work** and **Optional — set these up if you want them**. This is the only admin UI for blueprints.
- **API**: `/api/groups/blueprints`, which also serves the core catalog.

## How to use

### Apply from an integration card

1. Connect the integration. Its card opens the **Content** section automatically if anything needed is missing.
2. Fill a row's parameters if it has any. They are dropdowns of your entry types, collections or connections, prefilled with the blueprint's defaults.
3. Click **Add** on a row, or **Add N missing items** to apply everything needed that is missing (parameters are read from each row).
4. Read the result. A toast reports what was added and, for anything skipped, why; "already exists — left as it is" is information, not an error.
5. Review what arrived switched off (scheduled tasks, event subscriptions, incoming webhooks, workflows) and turn it on. An incoming webhook also needs a token, created on its page.

### Update an applied workflow or Playbook

When an integration ships a newer version of a workflow or Playbook you applied, its row shows ↑ and an **Update** button. Update replaces a workflow's definition with the integration's current one and keeps whether it is switched on. For a Playbook it replaces the text and the reference files, keeps its id and status and leaves the old version in its history. Everything else stays as you have it.

A Playbook is an entry with files, and writing one commits, so adding a Playbook is the one exception to "apply never commits": it is applied last when several are added together.

Marvin remembers the version it installed, so it can tell a new version from your own edits:

| Row says | Meaning | Update |
|---|---|---|
| ✓ | Same as the integration's version. | none |
| ↑ Update available | Untouched since install; the integration has a newer version. | Replaces the steps. |
| Edited in this workspace | You changed it and the integration has nothing newer. | none offered |
| Edited here · update available | You changed it and there is a newer version. | Asks first: your changes are replaced. |
| Differs from the integration's version | Installed before Marvin tracked edits, so an old version can't be told from an edit. | Asks first. It records the version, so later rows read as above. |

An edited workflow also carries an **Edited** tag on the Workflows page. The API refuses an update that would replace your changes unless `replace_edits=true` is sent (the result has `needs_confirmation`).

### Apply semantics

- **Create what is missing, never overwrite what exists.** The upsert is keyed on the resolved slug within the workspace. A customised copy survives a repeat apply and a provider upgrade. For `entry_fields`, "applied" means every declared field is already on the type and every declared submission setting is stored.
- **Dependency order.** Bulk apply sorts entry types, then added fields, collections, scheduled tasks, incoming webhooks and workflows, and flushes after each, so a collection that `requires: entry_type:<slug>` sees the type created moments earlier and a workflow finds the webhook it triggers on.
- **Requirements gate.** An unmet `requires` entry makes the blueprint `available: false`; applying it returns `created: false` with `detail: "needs entry_type:<slug>"` rather than half-creating.
- **Event subscriptions need a connection.** They reference an integration instance: `POST /{slug}/apply` takes `integration_id`, otherwise the workspace's only connection of that provider is used; with two or more, apply refuses rather than guess. They have no database slug, so the upsert dedupes on (integration, event type, action).
- **Created switched off.** Anything that acts once enabled (`scheduled_task`, `event_subscription`, `incoming_webhook`, `workflow`) is created with `enabled: false`. Turning it on is a deliberate second act.
- **Collections are materialised on create**, so a smart collection does not sit empty until the next entry event. Scheduled tasks go through the repository so `next_run_at` is computed.

## API

Workspace-scoped, under `/api/groups/blueprints`. Apply and update need workspace ADMIN or OWNER.

| Method | Path | Notes |
| --- | --- | --- |
| GET | `` | Catalog annotated per workspace: `applied`, `outdated`, `state` (`current`, `update`, `edited`, `edited_update`, `differs`), `edited`, `available`, `missing_requirements`, and for a Playbook `installed_id`, `installed_status` and `conflict` (why Add is refused: the name is taken). Filters `?kind=`, `?category=`, `?source=core|<provider>`, `?integration_id=` |
| GET | `/categories` | Category names in catalog order, core first then each provider |
| GET | `/{slug}?source=` | One blueprint with its payload |
| POST | `/{slug}/apply?source=&integration_id=` | Body: the `params` dict, e.g. `{"entry_type": "post"}`. Returns `BlueprintApplyResult` |
| POST | `/apply?source=` | Body: `slugs` list and `params` keyed by slug. Returns a list of results, applied in dependency order |
| POST | `/{slug}/update?source=&replace_edits=&integration_id=` | Workflows and Playbooks: replace the applied workflow's definition (or the Playbook's text and files) with the declared one. One changed in the workspace is refused (`needs_confirmation`) unless `replace_edits=true`. `integration_id` re-attaches a Playbook to a connection added again. Returns `BlueprintApplyResult` with `updated` |

A parameterised blueprint is judged `applied` by its default parameter values; one with a required parameter that has no default reads as not applied. `outdated` is true when an Update is worth offering: state `update`, `edited_update` or `differs`. Slugs are unique per source; pass `source` to disambiguate.

```json
{"slug": "recently-published", "kind": "collection", "created": true, "updated": false, "detail": "", "name": "Recently published"}
```

Full reference: [API reference](../api/index.md).

## Settings

None.

## Since

Blueprints and the core catalog: 1.0.0-rc.84 to rc.97. `entry_fields`, `incoming_webhook` and `workflow` kinds, and admin-only apply: rc.111. Parameters from dropdowns: rc.116. An `integration` parameter defaults to the workspace's own connection: rc.117. Updating an applied workflow: rc.118.

## Related

- [Integrations](integrations.md) — where provider blueprints are offered and applied.
- [Collections](collections.md) — the smart rules the core catalog demonstrates.
- SDK contract: [marvin-integration-sdk](https://github.com/InnerOpen/marvin-integration-sdk) `ContentBlueprint`.
- [Glossary](../glossary.md)

## Pick lists for fields that name another entry

A text field with `"ref": "voice"` (an entry type's slug) is shown as a pick list of that type's entries, saving the chosen one's slug. Add `"ref_via": {"entry_type": "cast-member", "field": "voice", "match": {"story": "story"}}` to put first the entries that other entries name: here, the voices of the characters cast in the story this entry belongs to (`match` pairs the other type's field with this entry's own). They are listed under "Cast in this story", and every other entry stays below under "Other voices", so nothing is out of reach. With nobody cast yet, or no value to match on, the list is the whole type as before. Screenplay Studio uses it on the voice of a take and of a speech line.

## A timeline view can read a file's facts from its Recording

A timeline `view` can name `spine.clip.recording` and, on a lane, `recording`: a field on the entry holding the slug of its Recording (the Media package's `recording` entry, one per audio or video file, with what the file says about itself). The Timeline then reads the file's facts from the Recording first: a clip's length, whether it has a sound, its poster and its text; a line's or a sound's length and waveform. Whatever the Recording does not have yet is read from the entry's own fields, as before. A Recording counts only when its file is the one the entry holds now (the clip, or a lane's `audio`, which a lane with `recording` must name), so a pointer left from an earlier take is ignored. A workspace without Recordings, or a view without the key, draws exactly as it did. Word timings still come from the take's file, as the render's captions and cues do. For Screenplay Studio's story timeline that is `"recording": "recording"` in `spine.clip` and on the lines lane.

## A view can put a link to itself in the sidebar

A `view` can say `"sidebar": true`, or `"sidebar": {"label": …, "icon": …}` (both optional: the label defaults to the view's title, the icon is a short emoji, 🎞 when none is named), to get a link in the sidebar that opens the view's page, which lists the entries to open in it. The link sits at the top of the package's own group in the sidebar (the one its collections are listed in), or right under Guided setups when the package has no group there (fewer than two of its collections are shown). A view without the key gets no link, as before. Either way, an entry of the view's type keeps its button that opens it in the view. For Screenplay Studio's story timeline that is `"sidebar": true` on the `story-timeline` view.

## A view's page can show its entries as cards

A view's page without an entry lists the entries to open in it. With a `picker` key the list becomes a grid of cards (three or four to a row on a wide screen, one on a phone), each a link that opens the entry in the view. All of its keys are optional:

- `picture`: an asset field on the entry, shown as the card's picture. Without one, the card shows the first picture of its strip, else the first letters of its title on the theme's accent colour.
- `subtitle`: the line under the title. It is a field key, or a list of up to three, joined with a dot. Each is a key or `{"field": …, "before": …}`, where `before` is up to 12 characters put before the value (`"Ep "`). A field with a `ref` shows the title of the entry it names, not its slug. Empty fields are left out.
- `badges`: up to three field keys shown as chips beside the title, such as a story's status.
- `strip`: `true` or `{"limit": n}` (1 to 24, default 16). It adds a thin filmstrip under the picture: the pictures of the view's spine items (a story's beat stills, `spine.picture`, which the strip needs), evenly sampled when there are more. An item with no picture yet is a hatched blank, and each tile's tooltip says which item it is ("Beat 07"). The card's counts then say how many items there are ("24 beats").
- `play`: an asset field on the entry holding a video, such as a story's latest render. A card that has one gets a Play button over its picture. It is a separate stop for the keyboard, and it plays the video in the card, loading nothing until it is pressed. A second press stops it. The video's length (its asset's `seconds`) is added to the counts ("24 beats · 1:27").

The page reads the spine items of all the cards in one query, 500 rows at a time and four pages at most. A story whose items were cut off by that limit shows no count. The pictures and the video come with the entries themselves, so no card fetches anything of its own. If one of those reads fails, that part of the card is left off. A view without `picker` keeps its plain list.

For Screenplay Studio's story timeline:

```json
"picker": {
  "picture": "cover",
  "subtitle": ["series", {"field": "episode", "before": "Ep "}],
  "badges": ["status"],
  "strip": {"limit": 16},
  "play": "video"
}
```

The render job keeps the story's newest whole-story render in the story's `video` field and trashes the one before, and a draft of a few beats never touches it. So `play` reads that field, not the render jobs.

## A timeline view can count in minutes, hours or days

A timeline `view` counts in seconds unless it says otherwise. With `"unit"` set to `"minutes"`, `"hours"` or `"days"` (or `"seconds"`, the same as leaving it out), every length and offset the view reads is in that unit: the spine's `seconds.hold` and its `defaults`, a lane's `seconds`, a `placed` lane's `at`, a card's `seconds`. The keys keep their names, so nothing about an existing view changes; in a view in minutes, a `hold` of 45 is three quarters of an hour.

The page then writes every time in the unit:

- The ruler steps in round numbers of it: 5, 10, 15 or 30 minutes and whole hours; quarter hours, hours and 3, 6, 12 or 24 hours; 1, 2, 7, 14 or 28 days.
- A position is the time from the start ("0 min", "1 h 30 min", "1 d 4 h"), or in days the day it falls on, the first being Day 1 ("Day 3").
- A length is at most two parts: "45 min", "1 h 30 min", "3 h", "1 d 4 h", "3 days", "2 weeks 3 days" (weeks once a length reaches one).
- The header, the card corners, the tooltips and the playhead clock use the same words. The clock takes what you type in the unit: "1 h 30 min", "1:30" or "90" in minutes, "Day 3" or "2 weeks" in days. The `,` and `.` keys move the playhead a minute (Shift: a quarter hour), a quarter hour (Shift: an hour) or a day (Shift: a week).

Sound runs in seconds, so a view in another unit has none. The view is refused if it names a lane's `audio`, `bed`, `cover`, `estimate_from`, `words`, `nudge`, `recording`, `volume`, `loop`, `waveform` or `placed.volume`, or `spine.clip`, `spine.word_cues`, `spine.starts_during`, a `picture_lead` (on the items or in `seconds.entry`) or `picker.play`; the message names the key. Its page has no Play button, mute buttons or waveforms, Space plays nothing, and the render's quiet stretches, overlap brackets and dragging of placed pieces are left out. Two more things differ from seconds, because the render's speech timing means nothing in a plan:

- The built-in defaults are a `hold` of 1 and no `lead`, `gap` or `tail` (seconds keeps 4, 0.3, 0.25 and 0.35). A view's own `defaults` still win.
- A piece of an `in` lane with no length of its own is drawn across its whole item (a post on its day, a panelist for the whole session), not as a sliver at its start. A short piece is drawn wide enough to read its name, and pieces that would overlap stack on rows, those that start together in their own order.

An older Marvin ignores `unit` and draws such a view in seconds.

The example package `docs/examples/timeline-demos.marvin-package.json` (Timeline Demos) shows both: an **Event agenda** in minutes (sessions of a `demo-event` grouped by the part of the day, with who is on stage and room and AV cues placed in them) and a **Content plan** in days (a `demo-plan`, one `demo-day` card per day, with its posts and their channel). Install it like any package, then make sample entries with `scripts/seed_timeline_demos.py`:

```sh
curl -X POST "$MARVIN_API_URL/api/groups/packages/install" -H "Authorization: Bearer $MARVIN_TOKEN" \
  -H "Content-Type: application/json" --data-binary @docs/examples/timeline-demos.marvin-package.json
MARVIN_API_URL=… MARVIN_TOKEN=… python scripts/seed_timeline_demos.py
```

The script looks each entry up by its slug and makes only the missing ones, so it can run again.

## Cues on words in a timeline view

A timeline `view` can declare `spine.word_cues` (`{field, lane, sounds?}`): a JSON list on each spine item (a Screenplay Studio beat's `cues`) of cues that sit between two words of a line. The item's page edits the list as rows instead of raw JSON, and the Timeline draws each cue as a flag on its line.

Each row picks a line and the gap between two of its words (click a word to put the cue after it). Then it says what happens there:

- **Sound**: one of the story's sounds, at its own level or the row's. It plays at the end of the word before the gap.
- **Camera move**: on top of the beat's own move.
  - *punch*: a quick zoom in.
  - *shake*.
  - *nudge*: a drift toward a point.
  - *whip pan*: a fast sweep left or right and back, by a share of the frame (0.05 to 0.5, default 0.35). It zooms in by 1 + 2 × that share to make room, so the default peaks at 1.7×.
  - *sway*: a handheld sway that dies away (0.8% of the frame over 1.5 s unless set).
- **Picture**: an overlay beat whose picture comes in at the start of the word after the gap.
- **Look**: laid over the shot, never changing its length.
  - *flash*: white, black, orange, red, gold or blue; 0.9 bright over 0.25 s unless set.
  - *burn*: an orange flash, 0.35 s.
  - *dip*: to black or white and back, 0.8 s.
  - *freeze*: the camera's move holds still, 0.6 s.
  - *tint*: sepia, mono, cold or warm, at full strength. It lasts to the end of the shot unless given seconds.
  - *blur*: 0.6 strong over 0.8 s.
  - *vignette*: 0.7 dark over 1 s.
  - *glitch*: 0.2 s.
- **Mix**: the voice is never touched.
  - *dead air*: ambience, music and effects go silent, 1.5 s.
  - *duck*: music and ambience dip to 0.3, 1.5 s.
- **Emphasis**: the word after the gap is shown bigger in the captions, 1.3× unless set (1 to 2).

Every number a kind takes shows the render's default as a placeholder; leave it empty to use that default. Numbers are held to the render's ranges. A cue's **nudge** (set by dragging its sound on the Timeline) moves its sound, camera move, look, mix and emphasis together, but not its picture.

On the Timeline, a look, a change to the mix, emphasis and the newer camera moves each get a small labelled chip beside the cue's flag, such as *flash*, *whip pan* or *dead air 1.5 s*, with the details in its tooltip. Dead air and a duck are also drawn over every bed lane (ambience, music) for as long as they last: hatched where the lane goes silent, dimmed where it dips. A view without bed lanes skips this. None of these cues changes the Timeline's length, its picture cuts or the playhead.

A kind Marvin does not know, a colour a kind does not take (the render leaves such a cue out), and any key a row carries that Marvin does not read are all kept as written when the row is saved. The Timeline shows an unknown kind by its own name with a "?". The kinds, their numbers and their defaults are in one file, `frontend/src/lib/cueKinds.ts`, matching the render's own (Screenplay Studio v218 and v219). Each kind has an `enabled` switch there, so taking one out of the editor is a one-line change.

### When a line moves to another beat

A cue row is stored on a beat but names a line. If the line is moved to another beat, the row stays where it was. The render plays the cue in the beat that holds its line now, and Marvin does the same:

- **On the beat that stores it**, the row says *This cue is for a line that is now in beat N*. **Move to beat N** moves it there, writing both beats' whole records and checking each one comes back as sent. **Delete** removes it from this beat when you save the page. If the line was deleted, the row says *a line that no longer exists*, and the render leaves the cue out.
- **On the beat that holds the line**, the rows other beats store for its lines are listed under the cue rows, read only, each saying which beat stores it.
- **On the Timeline**, the cue is drawn on its line in the beat it plays in. Its flag is dimmed and carries a *from beat M* chip, and dragging its sound still writes to the beat that stores it.
