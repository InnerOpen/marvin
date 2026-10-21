# ruff: noqa: F811 — the `workspace` / `model` fixtures are imported, then named as parameters
"""Playbooks 06: a loaded Playbook stays in effect for the thread, replies say which were used, pages show recent uses.

Driven like a person would: several turns of one Ask thread (`POST /api/ai/agent` with `threadId: "new"`, then the id it
returns) against the scripted fake model from test_playbooks, which also records every message list it was sent.
"""

from marvin.db.models.users.roles import WorkspaceRole
from tests import test_content_role_gates as gates
from tests import test_playbooks as base
from tests.test_playbooks import BENCH, BENCH_BODY, _playbook, _turn, model  # noqa: F401 — fixture

workspace = gates.workspace  # fixture: a workspace with a signed-in user

HEADING = "## Playbooks loaded earlier in this conversation"


class Recording(base.FakeModel):
    """The scripted model, remembering the whole message list of each request."""

    def __init__(self):
        super().__init__()
        self.requests: list[list] = []

    def complete_with_tools(self, messages, model, tools, options=None, tool_choice="auto"):
        self.requests.append(list(messages))
        return super().complete_with_tools(messages, model, tools, options, tool_choice)


import uuid  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture
def model(monkeypatch):
    from marvin.routes.ai.operations_controller import AIOperationsController

    fake = Recording()
    monkeypatch.setattr(AIOperationsController, "_agent_provider", lambda self: fake)
    monkeypatch.setattr(AIOperationsController, "_default_model", lambda self: "m")
    return fake


def _turn_on(client, message, thread="new") -> dict:
    res = client.post("/api/ai/agent", json={"message": message, "source": "api", "threadId": thread})
    assert res.status_code == 200, res.text
    return res.json()


def _thread(client, thread_id) -> dict:
    res = client.get(f"/api/ai/threads/{thread_id}")
    assert res.status_code == 200, res.text
    return res.json()


def test_a_playbook_loaded_on_turn_one_is_still_in_the_prompt_on_later_turns(workspace, db_session, model):
    _playbook(db_session, workspace.gid)
    client = gates._sign_in(workspace, WorkspaceRole.AUTHOR)

    first = _turn_on(client, f"Write a bench note, use {BENCH}")
    assert [s["tool"] for s in first["steps"]][0] == "load_playbook"
    assert HEADING not in model.systems[0]  # nothing to remember before it is loaded

    second = _turn_on(client, "Now make it shorter", first["threadId"])
    third = _turn_on(client, "And friendlier", first["threadId"])
    assert second["steps"] == [] and third["steps"] == []  # neither turn loaded it again
    for system in model.systems[-2:]:
        assert HEADING in system and BENCH_BODY in system

    # The reason it is re-included: the old tool result is not replayed, only the words.
    replayed = model.requests[-1]
    assert not any(m.role == "tool" for m in replayed)
    assert BENCH_BODY not in "".join(m.content or "" for m in replayed[1:])


def test_the_text_comes_from_the_playbook_as_published_now(workspace, db_session, model):
    row = _playbook(db_session, workspace.gid)
    client = gates._sign_in(workspace, WorkspaceRole.AUTHOR)
    first = _turn_on(client, f"use {BENCH}")

    row.data_json = {**row.data_json, "body": "A revised procedure."}
    db_session.commit()
    _turn_on(client, "again", first["threadId"])
    assert "A revised procedure." in model.systems[-1] and BENCH_BODY not in model.systems[-1]

    row.status = "draft"  # unpublished: an agent may not see it, so the thread stops carrying it
    db_session.commit()
    _turn_on(client, "once more", first["threadId"])
    assert HEADING not in model.systems[-1]


