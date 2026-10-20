"""Migration ``ef911a9c1779``: replies recorded on inbox items, internal Social entry types, the retired Social collections.

Schema: up, down, up on both engines (PostgreSQL — the test database, DDL is transactional so each case rolls back — and a
scratch in-memory SQLite). Data: the steps move nothing of anyone's content and are safe to run twice.
"""

import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from marvin.db.models import SqlAlchemyBase
from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel
from marvin.db.models.groups.groups import Groups
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.groups.social_inbox import SocialInboxItemModel as Item
from marvin.db.models.platform.collections import Collections
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.entry_collections import EntryCollections
from marvin.db.models.platform.entry_types import EntryTypes

TABLE = "social_inbox_items"
NEW_COLUMNS = {"reply_rule", "reply_text", "reply_note"}
_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_ef911a9c1779_*.py"))
_spec = importlib.util.spec_from_file_location("social_replies_migration", _PATH)
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
    """The database as it is at head, in a transaction rolled back after."""
    if request.param == "postgres":
        from marvin.db.db_setup import engine

        if engine.dialect.name != "postgresql":
            pytest.skip("the suite's own database is SQLite here (no transactional DDL); the scratch SQLite case covers it")
    else:
        engine = request.getfixturevalue("sqlite_engine")
    connection = engine.connect()
    outer = connection.begin()
    yield connection
    outer.rollback()
    connection.close()
    if request.param == "sqlite":  # SQLite's DDL isn't rolled back: put the columns back for the next case
        with engine.begin() as c:
            have = {col["name"] for col in sa.inspect(c).get_columns(TABLE)}
            for name in NEW_COLUMNS - have:
                c.execute(sa.text(f"ALTER TABLE {TABLE} ADD COLUMN {name} {'TEXT' if name == 'reply_text' else 'VARCHAR'}"))


def _run(conn, step: str) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        getattr(mig, step)()


def _columns(conn) -> set[str]:
    return {c["name"] for c in sa.inspect(conn).get_columns(TABLE)}


def test_up_down_up_adds_and_drops_the_three_columns_the_model_declares(conn):
    assert NEW_COLUMNS <= _columns(conn)
    declared = {c.name: c.nullable for c in Item.__table__.columns}
    _run(conn, "downgrade")
    assert not (NEW_COLUMNS & _columns(conn))
    _run(conn, "upgrade")
    after = {c["name"]: c["nullable"] for c in sa.inspect(conn).get_columns(TABLE)}
    assert after == declared  # the table the model declares, the new columns nullable
    _run(conn, "downgrade")
    _run(conn, "upgrade")
    assert NEW_COLUMNS <= _columns(conn)


def _world(session):
    """A workspace with: a note, an internal rule and log entry, a collection that names the rule type, a status collection, the two
    retired collections (one pristine and empty, one holding entries), embeddings and an item answered under the old log."""
    gid = uuid.uuid4()
    session.add(Groups(session=session, id=gid, name=f"mig-{gid.hex[:6]}", slug=f"mig-{gid.hex[:6]}"))
    session.flush()
    types = {}
    for slug in ("note", "social-auto-reply", "social-reply-log"):
        types[slug] = EntryTypes(session=session, group_id=gid, slug=slug, name=slug, schema_json={"fields": []})
        session.add(types[slug])
    session.flush()

    def entry(slug, type_slug, data=None):
        row = Entries(
            session=session, group_id=gid, entry_type_id=types[type_slug].id, title=slug, slug=slug, status="published", data_json=data or {}
        )
        session.add(row)
        session.flush()
        return row

    note, rule = entry("n1", "note"), entry("r1", "social-auto-reply", {"keywords": "price", "reply": "x"})
    log = entry("log1", "social-reply-log", {"rule": "r1", "reply": "Check the link", "error": "half failed"})
    person = entry("log2", "social-reply-log", {"rule": "inbox", "reply": "by hand"})

    def collection(slug, name, rules, smart=True):
        row = Collections(session=session, group_id=gid, slug=slug, name=name, is_smart=smart, smart_rules=rules)
        session.add(row)
        session.flush()
        return row

    published = collection("published-x", "Published", {"statuses": ["published"], "match": "all"})
    naming = collection("rules-x", "Rules", {"entry_types": ["social-auto-reply"], "match": "all"})
    pristine = collection("social-auto-reply-rules", "Social — Auto-reply rules", {"entry_types": ["social-auto-reply"], "match": "all"})
    busy = collection("social-replies", "Social — Replies", {"entry_types": ["social-reply-log"], "match": "all"})
    manual = collection("manual-x", "Manual", None, smart=False)
    for coll in (published, naming, manual):
        for e in (note, rule):
            session.add(EntryCollections(entry_id=e.id, collection_id=coll.id, sort_order=0))
    session.add(EntryCollections(entry_id=log.id, collection_id=busy.id, sort_order=0))
    for e in (note, rule):
        session.add(AIEmbeddingModel(session=session, group_id=gid, entity_type="entry", entity_id=e.id, chunk_index=0, chunk_text="t",
                                     embedding=[1.0], model_id="m", dimensions=1))  # fmt: skip
    session.flush()
    return SimpleNamespace_(gid=gid, note=note, rule=rule, log=log, person=person, published=published, naming=naming, pristine=pristine,
                            busy=busy, manual=manual)  # fmt: skip


