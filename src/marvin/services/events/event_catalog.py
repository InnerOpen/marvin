"""
Event catalog — the one list of facts about each event type.

Each entry describes:
  - name: human-readable event name
  - description: what triggers this event
  - category: grouping for the UI
  - variables: {{slug}} values available in templates/notifications
  - enabled: whether this event is available for subscription
  - scope: "workspace" (shown in the workspace's Event Log) or "platform" (the admin Events page)
  - triggerable / trigger_group: whether a workflow can start on it, and under which heading the builder lists it
  - emittable: whether a workflow's Emit event step may send it
  - sent_by: what in Marvin sends it; leads_to: the events it causes through Marvin's own code
  - alias_of: an old name for another type; hidden: nothing sends it or it's an alias, so it's never shown

Everything else that needs one of these lists reads it from here (the workflow trigger allowlist, the
emit_event action, the builder's menus); tests/test_event_catalog_facts.py keeps them honest.
"""

from dataclasses import dataclass, field
from typing import Literal

EventScope = Literal["workspace", "platform"]


@dataclass
class EventVariable:
    slug: str
    description: str
    example: str
    type: str = "string"


@dataclass
class CatalogEntry:
    event_type: str  # matches EventTypes enum value name
    name: str
    description: str
    category: str
    variables: list[EventVariable] = field(default_factory=list)
    enabled: bool = True
    """Whether this event is offered for subscription in the Events UI."""
    audited: bool = True
    """Whether this event is persisted to the event_log audit trail by default. Set False for
    high-frequency internal plumbing whose outcomes are captured elsewhere. A workspace admin can
    override it per event type (services/events/audit_settings.py) unless the entry is locked."""
    audit_locked: bool = False
    """Always audited: no workspace override can turn it off. Set by the security gate below."""
    scope: EventScope = "workspace"
    """Whose event it is. "platform" events (sign-ups, workspaces created by a platform admin, personal tokens…)
    are still stored with the workspace they touched, but only the super-admin Events page shows them; the
    workspace's Event Log, activity feeds and audit settings leave them out. Set by the platform gate below."""
    triggerable: bool = False
    """A workflow can start on it (an "event" trigger): the builder's trigger dropdown offers it and the
    automation listener reacts to it. Curated, not the whole firehose: only events that are actually sent and
    worth reacting to. Left out on purpose: internal/audit noise (AI runs, reindexing, deliveries,
    scheduled_task_*, webhook_task, auth, budgets), automation_ran/automation_failed (they drive the chained /
    on_error trigger types instead), automation_started (a workflow reacting to runs starting — its own
    included — would loop) and site_rebuild_queued (rebuild progress, not content). A triggerable event's
    `document_data` is flattened into `$event.*`, so conditions can key on its fields."""
    trigger_group: str | None = None
    """The heading the builder lists a triggerable event under, when it isn't `category` ("Entries",
    "Collections", … split the Content category the way the dropdown reads best)."""
    emittable: bool = False
    """A workflow's Emit event step may send it (services/automation/actions/emit_event.py): entry_* events,
    built from the entry in the workflow's context, and site build/deploy events — e.g. a host's "deploy
    failed" notification turned into Marvin's own event. The emitted event carries reaction_depth + 1."""
    internal: bool = False
    """Scheduler plumbing that fires on every tick: dispatch logs it at debug level and the console listener
    skips it, so the log isn't flooded."""
    sent_by: list[str] = field(default_factory=list)
    """What in Marvin sends it, one short line per sender, written from the dispatch sites. Workflows that
    send it (an Emit event step, an integration's blueprint) are data, not listed here. Empty only for an
    event nothing sends (_NO_EMITTER)."""
    leads_to: list[str] = field(default_factory=list)
    """Event types this one causes through Marvin's own code (built-in reactions, the scheduler), e.g.
    entry_published → site_rebuild_queued → webhook_triggered. What workflows cause is data, not listed here."""
    alias_of: str | None = None
    """An old name for another event type: nothing sends it, and a workflow trigger, Emit event step or
    subscription that names it is stored (and read, and run) as the event it stands for (`canonical_event_type`)."""
    hidden: bool = False
    """Not shown or offered anywhere: nothing sends it (_NO_EMITTER), or it's an alias. Set by the hidden gate
    below; its enum member and its catalog entry stay, so old rows still have a name."""


COMMON_VARS = [
    EventVariable("workspace_name", "Name of the workspace", "My Blog", type="name"),
    EventVariable("message_title", "Auto-generated event title (e.g. 'Entry Published')", "Entry Published", type="string"),
    EventVariable("message_body", "Optional description passed when the event was dispatched", "", type="string"),
    EventVariable("event_type", "Machine-readable event name", "entry_published", type="string"),
    EventVariable("timestamp", "ISO 8601 timestamp of when the event fired", "2026-07-16T10:00:00Z", type="datetime"),
    EventVariable("email_address", "Email address from the event (invitee, recipient, etc.)", "user@example.com", type="email"),
    EventVariable("button_link", "Primary URL from the event (invitation link, reset link, etc.)", "https://...", type="url"),
]

_WEBHOOK_VARS = [
    EventVariable("webhook_id", "ID of the outgoing webhook", "<webhook-uuid>", type="string"),
    EventVariable("webhook_name", "Name of the outgoing webhook", "Deploy hook", type="name"),
    EventVariable("webhook_type", "Its type", "event_driven", type="string"),
    EventVariable("enabled", "Whether it is switched on", "true"),
    EventVariable("subscribed_events", "The events it is subscribed to", "[...]"),
]
"""An outgoing webhook's settings, never its URL or headers (either can carry a credential)."""

_API_TOKEN_VARS = [
    EventVariable("token_id", "ID of the token", "<token-uuid>", type="string"),
    EventVariable("token_name", "Name given to the token", "CI Deploy Token", type="name"),
    EventVariable("user_id", "ID of the user who owns it", "<user-uuid>", type="string"),
    EventVariable("user_name", "Name of the user who owns it", "Jane Smith", type="name"),
]
"""A personal API token's identity, never its value or hash."""

