"""A text field can say what its text is, so the form can show it: `format: fountain` on a textarea or a markdown field."""

import pytest
from pydantic import ValidationError

from marvin.schemas.platform.entry_type_schema import MarkdownFieldSchema, TextareaFieldSchema


@pytest.mark.parametrize("schema", [TextareaFieldSchema, MarkdownFieldSchema])
def test_a_text_field_may_be_declared_a_screenplay(schema):
    field = schema(key="script", label="Script", type=schema.model_fields["type"].annotation.__args__[0], format="fountain")
    assert field.format == "fountain"


@pytest.mark.parametrize("schema", [TextareaFieldSchema, MarkdownFieldSchema])
def test_a_text_field_has_no_format_unless_it_says_so(schema):
    field = schema(key="notes", label="Notes", type=schema.model_fields["type"].annotation.__args__[0])
    assert field.format is None


def test_a_format_the_form_cannot_show_is_refused():
    with pytest.raises(ValidationError):
        TextareaFieldSchema(key="notes", label="Notes", type="textarea", format="screenplay")
