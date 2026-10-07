"""A workspace template can replace Marvin's own welcome and invitation emails (not the password-reset email: the
platform's alone, tests/test_event_secrets.py).

The email template page offers that as "Replaces Marvin's … email", with the variables of the event it's sent on,
from `GET /api/platform/workspaces/{id}/email-templates/system-emails` — not by listing platform events in
`/api/event/types`. Checked: the variables are the catalog's, the state matches what the email listener sends (and
the event page's system-email row), and connecting / disconnecting a template switches Marvin's own email off / on.
"""

import pytest

from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.email.system_email_events import SYSTEM_TEMPLATE_EVENT_MAP
from marvin.services.events import connections
from marvin.services.events.event_catalog import get_catalog_entry
from tests import test_event_connections as evc

world = evc.world  # the shared two-workspace fixture

TYPES = [("welcome", "user_signup"), ("invitation", "invitation_sent")]


def _url(world) -> str:
    return f"/api/platform/workspaces/{world.a}/email-templates"


def _system_emails(client, world) -> dict:
    res = client.get(f"{_url(world)}/system-emails")
    assert res.status_code == 200, res.text
    return {row["templateType"]: row for row in res.json()}


def test_each_system_email_lists_its_events_catalog_variables(world):
    rows = _system_emails(evc._client(world), world)
    assert set(rows) == set(SYSTEM_TEMPLATE_EVENT_MAP)
    for template_type, event_type in TYPES:
        row, entry = rows[template_type], get_catalog_entry(event_type)
        assert (row["eventType"], row["eventName"]) == (event_type, entry.name)
        # The event's variables, and the link its sender adds (the invitation's: never in the event itself).
        link = SYSTEM_TEMPLATE_EVENT_MAP[template_type].get("link_variable")
        assert row["variables"] == [{"slug": v.slug, "description": v.description, "example": v.example, "type": v.type} for v in entry.variables] + (
            [{"slug": link[0], "description": link[1], "example": "https://...", "type": "url"}] if link else []
        )
        assert row["label"].endswith("email") and row["recipientType"] == "event_field" and row["recipientField"] == "email_address"


@pytest.mark.parametrize("role", [WorkspaceRole.EDITOR, WorkspaceRole.VIEWER])
def test_only_workspace_admins_read_it(world, role):
    assert evc._client(world, role).get(f"{_url(world)}/system-emails").status_code == 403
    assert evc._client(world, WorkspaceRole.ADMIN).get(f"{_url(world)}/system-emails").status_code == 200


def test_the_platform_events_stay_off_the_workspace_event_list(world):
    offered = {e["value"] for e in evc._client(world).get("/api/event/types").json()}
    assert not {"user_signup", "user_password_reset_requested"} & offered


@pytest.mark.parametrize(("template_type", "event_type"), TYPES)
def test_connecting_a_template_replaces_marvins_email_and_disconnecting_restores_it(db_session, world, template_type, event_type):
    client = evc._client(world)
    with evc._system_template(db_session, template_type) as system:
        system.enabled = True
        db_session.commit()
        row = _system_emails(client, world)[template_type]
        assert row["systemSends"] is True and row["replacedBy"] == [] and row["systemTemplateId"] == str(system.id)
        assert evc._emails_sent(world.a, event_type) == {system.id}

        # Creating a workspace template of the type connects it (the "Replaces Marvin's … email" switch, on).
        res = client.post(f"{_url(world)}", json={"name": "Ours", "subject": "Hi", "templateType": template_type, "bodyMarkdown": "Hello"})
        assert res.status_code == 201, res.text
        own = res.json()["id"]
        row = _system_emails(client, world)[template_type]
        assert row["systemSends"] is False and row["replacedBy"] == [own]
        (sub,) = [s for s in client.get("/api/groups/email-event-subscriptions").json() if s["templateId"] == own]
        assert sub["eventType"] == event_type
        assert {str(s) for s in evc._emails_sent(world.a, event_type)} == {sub["id"]}  # the override, not Marvin's

        # The event page says the same: the system email row is off, the template's row on.
        reactions = evc._data(connections.reactions(db_session, world.a, event_type), "email")
        assert {(str(r.id), r.enabled) for r in reactions if r.detail == "System template"} == {(str(system.id), False)}

        # Switch off: the page deletes the connection, and Marvin's own email sends again.
        assert client.delete(f"/api/groups/email-event-subscriptions/{sub['id']}").status_code == 204
        row = _system_emails(client, world)[template_type]
        assert row["systemSends"] is True and row["replacedBy"] == []
        assert evc._emails_sent(world.a, event_type) == {system.id}

        # Switch on again: the page posts the connection with the system email's recipients.
        res = client.post(
            "/api/groups/email-event-subscriptions",
            json={"templateId": own, "eventType": event_type, "recipientType": row["recipientType"], "recipientField": row["recipientField"]},
        )
        assert res.status_code == 201, res.text
        assert _system_emails(client, world)[template_type]["replacedBy"] == [own]
        assert client.delete(f"{_url(world)}/{own}").status_code == 204
