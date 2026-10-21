"""`automation_result` step — report back on work Marvin handed to another system (services/automation_results.py).

An integration action that declares ``hands_off`` starts work elsewhere (a workflow in another tool, a build) and Marvin keeps one
result for it, in flight, without any step to remember. When the other side reports back — typically a workflow that starts on an
incoming webhook — this step settles that result, which Settings › Automation › Results then shows:

* ``status`` — the other system's own word for how it went (``success``, ``error``, ``waiting``…; a template is fine). The connection
  named in ``integration`` turns it into Marvin's (in flight, succeeded, failed) through its provider (``result_status``), so the
  workflow stays free of that system's vocabulary. A word the provider doesn't know leaves the result in flight with the word in its
  message. Without ``integration`` the connection that installed the triggering incoming webhook is used (a plugin's report-back
  workflow then names none), else the connection of the result it settles; failing all of them only Marvin's own three are understood.
* which result — the one with ``remote_id`` (the run's id on the other side, on that connection when one is named), else the newest one
  still in flight for ``entry_id`` (default: the triggering entry) and that connection. A report that matches nothing is kept as a
  new result (``target`` says what it was about) rather than dropped.
* ``message``, ``remote_url`` (a web address for the run; kept when the result has none yet) and ``finished_at`` (ISO 8601 or epoch
  seconds; default: now) are kept on it.

Output: ``result_id``, ``status`` (Marvin's), ``matched`` (``remote_id`` | ``entry`` | ``none``) and ``created``. A dry run says what it
would do and writes nothing. It needs the workflow author's role to be AUTHOR or above, as the entry step this replaces did.
"""

from __future__ import annotations

from marvin.services import automation_results as results

from ..matcher import interpolate
from .base import AutomationActionError, register_action


def _text(value) -> str | None:
    return None if value in (None, "") else str(value).strip() or None


def _webhook_connection(session, group_id, context: dict):
    """The connection that installed the incoming webhook this run answers, or None. A plugin's report-back workflow then needs no
    ``integration`` argument: its own webhook already says whose words the report is in, whatever the connection is called."""
    from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
    from marvin.db.models.groups.integrations import IntegrationModel

    slug = _text((context.get("event") or {}).get("webhook_slug"))
    if slug is None:
        return None
    webhook = session.query(WorkspaceIncomingWebhookModel).filter_by(group_id=group_id, slug=slug).first()
    if webhook is None or webhook.source_integration_id is None:
        return None
    return session.get(IntegrationModel, webhook.source_integration_id)


@register_action("automation_result")
def run_automation_result_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    from marvin.db.models.groups.integrations import IntegrationModel

    from ..authz import AUTOMATION_RESULT_MIN_ROLE, ROLE_OWNER, require_role

    require_role(ROLE_OWNER if authorizer_role is None else authorizer_role, AUTOMATION_RESULT_MIN_ROLE, "automation_result")
    word = _text(interpolate(action.get("status"), context))
    if word is None:
        raise AutomationActionError("automation_result: `status` came out empty — the report names no status to record")
    slug = _text(interpolate(action.get("integration"), context))
    connection = None
    if slug:
        connection = session.query(IntegrationModel).filter_by(group_id=group_id, slug=slug).first()
        if connection is None:
            raise AutomationActionError(f"automation_result: integration '{slug}' not found in this workspace")
    else:
        connection = _webhook_connection(session, group_id, context)
    remote_id = _text(interpolate(action.get("remote_id"), context))
    entry_ref = interpolate(action["entry_id"], context) if action.get("entry_id") else (context.get("entry") or {}).get("id")
    entry_id = results.entry_in(session, group_id, entry_ref)
    found, matched = results.find(session, group_id, connection, remote_id, entry_id)
    if connection is None and found is not None and found.integration_id is not None:
        connection = session.get(IntegrationModel, found.integration_id)  # the words are the connection the hand-off went through
    status = _status(connection, word)
    if dry_run:
        return {
            "dry_run": True,
            "kind": "automation_result",
            "would": "settle" if found is not None else "record",
            "status": status or "in_flight",
            "matched": matched,
        }
    row, matched = results.settle(
        session,
        group_id,
        status=status,
        word=word,
        integration=connection,
        remote_id=remote_id,
        entry_id=entry_id,
        target=_text(interpolate(action.get("target"), context)),
        message=_text(interpolate(action.get("message"), context)),
        remote_url=_text(interpolate(action.get("remote_url"), context)),
        finished_at=results.parse_moment(interpolate(action.get("finished_at"), context)),
    )
    return {"result_id": str(row.id), "status": row.status, "matched": matched, "created": matched == "none"}


def _status(connection, word: str) -> str | None:
    """Marvin's status for the other system's ``word``, as the connection's provider reads it (None: unknown)."""
    if connection is not None:
        from marvin.services.integrations import INTEGRATIONS_AVAILABLE

        if INTEGRATIONS_AVAILABLE:
            from marvin.services.integrations import get_provider

            try:
                provider = get_provider(connection.provider)
            except KeyError:
                provider = None
            mapper = getattr(provider, "result_status", None)  # an older SDK has none: Marvin's own words only
            if mapper is not None:
                return mapper(word)
    return word.strip().lower() if word.strip().lower() in results.STATUSES else None
