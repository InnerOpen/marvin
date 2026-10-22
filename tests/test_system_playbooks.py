# ruff: noqa: F811 — the `workspace` / `model` fixtures are imported, then named as parameters
"""System Playbooks: written procedures Marvin and its plugins give every workspace, read from the installed packages.

Three layers: the loader (pure: ``system.build`` over declarations, so the plugin-declared path is tested with fakes and core's own
folder with the real files), what a run sees (catalog, load, files, scope, tool limit, traces), and what a workspace and the platform can
do about them (switches, name clashes, copy, the admin page).
"""

import re
import sys
import uuid
from types import SimpleNamespace

import pytest

from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services.playbooks import PlaybookScope, find_published, published_playbooks, system
from marvin.services.playbooks.skill_md import parse_skill_md
from marvin.services.playbooks.system import Declared
from tests import test_content_role_gates as gates
from tests.test_playbooks import _invoke, _playbook, model, workspace  # noqa: F401 — fixtures

PLAYBOOKS = "/api/groups/playbooks"
ADMIN_URL = "/api/admin/system-playbooks"


def _declared(
    name="acme-report", *, owner="acme", front="", body="# Report\n\nDo it in order.\n", files=None, label="System · Acme", version="2.0.0"
):
    skill = f"---\nname: {name}\ndescription: Use when writing the Acme report.\n{front}---\n\n{body}"
    return Declared(name, {"skill_md": skill, "files": files or {}}, "plugin", label, owner, version)


def _as(workspace, role=WorkspaceRole.ADMIN):
    return gates._sign_in(workspace, role)


# ── The loader ───────────────────────────────────────────────────────────────


@pytest.mark.real_system_playbooks
def test_marvins_own_folder_loads_with_its_labels_and_defaults():
    from marvin import __version__

    found = system.system_playbooks()
    assert {"marvin-alt-text", "social-auto-reply-rule"} <= set(found)
    alt, rule = found["marvin-alt-text"], found["social-auto-reply-rule"]
    assert (alt.label, rule.label) == ("System · Marvin", "System · Social")
    assert (alt.source, alt.version) == ("core", __version__)
    assert alt.manual_only is False and rule.manual_only is True  # Rule 5: only `disable-model-invocation: false` is listed
    assert [p for p, _ in alt.files] == ["references/examples.md"] and [p for p, _ in rule.files] == ["references/examples.md"]
    assert alt.id == "system:marvin-alt-text" and len(alt.hash) == 64
    assert system.catalog().skipped == ()


@pytest.mark.real_system_playbooks
def test_every_shipped_skill_parses_passes_the_caps_and_the_lint_and_cites_real_manual_pages():
    from marvin.services.docs import get_docs
    from marvin.services.playbooks.blueprint import payload_problem

    docs = get_docs()
    assert docs.available
    declared, skipped = system.core_declarations()
    assert declared and not skipped
    for d in declared:
        assert payload_problem(d.payload, d.slug) is None, d.slug
        doc = parse_skill_md(d.payload["skill_md"])
        refusals, warnings = system.lint(doc, d.payload)
        assert refusals == [] and warnings == [], (d.slug, refusals, warnings)
        assert doc.allowed_tools == ""  # Rule 6: none of the first skills narrows tools
        assert "compose_entry" not in doc.allowed_tools
        text = "\n".join([d.payload["skill_md"], *d.payload["files"].values()])
        # Every `read_doc` page and section a skill names exists in the manual.
        for page, section in re.findall(r"`path` `([^`]+)` and `section` `([^`]+)`", text):
            assert page in docs.pages, (d.slug, page)
            assert docs.pages[page].section(section) is not None, (d.slug, page, section)
        for ref in re.findall(r"(?<![\w/.-])((?:references)/[A-Za-z0-9_./-]*[A-Za-z0-9_])", doc.body):
            assert ref in d.payload["files"], (d.slug, ref)


@pytest.mark.parametrize(
    ("declared", "reason"),
    [
        (_declared("other-thing"), "must start with 'acme-'"),
        (_declared("Acme Report"), "can't be used"),
        (_declared(files={"scripts/run.sh": "x"}), "script"),
        (_declared(files={"a.exe": "x"}), "must be one of"),
        (_declared(files={"../x.md": "x"}), "path"),
        (_declared(body="x" * (64 * 1024)), "over 64 KB"),
        (_declared(body="Open 3f2b8c1e-9d4a-4e6b-8a1f-0c2d3e4f5a6b first.\n"), "has the id"),
        (_declared(front="allowed-tools: get_entry compose_entry\n"), "allowed-tools 'compose_entry'"),
        (_declared(files={"references/a.md": "revise 3f2b8c1e-9d4a-4e6b-8a1f-0c2d3e4f5a6b"}), "references/a.md has the id"),
        (_declared(body="Call draft_workflow.\n" + "- step\n" * 25), "workflow-authoring skill"),
    ],
)
def test_a_bad_system_playbook_is_skipped_with_the_reason_and_the_good_one_stays(declared, reason):
    built = system.build(([], []), [(declared, "acme-"), (_declared("acme-fine"), "acme-")])
    assert list(built.playbooks) == ["acme-fine"]
    assert len(built.skipped) == 1 and reason in built.skipped[0].reason and built.skipped[0].label == "System · Acme"


