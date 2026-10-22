# ruff: noqa: F811 — the `workspace` fixture is imported, then named as a parameter
"""Integrations ship their own Playbooks: a ``kind="playbook"`` blueprint on the integration's card.

Seams: the blueprint schema and the pure payload check (services/playbooks/blueprint.py), the catalog's provider rules, and the
REST routes the card uses (``/api/groups/blueprints``): Add makes a **draft** with its files, review and ``installedBy`` and commits;
a taken name is refused; state, Update and edit protection; the footprint and the Playbooks page. Core builds the blueprint by hand
(``ContentBlueprint(kind="playbook", payload=…)``), so it needs no particular SDK helper.
"""

import uuid

import pytest

from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.platform.entries import Entries
from marvin.db.models.users.roles import WorkspaceRole
from marvin.schemas.platform.blueprints import Blueprint
from marvin.services import playbooks
from marvin.services.blueprints import apply_many, list_blueprints
from marvin.services.playbooks.blueprint import PROVENANCE_KEY, payload_problem
from tests import test_content_role_gates as gates

sdk = pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")
workspace = gates.workspace  # fixture: a workspace with a signed-in user

ADMIN, EDITOR = WorkspaceRole.ADMIN, WorkspaceRole.EDITOR
API = "/api/groups/blueprints"
NAME = "acme-weekly-report"


def skill(body="# Weekly report\n\nWrite it yourself, then save it with create_draft.\n\nSee references/checklist.md.", name=NAME, tools=""):
    extra = f"allowed-tools: {tools}\n" if tools else ""
    return f"---\nname: {name}\ndescription: How to write Acme's weekly report. Use it when drafting one.\n{extra}---\n\n{body}\n"


def payload(text=None, files=None, name=NAME):
    return {
        "skill_md": text if text is not None else skill(name=name),
        "files": {"references/checklist.md": "- one\n- two\n"} if files is None else files,
    }


def blueprint(slug=NAME, **kw):
    return sdk.ContentBlueprint(
        kind="playbook", slug=slug, name="Weekly report", description="How to write it.", payload=kw.pop("payload", None) or payload(name=slug)
    )


def register(monkeypatch, *content, slug="acme"):
    class _P(sdk.IntegrationProvider):
        name = "Acme"

    _P.slug = slug
    _P.content = tuple(content)
    monkeypatch.setitem(sdk.INTEGRATION_REGISTRY, slug, _P())


def connect(db_session, gid, provider="acme"):
    row = IntegrationModel(
        session=db_session, group_id=gid, provider=provider, name="Acme", slug=f"{provider}-{uuid.uuid4().hex[:4]}", enabled=True, config={}
    )
    db_session.add(row)
    db_session.commit()
    return row


def admin(workspace):
    return gates._sign_in(workspace, ADMIN)


def entry(db_session, gid, slug=NAME):
    db_session.expire_all()
    return db_session.query(Entries).filter_by(group_id=gid, slug=slug).first()


def add(client, integration=None, slug=NAME):
    params = {"integration_id": str(integration.id)} if integration else {}
    return client.post(f"{API}/{slug}/apply", params={"source": "acme", **params})


# ── The check ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad, message",
    [
        ({"files": {}}, "skill_md"),
        (payload(skill(name="other")), "must equal the blueprint slug"),
        (payload("no frontmatter"), "SKILL.md can't be used"),
        (payload(files={"scripts/run.sh": "x"}), "script"),
        (payload(files={"references/tool.py": "x"}), "script"),
        (payload(files={"../x.md": "x"}), "inside the Playbook"),
        (payload(files={"/abs.md": "x"}), "relative"),
        (payload(files={"references/a.png": "x"}), "must be one of"),
        (payload(files={"SKILL.md": "x"}), "other than SKILL.md"),
        (payload(files={f"references/f{i}.md": "x" for i in range(21)}), "at most 20"),
        (payload(files={"references/big.md": "x" * (64 * 1024 + 1)}), "over 64 KB"),
        (payload(files={f"references/f{i}.md": "x" * 60000 for i in range(5)}), "over 256 KB"),
        (payload(skill(body="x" * (64 * 1024 + 1))), "SKILL.md is over"),
        ({"skill_md": skill(), "files": {"references/a.md": 3}}, "map a relative path"),
    ],
)
def test_a_bad_payload_is_named(bad, message):
    assert message in (payload_problem(bad, NAME) or "")


