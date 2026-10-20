"""Migration ``c4e8a2d19f57``: remove the Buttondown plugin's two smart collections (only where they are still exactly the plugin's) and
set ``submission.kind: signup`` on the entry type Buttondown was applied with.

A data migration: up / down / up is about it being safe to run again and the downgrade doing nothing. Checked on both engines
(PostgreSQL, the test database, rolled back after; and a scratch in-memory SQLite).
"""

import importlib.util
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from marvin.db.models import SqlAlchemyBase
from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.groups import Groups
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.platform.collections import Collections
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.entry_collections import EntryCollections
from marvin.db.models.platform.entry_types import EntryTypes

_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_c4e8a2d19f57_*.py"))
_spec = importlib.util.spec_from_file_location("audience_subscribers_migration", _PATH)
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


def _group(session):
    gid = uuid.uuid4()
    session.add(Groups(session=session, id=gid, name=f"mig-{gid.hex[:6]}", slug=f"mig-{gid.hex[:6]}"))
    session.flush()
    return gid


RULES = {"entry_types": ["newsletter"], "statuses": ["published"], "match": "all"}


def _collection(session, gid, slug="confirmed-subscribers", name="Confirmed subscribers", rules=RULES, **over):
    row = Collections(
        session=session,
        group_id=gid,
        slug=slug,
        name=name,
        **{"is_smart": True, "is_public": False, "smart_rules": dict(rules) if rules is not None else None, **over},
    )
    session.add(row)
    session.flush()
    return row


def _exists(conn, collection_id) -> bool:
    return (
        conn.execute(
            sa.text("select count(*) from collections where id = :i"), {"i": collection_id.hex if conn.dialect.name == "sqlite" else collection_id}
        ).scalar()
        > 0
    )


def _count(conn, gid, table="collections") -> int:
    return conn.execute(
        sa.text(f"select count(*) from {table} where group_id = :g"), {"g": gid.hex if conn.dialect.name == "sqlite" else gid}
    ).scalar()


# ── the collections ─────────────────────────────────────────────────────────────────────────────────────────────


def test_the_plugins_two_collections_are_removed_with_their_membership_and_no_entry_is_touched(conn):
    session = Session(bind=conn)
    gid = _group(session)
    etype = EntryTypes(
        session=session, group_id=gid, slug="newsletter", name="n", schema_json={"fields": []}, capabilities_json={"submittable": True}
    )
    session.add(etype)
    session.flush()
    entry = Entries(session=session, group_id=gid, entry_type_id=etype.id, title="a", slug="a", status="published", data_json={})
    session.add(entry)
    session.flush()
    confirmed = _collection(session, gid)
    gone = _collection(
        session,
        gid,
        "unsubscribed",
        "Unsubscribed",
        {"entry_types": ["newsletter"], "statuses": ["archived"], "match": "all"},
        source_blueprint="unsubscribed",
    )
    keep = _collection(session, gid, "inbox-x", "Inbox X", {"statuses": ["inbox"], "match": "all"})
    for c in (confirmed, gone, keep):
        session.add(EntryCollections(entry_id=entry.id, collection_id=c.id, sort_order=0))
    session.flush()
    session.close()
    for _ in range(2):  # idempotent
        _run(conn, "upgrade")
    assert not _exists(conn, confirmed.id) and not _exists(conn, gone.id) and _exists(conn, keep.id)
    assert _count(conn, gid) == 1 and _count(conn, gid, "entries") == 1
    links = conn.execute(sa.text("select count(*) from entry_collections")).scalar()
    _run(conn, "downgrade")  # nothing to undo
    assert conn.execute(sa.text("select count(*) from entry_collections")).scalar() == links and not _exists(conn, confirmed.id)
    _run(conn, "upgrade")
    assert _count(conn, gid) == 1


