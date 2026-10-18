"""Entry snapshots: capture a version of an entry and put it back — through the `snapshot` workflow step and the entries
API. Restoring fires the normal events, respects the author's role (and the entry rules for a person), leaves status alone
unless asked, previews its diff in a dry run, and changes nothing the second time. Each entry keeps a bounded number."""

# ruff: noqa: F811 — `ws` is a fixture, not a redefinition
import uuid

import pytest

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.platform import Assets, Entries
from marvin.db.models.platform.entry_snapshots import EntrySnapshotModel
from marvin.db.models.users.roles import WorkspaceRole
from marvin.schemas.group.automation_definition import SnapshotAction
from marvin.services import snapshots
from marvin.services.automation.actions.base import AutomationActionError
from marvin.services.automation.actions.snapshot import run_snapshot_action
from marvin.services.automation.authoring import authoring_guide, draft_issues
from marvin.services.automation.authz import ROLE_AUTHOR, ROLE_EDITOR, ROLE_VIEWER
from marvin.services.automation.context import event_context
from marvin.services.automation.engine import run_automations_for_event
from marvin.services.automation.recorder import ExecutionRecorder
from marvin.services.entries import EntryService
from marvin.services.event_bus_service.event_bus_service import EventBusService
from tests import test_content_role_gates as gates
from tests.test_workflow_authoring import workspace, ws  # noqa: F401 — fixtures

P = gates.P
AD, ED, AU, VI = WorkspaceRole.ADMIN, WorkspaceRole.EDITOR, WorkspaceRole.AUTHOR, WorkspaceRole.VIEWER


@pytest.fixture(autouse=True)
def snapshots_cleared(ws):
    yield
    ws.session.rollback()
    ws.session.query(EntrySnapshotModel).filter(EntrySnapshotModel.group_id == ws.gid).delete(synchronize_session=False)
    ws.session.commit()


@pytest.fixture
def sent(monkeypatch):
    """The events the entry service sends, as [(event type, entity id)] — instead of putting them on the bus."""
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: seen.append((kw["event_type"].name, str(kw["entity_id"]))))
    return seen


def _entry(ws, title="Soup", **fields) -> Entries:
    body = {"entry_type_id": ws.et["id"], "title": title, "status": "draft", **fields}
    made = gates._sign_in(ws.workspace, AD).post(f"{P}/entries", json=body)
    assert made.status_code == 201, made.text
    ws.session.expire_all()
    return ws.session.get(Entries, made.json()["id"])


def _reload(ws, entry) -> Entries:
    ws.session.expire_all()
    return ws.session.get(Entries, entry.id)


def _asset(ws, slug: str) -> Assets:
    asset = Assets(
        session=ws.session, group_id=ws.gid, slug=f"{slug}-{ws.gid.hex[:6]}", name=slug, original_filename=f"{slug}.png", filename=f"{slug}.png",
        extension="png", file_size=1, mime_type="image/png", asset_type="image", checksum=uuid.uuid4().hex,
        storage_provider="local", storage_key=f"{slug}-{ws.gid.hex[:6]}.png", uploaded_by=ws.uid,
    )  # fmt: skip
    ws.session.add(asset)
    ws.session.commit()
    return asset


def _edit(ws, entry, **fields) -> None:
    EntryService(ws.session, ws.gid, actor_id=ws.uid).update(entry.id, fields)


def _step(ws, dry_run=False, role=None, context=None, **fields):
    return run_snapshot_action(
        ws.session,
        ws.gid,
        {"kind": "snapshot", **fields},
        context or {"steps": {}, "previous": {}, "event": {}},
        dry_run=dry_run,
        authorizer_role=role,
    )


def _on(entry):
    return {"entity_id": str(entry.id)}