def test_a_good_payload_has_no_problem():
    assert payload_problem(payload(), NAME) is None


def test_the_blueprint_schema_refuses_a_bad_playbook_and_never_requires_one():
    with pytest.raises(ValueError, match="script"):
        Blueprint(kind="playbook", slug=NAME, name="N", payload=payload(files={"scripts/a.sh": "x"}))
    with pytest.raises(ValueError, match="never required"):
        Blueprint(kind="playbook", slug=NAME, name="N", required=True, payload=payload())


def test_the_catalog_lists_playbooks_with_the_providers_prefix_and_skips_the_rest(monkeypatch, caplog):
    register(
        monkeypatch,
        blueprint(),
        blueprint(slug="weekly-report"),  # no provider prefix
        sdk.ContentBlueprint(kind="playbook", slug="acme-wrong", name="N", payload=payload(name=NAME)),  # name != slug
        sdk.ContentBlueprint(kind="collection", slug="acme-all", name="All", payload={"name": "All"}),
    )
    found = {b.slug: b for b in list_blueprints(source="acme")}
    assert set(found) == {NAME, "acme-all"}
    assert found[NAME].kind == "playbook" and found[NAME].category == "Acme" and found[NAME].required is False


# ── Add: a draft, with files, review and provenance ──────────────────────────


def test_add_makes_a_draft_with_its_files_review_and_provenance(workspace, db_session, monkeypatch):
    register(monkeypatch, blueprint())
    acme = connect(db_session, workspace.gid)
    res = add(admin(workspace), acme)
    assert res.status_code == 200, res.text
    assert res.json()["created"] is True and res.json()["detail"] == ""

    row = entry(db_session, workspace.gid)
    assert row.status == "draft" and row.title == NAME
    assert row.data_json["description"].startswith("How to write Acme's weekly report")
    assert [f.path for f in playbooks.reference_files(db_session, row.id)] == ["references/checklist.md"]
    meta = row.metadata_json
    assert meta["importReview"]["source"] == {"kind": "integration", "provider": "acme", "name": "Acme"}
    by = meta[PROVENANCE_KEY]
    assert (by["source"], by["integrationId"], by["blueprint"]) == ("acme", str(acme.id), NAME)
    assert by["hash"] and list(by["fileShas"]) == ["references/checklist.md"] and list(by["assets"]) == ["references/checklist.md"]
    # not published, so no agent sees it
    assert playbooks.published_playbook(db_session, workspace.gid, NAME) is None


def test_the_card_reads_applied_state_status_and_id(workspace, db_session, monkeypatch):
    register(monkeypatch, blueprint())
    acme = connect(db_session, workspace.gid)
    client = admin(workspace)
    before = client.get(API, params={"source": "acme"}).json()[0]
    assert (before["applied"], before["installedId"], before["conflict"], before["state"]) == (False, None, None, None)

    add(client, acme)
    after = client.get(API, params={"source": "acme"}).json()[0]
    row = entry(db_session, workspace.gid)
    assert (after["applied"], after["installedId"], after["installedStatus"], after["state"], after["outdated"]) == (
        True,
        str(row.id),
        "draft",
        "current",
        False,
    )


def test_adding_again_is_a_no_op(workspace, db_session, monkeypatch):
    register(monkeypatch, blueprint())
    client = admin(workspace)
    assert add(client).json()["created"] is True
    again = add(client).json()
    assert again["created"] is False and "left as it is" in again["detail"]
    assert db_session.query(Entries).filter_by(group_id=workspace.gid, slug=NAME).count() == 1


def test_only_an_admin_adds_one(workspace, db_session, monkeypatch):
    register(monkeypatch, blueprint())
    assert add(gates._sign_in(workspace, EDITOR)).status_code == 403
    assert entry(db_session, workspace.gid) is None


