"""Managing a workspace's own storage: its connections (buckets), checking one, and switching where uploads go.

The rules live in services/storage/workspace.py. Here: what the settings page shows and changes. Keys are only ever
workspace secret slugs (`secret_refs`); this module never sees a key except to fingerprint it while checking.

- A connection's bucket, endpoint and prefix never change: a different bucket is a new connection, so rows already
  stored as `ws:<id>` keep pointing at the right place. Its keys (secret slugs), public URL and label can change;
  any change sends it back to `unverified` until checked again.
- Checking = the platform's storage check (list, put, get, delete) through the connection, then a probe fetched from
  its public URL through the SSRF-guarded client. Success records a fingerprint of the keys: if the secrets change
  later without a new check, uploads stop (workspace.write_target) rather than run on unverified keys.
- Switching to `workspace` needs the platform's policy on and a verified connection; switching back is always
  allowed. Neither moves a file.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from marvin_integration_sdk.storage import StorageConfigError

from . import registry
from . import workspace as ws

MAX_LABEL = 80
PROBE_TIMEOUT_SECONDS = 10


class WorkspaceStorageError(ValueError):
    """A change that can't be made (the message is safe to show)."""


# ── what a provider asks for ─────────────────────────────────────────────────


@dataclass
class FieldSpec:
    env: str
    label: str
    help: str
    required: bool
    secret: bool
    fixed: bool
    """Can't change once the connection exists (it names the bucket)."""


@dataclass
class ProviderSpec:
    slug: str
    name: str
    fields: list[FieldSpec] = field(default_factory=list)


def _fixed_envs(provider_cls) -> set[str]:
    """The settings that name the bucket: the endpoint, the provider's always-required settings, and a prefix."""
    always = {s.env for s in provider_cls.settings if s.required and not s.secret}
    fixed = {e for e in always if e in {s.env for s in provider_cls.workspace_settings}}
    if provider_cls.endpoint_setting:
        fixed.add(provider_cls.endpoint_setting)
    fixed |= {s.env for s in provider_cls.workspace_settings if s.env.endswith("_PREFIX")}
    return fixed


def provider_specs(pol: ws.Policy, purpose: str = ws.PURPOSE_ASSETS) -> list[ProviderSpec]:
    """The installed plugins a workspace may use for ``purpose`` (the policy's plugins with a sound declaration)."""
    out = []
    for slug in pol.allowed_plugins:
        try:
            cls = ws.plugin_class(slug, purpose)
            name = registry.get_plugin(slug, needs="target" if purpose == ws.PURPOSE_BACKUPS else "provider").name
        except StorageConfigError:
            continue
        fixed = _fixed_envs(cls)
        out.append(
            ProviderSpec(
                slug=slug,
                name=name,
                fields=[FieldSpec(s.env, s.label or s.env, s.help, s.required, s.secret, s.env in fixed) for s in cls.workspace_settings],
            )
        )
    return out


def _provider_cls(slug: str, pol: ws.Policy, purpose: str = ws.PURPOSE_ASSETS):
    if slug not in pol.allowed_plugins:
        raise WorkspaceStorageError(f"The platform doesn't allow {slug!r} for workspace storage")
    try:
        return ws.plugin_class(slug, purpose)
    except StorageConfigError as e:
        raise WorkspaceStorageError(str(e)) from e


# ── connections ──────────────────────────────────────────────────────────────


