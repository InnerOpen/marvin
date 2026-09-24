"""Tests for the `run_integration_action` scheduled-task handler.

The handler is the only core piece of the "poll a provider on a schedule" path: it loads entries
into a provider action's arguments, persists the returned records as entries (deduped by slug),
and writes back a rotated credential. Requires the SDK to build a fake provider, so it skips when
no integration package is installed.
"""

import uuid
from types import SimpleNamespace

import pytest
from pytest import fixture

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider  # noqa: E402

from marvin.db.models.groups.groups import Groups  # noqa: E402
from marvin.db.models.groups.integrations import IntegrationModel  # noqa: E402
from marvin.db.models.platform.entries import Entries  # noqa: E402
from marvin.db.models.platform.entry_types import EntryTypes  # noqa: E402
from marvin.db.models.platform.event_log import EventLogModel  # noqa: E402
from marvin.services.scheduled_tasks.handlers import integrations as handler_mod  # noqa: E402
from marvin.services.scheduled_tasks.handlers.integrations import RunIntegrationActionHandler  # noqa: E402

RULES_TYPE = "ig-auto-reply"
LOG_TYPE = "ig-reply-log"


class _FakeProvider(IntegrationProvider):
    slug = "fake_ig"
    name = "Fake IG"

    def __init__(self):
        self.calls: list[tuple[str, dict, object]] = []
        self.result: dict = {}

    def run_action(self, key, args, ctx):
        self.calls.append((key, args, ctx))
        return self.result


class _RecordingSecrets:
    def __init__(self):
        self.written: list[tuple[str, str, object]] = []

    def get(self, slug, group_id=None):
        return "tok"

    def set(self, slug, value, group_id=None):
        self.written.append((slug, value, group_id))


@fixture
def provider(monkeypatch):
    p = _FakeProvider()
    monkeypatch.setitem(INTEGRATION_REGISTRY, p.slug, p)
    return p


@fixture
def secrets(monkeypatch):
    backend = _RecordingSecrets()
    monkeypatch.setattr("marvin.services.secrets.resolver.resolve_secret", lambda ref, gid=None: "tok")
    monkeypatch.setattr("marvin.services.secrets.factory.get_secret_backend", lambda: backend)
    monkeypatch.setattr("marvin.services.secrets.get_secret_backend", lambda: backend)
    return backend


