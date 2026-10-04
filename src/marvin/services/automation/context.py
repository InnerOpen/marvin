"""The `event` a workflow matches on (`$event.*`), built from a live Event or a logged one.

The reaction listener builds it for every triggering event; a dry run builds it from an event_log
row (or from an Event synthesized for an entry). One builder for all of them, so a dry run sees
exactly the `$event.*` a real run would have seen.
"""

from typing import Any


def event_context(
    event_type: str,
    document: dict | None,
    *,
    entity_id: Any = None,
    entity_type: str | None = None,
    user_id: Any = None,
    reaction_depth: int = 0,
    correlation_id: str | None = None,
) -> dict:
    """The match context's `event` for one event.

    ``document`` is the event's document_data with snake_case keys. It is flattened in so
    `$event.<field>` works for ANY event family (asset_type, resource_type, form_name, …) — not just
    entries. The curated keys below override, so a document field of the same name can't shadow them.

    ``entity_type``/``entity_id`` are what the event is about. The id stands in for `entry_id` only
    when that subject is an entry (or untyped): a workflow's own lifecycle event names the workflow,
    which must never be taken for the entry an entry step acts on.
    """
    doc = document or {}
    automation_id = doc.get("automation_id")
    is_entry_subject = entity_type in (None, "entry")
    return {
        **doc,
        "event_type": event_type,
        "entry_id": doc.get("entry_id") or (entity_id if is_entry_subject else None),
        # The event's subject, so a workflow's run can name what triggered it (and a condition can
        # key on $event.entity_type).
        "entity_type": entity_type if entity_id else None,
        "entity_id": str(entity_id) if entity_id else None,
        "automation_id": str(automation_id) if automation_id else None,
        "automation_slug": doc.get("automation_slug"),
        # Incoming-webhook triggers key on the webhook slug; conditions/actions reach the request
        # body via $event.payload.*
        "webhook_slug": doc.get("webhook_slug"),
        "payload": doc.get("payload"),
        # What an update changed — lets conditions key on transitions, e.g.
        # $event.after.status == "review" (only-changed-fields, so this reads as "changed to").
        "changed_fields": doc.get("changed_fields") or [],
        "before": doc.get("before") or {},
        "after": doc.get("after") or {},
        "user_id": user_id,
        "reaction_depth": reaction_depth,
        # Thread the triggering event's chain id so the whole reaction cascade shares it.
        "correlation_id": correlation_id,
    }


def event_context_from_event(event) -> dict:
    """`event_context` for a live :class:`Event` (what the reaction listener hands the engine)."""
    from fastapi.encoders import jsonable_encoder

    document: dict = {}
    if event.document_data is not None:
        try:
            document = jsonable_encoder(event.document_data, by_alias=False)
        except Exception:
            document = {}
    from marvin.services.event_bus_service.event_types import event_entity

    entity_type, entity_id = event_entity(event)
    return event_context(
        event.event_type.name,
        document,
        entity_id=entity_id,
        entity_type=entity_type,
        user_id=event.user_id,
        reaction_depth=getattr(event, "reaction_depth", 0),
        correlation_id=getattr(event, "correlation_id", None),
    )


def event_context_from_log(row) -> dict:
    """`event_context` for an event_log row — the logged event replayed.

    The log stores the Event as the API serializes it, so the document's keys are camelCase; they're
    mapped back to the snake_case names the live context uses. Only top-level keys: nested values
    such as a webhook's `payload` or an update's `before`/`after` are keyed by the sender or by field
    name and stay as they are.
    """
    from humps import decamelize

    data = row.event_data if isinstance(row.event_data, dict) else {}
    doc = data.get("documentData") or data.get("document_data") or {}
    document = {decamelize(k): v for k, v in doc.items()} if isinstance(doc, dict) else {}
    depth = data.get("reactionDepth", data.get("reaction_depth", 0))
    return event_context(
        row.event_type,
        document,
        entity_id=row.entity_id,
        entity_type=row.entity_type,
        user_id=row.user_id,
        reaction_depth=depth if isinstance(depth, int) else 0,
        correlation_id=row.correlation_id,
    )