def _clean(provider_cls, settings: dict | None, secret_refs: dict | None, existing_secret_slugs: set[str]) -> tuple[dict, dict]:
    """Keep only the provider's workspace settings: plain values for non-secret ones, secret slugs for the rest (any
    setting may name a secret; a secret one must). Refuses a value that should be a secret."""
    declared = {s.env: s for s in provider_cls.workspace_settings}
    clean_settings: dict[str, str] = {}
    for env, value in (settings or {}).items():
        if env not in declared:
            raise WorkspaceStorageError(f"{env} isn't a setting of this storage")
        if declared[env].secret:
            raise WorkspaceStorageError(f"{declared[env].label or env} must come from a workspace secret")
        text = str(value).strip() if value is not None else ""
        if text:
            clean_settings[env] = text
    clean_refs: dict[str, str] = {}
    for env, slug in (secret_refs or {}).items():
        if env not in declared:
            raise WorkspaceStorageError(f"{env} isn't a setting of this storage")
        slug = str(slug or "").strip()
        if not slug:
            continue
        if slug not in existing_secret_slugs:
            raise WorkspaceStorageError(f"No workspace secret named {slug!r}")
        clean_refs[env] = slug
        clean_settings.pop(env, None)
    missing = [s.label or s.env for s in provider_cls.workspace_settings if s.required and s.env not in clean_settings and s.env not in clean_refs]
    if missing:
        raise WorkspaceStorageError(f"Missing: {', '.join(missing)}")
    return clean_settings, clean_refs


def _secret_slugs(group_id) -> set[str]:
    from marvin.services.secrets.factory import get_secret_backend

    return set(get_secret_backend().list_slugs(group_id))


def _refuse_shared_bucket(session, group_id, cls, settings: dict, purpose: str) -> None:
    """Backups and served files never share a bucket: a backup bucket can't be one of the workspace's file buckets,
    nor the other way round."""
    from marvin.db.models.groups.storage_settings import WorkspaceStorageConnectionModel

    mine = ws._identity(cls, settings.get)
    others = session.query(WorkspaceStorageConnectionModel).filter(
        WorkspaceStorageConnectionModel.group_id == group_id, WorkspaceStorageConnectionModel.purpose != purpose
    )
    for other in others:
        try:
            if ws.bucket_identity(ws._snapshot(other)) == mine:
                raise WorkspaceStorageError(
                    "Backups need their own private bucket: this one is already used for the workspace's files"
                    if purpose == ws.PURPOSE_BACKUPS
                    else "This bucket already holds the workspace's backups: files need another one"
                )
        except StorageConfigError:
            continue


def create_connection(
    session, group_id, user_id, *, plugin_slug: str, label: str | None, settings: dict, secret_refs: dict, purpose: str = ws.PURPOSE_ASSETS
):
    from marvin.db.models.groups.storage_settings import WorkspaceStorageConnectionModel

    if purpose not in (ws.PURPOSE_ASSETS, ws.PURPOSE_BACKUPS):
        raise WorkspaceStorageError("purpose must be 'assets' or 'backups'")
    pol = ws.policy(session)
    cls = _provider_cls(plugin_slug, pol, purpose)
    clean_settings, clean_refs = _clean(cls, settings, secret_refs, _secret_slugs(group_id))
    _check_endpoint_now(cls, clean_settings, pol)
    _refuse_shared_bucket(session, group_id, cls, clean_settings, purpose)
    conn = WorkspaceStorageConnectionModel(
        session=session,
        group_id=group_id,
        plugin_slug=plugin_slug,
        purpose=purpose,
        label=(label or "").strip()[:MAX_LABEL] or None,
        settings=clean_settings,
        secret_refs=clean_refs,
        status="unverified",
        created_by=user_id,
    )
    session.add(conn)
    session.commit()
    return conn