class SimpleNamespace_:  # noqa: N801
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _item(session, gid, slug, item_id):
    now = datetime.now(UTC)
    integration = session.query(IntegrationModel).filter_by(group_id=gid, slug="i").first()
    if integration is None:
        integration = IntegrationModel(session=session, group_id=gid, provider="x", name="i", slug="i", enabled=True)
        session.add(integration)
        session.flush()
    row = Item(session=session, group_id=gid, integration_id=integration.id, integration_slug="i", network="x", item_id=item_id, kind="comment",
               text="hi", posted_at=now, first_seen_at=now, reply_log_slug=slug, replied_at=now)  # fmt: skip
    session.add(row)
    session.flush()
    return row


def test_the_data_steps_leave_internal_entries_out_of_status_collections_and_the_index_and_retire_the_collections(conn):
    session = Session(bind=conn)
    w = _world(session)
    first, second = _item(session, w.gid, "log1", "c1"), _item(session, w.gid, "log2", "c2")
    session.flush()
    session.close()
    for _ in range(2):  # twice: it must be idempotent
        bind = conn
        mig._backfill_replies(bind)
        mig._leave_collections(bind)
        mig._purge_embeddings(bind)
        mig._retire_collections(bind)
    session = Session(bind=conn)

    def members(coll):
        return {r[0] for r in session.query(EntryCollections.entry_id).filter_by(collection_id=coll.id)}

    assert members(w.published) == {w.note.id}  # the rule left a status collection
    assert members(w.naming) == {w.note.id, w.rule.id}  # a collection that names the type keeps it
    assert members(w.manual) == {w.note.id, w.rule.id}  # a hand-made collection is a person's: only smart (derived) membership is cleaned
    assert {r[0] for r in session.query(AIEmbeddingModel.entity_id).filter_by(group_id=w.gid)} == {w.note.id}  # the rule left the index
    assert session.query(Entries).filter_by(group_id=w.gid).count() == 4  # no entry was touched
    # the retired collections: the pristine empty one is gone, the one holding entries is hidden from the sidebar
    assert session.query(Collections).filter_by(group_id=w.gid, slug="social-auto-reply-rules").first() is None
    busy = session.query(Collections).filter_by(group_id=w.gid, slug="social-replies").one()
    assert busy.in_sidebar is False and members(busy) == {w.log.id}
    # answered items got what the log entry said
    session.expire_all()
    one, two = session.get(Item, first.id), session.get(Item, second.id)
    assert (one.reply_rule, one.reply_text, one.reply_note) == ("r1", "Check the link", "half failed")
    assert (two.reply_rule, two.reply_text) == (None, "by hand")  # "inbox" was a person's reply: it has no rule
    session.close()