def test_a_short_workflow_skill_that_calls_the_tools_is_allowed():
    ok = _declared(body="Call workflow_authoring_guide, then draft_workflow with what it says.\n")
    assert list(system.build(([], []), [(ok, "acme-")]).playbooks) == ["acme-report"]


def test_the_first_source_to_use_a_name_keeps_it_and_the_repeat_is_reported():
    first = _declared(label="System · Acme", version="1.0.0")
    again = _declared(label="System · Other", version="9.9.9", owner="acme")
    built = system.build(([], []), [(first, "acme-"), (again, "acme-")])
    assert built.playbooks["acme-report"].version == "1.0.0"
    assert [(s.name, s.label) for s in built.skipped] == [("acme-report", "System · Other")]
    assert "already used by System · Acme" in built.skipped[0].reason


def test_core_comes_before_plugins_in_the_catalog():
    core = [_declared("marvin-thing", owner="marvin", label="System · Marvin", version="1")]
    plugin = _declared("marvin-thing", owner="marvin")  # a plugin trying core's name
    built = system.build((core, []), [(plugin, "marvin-")])
    assert built.playbooks["marvin-thing"].label == "System · Marvin" and len(built.skipped) == 1


@pytest.mark.parametrize(
    ("front", "manual_only"),
    [("", True), ("disable-model-invocation: true\n", True), ("disable-model-invocation: false\n", False)],
)
def test_a_system_playbook_is_manual_only_unless_it_says_otherwise(front, manual_only):
    built = system.build(([], []), [(_declared(front=front), "acme-")])
    assert built.playbooks["acme-report"].manual_only is manual_only


def test_allowed_tools_and_an_ai_writer_in_the_body_are_warned_about_not_refused():
    d = _declared(front="allowed-tools: get_entry\n", body="Save it with compose_entry.\nNever use revise_entry.\n")
    got = system.build(([], []), [(d, "acme-")]).playbooks["acme-report"]
    assert got.allowed_tools == "get_entry"
    assert len(got.warnings) == 2 and any("allowed-tools" in w for w in got.warnings) and any("compose_entry" in w for w in got.warnings)


def test_the_hash_follows_the_content_not_the_version():
    a = system.build(([], []), [(_declared(version="1"), "acme-")]).playbooks["acme-report"]
    b = system.build(([], []), [(_declared(version="2"), "acme-")]).playbooks["acme-report"]
    c = system.build(([], []), [(_declared(body="# Report\n\nChanged.\n"), "acme-")]).playbooks["acme-report"]
    assert a.hash == b.hash != c.hash


def test_core_loads_with_its_own_parser_when_the_sdk_is_not_installed(monkeypatch):
    for name in [m for m in sys.modules if m == "marvin_integration_sdk" or m.startswith("marvin_integration_sdk.")]:
        monkeypatch.setitem(sys.modules, name, None)  # an import of the SDK now raises ImportError
    declared, skipped = system.core_declarations()
    built = system.build((declared, skipped), system.plugin_declarations())
    assert {"marvin-alt-text", "social-auto-reply-rule"} <= set(built.playbooks) and not built.skipped


def test_plugins_declare_through_providers_storage_and_ai_plugins(monkeypatch):
    """The three plugin lists, read with fakes: a provider's ``system_playbooks``, a storage or AI plugin's ``playbooks``."""
    from marvin_integration_sdk import INTEGRATION_REGISTRY

    def blueprint(name):
        d = _declared(name)
        return SimpleNamespace(slug=name, payload=d.payload)

    provider = SimpleNamespace(slug="acme_pages", name="Acme Pages", system_playbooks=(blueprint("acme-pages-fix"),))
    monkeypatch.setitem(INTEGRATION_REGISTRY, "acme_pages", provider)
    monkeypatch.setattr("marvin.services.integrations.loader.source_of", lambda slug: {"package": "p", "version": "3.1.0"})
    storage = SimpleNamespace(slug="bucket", name="Bucket storage", playbooks=(blueprint("bucket-setup"),))
    ai = SimpleNamespace(slug="vendor", name="Vendor AI", playbooks=(blueprint("vendor-keys"),))
    monkeypatch.setattr(system, "_storage_plugins", lambda: [("bucket", storage, "0.5.0")])
    monkeypatch.setattr(system, "_ai_plugins", lambda: [("vendor", ai, "1.2.3")])

    built = system.build(([], []), system.plugin_declarations())
    got = {n: (p.label, p.version) for n, p in built.playbooks.items()}
    assert got["acme-pages-fix"] == ("System · Acme Pages", "3.1.0")  # an underscore in the slug is a hyphen in the prefix
    assert got["bucket-setup"] == ("System · Bucket storage", "0.5.0")
    assert got["vendor-keys"] == ("System · Vendor AI", "1.2.3")


