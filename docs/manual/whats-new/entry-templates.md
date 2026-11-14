# Entry templates

An entry type can keep **templates**: named presets for the entries you make from pictures. Pick pictures and a template, look at the preview, and Marvin makes one Inbox draft per picture, titled after the picture, with the template's field values, tags and collections, and the picture set on the entry. The same template fills in entries you already have. The REST API, workflows and the assistants all use one service for this, so none of them makes up its own titles.

## What it does

**A template lives on its entry type.** Open the type in **Workspace > Entry types**: the **Templates** section lists them, and an admin adds, edits and deletes them there. A package can bring templates with the type it installs. A template holds:

- `name` and `slug`, and a `description` that says what the template is for.
- `title`: a pattern, `{asset.name}` by default. The settings show a live preview of the title from one of your pictures.
- `summary` and `entryDescription`: the text for the entry's summary and description.
- `fields`: values for the type's fields, by field key.
- `tags` and `collections`: tags to add (a missing tag is made) and the slugs of hand-picked collections to add each entry to.
- `status`: where a new entry starts, `inbox` by default. It can also be `draft` or `needs_review`; a template never approves or publishes.
- `assetField` and `assetRole`: the type's asset field the picture goes in (e.g. `image`), and the role it is attached with (`featured` by default).

**Variables.** Any text in a template can use `{asset.name}` (the picture's name in the library), `{asset.filename}` (the file name it was uploaded with), `{n}` (the entry's number in this batch, from 1) and `{date}` (today, `YYYY-MM-DD`). Saving a template is refused when it uses any other `{…}`, names a field the type does not have, gives a field a value of the wrong kind, or points `assetField` at a field that is not an asset field. The same check runs when the type's fields change, so a field a template fills cannot be removed until the template stops using it.

**Making entries from pictures.** `POST /api/platform/entries/from-template` takes `entryType`, `template`, `assets` (ids or slugs, at most 200) and `preview` (true by default):

- **The preview changes nothing.** It answers one row per picture: the title, the values that would be set, the tags and collections, and the picture. `todo` counts the rows that would make or fill an entry.
- **Create** (`preview: false`) makes each entry in the template's status. The picture is set both ways an entry holds its picture: the asset field holds its id, and it is attached with the template's role at position 0. Slugs follow the titles (`-2`, `-3` on a clash).
- **A picture that already has an entry of this type** fills that entry instead of making a second one, so running a batch again never makes duplicates.
- **Nothing is made while any row has a problem**, for example a required field that the template does not fill. The preview names the problem.

**Filling entries you already have.** `POST /api/platform/entries/apply-template` takes `entryType`, `template`, `entries` (ids or slugs, at most 200), `preview` (true by default) and `replace`:

- **Only empty values are filled** (missing, empty text or an empty list), unless `replace: true`. With `replace`, the title also follows the pattern again.
- **Tags and collections are only added**, and an entry's status is never changed.
- **The picture.** An entry's picture is the one in its asset field, else the one attached with the template's role, else its first attached one. It is put in the asset field when that is empty and attached when it is not. With no picture, the values that need one are left out and the row says so.
- **Left alone:** approved, published and archived entries, and those in the Trash. Change those one at a time.

**Who.** Previews need AUTHOR. Making entries needs what making one entry needs: an AUTHOR makes them, in the template's status. Filling an entry needs what editing it needs: an EDITOR fills any entry, an AUTHOR only their own drafts. Editing templates is for workspace admins, as is the rest of the type's settings.

**Fast, and one event.** Everything is read in a fixed number of queries and written set-based, 100 entries per transaction: 100 entries take well under a second. The entries send no `entry_created` or `entry_updated` of their own, so workflows that start on those events do not run for them. One **Entries Made from a Template** event (`entry_template_applied`) says how many were made and filled, with their ids. Smart-collection membership (Inbox and the rest) is worked out in bulk instead.

**In a workflow.** The steps **Create entries from a template** (`create_entries_from_template`) and **Apply a template** (`apply_template`) work like the REST calls:

- `mode: preview`, the default, answers the rows and changes nothing. `mode: create` or `mode: apply` does the work, and needs `confirm_total`, the preview step's `todo` (`${steps.<id>.output.todo}`). When there is no longer that much to do, the step fails and changes nothing.
- `assets` and `entries` take a list or a template, such as a collect step's ids.
- Making entries needs an AUTHOR author; filling needs an EDITOR.
- The editor's check warns when a step that writes has no approval before it under a trigger that fires on its own, and when `replace` overwrites values without asking.

**The assistants.**

- `list_assets` now gives each picture's `name`, `slug` and `filename`, so an assistant titles an entry after its picture instead of numbering them.
- `list_templates` lists a workspace's templates, and `get_entry_type` shows a type's templates.
- `create_draft` takes an optional `template`, and with no title it names the entry after its picture.
- The assistants are told never to invent descriptions or summaries you did not give.
- A change that waits for your approval is reported as "proposed, waiting for your approval", never as "Updated".
- `create_draft` and `update_draft` results carry a plain `message` saying which happened.
- An unknown field such as `image_url` is answered with the field the assistant most likely meant (`image`).

## Storage

Templates are kept on the entry type, in a JSON column (`entry_types.templates_json`, migration `4b537ff0c66a`), next to the type's schema, rendering and recipe. That way they travel with the type: a package exports and installs them with it, and a package update adds the templates a type lacks, by slug, without changing the ones the workspace edited.

## Picture presets

