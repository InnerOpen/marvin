# ruff: noqa: F811 — the `client` / `on` / `ws` fixtures are imported, then named as parameters
"""Playbooks 05: per-agent Playbook settings.

Driven like a user would: agents are defined through the settings API and run through `POST /api/ai/agents/{slug}/run` with
the scripted model from the Playbooks 01 tests, which reads its own system prompt and the catalog in it.

Rules under test: a chosen set narrows the catalog, `load_playbook` and `read_playbook_file`; up to three "always load"
Playbooks ride in full in the system frame (a fourth is refused, a size warning shows); a manual-only Playbook is not in the
catalog and loads only when the user's message names it.
"""

import pytest

from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.ai.base import ToolCall
from marvin.services.playbooks import ALWAYS_WARN_CHARS, PlaybookScope, is_named
from tests import test_content_role_gates as gates
from tests.test_playbooks import FakeModel, _invoke, _playbook, _tools_called, _turn, model, workspace  # noqa: F401 — fixtures

MANUAL = "refund-policy"


@pytest.fixture(autouse=True)
def _drop_agents(workspace, db_session):
    """Agents made through the API (SQLite doesn't cascade them with the workspace)."""
    yield
    from marvin.db.models.groups.agents import WorkspaceAgentModel

    db_session.rollback()
    db_session.query(WorkspaceAgentModel).filter_by(group_id=workspace.gid).delete()
    db_session.commit()


def _agent(workspace, slug="writer", *, playbooks=None, expect=201, **extra):
    body = {"slug": slug, "name": slug.title(), "allow_writes": False, **extra}
    if playbooks is not None:
        body["playbooks"] = playbooks
    res = gates._sign_in(workspace, WorkspaceRole.ADMIN).post("/api/ai/agents", json=body)
    assert res.status_code == expect, res.text
    return res.json()


def _run(workspace, slug, message) -> dict:
    res = gates._sign_in(workspace, WorkspaceRole.AUTHOR).post(f"/api/ai/agents/{slug}/run", json={"message": message, "source": "api"})
    assert res.status_code == 200, res.text
    return res.json()


def _manual(db_session, gid, name=MANUAL):
    row = _playbook(db_session, gid, name, description="How to handle a refund.", body="Refund within 30 days.")
    row.data_json = {**row.data_json, "manual_only": True}
    db_session.commit()
    return row


def _catalog(system: str) -> str:
    return system.split("## Playbooks\n", 1)[1] if "## Playbooks\n" in system else ""


# ── Chosen set ───────────────────────────────────────────────────────────────


def test_an_agent_defaults_to_all_published_playbooks(workspace, db_session, model):
    _playbook(db_session, workspace.gid, "alpha-voice")
    _playbook(db_session, workspace.gid, "beta-voice")
    agent = _agent(workspace)
    assert agent["playbooks"] is None

    _run(workspace, "writer", "hello")
    catalog = _catalog(model.systems[-1])
    assert "- alpha-voice:" in catalog and "- beta-voice:" in catalog


def test_a_chosen_set_narrows_the_catalog(workspace, db_session, model):
    _playbook(db_session, workspace.gid, "alpha-voice")
    _playbook(db_session, workspace.gid, "beta-voice")
    _agent(workspace, playbooks={"names": ["alpha-voice"]})

    _run(workspace, "writer", "hello")
    catalog = _catalog(model.systems[-1])
    assert "- alpha-voice:" in catalog
    assert "beta-voice" not in catalog


def test_load_playbook_refuses_one_outside_the_chosen_set_without_saying_it_exists(workspace, db_session, model):
    _playbook(db_session, workspace.gid, "alpha-voice")
    _playbook(db_session, workspace.gid, "beta-voice")
    _agent(workspace, playbooks={"names": ["alpha-voice"]})

    run = _run(workspace, "writer", "load playbook beta-voice")
    step = next(s for s in run["steps"] if s["tool"] == "load_playbook")
    assert "No published Playbook named 'beta-voice'" in step["result"]
    assert "Bench" not in step["result"] and "available" in step["result"]
    assert 'beta-voice"' not in step["result"].split("available")[1]  # the list of what exists leaves it out
    assert run["steps"] and not _used(run)


