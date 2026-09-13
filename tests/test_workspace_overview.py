"""workspace_overview: the corpus-level answer to "what's in the RAG?" — counts, not guesses."""

import json
import uuid
from types import SimpleNamespace

import sqlalchemy as sa
from pytest import fixture

from marvin.db.models.groups.ai_embeddings import AIEmbeddingModel
from marvin.db.models.groups.groups import Groups
from marvin.db.models.platform.assets import Assets
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.db.models.users.users import Users
from marvin.services.ai.tools.builtins_overview import workspace_overview


@fixture
def workspace(db_session):
    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"ov-{marker}", slug=f"ov-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    uid = uuid.uuid4()
    db_session.execute(
        sa.insert(Users.__table__).values(
            id=uid,
            group_id=gid,
            full_name="Test User",
            username=f"u-{marker}",
            email=f"u-{marker}@x.test",
            auth_method="MARVIN",
            is_superuser=False,
            platform_role="NONE",
            admin=True,
        )
    )
    et = EntryTypes(session=db_session, group_id=gid, name="Bench note", slug=f"bench-note-{marker}")
    db_session.add(et)
    db_session.flush()
    entries = [
        Entries(session=db_session, group_id=gid, entry_type_id=et.id, title=f"Note {i}", slug=f"note-{i}-{marker}", status=status)
        for i, status in enumerate(("published", "published", "draft"))
    ]
    asset = Assets(
        session=db_session,
        group_id=gid,
        slug=f"asset-{marker}",
        name="Asset",
        original_filename="a.jpg",
        filename="a.jpg",
        extension="jpg",
        file_size=1,
        mime_type="image/jpeg",
        asset_type="image",
        checksum="x",
        storage_provider="local",
        storage_key=f"key-{marker}",
        uploaded_by=uid,
    )
    db_session.add_all([*entries, asset])
    db_session.flush()
    # one entry indexed in two chunks, the others not indexed at all
    for chunk in range(2):
        db_session.add(
            AIEmbeddingModel(
                session=db_session,
                group_id=gid,
                entity_type="entry",
                entity_id=entries[0].id,
                chunk_index=chunk,
                chunk_text=f"chunk {chunk}",
                embedding=[0.0, 1.0],
                model_id="test-embed",
                dimensions=2,
            )
        )
    db_session.commit()

    yield gid, et.slug

    db_session.query(AIEmbeddingModel).filter(AIEmbeddingModel.group_id == gid).delete()
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(Assets).filter(Assets.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.query(Users).filter(Users.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def test_workspace_overview_reports_counts_by_type_status_and_index_coverage(db_session, workspace):
    gid, type_slug = workspace
    ctx = SimpleNamespace(session=db_session, group_id=gid, user=None, provider=None, logger=None)

    out = json.loads(workspace_overview(ctx, {}))

    assert out["workspace"]["slug"] == f"ov-{gid.hex[:8]}"
    assert out["entries"]["total"] == 3
    bench = next(t for t in out["entries"]["byType"] if t["slug"] == type_slug)
    assert bench["byStatus"] == {"published": 2, "draft": 1}
    assert out["assets"] == {"total": 1, "byType": {"image": 1}}
    assert out["index"]["entry"] == {"indexed": 1, "total": 3, "chunks": 2}
    assert out["index"]["asset"] == {"indexed": 0, "total": 1, "chunks": 0}
