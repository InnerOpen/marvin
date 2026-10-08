"""What every alert settings page shares (services/alerting.py): a channel's last delivery, a kind of alert,
and a message-capable action a route can use. Admin → Platform alerts and Settings → Automation →
Notifications build their own schemas on these."""

from datetime import datetime
from typing import Literal

from pydantic import UUID4, Field

from marvin.schemas._marvin import _MarvinModel


class AlertDelivery(_MarvinModel):
    at: datetime
    outcome: Literal["sent", "failed", "skipped"]
    detail: str
    event_type: str | None = None
    """The event that was sent; None for a test."""
    test: bool = False

    @classmethod
    def from_status(cls, raw: dict | None):
        """A stored last delivery, or None (nothing yet, or unreadable)."""
        try:
            return cls.model_validate(raw) if raw else None
        except ValueError:
            return None


class AlertKindRead(_MarvinModel):
    key: str
    label: str
    description: str
    event_type: str
    enabled: bool
    default: bool
    push: bool = True
    """False: the Push channel never takes this kind (people choose it in their Profile instead)."""


class AlertActionInput(_MarvinModel):
    key: str
    label: str
    description: str = ""
    required: bool = False


class AlertTarget(_MarvinModel):
    integration_id: UUID4
    integration_name: str
    provider: str
    provider_name: str
    connection_enabled: bool
    action: str
    action_label: str
    inputs: list[AlertActionInput] = Field(default_factory=list)

    @classmethod
    def from_target(cls, target):
        """An ``alerting.Target`` as this schema, with the action's own inputs (the message is Marvin's)."""
        action = target.action
        input_cls = cls.model_fields["inputs"].annotation.__args__[0]
        return cls(
            integration_id=target.integration_id,
            integration_name=target.integration_name,
            provider=target.provider,
            provider_name=target.provider_name,
            connection_enabled=target.connection_enabled,
            action=action.key,
            action_label=action.label,
            inputs=[
                input_cls(
                    key=key,
                    label=(prop or {}).get("title") or key,
                    description=(prop or {}).get("description") or "",
                    required=key in action.required,
                )
                for key, prop in action.inputs.items()
            ],
        )


class AlertTestRequest(_MarvinModel):
    channel: str
    """``email``, or a saved route's id."""
