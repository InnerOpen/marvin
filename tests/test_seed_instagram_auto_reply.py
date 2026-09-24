"""The Instagram auto-reply seed is idempotent and leaves CMS edits alone on a re-run."""

import importlib.util
import sys
import uuid
from pathlib import Path

from pytest import fixture

from marvin.db.models.groups.groups import Groups
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "seed_instagram_auto_reply.py"


def _load_seed():
    spec = importlib.util.spec_from_file_location("seed_instagram_auto_reply", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@fixture
def workspace(db_session):
    gid = uuid.uuid4()
    slug = f"ig-seed-{gid.hex[:8]}"
    g = Groups(session=db_session, name=slug, slug=slug)
    g.id = gid
    db_session.add(g)
    db_session.commit()

    yield gid, slug

    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.query(ScheduledTaskModel).filter(ScheduledTaskModel.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def test_seed_creates_types_tasks_and_draft_rules_once(db_session, workspace, monkeypatch):
    gid, slug = workspace
    seed = _load_seed()
    monkeypatch.setattr(sys, "argv", ["seed", "--workspace", slug])

    assert seed.main() == 0
    # a CMS edit to a seeded rule must survive the second run
    rule = db_session.query(Entries).filter(Entries.group_id == gid, Entries.slug == "ig-rule-size").one()
    rule.status = "published"
    db_session.commit()
    assert seed.main() == 0

    types = {t.slug: t for t in db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).all()}
    assert set(types) == {"ig-auto-reply", "ig-reply-log"}
    assert types["ig-auto-reply"].capabilities_json == {"publishable": False, "submittable": False, "routable": False}
    assert [f["key"] for f in types["ig-reply-log"].schema_json["fields"]][0] == "comment_id"

    tasks = {t.slug: t for t in db_session.query(ScheduledTaskModel).filter(ScheduledTaskModel.group_id == gid).all()}
    assert set(tasks) == {"instagram-auto-reply", "instagram-token-refresh"}
    auto = tasks["instagram-auto-reply"]
    assert auto.enabled is False
    assert auto.task_type == "run_integration_action"
    assert auto.task_config["args"]["dry_run"] is True
    assert auto.task_config["inputs"]["rules"] == {"entry_type": "ig-auto-reply", "status": "published", "as": "records"}
    assert auto.next_run_at is not None

    rules = db_session.query(Entries).filter(Entries.group_id == gid, Entries.entry_type_id == types["ig-auto-reply"].id).all()
    assert sorted(r.slug for r in rules) == ["ig-rule-link", "ig-rule-price", "ig-rule-size"]
    db_session.refresh(rule)
    assert rule.status == "published"
    assert all(r.status == "draft" for r in rules if r.slug != "ig-rule-size")


def test_seed_fails_cleanly_for_unknown_workspace(monkeypatch):
    seed = _load_seed()
    monkeypatch.setattr(sys, "argv", ["seed", "--workspace", "nope-" + uuid.uuid4().hex[:6]])
    assert seed.main() == 1