def update_connection(session, group_id, connection_id, *, label: str | None = None, settings: dict | None = None, secret_refs: dict | None = None):
    conn = get_connection(session, group_id, connection_id)
    if conn.status == ws.STATUS_RETIRED:
        raise WorkspaceStorageError("This connection is retired; add a new one")
    pol = ws.policy(session)
    cls = _provider_cls(conn.plugin_slug, pol, conn.purpose or ws.PURPOSE_ASSETS)
    fixed = _fixed_envs(cls)
    merged_settings = {**(conn.settings or {}), **(settings or {})}
    merged_refs = {**(conn.secret_refs or {}), **(secret_refs or {})}
    for env in fixed:
        before, after = (conn.settings or {}).get(env, ""), merged_settings.get(env, "")
        if str(before or "").strip() != str(after or "").strip():
            raise WorkspaceStorageError("The bucket, endpoint and prefix can't change: add a new connection for another bucket")
    clean_settings, clean_refs = _clean(cls, merged_settings, merged_refs, _secret_slugs(group_id))
    if label is not None:
        conn.label = label.strip()[:MAX_LABEL] or None
    if (clean_settings, clean_refs) != (conn.settings or {}, conn.secret_refs or {}):
        conn.settings, conn.secret_refs = clean_settings, clean_refs
        conn.status, conn.verified_at, conn.credential_fingerprint = "unverified", None, None
        conn.version = (conn.version or 1) + 1
    session.commit()
    ws.reset_cache()
    return conn


def retire_connection(session, group_id, connection_id):
    """Retire a connection: no new uploads through it, but the files already in it still serve. The active one can't
    be retired while the workspace uses it."""
    from marvin.db.models.groups.storage_settings import WorkspaceStorageSettingsModel

    conn = get_connection(session, group_id, connection_id)
    row = session.query(WorkspaceStorageSettingsModel).filter_by(group_id=group_id).one_or_none()
    if row and row.credential_mode == ws.MODE_WORKSPACE and str(row.active_connection_id) == str(conn.id):
        raise WorkspaceStorageError("Switch the workspace to another connection or the platform's storage first")
    if row and str(row.backup_connection_id) == str(conn.id):
        raise WorkspaceStorageError("Backups go to this bucket: pick another backup bucket or turn own backups off first")
    conn.status, conn.retired_at = ws.STATUS_RETIRED, datetime.now(UTC).replace(tzinfo=None)
    if row and str(row.active_connection_id) == str(conn.id):
        row.active_connection_id = None
    session.commit()
    ws.reset_cache()
    return conn


def get_connection(session, group_id, connection_id):
    from marvin.db.models.groups.storage_settings import WorkspaceStorageConnectionModel

    conn = session.get(WorkspaceStorageConnectionModel, uuid.UUID(str(connection_id)))
    if conn is None or str(conn.group_id) != str(group_id):
        raise LookupError("Connection not found")
    return conn


def _check_endpoint_now(cls, settings: dict, pol: ws.Policy) -> None:
    from marvin.core.config import get_app_settings

    endpoint = settings.get(cls.endpoint_setting) if cls.endpoint_setting else None
    try:
        ws.check_endpoint(endpoint, pol.endpoint_policy, production=bool(get_app_settings().PRODUCTION))
    except StorageConfigError as e:
        raise WorkspaceStorageError(f"Endpoint refused: {e}") from e


# ── checking ─────────────────────────────────────────────────────────────────


def _run_checks(session, conn) -> list[dict]:
    """The storage check through the connection, then (if it passed) a probe fetched from its public URL: one dict
    per step, {name, ok, ms, error, code}. Never raises."""
    from marvin.services.storage.healthcheck import check_provider, explain, scrub

    pol = ws.policy(session)
    backups = (conn.purpose or ws.PURPOSE_ASSETS) == ws.PURPOSE_BACKUPS
    try:
        if backups:
            target = ws.build_connection_target(
                ws._snapshot(conn), pol.endpoint_policy, production=ws._production(), asset_buckets=_asset_buckets(session, conn.group_id)
            )
        else:
            provider = ws.build_connection_provider(ws._snapshot(conn), pol.endpoint_policy, production=ws._production())
    except Exception as e:  # noqa: BLE001 — a connection that can't be built is the check's first failed step
        return [{"name": "connect", "ok": False, "ms": 0.0, "error": str(e), "code": None}]
    if backups:  # a private bucket: list, put, get, delete — no public URL
        from marvin.services.storage.healthcheck import check_target

        result = check_target(target)
        return [{"name": s.name, "ok": s.ok, "ms": round(s.ms, 1), "error": scrub(s.error), "code": s.code} for s in result.steps]
    result = check_provider(provider, location=ws.location_for(conn.id))
    steps = [{"name": s.name, "ok": s.ok, "ms": round(s.ms, 1), "error": scrub(s.error), "code": s.code} for s in result.steps]
    if result.ok:
        steps.append(_public_url_step(provider, explain))
    return steps