def test_an_older_plugin_without_the_field_adds_nothing(monkeypatch):
    storage = SimpleNamespace(slug="old", name="Old storage")  # SDK 0.15: no `playbooks`
    monkeypatch.setattr(system, "_storage_plugins", lambda: [("old", storage, "0.1")])
    monkeypatch.setattr(system, "_ai_plugins", lambda: [])
    assert [d for d, _ in system.plugin_declarations() if d.owner == "old"] == []


def test_a_name_clash_message_points_at_copy(system_playbooks):
    system_playbooks(_declared())
    assert "copy it instead" in system.name_clash_message("acme-report")
    assert system.name_clash_message("something-else") is None


# ── What a run sees ──────────────────────────────────────────────────────────


def _listed(db_session, workspace, scope=None):
    return [(p.name, p.source) for p in published_playbooks(db_session, workspace.gid, scope or PlaybookScope())]


def test_the_catalog_lists_the_workspaces_own_first_then_the_system_ones(workspace, db_session, system_playbooks):
    system_playbooks(
        _declared("acme-report", front="disable-model-invocation: false\n"), _declared("acme-aaa", front="disable-model-invocation: false\n")
    )
    _playbook(db_session, workspace.gid, "zeta-voice")
    assert _listed(db_session, workspace) == [("zeta-voice", "workspace"), ("acme-aaa", "plugin"), ("acme-report", "plugin")]
    assert [p.name for p in published_playbooks(db_session, workspace.gid)] == ["zeta-voice"]  # the admin screens: no scope, workspace rows only
    assert [p.name for p in published_playbooks(db_session, workspace.gid, system=True)] == ["zeta-voice", "acme-aaa", "acme-report"]


def test_manual_only_reaches_a_run_only_when_named_chosen_by_a_step_or_driven_directly(workspace, db_session, system_playbooks):
    system_playbooks(_declared("acme-report"))
    quiet = PlaybookScope()
    assert _listed(db_session, workspace, quiet) == []  # never offered in a catalog
    assert find_published(db_session, workspace.gid, "acme-report", quiet) is None
    assert find_published(db_session, workspace.gid, "acme-report", quiet.asking("please use the acme report playbook")) is not None
    assert find_published(db_session, workspace.gid, "acme-report", PlaybookScope(also=("acme-report",))) is not None  # a workflow step
    direct = PlaybookScope(direct=True)
    assert _listed(db_session, workspace, direct) == [("acme-report", "plugin")]
    assert find_published(db_session, workspace.gid, "acme-report", direct) is not None


def test_a_workflow_step_naming_a_manual_only_playbook_puts_it_in_the_frame(workspace, db_session, system_playbooks):
    from marvin.db.models.platform.entries import Entries
    from marvin.services.playbooks import always_playbooks

    system_playbooks(_declared("acme-report"))
    _playbook(db_session, workspace.gid, "manual-own")
    row = db_session.query(Entries).filter_by(slug="manual-own").one()
    row.data_json = {**row.data_json, "manual_only": True}
    db_session.commit()
    step = PlaybookScope(also=("acme-report", "manual-own"))
    assert [p.name for p in always_playbooks(db_session, workspace.gid, step)] == ["acme-report", "manual-own"]
    assert always_playbooks(db_session, workspace.gid, PlaybookScope()) == []


def test_the_tools_show_system_playbooks_with_their_label_version_and_files(workspace, db_session, system_playbooks):
    system_playbooks(_declared(files={"references/checks.md": "- one\n- two\n"}))
    listed = _invoke(workspace, "list_playbooks", {})["playbooks"]  # a person driving the tools: manual-only is shown, flagged
    assert listed == [{"name": "acme-report", "description": "Use when writing the Acme report.", "system": "System · Acme", "manualOnly": True}]
    loaded = _invoke(workspace, "load_playbook", {"name": "acme-report"})
    assert loaded["id"] == "system:acme-report" and loaded["source"] == "System · Acme" and loaded["version"] == "2.0.0"
    assert loaded["body"].startswith("# Report") and loaded["files"][0]["path"] == "references/checks.md" and loaded["hash"]
    read = _invoke(workspace, "read_playbook_file", {"playbook": "acme-report", "path": "references/checks.md"})
    assert read["text"] == "- one\n- two" and read["truncated"] is False
    cut = _invoke(workspace, "read_playbook_file", {"playbook": "acme-report", "path": "references/checks.md", "max_chars": 5})
    assert cut["truncated"] is True and cut["text"] == "- one"
    missing = _invoke(workspace, "read_playbook_file", {"playbook": "acme-report", "path": "references/nope.md"})
    assert missing["files"] == ["references/checks.md"]


