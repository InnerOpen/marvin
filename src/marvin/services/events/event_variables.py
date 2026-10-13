"""Build a flat variable dict from an Event for use in email template rendering."""

from fastapi.encoders import jsonable_encoder

from marvin.services.event_bus_service.event_types import Event


def enrich_variables(variables: dict, group_id=None) -> dict:
    """Inject derived convenience variables that may be missing from the raw event dict.

    Currently injects login_url from BASE_URL if not already present, so the welcome
    template (which has no invitation_url or reset_url in the event) gets a valid button_link.
    """
    if not variables.get("login_url"):
        try:
            from marvin.core.config import get_app_settings

            variables["login_url"] = get_app_settings().BASE_URL
        except Exception:
            pass

    # Re-compute button_link to pick up any newly-injected URL fields
    if not variables.get("button_link"):
        variables["button_link"] = (
            variables.get("invitation_url")
            or variables.get("reset_url")
            or variables.get("login_url")
            or variables.get("action_url")
            or variables.get("url")
            or variables.get("site_url")
            or ""
        )

    return variables


def build_event_variables(event: Event) -> dict:
    """Return a flat dict of all variables available for event-triggered email templates.

    Pulls all fields from event.document_data, plus top-level event metadata.
    Template authors can reference any of these as {{ variable_name }}.
    """
    variables: dict = {}

    if event.document_data is not None:
        # by_alias=False ensures snake_case keys so {{ workspace_name }} works in templates
        raw = jsonable_encoder(event.document_data, exclude_none=True, by_alias=False)
        if isinstance(raw, dict):
            variables.update(raw)

    variables["event_type"] = event.event_type.name
    variables["timestamp"] = event.timestamp.isoformat() if event.timestamp else ""
    variables["workspace_id"] = str(event.workspace_id)
    if event.user_id:
        variables["user_id"] = str(event.user_id)
    if event.entity_id:
        variables["entity_id"] = str(event.entity_id)

    # Include the event bus message title and body — useful as email subject/body
    if event.message:
        variables["message_title"] = event.message.title or ""
        variables["message_body"] = event.message.body or ""

    # Convenience alias — whichever email field is in the event
    variables["email_address"] = variables.get("invitee_email") or variables.get("recipient_email") or variables.get("email") or ""

    # Derive button_link from whichever URL field is present
    variables["button_link"] = (
        variables.get("invitation_url")
        or variables.get("reset_url")
        or variables.get("login_url")
        or variables.get("action_url")
        or variables.get("url")
        or variables.get("site_url")
        or ""
    )

    return variables
