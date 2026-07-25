"""System workflow collections.

Every workspace gets a small set of **system** collections that mirror the entry review
pipeline: Inbox → Drafts → Needs Review → Approved → Archive. They are:

- **smart** — membership is derived from entry status (see smart_collections), so entries move
  between them automatically as they progress;
- **system** (`is_system=True`) — locked from edit/delete (workflow infrastructure);
- **internal** (`is_public=False`) — never exposed via the publish API.

Seeding is idempotent (keyed on group_id + slug), so it is safe to run on every startup and for
each newly-created workspace.
"""

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

# Ordered before user collections via negative sort_order. `statuses` becomes the smart rule.
WORKFLOW_COLLECTIONS: list[dict] = [
    {"slug": "inbox", "name": "Inbox", "icon": "📥", "description": "New, unprocessed entries.", "sort_order": -40, "statuses": ["inbox"]},
    {"slug": "drafts", "name": "Drafts", "icon": "✏️", "description": "Entries being written.", "sort_order": -30, "statuses": ["draft"]},
    {
        "slug": "needs-review",
        "name": "Needs Review",
        "icon": "👀",
        "description": "Entries awaiting review.",
        "sort_order": -20,
        "statuses": ["needs_review"],
    },
    {
        "slug": "approved",
        "name": "Approved",
        "icon": "✅",
        "description": "Approved and ready to publish.",
        "sort_order": -10,
        "statuses": ["approved"],
    },
    {
        "slug": "archive",
        "name": "Archive",
        "icon": "🗄️",
        "description": "Archived entries, retired from the active pipeline.",
        "sort_order": -5,
        "statuses": ["archived"],
    },
]

# The slugs of Marvin-managed workflow collections. They are seeded per workspace and locked from
# create/edit, and they are status-driven (an entry appears in them by its status, not by explicit
# membership) — so a backup restore must skip them rather than try to recreate them.
SYSTEM_COLLECTION_SLUGS: frozenset[str] = frozenset(c["slug"] for c in WORKFLOW_COLLECTIONS)


def seed_system_workflow_collections(session, group_id) -> int:
    """Ensure the system workflow collections exist for one workspace and are materialized.

    Idempotent — skips any slug already present. Creates smart, system, non-public collections
    and materializes their membership from current entries. Does NOT commit (the caller does).
    Returns the number of collections created.
    """
    from marvin.db.models.platform.collections import Collections
    from marvin.services.collections.smart_collections import sync_collection

    existing_slugs = {row[0] for row in session.query(Collections.slug).filter(Collections.group_id == group_id).all()}

    created = 0
    for defn in WORKFLOW_COLLECTIONS:
        if defn["slug"] in existing_slugs:
            continue
        collection = Collections(
            session=session,
            group_id=group_id,
            slug=defn["slug"],
            name=defn["name"],
            description=defn["description"],
            icon=defn["icon"],
            sort_order=defn["sort_order"],
            is_smart=True,
            smart_rules={"statuses": defn["statuses"], "match": "all"},
            is_system=True,
            is_public=False,
        )
        session.add(collection)
        session.flush()  # assign id before materializing membership
        sync_collection(session, group_id, collection)
        created += 1
        logger.debug(f"Seeded system collection '{defn['slug']}' for workspace {group_id}")

    return created


def seed_all_workspaces(session) -> int:
    """Seed system workflow collections into every existing workspace. Commits. Returns total created."""
    from marvin.db.models.groups.groups import Groups

    total = 0
    for group in session.query(Groups).all():
        total += seed_system_workflow_collections(session, group.id)

    if total:
        session.commit()
        logger.info(f"System workflow collections: seeded {total} collection(s) across workspaces")
    else:
        logger.debug("System workflow collections: already present")
    return total