def test_a_workspace_playbook_with_the_name_wins_over_a_system_one(workspace, db_session, system_playbooks):
    system_playbooks(_declared())
    _playbook(db_session, workspace.gid, "acme-report", body="Mine.")  # older than the plugin: it shadows
    assert _invoke(workspace, "load_playbook", {"name": "acme-report"})["body"] == "Mine."
    state = next(s for s in system.system_states(db_session, workspace.gid))
    assert state.state == "hidden" and "your Playbook acme-report has this name" in state.detail


def test_a_run_catalog_names_a_listed_system_playbook_and_an_agent_can_load_it(workspace, db_session, model, system_playbooks):
    from tests.test_playbooks import _ask

    system_playbooks(_declared(front="disable-model-invocation: false\n"))
    run = _ask(workspace, "write the acme-report please")
    assert "- acme-report: Use when writing the Acme report." in model.systems[0]
    assert [s["tool"] for s in run["steps"]][0] == "load_playbook"
    assert run["steps"][0]["result"].count("system:acme-report") == 1


def test_the_trace_records_the_system_id_and_version(workspace, db_session, model, system_playbooks):
    from marvin.services.playbooks import playbooks_used
    from marvin.services.playbooks.memory import recent_uses
    from tests.test_playbooks import _ask

    system_playbooks(_declared(front="disable-model-invocation: false\n"))
    _ask(workspace, "write the acme-report please")
    found = recent_uses(db_session, workspace.gid)
    assert "system:acme-report" in found and found["system:acme-report"][0]["execution_id"]
    step = SimpleNamespace(tool="load_playbook", result='{"id": "system:acme-report", "name": "acme-report", "version": "2.0.0"}')
    assert playbooks_used([step]) == [{"id": "system:acme-report", "name": "acme-report", "version": "2.0.0"}]


def test_a_chosen_set_names_the_system_skills_it_wants(workspace, db_session, system_playbooks):
    system_playbooks(_declared("acme-a", front="disable-model-invocation: false\n"), _declared("acme-b", front="disable-model-invocation: false\n"))
    narrow = PlaybookScope(names=("acme-a",))
    assert _listed(db_session, workspace, narrow) == [("acme-a", "plugin")]
    assert find_published(db_session, workspace.gid, "acme-b", narrow) is None


def test_always_load_accepts_a_listed_system_skill_but_not_a_manual_only_one(workspace, db_session, system_playbooks):
    from marvin.services.playbooks import PlaybookSettingsError, always_playbooks, check_agent_settings

    system_playbooks(_declared("acme-a", front="disable-model-invocation: false\n"), _declared("acme-b"))
    check_agent_settings(db_session, workspace.gid, {"names": None, "always": ["acme-a"]})
    with pytest.raises(PlaybookSettingsError, match="acme-b"):
        check_agent_settings(db_session, workspace.gid, {"always": ["acme-b"]})
    assert [p.name for p in always_playbooks(db_session, workspace.gid, PlaybookScope(always=("acme-a",)))] == ["acme-a"]


def test_a_loaded_system_playbook_narrows_tools_like_any_playbook(workspace, db_session, system_playbooks):
    from marvin.services.ai.tool_gateway import playbook_tool_limit
    from marvin.services.playbooks import playbooks_in_effect

    system_playbooks(_declared(front="allowed-tools: get_entry\ndisable-model-invocation: false\n"))
    convo = [
        SimpleNamespace(role="assistant", tool_calls=[SimpleNamespace(id="c1", name="load_playbook")]),
        SimpleNamespace(role="tool", tool_call_id="c1", content='{"id": "system:acme-report", "name": "acme-report"}'),
    ]
    in_effect = playbooks_in_effect(db_session, workspace.gid, convo)
    assert [p.name for p in in_effect] == ["acme-report"]
    assert "get_entry" in playbook_tool_limit(in_effect, {"get_entry", "find_entries"}) and "find_entries" not in playbook_tool_limit(
        in_effect, {"get_entry", "find_entries"}
    )


def test_a_thread_keeps_a_loaded_system_playbook_in_effect(workspace, db_session, system_playbooks):
    from marvin.services.playbooks.memory import reload_block

    system_playbooks(_declared())
    thread = SimpleNamespace(messages=[SimpleNamespace(seq=1, meta_json={"playbooks": [{"id": "system:acme-report", "name": "acme-report"}]})])
    assert "Do it in order." in reload_block(db_session, workspace.gid, thread)


# ── Switches ─────────────────────────────────────────────────────────────────