def test_a_thread_without_a_playbook_and_a_stateless_run_add_nothing(workspace, db_session, model):
    _playbook(db_session, workspace.gid)
    client = gates._sign_in(workspace, WorkspaceRole.AUTHOR)
    first = _turn_on(client, "Say hello")
    _turn_on(client, "and again", first["threadId"])
    stateless = client.post("/api/ai/agent", json={"message": f"use {BENCH}", "source": "api"}).json()
    client.post("/api/ai/agent", json={"message": "no thread here", "source": "api"})
    assert all(HEADING not in s for s in model.systems[:2])
    assert stateless["playbooks"] == [{"id": stateless["playbooks"][0]["id"], "name": BENCH}]
    assert HEADING not in model.systems[-1]


def test_replies_name_the_playbooks_in_effect_and_the_thread_stores_them(workspace, db_session, model):
    row = _playbook(db_session, workspace.gid)
    client = gates._sign_in(workspace, WorkspaceRole.AUTHOR)
    first = _turn_on(client, f"use {BENCH}")
    second = _turn_on(client, "shorter please", first["threadId"])
    expected = [{"id": str(row.id), "name": BENCH}]
    assert first["playbooks"] == expected
    assert second["playbooks"] == expected  # still in effect, so the reply still says so
    assert "Used" not in second["answer"] and BENCH not in second["answer"]  # shown by the UI, not written by the model
    assistants = [m for m in _thread(client, first["threadId"])["messages"] if m["role"] == "assistant"]
    assert [m["metaJson"]["playbooks"] for m in assistants] == [expected, expected]


def test_a_thread_that_never_loaded_one_has_no_playbooks_key(workspace, db_session, model):
    _playbook(db_session, workspace.gid)
    client = gates._sign_in(workspace, WorkspaceRole.AUTHOR)
    first = _turn_on(client, "Say hello")
    assert first["playbooks"] == []
    assistant = [m for m in _thread(client, first["threadId"])["messages"] if m["role"] == "assistant"][0]
    assert "playbooks" not in assistant["metaJson"]


# ── Used recently ────────────────────────────────────────────────────────────

P = "/api/groups/playbooks"


def test_the_page_shows_where_a_playbook_was_used_lately(workspace, db_session, model):
    row = _playbook(db_session, workspace.gid)
    unused = _playbook(db_session, workspace.gid, "never-used")
    author = gates._sign_in(workspace, WorkspaceRole.AUTHOR)
    first = _turn_on(author, f"use {BENCH}")
    _turn_on(author, "shorter please", first["threadId"])  # a re-include is not a new use
    stateless = author.post("/api/ai/agent", json={"message": f"use {BENCH}", "source": "api"}).json()

    editor = gates._sign_in(workspace, WorkspaceRole.EDITOR, user_id=uuid.uuid4())  # another person
    uses = editor.get(f"{P}/{row.id}/uses").json()["items"]
    assert [u["executionId"] for u in uses] == [stateless["executionId"], first["executionId"]]
    newest, oldest = uses
    assert newest["agentSlug"] and newest["agentName"] and newest["usedAt"]
    assert newest["threadId"] is None  # a run with no conversation: nothing to link
    assert oldest["threadId"] is None  # the thread is the author's, not this editor's
    assert editor.get(f"{P}/{unused.id}/uses").json() == {"items": []}

    items = {i["name"]: i for i in editor.get(P).json()["items"]}
    assert items[BENCH]["lastUsedAt"] and items["never-used"]["lastUsedAt"] is None

    viewer = gates._sign_in(workspace, WorkspaceRole.VIEWER)
    assert viewer.get(f"{P}/{row.id}/uses").status_code == 403


def test_an_owner_of_the_run_gets_the_link_to_it(workspace, db_session, model):
    row = _playbook(db_session, workspace.gid)
    admin = gates._sign_in(workspace, WorkspaceRole.ADMIN)
    first = _turn_on(admin, f"use {BENCH}")
    uses = admin.get(f"{P}/{row.id}/uses").json()["items"]
    assert uses[0]["threadId"] == first["threadId"]


def test_uses_of_a_playbook_that_is_not_here_is_a_404(workspace, db_session):
    assert gates._sign_in(workspace, WorkspaceRole.EDITOR).get(f"{P}/{uuid.uuid4()}/uses").status_code == 404
