"""Migration ``d3b9f27a6c14``: the ``automation_results`` table, the n8n plugin's two smart collections removed (only where they are
still exactly the plugin's), and each entry's ``n8n_*`` metadata turned into one result and removed.

Checked on both engines (PostgreSQL, the test database, rolled back after; and a scratch in-memory SQLite). The data steps run
against the table the suite already has; the schema step is run up / down / up on its own.
"""

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from marvin.db.models import SqlAlchemyBase
from marvin.db.models.groups.groups import Groups
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.platform.collections import Collections
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.entry_collections import EntryCollections
from marvin.db.models.platform.entry_types import EntryTypes

_PATH = next((Path(__file__).resolve().parents[1] / "src" / "marvin" / "alembic" / "versions").glob("*_d3b9f27a6c14_*.py"))
_spec = importlib.util.spec_from_file_location("automation_results_migration", _PATH)
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


def _run(conn, step: str, *args):
    with Operations.context(MigrationContext.configure(conn)):
        return getattr(mig, step)(*args)


def _group(session):
    gid = uuid.uuid4()
    session.add(Groups(session=session, id=gid, name=f"mig-{gid.hex[:6]}", slug=f"mig-{gid.hex[:6]}"))
    session.flush()
    return gid


def _type(session, gid):
    row = EntryTypes(session=session, group_id=gid, slug="post", name="Post", schema_json={"fields": []})
    session.add(row)
    session.flush()
    return row


def _entry(session, gid, etype, slug, metadata, changed_ago=timedelta(days=3)):
    row = Entries(
        session=session, group_id=gid, entry_type_id=etype.id, title=slug, slug=slug, status="published", data_json={}, metadata_json=metadata
    )
    session.add(row)
    session.flush()
    row.update_at = datetime.now(UTC).replace(tzinfo=None) - changed_ago
    session.flush()
    return row


def _n8n(session, gid, slug="n8n"):
    session.add(IntegrationModel(session=session, group_id=gid, provider="n8n", name=slug, slug=slug, enabled=True, config={}))
    session.flush()


def _results(conn, gid):
    rows = conn.execute(
        sa.text(
            "select entry_id, integration_id, target, remote_id, status, message, sent_at, finished_at, attempt, workflow_id from automation_results "
            "where group_id = :g order by target, remote_id"
        ),
        {"g": gid.hex if conn.dialect.name == "sqlite" else gid},
    ).all()
    return rows


def _metadata(session, entry_id):
    session.expire_all()
    return session.get(Entries, entry_id).metadata_json


# ── the collections ─────────────────────────────────────────────────────────────────────────────────────────────

FAILED_RULES = {"where": [{"field": "metadata.n8n_status", "op": "eq", "value": "error"}], "match": "all"}
IN_FLIGHT_RULES = {"where": [{"field": "metadata.n8n_status", "op": "in", "value": ["sent", "waiting"]}], "match": "all"}


def _collection(session, gid, slug="n8n-failed", name="n8n: failed", rules=FAILED_RULES, **over):
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


def test_the_plugins_two_collections_are_removed_with_their_membership_and_no_entry_is_touched(conn):
    session = Session(bind=conn)
    gid = _group(session)
    entry = _entry(session, gid, _type(session, gid), "a", None)
    failed = _collection(session, gid)
    in_flight = _collection(session, gid, "n8n-in-flight", "n8n: in flight", IN_FLIGHT_RULES, source_blueprint="n8n-in-flight")
    keep = _collection(session, gid, "inbox-x", "Inbox X", {"where": [{"field": "status", "op": "eq", "value": "inbox"}], "match": "all"})
    for c in (failed, in_flight, keep):
        session.add(EntryCollections(entry_id=entry.id, collection_id=c.id, sort_order=0))
    session.flush()
    session.close()

    assert _run(conn, "remove_collections", conn) == 2
    assert _run(conn, "remove_collections", conn) == 0  # idempotent

    assert not _exists(conn, failed.id) and not _exists(conn, in_flight.id) and _exists(conn, keep.id)
    assert conn.execute(sa.text("select count(*) from entries")).scalar() >= 1
    assert conn.execute(sa.text("select count(*) from entry_collections")).scalar() == 1