def test_a_workspace_switch_hides_the_skill_everywhere_in_that_workspace_only(workspace, db_session, system_playbooks):
    system_playbooks(_declared(front="disable-model-invocation: false\n"))
    other = SimpleNamespace(gid=_other_workspace(db_session))
    res = _as(workspace).put(f"{PLAYBOOKS}/system/acme-report", json={"enabled": False})
    assert res.status_code == 200 and res.json()["state"] == "off" and res.json()["enabled"] is False
    assert _listed(db_session, workspace) == []
    assert find_published(db_session, workspace.gid, "acme-report", PlaybookScope(direct=True)) is None
    assert _invoke(workspace, "load_playbook", {"name": "acme-report"})["error"].startswith("No published Playbook")
    assert _invoke(workspace, "read_playbook_file", {"playbook": "acme-report", "path": "x.md"})["error"]
    assert _listed(db_session, other) == [("acme-report", "plugin")]  # isolation
    assert _as(workspace).put(f"{PLAYBOOKS}/system/acme-report", json={"enabled": True}).json()["state"] == "on"
    assert _listed(db_session, workspace) == [("acme-report", "plugin")]


def test_an_off_skill_is_absent_from_always_load_and_chosen_sets(workspace, db_session, system_playbooks):
    from marvin.services.playbooks import PlaybookSettingsError, always_playbooks, check_agent_settings

    system_playbooks(_declared(front="disable-model-invocation: false\n"))
    system.switch_here(db_session, workspace.gid, "acme-report", False)
    assert always_playbooks(db_session, workspace.gid, PlaybookScope(always=("acme-report",))) == []
    with pytest.raises(PlaybookSettingsError):
        check_agent_settings(db_session, workspace.gid, {"always": ["acme-report"]})


def test_only_an_admin_switches_a_system_playbook_and_an_unknown_name_is_404(workspace, system_playbooks):
    system_playbooks(_declared())
    assert _as(workspace, WorkspaceRole.EDITOR).put(f"{PLAYBOOKS}/system/acme-report", json={"enabled": False}).status_code == 403
    assert _as(workspace, WorkspaceRole.ADMIN).put(f"{PLAYBOOKS}/system/nope", json={"enabled": False}).status_code == 404
    assert _as(workspace, WorkspaceRole.EDITOR).get(f"{PLAYBOOKS}/system").status_code == 200
    assert _as(workspace, WorkspaceRole.VIEWER).get(f"{PLAYBOOKS}/system").status_code == 403


def test_the_switch_is_kept_by_name_when_the_plugin_goes_and_comes_back(workspace, db_session, system_playbooks):
    system_playbooks(_declared())
    system.switch_here(db_session, workspace.gid, "acme-report", False)
    system_playbooks()  # uninstalled
    assert system.off_here(db_session, workspace.gid) == ["acme-report"] and _listed(db_session, workspace) == []
    system_playbooks(_declared())  # reinstalled: still off
    assert _listed(db_session, workspace) == []


def test_the_server_switch_hides_it_in_every_workspace(workspace, db_session, system_playbooks, client):
    from marvin.app import app
    from marvin.core.dependencies import get_current_user

    system_playbooks(_declared(front="disable-model-invocation: false\n"))
    other = SimpleNamespace(gid=_other_workspace(db_session))
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(platform_role=PlatformRole.SUPER_ADMIN, is_superuser=False, admin=True)
    try:
        res = client.put(f"{ADMIN_URL}/acme-report", json={"enabled": False})
        assert res.status_code == 200 and res.json()["serverOff"] is True
        assert _listed(db_session, workspace) == [] and _listed(db_session, other) == []
        state = system.system_states(db_session, workspace.gid)[0]
        assert (state.state, state.detail) == ("off_server", "Off for this platform")
        assert client.put(f"{ADMIN_URL}/nope", json={"enabled": False}).status_code == 404
        assert client.put(f"{ADMIN_URL}/acme-report", json={"enabled": True}).json()["serverOff"] is False
        assert _listed(db_session, workspace) == [("acme-report", "plugin")]
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_the_platform_admin_page_needs_a_super_admin_and_lists_sources_badges_counts_and_failures(workspace, db_session, system_playbooks, client):
    from marvin.app import app
    from marvin.core.dependencies import get_current_user

    built = system_playbooks(
        _declared(front="allowed-tools: get_entry\n"),
        skipped=[system.Skipped("marvin-bad", "System · Marvin", "no SKILL.md")],
    )
    assert built.playbooks
    system.switch_here(db_session, workspace.gid, "acme-report", False)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(platform_role=PlatformRole.NONE, is_superuser=False, admin=False)
    try:
        assert client.get(ADMIN_URL).status_code == 403
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(platform_role=PlatformRole.SUPER_ADMIN, is_superuser=False, admin=True)
        page = client.get(ADMIN_URL).json()
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    item = page["items"][0]
    assert (item["name"], item["label"], item["version"], item["manualOnly"], item["allowedTools"]) == (
        "acme-report",
        "System · Acme",
        "2.0.0",
        True,
        "get_entry",
    )
    assert item["workspacesOff"] == 1 and item["warnings"] and item["serverOff"] is False
    assert page["skipped"] == [{"name": "marvin-bad", "label": "System · Marvin", "reason": "no SKILL.md"}]