def test_a_restore_puts_back_what_the_entry_was_and_sends_the_normal_events(ws, sent):
    from marvin.db.models.platform.collections import Collections

    svc = EntryService(ws.session, ws.gid, actor_id=ws.uid)
    entry = _entry(ws, "Soup", data_json={}, summary="A soup", metadata_json={"stage": "first"})
    keep, drop = _asset(ws, "keep"), _asset(ws, "drop")
    svc.attach_asset(entry.id, keep.id, role="hero")
    svc.add_to_collection(entry.id, "featured")
    saved = _step(ws, label="before the rewrite", **_on(entry))
    assert saved["created"] is True and saved["label"] == "before the rewrite" and saved["collections"] == ["featured"] and saved["assets"] == 1

    featured = ws.session.query(Collections).filter_by(group_id=ws.gid, slug="featured").one()
    svc.remove_from_collection(entry.id, featured.slug)
    svc.detach_asset(entry.id, keep.id)
    svc.attach_asset(entry.id, drop.id, role="inline")
    _edit(ws, entry, title="Stew", summary="A stew", metadata_json={"stage": "rewritten", "extra": 1})
    sent.clear()

    done = _step(ws, op="restore", snapshot=saved["snapshot_id"], context={"steps": {}, "previous": {}, "event": {}, "depth": 2})

    back = _reload(ws, entry)
    assert (back.title, back.summary, back.metadata_json) == ("Soup", "A soup", {"stage": "first"})
    assert sorted(a.slug for a in back.assets) == [keep.slug]
    assert [c.slug for c in back.collections] == ["featured"]
    assert done["restored"] is True and done["changed"] is True
    assert done["assets"] == {"attach": [keep.slug], "detach": [drop.slug], "missing": []}
    assert {e for e, _ in sent} == {"entry_updated", "entry_added_to_collection", "asset_attached_to_entry", "asset_detached_from_entry"}
    assert {i for _, i in sent} == {str(entry.id)}


def test_capturing_again_reuses_an_identical_snapshot_and_each_entry_keeps_a_bounded_number(ws, monkeypatch):
    entry = _entry(ws)
    first = _step(ws, **_on(entry))
    again = _step(ws, **_on(entry))
    assert again["snapshot_id"] == first["snapshot_id"] and again["created"] is False  # run two adds nothing
    assert ws.session.query(EntrySnapshotModel).filter_by(entry_id=entry.id).count() == 1

    monkeypatch.setattr(snapshots, "MAX_PER_ENTRY", 3)
    ids = []
    for n in range(5):
        _edit(ws, entry, title=f"Soup {n}")
        ids.append(_step(ws, **_on(entry))["snapshot_id"])
    kept = {str(r.id) for r in snapshots.list_for(ws.session, ws.gid, entry.id)}
    assert kept == set(ids[-3:])  # the oldest went first


def test_a_restore_leaves_status_alone_unless_asked_and_never_touches_the_trash(ws, sent):
    entry = _entry(ws)
    _edit(ws, entry, status="published")
    saved = _step(ws, **_on(entry))
    _edit(ws, entry, status="draft", title="Changed")

    _step(ws, op="restore", snapshot=saved["snapshot_id"])
    assert _reload(ws, entry).status == "draft" and _reload(ws, entry).title == "Soup"  # content back, not published

    sent.clear()
    done = _step(ws, op="restore", snapshot=saved["snapshot_id"], parts=["status"])
    assert _reload(ws, entry).status == "published" and done["status"] == {"before": "draft", "after": "published", "changes": True}
    assert "entry_published" in {e for e, _ in sent}

    EntryService(ws.session, ws.gid, actor_id=ws.uid).trash(entry.id)
    with pytest.raises(AutomationActionError, match="in the Trash"):
        _step(ws, op="restore", snapshot=saved["snapshot_id"])


