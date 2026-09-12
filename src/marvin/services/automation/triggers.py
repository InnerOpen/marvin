"""Curated catalog of events that can trigger a Flavor B automation.

NOT the raw `EventTypes` firehose — a meaningful, grouped allowlist of events that (a) are actually
emitted (see the event-catalog honesty pass) and (b) are useful to react to. Internal/audit noise is
deliberately excluded: `ai_operation_executed`, `ai_embeddings_reindexed`, `*_delivery_*`,
`scheduled_task_*`, `webhook_task`, notifications, search-index, session/auth, budget/quota,
`automation_ran`/`automation_failed` (those drive the `chained`/`on_error` trigger TYPES, not the
event dropdown).

Adding a family here is what lets `$event.<field>` conditions fire for non-entry events — the engine
flattens each event's `document_data` into the match context, so an `asset_uploaded` trigger can
condition on `event.asset_type == "image"`, a `resource_created` on `event.resource_type`, etc.
"""

# Grouped {group label: [event_type name, ...]} — drives the builder's trigger dropdown AND the
# reaction listener (an event fires an "event"-type automation only if its name is listed here).
TRIGGER_EVENT_GROUPS: dict[str, list[str]] = {
    "Entries": [
        "entry_created",
        "entry_updated",
        "entry_published",
        "entry_unpublished",
        "entry_archived",
        "entry_restored",
        "entry_deleted",
        "entry_resource_attached",
        "entry_resource_detached",
        "entry_tag_attached",
        "entry_tag_detached",
        "asset_attached_to_entry",
        "asset_detached_from_entry",
    ],
    "Collections": [
        "entry_added_to_collection",
        "entry_removed_from_collection",
        "collection_created",
        "collection_updated",
        "collection_deleted",
    ],
    "Assets": ["asset_uploaded", "asset_updated", "asset_deleted"],
    "Resources": ["resource_created", "resource_updated", "resource_deleted"],
    # `form_submission_received` is the one that matters for a site: it carries the submitted fields
    # as `event.submission_data.<key>` and the stored inbox entry as `entry.*`.
    "Forms": [
        "form_submission_received",
        "submission_surge_detected",
        "form_created",
        "form_updated",
        "form_published",
        "form_archived",
        "form_deleted",
    ],
    "Entry types": ["entry_type_created", "entry_type_updated", "entry_type_deleted"],
}

# Flat list (all groups) — the allowlist the listener checks and /options advertises.
TRIGGER_EVENT_NAMES: list[str] = [name for group in TRIGGER_EVENT_GROUPS.values() for name in group]
TRIGGER_EVENT_NAMES_SET: frozenset[str] = frozenset(TRIGGER_EVENT_NAMES)
