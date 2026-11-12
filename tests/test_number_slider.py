"""A number field may ask for a drag slider beside its box; it needs both ends."""

import pytest
from pydantic import ValidationError

from marvin.schemas.platform.entry_type_schema import EntryTypeSchemaDefinition


def _schema(**field) -> dict:
    return {"fields": [{"key": "level", "label": "Level", "type": "number", **field}]}


def test_a_number_field_with_both_ends_may_have_a_slider():
    parsed = EntryTypeSchemaDefinition.model_validate(_schema(min=0, max=1, step=0.01, slider=True))
    assert parsed.fields[0].slider is True


def test_a_slider_is_off_unless_asked_for():
    assert EntryTypeSchemaDefinition.model_validate(_schema(min=0, max=1)).fields[0].slider is False
    assert EntryTypeSchemaDefinition.model_validate(_schema()).fields[0].slider is False


@pytest.mark.parametrize("ends", [{}, {"min": 0}, {"max": 1}, {"min": 1, "max": 1}, {"min": 2, "max": 1}])
def test_a_slider_without_two_different_ends_is_refused(ends):
    with pytest.raises(ValidationError, match="a slider or a meter needs a min and a max"):
        EntryTypeSchemaDefinition.model_validate(_schema(slider=True, **ends))


def test_the_flag_survives_a_round_trip_so_a_package_can_carry_it():
    again = EntryTypeSchemaDefinition.model_validate(
        EntryTypeSchemaDefinition.model_validate(_schema(min=0, max=30, slider=True)).model_dump(by_alias=True)
    )
    assert again.fields[0].slider is True and again.fields[0].max == 30


def test_a_number_field_may_ask_for_a_meter_for_a_measured_value_and_it_needs_both_ends_too():
    parsed = EntryTypeSchemaDefinition.model_validate(_schema(min=-60, max=0, meter=True, readOnly=True))
    assert parsed.fields[0].meter is True
    assert EntryTypeSchemaDefinition.model_validate(_schema(min=-60, max=0)).fields[0].meter is False
    with pytest.raises(ValidationError, match="a slider or a meter needs a min and a max"):
        EntryTypeSchemaDefinition.model_validate(_schema(meter=True, min=0))
