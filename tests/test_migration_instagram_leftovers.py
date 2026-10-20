"""Migration ``b8d4e2f61a73``: removes the Instagram plugin's old auto-reply leftovers, and nothing else.

Runs on both engines (PostgreSQL: the test database, in a transaction rolled back after — skipped when the suite's database is
SQLite; and a scratch in-memory SQLite). The data step is idempotent; the downgrade is a no-op.
"""

import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from marvin.db.models import SqlAlchemyBase
from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel
from marvin.db.models.groups.groups import Groups
from marvin.db.models.platform.collections import Collections
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.entry_collections import EntryCollections
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskExecutionLogModel as ScheduledTaskExecutionLog
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_b8d4e2f61a73_*.py"))
_spec = importlib.util.spec_from_file_location("instagram_leftovers_migration", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


@pytest.fixture(scope="module")
def sqlite_engine():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SqlAlchemyBase.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(params=["postgres", "sqlite"])
def conn(request):
    if request.param == "postgres":
        from marvin.db.db_setup import engine

        if engine.dialect.name != "postgresql":
            pytest.skip("the suite's own database is SQLite here; the scratch SQLite case covers it")
    else:
        engine = request.getfixturevalue("sqlite_engine")
    connection = engine.connect()
    outer = connection.begin()
    yield connection
    outer.rollback()
    connection.close()


def _run(conn, step: str) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        getattr(mig, step)()


def _workspace(session, *, plugin_task_config=None):
    """A workspace with the plugin's leftovers (two types with entries, two collections, the auto-reply task with a log) beside content
    that must survive: a note, a rule of Social, the token-refresh task, a hand-made collection that reuses a leftover slug."""
    gid = uuid.uuid4()
    session.add(Groups(session=session, id=gid, name=f"ig-{gid.hex[:6]}", slug=f"ig-{gid.hex[:6]}"))
    session.flush()
    types = {}
    for slug in ("note", "social-auto-reply", "ig-auto-reply", "ig-reply-log"):
        types[slug] = EntryTypes(session=session, group_id=gid, slug=slug, name=slug, schema_json={"fields": []})
        session.add(types[slug])
    session.flush()

    def entry(slug, type_slug, status="published"):
        row = Entries(session=session, group_id=gid, entry_type_id=types[type_slug].id, title=slug, slug=slug, status=status, data_json={})
        session.add(row)
        session.flush()
        return row

    kept = {"note": entry("n1", "note"), "rule": entry("r1", "social-auto-reply")}
    gone = {
        "rule": entry("old-rule", "ig-auto-reply"),
        "draft": entry("old-draft", "ig-auto-reply", "draft"),
        "log": entry("ig-reply-c1", "ig-reply-log"),
    }

    def collection(slug, rules, name=None, smart=True):
        row = Collections(session=session, group_id=gid, slug=slug, name=name or slug, is_smart=smart, smart_rules=rules)
        session.add(row)
        session.flush()
        return row

    responses = collection("social-auto-responses", {"entry_types": ["ig-auto-reply"], "match": "all"}, "Social — Auto-Responses")
    sent = collection("social-sent", {"entry_types": ["ig-reply-log"], "match": "all"}, "Social — Sent")
    other = collection("featured", {"statuses": ["published"], "match": "all"})
    for e in (gone["rule"], gone["draft"]):
        session.add(EntryCollections(entry_id=e.id, collection_id=responses.id, sort_order=0))
    session.add(EntryCollections(entry_id=gone["log"].id, collection_id=sent.id, sort_order=0))
    for e in (kept["note"], kept["rule"], gone["rule"]):  # the old rule also sat in another collection
        session.add(EntryCollections(entry_id=e.id, collection_id=other.id, sort_order=0))
    for e in (kept["note"], gone["rule"], gone["log"]):
        session.add(AIEmbeddingModel(session=session, group_id=gid, entity_type="entry", entity_id=e.id, chunk_index=0, chunk_text="t",
                                     embedding=[1.0], model_id="m", dimensions=1))  # fmt: skip

    def task(slug, task_type, config):
        row = ScheduledTaskModel(session=session, group_id=gid, name=slug, slug=slug, enabled=True, schedule_type="interval",
                                 schedule_config={"interval_seconds": 120}, task_type=task_type, task_config=config)  # fmt: skip
        session.add(row)
        session.flush()
        return row

    auto = task("instagram-auto-reply", "run_integration_action", plugin_task_config or {"integration": "instagram", "action": "auto_reply"})
    refresh = task("instagram-token-refresh", "run_integration_action", {"integration": "instagram", "action": "refresh_token"})
    engine = task("social-engagement", "social_engagement", {})
    session.add(ScheduledTaskExecutionLog(session=session, task_id=auto.id, group_id=gid, status="success", executed_at=datetime.now(UTC)))
    session.flush()
    return SimpleNamespace(gid=gid, kept=kept, gone=gone, responses=responses, sent=sent, other=other, auto=auto, refresh=refresh, engine=engine)


def _count(session, model, **filters):
    return session.query(model).filter_by(**filters).count()


def test_it_removes_exactly_the_plugins_leftovers_and_a_second_run_changes_nothing(conn):
    session = Session(bind=conn)
    w = _workspace(session)
    other = _workspace(session)  # a second workspace is cleaned the same way
    session.flush()
    session.close()

    first = mig.remove_leftovers(conn)
    assert first == {"entries": 6, "entry_types": 4, "collections": 4, "tasks": 2}
    assert mig.remove_leftovers(conn) == {"entries": 0, "entry_types": 0, "collections": 0, "tasks": 0}  # idempotent

    session = Session(bind=conn)
    for ws in (w, other):
        gid = ws.gid
        assert {e.slug for e in session.query(Entries).filter_by(group_id=gid)} == {"n1", "r1"}  # only the Social rule and the note remain
        assert {t.slug for t in session.query(EntryTypes).filter_by(group_id=gid)} == {"note", "social-auto-reply"}
        assert {c.slug for c in session.query(Collections).filter_by(group_id=gid)} == {"featured"}
        assert {t.slug for t in session.query(ScheduledTaskModel).filter_by(group_id=gid)} == {"instagram-token-refresh", "social-engagement"}
        assert session.query(EntryCollections).filter_by(collection_id=ws.other.id).count() == 2  # note and rule stay in their collection
        assert session.query(ScheduledTaskExecutionLog).filter_by(task_id=ws.auto.id).count() == 0
        assert {r[0] for r in session.query(AIEmbeddingModel.entity_id).filter_by(group_id=gid)} == {ws.kept["note"].id}
    assert session.get(ScheduledTaskModel, w.refresh.id).enabled is True  # token refresh is as it was
    session.close()


def test_a_lookalike_is_left_alone(conn):
    """The same slugs on something that is not the plugin's: a collection over other types, and a task with another action."""
    session = Session(bind=conn)
    w = _workspace(session, plugin_task_config={"integration": "x", "action": "something_else"})
    w.responses.smart_rules = {"entry_types": ["note"], "match": "all"}
    w.sent.is_smart = False
    session.flush()
    session.close()

    result = mig.remove_leftovers(conn)
    assert result["collections"] == 0 and result["tasks"] == 0 and result["entry_types"] == 2

    session = Session(bind=conn)
    assert {c.slug for c in session.query(Collections).filter_by(group_id=w.gid)} == {"social-auto-responses", "social-sent", "featured"}
    assert _count(session, ScheduledTaskModel, group_id=w.gid, slug="instagram-auto-reply") == 1
    session.close()


def test_a_workspace_without_them_is_untouched(conn):
    session = Session(bind=conn)
    gid = uuid.uuid4()
    session.add(Groups(session=session, id=gid, name=f"plain-{gid.hex[:6]}", slug=f"plain-{gid.hex[:6]}"))
    session.add(EntryTypes(session=session, group_id=gid, slug="note", name="n", schema_json={"fields": []}))
    session.flush()
    session.close()
    assert mig.remove_leftovers(conn) == {"entries": 0, "entry_types": 0, "collections": 0, "tasks": 0}


def test_upgrade_runs_the_clean_up_and_the_downgrade_is_a_no_op(conn):
    session = Session(bind=conn)
    w = _workspace(session)
    session.flush()
    session.close()
    _run(conn, "upgrade")
    _run(conn, "downgrade")  # nothing to undo
    _run(conn, "upgrade")  # and up again: nothing left to remove
    session = Session(bind=conn)
    assert {e.slug for e in session.query(Entries).filter_by(group_id=w.gid)} == {"n1", "r1"}
    session.close()


def test_the_migration_follows_the_replies_migration_and_is_the_only_head():
    assert (mig.revision, mig.down_revision) == ("b8d4e2f61a73", "ef911a9c1779")
    versions = Path(_PATH).parent
    downs = {
        line.split('"')[1] for p in versions.glob("*.py") for line in p.read_text().splitlines() if line.startswith("down_revision") and '"' in line
    }
    assert "b8d4e2f61a73" not in downs