def _asset_buckets(session, group_id) -> list[tuple]:
    """(endpoint, bucket) of the workspace's file buckets: its backups may not go to any of them."""
    from marvin.db.models.groups.storage_settings import WorkspaceStorageConnectionModel

    out = []
    for c in session.query(WorkspaceStorageConnectionModel).filter_by(group_id=group_id, purpose=ws.PURPOSE_ASSETS):
        try:
            out.append(ws.bucket_identity(ws._snapshot(c)))
        except StorageConfigError:
            continue
    return out


def check_connection(session, group_id, connection_id) -> dict:
    """An owner's check: run the checks and record the outcome at once (verified, or failing). Returns
    {ok, steps: [{name, ok, ms, error, code}], checked_at}."""
    conn = get_connection(session, group_id, connection_id)
    steps = _run_checks(session, conn)
    return _record(session, conn, steps, ok=all(s["ok"] for s in steps))


HEALTH_FAILURES_TO_FAIL = 2
"""Failed hourly checks in a row before a verified connection is marked failing (uploads then stop): one blip isn't."""


def health_check(session, conn) -> str | None:
    """The hourly check of one connection. Returns "unhealthy" when this check marked it failing, "recovered" when it
    passed again after that, else None. Unlike an owner's check, a pass doesn't re-verify changed keys (the key
    fingerprint stays as the owner's last check left it)."""
    steps = _run_checks(session, conn)
    ok = all(s["ok"] for s in steps)
    now = datetime.now(UTC).replace(tzinfo=None)
    conn.last_checked_at = now
    transition = None
    if ok:
        if conn.status == "failing" and conn.verified_at is not None:
            conn.status, transition = ws.STATUS_OK, "recovered"
        conn.consecutive_failures, conn.last_error = 0, None
    else:
        failed = next(s for s in steps if not s["ok"])
        conn.last_error = f"{failed['name']}: {failed['error']}"[:500]
        conn.consecutive_failures = (conn.consecutive_failures or 0) + 1
        if conn.status == ws.STATUS_OK and conn.consecutive_failures >= HEALTH_FAILURES_TO_FAIL:
            conn.status, transition = "failing", "unhealthy"
    session.commit()
    ws.reset_cache()
    return transition


def connections_to_watch(session) -> list:
    """The connections the hourly check looks at: every one a workspace uploads through, and any that is failing."""
    from marvin.db.models.groups.storage_settings import WorkspaceStorageConnectionModel, WorkspaceStorageSettingsModel

    active = {
        str(cid)
        for (cid,) in session.query(WorkspaceStorageSettingsModel.active_connection_id).filter(
            WorkspaceStorageSettingsModel.credential_mode == ws.MODE_WORKSPACE, WorkspaceStorageSettingsModel.active_connection_id.isnot(None)
        )
    }
    active |= {
        str(cid)
        for (cid,) in session.query(WorkspaceStorageSettingsModel.backup_connection_id).filter(
            WorkspaceStorageSettingsModel.backup_connection_id.isnot(None)
        )
    }
    rows = session.query(WorkspaceStorageConnectionModel).filter(WorkspaceStorageConnectionModel.status.in_((ws.STATUS_OK, "failing"))).all()
    return [c for c in rows if str(c.id) in active or c.status == "failing"]


