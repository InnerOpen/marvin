# ruff: noqa: F811 — the `client` / `on` / `ws` fixtures are imported, then named as parameters
"""Playbooks 04: reference files.

A Playbook carries files (examples, checklists, a tone guide) attached with their relative paths kept. The agent sees
an index when it loads the Playbook and reads one file only when the instructions point to it. Driven through the
service (attach, list, remove) and through an agent run with a scripted fake model.
"""

import io
import json
import re
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from marvin.services.ai.base import ToolCall
from marvin.services.playbooks import PlaybookFileError, attach_reference, reference_files, remove_reference
from tests import test_content_role_gates as gates
from tests.test_playbooks import (  # noqa: F401 — fixtures and helpers shared with Playbooks 01
    BENCH,
    FakeModel,
    _ask,
    _playbook,
    _tools_called,
    _turn,
    model,
)
from tests.test_remote_mcp_oauth import client, on, ws  # noqa: F401 — fixtures

workspace = gates.workspace

TONE = "Warm, dry, never exclamation marks. Say 'batch', not 'run'."
BODY_WITH_POINTER = "# Bench Note voice\n\nFor the exact tone, read references/tone.md before you write."


@pytest.fixture
def store(monkeypatch):
    """Storage stand-in: storage_key -> bytes."""
    files: dict[str, bytes] = {}
    monkeypatch.setattr(
        "marvin.services.storage.provider_factory.provider_for", lambda asset: SimpleNamespace(get=lambda key: io.BytesIO(files[key]))
    )
    return files


def _asset(db_session, gid, uid, store, name="tone.md", text=TONE, *, trashed=False):
    from marvin.db.models.platform import Assets

    slug = f"{name}-{uuid.uuid4().hex[:6]}"
    row = Assets(
        session=db_session, group_id=gid, slug=slug, name=name, original_filename=name, filename=name, extension=name.rsplit(".", 1)[-1],
        file_size=len(text), mime_type="text/markdown", asset_type="document", checksum=uuid.uuid4().hex,
        storage_provider="local", storage_key=f"pb/{slug}", uploaded_by=uid, trashed_at=datetime.now(UTC) if trashed else None,
    )  # fmt: skip
    store[row.storage_key] = text.encode()
    db_session.add(row)
    db_session.commit()
    return row


def _ctx(workspace, db_session):
    from marvin.services.ai.tools.base import ToolContext

    return ToolContext(session=db_session, group_id=workspace.gid)


def _read(workspace, db_session, playbook, path, **kw):
    from marvin.services.ai.tools.builtins_playbooks import read_playbook_file

    return json.loads(read_playbook_file(_ctx(workspace, db_session), {"playbook": playbook, "path": path, **kw}))


# ── Attach, list, remove ─────────────────────────────────────────────────────


def test_a_reference_file_keeps_its_relative_path(workspace, db_session, store):
    pb = _playbook(db_session, workspace.gid)
    tone = _asset(db_session, workspace.gid, workspace.uid, store)

    attached = attach_reference(db_session, workspace.gid, pb.id, tone.id, "./references//tone.md")

    assert attached.path == "references/tone.md"
    assert [f.path for f in reference_files(db_session, pb.id)] == ["references/tone.md"]


def test_files_are_listed_by_path_and_one_can_be_removed_without_deleting_the_asset(workspace, db_session, store):
    pb = _playbook(db_session, workspace.gid)
    a, b = (_asset(db_session, workspace.gid, workspace.uid, store, n) for n in ("a.md", "b.md"))
    attach_reference(db_session, workspace.gid, pb.id, b.id, "references/b.md")
    attach_reference(db_session, workspace.gid, pb.id, a.id, "examples/a.md")

    assert [f.path for f in reference_files(db_session, pb.id)] == ["examples/a.md", "references/b.md"]
    assert remove_reference(db_session, workspace.gid, pb.id, "examples/a.md") is True
    assert remove_reference(db_session, workspace.gid, pb.id, "examples/a.md") is False
    assert [f.path for f in reference_files(db_session, pb.id)] == ["references/b.md"]
    db_session.refresh(a)
    assert a.trashed_at is None


@pytest.mark.parametrize("bad", ["", "/etc/passwd", "../secrets.md", "references/../../x", "a\\b.md", "."])
def test_a_path_that_leaves_the_playbook_is_refused(workspace, db_session, store, bad):
    pb = _playbook(db_session, workspace.gid)
    tone = _asset(db_session, workspace.gid, workspace.uid, store)
    with pytest.raises(PlaybookFileError):
        attach_reference(db_session, workspace.gid, pb.id, tone.id, bad)