CATALOG: list[CatalogEntry] = [
    # ── Invitations ─────────────────────────────────────────────────────────
    CatalogEntry(
        event_type="invitation_created",
        name="Invitation Created",
        description="A workspace invitation link was created.",
        category="Members",
        sent_by=["Creating an invitation link (Members settings, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("invitation_url", "Invitation link", "https://...", type="url"),
            EventVariable("inviter_name", "Who created the invitation", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="invitation_sent",
        name="Invitation Sent",
        description="A user has been invited to join the workspace.",
        category="Members",
        sent_by=["Emailing an invitation (Members settings, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("invitation_url", "Link for the recipient to accept the invite", "https://...", type="url"),
            EventVariable("inviter_name", "Name of the person who sent the invite", "Jane Smith", type="name"),
            EventVariable("recipient_email", "Email address of the invited user", "user@example.com", type="email"),
        ],
    ),
    CatalogEntry(
        event_type="invitation_accepted",
        name="Invitation Accepted",
        description="A user accepted their workspace invitation.",
        category="Members",
        sent_by=["Signing up with an invitation link"],
        variables=COMMON_VARS
        + [
            EventVariable("username", "Username of the new member", "jsmith", type="username"),
            EventVariable("first_name", "First name of the new member", "Jane", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="invitation_revoked",
        name="Invitation Revoked",
        description="A workspace invitation was revoked.",
        category="Members",
        sent_by=["Revoking an invitation (Members settings, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("inviter_name", "Who revoked the invitation", "Jane Smith", type="name"),
        ],
    ),
    # ── Members ─────────────────────────────────────────────────────────────
    CatalogEntry(
        event_type="member_added",
        name="Member Added",
        description="A new member joined the workspace.",
        category="Members",
        sent_by=["Adding a member (workspace Members settings, admin Workspaces page, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("username", "Username of the new member", "jsmith", type="username"),
            EventVariable("first_name", "First name of the new member", "Jane", type="name"),
            EventVariable("role", "Role assigned to the member", "EDITOR", type="role"),
        ],
    ),
    CatalogEntry(
        event_type="member_role_changed",
        name="Member Role Changed",
        description="A workspace member's role was updated.",
        category="Members",
        sent_by=["Changing a member's role (workspace Members settings, admin Workspaces page, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("username", "Username of the member", "jsmith", type="username"),
            EventVariable("new_role", "New role assigned", "ADMIN", type="role"),
            EventVariable("previous_role", "Previous role", "EDITOR", type="role"),
        ],
    ),
    CatalogEntry(
        event_type="member_removed",
        name="Member Removed",
        description="A member was removed from the workspace.",
        category="Members",
        sent_by=["Removing a member (workspace Members settings, admin Workspaces page, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("username", "Username of the removed member", "jsmith", type="username"),
            EventVariable("role", "Role the member held", "EDITOR", type="role"),
        ],
    ),
    # ── Auth ────────────────────────────────────────────────────────────────
    CatalogEntry(
        event_type="user_signup",
        name="New User Signup",
        description="A new user account was created.",
        category="Authentication",
        sent_by=["Signing up"],
        variables=COMMON_VARS
        + [
            EventVariable("username", "Username of the new user", "jsmith", type="username"),
            EventVariable("first_name", "First name", "Jane", type="name"),
            EventVariable("login_url", "Link to log in", "https://...", type="url"),
        ],
    ),
    CatalogEntry(
        event_type="user_updated",
        name="User Updated",
        description="A user's profile or account details were updated.",
        category="Authentication",
        variables=COMMON_VARS
        + [
            EventVariable("username", "Username of the updated user", "jsmith", type="username"),
        ],
    ),
    CatalogEntry(
        event_type="user_deleted",
        name="User Deleted",
        description="A user account was permanently deleted.",
        category="Authentication",
        variables=COMMON_VARS
        + [
            EventVariable("username", "Username of the deleted account", "jsmith", type="username"),
        ],
    ),
    CatalogEntry(
        event_type="user_password_reset_requested",
        name="Password Reset Requested",
        description="A user requested a password reset.",
        category="Authentication",
        sent_by=["Asking for a password reset link"],
        variables=[
            EventVariable("username", "Username requesting the reset", "jsmith", type="username"),
            EventVariable("reset_url", "Password reset link", "https://...", type="url"),
            EventVariable("expiry_hours", "Hours until the link expires", "24", type="count"),
        ],
    ),
    CatalogEntry(
        event_type="user_password_reset_completed",
        name="Password Reset Completed",
        description="A user successfully reset their password.",
        category="Authentication",
        variables=[
            EventVariable("username", "Username who completed the reset", "jsmith", type="username"),
        ],
    ),
    CatalogEntry(
        event_type="token_refreshed",
        name="Access Token Refreshed",
        description="A signed-in user's access token was renewed.",
        category="Authentication",
        sent_by=["Refreshing a signed-in session's token"],
        variables=COMMON_VARS
        + [
            EventVariable("username", "Username whose token was renewed", "jsmith", type="username"),
        ],
    ),
    # ── Workspaces ───────────────────────────────────────────────────────────
    CatalogEntry(
        event_type="workspace_created",
        name="Workspace Created",
        description="A new workspace was created.",
        category="Workspaces",
        sent_by=["A platform admin creating a workspace"],
        variables=COMMON_VARS
        + [
            EventVariable("creator_name", "Name of the user who created the workspace", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="workspace_updated",
        name="Workspace Updated",
        description="A workspace's name or configuration was updated.",
        category="Workspaces",
        sent_by=["A platform admin editing a workspace"],
        variables=COMMON_VARS
        + [
            EventVariable("workspace_slug", "URL slug of the workspace", "my-blog", type="slug"),
        ],
    ),
    CatalogEntry(
        event_type="workspace_deleted",
        name="Workspace Deleted",
        description="A workspace was permanently deleted.",
        category="Workspaces",
        sent_by=["A platform admin deleting a workspace"],
        variables=COMMON_VARS + [],
    ),
    CatalogEntry(
        event_type="workspace_activated",
        name="Workspace Activated",
        description="A user switched to this workspace.",
        category="Workspaces",
        sent_by=["Switching to a workspace"],
        variables=COMMON_VARS + [],
    ),
    CatalogEntry(
        event_type="workspace_settings_changed",
        name="Workspace Settings Changed",
        description="Workspace preferences or settings were modified.",
        category="Workspaces",
        sent_by=["Saving workspace preferences", "Changing which events the Event Log records"],
        leads_to=["site_rebuild_queued"],
        variables=COMMON_VARS
        + [
            EventVariable("changed_by_name", "Name of the user who changed settings", "Jane Smith", type="name"),
            EventVariable("changed_fields", "Comma-separated list of changed fields", "site_title, site_logo"),
        ],
    ),
    # ── Content: Entries ─────────────────────────────────────────────────────
    CatalogEntry(
        event_type="entry_created",
        name="Entry Created",
        description="A new content entry was created.",
        category="Content",
        trigger_group="Entries",
        triggerable=True,
        emittable=True,
        sent_by=[
            "Creating an entry (app, API, CLI)",
            "Composing an entry with AI (AI operations, assistant, MCP)",
            "A site visitor's form submission, stored as an inbox entry",
            "An integration task storing fetched records as entries",
        ],
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Title of the entry", "Draft Post", type="title"),
            EventVariable("author_name", "Author's display name", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="entry_updated",
        name="Entry Updated",
        description="A content entry was updated.",
        category="Content",
        trigger_group="Entries",
        triggerable=True,
        emittable=True,
        sent_by=[
            "Saving an entry (app, API, CLI)",
            "Every status change (publish, unpublish, archive, restore), wherever it's made",
            "Applying or revising an entry with AI (AI suggestions, revise operations, assistant, MCP)",
            "An integration action failing on an entry (flags it for review)",
        ],
        leads_to=["site_rebuild_queued", "ai_embeddings_reindexed"],
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Title of the entry", "My Post", type="title"),
            EventVariable("author_name", "Who made the update", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="entry_published",
        name="Entry Published",
        description="A content entry was published.",
        category="Content",
        trigger_group="Entries",
        triggerable=True,
        emittable=True,
        sent_by=["Publishing an entry (app, API, CLI)", "The Publish Scheduled Entries task (an entry's publish date)"],
        leads_to=["site_rebuild_queued", "ai_embeddings_reindexed"],
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Title of the published entry", "My Post", type="title"),
            EventVariable("entry_slug", "URL slug of the entry", "my-post", type="slug"),
            EventVariable("author_name", "Author's display name", "Jane Smith", type="name"),
            EventVariable("entry_url", "Public URL of the entry", "https://...", type="url"),
        ],
    ),
    CatalogEntry(
        event_type="entry_unpublished",
        name="Entry Unpublished",
        description="A published entry was taken offline.",
        category="Content",
        trigger_group="Entries",
        triggerable=True,
        emittable=True,
        sent_by=["Unpublishing an entry (app, API, CLI)"],
        leads_to=["site_rebuild_queued"],
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Title of the entry", "My Post", type="title"),
            EventVariable("author_name", "Who unpublished it", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="entry_archived",
        name="Entry Archived",
        description="An entry was archived.",
        category="Content",
        trigger_group="Entries",
        triggerable=True,
        emittable=True,
        sent_by=["Archiving an entry (app, API, CLI)", "The Unpublish Expired Entries task (an entry's expiry date)"],
        leads_to=["site_rebuild_queued"],
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Title of the archived entry", "Old Post", type="title"),
            EventVariable("author_name", "Who archived it", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="entry_restored",
        name="Entry Restored",
        description="An archived entry was restored.",
        category="Content",
        trigger_group="Entries",
        triggerable=True,
        emittable=True,
        sent_by=["Restoring an archived entry (app, API, CLI)"],
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Title of the restored entry", "My Post", type="title"),
            EventVariable("author_name", "Who restored it", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="entry_scheduled_publish_blocked",
        name="Scheduled Publish Waiting",
        # Once per distinct reason (and again after the entry is edited), not on every 5-minute run.
        description="An entry's Scheduled Publish time arrived but it wasn't published: it doesn't meet its type's "
        "requirements (or its expiration date has passed), or the workspace publishes only approved entries on schedule.",
        category="Content",
        trigger_group="Entries",
        triggerable=True,
        emittable=True,
        sent_by=["The Publish Scheduled Entries task, when an entry can't publish yet"],
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Title of the waiting entry", "October newsletter", type="title"),
            EventVariable("waiting_for", "requirements or approval", "requirements"),
            EventVariable("reason", "Why it's waiting, in one line", "Required field 'Subject' is empty."),
            EventVariable("issues", "Each unmet requirement", "[\"Required field 'Subject' is empty.\"]"),
            EventVariable("publish_at", "The Scheduled Publish time that arrived", "2026-07-16T10:00:00Z", type="datetime"),
        ],
    ),
    CatalogEntry(
        event_type="entry_deleted",
        name="Entry Deleted",
        description="A content entry was permanently deleted.",
        category="Content",
        trigger_group="Entries",
        triggerable=True,
        emittable=True,
        sent_by=["Deleting an entry (app, API, CLI)"],
        leads_to=["site_rebuild_queued"],
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Title of the deleted entry", "Old Post", type="title"),
            EventVariable("author_name", "Who deleted it", "Jane Smith", type="name"),
        ],
    ),
    # ── Content: Collections ─────────────────────────────────────────────────
    CatalogEntry(
        event_type="collection_created",
        name="Collection Created",
        description="A new collection was created.",
        category="Content",
        trigger_group="Collections",
        triggerable=True,
        sent_by=["Creating a collection (app, API, CLI)"],
        variables=COMMON_VARS
        + [
            EventVariable("collection_name", "Name of the collection", "Featured Posts", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="collection_updated",
        name="Collection Updated",
        description="A collection was updated.",
        category="Content",
        trigger_group="Collections",
        triggerable=True,
        sent_by=["Editing a collection or reordering its entries (app, API, CLI)"],
        leads_to=["site_rebuild_queued"],
        variables=COMMON_VARS
        + [
            EventVariable("collection_name", "Name of the collection", "Featured Posts", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="collection_deleted",
        name="Collection Deleted",
        description="A collection was permanently deleted.",
        category="Content",
        trigger_group="Collections",
        triggerable=True,
        sent_by=["Deleting a collection (app, API, CLI)"],
        leads_to=["site_rebuild_queued"],
        variables=COMMON_VARS
        + [
            EventVariable("collection_name", "Name of the deleted collection", "Featured Posts", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="entry_added_to_collection",
        name="Entry Added to Collection",
        description="An entry was added to a collection.",
        category="Content",
        trigger_group="Collections",
        triggerable=True,
        emittable=True,
        sent_by=["Adding an entry to a collection (app, API, CLI, AI assistant, MCP)"],
        leads_to=["site_rebuild_queued"],
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Title of the entry", "My Post", type="title"),
            EventVariable("collection_name", "Name of the collection", "Featured Posts", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="entry_removed_from_collection",
        name="Entry Removed from Collection",
        description="An entry was removed from a collection.",
        category="Content",
        trigger_group="Collections",
        triggerable=True,
        emittable=True,
        sent_by=["Removing an entry from a collection (app, API, CLI, AI assistant, MCP)"],
        leads_to=["site_rebuild_queued"],
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Title of the entry", "My Post", type="title"),
            EventVariable("collection_name", "Name of the collection", "Featured Posts", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="entry_resource_attached",
        name="Resource Attached to Entry",
        description="A reusable resource (material, technique, supplier, …) was attached to an entry.",
        category="Content",
        trigger_group="Entries",
        triggerable=True,
        emittable=True,
        sent_by=["Attaching a resource to an entry (AI assistant, MCP)"],
        leads_to=["site_rebuild_queued"],
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Title of the entry", "My Post", type="title"),
            EventVariable("resource_name", "Name of the resource", "Waxed Canvas", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="entry_resource_detached",
        name="Resource Detached from Entry",
        description="A reusable resource was detached from an entry.",
        category="Content",
        trigger_group="Entries",
        triggerable=True,
        emittable=True,
        sent_by=["Detaching a resource from an entry (AI assistant, MCP)"],
        leads_to=["site_rebuild_queued"],
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Title of the entry", "My Post", type="title"),
            EventVariable("resource_name", "Name of the resource", "Waxed Canvas", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="entry_tag_attached",
        name="Tag Attached to Entry",
        description="A tag was attached to an entry.",
        category="Content",
        trigger_group="Entries",
        triggerable=True,
        emittable=True,
        sent_by=["Tagging an entry (AI assistant, MCP)"],
        leads_to=["site_rebuild_queued"],
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Title of the entry", "My Post", type="title"),
            EventVariable("tag_name", "Name of the tag", "waxed", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="entry_tag_detached",
        name="Tag Detached from Entry",
        description="A tag was detached from an entry.",
        category="Content",
        trigger_group="Entries",
        triggerable=True,
        emittable=True,
        sent_by=["Untagging an entry (AI assistant, MCP)"],
        leads_to=["site_rebuild_queued"],
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Title of the entry", "My Post", type="title"),
            EventVariable("tag_name", "Name of the tag", "waxed", type="name"),
        ],
    ),
    # ── Content: Entry Types ──────────────────────────────────────────────────
    CatalogEntry(
        event_type="entry_type_created",
        name="Entry Type Created",
        description="A new content type schema was created.",
        category="Content",
        trigger_group="Entry types",
        triggerable=True,
        emittable=True,
        sent_by=["Creating an entry type (app, API, CLI)"],
        variables=COMMON_VARS
        + [
            EventVariable("entry_type_name", "Name of the entry type", "Blog Post", type="name"),
            EventVariable("entry_type_slug", "Slug of the entry type", "blog-post", type="slug"),
        ],
    ),
    CatalogEntry(
        event_type="entry_type_updated",
        name="Entry Type Updated",
        description="A content type schema was updated.",
        category="Content",
        trigger_group="Entry types",
        triggerable=True,
        emittable=True,
        sent_by=["Editing an entry type (app, API, CLI)"],
        variables=COMMON_VARS
        + [
            EventVariable("entry_type_name", "Name of the entry type", "Blog Post", type="name"),
            EventVariable("entry_type_slug", "Slug of the entry type", "blog-post", type="slug"),
        ],
    ),
    CatalogEntry(
        event_type="entry_type_deleted",
        name="Entry Type Deleted",
        description="A content type schema was permanently deleted.",
        category="Content",
        trigger_group="Entry types",
        triggerable=True,
        emittable=True,
        sent_by=["Deleting an entry type (app, API, CLI)"],
        variables=COMMON_VARS
        + [
            EventVariable("entry_type_name", "Name of the entry type", "Blog Post", type="name"),
            EventVariable("entry_type_slug", "Slug of the entry type", "blog-post", type="slug"),
        ],
    ),
    # ── Content: Resources ────────────────────────────────────────────────────
    CatalogEntry(
        event_type="resource_created",
        name="Resource Created",
        description="A new resource link was added.",
        category="Content",
        trigger_group="Resources",
        triggerable=True,
        sent_by=["Creating a resource (app, API, CLI)"],
        leads_to=["ai_embeddings_reindexed"],
        variables=COMMON_VARS
        + [
            EventVariable("resource_name", "Name of the resource", "API Docs", type="name"),
            EventVariable("resource_url", "URL of the resource", "https://...", type="url"),
        ],
    ),
    CatalogEntry(
        event_type="resource_updated",
        name="Resource Updated",
        description="A resource link was updated.",
        category="Content",
        trigger_group="Resources",
        triggerable=True,
        sent_by=["Editing a resource (app, API, CLI)", "Tagging or untagging a resource (AI assistant, MCP)"],
        leads_to=["site_rebuild_queued", "ai_embeddings_reindexed"],
        variables=COMMON_VARS
        + [
            EventVariable("resource_name", "Name of the resource", "API Docs", type="name"),
            EventVariable("resource_url", "URL of the resource", "https://...", type="url"),
        ],
    ),
    CatalogEntry(
        event_type="resource_deleted",
        name="Resource Deleted",
        description="A resource link was deleted.",
        category="Content",
        trigger_group="Resources",
        triggerable=True,
        sent_by=["Deleting a resource (app, API, CLI)"],
        leads_to=["site_rebuild_queued"],
        variables=COMMON_VARS
        + [
            EventVariable("resource_name", "Name of the deleted resource", "API Docs", type="name"),
        ],
    ),
    # ── Assets ──────────────────────────────────────────────────────────────
    CatalogEntry(
        event_type="asset_uploaded",
        name="Asset Uploaded",
        description="A new file or media asset was uploaded.",
        category="Assets",
        triggerable=True,
        sent_by=["Uploading an asset (app, API, CLI)"],
        leads_to=["ai_embeddings_reindexed"],
        variables=COMMON_VARS
        + [
            EventVariable("asset_name", "Filename of the uploaded asset", "photo.jpg", type="name"),
            EventVariable("asset_type", "MIME type of the asset", "image/jpeg"),
            EventVariable("uploader_name", "Who uploaded it", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="asset_updated",
        name="Asset Updated",
        description="An asset's metadata was updated.",
        category="Assets",
        triggerable=True,
        sent_by=["Editing an asset (app, API, CLI)", "Tagging or untagging an asset (AI assistant, MCP)"],
        leads_to=["site_rebuild_queued", "ai_embeddings_reindexed"],
        variables=COMMON_VARS
        + [
            EventVariable("asset_name", "Filename of the asset", "photo.jpg", type="name"),
            EventVariable("uploader_name", "Who updated it", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="asset_deleted",
        name="Asset Deleted",
        description="An asset was deleted from the workspace.",
        category="Assets",
        triggerable=True,
        sent_by=["Deleting an asset (app, API, CLI)"],
        leads_to=["site_rebuild_queued"],
        variables=COMMON_VARS
        + [
            EventVariable("asset_name", "Filename of the deleted asset", "old-photo.jpg", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="asset_attached_to_entry",
        name="Asset Attached to Entry",
        description="An asset was attached to a content entry.",
        category="Assets",
        trigger_group="Entries",
        triggerable=True,
        sent_by=["Attaching an asset to an entry, or importing images into one (AI assistant, MCP)"],
        leads_to=["site_rebuild_queued"],
        variables=COMMON_VARS
        + [
            EventVariable("asset_name", "Filename of the asset", "photo.jpg", type="name"),
            EventVariable("entry_title", "Title of the entry", "My Post", type="title"),
        ],
    ),
    CatalogEntry(
        event_type="asset_detached_from_entry",
        name="Asset Detached from Entry",
        description="An asset was detached from a content entry.",
        category="Assets",
        trigger_group="Entries",
        triggerable=True,
        sent_by=["Detaching an asset from an entry (AI assistant, MCP)"],
        leads_to=["site_rebuild_queued"],
        variables=COMMON_VARS
        + [
            EventVariable("asset_name", "Filename of the asset", "photo.jpg", type="name"),
            EventVariable("entry_title", "Title of the entry", "My Post", type="title"),
        ],
    ),
    # ── Forms ────────────────────────────────────────────────────────────────
    CatalogEntry(
        event_type="form_submission_received",
        name="Form Submission Received",
        description="Someone submitted a form in the workspace.",
        category="Forms",
        triggerable=True,
        sent_by=["A site visitor submitting a form (a Form, or an entry type that takes submissions)"],
        variables=COMMON_VARS
        + [
            EventVariable("form_name", "Name of the form", "Contact Form", type="name"),
            EventVariable("submitter_email", "Email of the submitter (if provided)", "user@example.com", type="email"),
            EventVariable("duplicate", "True when the submitter was already on file and their entry was updated", "false"),
            EventVariable("existing_entry_id", "The entry the submission matched by the type's match field (if any)", "<entry-uuid>"),
            EventVariable("previous_status", "The matched entry's status before this submission (if any)", "published"),
        ],
    ),
    CatalogEntry(
        event_type="form_created",
        name="Form Created",
        description="A new form was created.",
        category="Forms",
        triggerable=True,
        sent_by=["Creating a form (app, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("form_name", "Name of the form", "Contact Form", type="name"),
            EventVariable("author_name", "Who created the form", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="form_updated",
        name="Form Updated",
        description="A form was updated.",
        category="Forms",
        triggerable=True,
        sent_by=["Editing a form (app, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("form_name", "Name of the form", "Contact Form", type="name"),
            EventVariable("author_name", "Who updated it", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="form_published",
        name="Form Published",
        description="A form was published and is now accepting submissions.",
        category="Forms",
        triggerable=True,
        sent_by=["Publishing a form (app, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("form_name", "Name of the form", "Contact Form", type="name"),
            EventVariable("author_name", "Who published it", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="form_archived",
        name="Form Archived",
        description="A form was archived and is no longer accepting submissions.",
        category="Forms",
        triggerable=True,
        sent_by=["Archiving a form (app, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("form_name", "Name of the form", "Contact Form", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="form_deleted",
        name="Form Deleted",
        description="A form was permanently deleted.",
        category="Forms",
        triggerable=True,
        sent_by=["Deleting a form (app, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("form_name", "Name of the deleted form", "Contact Form", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="submission_surge_detected",
        name="Submission Surge Detected",
        description="One form received an unusual burst of submissions within the configured window.",
        category="Forms",
        triggerable=True,
        sent_by=["Form submissions crossing the surge threshold (checked on each submission)"],
        variables=COMMON_VARS
        + [
            EventVariable("form_name", "Name of the form", "Newsletter", type="name"),
            EventVariable("submission_count", "Submissions seen in the window", "50"),
            EventVariable("threshold", "Configured surge threshold", "50"),
            EventVariable("window_minutes", "Window length in minutes", "10"),
        ],
    ),
    CatalogEntry(
        event_type="form_submission_processed",
        name="Form Submission Processed",
        description="A form submission was successfully processed.",
        category="Forms",
        variables=COMMON_VARS
        + [
            EventVariable("form_name", "Name of the form", "Contact Form", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="form_submission_failed",
        name="Form Submission Failed",
        description="A form submission failed to process.",
        category="Forms",
        variables=COMMON_VARS
        + [
            EventVariable("form_name", "Name of the form", "Contact Form", type="name"),
            EventVariable("error_message", "What went wrong", "Validation error", type="error"),
        ],
    ),
    # ── Publishing ───────────────────────────────────────────────────────────
    CatalogEntry(
        event_type="site_published",
        name="Site Published",
        description="A site publish was triggered.",
        category="Publishing",
        variables=COMMON_VARS
        + [
            EventVariable("site_url", "URL of the site", "https://mysite.com", type="url"),
        ],
    ),
    CatalogEntry(
        event_type="site_rebuild_queued",
        name="Site Rebuild Queued",
        # One per batch: later requests join it silently, and `webhook_triggered` sends it.
        description="A change queued a site rebuild; more changes join it until requests go quiet, then it is sent.",
        category="Publishing",
        sent_by=[
            "Queuing a site rebuild, once per pending rebuild: a content change a site can see",
            "The Rebuild site button (app, API)",
            "The Request Site Rebuild scheduled task",
        ],
        leads_to=["webhook_triggered"],
        variables=COMMON_VARS
        + [
            EventVariable("reason", "Why the first request asked for a rebuild", "content change: Entry 'Summer menu' published"),
            EventVariable("change", "The first change it covers (label, event, entity)", "{...}"),
            EventVariable("quiet_seconds", "Sent once requests have been quiet this long", "60", type="number"),
            EventVariable("max_wait_seconds", "...or at the latest this long after the first request", "600", type="number"),
            EventVariable("queued_at", "When the first request arrived", "2026-07-16T10:00:00Z", type="datetime"),
            EventVariable("expected_send_at", "When it is sent if nothing else joins it", "2026-07-16T10:01:00Z", type="datetime"),
        ],
    ),
    CatalogEntry(
        # Internal name kept: deploy-hook webhooks and integration actions subscribe to webhook_triggered.
        event_type="webhook_triggered",
        name="Site Rebuild Sent",
        description=(
            "A queued site rebuild was sent once its requests went quiet. This is the signal deploy hooks listen to: "
            "connect your host's deploy hook (an outgoing webhook, or an integration action such as Cloudflare Pages → "
            "Deploy) here and it rebuilds the site, with the changes the rebuild covers."
        ),
        category="Publishing",
        sent_by=["Sending a queued site rebuild once its requests go quiet (scheduler)"],
        variables=COMMON_VARS
        + [
            EventVariable("request_count", "Rebuild requests this build covers", "3", type="number"),
            EventVariable("changes", "The changes it covers (label, event, entity), newest last", "[...]"),
        ],
    ),
    CatalogEntry(
        event_type="site_deployment_started",
        name="Site Deployment Started",
        description="A site build or deployment has begun (the host reported it).",
        category="Publishing",
        trigger_group="Site",
        triggerable=True,
        emittable=True,
        sent_by=["A workflow's Emit event step (e.g. from a host's deploy notification)"],
        variables=COMMON_VARS
        + [
            EventVariable("site_url", "URL of the site being deployed", "https://mysite.com", type="url"),
        ],
    ),
    CatalogEntry(
        event_type="site_deployment_completed",
        name="Site Deployment Completed",
        description="A site build or deployment finished successfully (the host reported it).",
        category="Publishing",
        trigger_group="Site",
        triggerable=True,
        emittable=True,
        sent_by=["A workflow's Emit event step (e.g. from a host's deploy notification)"],
        variables=COMMON_VARS
        + [
            EventVariable("site_url", "URL of the deployed site", "https://mysite.com", type="url"),
            EventVariable("duration", "How long the deployment took", "45s", type="duration"),
        ],
    ),
    CatalogEntry(
        event_type="site_deployment_failed",
        name="Site Deployment Failed",
        description="A site build or deployment failed (the host reported it).",
        category="Publishing",
        trigger_group="Site",
        triggerable=True,
        emittable=True,
        sent_by=["A workflow's Emit event step (e.g. from a host's deploy notification)"],
        variables=COMMON_VARS
        + [
            EventVariable("error_message", "What went wrong", "Build timeout", type="error"),
        ],
    ),
    CatalogEntry(
        event_type="site_build_started",
        name="Site Build Started (old name)",
        description="Old name for Site Deployment Started: workflows and the Emit event step that name it get site_deployment_started.",
        category="Publishing",
        alias_of="site_deployment_started",
        variables=COMMON_VARS
        + [
            EventVariable("site_url", "URL of the site being built", "https://mysite.com", type="url"),
        ],
    ),
    CatalogEntry(
        event_type="site_build_completed",
        name="Site Build Completed (old name)",
        description="Old name for Site Deployment Completed: workflows and the Emit event step that name it get site_deployment_completed.",
        category="Publishing",
        alias_of="site_deployment_completed",
        variables=COMMON_VARS
        + [
            EventVariable("site_url", "URL of the deployed site", "https://mysite.com", type="url"),
            EventVariable("duration", "How long the build took", "45s", type="duration"),
        ],
    ),
    CatalogEntry(
        event_type="site_build_failed",
        name="Site Build Failed (old name)",
        description="Old name for Site Deployment Failed: workflows and the Emit event step that name it get site_deployment_failed.",
        category="Publishing",
        alias_of="site_deployment_failed",
        variables=COMMON_VARS
        + [
            EventVariable("error_message", "What went wrong", "Compilation error", type="error"),
        ],
    ),
    # ── Connect: Integrations ─────────────────────────────────────────────────
    # Not workflow triggers (automation/triggers.py): a workflow reacting to a connection alert could
    # call the failing connection again. Route them from Settings → Integrations → Integration alerts.
    CatalogEntry(
        event_type="integration_attention_needed",
        name="Integration Needs Attention",
        description="An integration failed in a way its provider says admins should know about (expired credentials, "
        "a misconfigured account, …). Sent once when the alert opens and again after each reminder window — "
        "never once per affected item.",
        category="Connect",
        sent_by=["An integration failing (Alerts & health)"],
        variables=COMMON_VARS
        + [
            EventVariable("integration_name", "The connection's name", "Shop", type="name"),
            EventVariable("integration_slug", "The connection's slug", "shop"),
            EventVariable("provider_name", "The provider's name", "Square", type="name"),
            EventVariable("code", "The provider's error code", "auth"),
            EventVariable("error", "The latest failure's message", "The access token expired"),
            EventVariable("count", "Failures since the alert opened", "3", type="number"),
            EventVariable("reminder", "True when the alert was already open (a reminder)", "false"),
            EventVariable("title", "Short heading", "Square needs attention"),
            EventVariable("summary", "One line with the detail, for chat channels", "Square (shop) needs attention: auth — ..."),
        ],
    ),
    CatalogEntry(
        event_type="integration_attention_resolved",
        name="Integration Working Again",
        description="A connection that needed attention is working again — a passing health check, a successful action, "
        "or an admin's Resolve. Also delivered to every channel that delivered the alert.",
        category="Connect",
        sent_by=["An integration working again: a passing health check, a successful action, or an admin"],
        variables=COMMON_VARS
        + [
            EventVariable("integration_name", "The connection's name", "Shop", type="name"),
            EventVariable("provider_name", "The provider's name", "Square", type="name"),
            EventVariable("code", "The error code that was resolved", "auth"),
            EventVariable("resolution", "How it resolved (check, action, manual)", "check"),
            EventVariable("title", "Short heading", "Square is working again"),
            EventVariable("summary", "One line with the detail, for chat channels", "Square (shop) is working again"),
        ],
    ),
    # ── Connect: Webhooks ─────────────────────────────────────────────────────
    CatalogEntry(
        event_type="incoming_webhook",
        name="Incoming Webhook Received",
        description="An external system POSTed to a tokened incoming-webhook URL. Automations can "
        "react to this and read the request body via $event.payload.",
        category="Connect",
        sent_by=["A call to one of the workspace's incoming webhook URLs"],
        variables=COMMON_VARS
        + [
            EventVariable("webhook_slug", "Slug of the incoming webhook that fired", "stripe-payments", type="string"),
            EventVariable("webhook_name", "Name of the incoming webhook", "Stripe Payments", type="name"),
            EventVariable("source_ip", "IP address the request came from", "203.0.113.7", type="string"),
        ],
    ),
    CatalogEntry(
        event_type="webhook_created",
        name="Webhook Created",
        description="An outgoing webhook was added.",
        category="Connect",
        sent_by=["Adding an outgoing webhook (app, API)"],
        variables=COMMON_VARS + _WEBHOOK_VARS + [EventVariable("changed_by_name", "Who added it", "Jane Smith", type="name")],
    ),
    CatalogEntry(
        event_type="webhook_updated",
        name="Webhook Updated",
        description="An outgoing webhook's settings were changed.",
        category="Connect",
        sent_by=["Saving an outgoing webhook (app, API)"],
        variables=COMMON_VARS + _WEBHOOK_VARS + [EventVariable("changed_by_name", "Who changed it", "Jane Smith", type="name")],
    ),
    CatalogEntry(
        event_type="webhook_deleted",
        name="Webhook Deleted",
        description="An outgoing webhook was deleted.",
        category="Connect",
        sent_by=["Deleting an outgoing webhook (app, API)"],
        variables=COMMON_VARS + _WEBHOOK_VARS + [EventVariable("changed_by_name", "Who deleted it", "Jane Smith", type="name")],
    ),
    CatalogEntry(
        # Hidden (_NO_EMITTER): one per delivery is noise, and the webhook's activity log already records each one.
        event_type="webhook_delivery_succeeded",
        name="Webhook Delivery Succeeded",
        description="A webhook was delivered successfully.",
        category="Connect",
        variables=COMMON_VARS
        + [
            EventVariable("webhook_name", "Name of the webhook", "Deploy hook", type="name"),
            EventVariable("status_code", "HTTP response code received", "200", type="count"),
        ],
    ),
    CatalogEntry(
        event_type="webhook_delivery_failed",
        name="Webhook Delivery Failed",
        description="An outgoing webhook couldn't deliver an event, even after its retries.",
        category="Connect",
        sent_by=["An outgoing webhook delivery failing after its retries (event, scheduled and test sends)"],
        variables=COMMON_VARS
        + [
            EventVariable("webhook_id", "ID of the webhook", "<webhook-uuid>", type="string"),
            EventVariable("webhook_name", "Name of the webhook", "Deploy hook", type="name"),
            EventVariable("delivered_event_type", "The event it was delivering", "webhook_triggered", type="string"),
            EventVariable("status_code", "HTTP status of the last attempt (if the host answered)", "503", type="count"),
            EventVariable("error_message", "What went wrong", "HTTP 503", type="error"),
            EventVariable("attempts", "How many attempts were made", "3", type="count"),
        ],
    ),
    # ── Connect: API Clients ──────────────────────────────────────────────────
    CatalogEntry(
        event_type="api_client_created",
        name="API Client Created",
        description="A new API client was registered.",
        category="Connect",
        sent_by=["Creating an API client (app, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("client_name", "Name of the API client", "My Site Client", type="name"),
            EventVariable("client_slug", "Slug of the API client", "my-site-client", type="slug"),
            EventVariable("created_by", "Who created the client", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="api_client_updated",
        name="API Client Updated",
        description="An API client's configuration was updated.",
        category="Connect",
        sent_by=["Editing an API client (app, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("client_name", "Name of the API client", "My Site Client", type="name"),
            EventVariable("client_slug", "Slug of the API client", "my-site-client", type="slug"),
        ],
    ),
    CatalogEntry(
        event_type="api_client_deleted",
        name="API Client Deleted",
        description="An API client was deleted.",
        category="Connect",
        sent_by=["Deleting an API client (app, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("client_name", "Name of the deleted API client", "My Site Client", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="api_client_enabled",
        name="API Client Enabled",
        description="An API client was enabled.",
        category="Connect",
        sent_by=["Turning an API client on (app, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("client_name", "Name of the API client", "My Site Client", type="name"),
            EventVariable("client_slug", "Slug of the API client", "my-site-client", type="slug"),
        ],
    ),
    CatalogEntry(
        event_type="api_client_disabled",
        name="API Client Disabled",
        description="An API client was disabled.",
        category="Connect",
        sent_by=["Turning an API client off (app, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("client_name", "Name of the API client", "My Site Client", type="name"),
            EventVariable("client_slug", "Slug of the API client", "my-site-client", type="slug"),
        ],
    ),
    CatalogEntry(
        event_type="api_client_token_rotated",
        name="API Client Token Rotated",
        description="An API client's token was rotated (old token invalidated, new one issued).",
        category="Connect",
        sent_by=["Rotating an API client's token (app, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("client_name", "Name of the API client", "My Site Client", type="name"),
        ],
    ),
    # ── Connect: Email templates ──────────────────────────────────────────────
    # Not subscribable and always audited, as they were before they had an entry (an uncatalogued type is
    # always audited): the record of who changed what an automated email says.
    CatalogEntry(
        event_type="email_template_created",
        name="Email Template Created",
        description="A workspace email template, or a platform admin's system template, was created.",
        category="Connect",
        sent_by=["Creating an email template (workspace Email settings, API)", "A platform admin creating a system email template"],
        enabled=False,
        audit_locked=True,
        variables=COMMON_VARS
        + [
            EventVariable("template_id", "The template's id", "<template-uuid>"),
            EventVariable("template_type", "What the template is for", "invitation"),
            EventVariable("system_template", "A platform-wide system template (not the workspace's own)", "false"),
        ],
    ),
    CatalogEntry(
        event_type="email_template_updated",
        name="Email Template Updated",
        description="A workspace email template, or a platform admin's system template, was updated.",
        category="Connect",
        sent_by=["Editing an email template (workspace Email settings, API)", "A platform admin editing a system email template"],
        enabled=False,
        audit_locked=True,
        variables=COMMON_VARS
        + [
            EventVariable("template_id", "The template's id", "<template-uuid>"),
            EventVariable("template_type", "What the template is for", "invitation"),
            EventVariable("system_template", "A platform-wide system template (not the workspace's own)", "false"),
        ],
    ),
    CatalogEntry(
        event_type="email_template_deleted",
        name="Email Template Deleted",
        description="A workspace email template, or a platform admin's system template, was deleted.",
        category="Connect",
        sent_by=["Deleting an email template (workspace Email settings, API)", "A platform admin deleting a system email template"],
        enabled=False,
        audit_locked=True,
        variables=COMMON_VARS
        + [
            EventVariable("template_id", "The template's id", "<template-uuid>"),
            EventVariable("template_type", "What the template is for", "invitation"),
            EventVariable("system_template", "A platform-wide system template (not the workspace's own)", "false"),
        ],
    ),
    # ── Security ─────────────────────────────────────────────────────────────
    CatalogEntry(
        event_type="api_token_created",
        name="API Token Created",
        description="A personal API token was created.",
        category="Security",
        sent_by=["Creating a personal API token (profile, API)"],
        variables=COMMON_VARS + _API_TOKEN_VARS,
    ),
    CatalogEntry(
        event_type="api_token_rotated",
        name="API Token Rotated",
        description="A personal API token was rotated (old token invalidated, new one issued).",
        category="Security",
        sent_by=["Rotating a personal API token (profile, API)"],
        variables=COMMON_VARS + _API_TOKEN_VARS,
    ),
    CatalogEntry(
        event_type="api_token_revoked",
        name="API Token Revoked",
        description="A personal API token was revoked or deleted, so it no longer works.",
        category="Security",
        sent_by=["Revoking or deleting a personal API token (profile, API)"],
        variables=COMMON_VARS + _API_TOKEN_VARS,
    ),
    CatalogEntry(
        event_type="api_rate_limit_exceeded",
        name="API Rate Limit Exceeded",
        description="An API rate limit was exceeded.",
        category="Security",
        variables=COMMON_VARS
        + [
            EventVariable("client_name", "Name of the API client", "My Site Client", type="name"),
            EventVariable("limit", "Rate limit that was exceeded", "1000", type="count"),
        ],
    ),
    CatalogEntry(
        event_type="login_failed_multiple_times",
        name="Repeated Login Failures",
        description="Multiple failed login attempts detected for an account.",
        category="Security",
        variables=COMMON_VARS
        + [
            EventVariable("username", "Account targeted", "jsmith", type="username"),
            EventVariable("attempt_count", "Number of failures", "5", type="count"),
        ],
    ),
    CatalogEntry(
        event_type="suspicious_activity_detected",
        name="Suspicious Activity Detected",
        description="Suspicious activity was detected on an account or in the workspace.",
        category="Security",
        variables=COMMON_VARS
        + [
            EventVariable("username", "Account involved", "jsmith", type="username"),
            EventVariable("activity_description", "What was detected", "Multiple failed logins from new IP"),
        ],
    ),
    # ── Automation: Scheduled Tasks ───────────────────────────────────────────
    CatalogEntry(
        event_type="scheduled_task_created",
        name="Scheduled Task Created",
        description="A new scheduled task was created.",
        category="Automation",
        sent_by=["Creating a scheduled task (app, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("task_name", "Name of the task", "Daily Cleanup", type="name"),
            EventVariable("task_type", "Type of task", "publish"),
        ],
    ),
    CatalogEntry(
        event_type="scheduled_task_updated",
        name="Scheduled Task Updated",
        description="A scheduled task's configuration was updated.",
        category="Automation",
        sent_by=["Editing a scheduled task (app, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("task_name", "Name of the task", "Daily Cleanup", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="scheduled_task_deleted",
        name="Scheduled Task Deleted",
        description="A scheduled task was deleted.",
        category="Automation",
        sent_by=["Deleting a scheduled task (app, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("task_name", "Name of the deleted task", "Daily Cleanup", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="automation_started",
        name="Workflow Started",
        # Not triggerable: reacting to a run starting would loop.
        description="A workflow run began; the run's automation_ran / automation_failed event carries the same execution id.",
        category="Automation",
        sent_by=["A workflow starting a run"],
        variables=COMMON_VARS
        + [
            EventVariable("automation_name", "The workflow's name", "Tag new recipes", type="name"),
            EventVariable("automation_slug", "The workflow's slug", "tag-new-recipes"),
            EventVariable("execution_id", "The run's id, shared with the event that ends it", "<execution-uuid>"),
            EventVariable("trigger", "What started it (manual, schedule, chat, event, incoming_webhook, chained, on_error)", "manual"),
            EventVariable("target_count", "For a target-query run, how many entries it acts on", "12", type="number"),
        ],
    ),
    CatalogEntry(
        event_type="automation_ran",
        name="Workflow Ran",
        # Not an "event" trigger: it drives the chained / on_error trigger types. Not subscribable and always
        # audited, as before it had an entry.
        description="A workflow run finished; what each step did is in its steps.",
        category="Automation",
        sent_by=["A workflow run finishing"],
        enabled=False,
        audit_locked=True,
        variables=COMMON_VARS
        + [
            EventVariable("automation_name", "The workflow's name", "Tag new recipes", type="name"),
            EventVariable("automation_slug", "The workflow's slug", "tag-new-recipes"),
            EventVariable("execution_id", "The run's id, shared with its automation_started event", "<execution-uuid>"),
            EventVariable("error", "Why it failed (failed runs)", "", type="error"),
        ],
    ),
    CatalogEntry(
        event_type="automation_failed",
        name="Workflow Failed",
        # Not an "event" trigger: it drives the chained / on_error trigger types. Not subscribable and always
        # audited, as before it had an entry.
        description="A workflow run failed; its error names the step that failed.",
        category="Automation",
        sent_by=["A workflow run failing"],
        enabled=False,
        audit_locked=True,
        variables=COMMON_VARS
        + [
            EventVariable("automation_name", "The workflow's name", "Tag new recipes", type="name"),
            EventVariable("automation_slug", "The workflow's slug", "tag-new-recipes"),
            EventVariable("execution_id", "The run's id, shared with its automation_started event", "<execution-uuid>"),
            EventVariable("error", "Why it failed (failed runs)", "", type="error"),
        ],
    ),
    CatalogEntry(
        event_type="webhook_task",
        name="Webhook Task (internal)",
        description="Internal scheduler tick that dispatches due webhooks. Not subscribable; "
        "delivery outcomes are recorded in webhook_execution_logs.",
        category="Automation",
        internal=True,
        sent_by=["The scheduler's webhook tick", "Re-running today's scheduled webhooks or testing one (app, API)"],
        enabled=False,  # internal plumbing — not offered for subscription
        audited=False,  # high-frequency noise — kept out of the audit log
    ),
    CatalogEntry(
        event_type="scheduled_task_triggered",
        name="Scheduled Task Triggered",
        description="A scheduled task was manually triggered.",
        category="Automation",
        internal=True,
        sent_by=["The scheduler, when a task is due", "Run now (workspace or admin Scheduled Tasks)"],
        leads_to=["scheduled_task_started", "scheduled_task_completed", "scheduled_task_failed"],
        audited=False,  # internal trigger — outcome captured by started/completed/failed
        variables=COMMON_VARS
        + [
            EventVariable("task_name", "Name of the task", "Daily Cleanup", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="scheduled_task_started",
        name="Scheduled Task Started",
        description="A scheduled task has begun execution.",
        category="Automation",
        internal=True,
        sent_by=["Running a scheduled task"],
        audited=False,  # start marker — completed/failed carry the audit value
        variables=COMMON_VARS
        + [
            EventVariable("task_name", "Name of the task", "Daily Cleanup", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="scheduled_task_completed",
        name="Scheduled Task Completed",
        description="A scheduled task ran successfully and had something to report, or was run by hand. Routine runs with nothing to do are not announced.",
        category="Automation",
        internal=True,
        sent_by=["Running a scheduled task, when it succeeds"],
        variables=COMMON_VARS
        + [
            EventVariable("task_name", "Name of the task", "Daily Cleanup", type="name"),
            EventVariable("duration_ms", "How long it took (ms)", "1234", type="duration"),
        ],
    ),
    CatalogEntry(
        event_type="scheduled_task_failed",
        name="Scheduled Task Failed",
        description="A scheduled task failed to execute.",
        category="Automation",
        internal=True,
        sent_by=["Running a scheduled task, when it fails"],
        variables=COMMON_VARS
        + [
            EventVariable("task_name", "Name of the failed task", "Daily Cleanup", type="name"),
            EventVariable("error_message", "What went wrong", "Connection timeout", type="error"),
        ],
    ),
    CatalogEntry(
        event_type="scheduled_task_cancelled",
        name="Scheduled Task Cancelled",
        description="A scheduled task execution was cancelled.",
        category="Automation",
        variables=COMMON_VARS
        + [
            EventVariable("task_name", "Name of the task", "Daily Cleanup", type="name"),
        ],
    ),
    # ── Collaboration ────────────────────────────────────────────────────────
    CatalogEntry(
        event_type="comment_added",
        name="Comment Added",
        description="A comment was added to an entry.",
        category="Collaboration",
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Entry that was commented on", "My Post", type="title"),
            EventVariable("commenter_name", "Who left the comment", "Jane Smith", type="name"),
            EventVariable("comment_excerpt", "First part of the comment", "Great post!"),
        ],
    ),
    CatalogEntry(
        event_type="comment_updated",
        name="Comment Updated",
        description="A comment on an entry was edited.",
        category="Collaboration",
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Entry that was commented on", "My Post", type="title"),
            EventVariable("commenter_name", "Who left the comment", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="comment_deleted",
        name="Comment Deleted",
        description="A comment on an entry was deleted.",
        category="Collaboration",
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Entry the comment was on", "My Post", type="title"),
            EventVariable("commenter_name", "Who left the original comment", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="mention_created",
        name="Mention",
        description="A user was mentioned in content.",
        category="Collaboration",
        variables=COMMON_VARS
        + [
            EventVariable("mentioned_user", "Username who was mentioned", "jsmith", type="username"),
            EventVariable("mentioned_by", "Who made the mention", "Jane Smith", type="name"),
            EventVariable("entry_title", "Where the mention occurred", "My Post", type="title"),
        ],
    ),
    CatalogEntry(
        event_type="entry_shared",
        name="Entry Shared",
        description="An entry was shared with another user.",
        category="Collaboration",
        emittable=True,
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Title of the shared entry", "My Post", type="title"),
            EventVariable("shared_by", "Who shared the entry", "Jane Smith", type="name"),
            EventVariable("shared_with", "Who it was shared with", "jsmith", type="username"),
        ],
    ),
    # ── AI: ask-first approvals ──────────────────────────────────────────────
    CatalogEntry(
        event_type="approval_requested",
        name="Agent Approval Requested",
        description=(
            'An agent run paused for the user\'s decision: a tool marked "ask first" is waiting — its own, or one a specialist it '
            "handed off to asked for (via_agent)."
        ),
        category="AI",
        sent_by=["An AI run pausing to ask before a tool call"],
        variables=COMMON_VARS
        + [
            EventVariable("agent_slug", "The agent whose run is waiting", "marvin"),
            EventVariable("thread_id", "The Ask thread the run is parked on", "b7c1…", type="string"),
            EventVariable("execution_id", "The AI execution row of the run", "9f2e…", type="string"),
            EventVariable("calls", "The tool calls waiting: [{id, tool, arguments}]", "[]", type="string"),
            EventVariable("decisions", "Empty on a request", "", type="string"),
            EventVariable("via_agent", "When every call belongs to one specialist Marvin handed off to: its slug", "workshop"),
            EventVariable("child_thread_id", "That specialist's thread", "c4d2…", type="string"),
            EventVariable("child_execution_id", "That specialist's AI execution row", "1a7b…", type="string"),
        ],
    ),
    CatalogEntry(
        event_type="approval_granted",
        name="Agent Approval Granted",
        description="The user approved at least one of the tool calls a paused agent run was waiting on; the run resumed.",
        category="AI",
        sent_by=["Approving a paused AI tool call"],
        variables=COMMON_VARS
        + [
            EventVariable("agent_slug", "The agent whose run resumed", "marvin"),
            EventVariable("thread_id", "The Ask thread the run was parked on", "b7c1…", type="string"),
            EventVariable("execution_id", "The AI execution row of the run", "9f2e…", type="string"),
            EventVariable("calls", "The approved tool calls: [{id, tool, arguments, via?}]", "[]", type="string"),
            EventVariable("decisions", "Per call id: approve | deny", "{}", type="string"),
            EventVariable("via_agent", "When every call belongs to one specialist Marvin handed off to: its slug", "workshop"),
            EventVariable("child_thread_id", "That specialist's thread", "c4d2…", type="string"),
            EventVariable("child_execution_id", "That specialist's AI execution row", "1a7b…", type="string"),
            EventVariable("decided_by", "The user who decided (empty when the system ended it)", "5e0a…", type="string"),
            EventVariable("surface", "Where it was decided: ask_page | bubble", "ask_page"),
        ],
    ),
    CatalogEntry(
        event_type="approval_rejected",
        name="Agent Approval Rejected",
        description=(
            "The user denied at least one of the tool calls a paused agent run was waiting on (a new message denies them all; "
            "a request not decided in time expires)."
        ),
        category="AI",
        sent_by=[
            "Denying a paused AI tool call",
            "Sending a new message instead of answering (the paused call is abandoned)",
            "Expiring runs left waiting too long (hourly)",
        ],
        variables=COMMON_VARS
        + [
            EventVariable("agent_slug", "The agent whose run was waiting", "marvin"),
            EventVariable("thread_id", "The Ask thread the run was parked on", "b7c1…", type="string"),
            EventVariable("execution_id", "The AI execution row of the run", "9f2e…", type="string"),
            EventVariable("calls", "The denied tool calls: [{id, tool, arguments, via?}]", "[]", type="string"),
            EventVariable("decisions", "Per call id: approve | deny", "{}", type="string"),
            EventVariable("via_agent", "When every call belongs to one specialist Marvin handed off to: its slug", "workshop"),
            EventVariable("child_thread_id", "That specialist's thread", "c4d2…", type="string"),
            EventVariable("child_execution_id", "That specialist's AI execution row", "1a7b…", type="string"),
            EventVariable("decided_by", "The user who decided (empty when the system ended it)", "5e0a…", type="string"),
            EventVariable("surface", "Where it was decided: ask_page | bubble", "ask_page"),
            EventVariable("reason", "Set when no user decided: abandoned | expired | no_longer_permitted", "expired"),
        ],
    ),
    # ── System: Storage ───────────────────────────────────────────────────────
    CatalogEntry(
        event_type="storage_quota_warning",
        name="Storage Quota Warning",
        description="Storage usage is approaching the limit.",
        category="System",
        variables=COMMON_VARS
        + [
            EventVariable("usage_percent", "Percentage of quota used", "85", type="percent"),
            EventVariable("used_gb", "GB currently used", "8.5", type="size"),
            EventVariable("quota_gb", "Total quota in GB", "10", type="size"),
        ],
    ),
    CatalogEntry(
        event_type="storage_quota_exceeded",
        name="Storage Quota Exceeded",
        description="Storage quota has been exceeded.",
        category="System",
        variables=COMMON_VARS
        + [
            EventVariable("usage_percent", "Percentage of quota used", "103", type="percent"),
            EventVariable("used_gb", "GB currently used", "10.3", type="size"),
            EventVariable("quota_gb", "Total quota in GB", "10", type="size"),
        ],
    ),
    # ── System: Backups ───────────────────────────────────────────────────────
    CatalogEntry(
        event_type="backup_started",
        name="Backup Started",
        description="A database backup has started.",
        category="System",
        variables=COMMON_VARS + [],
    ),
    CatalogEntry(
        event_type="backup_completed",
        name="Backup Completed",
        description="A database backup finished successfully.",
        category="System",
        variables=COMMON_VARS
        + [
            EventVariable("backup_size", "Size of the backup", "45MB", type="size"),
            EventVariable("duration", "How long it took", "12s", type="duration"),
        ],
    ),
    CatalogEntry(
        event_type="backup_failed",
        name="Backup Failed",
        description="A database backup failed.",
        category="System",
        variables=COMMON_VARS
        + [
            EventVariable("error_message", "What went wrong", "Disk full", type="error"),
        ],
    ),
    # ── AI ──────────────────────────────────────────────────────────────────
    CatalogEntry(
        event_type="ai_operation_executed",
        name="AI Operation Executed",
        description="An AI operation completed successfully.",
        category="AI",
        sent_by=["Running an AI operation (app, API, CLI, MCP)", "An integration capability's AI call"],
        variables=COMMON_VARS
        + [
            EventVariable("operation_slug", "The operation that ran", "generate-summary"),
            EventVariable("model_id", "Model used", "gpt-4o-mini"),
            EventVariable("total_tokens", "Total tokens used", "1223", type="number"),
            EventVariable("estimated_cost_usd", "Estimated cost (USD)", "0.0002", type="number"),
        ],
    ),
    CatalogEntry(
        event_type="ai_operation_failed",
        name="AI Operation Failed",
        description="An AI operation failed to complete.",
        category="AI",
        sent_by=["Running an AI operation (app, API, CLI, MCP), when it fails", "An integration capability's AI call, when it fails"],
        variables=COMMON_VARS
        + [
            EventVariable("operation_slug", "The operation that ran", "generate-summary"),
            EventVariable("model_id", "Model attempted", "gpt-4o-mini"),
            EventVariable("error_message", "What went wrong", "insufficient_quota", type="error"),
        ],
    ),
    CatalogEntry(
        event_type="ai_embeddings_reindexed",
        name="AI Embeddings Reindexed",
        description="Workspace embeddings were (re)indexed for semantic search / RAG.",
        category="AI",
        sent_by=[
            "Reindexing the workspace for AI search (AI settings, API)",
            "Refreshing AI search after a content change (built-in)",
            "The Reindex Embeddings scheduled task",
        ],
        variables=COMMON_VARS
        + [
            EventVariable("model_id", "Embedding model", "text-embedding-3-small"),
            EventVariable("entities_indexed", "Entities embedded", "70", type="number"),
            EventVariable("chunks_indexed", "Chunks embedded", "70", type="number"),
        ],
    ),
    CatalogEntry(
        event_type="ai_budget_threshold_reached",
        name="AI Budget Threshold Reached",
        description="Workspace AI spend crossed a budget warning threshold (~80% of the monthly cost limit).",
        category="AI",
        sent_by=["An AI call crossing the workspace's monthly budget warning (AI operations, workflow steps, persona lines)"],
        variables=COMMON_VARS
        + [
            EventVariable("current_value", "Current monthly spend (USD)", "40.00", type="number"),
            EventVariable("limit_value", "Monthly cost limit (USD)", "50.00", type="number"),
            EventVariable("percent", "Percent of limit reached", "80", type="number"),
        ],
    ),
    CatalogEntry(
        event_type="ai_budget_exceeded",
        name="AI Budget Exceeded",
        description="The workspace monthly AI cost limit was reached.",
        category="AI",
        sent_by=["An AI call going over the workspace's monthly budget (AI operations, workflow steps, persona lines)"],
        variables=COMMON_VARS
        + [
            EventVariable("current_value", "Current monthly spend (USD)", "50.00", type="number"),
            EventVariable("limit_value", "Monthly cost limit (USD)", "50.00", type="number"),
        ],
    ),
    CatalogEntry(
        event_type="ai_provider_quota_exceeded",
        name="AI Provider Quota Exceeded",
        description="The AI provider rejected a call for lack of quota/credits (no tokens available).",
        category="AI",
        sent_by=["An AI provider refusing a call for lack of quota or credits"],
        variables=COMMON_VARS
        + [
            EventVariable("provider_type", "Provider", "openai"),
            EventVariable("operation_slug", "Operation attempted", "generate-summary"),
            EventVariable("detail", "Provider error detail", "insufficient_quota", type="error"),
        ],
    ),
    # ── Secrets ─────────────────────────────────────────────────────────────
    # Payloads carry the slug/name only — never the secret value (a leak vector; see event_types.py).
    CatalogEntry(
        event_type="secret_created",
        name="Secret Created",
        description="A workspace secret was created.",
        category="Secrets",
        sent_by=["Creating a secret (Secrets settings, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("slug", "The secret's reference slug", "OPENAI_API_KEY", type="string"),
            EventVariable("name", "The secret's label", "OpenAI Key", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="secret_updated",
        name="Secret Updated",
        description="A workspace secret's name, description, or value changed. The value is never included.",
        category="Secrets",
        sent_by=["Editing a secret (Secrets settings, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("slug", "The secret's reference slug", "OPENAI_API_KEY", type="string"),
            EventVariable("name", "The secret's label", "OpenAI Key", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="secret_deleted",
        name="Secret Deleted",
        description="A workspace secret was deleted.",
        category="Secrets",
        sent_by=["Deleting a secret (Secrets settings, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("slug", "The secret's reference slug", "OPENAI_API_KEY", type="string"),
            EventVariable("name", "The secret's label", "OpenAI Key", type="name"),
        ],
    ),
    # ── Variables ───────────────────────────────────────────────────────────
    # Variables are plain-text, so the payload may carry the value.
    CatalogEntry(
        event_type="variable_created",
        name="Variable Created",
        description="A workspace variable was created.",
        category="Variables",
        sent_by=["Creating a variable (Variables settings, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("slug", "The variable's reference slug", "SITE_URL", type="string"),
            EventVariable("name", "The variable's label", "Site URL", type="name"),
            EventVariable("value", "The variable's plain-text value", "https://example.com", type="string"),
        ],
    ),
    CatalogEntry(
        event_type="variable_updated",
        name="Variable Updated",
        description="A workspace variable's name, description, or value changed.",
        category="Variables",
        sent_by=["Editing a variable (Variables settings, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("slug", "The variable's reference slug", "SITE_URL", type="string"),
            EventVariable("name", "The variable's label", "Site URL", type="name"),
            EventVariable("value", "The variable's plain-text value", "https://example.com", type="string"),
        ],
    ),
    CatalogEntry(
        event_type="variable_deleted",
        name="Variable Deleted",
        description="A workspace variable was deleted.",
        category="Variables",
        sent_by=["Deleting a variable (Variables settings, API)"],
        variables=COMMON_VARS
        + [
            EventVariable("slug", "The variable's reference slug", "SITE_URL", type="string"),
            EventVariable("name", "The variable's label", "Site URL", type="name"),
        ],
    ),
]

# ── Honesty gate: events with NO real emitter ─────────────────────────────────
# These EventTypes are declared (and had catalog entries) but are NEVER dispatched anywhere in the
# codebase — so advertising them for subscription is a lie: a user could subscribe and never receive
# anything. We keep the enum members (removing them risks breaking serialized data / migrations) but
# force them out of the subscribable catalog. `test_every_catalog_entry_has_an_emitter` verifies this
# set stays accurate as emitters come and go. Give any of these a real dispatch site → remove it here.
_NO_EMITTER: frozenset[str] = frozenset(
    {
        # Security signals with no feature behind them yet. They stay platform scope and audit-locked, so building
        # one is: dispatch it, then take it out of this set.
        "api_rate_limit_exceeded",
        # asset_attached_to_entry / asset_detached_from_entry now have emitters (EntryService.attach_asset
        # / detach_asset) — no longer dead.
        "backup_completed",
        "backup_failed",
        "backup_started",
        "comment_added",
        "comment_deleted",
        "comment_updated",
        "entry_shared",
        "form_submission_failed",
        "form_submission_processed",
        # form_submission_received now has an emitter (the publishing submit path — legacy Forms and
        # the submittable entry-type path) — no longer dead.
        "login_failed_multiple_times",
        "mention_created",
        "scheduled_task_cancelled",
        # site_deployment_* have an emitter (the workflow emit_event step, e.g. from a host's deploy notification);
        # site_build_* are its old names (alias_of), not senders' names.
        "site_published",  # nothing publishes "the site" as one act: site_rebuild_queued / webhook_triggered do
        "storage_quota_exceeded",
        "storage_quota_warning",
        "suspicious_activity_detected",
        "user_deleted",
        "user_password_reset_completed",
        "user_updated",
        # webhook_created/updated/deleted and webhook_delivery_failed are sent (outgoing webhook routes, the
        # publisher). One event per successful delivery would be noise next to the webhook's own activity log.
        "webhook_delivery_succeeded",
    }
)
for _e in CATALOG:
    if _e.event_type in _NO_EMITTER:
        _e.enabled = False  # not offered for subscription — nothing ever emits it

# ── Aliases: old names for another event type ────────────────────────────────────────────────────────
# site_build_* and site_deployment_* were two families for one thing (a host reporting a build/deploy); the
# deployment family is the one kept. An alias is never offered, triggerable or emittable, and anything that
# names it — a workflow trigger, an Emit event step, a subscription — is stored and run as its target
# (`canonical_event_type`; the 2026-10-06 migration rewrote stored ones). Its enum member stays.
ALIASES: dict[str, str] = {e.event_type: e.alias_of for e in CATALOG if e.alias_of}
for _e in CATALOG:
    if _e.alias_of:
        _e.enabled = _e.triggerable = _e.emittable = False

# ── Hidden gate: never shown ─────────────────────────────────────────────────────────────────────────
# Nothing sends a _NO_EMITTER type and an alias is another type's old name, so neither is listed anywhere a
# workspace or admin browses or picks event types (the Events catalog, the pickers, Audit coverage, the admin
# Events filter, the connections summary). Their entries stay so old Event Log rows keep a name.
HIDDEN_EVENT_TYPES: frozenset[str] = _NO_EMITTER | frozenset(ALIASES)
for _e in CATALOG:
    _e.hidden = _e.event_type in HIDDEN_EVENT_TYPES

# ── Security gate: events that are always audited ─────────────────────────────
# Who can get in and with what rights, which credentials exist, and how the workspace (its audit
# settings included: they're recorded as workspace_settings_changed) is configured. A workspace admin
# can't drop these from the Event Log — the record of what an admin did must not be theirs to switch off.
# Locking is by category, so a new entry in one of these categories is locked without anyone remembering.
_AUDIT_LOCKED_CATEGORIES: frozenset[str] = frozenset({"Members", "Authentication", "Workspaces", "Security", "Secrets"})
_AUDIT_LOCKED_PREFIXES: tuple[str, ...] = ("api_client_", "approval_")
"""API clients (and their tokens) sit in Connect, next to webhooks: they're credentials. Approvals sit in AI:
they're a person authorising (or refusing) an AI tool call."""
for _e in CATALOG:
    if _e.category in _AUDIT_LOCKED_CATEGORIES or _e.event_type.startswith(_AUDIT_LOCKED_PREFIXES):
        _e.audit_locked = True  # test_audit_settings checks a locked entry isn't also declared audited=False

# ── Platform gate: events that belong to the platform, not to a workspace ─────────────────────────────
# Accounts (sign-up, profile, password, token refresh), workspaces as a platform admin creates, edits and deletes
# them (workspace_updated is only emitted by the admin workspace controller) or a user switches to them, personal
# API tokens (user-level, unlike a workspace's API clients), the platform's own security signals and backups.
# They keep the workspace_id they were dispatched with and fire the same subscriptions; only the super-admin
# Events page lists them. They're always audited (most are security records, and no workspace admin owns them).
# What stays workspace scope: members and invitations, workspace_settings_changed (a workspace admin changing
# their own workspace), secrets, variables, storage quota, content, automation, AI.
_PLATFORM_SCOPE: frozenset[str] = frozenset(
    {
        "user_signup",
        "user_updated",
        "user_deleted",
        "user_password_reset_requested",
        "user_password_reset_completed",
        "token_refreshed",
        "workspace_created",
        "workspace_updated",
        "workspace_deleted",
        "workspace_activated",
        "api_token_created",
        "api_token_rotated",
        "api_token_revoked",
        "api_rate_limit_exceeded",
        "login_failed_multiple_times",
        "suspicious_activity_detected",
        "backup_started",
        "backup_completed",
        "backup_failed",
    }
)
for _e in CATALOG:
    if _e.event_type in _PLATFORM_SCOPE:
        _e.scope = "platform"
        _e.audit_locked = True

PLATFORM_EVENT_TYPES: frozenset[str] = frozenset(e.event_type for e in CATALOG if e.scope == "platform")
"""Every platform-scope event type: what the workspace's reads of the Event Log leave out."""

# Quick lookup
CATALOG_BY_TYPE: dict[str, CatalogEntry] = {e.event_type: e for e in CATALOG}

TRIGGERABLE_EVENT_TYPES: frozenset[str] = frozenset(e.event_type for e in CATALOG if e.triggerable)
"""What a workflow's "event" trigger can name — the automation listener reacts to exactly these (plus the
incoming_webhook / chained / on_error trigger types' own events)."""

EMITTABLE_EVENT_TYPES: frozenset[str] = frozenset(e.event_type for e in CATALOG if e.emittable)
"""What a workflow's Emit event step accepts."""

INTERNAL_EVENT_TYPES: frozenset[str] = frozenset(e.event_type for e in CATALOG if e.internal)
"""Scheduler plumbing kept out of the info log and the console listener."""


def trigger_groups() -> dict[str, list[str]]:
    """The builder's trigger dropdown: triggerable events under their heading, both in catalog order."""
    groups: dict[str, list[str]] = {}
    for e in CATALOG:
        if e.triggerable:
            groups.setdefault(e.trigger_group or e.category, []).append(e.event_type)
    return groups


def offered_emittable() -> list[str]:
    """What the builder's Emit event step offers, in catalog order: emittable events that are also subscribable
    (an event nothing else sends isn't offered, though the step still accepts it)."""
    return [e.event_type for e in CATALOG if e.emittable and e.enabled]


# Categories in display order
CATEGORIES = [
    "Members",
    "Authentication",
    "Workspaces",
    "Content",
    "Assets",
    "Forms",
    "Publishing",
    "Connect",
    "Automation",
    "AI",
    "Collaboration",
    "Workflow",
    "Security",
    "Secrets",
    "Variables",
    "System",
]


def canonical_event_type(event_type: str) -> str:
    """The event type a name stands for: an alias's target (site_build_completed → site_deployment_completed),
    anything else unchanged."""
    return ALIASES.get(event_type, event_type)


def aliases_of(event_type: str) -> list[str]:
    """The old names that stand for `event_type` (empty for most types)."""
    return [alias for alias, target in ALIASES.items() if target == event_type]


def get_event_variables(event_type: str) -> list[EventVariable]:
    """Return variables available for a given event type."""
    entry = CATALOG_BY_TYPE.get(event_type)
    return entry.variables if entry else []


def get_catalog_entry(event_type: str) -> CatalogEntry | None:
    return CATALOG_BY_TYPE.get(event_type)


def is_platform_event(event_type: str) -> bool:
    """A platform-scope event: the admin Events page shows it, a workspace's Event Log doesn't."""
    return event_type in PLATFORM_EVENT_TYPES