def _public_url_step(provider, explain) -> dict:
    """Put a probe, fetch it from the public URL through the SSRF-guarded client, delete it."""
    import time

    from marvin.services.integrations.http_client import build_http
    from marvin.services.storage.healthcheck import healthcheck_key

    key = healthcheck_key()
    data = f"Marvin public URL check {key}\n".encode()
    started = time.perf_counter()
    error = None
    try:
        provider.put(key, io.BytesIO(data), "text/plain", {})
        url = provider.get_public_url(key)
        resp = build_http().get(url, timeout=PROBE_TIMEOUT_SECONDS)
        if resp.status_code != 200:
            error = f"the public URL answered {resp.status_code}: is public access on for the bucket, at this address?"
        elif resp.content != data:
            error = "the public URL served something else: does it point at this bucket (and prefix)?"
    except Exception as e:  # noqa: BLE001
        error = f"the public URL couldn't be fetched: {explain(e).message}"
    finally:
        try:
            provider.delete(key)
        except Exception:  # noqa: BLE001 — the probe is tiny and under _marvin-healthcheck/
            pass
    return {"name": "public url", "ok": error is None, "ms": round((time.perf_counter() - started) * 1000, 1), "error": error, "code": None}


def _record(session, conn, steps: list[dict], *, ok: bool) -> dict:
    now = datetime.now(UTC).replace(tzinfo=None)
    conn.last_checked_at = now
    if conn.status != ws.STATUS_RETIRED:
        conn.status = ws.STATUS_OK if ok else "failing"
    if ok:
        conn.verified_at, conn.last_error, conn.credential_fingerprint = now, None, ws.credential_fingerprint(conn)
        conn.consecutive_failures = 0
    else:
        failed = next((s for s in steps if not s["ok"]), None)
        conn.last_error = f"{failed['name']}: {failed['error']}"[:500] if failed else "failed"
    session.commit()
    ws.reset_cache()
    return {"ok": ok, "steps": steps, "checked_at": now.isoformat() + "Z"}


# ── mode ─────────────────────────────────────────────────────────────────────


def set_mode(session, group_id, user_id, *, mode: str, connection_id=None) -> tuple[str | None, str | None]:
    """Switch where new uploads go. Returns (previous location, new location); None is the platform's storage."""
    from marvin.db.models.groups.storage_settings import WorkspaceStorageSettingsModel

    if mode not in (ws.MODE_PLATFORM, ws.MODE_WORKSPACE):
        raise WorkspaceStorageError("mode must be 'platform' or 'workspace'")
    row = session.query(WorkspaceStorageSettingsModel).filter_by(group_id=group_id).one_or_none()
    previous = ws.location_for(row.active_connection_id) if row and row.credential_mode == ws.MODE_WORKSPACE and row.active_connection_id else None
    if row is None:
        row = WorkspaceStorageSettingsModel(session=session, group_id=group_id)
        session.add(row)
    if mode == ws.MODE_WORKSPACE:
        if not ws.policy(session).allowed:
            raise WorkspaceStorageError("The platform doesn't allow workspace storage")
        conn = get_connection(session, group_id, connection_id) if connection_id else None
        if conn is None or conn.status != ws.STATUS_OK:
            raise WorkspaceStorageError("Check the connection first: only a verified connection can take uploads")
        if (conn.purpose or ws.PURPOSE_ASSETS) != ws.PURPOSE_ASSETS:
            raise WorkspaceStorageError("That bucket is for backups: files need a bucket of their own")
        row.active_connection_id = conn.id
    row.credential_mode, row.updated_by = mode, user_id
    session.commit()
    ws.reset_cache()
    return previous, ws.location_for(row.active_connection_id) if mode == ws.MODE_WORKSPACE else None


# ── the page ─────────────────────────────────────────────────────────────────


def connection_view(conn) -> dict[str, Any]:
    return {
        "id": str(conn.id),
        "plugin_slug": conn.plugin_slug,
        "purpose": conn.purpose or ws.PURPOSE_ASSETS,
        "label": conn.label,
        "location": ws.location_for(conn.id),
        "settings": dict(conn.settings or {}),
        "secret_refs": dict(conn.secret_refs or {}),
        "status": conn.status,
        "verified_at": conn.verified_at,
        "last_checked_at": conn.last_checked_at,
        "last_error": conn.last_error,
        "retired_at": conn.retired_at,
    }


