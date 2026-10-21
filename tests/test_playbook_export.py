# ruff: noqa: F811 — the `workspace` fixture is imported, then named as a parameter
"""Playbooks 10: export a Playbook as a standard skill folder (zip), and get the same Playbook back by importing it.

Seam: the export route (``GET /api/groups/playbooks/{id}/export``) with the import route (``POST .../import``) as its
inverse; both are driven through the API. The codec's own cases are in tests/test_skill_md.py.
"""

import io
import zipfile

from marvin.db.models.users.roles import WorkspaceRole
from marvin.services import playbooks
from tests import test_content_role_gates as gates
from tests.test_playbook_import import _entry, make_zip, post, skill

workspace = gates.workspace

PREFIX = "/api/groups/playbooks"


def export(workspace, entry_id, role=WorkspaceRole.EDITOR):
    return gates._sign_in(workspace, role).get(f"{PREFIX}/{entry_id}/export")


def members(res) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        return {i.filename: z.read(i) for i in z.infolist()}


def imported(workspace, **files):
    """Import a skill with these reference files; returns the new entry's id."""
    data = make_zip(
        {"SKILL.md": skill("tidy-notes", extra="license: MIT\nallowed-tools: find_entries\ndisable-model-invocation: true\nowner: me\n"), **files},
        folder="tidy-notes/",
    )
    res = post(workspace, data)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_a_playbook_downloads_as_a_zip_in_the_standard_layout(workspace):
    entry_id = imported(workspace, **{"references/guide.md": "# Guide\n", "scripts/run.sh": "#!/bin/sh\necho hi\n"})
    res = export(workspace, entry_id)
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    assert 'filename="tidy-notes.zip"' in res.headers["content-disposition"]
    files = members(res)
    assert sorted(files) == ["tidy-notes/SKILL.md", "tidy-notes/references/guide.md", "tidy-notes/scripts/run.sh"]
    assert files["tidy-notes/references/guide.md"] == b"# Guide\n"
    head = files["tidy-notes/SKILL.md"].decode()
    assert head.startswith("---\nname: tidy-notes\n") and "\nlicense: MIT\n" in head


def test_marvin_only_settings_sit_under_metadata_and_other_keys_stay(workspace):
    text = members(export(workspace, imported(workspace)))["tidy-notes/SKILL.md"].decode()
    assert "metadata:\n  marvin-manual-only: 'true'\n" in text
    assert "disable-model-invocation: true" in text and "owner: me" in text


def test_exporting_then_importing_gives_back_the_same_playbook(workspace, db_session):
    original_id = imported(workspace, **{"references/guide.md": "# Guide\n", "templates/a/b.txt": "deep"})
    zipped = export(workspace, original_id).content

    res = post(workspace, zipped, name="tidy-notes-copy")
    assert res.status_code == 201, res.text
    assert res.json()["fileCount"] == 2

    a, b = _entry(db_session, workspace.gid, "tidy-notes"), _entry(db_session, workspace.gid, "tidy-notes-copy")
    assert b.data_json == {**a.data_json, "name": "tidy-notes-copy"}  # every field, the body and the manual-only flag
    assert b.data_json["manual_only"] is True and b.data_json["allowed_tools"] == "find_entries"
    assert b.metadata_json["frontmatterExtra"] == a.metadata_json["frontmatterExtra"] == {"owner": "me"}

    def files(entry):
        return {f.path: gates_bytes(db_session, f) for f in playbooks.reference_files(db_session, entry.id)}

    assert files(b) == files(a) == {"references/guide.md": b"# Guide\n", "templates/a/b.txt": b"deep"}


def test_a_draft_exports_and_a_second_export_is_identical(workspace):
    entry_id = imported(workspace, **{"references/guide.md": "x"})
    assert members(export(workspace, entry_id)) == members(export(workspace, entry_id))


def test_a_playbook_without_files_exports_just_skill_md(workspace):
    res = post(workspace, skill("solo-note").encode(), filename="SKILL.md")
    assert list(members(export(workspace, res.json()["id"]))) == ["solo-note/SKILL.md"]


def test_a_viewer_cannot_export(workspace):
    assert export(workspace, imported(workspace), role=WorkspaceRole.VIEWER).status_code == 403


def test_an_unknown_or_foreign_playbook_is_a_404(workspace):
    assert export(workspace, "00000000-0000-4000-8000-000000000000").status_code == 404


def test_agents_have_no_tool_to_export():
    from marvin.services.ai.tools import list_tools

    assert not [t.name for t in list_tools() if "playbook" in t.name and "export" in t.name]


def gates_bytes(db_session, ref) -> bytes:
    from marvin.db.models.platform.assets import Assets
    from marvin.services.storage.provider_factory import provider_for

    asset = db_session.get(Assets, ref.asset_id)
    return provider_for(asset).get(asset.storage_key).read()
