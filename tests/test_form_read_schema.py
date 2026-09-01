"""FormRead must serialize from a Forms ORM object without a field-name mismatch.

The read field was named `form_schema` while the ORM column/attribute is `schema_json`. Because the
base model reads by field name under `from_attributes`/`populate_by_name`, `model_validate(orm_obj)`
found neither `form_schema` nor `formSchema` on the ORM instance, and the required field raised a
ValidationError → HTTP 500 on GET /api/forms and /api/forms/{id}. The submission path dodged it by
constructing PublishedFormRead explicitly. Reads must be total over persisted data; the field name
now matches the ORM attribute while the camelCase output stays `schemaJson`.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from marvin.schemas.platform.forms import FormRead


def _orm_like(**overrides):
    """A stand-in for a Forms ORM row — attribute names match the SQLAlchemy model, not the API."""
    obj = SimpleNamespace(
        id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        slug="contact",
        name="Contact",
        description=None,
        schema_json={"fields": [{"name": "email", "type": "email"}]},
        settings_json=None,
        metadata_json=None,
        status="published",
        submissions_count=3,
        last_submission_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        update_at=datetime.now(UTC),
    )
    for key, value in overrides.items():
        setattr(obj, key, value)
    return obj


def test_form_read_validates_from_orm_object():
    """The regression: reading a form from the ORM used to raise, 500'ing the admin form endpoints."""
    form = FormRead.model_validate(_orm_like())

    assert form.form_schema == {"fields": [{"name": "email", "type": "email"}]}


def test_form_read_serializes_schema_under_camel_case_alias():
    """The API contract is unchanged: the schema is still emitted as `schemaJson`."""
    form = FormRead.model_validate(_orm_like())

    dumped = form.model_dump(mode="json", by_alias=True)
    assert dumped["schemaJson"] == {"fields": [{"name": "email", "type": "email"}]}
    assert "form_schema" not in dumped


def test_form_read_handles_empty_schema():
    """An empty schema dict is valid — it must not be mistaken for a missing required field."""
    form = FormRead.model_validate(_orm_like(schema_json={}))

    assert form.form_schema == {}
