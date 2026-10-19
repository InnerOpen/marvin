"""platform smtp and alert connections

Data migration for retiring the platform workspace. Until now Marvin's own mail and alerts borrowed the
`is_platform` workspace: its active SMTP profile sent platform mail when the environment's SMTP_* were incomplete, and
its integrations carried platform alert routes. Both now live in `platform_settings` (`smtp`, `platform_connections`)
with their credentials as platform secrets (`workspace_secrets.group_id` NULL, migration d6896d6a5e2e).

What is copied, so behaviour is unchanged on the day this runs (the workspace's own rows are left untouched, which is
what makes downgrade and `helm rollback` safe):

* **SMTP** — only when the environment's SMTP_* are *not* complete (today the profile sends platform mail only then;
  with a complete environment the environment wins and the profile is left alone). The admin block holds exactly the
  profile's fields that differ from the environment: Admin → Email merges per field over the environment, so a field
  equal to the environment's is the same either way, and a differing one is what the profile was providing. A profile
  field left empty where the environment has a value (e.g. no username while SMTP_USER is set) cannot be expressed as
  "unset"; the merge then takes the environment's, and the migration logs it.
* **The SMTP password** — with `SECRET_BACKEND=database` the Fernet ciphertext moves verbatim into a platform
  `PLATFORM_SMTP_PASSWORD` secret (same key, so no decrypt; precedent 1467f4e1c2f7). With any other backend nothing
  can be copied from here: it is logged, and Admin → Email shows "password missing" until it is entered again.
* **Alert connections** — each integration an alert route (`platform_settings.platform_alerts`) points at, from the
  platform workspace, becomes a `platform_connections` entry with the same id (so routes and delivery statuses need no
  rewrite), carrying its provider, name, config, enabled flag and `secret_ref`. Its credential secret, and every whole
  `{{SLUG}}` secret in a route's arguments, are copied into the platform scope the same way as the SMTP password.

Everything is SQLAlchemy Core with JSON read and written as Python values, so it runs on SQLite and PostgreSQL alike.
Re-running it is harmless: an existing `smtp` block, platform connection or platform secret is never overwritten.

Revision ID: 3442416ae2bd
Revises: d6896d6a5e2e
Create Date: 2026-10-18 22:02:59.614812

"""

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types as mt
from marvin.core.root_logger import get_logger

# revision identifiers, used by Alembic.
revision: str = "3442416ae2bd"
down_revision: str | None = "d6896d6a5e2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = get_logger("alembic.platform_smtp_and_alert_connections")

SMTP_KEY = "smtp"
CONNECTIONS_KEY = "platform_connections"
ALERTS_KEY = "platform_alerts"
PASSWORD_SLUG = "PLATFORM_SMTP_PASSWORD"
_REFERENCE = re.compile(r"^\{\{\s*([A-Za-z0-9_]+)\s*\}\}$")


