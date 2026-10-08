"""DB-backed tests for the AI-suggested-asset approval flow on EntryService.

A generative media step links its output to the entry but flags the junction pending
(metadata_json.suggested). Approve clears the flag (asset becomes a normal confirmed link);
reject unlinks and — when the asset is orphaned — deletes it. Both are 404 (return None) on a
junction that isn't actually flagged suggested, so a curated asset can never be touched.
"""

import uuid

from pytest import fixture

from marvin.db.models.platform import Assets, Entries, EntryAssets, EntryTypes
from marvin.services.entries import EntryService


class _SpyBus:
    def __init__(self):
        self.events = []

    def dispatch(self, *, event_type, **_):
        self.events.append(event_type.name)


@fixture
def workspace(db_session):
    """A throwaway workspace: one entry, one asset, and a *suggested* entry↔asset junction."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"sug-{marker}", slug=f"sug-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()

    uid = uuid.uuid4()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=f"u-{marker}",
            email=f"u-{marker}@t.test",
            full_name="U",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )

    et = EntryTypes(session=db_session, group_id=gid, name="Note", slug="note", schema_json={})
    et.id = uuid.uuid4()
    db_session.add(et)
    db_session.flush()

    entry = Entries(session=db_session, group_id=gid, entry_type_id=et.id, title="T", slug=f"t-{marker}")
    db_session.add(entry)

    aid = uuid.uuid4()
    db_session.execute(
        Assets.__table__.insert().values(
            id=aid,
            group_id=gid,
            slug="gen-img",
            name="Generated Image",
            original_filename="g.jpg",
            filename="g",
            extension="jpg",
            file_size=1234,
            mime_type="image/jpeg",
            asset_type="image",
            checksum="abc",
            storage_provider="local",
            storage_key=f"k/{marker}.jpg",
            uploaded_by=uid,
        )
    )
    db_session.flush()

    db_session.add(
        EntryAssets(
            entry_id=entry.id,
            asset_id=aid,
            role="hero-generated",
            position=900,
            metadata_json={
                "suggested": True,
                "media_op": "generate",
                "prompt": "a hat",
                "derived_from": str(uuid.uuid4()),
                "derivation": "media:generate",
            },
        )
    )
    db_session.commit()

    yield gid, entry.id, aid

    db_session.query(EntryAssets).delete()
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.execute(Assets.__table__.delete().where(Assets.group_id == gid))
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.execute(Users.__table__.delete().where(Users.group_id == gid))
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _svc(db_session, gid):
    bus = _SpyBus()
    return EntryService(db_session, gid, event_bus=bus, integration_id="entry_management"), bus


def test_approve_clears_suggested_flag_and_keeps_link(db_session, workspace):
    gid, entry_id, asset_id = workspace
    svc, bus = _svc(db_session, gid)

    entry = svc.approve_suggested_asset(entry_id, asset_id)

    assert entry is not None
    junction = db_session.query(EntryAssets).filter_by(entry_id=entry_id, asset_id=asset_id).first()
    assert junction is not None, "link must be kept on approve"
    assert not (junction.metadata_json or {}).get("suggested"), "suggested flag must be cleared"
    # non-suggested provenance keys are preserved
    assert junction.metadata_json.get("media_op") == "generate"
    assert bus.events == ["entry_updated"]


def test_approve_non_suggested_is_404(db_session, workspace):
    gid, entry_id, asset_id = workspace
    svc, _ = _svc(db_session, gid)
    svc.approve_suggested_asset(entry_id, asset_id)  # first approve clears the flag

    # second approve: no suggested link remains → None (404), and the link is untouched
    assert svc.approve_suggested_asset(entry_id, asset_id) is None
    assert db_session.query(EntryAssets).filter_by(entry_id=entry_id, asset_id=asset_id).count() == 1


def test_reject_unlinks_and_deletes_orphan_asset(db_session, workspace):
    gid, entry_id, asset_id = workspace
    svc, bus = _svc(db_session, gid)

    entry = svc.reject_suggested_asset(entry_id, asset_id)

    assert entry is not None
    assert db_session.query(EntryAssets).filter_by(entry_id=entry_id, asset_id=asset_id).count() == 0
    assert db_session.get(Assets, asset_id) is None, "orphaned asset must be deleted"
    # Through the one asset delete: its file goes from storage and asset_deleted says so.
    assert bus.events == ["asset_deleted", "entry_updated"]


def test_reject_keeps_asset_when_still_linked_elsewhere(db_session, workspace):
    gid, entry_id, asset_id = workspace
    svc, _ = _svc(db_session, gid)

    # A second (confirmed) entry also uses this asset → reject must not delete the asset.
    other = Entries(session=db_session, group_id=gid, entry_type_id=None, title="Other", slug=f"o-{gid.hex[:6]}")
    et = db_session.query(EntryTypes).filter_by(group_id=gid).first()
    other.entry_type_id = et.id
    db_session.add(other)
    db_session.flush()
    db_session.add(EntryAssets(entry_id=other.id, asset_id=asset_id, role="hero", position=0))
    db_session.commit()

    svc.reject_suggested_asset(entry_id, asset_id)

    assert db_session.query(EntryAssets).filter_by(entry_id=entry_id, asset_id=asset_id).count() == 0
    assert db_session.get(Assets, asset_id) is not None, "asset still linked elsewhere must survive"
    assert db_session.query(EntryAssets).filter_by(asset_id=asset_id).count() == 1


def test_reject_non_suggested_is_404_and_preserves_asset(db_session, workspace):
    gid, entry_id, asset_id = workspace
    svc, _ = _svc(db_session, gid)
    # Turn the suggested link into a normal one.
    junction = db_session.query(EntryAssets).filter_by(entry_id=entry_id, asset_id=asset_id).first()
    junction.metadata_json = {"media_op": "generate"}
    db_session.commit()

    assert svc.reject_suggested_asset(entry_id, asset_id) is None
    assert db_session.query(EntryAssets).filter_by(entry_id=entry_id, asset_id=asset_id).count() == 1
    assert db_session.get(Assets, asset_id) is not None
