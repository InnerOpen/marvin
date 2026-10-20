"""automation results: the table, and the n8n plugin's collections and entry metadata folded into it

Schema (additive):
  - ``automation_results`` — one row per hand-off of work to another system: the entry, the connection, the Marvin workflow that
    handed it off, what was asked (``target``), the run on the other side (``remote_id``, ``remote_url``), a status in Marvin's words
    (in_flight | succeeded | failed), a message, when it was sent and finished, and the attempt. Deleted with the workspace, the
    connection and the entry; a daily system task (``prune_automation_results``) trims it.

Data (a one-time clean-up of what the n8n plugin kept before there was a table; idempotent, plain statements, no model code):

  * removes the plugin's two smart collections, ``n8n-failed`` named "n8n: failed" and ``n8n-in-flight`` named "n8n: in flight",
    where each is still exactly what the plugin created: a smart entry collection, private, that nobody installed from another
    blueprint, whose rules are exactly the plugin's (``metadata.n8n_status`` eq ``error``, or in ``sent`` / ``waiting``). Anything
    else under those slugs (a renamed or public one, an extra rule, another status, a manual collection) is a person's own and is
    left alone. Their membership rows go with them; no entry is touched;
  * turns each entry's ``n8n_*`` metadata (``n8n_status``, ``n8n_execution_id``, ``n8n_workflow``, ``n8n_finished_at``,
    ``n8n_message``) into one result, then removes those keys: ``sent`` and ``waiting`` become in flight, ``success`` succeeded and
    ``error`` failed; a missing or unknown status is in flight with the word in its message, so nothing is guessed to have worked.
    The result is attached to the workspace's ``n8n`` connection when there is exactly one (a wrong connection is worse than none).
    Its time is the finish time n8n reported, else when the entry last changed (the best Marvin knows: the plugin never kept when it
    was sent), so an old "sent" with no report shows as No reply. Such a result has no Marvin workflow, so it cannot be retried.

The downgrade drops the table. It does not put the collections or the entry metadata back: they were derived from reports n8n can
send again, and the results are the record now.

Revision ID: d3b9f27a6c14
Revises: c4e8a2d19f57
Create Date: 2026-10-25 09:00:00

"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

import marvin.db.migration_types

# revision identifiers, used by Alembic.
revision: str = "d3b9f27a6c14"
down_revision: str | None = "c4e8a2d19f57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUID = marvin.db.migration_types.GUID

# the plugin's collections: slug -> (name, the one rule it asks for)
COLLECTIONS = {
    "n8n-failed": ("n8n: failed", {"op": "eq", "value": "error"}),
    "n8n-in-flight": ("n8n: in flight", {"op": "in", "value": ["sent", "waiting"]}),
}
STATUS_KEY, EXECUTION_KEY, WORKFLOW_KEY, FINISHED_KEY, MESSAGE_KEY = (
    "n8n_status",
    "n8n_execution_id",
    "n8n_workflow",
    "n8n_finished_at",
    "n8n_message",
)
KEYS = (STATUS_KEY, EXECUTION_KEY, WORKFLOW_KEY, FINISHED_KEY, MESSAGE_KEY)
STATUSES = {"sent": "in_flight", "waiting": "in_flight", "success": "succeeded", "error": "failed"}
PROVIDER = "n8n"
FIELD_MAX = 2000


def upgrade() -> None:
    op.create_table(
        "automation_results",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("group_id", GUID(), nullable=False),
        sa.Column("entry_id", GUID(), nullable=True),
        sa.Column("integration_id", GUID(), nullable=True),
        sa.Column("workflow_id", GUID(), nullable=True),
        sa.Column("action", sa.String(), nullable=True),
        sa.Column("target", sa.String(), nullable=True),
        sa.Column("remote_id", sa.String(), nullable=True),
        sa.Column("remote_url", sa.String(), nullable=True),
        sa.Column("status", sa.String(), server_default="in_flight", nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("sent_at", marvin.db.migration_types.AwareDateTime(), nullable=False),
        sa.Column("finished_at", marvin.db.migration_types.AwareDateTime(), nullable=True),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("dismissed_at", marvin.db.migration_types.AwareDateTime(), nullable=True),
        sa.Column("dismissed_by", GUID(), nullable=True),
        sa.Column("created_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.Column("update_at", marvin.db.migration_types.NaiveDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entry_id"], ["entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["integration_id"], ["integrations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workspace_automations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["dismissed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("automation_results", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_automation_results_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_automation_results_group_id"), ["group_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_automation_results_entry_id"), ["entry_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_automation_results_integration_id"), ["integration_id"], unique=False)
        batch_op.create_index("ix_automation_results_group_status", ["group_id", "status"], unique=False)
        batch_op.create_index("ix_automation_results_group_sent", ["group_id", "sent_at"], unique=False)
        batch_op.create_index("ix_automation_results_remote", ["integration_id", "remote_id"], unique=False)

    bind = op.get_bind()
    remove_collections(bind)
    import_entry_metadata(bind)


def downgrade() -> None:
    """Drops the table. The collections and the entry metadata are not put back (see the module docstring)."""
    with op.batch_alter_table("automation_results", schema=None) as batch_op:
        batch_op.drop_index("ix_automation_results_remote")
        batch_op.drop_index("ix_automation_results_group_sent")
        batch_op.drop_index("ix_automation_results_group_status")
        batch_op.drop_index(batch_op.f("ix_automation_results_integration_id"))
        batch_op.drop_index(batch_op.f("ix_automation_results_entry_id"))
        batch_op.drop_index(batch_op.f("ix_automation_results_group_id"))
        batch_op.drop_index(batch_op.f("ix_automation_results_created_at"))

    op.drop_table("automation_results")


def _tables():
    id_ = lambda: sa.column("id", GUID())  # noqa: E731
    return {
        "collections": sa.table(
            "collections",
            id_(),
            sa.column("slug", sa.String()),
            sa.column("name", sa.String()),
            sa.column("is_smart", sa.Boolean()),
            sa.column("is_public", sa.Boolean()),
            sa.column("target_type", sa.String()),
            sa.column("smart_rules", sa.JSON()),
            sa.column("source_blueprint", sa.String()),
        ),
        "collection_children": [
            sa.table(name, sa.column("collection_id", GUID())) for name in ("entry_collections", "collection_assets", "collection_resources")
        ],
        "entries": sa.table(
            "entries",
            id_(),
            sa.column("group_id", GUID()),
            sa.column("metadata_json", sa.JSON()),
            sa.column("created_at", marvin.db.migration_types.NaiveDateTime()),
            sa.column("update_at", marvin.db.migration_types.NaiveDateTime()),
        ),
        "integrations": sa.table(
            "integrations", id_(), sa.column("group_id", GUID()), sa.column("provider", sa.String()), sa.column("slug", sa.String())
        ),
        "results": sa.table(
            "automation_results",
            id_(),
            sa.column("group_id", GUID()),
            sa.column("entry_id", GUID()),
            sa.column("integration_id", GUID()),
            sa.column("target", sa.String()),
            sa.column("remote_id", sa.String()),
            sa.column("status", sa.String()),
            sa.column("message", sa.Text()),
            sa.column("sent_at", marvin.db.migration_types.AwareDateTime()),
            sa.column("finished_at", marvin.db.migration_types.AwareDateTime()),
            sa.column("attempt", sa.Integer()),
            sa.column("created_at", marvin.db.migration_types.NaiveDateTime()),
            sa.column("update_at", marvin.db.migration_types.NaiveDateTime()),
        ),
    }  # fmt: skip


def is_plugin_collection(slug, name, is_smart, is_public, target_type, rules, source_blueprint) -> bool:
    """Whether a row under one of the plugin's slugs is still exactly what the plugin created."""
    expected_name, condition = COLLECTIONS[slug]
    if name != expected_name or is_smart is not True or is_public is not False or (target_type or "entry") != "entry":
        return False
    if source_blueprint not in (None, slug):
        return False
    if not isinstance(rules, dict) or set(rules) != {"where", "match"} or rules["match"] != "all":
        return False
    where = rules["where"]
    return where == [{"field": f"metadata.{STATUS_KEY}", **condition}]