def test_load_playbook_loads_one_in_the_chosen_set(workspace, db_session, model):
    _playbook(db_session, workspace.gid, "alpha-voice")
    _agent(workspace, playbooks={"names": ["alpha-voice"]})

    run = _run(workspace, "writer", "load playbook alpha-voice")
    assert "load_playbook" in _tools_called(run) and "# Bench Note voice" in run["steps"][0]["result"]


def test_an_empty_chosen_set_offers_nothing(workspace, db_session, model):
    _playbook(db_session, workspace.gid, "alpha-voice")
    _agent(workspace, playbooks={"names": []})

    _run(workspace, "writer", "hello")
    assert "## Playbooks" not in model.systems[-1]


def test_read_playbook_file_respects_the_chosen_set(workspace, db_session):
    from marvin.services.playbooks import published_playbook_file, published_playbook_files

    _playbook(db_session, workspace.gid, "alpha-voice")
    outside = PlaybookScope(names=("beta-voice",))
    assert published_playbook_files(db_session, workspace.gid, "alpha-voice", outside) is None
    assert published_playbook_files(db_session, workspace.gid, "alpha-voice", PlaybookScope(names=("alpha-voice",))) == []
    assert published_playbook_file(db_session, workspace.gid, "alpha-voice", "references/x.md", outside) is None


def test_the_settings_survive_a_patch_and_null_goes_back_to_all(workspace, db_session):
    _playbook(db_session, workspace.gid, "alpha-voice")
    _agent(workspace, playbooks={"names": ["alpha-voice"], "always": ["alpha-voice"]})
    admin = gates._sign_in(workspace, WorkspaceRole.ADMIN)

    got = admin.get("/api/ai/agents/writer").json()
    assert got["playbooks"] == {"names": ["alpha-voice"], "always": ["alpha-voice"]}
    patched = admin.patch("/api/ai/agents/writer", json={"playbooks": None})
    assert patched.status_code == 200 and patched.json()["playbooks"] is None


# ── Always load ──────────────────────────────────────────────────────────────


def test_always_load_puts_the_playbook_in_full_in_the_system_frame(workspace, db_session, model):
    _playbook(db_session, workspace.gid, "alpha-voice", body="ALPHA STEPS: one, two.")
    _playbook(db_session, workspace.gid, "beta-voice", body="BETA STEPS.")
    _agent(workspace, playbooks={"always": ["alpha-voice"]})

    _run(workspace, "writer", "hello")
    system = model.systems[-1]
    assert "ALPHA STEPS: one, two." in system
    assert "BETA STEPS." not in system  # only listed in the catalog, not loaded
    assert system.index("ALPHA STEPS") > system.index("## Playbooks\n")  # after the catalog


def test_an_agent_without_always_load_carries_no_playbook_text(workspace, db_session, model):
    _playbook(db_session, workspace.gid, "alpha-voice", body="ALPHA STEPS.")
    _agent(workspace)
    _run(workspace, "writer", "hello")
    assert "ALPHA STEPS." not in model.systems[-1]


def test_a_fourth_always_load_is_refused(workspace, db_session):
    for n in ("a-one", "a-two", "a-three", "a-four"):
        _playbook(db_session, workspace.gid, n)
    _agent(workspace, "ok", playbooks={"always": ["a-one", "a-two", "a-three"]})
    res = _agent(workspace, "too-many", playbooks={"always": ["a-one", "a-two", "a-three", "a-four"]}, expect=422)
    assert "3" in str(res)  # pydantic's own limit
    admin = gates._sign_in(workspace, WorkspaceRole.ADMIN)
    patched = admin.patch("/api/ai/agents/ok", json={"playbooks": {"always": ["a-one", "a-two", "a-three", "a-four"]}})
    assert patched.status_code == 422


def test_always_load_must_be_in_the_chosen_set_published_and_not_manual_only(workspace, db_session):
    _playbook(db_session, workspace.gid, "alpha-voice")
    _playbook(db_session, workspace.gid, "draft-voice", status="draft")
    _manual(db_session, workspace.gid)

    outside = _agent(workspace, "w1", playbooks={"names": ["alpha-voice"], "always": [MANUAL]}, expect=422)
    assert "chosen set" in outside["detail"]
    draft = _agent(workspace, "w2", playbooks={"always": ["draft-voice"]}, expect=422)
    assert "published" in draft["detail"]
    manual = _agent(workspace, "w3", playbooks={"always": [MANUAL]}, expect=422)
    assert "manual-only" in manual["detail"]


