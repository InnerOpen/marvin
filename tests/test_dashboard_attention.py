"""The dashboard's Needs Attention counts match the entries list each one links to.

Regression: one "drafts" number counted inbox + draft entries but linked to ?status=draft, so Mash & Burn
showed 11 "drafts" over a list of 2 (the other 9 were form submissions and AI drafts in the inbox).
"""

import uuid
from types import SimpleNamespace

from pytest import fixture

from marvin.routes.platform import stats_controller as sc


@fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import Entries, EntryTypes

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"att-{gid.hex[:8]}", slug=f"att-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    et = EntryTypes(session=db_session, group_id=gid, name="Note", slug="note", schema_json={})
    db_session.add(et)
    db_session.flush()
    for i, status in enumerate(["inbox"] * 3 + ["draft"] * 2 + ["needs_review"] + ["published"]):
        db_session.add(Entries(session=db_session, group_id=gid, entry_type_id=et.id, title=f"E{i}", slug=f"e{i}-{gid.hex[:6]}", status=status))
    db_session.commit()
    yield gid
    db_session.query(Entries).filter_by(group_id=gid).delete()
    db_session.query(EntryTypes).filter_by(group_id=gid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


def test_inbox_and_drafts_are_counted_apart(db_session, workspace, monkeypatch):
    for name, value in (("group_id", workspace), ("repos", SimpleNamespace(session=db_session))):
        monkeypatch.setattr(sc.StatsController, name, property(lambda self, v=value: v), raising=False)

    attention = object.__new__(sc.StatsController).get_dashboard().attention

    assert (attention.inbox, attention.drafts) == (3, 2)


def test_entries_in_needs_review_are_counted_apart(db_session, workspace, monkeypatch):
    # A flagged submission or a refused newsletter signup leaves the inbox for Needs review; it must
    # still show here, behind the Review Queue's own filter.
    for name, value in (("group_id", workspace), ("repos", SimpleNamespace(session=db_session))):
        monkeypatch.setattr(sc.StatsController, name, property(lambda self, v=value: v), raising=False)

    attention = object.__new__(sc.StatsController).get_dashboard().attention

    assert attention.needs_review == 1
