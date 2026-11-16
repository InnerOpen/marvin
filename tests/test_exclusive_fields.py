"""Fields that take turns (`exclusive_with`): a story's script is written in its Fountain box OR attached as its Fountain file.

Every write sends the whole data, so "this write fills the second" is read against the entry as stored: a write that leaves both
filled is refused (422, naming both) unless both were already filled before it, so a record saved before the rule still saves.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.platform import Entries, EntryTypes
from marvin.db.models.platform.assets import Assets
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.repos.repository_factory import AllRepositories
from marvin.schemas.platform.entry_type_schema import EntryTypeSchemaDefinition
from marvin.services.automation.actions.base import AutomationActionError
from marvin.services.automation.actions.entry import run_entry_action
from marvin.services.automation.authz import ROLE_ADMIN
from marvin.services.blueprints.apply import BlueprintParameterError, _exclusive_names_known, entry_type_additions
from marvin.services.content_validator import exclusive_conflict, is_filled

FOUNTAIN = {"key": "fountain", "label": "Fountain", "type": "markdown", "format": "fountain", "exclusive_with": ["fountain_file"]}
FILE = {"key": "fountain_file", "label": "Fountain file", "type": "asset", "preview": "text", "exclusive_with": ["fountain"]}
SCHEMA = {"fields": [{"key": "premise", "label": "Premise", "type": "text"}, FOUNTAIN, FILE]}


def _schema(fields=None) -> EntryTypeSchemaDefinition:
    return EntryTypeSchemaDefinition.model_validate({"fields": fields or SCHEMA["fields"]})


class TestTheSchema:
    def test_a_field_names_the_fields_it_takes_turns_with_and_a_file_may_read_as_text(self):
        parsed = _schema()
        assert parsed.get_field("fountain").exclusive_with == ["fountain_file"]
        assert parsed.get_field("fountain_file").preview == "text"
        assert [(a.key, b.key) for a, b in parsed.exclusive_pairs()] == [("fountain", "fountain_file")]

    def test_one_side_naming_the_other_is_enough(self):
        parsed = _schema([{**FOUNTAIN}, {k: v for k, v in FILE.items() if k != "exclusive_with"}])
        assert [(a.key, b.key) for a, b in parsed.exclusive_pairs()] == [("fountain", "fountain_file")]

    def test_a_name_that_is_not_a_field_is_left_out_so_the_type_keeps_saving(self):
        assert _schema([{**FOUNTAIN, "exclusive_with": ["gone"]}]).exclusive_pairs() == []

    @pytest.mark.parametrize(
        "bad",
        [
            {**FOUNTAIN, "exclusive_with": ["fountain"]},
            {**FOUNTAIN, "exclusive_with": ["fountain_file", "fountain_file"]},
            {**FOUNTAIN, "exclusive_with": ["not a key"]},
        ],
    )
    def test_itself_twice_or_not_a_key_is_refused(self, bad):
        with pytest.raises(ValidationError):
            _schema([bad, FILE])

    def test_preview_is_text_or_nothing(self):
        with pytest.raises(ValidationError):
            _schema([FOUNTAIN, {**FILE, "preview": "html"}])

    def test_a_package_naming_a_field_the_type_lacks_is_refused(self):
        with pytest.raises(BlueprintParameterError, match="fountain -> fountain_fyle"):
            _exclusive_names_known({"fields": [{**FOUNTAIN, "exclusive_with": ["fountain_fyle"]}, FILE]}, "story")
        _exclusive_names_known(SCHEMA, "story")

    def test_a_package_update_adds_the_setting_to_a_field_the_workspace_already_has(self):
        row = SimpleNamespace(
            schema_json={
                "fields": [
                    {"key": "fountain", "label": "Fountain", "type": "markdown", "helpText": "mine"},
                    {"key": "fountain_file", "label": "F", "type": "asset"},
                ]
            }
        )
        blueprint = SimpleNamespace(payload={"schema_json": {"fields": [{**FOUNTAIN, "helpText": "new"}, FILE]}})
        schema, notes = entry_type_additions(row, blueprint)
        fountain, file = schema["fields"]
        assert fountain["exclusive_with"] == ["fountain_file"] and fountain["helpText"] == "mine"  # a setting already there is kept
        assert file["exclusive_with"] == ["fountain"] and file["preview"] == "text"
        assert any("exclusive_with" in n for n in notes)


class TestTheRule:
    @pytest.mark.parametrize("empty", [None, "", "   \n", [], ["  "]])
    def test_blank_holds_nothing(self, empty):
        assert not is_filled(empty)

    def test_one_or_the_other_or_neither_goes_ahead(self):
        for data in ({"fountain": "INT. PORCH"}, {"fountain_file": "a1"}, {}, {"fountain": "  ", "fountain_file": "a1"}):
            assert exclusive_conflict(_schema(), data) is None

    def test_both_in_one_write_is_refused_naming_both(self):
        said = exclusive_conflict(_schema(), {"fountain": "INT. PORCH", "fountain_file": "a1"})
        assert "“Fountain” (fountain)" in said and "“Fountain file” (fountain_file)" in said and "Clear one" in said

    def test_the_second_while_the_first_holds_something_says_which_to_clear(self):
        said = exclusive_conflict(_schema(), {"fountain": "INT. PORCH", "fountain_file": "a1"}, before={"fountain": "INT. PORCH"})
        assert said.startswith("“Fountain” (fountain) already holds something") and "Clear “Fountain” first" in said
        said = exclusive_conflict(_schema(), {"fountain": "x", "fountain_file": "a1"}, before={"fountain_file": "a1"})
        assert "Clear “Fountain file” first, then fill “Fountain”" in said

    def test_a_record_already_in_both_still_saves(self):
        both = {"fountain": "INT. PORCH", "fountain_file": "a1"}
        assert exclusive_conflict(_schema(), both, before=both) is None
        assert exclusive_conflict(_schema(), {**both, "fountain": "INT. KITCHEN"}, before=both) is None
        assert exclusive_conflict(_schema(), {**both, "premise": "new"}, before=both) is None


class _Bus:
    def dispatch(self, **_):
        pass


@fixture
def ws(db_session):
    """A committed workspace with a story type whose script is a text or a file, an asset and a person to act as."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.db.models.users.users import Users
    from marvin.services.group.group_purge import purge_group_dependents

    session = db_session
    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=session, name=f"ex-{marker}", slug=f"ex-{marker}")
    g.id = gid
    session.add(g)
    session.flush()
    if session.query(GroupPreferencesModel).filter_by(group_id=gid).first() is None:
        session.add(GroupPreferencesModel(session=session, group_id=gid))
    uid = uuid.uuid4()
    session.execute(
        Users.__table__.insert().values(
            id=uid, group_id=gid, username=f"ed-{marker}", email=f"ex-{marker}@t.test",
            full_name="Ed", password="x", is_superuser=False, platform_role="NONE", auth_method="MARVIN"
        )
    )  # fmt: skip
    et = EntryTypes(session=session, group_id=gid, name="Story", slug="story", schema_json=SCHEMA)
    et.id = uuid.uuid4()
    session.add(et)
    asset = Assets(
        session=session, group_id=gid, slug=f"script-{marker}", name="script", original_filename="script.fountain", filename="script.fountain",
        extension="fountain", file_size=10, mime_type="application/octet-stream", asset_type="document", checksum=marker,
        storage_provider="local", storage_key=f"{gid.hex}/script.fountain", uploaded_by=uid,
    )  # fmt: skip
    session.add(asset)
    session.commit()

    def story(**data) -> Entries:
        e = Entries(
            session=session, group_id=gid, entry_type_id=et.id, title="Porch", slug=f"porch-{uuid.uuid4().hex[:6]}", data_json=data, status="draft"
        )
        session.add(e)
        session.commit()
        return e

    yield SimpleNamespace(gid=gid, uid=uid, type=et, file=str(asset.id), story=story, session=session)
    app.dependency_overrides.pop(get_current_user, None)
    session.rollback()
    purge_group_dependents(session, gid)
    session.query(Groups).filter(Groups.id == gid).delete()
    session.commit()


