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
