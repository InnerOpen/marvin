# Trash

Deleting an entry, an asset or a resource now moves it to the **Trash**, where it can be restored until the Trash is emptied. A workflow can move things there, and so can an agent; only a person can empty the Trash or delete anything forever.

## What it does

**Delete moves to the Trash.** On the entry page, **Move to Trash** (it replaced **Delete**) sets the entry's status to `trashed`. There is no confirmation: the entries list you land on offers **Undo**. A trashed entry:

- is off the site and the publishing API (a published entry is unpublished on the way in, so `entry_unpublished` fires and the site rebuilds);
- is out of every list, search and count: the entries list, collections (manual ones keep its membership, so a restore puts it back in place), smart collections, `find_entries`, workflow targets, search and the RAG index, tag counts, the dashboard, `workspace_overview`;
- is listed only in the **Trash** system collection, and still opens by its id (the entry page shows "This entry is in the Trash" and is read-only until restored);
- keeps where it came from in `metadata_json.trash` (`previous_status`, `trashed_at`, `trashed_by`), removed again on restore;
- loses a pending Scheduled Publish (`publish_at` is cleared), so neither the trashed entry nor its restore goes live on schedule.

**Restore** puts the entry back in the status it had, except that a **published** entry comes back as a **draft**: restoring never puts anything on the site by itself. Publish it again when it's ready.

**Delete forever** removes one trashed entry for good. **Empty trash** removes everything in the Trash — entries, assets and resources — after one confirmation. Both delete each entry the normal way, so `entry_deleted` fires per entry and its links to collections, tags, assets and resources go with it.

**Auto-empty.** Entries, assets and resources that have been in the Trash longer than the workspace allows are deleted forever by an hourly job (on the scheduler leader only; running it twice deletes nothing twice). The limit is a platform default — **30 days** unless a super admin changes it — that a workspace can override with **Never**, 7, 30 or 90 days. **Never** keeps entries until someone empties the Trash. An entry with no recorded `trashed_at` (one trashed before the record existed, e.g. from a restored backup) is never auto-deleted; emptying the Trash removes it.

**Assets and resources.** On an asset or resource page, and in the asset and resource lists, **Move to Trash** replaced **Delete** (no confirmation; restore it from the Trash). A trashed asset or resource:

- is out of the asset library, the resource list, the entry editor's pickers and an entry's attachments, collection members and counts, tag counts, the dashboard, and the AI's tools (`list_assets`, `list_resources`, `find_entries`, `get_entry`, `search_content`, `workspace_overview`, the RAG index);
- is out of the publishing API: an entry's `assets[]` / `resources[]` (and a list item's `assetSlugs` / `resourceSlugs` and `featuredAsset`), `GET …/assets`, `GET …/resources`, a read by slug (404), a resource's entries (404), and the site settings' `logo`, `favicon` and `seo.image` when they name it (they come back as `null`);
- keeps its links to entries and collections, so a restore puts it back in place. Saving an entry keeps the links to its trashed attachments too, though the editor doesn't show them;
- still opens by its id: the page says "This asset is in the Trash" (or resource) with **Restore** and **Delete forever**, and is read-only until restored. The API returns it with `trashedAt` and `trashedBy`;
- **keeps its file in storage.** Sites load files straight from the bucket (for example `https://assets.iwobble.com/…`), so the file is only removed when the asset is deleted forever: by **Delete forever**, **Empty trash** or the auto-empty. That deletion takes the same path as before, so `asset_deleted` fires and the file, and any copy at an old key, goes from storage.

Trashing or restoring an asset or resource that a site shows (attached to a published entry, in a collection visible to sites, or named as the site logo or favicon) queues a site rebuild; one only a draft uses doesn't. When Marvin can't tell, it queues one.

**One Trash, three tabs.** The Trash has **Entries**, **Assets** and **Resources** tabs, each with per-item **Restore** and **Delete forever** and **Restore selected**. **Empty trash** (ADMIN/OWNER) empties all three after one confirmation: "Permanently delete N items? Files are removed from storage. This can't be undone." Restoring or deleting an asset or resource needs EDITOR, as its page does.

**Archive or Trash?** Archive retires an entry you want to keep (it stays in the **Archive** collection indefinitely and is never deleted). Trash is for entries you want gone, with a safety net.

### Events

| Event | When |
| --- | --- |
| `entry_trashed` | an entry is moved to the Trash (after `entry_updated`, and `entry_unpublished` when it was published) |
| `entry_restored` | an entry leaves the Trash (also: an archived entry is restored) |
| `entry_deleted` | an entry is deleted forever (Delete forever, Empty trash, auto-empty) |
| `asset_trashed` / `resource_trashed` | an asset or resource is moved to the Trash |
| `asset_restored` / `resource_restored` | an asset or resource leaves the Trash |
| `asset_deleted` / `resource_deleted` | an asset (its file too) or resource is deleted forever |

## Where

- **Trash** collection (`/workspace/collections/<id>`, listed with the system collections, 🗑️): **Entries**, **Assets** and **Resources** tabs (`#assets` / `#resources` opens one), each with per-item **Restore** and **Delete forever** and **Restore selected**; **Empty trash** (workspace ADMIN/OWNER) for all three, and how long the Trash keeps things.
- Entry, asset and resource pages: **Move to Trash**; on a trashed one, the banner with **Restore** and **Delete forever**. The asset and resource lists have **Move to Trash** per row.
- **Settings → General → Trash**: the workspace's auto-empty choice (ADMIN/OWNER).
- **Admin → Site Settings → Trash**: the platform default (super admin).