def test_a_workspaces_export_carries_its_switches_and_an_import_restores_them(workspace, db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.repos.all_repositories import get_repositories
    from marvin.repos.seed.workspace_exporter import WorkspaceExporter
    from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader

    system.switch_here(db_session, workspace.gid, "acme-report", False)
    system.switch_here(db_session, workspace.gid, "gone-plugin-skill", False)  # not installed here: kept
    data = WorkspaceExporter(get_repositories(db_session, group_id=workspace.gid)).export_workspace()
    assert data["ai_settings"]["systemPlaybooksOff"] == ["acme-report", "gone-plugin-skill"]

    target = uuid.uuid4()
    g = Groups(session=db_session, name=f"sys-{target.hex[:8]}", slug=f"sys-{target.hex[:8]}")
    g.id = target
    db_session.add(g)
    db_session.commit()
    try:
        WorkspaceSeedLoader(get_repositories(db_session, group_id=workspace.gid))._load_data(data, overwrite=True, target_group_id=str(target))
        assert db_session.query(WorkspaceAISettingsModel).filter_by(group_id=target).one().system_playbooks_off == [
            "acme-report",
            "gone-plugin-skill",
        ]
    finally:
        db_session.query(WorkspaceAISettingsModel).filter_by(group_id=target).delete()
        db_session.query(Groups).filter_by(id=target).delete()
        db_session.commit()


def _other_workspace(db_session):
    from tests.test_playbooks import _other_workspace as make

    return make(db_session)


# ── Names ────────────────────────────────────────────────────────────────────


def test_a_new_workspace_playbook_may_not_take_a_system_name(workspace, db_session, system_playbooks):
    from marvin.db.models.platform.entries import Entries
    from marvin.services.playbooks import ensure_playbook_type

    system_playbooks(_declared())
    type_id = ensure_playbook_type(db_session, workspace.gid)
    client = _as(workspace, WorkspaceRole.EDITOR)
    res = client.post(
        "/api/platform/entries",
        json={
            "entry_type_id": str(type_id),
            "title": "acme-report",
            "slug": "acme-report",
            "status": "draft",
            "data_json": {"name": "acme-report", "description": "d", "body": "b"},
        },
    )
    assert res.status_code == 409 and "copy it instead" in res.json()["detail"]
    ok = client.post(
        "/api/platform/entries",
        json={
            "entry_type_id": str(type_id),
            "title": "report",
            "slug": "report",
            "status": "draft",
            "data_json": {"name": "report", "description": "d", "body": "b"},
        },
    )
    assert ok.status_code == 201
    renamed = client.patch(f"/api/platform/entries/{ok.json()['id']}", json={"slug": "acme-report"})
    assert renamed.status_code == 409
    assert db_session.query(Entries).filter_by(group_id=workspace.gid, slug="acme-report").count() == 0


def test_import_card_add_and_an_agents_draft_refuse_a_system_name(workspace, db_session, system_playbooks):
    from marvin.services.blueprints.playbook_apply import blueprint_conflict

    system_playbooks(_declared())
    skill = b"---\nname: acme-report\ndescription: Mine.\n---\n\nBody.\n"
    res = _as(workspace).post(f"{PLAYBOOKS}/import", files={"file": ("SKILL.md", skill)})
    assert res.status_code == 409 and "copy it instead" in res.json()["detail"]
    renamed = _as(workspace).post(f"{PLAYBOOKS}/import", files={"file": ("SKILL.md", skill)}, data={"name": "my-report"})
    assert renamed.status_code == 201

    blueprint = SimpleNamespace(slug="acme-report", source="acme")
    assert "copy it instead" in blueprint_conflict(db_session, workspace.gid, blueprint)

    out = _invoke(
        workspace,
        "create_draft",
        {"entry_type": "playbook", "title": "acme-report", "fields": {"name": "acme-report", "description": "x", "body": "y"}},
        WorkspaceRole.EDITOR,
    )
    assert "copy it instead" in out["error"]


def test_proposals_and_replaces_against_a_system_playbook_are_refused(workspace, db_session, system_playbooks):
    system_playbooks(_declared(front="disable-model-invocation: false\n"))
    out = _invoke(workspace, "propose_playbook_change", {"playbook": "acme-report", "body": "new"}, WorkspaceRole.EDITOR)
    assert "read-only" in out["error"] and "Copy" in out["error"]
    draft = _invoke(
        workspace,
        "create_draft",
        {"entry_type": "playbook", "title": "tweak", "fields": {"name": "tweak", "description": "d", "body": "b"}},
        WorkspaceRole.EDITOR,
    )
    out = _invoke(workspace, "update_draft", {"entry": draft["entryId"], "fields": {"replaces": "acme-report"}}, WorkspaceRole.EDITOR)
    assert "read-only" in out["error"]
    # An editor who sets it by hand gets the same refusal when publishing the "change".
    from fastapi import HTTPException

    from marvin.db.models.platform.entries import Entries
    from marvin.services.playbooks import change_target

    row = db_session.get(Entries, uuid.UUID(draft["entryId"]))
    row.data_json = {**row.data_json, "replaces": "acme-report"}
    db_session.commit()
    with pytest.raises(HTTPException) as refused:
        change_target(db_session, row)
    assert refused.value.status_code == 409 and "read-only" in refused.value.detail


# ── Copy ─────────────────────────────────────────────────────────────────────


def _copy(workspace, name=None, role=WorkspaceRole.ADMIN):
    return _as(workspace, role).post(f"{PLAYBOOKS}/system/acme-report/copy", json={"name": name} if name else None)


def test_copy_makes_a_draft_with_files_review_and_copied_from_and_suggests_a_name(workspace, db_session, system_playbooks):
    from marvin.db.models.platform.entries import Entries

    built = system_playbooks(_declared(files={"references/checks.md": "- one\n"}))
    item = _as(workspace).get(f"{PLAYBOOKS}/system").json()["items"][0]
    assert item["suggestedCopyName"] == "report" and item["fileCount"] == 1

    res = _copy(workspace)
    assert res.status_code == 201, res.text
    body = res.json()
    assert (body["name"], body["status"], body["fileCount"]) == ("report", "draft", 1)
    assert body["review"]["source"]["kind"] == "system" and body["review"]["source"]["version"] == "2.0.0"
    row = db_session.get(Entries, uuid.UUID(body["id"]))
    assert row.data_json["description"] == "Use when writing the Acme report." and row.data_json["body"].startswith("# Report")
    assert row.metadata_json["copiedFrom"] == {
        "name": "acme-report", "label": "System · Acme", "version": "2.0.0", "hash": built.playbooks["acme-report"].hash,
    }  # fmt: skip
    from marvin.services.playbooks import reference_files

    assert [f.path for f in reference_files(db_session, row.id)] == ["references/checks.md"]


def test_copy_refuses_a_taken_name_a_system_name_and_a_non_admin(workspace, db_session, system_playbooks):
    system_playbooks(_declared(), _declared("acme-other"))
    _playbook(db_session, workspace.gid, "report")
    assert _copy(workspace).status_code == 409  # the suggestion is taken: say so, never suffix
    items = {i["name"]: i for i in _as(workspace).get(f"{PLAYBOOKS}/system").json()["items"]}
    assert items["acme-report"]["suggestedCopyName"] == "" and items["acme-other"]["suggestedCopyName"] == "other"
    assert _copy(workspace, "acme-other").status_code == 409
    assert _copy(workspace, "Not A Name").status_code == 400
    assert _copy(workspace, "my-report", role=WorkspaceRole.EDITOR).status_code == 403
    assert _copy(workspace, "my-report").status_code == 201


def test_a_published_copy_replaces_its_original_and_unpublishing_brings_it_back(workspace, db_session, system_playbooks):
    from marvin.db.models.platform.entries import Entries

    system_playbooks(_declared(front="disable-model-invocation: false\n"))
    copy = db_session.get(Entries, uuid.UUID(_copy(workspace).json()["id"]))
    assert _listed(db_session, workspace) == [("acme-report", "plugin")]  # a draft copy changes nothing
    copy.status = "published"
    db_session.commit()
    assert _listed(db_session, workspace) == [("report", "workspace")]
    state = system.system_states(db_session, workspace.gid)[0]
    assert state.state == "replaced" and "report" in state.detail
    copy.status = "draft"
    db_session.commit()
    assert _listed(db_session, workspace) == [("acme-report", "plugin")]
    copy.status = "trashed"
    db_session.commit()
    assert _listed(db_session, workspace) == [("acme-report", "plugin")]


def test_a_copy_hears_when_the_original_changed_and_can_mark_it_seen(workspace, db_session, system_playbooks):
    system_playbooks(_declared(version="1.0.0"))
    made = _copy(workspace).json()
    row = next(i for i in _as(workspace).get(PLAYBOOKS).json()["items"] if i["id"] == made["id"])
    assert row["copiedFrom"] == {
        "name": "acme-report", "label": "System · Acme", "version": "1.0.0", "currentVersion": "1.0.0", "upstreamChanged": False,
    }  # fmt: skip
    system_playbooks(_declared(version="1.2.0", body="# Report\n\nA better order.\n"))
    row = next(i for i in _as(workspace).get(PLAYBOOKS).json()["items"] if i["id"] == made["id"])
    assert row["copiedFrom"]["upstreamChanged"] is True and (row["copiedFrom"]["version"], row["copiedFrom"]["currentVersion"]) == ("1.0.0", "1.2.0")
    assert _as(workspace, WorkspaceRole.EDITOR).post(f"{PLAYBOOKS}/{made['id']}/upstream-seen").status_code == 403
    assert _as(workspace).post(f"{PLAYBOOKS}/{made['id']}/upstream-seen").status_code == 204
    row = next(i for i in _as(workspace).get(PLAYBOOKS).json()["items"] if i["id"] == made["id"])
    assert row["copiedFrom"]["upstreamChanged"] is False and row["copiedFrom"]["version"] == "1.2.0"
    plain = _playbook(db_session, workspace.gid, "plain-one")
    assert _as(workspace).post(f"{PLAYBOOKS}/{plain.id}/upstream-seen").status_code == 404


# ── Screens' data ────────────────────────────────────────────────────────────


def test_the_system_list_and_the_read_view_carry_what_the_screens_show(workspace, db_session, system_playbooks):
    system_playbooks(_declared(files={"references/checks.md": "- one\n"}, front="allowed-tools: get_entry\n"))
    items = _as(workspace, WorkspaceRole.EDITOR).get(f"{PLAYBOOKS}/system").json()["items"]
    assert [(i["name"], i["label"], i["version"], i["manualOnly"], i["allowedTools"], i["state"]) for i in items] == [
        ("acme-report", "System · Acme", "2.0.0", True, "get_entry", "on")
    ]
    one = _as(workspace, WorkspaceRole.EDITOR).get(f"{PLAYBOOKS}/system/acme-report").json()
    assert (
        one["body"].startswith("# Report")
        and one["files"] == [{"path": "references/checks.md", "text": "- one\n"}]
        and one["warnings"]
        and one["source"] == "plugin"
    )
    assert _as(workspace).get(f"{PLAYBOOKS}/system/nope").status_code == 404
    uses = _as(workspace).get(f"{PLAYBOOKS}/system/acme-report/uses").json()
    assert uses == {"items": []}


def test_the_integration_card_and_the_plugin_list_say_what_a_provider_gives_every_workspace(workspace, system_playbooks, monkeypatch, client):
    from marvin_integration_sdk import INTEGRATION_REGISTRY

    from marvin.services import plugins

    system_playbooks(_declared("acme-report"))
    provider = SimpleNamespace(
        slug="acme", name="Acme", actions=(), content=(), icon="", info=lambda: {"slug": "acme", "name": "Acme", "category": "capability"}
    )
    monkeypatch.setitem(INTEGRATION_REGISTRY, "acme", provider)
    cards = _as(workspace, WorkspaceRole.VIEWER).get("/api/groups/integrations/providers").json()
    acme = next(c for c in cards if c["slug"] == "acme")
    assert acme["systemPlaybooks"] == [{"name": "acme-report", "description": "Use when writing the Acme report.", "label": "System · Acme"}]
    assert plugins._provider_read(provider, {}).system_playbooks == 1


def test_the_s3_plugins_playbook_loads_through_core_and_cites_real_manual_pages(monkeypatch):
    """Runs where the S3 plugin (0.5.0+, with SDK 0.16) is installed; skipped on the pinned versions that predate it."""
    plugin_module = pytest.importorskip("marvin_storage_s3")
    plugin = plugin_module.plugin()
    if not getattr(plugin, "playbooks", ()):
        pytest.skip("the installed marvin-storage-s3 ships no system Playbook yet")
    from marvin.services.docs import get_docs

    monkeypatch.setattr(system, "_storage_plugins", lambda: [("s3", plugin, "0.5.0")])
    built = system.build(([], []), _real_plugin_declarations())
    got = built.playbooks["s3-workspace-bucket"]
    assert not built.skipped and got.manual_only is True and got.warnings == () and got.label.startswith("System · ")
    assert [p for p, _ in got.files] == ["references/failures.md"]
    docs = get_docs()
    text = got.body + "\n".join(t for _, t in got.files)
    for page, section in re.findall(r"`path` `([^`]+)` and `section`\s+`([^`]+)`", text):
        assert docs.pages[page].section(section) is not None, (page, section)


def _real_plugin_declarations():
    return [
        (d, f"{d.owner}-")
        for slug, plugin, version in system._storage_plugins()
        for d in system._declared_from_blueprints(getattr(plugin, "playbooks", ()), label=f"System · {plugin.name}", owner=slug, version=version)
    ]