def test_a_dry_run_previews_the_diff_and_writes_nothing_and_a_second_restore_changes_nothing(ws, sent):
    entry = _entry(ws, "Soup", data_json={})
    saved = _step(ws, **_on(entry))
    _edit(ws, entry, title="Stew")
    sent.clear()

    preview = _step(ws, op="restore", dry_run=True, snapshot=saved["snapshot_id"])
    assert preview["dry_run"] and preview["would"] == "restore" and preview["content"] == {"title": {"before": "Stew", "after": "Soup"}}
    assert _reload(ws, entry).title == "Stew" and sent == []
    assert _step(ws, dry_run=True, **_on(entry))["would"] == "capture"  # the entry has moved on from its last snapshot

    real = _step(ws, op="restore", snapshot=saved["snapshot_id"])
    assert real["restored"] is True and _reload(ws, entry).title == "Soup"
    sent.clear()
    second = _step(ws, op="restore", snapshot=saved["snapshot_id"])
    assert second["restored"] is False and second["changed"] is False and sent == []
    assert _step(ws, op="restore", dry_run=True, snapshot=saved["snapshot_id"])["would"] == "leave"
    assert _step(ws, dry_run=True, **_on(entry))["would"] == "reuse"
    # An earlier capture that only previewed leaves no id to diff: the preview says so instead of failing.
    pending = _step(ws, op="restore", dry_run=True, snapshot="${steps.save.output.snapshot_id}", context={"steps": {}, "previous": {}, "event": {}})
    assert pending["would"] == "restore" and pending["snapshot_id"] is None


def test_restore_without_an_id_takes_the_entrys_latest_and_a_label_picks_one(ws):
    entry = _entry(ws, "One")
    _step(ws, label="start", **_on(entry))
    _edit(ws, entry, title="Two")
    _step(ws, label="middle", **_on(entry))
    _edit(ws, entry, title="Three")

    assert _step(ws, op="restore", **_on(entry))["restored"] is True and _reload(ws, entry).title == "Two"
    _edit(ws, entry, title="Three")
    _step(ws, op="restore", label="start", **_on(entry))
    assert _reload(ws, entry).title == "One"
    with pytest.raises(AutomationActionError, match="no snapshot with that label"):
        _step(ws, op="restore", label="nope", **_on(entry))


def test_snapshot_steps_need_an_author_or_better_and_stay_in_this_workspace(ws):
    entry = _entry(ws)
    for role in (ROLE_VIEWER, 0):
        with pytest.raises(AutomationActionError, match="requires role"):
            _step(ws, role=role, **_on(entry))
    saved = _step(ws, role=ROLE_AUTHOR, **_on(entry))
    _edit(ws, entry, title="Stew")
    with pytest.raises(AutomationActionError, match="requires role"):
        _step(ws, op="restore", role=ROLE_VIEWER, snapshot=saved["snapshot_id"])
    assert _step(ws, op="restore", role=ROLE_EDITOR, snapshot=saved["snapshot_id"])["restored"] is True

    with pytest.raises(AutomationActionError, match="no such snapshot"):
        run_snapshot_action(ws.session, uuid.uuid4(), {"kind": "snapshot", "op": "restore", "snapshot": saved["snapshot_id"]}, {"event": {}})
    other = _entry(ws, "Other")
    with pytest.raises(AutomationActionError, match="another entry"):
        _step(ws, op="restore", snapshot=saved["snapshot_id"], **_on(other))


def test_a_workflow_captures_before_a_change_and_restores_when_a_later_step_fails(ws, sent):
    entry = _entry(ws, "Soup", data_json={})
    row = WorkspaceAutomationModel(
        session=ws.session, group_id=ws.gid, name="Guarded rewrite", slug="guarded-rewrite", enabled=True,
        definition={
            "trigger": {"type": "event", "event": "entry_created"},
            "actions": [
                {"kind": "snapshot", "id": "save", "label": "before rewrite"},
                {"kind": "entry", "op": "set_metadata", "metadata": {"rewritten": True}},
                {"kind": "entry", "op": "add_to_collection", "collection_slug": "${event.payload.collection}"},
            ],
            "on_failure": [{"kind": "snapshot", "op": "restore", "snapshot": "${steps.save.output.snapshot_id}"}],
        },
    )  # fmt: skip
    ws.session.add(row)
    ws.session.commit()
    assert draft_issues(ws.session, ws.gid, row.definition) == []

    ctx = event_context("entry_created", {"entry_id": str(entry.id)}, entity_id=entry.id, entity_type="entry", correlation_id="rewrite-1")
    run_automations_for_event(ws.session, ws.gid, ctx, recorder=ExecutionRecorder(ws.session, ws.gid))

    assert (_reload(ws, entry).metadata_json or {}).get("rewritten") is None  # the change was undone
    (snap,) = snapshots.list_for(ws.session, ws.gid, entry.id)
    assert snap.label == "before rewrite" and snap.source == "workflow" and snap.automation_id == row.id
    ws.session.delete(row)
    ws.session.commit()