RENAMED_LOOKALIKES = {
    "renamed": {"name": "Our failures"},
    "public": {"is_public": True},
    "an extra rule": {"rules": {**FAILED_RULES, "where": FAILED_RULES["where"] + [{"field": "status", "op": "eq", "value": "published"}]}},
    "another value": {"rules": {"where": [{"field": "metadata.n8n_status", "op": "eq", "value": "success"}], "match": "all"}},
    "another field": {"rules": {"where": [{"field": "metadata.status", "op": "eq", "value": "error"}], "match": "all"}},
    "another operator": {"rules": {"where": [{"field": "metadata.n8n_status", "op": "in", "value": ["error"]}], "match": "all"}},
    "any, not all": {"rules": {**FAILED_RULES, "match": "any"}},
    "an extra key": {"rules": {**FAILED_RULES, "entry_types": ["post"]}},
    "a manual collection": {"is_smart": False, "rules": None},
    "an asset collection": {"target_type": "asset"},
    "installed from another blueprint": {"source_blueprint": "something-else"},
}


@pytest.mark.parametrize("what", sorted(RENAMED_LOOKALIKES))
def test_a_lookalike_under_the_plugins_slug_is_left_alone(conn, what):
    session = Session(bind=conn)
    gid = _group(session)
    row = _collection(session, gid, **dict(RENAMED_LOOKALIKES[what]))
    session.close()

    _run(conn, "remove_collections", conn)

    assert _exists(conn, row.id)


def test_the_other_slugs_rules_and_the_same_rules_under_another_slug_are_left_alone(conn):
    session = Session(bind=conn)
    gid = _group(session)
    mismatched = _collection(session, gid, "n8n-in-flight", "n8n: in flight")  # the in-flight slug with the failed rules
    elsewhere = _collection(session, gid, "my-failures", "n8n: failed")
    session.close()

    _run(conn, "remove_collections", conn)

    assert _exists(conn, mismatched.id) and _exists(conn, elsewhere.id)


# ── the entry metadata ──────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("word", "status"),
    [("sent", "in_flight"), ("waiting", "in_flight"), ("success", "succeeded"), ("error", "failed"), ("SUCCESS", "succeeded")],
)
def test_each_status_n8n_kept_becomes_one_of_marvins_and_the_metadata_is_removed(conn, word, status):
    session = Session(bind=conn)
    gid = _group(session)
    entry = _entry(
        session,
        gid,
        _type(session, gid),
        "a",
        {"n8n_status": word, "n8n_execution_id": "42", "n8n_workflow": "marvin/new-entry", "n8n_message": "ok"},
    )
    session.close()

    assert _run(conn, "import_entry_metadata", conn) == 1

    (row,) = _results(conn, gid)
    assert (row.target, row.remote_id, row.status, row.message, row.attempt, row.workflow_id) == ("marvin/new-entry", "42", status, "ok", 1, None)
    assert str(row.entry_id).replace("-", "") == entry.id.hex
    assert _metadata(Session(bind=conn), entry.id) == {}


def test_the_time_is_what_n8n_reported_else_when_the_entry_last_changed_and_an_in_flight_one_has_no_finish_time(conn):
    session = Session(bind=conn)
    gid = _group(session)
    etype = _type(session, gid)
    _entry(session, gid, etype, "done", {"n8n_status": "success", "n8n_workflow": "a", "n8n_finished_at": "2026-10-01T12:30:00Z"})
    _entry(session, gid, etype, "done-unreadable", {"n8n_status": "error", "n8n_workflow": "b", "n8n_finished_at": "yesterday"}, timedelta(days=2))
    _entry(session, gid, etype, "waiting", {"n8n_status": "sent", "n8n_workflow": "c"}, timedelta(days=5))
    session.close()

    _run(conn, "import_entry_metadata", conn)

    done, unreadable, waiting = _results(conn, gid)
    when = lambda value: value if isinstance(value, datetime) else datetime.fromisoformat(str(value))  # noqa: E731  (SQLite hands back text)
    assert when(done.sent_at) == when(done.finished_at) == datetime(2026, 10, 1, 12, 30, tzinfo=UTC).replace(tzinfo=when(done.sent_at).tzinfo)
    assert abs(when(unreadable.finished_at).replace(tzinfo=None) - (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2))) < timedelta(
        minutes=5
    )
    assert waiting.finished_at is None
    assert abs(when(waiting.sent_at).replace(tzinfo=None) - (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=5))) < timedelta(minutes=5)