LOOKALIKES = {
    "renamed": {"name": "Our readers"},
    "public": {"is_public": True},
    "an extra rule": {"rules": {**RULES, "published_within_days": 30}},
    "another status": {"rules": {**RULES, "statuses": ["archived"]}},
    "two statuses": {"rules": {**RULES, "statuses": ["published", "archived"]}},
    "two types": {"rules": {**RULES, "entry_types": ["newsletter", "other"]}},
    "no type rule": {"rules": {"statuses": ["published"], "match": "all"}},
    "any, not all": {"rules": {**RULES, "match": "any"}},
    "a manual collection": {"is_smart": False, "rules": None},
    "an asset collection": {"target_type": "asset"},
    "installed from another blueprint": {"source_blueprint": "something-else"},
}


@pytest.mark.parametrize("what", sorted(LOOKALIKES))
def test_a_lookalike_under_the_plugins_slug_is_left_alone(conn, what):
    session = Session(bind=conn)
    gid = _group(session)
    over = dict(LOOKALIKES[what])
    row = _collection(session, gid, **over)
    session.close()
    _run(conn, "upgrade")
    assert _exists(conn, row.id)


def test_the_other_slug_and_the_same_rules_under_another_slug_are_left_alone(conn):
    session = Session(bind=conn)
    gid = _group(session)
    # the unsubscribed slug with the confirmed rules (published), and the confirmed rules under a slug that isn't the plugin's
    mismatched = _collection(session, gid, "unsubscribed", "Unsubscribed")
    elsewhere = _collection(session, gid, "my-readers", "Confirmed subscribers")
    session.close()
    _run(conn, "upgrade")
    assert _exists(conn, mismatched.id) and _exists(conn, elsewhere.id)


# ── the signup form ─────────────────────────────────────────────────────────────────────────────────────────────

SUBSCRIBE = {
    "trigger": {"type": "event", "event": "form_submission_received"},
    "conditions": [
        {"field": "entry.entry_type", "op": "eq", "value": "newsletter"},
        {"field": "event.flagged", "op": "neq", "value": True},
    ],
    "actions": [{"kind": "entry", "op": "set_metadata", "metadata": {"a": "b"}}],
}


def _type(session, gid, slug, caps):
    row = EntryTypes(session=session, group_id=gid, slug=slug, name=slug, schema_json={"fields": []}, capabilities_json=caps)
    session.add(row)
    session.flush()
    return row


def _workflow(session, gid, slug, definition, source=None):
    session.add(WorkspaceAutomationModel(session=session, group_id=gid, name=slug, slug=slug, definition=definition, source_blueprint=source))
    session.flush()


def _integration(session, gid, provider="buttondown"):
    session.add(IntegrationModel(session=session, group_id=gid, provider=provider, name=provider, slug=provider, enabled=True, config={}))
    session.flush()


def _caps(conn, gid):
    t = sa.table("entry_types", sa.column("group_id", mig.GUID()), sa.column("slug", sa.String()), sa.column("capabilities_json", sa.JSON()))
    return dict(conn.execute(sa.select(t.c.slug, t.c.capabilities_json).where(t.c.group_id == gid)).all())


FORM = {"submittable": True, "publishable": False, "listed": False}
MARKED = {**FORM, "submission": {"kind": "signup", "destination": "audience"}}


