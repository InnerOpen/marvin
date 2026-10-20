"""Migration ``a1d7c35e9f20``: ``listed: false`` on the Social types and the forms (internal is that flag only).

No schema change, so up / down / up is about the data step being safe to run again and the downgrade being a no-op. The data step
sets the flag and removes what is derived from it (collection membership, embeddings). It is checked on both engines (PostgreSQL — the test database,
rolled back after — and a scratch in-memory SQLite).
"""

import importlib.util
import uuid
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

_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_a1d7c35e9f20_*.py"))
_spec = importlib.util.spec_from_file_location("audience_submissions_migration", _PATH)
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


def _world(session):
    """A workspace with a message form (nothing stored: the default), a signup form, a content form (destination entries), a form that
    says audience, and a note; an Inbox-like collection, one naming the contact type, the Trash, and a manual collection."""
    gid = uuid.uuid4()
    session.add(Groups(session=session, id=gid, name=f"mig-{gid.hex[:6]}", slug=f"mig-{gid.hex[:6]}"))
    session.flush()
    caps = {
        "contact": {"submittable": True, "publishable": False},
        "newsletter": {"submittable": True, "submission": {"kind": "signup"}},
        "testimonial": {"submittable": True, "submission": {"destination": "entries"}},
        "workshop": {"submittable": True, "submission": {"destination": "audience"}},
        "note": {"publishable": True, "submittable": False},
        "social-auto-reply": None,  # stored before the flag existed
        "social-reply-log": {"publishable": False, "routable": False},
        "already": {"submittable": True, "listed": False, "submission": {"destination": "audience", "notify": False}},
    }
    types, entries = {}, {}
    for slug, c in caps.items():
        types[slug] = EntryTypes(session=session, group_id=gid, slug=slug, name=slug, schema_json={"fields": []}, capabilities_json=c)
        session.add(types[slug])
    session.flush()
    for slug in caps:
        entries[slug] = Entries(
            session=session, group_id=gid, entry_type_id=types[slug].id, title=slug, slug=f"e-{slug}", status="inbox", data_json={}
        )
        session.add(entries[slug])
    trashed = Entries(session=session, group_id=gid, entry_type_id=types["contact"].id, title="gone", slug="e-gone", status="trashed", data_json={})
    session.add(trashed)
    session.flush()

    def collection(slug, rules, smart=True):
        row = Collections(session=session, group_id=gid, slug=slug, name=slug, is_smart=smart, smart_rules=rules)
        session.add(row)
        session.flush()
        return row

    colls = SimpleNamespace(
        inbox=collection("inbox-x", {"statuses": ["inbox"], "match": "all"}),
        naming=collection("contacts-x", {"entry_types": ["contact"], "match": "all"}),
        trash=collection("trash-x", {"statuses": ["trashed"], "match": "all"}),
        manual=collection("manual-x", None, smart=False),
    )
    for coll in (colls.inbox, colls.naming, colls.manual):
        for e in entries.values():
            session.add(EntryCollections(entry_id=e.id, collection_id=coll.id, sort_order=0))
    session.add(EntryCollections(entry_id=trashed.id, collection_id=colls.trash.id, sort_order=0))
    for e in entries.values():
        session.add(AIEmbeddingModel(session=session, group_id=gid, entity_type="entry", entity_id=e.id, chunk_index=0, chunk_text="t",
                                     embedding=[1.0], model_id="m", dimensions=1))  # fmt: skip
    session.flush()
    return SimpleNamespace(gid=gid, entries=entries, trashed=trashed, colls=colls)


def test_up_down_up_runs_clean_and_the_downgrade_does_nothing(conn):
    session = Session(bind=conn)
    w = _world(session)
    session.flush()
    session.close()
    before = conn.execute(sa.text("select count(*) from entry_collections")).scalar()
    _run(conn, "upgrade")
    after_up = conn.execute(sa.text("select count(*) from entry_collections")).scalar()
    _run(conn, "downgrade")
    assert conn.execute(sa.text("select count(*) from entry_collections")).scalar() == after_up  # nothing to undo
    _run(conn, "upgrade")
    assert conn.execute(sa.text("select count(*) from entry_collections")).scalar() == after_up  # again: nothing more to remove
    assert after_up < before and w.gid


def _flags(conn, gid):
    t = sa.table("entry_types", sa.column("group_id", mig.GUID()), sa.column("slug", sa.String()), sa.column("capabilities_json", sa.JSON()))
    return dict(conn.execute(sa.select(t.c.slug, t.c.capabilities_json).where(t.c.group_id == gid)).all())


def test_the_social_types_and_the_audience_forms_are_flagged_and_nothing_else(conn):
    session = Session(bind=conn)
    w = _world(session)
    session.close()
    for _ in range(2):  # idempotent
        mig.leave_listing(conn)
    caps = _flags(conn, w.gid)
    unlisted = {slug for slug, c in caps.items() if (c or {}).get("listed") is False}
    # the Social types (any workspace), a form that stored nothing, a signup form, a form that says audience, one already unlisted
    assert unlisted == {"social-auto-reply", "social-reply-log", "contact", "newsletter", "workshop", "already"}
    assert "listed" not in (caps["testimonial"] or {}) and "listed" not in (caps["note"] or {})  # destination entries, and an ordinary type
    assert caps["social-reply-log"] == {"publishable": False, "routable": False, "listed": False}  # the other keys are kept
    assert caps["newsletter"] == {"submittable": True, "submission": {"kind": "signup"}, "listed": False}
    assert caps["already"] == {"submittable": True, "listed": False, "submission": {"destination": "audience", "notify": False}}  # as it was


def test_the_entries_of_the_flagged_types_leave_the_status_collections_and_the_index_and_nothing_else(conn):
    session = Session(bind=conn)
    w = _world(session)
    session.close()
    assert {slug for _, slug, _ in mig.types_to_unlist(conn)} >= {"contact", "newsletter", "workshop", "social-auto-reply", "social-reply-log"}
    for _ in range(2):  # idempotent
        mig.leave_listing(conn)
    assert mig.types_to_unlist(conn) == [] or all(slug not in w.entries for _, slug, _ in mig.types_to_unlist(conn))
    session = Session(bind=conn)

    def members(coll):
        return {r[0] for r in session.query(EntryCollections.entry_id).filter_by(collection_id=coll.id)}

    e = w.entries
    stays = {e["testimonial"].id, e["note"].id, e["already"].id}  # "already" was flagged before: this migration doesn't touch its entries
    assert members(w.colls.inbox) == stays  # the content form and the note stay; the newly flagged types leave
    assert members(w.colls.naming) == stays | {e["contact"].id}  # it names contact, so contact stays; the other types leave
    assert members(w.colls.manual) == {x.id for x in e.values()}  # a hand-made collection is a person's
    assert members(w.colls.trash) == {w.trashed.id}  # the Trash keeps a trashed entry
    indexed = {r[0] for r in session.query(AIEmbeddingModel.entity_id).filter_by(group_id=w.gid)}
    assert indexed == stays
    assert session.query(Entries).filter_by(group_id=w.gid).count() == len(e) + 1  # no entry was touched
    assert session.query(EntryTypes).filter_by(group_id=w.gid).count() == len(e)
    session.close()