def test_a_size_warning_shows_in_the_prompt_preview_when_the_always_load_text_is_long(workspace, db_session):
    _playbook(db_session, workspace.gid, "long-one", body="x" * (ALWAYS_WARN_CHARS + 1))
    _playbook(db_session, workspace.gid, "short-one", body="short")
    _agent(workspace, "big", playbooks={"always": ["long-one"]})
    _agent(workspace, "small", playbooks={"always": ["short-one"]})
    admin = gates._sign_in(workspace, WorkspaceRole.ADMIN)

    big = admin.post("/api/ai/agents/big/preview-prompt", json={}).json()
    small = admin.post("/api/ai/agents/small/preview-prompt", json={}).json()
    assert "tokens" in big["playbooksWarning"] and small["playbooksWarning"] is None
    assert "x" * 50 in big["system"]  # the preview shows what a run sends


def test_the_preview_reflects_unsaved_playbook_settings(workspace, db_session):
    _playbook(db_session, workspace.gid, "alpha-voice", body="ALPHA STEPS.")
    _agent(workspace)
    admin = gates._sign_in(workspace, WorkspaceRole.ADMIN)
    res = admin.post("/api/ai/agents/writer/preview-prompt", json={"playbooks": {"always": ["alpha-voice"]}}).json()
    assert "ALPHA STEPS." in res["system"]


# ── Manual only ──────────────────────────────────────────────────────────────


def test_a_manual_only_playbook_is_not_in_the_catalog(workspace, db_session, model):
    _playbook(db_session, workspace.gid, "alpha-voice")
    _manual(db_session, workspace.gid)
    _agent(workspace)

    _run(workspace, "writer", "hello")
    catalog = _catalog(model.systems[-1])
    assert "- alpha-voice:" in catalog and MANUAL not in catalog


def test_load_playbook_refuses_a_manual_only_playbook_the_user_did_not_name(workspace, db_session, model, monkeypatch):
    _manual(db_session, workspace.gid)
    _agent(workspace)
    # A model that reaches for it on its own, whatever the user wrote.
    original = FakeModel.complete_with_tools

    def eager(self, messages, model, tools, options=None, tool_choice="auto"):
        if messages[-1].role != "tool":
            self.systems.append(messages[0].content)
            return _turn(tool_calls=[ToolCall(id="c1", name="load_playbook", arguments={"name": MANUAL})])
        return original(self, messages, model, tools, options, tool_choice)

    monkeypatch.setattr(FakeModel, "complete_with_tools", eager)

    run = _run(workspace, "writer", "I need help with a customer.")
    step = run["steps"][0]
    assert step["tool"] == "load_playbook" and "manual-only" in step["result"]
    assert "Refund within 30 days." not in step["result"]
    assert not _used(run)


def test_naming_a_manual_only_playbook_in_the_message_lets_it_load(workspace, db_session, model):
    _manual(db_session, workspace.gid)
    _agent(workspace)
    run = _run(workspace, "writer", "Use the Refund Policy playbook for this one. load playbook refund-policy")
    step = run["steps"][0]
    assert "Refund within 30 days." in step["result"]
    assert [p["name"] for p in _used(run)] == [MANUAL]


def test_manual_only_never_loads_for_callers_without_an_agent_message(workspace, db_session):
    _manual(db_session, workspace.gid)
    out = _invoke(workspace, "load_playbook", {"name": MANUAL})
    assert "manual-only" in str(out)
    assert MANUAL not in str(_invoke(workspace, "list_playbooks", {}))