def _tables():
    groups = sa.table("groups", sa.column("id", mt.GUID()), sa.column("is_platform", sa.Boolean()))
    profiles = sa.table(
        "workspace_smtp_profiles",
        sa.column("group_id", mt.GUID()),
        sa.column("host", sa.String()),
        sa.column("port", sa.Integer()),
        sa.column("username", sa.String()),
        sa.column("secret_ref", sa.String()),
        sa.column("from_name", sa.String()),
        sa.column("from_email", sa.String()),
        sa.column("auth_strategy", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime()),
    )
    integrations = sa.table(
        "integrations",
        sa.column("id", mt.GUID()),
        sa.column("group_id", mt.GUID()),
        sa.column("provider", sa.String()),
        sa.column("name", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("config", sa.JSON()),
        sa.column("secret_ref", sa.String()),
    )
    secrets = sa.table(
        "workspace_secrets",
        sa.column("id", mt.GUID()),
        sa.column("group_id", mt.GUID()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("description", sa.String()),
        sa.column("encrypted_value", sa.Text()),
        sa.column("created_at", sa.DateTime()),
        sa.column("update_at", sa.DateTime()),
    )
    settings = sa.table(
        "platform_settings",
        sa.column("id", mt.GUID()),
        sa.column("key", sa.String()),
        sa.column("value_json", sa.JSON()),
        sa.column("created_at", sa.DateTime()),
        sa.column("update_at", sa.DateTime()),
    )
    return groups, profiles, integrations, secrets, settings


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _env_value(settings, name: str) -> str | None:
    value = getattr(settings, name, None)
    if value is None:
        return None
    value = value.get_secret_value() if hasattr(value, "get_secret_value") else value
    return str(value) if str(value) != "" else None


def smtp_block(profile: dict, env: dict[str, str | None]) -> tuple[dict, list[str]]:
    """The admin block for a profile: only the fields that differ from the environment. Also the fields the profile
    leaves empty while the environment has a value — they can't be copied as "unset"."""
    wanted = {
        "host": profile.get("host"),
        "port": profile.get("port"),
        "username": profile.get("username"),
        "auth_strategy": (profile.get("auth_strategy") or "TLS").upper(),
        "from_name": profile.get("from_name"),
        "from_email": profile.get("from_email"),
    }
    block: dict = {}
    lost: list[str] = []
    for name, value in wanted.items():
        text = None if value in (None, "") else str(value)
        base = env.get(name)
        if text is None:
            if base is not None:
                lost.append(name)
            continue
        if name == "auth_strategy" and base is not None:
            base = base.upper()
        if text == base:
            continue
        block[name] = int(text) if name == "port" else text
    return block, lost


def _setting(bind, settings, key: str):
    return bind.execute(sa.select(settings.c.id, settings.c.value_json).where(settings.c.key == key)).first()


def _write_setting(bind, settings, key: str, value: dict) -> None:
    row = _setting(bind, settings, key)
    if row is None:
        bind.execute(settings.insert().values(id=uuid.uuid4(), key=key, value_json=value, created_at=_now(), update_at=_now()))
    else:
        bind.execute(settings.update().where(settings.c.id == row.id).values(value_json=value, update_at=_now()))


def _copy_secret(bind, secrets, group_id, slug: str, as_slug: str, name: str, backend: str) -> bool:
    """Copy a workspace secret's ciphertext into the platform scope under ``as_slug``. True when the platform scope
    holds it afterwards. Only the database backend stores values in this table; any other is logged."""
    if backend != "database":
        logger.warning(
            f"platform secret {as_slug}: SECRET_BACKEND={backend}, so '{slug}' can't be copied from the migration — enter it again in Admin"
        )
        return False
    if bind.execute(sa.select(secrets.c.id).where(secrets.c.slug == as_slug, secrets.c.group_id.is_(None))).first() is not None:
        return True  # already there: never overwritten
    source = bind.execute(sa.select(secrets.c.encrypted_value).where(secrets.c.slug == slug, secrets.c.group_id == group_id)).first()
    if source is None:
        logger.warning(f"platform secret {as_slug}: workspace secret '{slug}' not found, nothing to copy")
        return False
    bind.execute(
        secrets.insert().values(
            id=uuid.uuid4(),
            group_id=None,
            name=name,
            slug=as_slug,
            description="Copied from the platform workspace when it was retired.",
            encrypted_value=source.encrypted_value,
            created_at=_now(),
            update_at=_now(),
        )
    )
    return True


def _copy_smtp(bind, profiles, secrets, settings, platform_id, settings_obj, backend: str) -> None:
    current = _setting(bind, settings, SMTP_KEY)
    if current is not None and (current.value_json or {}):
        logger.info("platform smtp: an admin block already exists, left as it is")
        return
    if settings_obj.SMTP_ENABLED:
        logger.info("platform smtp: the environment's SMTP_* are complete and win today, so the platform workspace's profile is not copied")
        return
    profile = bind.execute(
        sa.select(profiles).where(profiles.c.group_id == platform_id, profiles.c.is_active.is_(True)).order_by(profiles.c.created_at)
    ).first()
    if profile is None:
        return
    env = {
        "host": _env_value(settings_obj, "SMTP_HOST"),
        "port": _env_value(settings_obj, "SMTP_PORT"),
        "username": _env_value(settings_obj, "SMTP_USER"),
        "auth_strategy": _env_value(settings_obj, "SMTP_AUTH_STRATEGY"),
        "from_name": _env_value(settings_obj, "SMTP_FROM_NAME"),
        "from_email": _env_value(settings_obj, "SMTP_FROM_EMAIL"),
    }
    block, lost = smtp_block(profile._asdict(), env)
    if lost:
        logger.warning(f"platform smtp: the profile leaves {', '.join(lost)} empty where the environment has a value; the environment's applies")
    if profile.secret_ref and _copy_secret(bind, secrets, platform_id, profile.secret_ref, PASSWORD_SLUG, "Platform SMTP password", backend):
        block["password_ref"] = PASSWORD_SLUG
    if block:
        _write_setting(bind, settings, SMTP_KEY, block)
        logger.info(f"platform smtp: copied {sorted(block)} from the platform workspace's active profile")


def _copy_connections(bind, integrations, secrets, settings, platform_id, backend: str) -> None:
    alerts = _setting(bind, settings, ALERTS_KEY)
    routes = ((alerts.value_json if alerts else None) or {}).get("routes") or []
    wanted: list[str] = []
    arg_slugs: list[str] = []
    for route in routes:
        if isinstance(route, dict) and route.get("integration_id") and str(route["integration_id"]) not in wanted:
            wanted.append(str(route["integration_id"]))
        for value in ((route or {}).get("args") or {}).values() if isinstance(route, dict) else ():
            match = _REFERENCE.match(value.strip()) if isinstance(value, str) else None
            if match and match.group(1) not in arg_slugs:
                arg_slugs.append(match.group(1))
    if not wanted:
        return
    existing = _setting(bind, settings, CONNECTIONS_KEY)
    connections = list(((existing.value_json if existing else None) or {}).get("connections") or [])
    have = {str(c.get("id")) for c in connections if isinstance(c, dict)}
    added = 0
    for raw_id in wanted:
        if raw_id in have:
            continue
        try:
            integration_id = uuid.UUID(raw_id)
        except ValueError:
            logger.warning(f"platform connections: route points at '{raw_id}', not an id")
            continue
        row = bind.execute(sa.select(integrations).where(integrations.c.id == integration_id, integrations.c.group_id == platform_id)).first()
        if row is None:
            logger.warning(f"platform connections: route points at integration {raw_id}, which isn't in the platform workspace; not copied")
            continue
        if row.secret_ref:
            _copy_secret(bind, secrets, platform_id, row.secret_ref, row.secret_ref, f"Platform channel · {row.name}", backend)
        connections.append(
            {
                "id": raw_id,
                "provider": row.provider,
                "name": row.name,
                "config": dict(row.config or {}),
                "secret_ref": row.secret_ref or None,
                "enabled": bool(row.enabled),
            }
        )
        added += 1
    for slug in arg_slugs:
        _copy_secret(bind, secrets, platform_id, slug, slug, f"Platform route argument · {slug}", backend)
    if added:
        _write_setting(bind, settings, CONNECTIONS_KEY, {"connections": connections})
        logger.info(f"platform connections: copied {added} integration(s) from the platform workspace")


def upgrade() -> None:
    from marvin.core.config import get_app_settings

    bind = op.get_bind()
    groups, profiles, integrations, secrets, settings = _tables()
    platform = bind.execute(sa.select(groups.c.id).where(groups.c.is_platform.is_(True))).first()
    if platform is None:
        logger.info("platform smtp / connections: no platform workspace, nothing to copy")
        return
    app_settings = get_app_settings()
    backend = (app_settings.SECRET_BACKEND or "database").lower()
    _copy_smtp(bind, profiles, secrets, settings, platform.id, app_settings, backend)
    _copy_connections(bind, integrations, secrets, settings, platform.id, backend)


def downgrade() -> None:
    # The platform workspace's own rows were never touched, so removing the copies is the whole rollback.
    bind = op.get_bind()
    _, _, _, secrets, settings = _tables()
    bind.execute(settings.delete().where(settings.c.key.in_([SMTP_KEY, CONNECTIONS_KEY])))
    bind.execute(secrets.delete().where(secrets.c.group_id.is_(None)))