def remove_collections(bind) -> int:
    """Remove the plugin's two collections where they are still its own; returns how many."""
    t = _tables()
    coll = t["collections"]
    rows = bind.execute(
        sa.select(
            coll.c.id, coll.c.slug, coll.c.name, coll.c.is_smart, coll.c.is_public, coll.c.target_type, coll.c.smart_rules, coll.c.source_blueprint
        ).where(coll.c.slug.in_(list(COLLECTIONS)))
    ).all()
    ids = [cid for cid, *rest in rows if is_plugin_collection(*rest)]
    for chunk in _chunks(ids):
        for child in t["collection_children"]:
            bind.execute(child.delete().where(child.c.collection_id.in_(chunk)))
        bind.execute(coll.delete().where(coll.c.id.in_(chunk)))
    return len(ids)


def _text(value) -> str | None:
    return None if value in (None, "") else str(value)[:FIELD_MAX]


def _moment(value, fallback: datetime | None) -> datetime:
    """The time n8n reported (ISO 8601, with or without a zone), else ``fallback`` (when the entry last changed), else now; always aware."""
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    if fallback is not None:
        return fallback if fallback.tzinfo else fallback.replace(tzinfo=UTC)
    return datetime.now(UTC)


def import_entry_metadata(bind) -> int:
    """Turn each entry's ``n8n_*`` metadata into one result, then remove the keys; returns how many results were made."""
    t = _tables()
    entries, results, ints = t["entries"], t["results"], t["integrations"]
    connection: dict = {}
    for group_id, integration_id in bind.execute(sa.select(ints.c.group_id, ints.c.id).where(ints.c.provider == PROVIDER)).all():
        connection[group_id] = None if group_id in connection else integration_id  # two n8n connections: which one is not known
    rows = bind.execute(
        sa.select(entries.c.id, entries.c.group_id, entries.c.metadata_json, entries.c.update_at, entries.c.created_at).where(
            sa.cast(entries.c.metadata_json, sa.Text).like('%"n8n\\_%', escape="\\")
        )
    ).all()
    made = 0
    for entry_id, group_id, metadata, changed_at, created_at in rows:
        if not isinstance(metadata, dict) or not any(key in metadata for key in KEYS):
            continue
        word = str(metadata.get(STATUS_KEY) or "").strip().lower()
        status = STATUSES.get(word, "in_flight")
        message = _text(metadata.get(MESSAGE_KEY))
        if word and word not in STATUSES:
            message = f"Imported with the status “{word}”" + (f": {message}" if message else "")
        happened = _moment(metadata.get(FINISHED_KEY), changed_at or created_at)
        stamp = _moment(None, changed_at or created_at)
        bind.execute(
            results.insert().values(
                id=uuid.uuid4(),
                group_id=group_id,
                entry_id=entry_id,
                integration_id=connection.get(group_id),
                target=_text(metadata.get(WORKFLOW_KEY)),
                remote_id=_text(metadata.get(EXECUTION_KEY)),
                status=status,
                message=message,
                sent_at=stamp if status == "in_flight" else happened,
                finished_at=None if status == "in_flight" else happened,
                attempt=1,
                created_at=datetime.now(UTC).replace(tzinfo=None),
                update_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        made += 1
        kept = {k: v for k, v in metadata.items() if k not in KEYS}
        bind.execute(entries.update().where(entries.c.id == entry_id).values(metadata_json=kept))
    return made


def _chunks(items: list, size: int = 500):
    for start in range(0, len(items), size):
        yield items[start : start + size]