def _own_playbook(db_session, gid, uid, status="draft", name=NAME):
    from marvin.services.entries.entry_service import EntryService

    return EntryService(db_session, gid, actor_id=uid).create(
        {
            "entry_type_id": playbooks.ensure_playbook_type(db_session, gid),
            "title": name,
            "slug": name,
            "status": status,
            "data_json": {"name": name, "description": "Mine.", "body": "My own."},
            "created_by": uid,
        }
    )


@pytest.mark.parametrize("trash", [False, True])
def test_a_taken_name_is_refused_never_renamed_or_adopted(workspace, db_session, monkeypatch, trash):
    register(monkeypatch, blueprint())
    _own_playbook(db_session, workspace.gid, workspace.uid)
    if trash:
        entry(db_session, workspace.gid).status = "trashed"
        db_session.commit()
    client = admin(workspace)

    card = client.get(API, params={"source": "acme"}).json()[0]
    assert card["applied"] is False and f"'{NAME}' is already used" in card["conflict"]
    assert ("Trash" in card["conflict"]) is trash

    res = add(client).json()
    assert res["created"] is False and "already used" in res["detail"]
    db_session.expire_all()
    assert db_session.query(Entries).filter_by(group_id=workspace.gid, slug=NAME).one().data_json["body"] == "My own."


def test_playbooks_are_applied_last_and_the_others_still_land(workspace, db_session, monkeypatch):
    col = sdk.ContentBlueprint(
        kind="collection", slug="acme-all", name="All", payload={"name": "All", "is_smart": True, "smart_rules": {"entry_types": ["x"]}}
    )
    register(monkeypatch, blueprint(), col)
    results = apply_many(db_session, workspace.gid, list_blueprints(source="acme"), actor_id=workspace.uid)
    assert [r.kind for r in results] == ["collection", "playbook"]
    assert all(r.created for r in results), [r.detail for r in results]


def test_a_file_the_asset_store_turns_down_is_named_and_the_draft_is_still_made(workspace, db_session, monkeypatch):
    from marvin.services.assets.asset_storage_service import AssetRejected, AssetStorageService

    register(monkeypatch, blueprint())

    def refuse(self, *a, **k):
        raise AssetRejected("not an allowed type", 400)

    monkeypatch.setattr(AssetStorageService, "upload_asset", refuse)
    res = add(admin(workspace)).json()
    assert res["created"] is True and "references/checklist.md" in res["detail"] and "not an allowed type" in res["detail"]
    assert entry(db_session, workspace.gid).status == "draft"


# ── State, Update, edit protection ───────────────────────────────────────────

V2_BODY = "# Weekly report\n\nVersion two. Save it with create_draft.\n\nSee references/checklist.md and references/tone.md."


def ship_v2(monkeypatch):
    register(
        monkeypatch,
        blueprint(payload=payload(skill(V2_BODY), {"references/checklist.md": "- one\n- two\n- three\n", "references/tone.md": "Plain.\n"})),
    )


def card(client):
    return client.get(API, params={"source": "acme"}).json()[0]


def update(client, replace=False, integration=None):
    params = {"source": "acme", "replace_edits": str(replace).lower(), **({"integration_id": str(integration.id)} if integration else {})}
    return client.post(f"{API}/{NAME}/update", params=params).json()


def edit_text(db_session, gid, body="Changed here."):
    row = entry(db_session, gid)
    row.data_json = {**row.data_json, "body": body}
    db_session.commit()


def test_every_state(workspace, db_session, monkeypatch):
    register(monkeypatch, blueprint())
    client = admin(workspace)
    add(client)
    assert card(client)["state"] == "current"

    ship_v2(monkeypatch)
    assert (card(client)["state"], card(client)["outdated"]) == ("update", True)

    register(monkeypatch, blueprint())
    edit_text(db_session, workspace.gid)
    assert (card(client)["state"], card(client)["edited"], card(client)["outdated"]) == ("edited", True, False)

    ship_v2(monkeypatch)
    assert (card(client)["state"], card(client)["outdated"]) == ("edited_update", True)


