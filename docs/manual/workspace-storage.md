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
  storage, and they aren't in the platform's asset backups: the bucket is its owner's to back up.
- **Changes are audited**: switching where uploads go is a `storage_provider_changed` event (platform admins are
  notified, as for the platform's own storage switch), adding, changing or retiring a bucket is
  `workspace_settings_changed` (`storage`), and the platform switch is `platform_settings_changed`
  (`workspace_storage`). None of them carries a key.

## API

- `GET /api/groups/storage-settings`: the page's data (OWNER and ADMIN).
- `POST /api/groups/storage-settings/connections`: add a bucket (`pluginSlug`, `label`, `settings`, `secretRefs`).
- `PATCH /api/groups/storage-settings/connections/{id}`, `POST …/{id}/check`, `POST …/{id}/retire`.
- `PUT /api/groups/storage-settings/mode`: `{"mode": "platform"}` or `{"mode": "workspace", "connectionId": …}`.
- `GET` / `PUT /api/admin/storage/workspace-policy`: `{"allowed": …, "endpointPolicy": "known" | "public" | "any"}`
  (super admins).

Moving existing files into a workspace's bucket is planned (a dry run first, then a copy that never deletes the
originals); until then only new uploads go there.
