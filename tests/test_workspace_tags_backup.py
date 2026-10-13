"""Backup/restore must carry tags — export the vocabulary + per-entry slugs, import rebuilds both.

Guards the gap that a workspace restore used to silently drop every tag: the exporter now emits a
top-level `tags` vocabulary (slug + name + color) plus a slug list on each entry, and the seed
loader recreates the vocabulary and relinks entries (find-or-create by slug, so it's idempotent
and an entry-referenced tag missing from the vocabulary is created on the fly).
"""

import uuid

from pytest import fixture

from marvin.db.models.platform import Entries, EntryTags, EntryTypes, Tags
from marvin.repos.all_repositories import get_repositories
from marvin.repos.seed.workspace_exporter import WorkspaceExporter
from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader
from marvin.schemas.platform import EntryUpdate, TagCreate


@fixture
def group(db_session):
    """A throwaway workspace with one entry type, cleaned up after the test."""
    from marvin.db.models.groups import Groups

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"bk-{marker}", slug=f"bk-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()

    etid = uuid.uuid4()
    et = EntryTypes(session=db_session, group_id=gid, name="Note", slug="note", schema_json={})
    et.id = etid
    db_session.add(et)
    db_session.commit()

    yield gid, etid, marker

    db_session.query(EntryTags).filter(EntryTags.entry_id.in_(db_session.query(Entries.id).filter(Entries.group_id == gid))).delete(
        synchronize_session=False
    )
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(Tags).filter(Tags.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def test_export_emits_tag_vocabulary_and_per_entry_slugs(db_session, group):
    gid, etid, marker = group
    repos = get_repositories(db_session, group_id=gid)

    waxed = repos.tags.create(TagCreate(name="Waxed Canvas", color="#a33"))
    repos.tags.create(TagCreate(name="Leather"))
    entry = Entries(session=db_session, group_id=gid, entry_type_id=etid, title="Jacket", slug=f"jacket-{marker}")
    db_session.add(entry)
    db_session.commit()
    repos.entries.update(entry.id, EntryUpdate(tag_ids=[waxed.id]))

    data = WorkspaceExporter(repos).export_workspace()

    vocab = {t["slug"]: t for t in data["tags"]}
    assert "waxed-canvas" in vocab and "leather" in vocab
    assert vocab["waxed-canvas"] == {"name": "Waxed Canvas", "slug": "waxed-canvas", "color": "#a33"}

    exported_entry = next(e for e in data["entries"] if e["slug"] == f"jacket-{marker}")
    assert exported_entry["tags"] == ["waxed-canvas"]


def test_import_rebuilds_vocabulary_and_links(db_session, group):
    gid, etid, marker = group
    repos = get_repositories(db_session, group_id=gid)

    payload = {
        "tags": [
            {"name": "Waxed Canvas", "slug": "waxed-canvas", "color": "#a33"},
            {"name": "Leather", "slug": "leather", "color": None},
        ],
        "entries": [
            {"entryType": "note", "title": "Jacket", "slug": f"jacket-{marker}", "status": "draft", "data": {}, "tags": ["waxed-canvas", "leather"]},
            # 'stitching' is NOT in the vocabulary — must be created on the fly from the link.
            {"entryType": "note", "title": "Belt", "slug": f"belt-{marker}", "status": "draft", "data": {}, "tags": ["leather", "stitching"]},
        ],
    }
    result = WorkspaceSeedLoader(repos)._load_data(payload, overwrite=True, target_group_id=str(gid))

    assert result["tags"] == 2 and result["errors"] == 0

    # Vocabulary: the 2 declared + the 1 auto-created from an entry link.
    slugs = {t.slug for t in db_session.query(Tags).filter(Tags.group_id == gid).all()}
    assert slugs == {"waxed-canvas", "leather", "stitching"}

    waxed = db_session.query(Tags).filter(Tags.group_id == gid, Tags.slug == "waxed-canvas").one()
    assert waxed.name == "Waxed Canvas" and waxed.color == "#a33"  # display fields preserved

    jacket = db_session.query(Entries).filter(Entries.group_id == gid, Entries.slug == f"jacket-{marker}").one()
    belt = db_session.query(Entries).filter(Entries.group_id == gid, Entries.slug == f"belt-{marker}").one()
    assert set(jacket.tag_names) == {"waxed-canvas", "leather"}
    assert set(belt.tag_names) == {"leather", "stitching"}


def test_reimport_is_idempotent(db_session, group):
    gid, etid, marker = group
    repos = get_repositories(db_session, group_id=gid)

    payload = {
        "tags": [{"name": "Leather", "slug": "leather", "color": None}],
        "entries": [
            {"entryType": "note", "title": "Belt", "slug": f"belt-{marker}", "status": "draft", "data": {}, "tags": ["leather"]},
        ],
    }
    WorkspaceSeedLoader(repos)._load_data(payload, overwrite=True, target_group_id=str(gid))
    WorkspaceSeedLoader(repos)._load_data(payload, overwrite=True, target_group_id=str(gid))

    # No duplicate tags, no duplicate links after a second restore.
    assert db_session.query(Tags).filter(Tags.group_id == gid, Tags.slug == "leather").count() == 1
    belt = db_session.query(Entries).filter(Entries.group_id == gid, Entries.slug == f"belt-{marker}").one()
    assert belt.tag_names == ["leather"]