def test_an_added_or_replaced_file_reads_as_an_edit(workspace, db_session, monkeypatch):
    from marvin.repos.repository_factory import AllRepositories
    from marvin.services.assets.asset_storage_service import AssetStorageService
    from marvin.services.blueprints.playbook_apply import _upload

    register(monkeypatch, blueprint())
    client = admin(workspace)
    add(client)
    row = entry(db_session, workspace.gid)
    assets = AssetStorageService.for_workspace(AllRepositories(db_session, group_id=workspace.gid))
    extra = _upload(assets, NAME, "references/extra.md", b"mine", workspace.gid, workspace.uid)
    playbooks.attach_reference(db_session, workspace.gid, row.id, extra.id, "references/extra.md")
    assert card(client)["state"] == "edited"
    update(client, replace=True)  # back to what the integration ships: the extra file goes too
    assert card(client)["state"] == "current"
    assert [f.path for f in playbooks.reference_files(db_session, row.id)] == ["references/checklist.md"]


def test_update_replaces_text_and_files_keeps_id_and_status_and_history(workspace, db_session, monkeypatch):
    from marvin.db.models.platform.assets import Assets

    register(monkeypatch, blueprint())
    client = admin(workspace)
    add(client)
    row = entry(db_session, workspace.gid)
    row_id = row.id
    row.status = "published"
    db_session.commit()
    old_checklist = playbooks.published_playbook_file(db_session, workspace.gid, NAME, "references/checklist.md")

    from marvin.services.entries.entry_service import EntryService

    updated, original = [], EntryService.update

    def spy(self, entry_id, data, **kw):
        updated.append(entry_id)
        return original(self, entry_id, data, **kw)

    monkeypatch.setattr(EntryService, "update", spy)  # the text goes through the entries' own update: history, events, same id
    ship_v2(monkeypatch)
    res = update(client)
    assert res["updated"] is True and res["needsConfirmation"] is False, res
    assert updated == [row_id]

    row = entry(db_session, workspace.gid)
    assert row.id == row_id and row.status == "published"
    assert "Version two" in row.data_json["body"]
    live = playbooks.published_playbook(db_session, workspace.gid, NAME)
    assert "Version two" in live.body  # a published one: agents use the new text at once
    assert [f.path for f in playbooks.reference_files(db_session, row.id)] == ["references/checklist.md", "references/tone.md"]
    assert card(client)["state"] == "current"
    assert row.metadata_json[PROVENANCE_KEY]["hash"] and set(row.metadata_json[PROVENANCE_KEY]["assets"]) == {
        "references/checklist.md",
        "references/tone.md",
    }
    db_session.expire_all()
    assert db_session.get(Assets, old_checklist.id).trashed_at is not None  # the replaced file's asset went to the Trash


def test_an_edited_playbook_needs_confirmation_and_the_edit_survives_until_forced(workspace, db_session, monkeypatch):
    register(monkeypatch, blueprint())
    client = admin(workspace)
    add(client)
    edit_text(db_session, workspace.gid)
    ship_v2(monkeypatch)

    refused = update(client)
    assert refused["needsConfirmation"] is True and refused["updated"] is False
    assert entry(db_session, workspace.gid).data_json["body"] == "Changed here."

    assert update(client, replace=True)["updated"] is True
    assert "Version two" in entry(db_session, workspace.gid).data_json["body"]


def test_forced_update_of_an_edited_copy_restores_the_integrations_version(workspace, db_session, monkeypatch):
    register(monkeypatch, blueprint())
    client = admin(workspace)
    add(client)
    edit_text(db_session, workspace.gid)
    assert card(client)["state"] == "edited"
    assert update(client)["needsConfirmation"] is True
    assert update(client, replace=True)["updated"] is True
    assert "Changed here" not in entry(db_session, workspace.gid).data_json["body"]
    assert card(client)["state"] == "current"


def test_update_is_admin_only_and_needs_the_playbook_to_be_there(workspace, db_session, monkeypatch):
    register(monkeypatch, blueprint())
    assert gates._sign_in(workspace, EDITOR).post(f"{API}/{NAME}/update", params={"source": "acme"}).status_code == 403
    assert "not applied" in update(admin(workspace))["detail"]


# ── Footprint, the Playbooks page, a removed integration ─────────────────────


def footprint(client, integration):
    return client.get(f"/api/groups/integrations/{integration.id}/footprint").json()