def view(session, group_id) -> dict[str, Any]:
    """Everything the Workspace → Storage page shows."""
    import sqlalchemy as sa

    from marvin.db.models.groups.storage_settings import WorkspaceStorageConnectionModel, WorkspaceStorageSettingsModel
    from marvin.db.models.platform import Assets

    pol = ws.policy(session)
    row = session.query(WorkspaceStorageSettingsModel).filter_by(group_id=group_id).one_or_none()
    conns = (
        session.query(WorkspaceStorageConnectionModel).filter_by(group_id=group_id).order_by(WorkspaceStorageConnectionModel.created_at.desc()).all()
    )
    usage = dict(
        session.query(Assets.storage_provider, sa.func.count(Assets.id)).filter(Assets.group_id == group_id).group_by(Assets.storage_provider).all()
    )
    return {
        "policy": {"allowed": pol.allowed, "endpoint_policy": pol.endpoint_policy},
        "mode": row.credential_mode if row else ws.MODE_PLATFORM,
        "active_connection_id": str(row.active_connection_id) if row and row.active_connection_id else None,
        "bundle_includes_own_bucket": bool(row.bundle_includes_own_bucket) if row else False,
        "providers": [{"slug": p.slug, "name": p.name, "fields": [vars(f) for f in p.fields]} for p in provider_specs(pol)],
        "backup_providers": [
            {"slug": p.slug, "name": p.name, "fields": [vars(f) for f in p.fields]} for p in provider_specs(pol, ws.PURPOSE_BACKUPS)
        ],
        "backup_connection_id": str(row.backup_connection_id) if row and row.backup_connection_id else None,
        "backup_keep": int(row.backup_keep) if row else 7,
        "connections": [{**connection_view(c), "files": int(usage.get(ws.location_for(c.id), 0))} for c in conns],
        "platform_files": int(sum(n for loc, n in usage.items() if not ws.is_workspace_location(loc))),
    }


# ── the platform's policy (Admin → Storage) ──────────────────────────────────


def save_policy(session, *, allowed: bool, endpoint_policy: str) -> tuple[dict, list[str]]:
    """Store the platform's policy. Returns (the stored value, what changed, one line each)."""
    from marvin.services.platform_settings import PlatformSettingsService

    if endpoint_policy not in ws.ENDPOINT_POLICIES:
        raise WorkspaceStorageError(f"endpoint_policy must be one of {', '.join(ws.ENDPOINT_POLICIES)}")
    before = ws.policy(session)
    svc = PlatformSettingsService(session)
    stored = dict(svc.get(ws.POLICY_KEY) or {})
    stored.update({"allowed": bool(allowed), "endpoint_policy": endpoint_policy})
    svc.set(ws.POLICY_KEY, stored)
    ws.reset_cache()
    changes = []
    if before.allowed != bool(allowed):
        changes.append(f"Workspace storage: {'allowed' if allowed else 'off'}")
    if before.endpoint_policy != endpoint_policy:
        changes.append(f"Endpoint policy: {before.endpoint_policy} -> {endpoint_policy}")
    return stored, changes


# ── copying existing files into a bucket ─────────────────────────────────────

COPY_TASK_TYPE = "copy_to_workspace_storage"