def test_an_unknown_or_missing_status_is_in_flight_with_the_word_in_its_message_so_nothing_is_guessed_to_have_worked(conn):
    session = Session(bind=conn)
    gid = _group(session)
    etype = _type(session, gid)
    _entry(session, gid, etype, "odd", {"n8n_status": "crashed", "n8n_workflow": "a", "n8n_message": "boom"})
    _entry(session, gid, etype, "bare", {"n8n_execution_id": "7", "n8n_workflow": "b"})
    session.close()

    _run(conn, "import_entry_metadata", conn)

    odd, bare = _results(conn, gid)
    assert (odd.status, odd.message) == ("in_flight", "Imported with the status “crashed”: boom")
    assert (bare.status, bare.message, bare.remote_id) == ("in_flight", None, "7")


def test_only_the_n8n_keys_are_removed_and_an_entry_without_them_is_left_as_it_is(conn):
    session = Session(bind=conn)
    gid = _group(session)
    etype = _type(session, gid)
    mixed = _entry(session, gid, etype, "mixed", {"n8n_status": "error", "n8n_workflow": "a", "keep": "me", "n8n_other": "x"})
    plain = _entry(session, gid, etype, "plain", {"keep": "me"})
    empty = _entry(session, gid, etype, "empty", None)
    session.close()

    assert _run(conn, "import_entry_metadata", conn) == 1

    check = Session(bind=conn)
    assert _metadata(check, mixed.id) == {"keep": "me", "n8n_other": "x"}
    assert _metadata(check, plain.id) == {"keep": "me"} and _metadata(check, empty.id) is None


def test_the_result_is_attached_to_the_workspaces_n8n_connection_when_there_is_exactly_one_and_a_second_run_finds_nothing(conn):
    session = Session(bind=conn)
    one, two, none = _group(session), _group(session), _group(session)
    _n8n(session, one)
    _n8n(session, two, "n8n")
    _n8n(session, two, "n8n-staging")
    for gid in (one, two, none):
        _entry(session, gid, _type(session, gid), "a", {"n8n_status": "error", "n8n_workflow": "a"})
    ids = {g: session.query(IntegrationModel.id).filter_by(group_id=g).scalar() for g in (one,)}
    session.close()

    assert _run(conn, "import_entry_metadata", conn) == 3
    assert _run(conn, "import_entry_metadata", conn) == 0  # the keys are gone: idempotent

    assert [r.integration_id for r in _results(conn, one)] != [None]
    assert str(_results(conn, one)[0].integration_id).replace("-", "") == ids[one].hex
    assert _results(conn, two)[0].integration_id is None and _results(conn, none)[0].integration_id is None  # two connections: which is not known


# ── the table, up and down ──────────────────────────────────────────────────────────────────────────────────────


def test_the_schema_goes_up_down_and_up_again_and_the_data_steps_run_with_it(conn):
    session = Session(bind=conn)
    gid = _group(session)
    entry = _entry(session, gid, _type(session, gid), "a", {"n8n_status": "success", "n8n_workflow": "a"})
    failed = _collection(session, gid)
    session.close()
    conn.execute(sa.text("drop table automation_results"))  # the suite's database is already at head

    _run(conn, "upgrade")
    assert len(_results(conn, gid)) == 1 and not _exists(conn, failed.id)
    assert _metadata(Session(bind=conn), entry.id) == {}

    _run(conn, "downgrade")  # drops the table; the collections and metadata are not put back
    assert "automation_results" not in sa.inspect(conn).get_table_names()
    assert not _exists(conn, failed.id) and _metadata(Session(bind=conn), entry.id) == {}

    _run(conn, "upgrade")
    assert _results(conn, gid) == []  # nothing left to import: the keys went the first time
    columns = {c["name"] for c in sa.inspect(conn).get_columns("automation_results")}
    assert {"group_id", "entry_id", "integration_id", "workflow_id", "action", "target", "remote_id", "remote_url", "status", "message"} <= columns
    assert {"sent_at", "finished_at", "attempt", "dismissed_at", "dismissed_by"} <= columns