def test_the_footprint_lists_the_playbook_published_or_not(workspace, db_session, monkeypatch):
    register(monkeypatch, blueprint())
    acme, other = connect(db_session, workspace.gid), connect(db_session, workspace.gid)
    client = admin(workspace)
    add(client, acme)
    got = footprint(client, acme)
    assert [(i["name"], i["enabled"]) for i in got["playbooks"]] == [(NAME, False)]
    assert got["total"] == 1
    assert footprint(client, other)["playbooks"] == [] and footprint(client, other)["total"] == 0

    row = entry(db_session, workspace.gid)
    row.status = "published"
    db_session.commit()
    assert footprint(client, acme)["playbooks"][0]["enabled"] is True


def test_the_playbooks_page_says_where_it_came_from_and_when_that_integration_is_gone(workspace, db_session, monkeypatch):
    register(monkeypatch, blueprint())
    acme = connect(db_session, workspace.gid)
    client = admin(workspace)
    add(client, acme)
    _own_playbook(db_session, workspace.gid, workspace.uid, name="my-own")

    items = {i["name"]: i for i in client.get("/api/groups/playbooks").json()["items"]}
    assert items["my-own"]["fromIntegration"] is None
    assert items[NAME]["fromIntegration"] == {"source": "acme", "name": "Acme", "integrationId": str(acme.id), "removed": False}

    db_session.delete(db_session.get(IntegrationModel, acme.id))
    db_session.commit()
    items = {i["name"]: i for i in client.get("/api/groups/playbooks").json()["items"]}
    assert items[NAME]["fromIntegration"]["removed"] is True and items[NAME]["fromIntegration"]["integrationId"] is None
    assert items[NAME]["status"] == "draft"  # it stays


def test_a_removed_integrations_playbook_is_not_swept_with_its_other_items(workspace, db_session, monkeypatch):
    register(monkeypatch, blueprint())
    acme = connect(db_session, workspace.gid)
    client = admin(workspace)
    add(client, acme)
    db_session.delete(db_session.get(IntegrationModel, acme.id))
    db_session.commit()
    client.delete("/api/groups/removed-integration-items/workflows")
    assert entry(db_session, workspace.gid) is not None


def test_adding_the_provider_again_takes_its_playbook_back_and_update_records_it(workspace, db_session, monkeypatch):
    register(monkeypatch, blueprint())
    client = admin(workspace)
    first = connect(db_session, workspace.gid)
    add(client, first)
    db_session.delete(db_session.get(IntegrationModel, first.id))
    db_session.commit()
    second = connect(db_session, workspace.gid)
    assert [i["name"] for i in footprint(client, second)["playbooks"]] == [NAME]  # the provider is back: it is theirs again
    items = {i["name"]: i for i in client.get("/api/groups/playbooks").json()["items"]}
    assert items[NAME]["fromIntegration"]["removed"] is False and items[NAME]["fromIntegration"]["integrationId"] == str(second.id)
    update(client, integration=second)  # nothing new to take, but the connection is recorded
    assert entry(db_session, workspace.gid).metadata_json[PROVENANCE_KEY]["integrationId"] == str(second.id)


# ── What agents see ──────────────────────────────────────────────────────────


def test_a_published_integration_playbook_loads_like_any_other_and_a_draft_does_not(workspace, db_session, monkeypatch):
    register(monkeypatch, sdk.ContentBlueprint(kind="playbook", slug=NAME, name="W", payload=payload(skill(tools="list_events get_entry"))))
    client = admin(workspace)
    add(client)
    assert playbooks.published_playbooks(db_session, workspace.gid) == []

    row = entry(db_session, workspace.gid)
    row.status = "published"
    db_session.commit()
    found = playbooks.published_playbook(db_session, workspace.gid, NAME)
    assert found is not None and found.allowed_tools == "list_events get_entry"
    assert playbooks.published_playbook_file(db_session, workspace.gid, NAME, "references/checklist.md") is not None
    # the integration being off or removed does not hide it
    acme = connect(db_session, workspace.gid)
    acme.enabled = False
    db_session.commit()
    assert playbooks.published_playbook(db_session, workspace.gid, NAME) is not None