def test_the_step_is_validated_guided_and_listed_as_a_sender(ws):
    from marvin.services.events.connections import workflow_sends

    ok = {"trigger": {"type": "manual"}, "actions": [{"kind": "snapshot", "label": "x"}, {"kind": "snapshot", "op": "restore", "parts": ["content"]}]}
    assert draft_issues(ws.session, ws.gid, ok) == []
    for bad in ({"op": "capture", "snapshot": "abc"}, {"op": "restore", "parts": []}, {"op": "restore", "parts": ["tags"]}, {"label": "x" * 101}):
        with pytest.raises(ValueError):
            SnapshotAction(kind="snapshot", **bad)
    actions = authoring_guide(ws.session, ws.gid, "actions")["actions"]
    assert "section=records" in actions["kinds"]["snapshot"]["description"]  # one line in actions; the rest in records
    assert "snapshot_id" in authoring_guide(ws.session, ws.gid, "records")["records"]["snapshot"]["note"]
    assert "entry_updated" in workflow_sends(ok) and "asset_detached_from_entry" in workflow_sends(ok)
    assert "entry_updated" not in workflow_sends({"actions": [{"kind": "snapshot"}]})


# ── The entries API ──────────────────────────────────────────────────────────
def test_the_api_captures_lists_diffs_restores_and_removes_with_the_entry_roles(ws, sent):
    entry = _entry(ws, "Soup")
    admin = gates._sign_in(ws.workspace, AD)
    url = f"{P}/entries/{entry.id}/snapshots"
    made = admin.post(url, json={"label": "v1"})
    assert made.status_code == 201 and made.json()["label"] == "v1" and made.json()["created"] is True and made.json()["source"] == "api"
    assert admin.post(url, json={"label": "v1"}).json()["created"] is False
    _edit(ws, entry, title="Stew")
    sid = made.json()["id"]

    diff = admin.get(f"{url}/{sid}/diff")
    assert diff.status_code == 200 and diff.json()["changed"] is True and diff.json()["content"]["title"] == {"before": "Stew", "after": "Soup"}
    assert _reload(ws, entry).title == "Stew"
    restored = admin.post(f"{url}/{sid}/restore", json={})
    assert restored.status_code == 200 and restored.json()["restored"] is True and _reload(ws, entry).title == "Soup"
    assert [s["id"] for s in admin.get(url).json()] == [sid]
    assert admin.post(f"{url}/{sid}/restore", json={"parts": ["tags"]}).status_code == 422

    assert gates._sign_in(ws.workspace, VI).get(url).status_code == 403
    assert gates._sign_in(ws.workspace, VI).post(url, json={}).status_code == 403
    assert gates._sign_in(ws.workspace, AU, user_id=uuid.uuid4()).post(url, json={}).status_code in (403, 404)  # not their entry
    assert admin.get(f"{P}/entries/{uuid.uuid4()}/snapshots").status_code == 404
    other = _entry(ws, "Other")
    assert admin.get(f"{P}/entries/{other.id}/snapshots/{sid}/diff").status_code == 404  # another entry's snapshot
    assert admin.delete(f"{url}/{sid}").status_code == 204 and admin.get(url).json() == []
    assert admin.delete(f"{url}/{sid}").status_code == 404