def test_a_manual_only_playbook_outside_the_chosen_set_is_not_acknowledged(workspace, db_session, model):
    _manual(db_session, workspace.gid)
    _playbook(db_session, workspace.gid, "alpha-voice")
    _agent(workspace, playbooks={"names": ["alpha-voice"]})
    run = _run(workspace, "writer", f"load playbook {MANUAL}")
    assert "No published Playbook" in run["steps"][0]["result"]


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("use refund-policy here", True),
        ("Use the Refund Policy playbook", True),
        ("REFUND_POLICY please", True),
        ("(refund-policy)", True),
        ("refund policies are long", False),
        ("a refund-policy-v2 exists", False),
        ("myrefund-policy", False),
        ("refund and policy", False),
        ("", False),
        (None, False),
    ],
)
def test_what_counts_as_naming_a_playbook(text, named):
    assert is_named("refund-policy", text) is named


def _used(run):
    from types import SimpleNamespace

    from marvin.services.playbooks import playbooks_used

    return playbooks_used([SimpleNamespace(tool=s["tool"], result=s["result"]) for s in run["steps"]])


# ── With thread memory (06) and the tool limit (07) ──────────────────────────


def _turn_on(workspace, slug, message, thread="new") -> dict:
    res = gates._sign_in(workspace, WorkspaceRole.AUTHOR).post(
        f"/api/ai/agents/{slug}/run", json={"message": message, "source": "api", "threadId": thread}
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_a_playbook_both_always_loaded_and_loaded_in_the_thread_appears_once(workspace, db_session, model):
    from tests.test_playbooks import BENCH, BENCH_BODY

    _playbook(db_session, workspace.gid)
    _agent(workspace, playbooks={"always": [BENCH]})

    first = _turn_on(workspace, "writer", f"Write a bench note, use {BENCH}")
    assert first["steps"][0]["tool"] == "load_playbook"  # loaded in the thread as well
    _turn_on(workspace, "writer", "Now make it shorter", first["threadId"])

    system = model.systems[-1]
    assert system.count(BENCH_BODY) == 1  # in the frame; the thread's reload skips it
    assert "## Playbooks loaded earlier in this conversation" not in system


def test_a_thread_loaded_playbook_that_is_not_always_loaded_is_still_reloaded(workspace, db_session, model):
    from tests.test_playbooks import BENCH, BENCH_BODY

    _playbook(db_session, workspace.gid)
    _playbook(db_session, workspace.gid, "alpha-voice", body="ALPHA STEPS.")
    _agent(workspace, playbooks={"always": ["alpha-voice"]})

    first = _turn_on(workspace, "writer", f"use {BENCH}")
    _turn_on(workspace, "writer", "Now make it shorter", first["threadId"])
    system = model.systems[-1]
    assert system.count(BENCH_BODY) == 1 and system.count("ALPHA STEPS.") == 1
    assert "## Playbooks loaded earlier in this conversation" in system


def test_an_always_loaded_playbooks_allowed_tools_narrow_the_run(workspace, db_session, model):
    from tests.test_playbooks import BENCH

    row = _playbook(db_session, workspace.gid)
    row.data_json = {**row.data_json, "allowed_tools": "list_tags"}
    db_session.commit()
    _playbook(db_session, workspace.gid, "other-voice", body="OTHER.")
    _agent(workspace, playbooks={"always": [BENCH]})

    run = _run(workspace, "writer", "please use other-voice")  # loads only the unlimited one, then tries find_entries
    assert _tools_called(run) == ["load_playbook", "find_entries"]
    assert "limits this task" in run["steps"][1]["result"]


def test_playbooks_in_effect_adds_the_always_loaded_ones_inside_the_chosen_set(workspace, db_session):
    from types import SimpleNamespace

    from marvin.services.playbooks import playbooks_in_effect

    for name in ("always-one", "thread-one", "outside-one"):
        _playbook(db_session, workspace.gid, name)
    row = next(r for r in [_playbook(db_session, workspace.gid, "x-extra")])
    thread = SimpleNamespace(
        messages=[SimpleNamespace(seq=1, meta_json={"playbooks": [{"id": "1", "name": "thread-one"}, {"id": "2", "name": "outside-one"}]})]
    )
    assert row is not None
    scope = PlaybookScope(names=("always-one", "thread-one"), always=("always-one",))
    assert [p.name for p in playbooks_in_effect(db_session, workspace.gid, (), thread, scope)] == ["always-one", "thread-one"]
    assert [p.name for p in playbooks_in_effect(db_session, workspace.gid, (), thread)] == ["thread-one", "outside-one"]