@fixture
def workspace(db_session):
    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"ig-{marker}", slug=f"ig-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    rules_type = EntryTypes(
        session=db_session,
        group_id=gid,
        name="IG rule",
        slug=RULES_TYPE,
        schema_json={"fields": [{"key": "keywords", "label": "Keywords", "type": "text"}, {"key": "reply", "label": "Reply", "type": "textarea"}]},
    )
    log_type = EntryTypes(
        session=db_session,
        group_id=gid,
        name="IG reply log",
        slug=LOG_TYPE,
        schema_json={"fields": [{"key": "comment_id", "label": "Comment", "type": "text", "required": True}]},
    )
    db_session.add_all([rules_type, log_type])
    db_session.flush()
    db_session.add_all(
        [
            Entries(
                session=db_session,
                group_id=gid,
                entry_type_id=rules_type.id,
                title="Size rule",
                slug=f"size-{marker}",
                status="published",
                data_json={"keywords": "size, sizing", "reply": "S–XL"},
            ),
            Entries(
                session=db_session,
                group_id=gid,
                entry_type_id=rules_type.id,
                title="Draft rule",
                slug=f"draft-{marker}",
                status="draft",
                data_json={"keywords": "price", "reply": "not yet"},
            ),
            Entries(
                session=db_session,
                group_id=gid,
                entry_type_id=log_type.id,
                title="old reply",
                slug="ig-reply-c0",
                status="draft",
                data_json={"comment_id": "c0"},
            ),
        ]
    )
    db_session.add(
        IntegrationModel(
            session=db_session,
            group_id=gid,
            provider="fake_ig",
            name="IG",
            slug="ig",
            enabled=True,
            config={"ig_user_id": "1"},
            secret_ref="INTEGRATION_IG",
        )
    )
    db_session.commit()

    yield gid

    # entry_created (emitted when the handler persists records) writes an audit row per entry
    db_session.query(EventLogModel).filter(EventLogModel.workspace_id == gid).delete()
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.query(IntegrationModel).filter(IntegrationModel.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


TASK_CONFIG = {
    "integration": "ig",
    "action": "auto_reply",
    "args": {"dry_run": True, "max_age_days": 7},
    "inputs": {
        "rules": {"entry_type": RULES_TYPE, "status": "published", "as": "records"},
        "skip_comment_ids": {"entry_type": LOG_TYPE, "as": "field", "field": "comment_id"},
    },
    "outputs": {
        "records_entry_type": LOG_TYPE,
        "slug_prefix": "ig-reply-",
        "slug_field": "comment_id",
        "title_template": "Reply to @{username} ({keyword})",
        "status": "draft",
    },
}


def _run(gid, config=TASK_CONFIG):
    task = SimpleNamespace(group_id=gid, task_config=config)
    return RunIntegrationActionHandler().execute(task, SimpleNamespace(dispatch=lambda **_: None))


def test_inputs_come_from_entry_data_json(db_session, workspace, provider, secrets):
    skipped = [{"comment_id": "c0", "reason": "already_replied"}]
    provider.result = {"checked": 4, "matched": 1, "sent": 0, "dry_run": True, "records": [], "skipped": skipped}

    summary = _run(workspace)

    key, args, ctx = provider.calls[0]
    assert key == "auto_reply"
    assert args["dry_run"] is True and args["max_age_days"] == 7
    assert [r["reply"] for r in args["rules"]] == ["S–XL"]  # only the published rule
    assert args["rules"][0]["keywords"] == "size, sizing" and "slug" in args["rules"][0]
    assert args["skip_comment_ids"] == ["c0"]
    assert ctx.secret == "tok" and ctx.config == {"ig_user_id": "1"}
    assert summary == "ig.auto_reply: checked=4 matched=1 sent=0 skipped=1 (dry run) → 0 log entries"


def test_records_become_entries_once(db_session, workspace, provider, secrets):
    record = {"comment_id": "c1", "media_id": "m1", "username": "fan", "keyword": "size", "reply": "S–XL", "text": "size?", "sent_at": "now"}
    provider.result = {"checked": 1, "matched": 1, "sent": 1, "dry_run": False, "records": [record], "skipped": []}

    first = _run(workspace)
    second = _run(workspace)

    assert first.endswith("→ 1 log entry")
    assert second.endswith("→ 0 log entries")
    rows = db_session.query(Entries).filter(Entries.group_id == workspace, Entries.slug == "ig-reply-c1").all()
    assert len(rows) == 1
    assert rows[0].title == "Reply to @fan (size)"
    assert rows[0].status == "draft"
    assert rows[0].data_json["comment_id"] == "c1"
    # the new log entry now feeds skip_comment_ids on the next run
    assert sorted(provider.calls[1][1]["skip_comment_ids"]) == ["c0", "c1"]


def test_secret_update_is_written_to_backend(db_session, workspace, provider, secrets):
    provider.result = {"expires_in": 5183944, "secret_update": "new-tok"}

    summary = _run(workspace, {"integration": "ig", "action": "refresh_token"})

    assert secrets.written == [("INTEGRATION_IG", "new-tok", workspace)]
    assert "credential rotated" in summary
    row = db_session.query(IntegrationModel).filter_by(group_id=workspace, slug="ig").first()
    db_session.refresh(row)
    assert row.secret_ref == "INTEGRATION_IG"


def test_guards_return_messages_instead_of_raising(db_session, workspace, provider, secrets, monkeypatch):
    assert "workspace" in _run(None)
    assert "not found" in _run(workspace, {**TASK_CONFIG, "integration": "ghost"})
    assert "needs 'integration'" in _run(workspace, {"action": "x"})

    row = db_session.query(IntegrationModel).filter_by(group_id=workspace, slug="ig").first()
    row.enabled = False
    db_session.commit()
    assert "disabled" in _run(workspace)
    row.enabled = True
    db_session.commit()

    monkeypatch.delitem(INTEGRATION_REGISTRY, "fake_ig")
    assert "not installed" in _run(workspace)
    assert provider.calls == []


def test_sdk_missing_short_circuits(monkeypatch, workspace):
    monkeypatch.setattr("marvin.services.integrations.INTEGRATIONS_AVAILABLE", False)
    assert "SDK not installed" in _run(workspace)


def test_provider_error_propagates_as_failure(db_session, workspace, provider, secrets):
    def boom(key, args, ctx):
        raise ValueError("Instagram API error: HTTP 401")

    provider.run_action = boom
    with pytest.raises(ValueError, match="HTTP 401"):
        _run(workspace)


def test_handler_is_registered_but_not_automation_allowed():
    from marvin.services.automation.actions.handler import AUTOMATION_ALLOWED_HANDLERS
    from marvin.services.scheduled_tasks import TaskHandlerRegistry

    assert TaskHandlerRegistry.is_registered("run_integration_action")
    assert "run_integration_action" not in AUTOMATION_ALLOWED_HANDLERS
    assert handler_mod.RunIntegrationActionHandler.config_schema["required"] == ["integration", "action"]