def copy_plan(session, group_id, connection_id) -> dict[str, Any]:
    """What copying the workspace's existing files into the connection would do, without doing it: the files and
    bytes by where they are now, and how many entries embed their current links (those links keep working: a copy
    never deletes the original)."""
    import sqlalchemy as sa

    from marvin.db.models.platform import Assets, Entries
    from marvin.services.storage.keys import workspace_code

    conn = get_connection(session, group_id, connection_id)
    location = ws.location_for(conn.id)
    rows = (
        session.query(Assets.storage_provider, sa.func.count(Assets.id), sa.func.coalesce(sa.func.sum(Assets.file_size), 0))
        .filter(Assets.group_id == group_id, Assets.storage_provider != location)
        .group_by(Assets.storage_provider)
        .all()
    )
    code = workspace_code(session, group_id)
    embedding = (
        session.query(sa.func.count(Entries.id)).filter(Entries.group_id == group_id, sa.cast(Entries.data_json, sa.Text).like(f"%{code}/%")).scalar()
        or 0
    )
    from marvin.db.models.groups.storage_settings import WorkspaceStorageSettingsModel

    row = session.query(WorkspaceStorageSettingsModel).filter_by(group_id=group_id).one_or_none()
    uploads_here = bool(row and row.credential_mode == ws.MODE_WORKSPACE and str(row.active_connection_id) == str(conn.id))
    return {
        "connection_id": str(conn.id),
        "location": location,
        "files": int(sum(n for _, n, _ in rows)),
        "bytes": int(sum(b for _, _, b in rows)),
        "by_location": [{"location": loc, "files": int(n), "bytes": int(b)} for loc, n, b in rows],
        "entries_with_links": int(embedding),
        "uploads_go_here": uploads_here,
        "ready": conn.status == ws.STATUS_OK,
    }


def start_copy(session, group_id, user_id, connection_id, *, verify: bool = True):
    """Copy the workspace's files into a verified connection in the background: a workspace scheduled task (never on
    a schedule, run now) whose history shows the outcome. Returns the task."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    conn = get_connection(session, group_id, connection_id)
    if (conn.purpose or ws.PURPOSE_ASSETS) != ws.PURPOSE_ASSETS:
        raise WorkspaceStorageError("That bucket is for backups: files are only copied into a file bucket")
    if conn.status != ws.STATUS_OK:
        raise WorkspaceStorageError("Check the connection first: files are only copied into a verified bucket")
    if not ws.policy(session).allowed:
        raise WorkspaceStorageError("The platform doesn't allow workspace storage")
    slug = f"copy-to-bucket-{str(conn.id)[:8]}"
    task = session.query(ScheduledTaskModel).filter_by(group_id=group_id, slug=slug).one_or_none()
    name = f"Copy files to {conn.label or 'own bucket'}"
    if task is None:
        task = ScheduledTaskModel(
            session=session,
            group_id=group_id,
            name=name,
            slug=slug,
            description="Copies this workspace's existing files into its own bucket (Workspace settings → Storage). Originals are kept.",
            enabled=False,  # runs only when started from the Storage page (or Run Now)
            schedule_type="once",
            schedule_config={},
            task_type=COPY_TASK_TYPE,
            task_config={},
        )
        session.add(task)
    task.name = name
    task.task_config = {"connection_id": str(conn.id), "verify": bool(verify), "started_by": str(user_id) if user_id else None}
    session.commit()
    workspace = session.get(Groups, group_id)
    return task, workspace


def set_bundle_includes_own_bucket(session, group_id, user_id, include: bool) -> None:
    from marvin.db.models.groups.storage_settings import WorkspaceStorageSettingsModel

    row = session.query(WorkspaceStorageSettingsModel).filter_by(group_id=group_id).one_or_none()
    if row is None:
        row = WorkspaceStorageSettingsModel(session=session, group_id=group_id)
        session.add(row)
    row.bundle_includes_own_bucket, row.updated_by = bool(include), user_id
    session.commit()


def all_workspace_buckets(session) -> list[dict[str, Any]]:
    """Every workspace's bucket connections for platform admins (Admin → Storage, Backup health): which workspace,
    status, whether uploads go there, files in it and whether its bundles include them."""
    import sqlalchemy as sa

    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.storage_settings import WorkspaceStorageConnectionModel, WorkspaceStorageSettingsModel
    from marvin.db.models.platform import Assets

    names = {str(g.id): (g.name, g.slug) for g in session.query(Groups).all()}
    settings = {str(r.group_id): r for r in session.query(WorkspaceStorageSettingsModel).all()}
    files = dict(
        session.query(Assets.storage_provider, sa.func.count(Assets.id))
        .filter(Assets.storage_provider.like(f"{ws.LOCATION_PREFIX}%"))
        .group_by(Assets.storage_provider)
        .all()
    )
    out = []
    for c in session.query(WorkspaceStorageConnectionModel).order_by(WorkspaceStorageConnectionModel.created_at).all():
        row = settings.get(str(c.group_id))
        name, slug = names.get(str(c.group_id), ("?", "?"))
        out.append(
            {
                **connection_view(c),
                "workspace_id": str(c.group_id),
                "workspace": name,
                "workspace_slug": slug,
                "in_use": bool(row and row.credential_mode == ws.MODE_WORKSPACE and str(row.active_connection_id) == str(c.id)),
                "files": int(files.get(ws.location_for(c.id), 0)),
                "in_bundles": bool(row and row.bundle_includes_own_bucket),
            }
        )
    return out


# ── the workspace's own backups (slice 5) ────────────────────────────────────

BACKUP_TASK_TYPE = "backup_to_workspace_bucket"
MAX_BACKUP_KEEP = 90


def set_backup_bucket(session, group_id, user_id, *, connection_id, keep: int | None = None) -> None:
    """Where the workspace's own backups go (a verified backup bucket), or None to stop them; ``keep`` backups stay."""
    from marvin.db.models.groups.storage_settings import WorkspaceStorageSettingsModel

    row = session.query(WorkspaceStorageSettingsModel).filter_by(group_id=group_id).one_or_none()
    if row is None:
        row = WorkspaceStorageSettingsModel(session=session, group_id=group_id)
        session.add(row)
    if connection_id:
        if not ws.policy(session).allowed:
            raise WorkspaceStorageError("The platform doesn't allow workspace storage")
        conn = get_connection(session, group_id, connection_id)
        if (conn.purpose or ws.PURPOSE_ASSETS) != ws.PURPOSE_BACKUPS:
            raise WorkspaceStorageError("That bucket holds the workspace's files: backups need a private bucket of their own")
        if conn.status != ws.STATUS_OK:
            raise WorkspaceStorageError("Check the backup bucket first: backups only go to a verified bucket")
        row.backup_connection_id = conn.id
    else:
        row.backup_connection_id = None
    if keep is not None:
        if not 1 <= int(keep) <= MAX_BACKUP_KEEP:
            raise WorkspaceStorageError(f"Keep between 1 and {MAX_BACKUP_KEEP} backups")
        row.backup_keep = int(keep)
    row.updated_by = user_id
    session.commit()


