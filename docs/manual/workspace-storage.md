# A workspace's own storage

A workspace can keep its files in its own bucket instead of the platform's storage: its own Cloudflare R2, AWS S3 or
Backblaze B2 bucket, paid for and owned by whoever runs that workspace. Marvin stores new uploads there, serves them
from the bucket's public address, and keeps working with the files already stored elsewhere.

## Who can do what

- **A platform super admin** allows it for the whole platform: **Admin → Storage → Workspaces' own storage** (off
  until then; the environment default is `STORAGE_ALLOW_WORKSPACE_STORAGE`). The same card sets which endpoints a
  workspace may use: known services (Cloudflare R2, AWS S3, Backblaze B2; the default), any public address, or any
  address including the platform's own network.
- **A workspace owner** adds buckets, checks them and chooses where new uploads go: **Workspace settings → Storage**
  (`/workspace/settings/storage`). Workspace admins see the page but can't change it.

## Setting up a bucket (Cloudflare R2)

1. In Cloudflare, create a bucket, then **Settings → Public access**: turn on the R2.dev address, or connect a custom
   domain. Copy that public address (`https://pub-….r2.dev` or `https://files.example.com`), not the
   `….r2.cloudflarestorage.com` API address, which needs a key to read.
2. **R2 → Manage API tokens → Create API token**: permission **Object Read & Write**, applied to **that bucket only**.
   Keep the access key ID and secret access key.
3. In Marvin, **Workspace settings → Storage → Add a bucket**: the bucket name, the endpoint
   (`https://<account id>.r2.cloudflarestorage.com`), the public address, and the keys. Keys are saved as workspace
   secrets (**Workspace settings → Environment → Secrets**): pick ones you already added, or type them and the page
   saves them there first. The access key ID can also be typed as a plain setting.
4. **Check connection.** Marvin lists the bucket, writes a tiny file under `_marvin-healthcheck/`, reads it back,
   deletes it, then writes one more and fetches it from the public address. Each step shows its result; the first
   failure says why (a revoked key, a key that can't reach the bucket, public access off, a public address that serves
   another bucket). A passing check marks the bucket **Verified**.
5. Under **New uploads go to**, choose **Your own bucket** and the verified bucket, then **Save**.

AWS S3 and Backblaze B2 work the same way: leave the endpoint empty for AWS (and set the region), use
`https://s3.<region>.backblazeb2.com` for B2, and use a key limited to the one bucket.

## How it behaves

- **Only new uploads change place.** Files already stored, on the platform or in another bucket, stay where they are
  and keep working; each file remembers where it lives. Switching back to the platform's storage is always allowed.
- **Nothing falls back silently.** While a workspace uses its own bucket, an upload that can't go there is refused
  with a message saying why (HTTP 503), and never written to the platform's storage instead: when the bucket's
  connection isn't verified, when its keys were changed in Secrets after the last check (check it again), or when a
  platform admin has turned workspace storage off (switch back to the platform's storage, or ask them).
- **A bucket's name, endpoint and prefix never change.** Another bucket is another connection; its keys, label and
  public address can change, which makes it unverified until checked again. **Retire** a bucket you no longer upload
  to: its files keep serving.
- **The platform's own bucket can't be used** as a workspace bucket, whatever keys or prefix.
- **Usage**: the page counts each bucket's files. Files in a workspace's own bucket don't count toward the platform's
  storage, and they aren't in the platform's asset backups: the bucket is its owner's to back up. **Backups** on the
  page decides whether the workspace's backup bundles include them (off by default: bundles grow, and egress is the
  owner's); files on the platform's storage are always in them.
- **Hourly checks**: the system task **Check Workspace Storage** checks every bucket a workspace uploads to (and any
  marked failing) the way **Check connection** does. One failure is a blip and changes nothing; two in a row mark the
  bucket failing, which pauses that workspace's uploads with a plain message and sends `workspace_storage_unhealthy`
  to the workspace; the first pass after that marks it working again and sends `workspace_storage_recovered`. A check
  never re-verifies keys: after a key change, an owner checks the connection.
- **Platform admins** see every workspace's buckets (status, last check, files, whether uploads go there, whether its
  bundles include them) on **Admin → Storage**, and **Admin → Backup health** lists the workspaces whose files the
  platform's asset backups don't reach.
- **A file is only ever read from its own workspace's bucket**: a file record pointing at another workspace's bucket
  (a hand-edited bundle, say) is refused rather than read with that workspace's keys.
- **Changes are audited**: switching where uploads go is a `storage_provider_changed` event (platform admins are
  notified, as for the platform's own storage switch), adding, changing or retiring a bucket is
  `workspace_settings_changed` (`storage`), and the platform switch is `platform_settings_changed`
  (`workspace_storage`). None of them carries a key.

## API

- `GET /api/groups/storage-settings`: the page's data (OWNER and ADMIN).
- `POST /api/groups/storage-settings/connections`: add a bucket (`pluginSlug`, `label`, `settings`, `secretRefs`).
- `PATCH /api/groups/storage-settings/connections/{id}`, `POST …/{id}/check`, `POST …/{id}/retire`.
- `PUT /api/groups/storage-settings/mode`: `{"mode": "platform"}` or `{"mode": "workspace", "connectionId": …}`.
- `PUT /api/groups/storage-settings/bundle`: `{"include": true}` puts the bucket's files in backup bundles (OWNER).
- `GET /api/admin/storage/workspace-buckets`: every workspace's buckets (super admins).
- `GET` / `PUT /api/admin/storage/workspace-policy`: `{"allowed": …, "endpointPolicy": "known" | "public" | "any"}`
  (super admins).

## Copying existing files into the bucket

On a verified bucket, **Copy existing files here…** first shows what it would do, without copying anything: how many
of the workspace's files (and how much data) are elsewhere, and how many entries embed links to them. **Start copying**
then copies them in the background as a workspace scheduled task, **Copy files to <bucket>** (its history in
**Automation → Scheduled Tasks** says how many moved and what failed). Each file is copied, its copy's sha256 checked,
and only then is its row pointed at the bucket, in a short transaction that leaves alone a file changed or deleted
meanwhile. **Originals are never deleted**, so links already published (in entries, built sites, emails) keep working.
A run that stops part way is finished by starting it again: files already there are skipped. Switch new uploads to the
bucket first, or files uploaded during the copy stay behind (the dry run says so).

The command line does the same, and the way back: `python -m marvin.scripts.storage_migrate --workspace <slug> --to
ws:<connection id> --verify [--dry-run]`, and `--to s3` (or `local`) to move a workspace's files back to the platform.
A run into a workspace's bucket must name that workspace (`--workspace`); another workspace's files are refused.

A copy sends two workspace events, which workflows and webhooks can react to: `workspace_storage_copy_started`
(the bucket, how many files and how much data) and `workspace_storage_copy_finished` (moved, already there, changed
meanwhile, failed, data copied, and each failed file with why), also when the copy couldn't start. The task's own
`scheduled_task_completed` / `scheduled_task_failed` follow as for any task.

- `GET /api/groups/storage-settings/connections/{id}/copy`: the dry run.
- `POST /api/groups/storage-settings/connections/{id}/copy`: start copying (OWNER; 202 with the task).
