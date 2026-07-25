"""Secret/variable CRUD events (backlog Phase 1).

The load-bearing guarantee: a secret event NEVER carries the value — not on the model, and not through
the template-variable flattening that feeds notifications. Variables are plain-text, so theirs may.
"""

import uuid

from fastapi.encoders import jsonable_encoder

from marvin.services.event_bus_service.event_types import EventDocumentType, EventOperation, EventSecretData, EventVariableData
from marvin.services.events.event_catalog import CATALOG

SECRET_EVENTS = ["secret_created", "secret_updated", "secret_deleted"]
VARIABLE_EVENTS = ["variable_created", "variable_updated", "variable_deleted"]


def test_secret_payload_has_no_value_field_but_variable_does():
    assert "value" not in EventSecretData.model_fields
    assert "value" in EventVariableData.model_fields


def test_secret_payload_never_leaks_a_value_when_flattened():
    # jsonable_encoder(..., by_alias=False) mirrors build_event_variables() — the notification path.
    payload = EventSecretData(operation=EventOperation.create, slug="OPENAI_API_KEY", name="OpenAI", workspace_id=uuid.uuid4())
    flat = jsonable_encoder(payload, exclude_none=True, by_alias=False)
    assert flat["slug"] == "OPENAI_API_KEY" and flat["name"] == "OpenAI"
    assert flat["document_type"] == EventDocumentType.secret.value
    assert "value" not in flat


def test_variable_payload_carries_the_value():
    payload = EventVariableData(operation=EventOperation.update, slug="SITE_URL", name="Site", value="https://example.com", workspace_id=uuid.uuid4())
    flat = jsonable_encoder(payload, exclude_none=True, by_alias=False)
    assert flat["value"] == "https://example.com"


def test_all_six_events_are_advertised_and_categorised():
    entries = {c.event_type: c for c in CATALOG}
    for et in SECRET_EVENTS:
        assert et in entries and entries[et].enabled, f"{et} not subscribable"
        assert entries[et].category == "Secrets"
    for et in VARIABLE_EVENTS:
        assert et in entries and entries[et].enabled, f"{et} not subscribable"
        assert entries[et].category == "Variables"


def test_secret_catalog_entries_advertise_no_value_variable():
    entries = {c.event_type: c for c in CATALOG}
    for et in SECRET_EVENTS:
        assert "value" not in {v.slug for v in entries[et].variables}
    # variable create/update advertise the value; delete does not.
    assert "value" in {v.slug for v in entries["variable_updated"].variables}
    assert "value" not in {v.slug for v in entries["variable_deleted"].variables}