def _repos(ws):
    return AllRepositories(ws.session, group_id=ws.gid).entries


class TestEveryWrite:
    def test_create_with_both_is_refused_and_with_one_goes_ahead(self, ws):
        with pytest.raises(HTTPException) as e:
            _repos(ws).create(
                {"entry_type_id": ws.type.id, "group_id": ws.gid, "title": "A", "data_json": {"fountain": "INT.", "fountain_file": ws.file}}
            )
        assert e.value.status_code == 422 and "fountain_file" in e.value.detail
        ws.session.rollback()
        made = _repos(ws).create(
            {"entry_type_id": ws.type.id, "group_id": ws.gid, "title": "B", "data_json": {"fountain": "INT.", "fountain_file": ""}}
        )
        assert made.data_json["fountain"] == "INT."

    def test_update_that_fills_the_file_while_the_text_is_there_is_refused(self, ws):
        s = ws.story(fountain="INT. PORCH")
        with pytest.raises(HTTPException) as e:
            _repos(ws).update(s.id, {"data_json": {"fountain": "INT. PORCH", "fountain_file": ws.file}})
        assert e.value.status_code == 422 and "Clear “Fountain” first" in e.value.detail

    def test_the_worker_swapping_one_for_the_other_in_one_write_goes_ahead(self, ws):
        s = ws.story(fountain_file=ws.file)
        _repos(ws).update(s.id, {"data_json": {"fountain": "INT. NEW", "fountain_file": None}})  # apply_revision with a proposed text
        _repos(ws).update(s.id, {"data_json": {"fountain": "", "fountain_file": ws.file}})  # apply_revision with a file

    def test_a_record_already_in_both_saves_with_them_as_they_are(self, ws):
        s = ws.story(fountain="INT. PORCH", fountain_file=ws.file)
        out = _repos(ws).update(s.id, {"data_json": {"fountain": "INT. PORCH\r\n", "fountain_file": ws.file, "premise": "Two on a porch"}})
        assert out.data_json["premise"] == "Two on a porch"

    def test_a_workflow_set_data_is_refused_with_the_reason(self, ws):
        s = ws.story(fountain_file=ws.file)
        with pytest.raises(AutomationActionError, match="Clear “Fountain file” first"):
            run_entry_action(
                ws.session, ws.gid, {"kind": "entry", "op": "set_data", "data": {"fountain": "INT. PORCH"}},
                {"event": {"entry_id": str(s.id)}, "steps": {}, "depth": 0}, authorizer_role=ROLE_ADMIN,
            )  # fmt: skip

    def test_an_applied_suggestion_is_refused_too(self, ws):
        s = ws.story(fountain="INT. PORCH")
        with pytest.raises(HTTPException) as e:
            _repos(ws).apply_fields(s.id, {"data_json.fountain_file": ws.file})
        assert e.value.status_code == 422
        _repos(ws).apply_fields(s.id, {"data_json.premise": "fine"})

    def test_rest_says_422_with_the_words(self, ws):
        role = WorkspaceRole.EDITOR
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=ws.uid, group_id=ws.gid, active_group_id=ws.gid, admin=False, is_superuser=False, full_name="Ed", email="ed@t.test",
            platform_role=PlatformRole.NONE, workspace_memberships=[SimpleNamespace(group_id=ws.gid, workspace_role=role)],
            get_workspace_role=lambda g: role if str(g) == str(ws.gid) else None, has_workspace_role=lambda g, required: str(g) == str(ws.gid),
        )  # fmt: skip
        s = ws.story(fountain="INT. PORCH")
        r = TestClient(app).patch(f"/api/platform/entries/{s.id}", json={"dataJson": {"fountain": "INT. PORCH", "fountain_file": ws.file}})
        assert r.status_code == 422, r.text
        assert "“Fountain file” (fountain_file)" in r.json()["detail"]