def _world(session):
    """One workspace per way Buttondown can have been applied (and not)."""
    w = {}

    w["subscribe"] = gid = _group(session)  # the subscribe workflow names the form
    _type(session, gid, "newsletter", FORM)
    _workflow(session, gid, "buttondown-subscribe-on-signup", SUBSCRIBE, source="buttondown-subscribe-on-signup")

    w["named_by_blueprint"] = gid = _group(session)  # renamed workflow, but installed from the blueprint
    _type(session, gid, "newsletter", FORM)
    _workflow(session, gid, "my-signup", SUBSCRIBE, source="buttondown-subscribe-on-signup")

    w["other_name"] = gid = _group(session)  # applied with another signup_type; the default type is a different form
    _type(session, gid, "signups", FORM)
    _type(session, gid, "newsletter", FORM)
    _integration(session, gid)
    _workflow(
        session, gid, "buttondown-subscribe-on-signup", {**SUBSCRIBE, "conditions": [{"field": "entry.entry_type", "op": "eq", "value": "signups"}]}
    )

    w["events_only"] = gid = _group(session)  # the subscribe workflow is gone; the confirm workflow's entry step still names the form
    _type(session, gid, "list", FORM)
    _workflow(
        session,
        gid,
        "buttondown-subscriber-confirmed",
        {
            "trigger": {"type": "incoming_webhook", "webhook": "buttondown"},
            "actions": [{"kind": "entry", "op": "publish", "entity_query": {"entry_type": "list"}}],
        },
    )

    w["integration_only"] = gid = _group(session)  # a Buttondown connection and no workflows: the plugin's default type
    _type(session, gid, "newsletter", FORM)
    _integration(session, gid)

    w["no_buttondown"] = gid = _group(session)  # a newsletter form and some other integration: not ours to mark
    _type(session, gid, "newsletter", FORM)
    _integration(session, gid, provider="square")
    _workflow(session, gid, "my-own-subscribe", SUBSCRIBE)  # a person's workflow with the same condition

    w["chosen"] = gid = _group(session)  # a kind someone set is theirs, message included; a destination too
    _type(session, gid, "newsletter", {**FORM, "submission": {"kind": "message", "destination": "entries"}})
    _workflow(session, gid, "buttondown-subscribe-on-signup", SUBSCRIBE)

    w["destination_entries"] = gid = _group(session)  # only the missing key is written
    _type(session, gid, "newsletter", {**FORM, "submission": {"destination": "entries", "notify": False}})
    _workflow(session, gid, "buttondown-subscribe-on-signup", SUBSCRIBE)

    w["not_a_form"] = gid = _group(session)  # the condition names an ordinary type; and a workflow naming a type that isn't there
    _type(session, gid, "newsletter", {"publishable": True})
    _workflow(session, gid, "buttondown-subscribe-on-signup", SUBSCRIBE)
    w["missing_type"] = gid = _group(session)
    _workflow(session, gid, "buttondown-subscribe-on-signup", SUBSCRIBE)
    return w


def test_the_form_buttondown_was_applied_with_is_marked_a_signup_and_nothing_else_is(conn):
    session = Session(bind=conn)
    w = _world(session)
    session.flush()
    session.close()
    for _ in range(2):  # idempotent
        mig.mark_signup_forms(conn)
    c = {name: _caps(conn, gid) for name, gid in w.items()}
    assert c["subscribe"]["newsletter"] == MARKED
    assert c["named_by_blueprint"]["newsletter"] == MARKED
    assert c["other_name"]["signups"] == MARKED and c["other_name"]["newsletter"] == FORM  # the named form, not the default one
    assert c["events_only"]["list"] == MARKED
    assert c["integration_only"]["newsletter"] == MARKED
    assert c["no_buttondown"]["newsletter"] == FORM
    assert c["chosen"]["newsletter"] == {**FORM, "submission": {"kind": "message", "destination": "entries"}}
    assert c["destination_entries"]["newsletter"] == {**FORM, "submission": {"destination": "entries", "notify": False, "kind": "signup"}}
    assert c["not_a_form"]["newsletter"] == {"publishable": True} and c["missing_type"] == {}


def test_up_down_up_runs_clean_on_both_halves_and_the_downgrade_does_nothing(conn):
    session = Session(bind=conn)
    w = _world(session)
    _collection(session, w["subscribe"])
    session.flush()
    session.close()
    _run(conn, "upgrade")
    after = _caps(conn, w["subscribe"])
    assert after["newsletter"] == MARKED and _count(conn, w["subscribe"]) == 0
    _run(conn, "downgrade")
    assert _caps(conn, w["subscribe"]) == after  # the flag is data: not undone
    _run(conn, "upgrade")
    assert _caps(conn, w["subscribe"]) == after


def test_the_helpers_read_the_names_the_workflows_carry():
    assert mig.named_entry_types(SUBSCRIBE) == ["newsletter"]
    assert (
        mig.named_entry_types(
            {"conditions": [{"field": "entry.entry_type", "op": "neq", "value": "x"}, {"field": "event.x", "op": "eq", "value": "y"}]}
        )
        == []
    )
    assert mig.named_entry_types(None) == [] and mig.named_entry_types({"conditions": "bad"}) == []
    assert mig.queried_entry_types({"actions": [{"entity_query": {"entry_type": "list"}}, {"op": "x"}, {"entity_query": {}}]}) == ["list"]
