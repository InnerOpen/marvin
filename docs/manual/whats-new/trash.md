# Trash

Deleting an entry now moves it to the **Trash**, where it can be restored until the Trash is emptied. A workflow can move a whole query of entries there, and so can an agent; only a person can empty the Trash or delete anything forever.

## What it does

**Delete moves to the Trash.** On the entry page, **Move to Trash** (it replaced **Delete**) sets the entry's status to `trashed`. There is no confirmation: the entries list you land on offers **Undo**. A trashed entry:

- is off the site and the publishing API (a published entry is unpublished on the way in, so `entry_unpublished` fires and the site rebuilds);
- is out of every list, search and count: the entries list, collections (manual ones keep its membership, so a restore puts it back in place), smart collections, `find_entries`, workflow targets, search and the RAG index, tag counts, the dashboard, `workspace_overview`;
- is listed only in the **Trash** system collection, and still opens by its id (the entry page shows "This entry is in the Trash" and is read-only until restored);
- keeps where it came from in `metadata_json.trash` (`previous_status`, `trashed_at`, `trashed_by`), removed again on restore;
- loses a pending Scheduled Publish (`publish_at` is cleared), so neither the trashed entry nor its restore goes live on schedule.

**Restore** puts the entry back in the status it had, except that a **published** entry comes back as a **draft**: restoring never puts anything on the site by itself. Publish it again when it's ready.

**Delete forever** removes one trashed entry for good. **Empty trash** removes every entry in the Trash, after one confirmation ("Permanently delete N entries? This can't be undone."). Both delete each entry the normal way, so `entry_deleted` fires per entry and its links to collections, tags, assets and resources go with it.

**Auto-empty.** Entries that have been in the Trash longer than the workspace allows are deleted forever by an hourly job (on the scheduler leader only; running it twice deletes nothing twice). The limit is a platform default — **30 days** unless a super admin changes it — that a workspace can override with **Never**, 7, 30 or 90 days. **Never** keeps entries until someone empties the Trash. An entry with no recorded `trashed_at` (one trashed before the record existed, e.g. from a restored backup) is never auto-deleted; emptying the Trash removes it.

**Archive or Trash?** Archive retires an entry you want to keep (it stays in the **Archive** collection indefinitely and is never deleted). Trash is for entries you want gone, with a safety net.

### Events

| Event | When |
| --- | --- |
| `entry_trashed` | an entry is moved to the Trash (after `entry_updated`, and `entry_unpublished` when it was published) |
| `entry_restored` | an entry leaves the Trash (also: an archived entry is restored) |
| `entry_deleted` | an entry is deleted forever (Delete forever, Empty trash, auto-empty) |

## Where

- **Trash** collection (`/workspace/collections/<id>`, listed with the system collections, 🗑️): per-entry **Restore** and **Delete forever**, **Restore selected**, **Empty trash** (workspace ADMIN/OWNER), and how long the Trash keeps entries.
- Entry page: **Move to Trash**; on a trashed entry, the banner with **Restore** and **Delete forever**.
- **Settings → General → Trash**: the workspace's auto-empty choice (ADMIN/OWNER).
- **Admin → Site Settings → Trash**: the platform default (super admin).

## How to use

**Clear out a batch with a workflow.** Make a workflow with **Run on a query of entries** (for example entry type `signup`, status `inbox`) and one **Entry action** step with **Move to Trash** (`op: "trash"`). Run it, check the Trash, then **Empty trash**. Entries already in the Trash are left out of the query, so running it again does nothing to them.

**Restore with a workflow.** The **Restore** op on a trashed entry returns it to the status it had (a published one as a draft); target trashed entries with status **in the Trash** (`status: "trashed"`).

**Ask an agent.** "Delete the test signups" makes an agent call `trash_entries`: the entries go to the Trash and the answer links to it.

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

`GET /api/platform/entries` and `/entries/counts` leave trashed entries out (`counts` has a `trashed` key, not included in `total`). An entry can't be created with status `trashed`.

The SDK's `entries.delete(id)`, the CLI and MarvinMCP call `DELETE /entries/{id}`, so they now move the entry to the Trash instead of deleting it.

## Settings

| Setting | Where | Default |
| --- | --- | --- |
| Platform auto-empty | Admin → Site Settings → Trash (`platform_settings` key `trash`) | 30 days |
| Workspace auto-empty | Settings → General → Trash (`trash_auto_empty_days`) | inherit the platform default |

## Limits

- Only entries have a Trash; deleting an asset, resource or collection is still immediate.
- No agent or workflow can empty the Trash or delete forever.
- A user collection with the slug `trash` made before this release keeps its slug, and the system Trash isn't added to that workspace.

## Related

- [Collections](collections.md) — the system collections.
- [Workflows](workflows.md) — the Entry action's `trash` and `restore` ops.
- [Agents and Ask](agents-and-ask.md) — `trash_entries`.
