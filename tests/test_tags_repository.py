"""DB-backed tests for TagsRepository — the find-or-create vocabulary and entry `tag_ids` wiring.

The behavior worth pinning is the part that differs from every other repo: creating a tag whose
slug already exists returns the *existing* row (so "create-on-type" is idempotent), the slug is
stable across renames, and `tag_ids` on an entry update *replaces* the entry's tag set.
"""

import uuid

from pytest import fixture

from marvin.db.models.platform import Entries, EntryTags, EntryTypes, Tags
from marvin.repos.all_repositories import get_repositories
from marvin.schemas.platform import EntryUpdate, TagCreate, TagUpdate


@fixture
def group(db_session):
    """A throwaway workspace with one entry type + one entry, cleaned up after the test."""
    from marvin.db.models.groups import Groups

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"tag-test-{marker}", slug=f"tag-test-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()

    etid = uuid.uuid4()
    et = EntryTypes(session=db_session, group_id=gid, name="Note", slug="note", schema_json={})
    et.id = etid
    db_session.add(et)
    db_session.flush()

    entry = Entries(session=db_session, group_id=gid, entry_type_id=etid, title="T", slug=f"t-{marker}")
    db_session.add(entry)
    db_session.commit()

    yield gid, entry.id

    db_session.query(EntryTags).filter(EntryTags.entry_id == entry.id).delete()
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(Tags).filter(Tags.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def test_create_is_find_or_create_by_slug(db_session, group):
    gid, _ = group
    repos = get_repositories(db_session, group_id=gid)

    first = repos.tags.create(TagCreate(name="Chore Coat"))
    again = repos.tags.create(TagCreate(name="chore coat"))  # same slug, different casing

    assert first.slug == "chore-coat"
    assert first.id == again.id  # existing row returned, not a duplicate
    assert db_session.query(Tags).filter(Tags.group_id == gid, Tags.slug == "chore-coat").count() == 1


def test_slug_is_stable_across_rename(db_session, group):
    gid, _ = group
    repos = get_repositories(db_session, group_id=gid)

    tag = repos.tags.create(TagCreate(name="Waxed"))
    renamed = repos.tags.update(tag.id, TagUpdate(name="Waxed Canvas", color="#333"))

    assert renamed.name == "Waxed Canvas"
    assert renamed.color == "#333"
    assert renamed.slug == "waxed"  # identity unchanged — protects smart-collection rules


def test_tag_ids_on_entry_update_replaces_the_set(db_session, group):
    gid, entry_id = group
    repos = get_repositories(db_session, group_id=gid)

    leather = repos.tags.create(TagCreate(name="Leather"))
    waxed = repos.tags.create(TagCreate(name="Waxed"))

    repos.entries.update(entry_id, EntryUpdate(tag_ids=[leather.id, waxed.id]))
    assert set(db_session.get(Entries, entry_id).tag_names) == {"leather", "waxed"}

    # replace, not append
    repos.entries.update(entry_id, EntryUpdate(tag_ids=[leather.id]))
    assert db_session.get(Entries, entry_id).tag_names == ["leather"]

    # empty list clears
    repos.entries.update(entry_id, EntryUpdate(tag_ids=[]))
    assert db_session.get(Entries, entry_id).tag_names == []


def test_entry_read_exposes_tag_slugs_not_objects(db_session, group):
    """EntryRead.tags must be slug strings — the model_validate override converts the ORM
    Tag relationship (objects) into `tag_names`, or pydantic would choke on list[str]."""
    from marvin.db.models.platform import Entries
    from marvin.schemas.platform import EntryRead

    gid, entry_id = group
    repos = get_repositories(db_session, group_id=gid)

    waxed = repos.tags.create(TagCreate(name="Waxed Canvas"))
    repos.entries.update(entry_id, EntryUpdate(tag_ids=[waxed.id]))

    read = EntryRead.model_validate(db_session.get(Entries, entry_id))
    assert read.tags == ["waxed-canvas"]  # slug string, not a Tag object


def test_apply_fields_tags_target_unions_and_find_or_creates(db_session, group):
    """The generate-tags write-back (apply_fields with the "tags" target) find-or-creates each
    suggested name and unions it with the entry's existing tags — additive, deduped by slug."""
    from marvin.db.models.platform import Entries, EntryTags

    gid, entry_id = group
    repos = get_repositories(db_session, group_id=gid)
    leather = repos.tags.create(TagCreate(name="Leather"))
    repos.entries.update(entry_id, EntryUpdate(tag_ids=[leather.id]))  # pre-existing curated tag

    # Suggest one existing (by display name) + two new — existing must not duplicate, new are created.
    repos.entries.apply_fields(entry_id, {"tags": ["Leather", "Waxed Canvas", "workwear"]})

    entry = db_session.get(Entries, entry_id)
    assert set(entry.tag_names) == {"leather", "waxed-canvas", "workwear"}
    # 'leather' kept its single link (union, not re-added)
    from sqlalchemy import func

    dupes = (
        db_session.query(EntryTags.tag_id, func.count())
        .filter(EntryTags.entry_id == entry_id)
        .group_by(EntryTags.tag_id)
        .having(func.count() > 1)
        .all()
    )
    assert not dupes


def test_attaching_the_same_tag_twice_is_idempotent(db_session, group):
    gid, entry_id = group
    repos = get_repositories(db_session, group_id=gid)

    leather = repos.tags.create(TagCreate(name="Leather"))
    repos.entries._attach_tags(entry_id, [leather.id, leather.id])
    db_session.commit()

    assert db_session.query(EntryTags).filter(EntryTags.entry_id == entry_id, EntryTags.tag_id == leather.id).count() == 1