def _on_demand_task(session, group_id, *, slug: str, name: str, description: str, task_type: str, config: dict):
    """A workspace scheduled task that never runs on a schedule, only when started (Run Now): its history shows how it went."""
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    task = session.query(ScheduledTaskModel).filter_by(group_id=group_id, slug=slug).one_or_none()
    if task is None:
        task = ScheduledTaskModel(
            session=session,
            group_id=group_id,
            name=name,
            slug=slug,
            description=description,
            enabled=False,
            schedule_type="once",
            schedule_config={},
            task_type=task_type,
            task_config={},
        )
        session.add(task)
    task.name, task.task_config = name, config
    session.commit()
    return task


def start_backup(session, group_id, user_id):
    """Back up now: a workspace task that makes the bundle and saves it to the backup bucket. Returns (task, workspace)."""
    from marvin.db.models.groups import Groups

    from .workspace_backups import WorkspaceBackupError, _target

    try:
        _target(session, group_id)
    except WorkspaceBackupError as e:
        raise WorkspaceStorageError(str(e)) from e
    task = _on_demand_task(
        session,
        group_id,
        slug="back-up-to-own-bucket",
        name="Back up to the workspace's bucket",
        description="Saves a backup of this workspace to its own private backup bucket (Workspace settings → Storage).",
        task_type=BACKUP_TASK_TYPE,
        config={"started_by": str(user_id) if user_id else None},
    )
    return task, session.get(Groups, group_id)