## How to use

**Clear out a batch with a workflow.** Make a workflow with **Run on a query of entries** (for example entry type `signup`, status `inbox`) and one **Entry action** step with **Move to Trash** (`op: "trash"`). Run it, check the Trash, then **Empty trash**. Entries already in the Trash are left out of the query, so running it again does nothing to them.

**Restore with a workflow.** The **Restore** op on a trashed entry returns it to the status it had (a published one as a draft); target trashed entries with status **in the Trash** (`status: "trashed"`).

**Trash an asset or resource with a workflow.** An **Entry action** step with **Move to Trash** or **Restore** and **Acts on: Asset** or **Resource** (`entity_type: "asset"` / `"resource"`) targets the asset or resource by slug (`entity_slug`) or id (`entity_id`, by default the triggering `$event.asset_id` / `$event.resource_id`). One already where the op would put it is skipped.

**Ask an agent.** "Delete the test signups" makes an agent call `trash_entries`: the entries go to the Trash and the answer links to it. "Delete the old banner image" works the same way with the tool's `assets` list (and `resources` for resources); "bring it back" calls `restore_entries`.

## API

| Method and path | What it does |
| --- | --- |
| `DELETE /api/platform/entries/{id}` | Move to the Trash (`{"trashed": true}`). Same permission as before: EDITOR+, or an AUTHOR on their own entry that isn't approved or published |
| `DELETE /api/platform/entries/{id}?permanent=true` | Delete a **trashed** entry forever (`{"deleted": true}`); 409 for an entry not in the Trash |
| `POST /api/platform/entries/{id}/restore` | Restore from the Trash; returns the entry. 409 if it isn't in the Trash |
| `POST /api/platform/entries/trash/empty` | Empty the Trash (ADMIN/OWNER); returns `{"deleted": n}` |
| `GET /api/platform/entries/trash` | `{count, effective_days, platform_default_days, workspace_override_days}` |
| `PATCH /api/platform/entries/{id}` | 409 on a trashed entry (restore it first); `status: "trashed"` is refused — use `DELETE` |
| `GET /api/groups/{id}/preferences/trash` | the workspace's auto-empty: platform default, override, effective |
| `PATCH /api/groups/{id}/preferences` | `trash_auto_empty_days`: `0` (never), `7`, `30`, `90`, or `null` to inherit (ADMIN/OWNER) |
| `GET` / `PUT /api/admin/trash` | the platform default, `{auto_empty_days}` (super admin) |
| `DELETE /api/platform/assets/{id}`, `/resources/{id}` | Move to the Trash (`{"trashed": true}`); EDITOR+, as before. The file stays in storage |
| `DELETE …/assets/{id}?permanent=true`, `…/resources/{id}?permanent=true` | Delete a **trashed** asset (file included) or resource forever (`{"deleted": true}`); 409 for one not in the Trash |
| `POST /api/platform/assets/{id}/restore`, `/resources/{id}/restore` | Restore from the Trash; returns the asset or resource. 409 if it isn't in the Trash |
| `PATCH /api/platform/assets/{id}`, `/resources/{id}` | 409 on a trashed one (restore it first) |
| `GET /api/platform/trash` | the whole Trash: `{entries, assets, resources, total}` plus the auto-empty settings |
| `GET /api/platform/trash/assets`, `/trash/resources` | the trashed assets / resources |
| `POST /api/platform/trash/empty` | Empty the whole Trash — entries, assets and resources (ADMIN/OWNER); returns `{deleted, entries, assets, resources}` |

`GET /api/platform/entries` and `/entries/counts` leave trashed entries out (`counts` has a `trashed` key, not included in `total`). An entry can't be created with status `trashed`. `GET /api/platform/assets` and `/resources` leave trashed ones out; a fetch by id returns them with `trashedAt` (and `trashedBy`). `POST /entries/trash/empty` still empties only entries; the Trash view uses `POST /trash/empty`.

The SDK's `entries.delete(id)`, `assets.delete(id)` and `resources.delete(id)`, the CLI and MarvinMCP call `DELETE`, so they now move the item to the Trash instead of deleting it. The admin routes for assets and resources (`/api/admin/platform/…`) do the same; their asset delete used to remove only the row and leave the file in storage.

## Settings

| Setting | Where | Default |
| --- | --- | --- |
| Platform auto-empty | Admin → Site Settings → Trash (`platform_settings` key `trash`) | 30 days |
| Workspace auto-empty | Settings → General → Trash (`trash_auto_empty_days`) | inherit the platform default |

## Limits

- Deleting a collection is still immediate.
- A trashed asset's file is still reachable by its URL until it is deleted forever: the Trash hides the asset from Marvin and the publishing API, not the file from the bucket. An image URL pasted into an entry's text or a field (rather than attached), or into the raw site `metadata` blob, keeps showing it, and a site built earlier keeps its copy until it rebuilds.
- A workspace export or backup includes trashed assets and resources, without their Trash state: importing one brings them back out of the Trash.
- No agent or workflow can empty the Trash or delete forever.
- A user collection with the slug `trash` made before this release keeps its slug, and the system Trash isn't added to that workspace.

## Related

- [Collections](collections.md) — the system collections.
- [Workflows](workflows.md) — the Entry action's `trash` and `restore` ops.
- [Agents and Ask](agents-and-ask.md) — `trash_entries`, `restore_entries`.
- [Publishing API](publishing-api.md) — what a site sees.
