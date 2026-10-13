"""Workspace search reindex: batched, incremental, failures reported, one run at a time.

Regression: the Reindex button made one embedding call per item inside the web request — minutes for a
real workspace, so the browser timed out behind the tunnel while the server kept going (and a second
click ran it all again); and a failing item was swallowed, so a broken run reported "0 entities".
"""

import uuid

from pytest import fixture

from marvin.services.ai import embeddings
from marvin.services.ai.embeddings import EMBED_BATCH_CHUNKS, reindex_workspace


class _Provider:
    provider_type = "openai"

    def __init__(self, fail_with: Exception | None = None):
        self.calls: list[int] = []
        self.fail_with = fail_with

    def embed(self, texts, model):
        self.calls.append(len(texts))
        if self.fail_with:
            raise self.fail_with
        return [[0.1, 0.2, 0.3] for _ in texts]


@fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel
    from marvin.db.models.platform import Entries, EntryTypes

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"rx-{gid.hex[:8]}", slug=f"rx-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    et = EntryTypes(session=db_session, group_id=gid, name="Note", slug="note", schema_json={})
    db_session.add(et)
    db_session.flush()
    for i in range(EMBED_BATCH_CHUNKS + 6):  # more than one batch
        db_session.add(
            Entries(
                session=db_session,
                group_id=gid,
                entry_type_id=et.id,
                title=f"Note {i}",
                slug=f"n{i}-{gid.hex[:6]}",
                summary=f"About thing {i}",
                status="published",
            )
        )
    db_session.commit()
    yield gid
    db_session.query(AIEmbeddingModel).filter_by(group_id=gid).delete()
    db_session.query(Entries).filter_by(group_id=gid).delete()
    db_session.query(EntryTypes).filter_by(group_id=gid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


def test_items_are_embedded_in_batches_not_one_call_each(db_session, workspace):
    provider = _Provider()
    result = reindex_workspace(db_session, workspace, provider, "m")

    assert result.entities == EMBED_BATCH_CHUNKS + 6 and result.failed == 0
    assert len(provider.calls) == 2 and max(provider.calls) <= EMBED_BATCH_CHUNKS + 1


def test_a_second_run_skips_items_whose_text_has_not_changed(db_session, workspace):
    reindex_workspace(db_session, workspace, _Provider(), "m")
    provider = _Provider()

    result = reindex_workspace(db_session, workspace, provider, "m")

    assert result.skipped == EMBED_BATCH_CHUNKS + 6 and result.entities == 0 and provider.calls == []


def test_force_re_embeds_everything(db_session, workspace):
    reindex_workspace(db_session, workspace, _Provider(), "m")

    result = reindex_workspace(db_session, workspace, _Provider(), "m", force=True)

    assert result.entities == EMBED_BATCH_CHUNKS + 6 and result.skipped == 0


def test_a_failing_provider_is_reported_not_swallowed(db_session, workspace):
    result = reindex_workspace(db_session, workspace, _Provider(fail_with=RuntimeError("quota exceeded")), "m")

    assert result.entities == 0 and result.failed == EMBED_BATCH_CHUNKS + 6
    assert result.errors == ["RuntimeError: quota exceeded"] and "failed: RuntimeError: quota exceeded" in result.summary


def test_progress_reaches_the_total(db_session, workspace):
    seen = []
    reindex_workspace(db_session, workspace, _Provider(), "m", progress=lambda done, total: seen.append((done, total)))

    assert seen[-1] == (EMBED_BATCH_CHUNKS + 6, EMBED_BATCH_CHUNKS + 6)


# --- background runs ------------------------------------------------------------------------------


def test_only_one_reindex_runs_per_workspace(monkeypatch):
    from marvin.services.ai import reindex_jobs

    started = []

    class _Thread:
        def __init__(self, target, args, name, daemon):
            self.args = args

        def start(self):
            started.append(self.args)

    monkeypatch.setattr(reindex_jobs.threading, "Thread", _Thread)
    gid = uuid.uuid4()
    try:
        assert reindex_jobs.start(gid) is True
        assert reindex_jobs.start(gid) is False  # a second click is refused, not run twice
        assert reindex_jobs.status(gid)["done"] == 0 and len(started) == 1
    finally:
        reindex_jobs._running.pop(str(gid), None)


def test_the_run_reports_through_the_event_even_when_it_fails(monkeypatch):
    from marvin.services.ai import reindex_jobs

    emitted = {}
    monkeypatch.setattr("marvin.services.ai.factory.get_workspace_ai_provider", lambda s, g: (_ for _ in ()).throw(RuntimeError("no key")))
    monkeypatch.setattr(reindex_jobs, "emit", lambda gid, model, result, **kw: emitted.update(result=result))
    gid = uuid.uuid4()
    reindex_jobs._running[str(gid)] = {"done": 0, "total": 0}

    reindex_jobs._run(gid, None, False)

    assert emitted["result"].errors == ["RuntimeError: no key"] and reindex_jobs.status(gid) is None


def test_embeddings_module_keeps_single_entity_indexing(db_session, workspace):
    # index_entity (single-entity reindex, live re-embed on save) shares the storage helper.
    from marvin.db.models.platform import Entries

    entry = db_session.query(Entries).filter_by(group_id=workspace).first()
    assert embeddings.index_entity(db_session, workspace, "entry", entry.id, "Some text to embed", _Provider(), "m") == 1


# --- only published entries are searchable ----------------------------------------------------------


def test_the_full_reindex_leaves_out_and_purges_unpublished_entries(db_session, workspace):
    from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel
    from marvin.db.models.platform import Entries

    reindex_workspace(db_session, workspace, _Provider(), "m")
    archived = db_session.query(Entries).filter_by(group_id=workspace).first()
    archived.status = "archived"
    db_session.commit()

    result = reindex_workspace(db_session, workspace, _Provider(), "m")

    assert result.purged == 1
    assert db_session.query(AIEmbeddingModel).filter_by(group_id=workspace, entity_id=archived.id).count() == 0


def test_unpublishing_or_archiving_takes_an_entry_out_of_the_index():
    from marvin.services.ai.embeddings_registry import delete_descriptor_for
    from marvin.services.event_bus_service.event_types import EventTypes

    for event in (EventTypes.entry_deleted, EventTypes.entry_unpublished, EventTypes.entry_archived):
        assert delete_descriptor_for(event).entity_type == "entry"


def test_an_unchanged_save_needs_no_new_embedding(db_session, workspace):
    from marvin.db.models.platform import Entries
    from marvin.services.ai.embeddings import chunks_unchanged, entity_chunks

    entry = db_session.query(Entries).filter_by(group_id=workspace).first()
    embeddings.index_entity(db_session, workspace, "entry", entry.id, "The same text", _Provider(), "m")

    assert chunks_unchanged(db_session, workspace, "entry", entry.id, "m", entity_chunks("The same text"))
    assert not chunks_unchanged(db_session, workspace, "entry", entry.id, "m", entity_chunks("Different text"))