A **picture preset** treats every picture the same way: the same crop, the same size, the same brightness and colour, the same format. Give a template a preset, and each entry it makes shows the treated picture. The original stays in the library, unchanged, as the picture the treated one was made from (it is listed under it as a version).

**Where they live.** A preset is kept on the entry type, beside its templates (`entry_types.picture_presets_json`, migration `7c2e5a91d4f3`), and an admin edits it in the type's settings, in the **Picture presets** section. Every template of the type can use it, so one preset serves an Ornament template and a Vase template alike. A package brings presets with its type, and a package update adds the presets a type lacks, by slug, without changing the ones the workspace edited. A template can only name a preset its own type has, and a preset a template uses cannot be removed until the template stops using it.

**What a preset holds.** A `name`, a `slug`, an optional `description`, and `steps`, in order (at most 12). Each step takes what a workflow's media step takes for that op:

- `crop`: `aspect` (`1:1`, `4:5`, `16:9`…) and `focus`: `center` (the default), `subject` (a vision model finds it; one AI call per picture), or a fixed point `x,y` from 0 to 1 (`0.5,0.3` keeps the upper middle).
- `resize`: `width` and/or `height` (never larger than the picture), `fit` `inside` (the default) or `cover`.
- `grade`: a named grade (`warm`, `cool`, `muted`, `rustic-warm` or one of the workspace's own) and/or `brightness`, `contrast`, `saturation` (1 leaves it as it is, 1.1 is 10% more, 0.9 10% less), `warmth` (above 1 warmer, below 1 cooler) and `vignette` (0 to 1: how much the corners darken).
- `convert`: `format` (`jpeg`, `webp` or `png`) and `quality`.

All the steps run on the picture in one pass and it is saved once, at the end, so nothing is lost between steps.

**One new picture per original, made once.** The treated picture is named `<original>--preset-<hash>`, the hash over the steps and the original's file. Running a preset again on the same picture reuses what it made; editing the preset's steps makes new pictures. A treated picture asked for again is traced back to its original first, so a picture is never treated twice. Treated pictures send no `asset_uploaded`, so a workflow that starts when a picture is added does not run for them.

**In a template.** `picturePreset` names the preset and `treatedRole` (`featured` by default) the role the treated picture is attached with; it also goes in the template's asset field, and the original is not attached. When the treated picture was made before, the entry gets it straight away. When it was not, the entry gets the original for now, the treatment runs in the background and the treated picture then takes the original's place, but only where the entry still holds the original: a picture someone changed in the meantime is left as it is. The answer's `treatmentJob` names that background job. Running the template again on the original fills the entry it made, never a second one.

**Treating pictures without making entries.** `POST /api/platform/assets/apply-preset` takes `entryType`, `preset` (or `template`, to use its preset), and `assets` (pictures) or `entries` (each entry's picture is treated and the treated one takes its place), at most 200, and `preview` (true by default). The preview changes nothing: one row per picture, `create` or `reuse` (made before) or `skip` with the reason. With `preview: false` the work starts in the background and the answer carries the `job`; `GET /api/platform/assets/apply-preset/jobs/{id}` says how it goes and, for each original, its treated picture. A workspace runs one treatment at a time; others wait their turn. A job lives in memory, so after a restart run it again (what was made is reused). An AUTHOR treats the pictures they uploaded and their own draft entries; an EDITOR treats any. Approved, published and archived entries are left alone.

**How long.** On the development machine, 50 phone photos (4032×3024 JPEGs, about 7 MB each) were cropped, graded with all five settings, resized and saved as WebP in 27 seconds, about half a second each. The request that started it answered in 25 ms, and the app went on answering meanwhile (`GET /api/self`: median 9 ms, slowest 42 ms).

**On upload.** The **Upload Asset** page has **Make an entry for each**: `none` (the default, which changes nothing) or one of the workspace's templates. With a template chosen, once the files are up Marvin:

1. names each picture: the AI looks at it and gives it a short name ("Red cardinal ornament"; one AI call each, and it can be switched off). Without one, the picture keeps a tidied file name ("IMG 4491") and its entry is tagged **Needs a name**;
2. treats the pictures with the template's preset, when it has one, and waits for that (the batch's own "apply my last adjustments" is switched off, so nothing is treated twice);
3. shows the entries the template would make, with their titles and the treated pictures, and makes them as Inbox drafts when you say so.

A guided setup's gallery can do the same for its upload button: `upload.template` names one of the type's templates, and the uploaded picture's entry is made with it, preset and all.

**Pictures and entries you already have.** The Assets and Entries pages have no way to select several items yet, so for those use a guided setup: a `choose` step with `multiple: true` (multi-select cards; see [Guided setups](guided-setups.md)) for the picks, then a run step that passes them on (`inputs: {pictures: "${pictures}"}`, comma-separated ids) to a workflow whose `apply_picture_preset` step takes `entries: ${inputs.pictures}` or `assets: ${inputs.pictures}` (preview, then apply), or whose `apply_template` step does. Applying a template that has a preset to existing entries treats their pictures and puts the treated ones in place in the same way. `POST /api/platform/assets/apply-preset` with `entries` does it too.

**In a workflow.** The step **Treat pictures with a preset** (`apply_picture_preset`) works like the REST call: `mode: preview`, then `mode: apply` with `confirm_total` (the preview's `todo`). It runs in the run itself (a run is already in the background) and outputs `treated` (original → treated id) and `ids`. The media step's `grade` takes the free settings and its `crop` the fixed focus point too.

**The assistants.** `apply_preset` previews a preset on pictures and, with `confirm`, starts the treatment. `list_templates` says which preset a template uses.
