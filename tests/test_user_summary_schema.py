"""A user without a username must not break every response that embeds one.

`UserSQLModel.username` is nullable, and stays NULL when a user is created with neither a username
nor a full name to derive one from. `UserSummary` declared it as a required `str`, so the moment
such a user existed, any response carrying `list[UserSummary]` — GroupRead does — failed to
serialize and the endpoint returned 500. That took out GET /api/admin/groups, and with it the
Platform Users page, which loads groups alongside the user list.
"""

import uuid

import pytest
from pydantic import ValidationError

from marvin.schemas.group.group import GroupRead
from marvin.schemas.user.user import UserSummary


def _summary_payload(**overrides) -> dict:
    payload = {
        "id": uuid.uuid4(),
        "group_id": uuid.uuid4(),
        "username": "ada",
        "email": "ada@example.com",
        "full_name": "Ada Lovelace",
    }
    payload.update(overrides)
    return payload


def test_user_summary_accepts_null_username():
    summary = UserSummary(**_summary_payload(username=None))

    assert summary.username is None


def test_user_summary_accepts_user_with_no_name_at_all():
    """The exact shape the API produces for a user created with only an email and password."""
    summary = UserSummary(**_summary_payload(username=None, full_name=None))

    assert summary.username is None
    assert summary.full_name is None


def test_user_summary_still_accepts_a_username():
    summary = UserSummary(**_summary_payload(username="ada"))

    assert summary.username == "ada"


def test_user_summary_rejects_a_non_string_username():
    """Optional must not mean untyped — a wrong type is still a validation error."""
    with pytest.raises(ValidationError):
        UserSummary(**_summary_payload(username=123))


def test_group_read_serializes_a_member_with_no_username():
    """The regression itself: GroupRead embeds list[UserSummary] and used to raise here."""
    group = GroupRead(
        id=uuid.uuid4(),
        name="Test Workspace",
        slug="test-workspace",
        users=[UserSummary(**_summary_payload(username=None, full_name=None))],
    )

    assert group.users[0].username is None
    # Serializing is what the endpoint actually does, and where the 500 surfaced.
    assert group.model_dump()["users"][0]["username"] is None
