from typing import Annotated

from pydantic import Field, StringConstraints, field_validator
from pydantic_core.core_schema import ValidationInfo

from marvin.schemas._marvin import _MarvinModel


class UserRegistrationCreate(_MarvinModel):
    group: str | None = None
    group_token: Annotated[str | None, Field(validate_default=True)] = None
    email: Annotated[str, StringConstraints(to_lower=True, strip_whitespace=True)]
    username: Annotated[str, StringConstraints(to_lower=True, strip_whitespace=True)]
    full_name: Annotated[str, StringConstraints(strip_whitespace=True)]
    password: str
    password_confirm: str
    advanced: bool = False
    private: bool = False

    seed_data: bool = False

    @field_validator("password")
    @classmethod
    def password_long_enough(cls, value: str) -> str:
        from .password_rules import check_password_length

        return check_password_length(value)

    @field_validator("password_confirm")
    @classmethod
    def passwords_match(cls, value, info: ValidationInfo):
        if "password" in info.data and value != info.data["password"]:
            raise ValueError("passwords do not match")
        return value

    @field_validator("group_token")
    @classmethod
    def group_or_token(cls, value, info: ValidationInfo):
        # Either group_token OR group must be provided (both can be None/empty, but not both)
        has_token = value is not None and value.strip() != ""
        has_group = "group" in info.data and info.data["group"] is not None and info.data["group"].strip() != ""

        if not has_token and not has_group:
            raise ValueError("group or group_token must be provided")

        return value
