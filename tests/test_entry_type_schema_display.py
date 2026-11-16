"""A read-only text field can say it holds a job's report, so the form shows it as the guided steps show a job's result."""

import pytest
from pydantic import ValidationError

from marvin.schemas.platform.entry_type_schema import EntryTypeSchemaDefinition, TextareaFieldSchema


def test_a_textarea_may_be_shown_as_a_report():
    field = TextareaFieldSchema(key="check", label="Check", type="textarea", readOnly=True, display="report")
    assert field.display == "report"


def test_a_textarea_is_plain_unless_it_says_so():
    assert TextareaFieldSchema(key="notes", label="Notes", type="textarea").display is None


def test_a_display_the_form_cannot_show_is_refused():
    with pytest.raises(ValidationError):
        TextareaFieldSchema(key="notes", label="Notes", type="textarea", display="chart")
    with pytest.raises(ValidationError):
        EntryTypeSchemaDefinition.model_validate({"fields": [{"key": "notes", "label": "Notes", "type": "textarea", "display": "chart"}]})


def test_a_package_update_gives_an_existing_field_its_display():
    """A field already in the workspace gains `display` from a newer package (a setting it lacks is added, one it has is kept)."""
    from types import SimpleNamespace

    from marvin.schemas.platform.blueprints import Blueprint
    from marvin.services.blueprints.apply import entry_type_additions

    row = SimpleNamespace(schema_json={"fields": [{"key": "check", "label": "Check", "type": "textarea", "readOnly": True}]})
    declared = {"key": "check", "label": "Check", "type": "textarea", "readOnly": True, "display": "report"}
    blueprint = Blueprint(kind="entry_type", slug="story", name="Story", payload={"schema_json": {"fields": [declared]}})
    schema, notes = entry_type_additions(row, blueprint)
    assert schema["fields"][0]["display"] == "report"
    assert notes == ["check: display"]