def test_a_taken_path_and_a_foreign_or_trashed_asset_are_refused(workspace, db_session, store):
    pb = _playbook(db_session, workspace.gid)
    one, two = (_asset(db_session, workspace.gid, workspace.uid, store, n) for n in ("one.md", "two.md"))
    dead = _asset(db_session, workspace.gid, workspace.uid, store, "dead.md", trashed=True)
    attach_reference(db_session, workspace.gid, pb.id, one.id, "references/x.md")

    with pytest.raises(PlaybookFileError, match="already has a file"):
        attach_reference(db_session, workspace.gid, pb.id, two.id, "references/x.md")
    with pytest.raises(PlaybookFileError, match="No such asset"):
        attach_reference(db_session, workspace.gid, pb.id, dead.id, "references/dead.md")
    with pytest.raises(PlaybookFileError, match="No such asset"):
        attach_reference(db_session, workspace.gid, pb.id, uuid.uuid4(), "references/none.md")
    with pytest.raises(PlaybookFileError, match="No such Playbook"):
        attach_reference(db_session, uuid.uuid4(), pb.id, one.id, "references/y.md")


# ── The tools ────────────────────────────────────────────────────────────────


def test_load_playbook_returns_an_index_not_the_contents(workspace, db_session, store):
    from marvin.services.ai.tools.builtins_playbooks import load_playbook

    pb = _playbook(db_session, workspace.gid, body=BODY_WITH_POINTER)
    attach_reference(db_session, workspace.gid, pb.id, _asset(db_session, workspace.gid, workspace.uid, store).id, "references/tone.md")

    out = json.loads(load_playbook(_ctx(workspace, db_session), {"name": BENCH}))

    assert [f["path"] for f in out["files"]] == ["references/tone.md"]
    assert TONE not in json.dumps(out)


def test_a_published_playbook_file_is_read(workspace, db_session, store):
    pb = _playbook(db_session, workspace.gid)
    attach_reference(db_session, workspace.gid, pb.id, _asset(db_session, workspace.gid, workspace.uid, store).id, "references/tone.md")

    out = _read(workspace, db_session, BENCH, "references/tone.md")

    assert out["text"] == TONE and out["path"] == "references/tone.md"


def test_a_draft_another_workspace_and_unknown_paths_are_refused(workspace, db_session, store):
    draft = _playbook(db_session, workspace.gid, "draft-one", status="draft")
    pb = _playbook(db_session, workspace.gid)
    tone = _asset(db_session, workspace.gid, workspace.uid, store)
    attach_reference(db_session, workspace.gid, draft.id, tone.id, "references/tone.md")
    attach_reference(db_session, workspace.gid, pb.id, _asset(db_session, workspace.gid, workspace.uid, store, "b.md").id, "references/b.md")

    assert "error" in _read(workspace, db_session, "draft-one", "references/tone.md")
    assert TONE not in json.dumps(_read(workspace, db_session, "draft-one", "references/tone.md"))
    unknown = _read(workspace, db_session, BENCH, "references/missing.md")
    assert "error" in unknown and unknown["files"] == ["references/b.md"]
    assert "error" in _read(workspace, db_session, BENCH, "../references/b.md")

    other = SimpleNamespace(gid=uuid.uuid4(), uid=workspace.uid)
    assert "error" in _read(other, db_session, BENCH, "references/b.md")


def test_a_file_trashed_after_attaching_is_no_longer_read(workspace, db_session, store):
    pb = _playbook(db_session, workspace.gid)
    tone = _asset(db_session, workspace.gid, workspace.uid, store)
    attach_reference(db_session, workspace.gid, pb.id, tone.id, "references/tone.md")
    tone.trashed_at = datetime.now(UTC)
    db_session.commit()

    assert "error" in _read(workspace, db_session, BENCH, "references/tone.md")


# ── The run ──────────────────────────────────────────────────────────────────


class ReadingModel(FakeModel):
    """Loads the Playbook, then reads the file the instructions it was given point to, then answers with it."""

    def complete_with_tools(self, messages, model, tools, options=None, tool_choice="auto"):
        last = messages[-1]
        if last.role == "tool":
            called = [c for m in messages if m.role == "assistant" and m.tool_calls for c in m.tool_calls]
            if called[-1].name == "load_playbook":
                loaded = json.loads(last.content)
                pointed = re.search(r"read (\S+\.md)", loaded["body"])
                assert pointed and pointed.group(1) in [f["path"] for f in loaded["files"]]
                return _turn(
                    tool_calls=[ToolCall(id="c2", name="read_playbook_file", arguments={"playbook": loaded["name"], "path": pointed.group(1)})]
                )
            return _turn(content="Tone: " + json.loads(last.content)["text"])
        return super().complete_with_tools(messages, model, tools, options, tool_choice)


def test_the_agent_reads_the_reference_file_the_playbook_points_to(workspace, db_session, store, monkeypatch):
    from marvin.routes.ai.operations_controller import AIOperationsController

    fake = ReadingModel()
    monkeypatch.setattr(AIOperationsController, "_agent_provider", lambda self: fake)
    monkeypatch.setattr(AIOperationsController, "_default_model", lambda self: "m")
    pb = _playbook(db_session, workspace.gid, body=BODY_WITH_POINTER)
    attach_reference(db_session, workspace.gid, pb.id, _asset(db_session, workspace.gid, workspace.uid, store).id, "references/tone.md")

    run = _ask(workspace, f"Please draft a {BENCH}.")

    assert _tools_called(run) == ["load_playbook", "read_playbook_file"]
    assert "read_playbook_file" in fake.tool_names[0]
    assert run["answer"] == "Tone: " + TONE
