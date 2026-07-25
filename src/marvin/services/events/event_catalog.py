"""
Event catalog — defines user-subscribable events with their data contracts.

Each entry describes:
  - name: human-readable event name
  - description: what triggers this event
  - category: grouping for the UI
  - variables: {{slug}} values available in templates/notifications
  - enabled: whether this event is available for subscription
"""

from dataclasses import dataclass, field


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
    """Whether this event is persisted to the event_log audit trail. Set False for
    high-frequency internal plumbing whose outcomes are captured elsewhere."""


COMMON_VARS = [
    EventVariable("workspace_name", "Name of the workspace", "My Blog", type="name"),
    EventVariable("message_title", "Auto-generated event title (e.g. 'Entry Published')", "Entry Published", type="string"),
    EventVariable("message_body", "Optional description passed when the event was dispatched", "", type="string"),
    EventVariable("event_type", "Machine-readable event name", "entry_published", type="string"),
    EventVariable("timestamp", "ISO 8601 timestamp of when the event fired", "2026-07-16T10:00:00Z", type="datetime"),
    EventVariable("email_address", "Email address from the event (invitee, recipient, etc.)", "user@example.com", type="email"),
    EventVariable("button_link", "Primary URL from the event (invitation link, reset link, etc.)", "https://...", type="url"),
]

CATALOG: list[CatalogEntry] = [
    # ── Invitations ─────────────────────────────────────────────────────────
    CatalogEntry(
        event_type="invitation_created",
        name="Invitation Created",
        description="A workspace invitation link was created.",
        category="Members",
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
    # ── Workspaces ───────────────────────────────────────────────────────────
    CatalogEntry(
        event_type="workspace_created",
        name="Workspace Created",
        description="A new workspace was created.",
        category="Workspaces",
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
        variables=COMMON_VARS + [],
    ),
    CatalogEntry(
        event_type="workspace_settings_changed",
        name="Workspace Settings Changed",
        description="Workspace preferences or settings were modified.",
        category="Workspaces",
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
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Title of the restored entry", "My Post", type="title"),
            EventVariable("author_name", "Who restored it", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="entry_deleted",
        name="Entry Deleted",
        description="A content entry was permanently deleted.",
        category="Content",
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
        variables=COMMON_VARS
        + [
            EventVariable("asset_name", "Filename of the asset", "photo.jpg", type="name"),
            EventVariable("entry_title", "Title of the entry", "My Post", type="title"),
        ],
    ),
    # ── Forms ────────────────────────────────────────────────────────────────
    CatalogEntry(
        event_type="form_created",
        name="Form Created",
        description="A new form was created.",
        category="Forms",
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
        variables=COMMON_VARS
        + [
            EventVariable("form_name", "Name of the deleted form", "Contact Form", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="form_submission_received",
        name="Form Submission Received",
        description="Someone submitted a form in the workspace.",
        category="Forms",
        variables=COMMON_VARS
        + [
            EventVariable("form_name", "Name of the form", "Contact Form", type="name"),
            EventVariable("submitter_email", "Email of the submitter (if provided)", "user@example.com", type="email"),
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
        event_type="site_deployment_started",
        name="Site Deployment Started",
        description="A site deployment has begun.",
        category="Publishing",
        variables=COMMON_VARS
        + [
            EventVariable("site_url", "URL of the site being deployed", "https://mysite.com", type="url"),
        ],
    ),
    CatalogEntry(
        event_type="site_deployment_completed",
        name="Site Deployment Completed",
        description="A site deployment finished successfully.",
        category="Publishing",
        variables=COMMON_VARS
        + [
            EventVariable("site_url", "URL of the deployed site", "https://mysite.com", type="url"),
            EventVariable("duration", "How long the deployment took", "45s", type="duration"),
        ],
    ),
    CatalogEntry(
        event_type="site_deployment_failed",
        name="Site Deployment Failed",
        description="A site deployment failed.",
        category="Publishing",
        variables=COMMON_VARS
        + [
            EventVariable("error_message", "What went wrong", "Build timeout", type="error"),
        ],
    ),
    CatalogEntry(
        event_type="site_build_started",
        name="Site Build Started",
        description="A site build process has started.",
        category="Publishing",
        variables=COMMON_VARS
        + [
            EventVariable("site_url", "URL of the site being built", "https://mysite.com", type="url"),
        ],
    ),
    CatalogEntry(
        event_type="site_build_completed",
        name="Site Build Completed",
        description="A site build process finished successfully.",
        category="Publishing",
        variables=COMMON_VARS
        + [
            EventVariable("site_url", "URL of the deployed site", "https://mysite.com", type="url"),
            EventVariable("duration", "How long the build took", "45s", type="duration"),
        ],
    ),
    CatalogEntry(
        event_type="site_build_failed",
        name="Site Build Failed",
        description="A site build failed.",
        category="Publishing",
        variables=COMMON_VARS
        + [
            EventVariable("error_message", "What went wrong", "Compilation error", type="error"),
        ],
    ),
    # ── Connect: Webhooks ─────────────────────────────────────────────────────
    CatalogEntry(
        event_type="incoming_webhook",
        name="Incoming Webhook Received",
        description="An external system POSTed to a tokened incoming-webhook URL. Automations can "
        "react to this and read the request body via $event.payload.",
        category="Connect",
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
        description="A new webhook was configured.",
        category="Connect",
        variables=COMMON_VARS
        + [
            EventVariable("webhook_url", "URL the webhook posts to", "https://...", type="url"),
            EventVariable("created_by", "Who created the webhook", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="webhook_updated",
        name="Webhook Updated",
        description="A webhook configuration was updated.",
        category="Connect",
        variables=COMMON_VARS
        + [
            EventVariable("webhook_url", "URL the webhook posts to", "https://...", type="url"),
        ],
    ),
    CatalogEntry(
        event_type="webhook_deleted",
        name="Webhook Deleted",
        description="A webhook was deleted.",
        category="Connect",
        variables=COMMON_VARS
        + [
            EventVariable("webhook_url", "URL of the deleted webhook", "https://...", type="url"),
        ],
    ),
    CatalogEntry(
        event_type="webhook_triggered",
        name="Webhook Triggered",
        description="A webhook was triggered by an event.",
        category="Connect",
        variables=COMMON_VARS
        + [
            EventVariable("webhook_url", "URL the webhook posted to", "https://...", type="url"),
            EventVariable("event_type", "Event that triggered the webhook", "entry_published"),
        ],
    ),
    CatalogEntry(
        event_type="webhook_delivery_succeeded",
        name="Webhook Delivery Succeeded",
        description="A webhook was delivered successfully.",
        category="Connect",
        variables=COMMON_VARS
        + [
            EventVariable("webhook_url", "URL the webhook was delivered to", "https://...", type="url"),
            EventVariable("status_code", "HTTP response code received", "200", type="count"),
        ],
    ),
    CatalogEntry(
        event_type="webhook_delivery_failed",
        name="Webhook Delivery Failed",
        description="A webhook delivery failed.",
        category="Connect",
        variables=COMMON_VARS
        + [
            EventVariable("webhook_url", "URL the webhook attempted to post to", "https://...", type="url"),
            EventVariable("error_message", "What went wrong", "Connection refused", type="error"),
            EventVariable("status_code", "HTTP response code received (if any)", "503", type="count"),
        ],
    ),
    # ── Connect: API Clients ──────────────────────────────────────────────────
    CatalogEntry(
        event_type="api_client_created",
        name="API Client Created",
        description="A new API client was registered.",
        category="Connect",
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
        variables=COMMON_VARS
        + [
            EventVariable("client_name", "Name of the API client", "My Site Client", type="name"),
        ],
    ),
    # ── Security ─────────────────────────────────────────────────────────────
    CatalogEntry(
        event_type="api_token_created",
        name="API Token Created",
        description="A new API token was generated.",
        category="Security",
        variables=COMMON_VARS
        + [
            EventVariable("token_name", "Name given to the token", "CI Deploy Token", type="name"),
            EventVariable("created_by", "Who created it", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="api_token_rotated",
        name="API Token Rotated",
        description="An API token was rotated (old token invalidated, new one issued).",
        category="Security",
        variables=COMMON_VARS
        + [
            EventVariable("token_name", "Name of the rotated token", "CI Deploy Token", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="api_token_revoked",
        name="API Token Revoked",
        description="An API token was revoked.",
        category="Security",
        variables=COMMON_VARS
        + [
            EventVariable("token_name", "Name of the revoked token", "CI Deploy Token", type="name"),
        ],
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
        variables=COMMON_VARS
        + [
            EventVariable("task_name", "Name of the deleted task", "Daily Cleanup", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="webhook_task",
        name="Webhook Task (internal)",
        description="Internal scheduler tick that dispatches due webhooks. Not subscribable; "
        "delivery outcomes are recorded in webhook_execution_logs.",
        category="Automation",
        enabled=False,  # internal plumbing — not offered for subscription
        audited=False,  # high-frequency noise — kept out of the audit log
    ),
    CatalogEntry(
        event_type="scheduled_task_triggered",
        name="Scheduled Task Triggered",
        description="A scheduled task was manually triggered.",
        category="Automation",
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
        audited=False,  # start marker — completed/failed carry the audit value
        variables=COMMON_VARS
        + [
            EventVariable("task_name", "Name of the task", "Daily Cleanup", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="scheduled_task_completed",
        name="Scheduled Task Completed",
        description="A scheduled task ran successfully.",
        category="Automation",
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
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "Title of the shared entry", "My Post", type="title"),
            EventVariable("shared_by", "Who shared the entry", "Jane Smith", type="name"),
            EventVariable("shared_with", "Who it was shared with", "jsmith", type="username"),
        ],
    ),
    # ── Workflow / Approvals ─────────────────────────────────────────────────
    CatalogEntry(
        event_type="approval_requested",
        name="Approval Requested",
        description="An entry or action was submitted for approval.",
        category="Workflow",
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "What needs approval", "My Post", type="title"),
            EventVariable("requester_name", "Who submitted it", "Jane Smith", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="approval_granted",
        name="Approval Granted",
        description="An approval request was accepted.",
        category="Workflow",
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "What was approved", "My Post", type="title"),
            EventVariable("approver_name", "Who approved it", "Admin", type="name"),
        ],
    ),
    CatalogEntry(
        event_type="approval_rejected",
        name="Approval Rejected",
        description="An approval request was declined.",
        category="Workflow",
        variables=COMMON_VARS
        + [
            EventVariable("entry_title", "What was rejected", "My Post", type="title"),
            EventVariable("approver_name", "Who rejected it", "Admin", type="name"),
            EventVariable("reason", "Reason for rejection", "Needs more detail"),
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
        "api_rate_limit_exceeded",
        "api_token_created",
        "api_token_revoked",
        "api_token_rotated",
        "approval_granted",
        "approval_rejected",
        "approval_requested",
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
        "form_submission_received",
        "login_failed_multiple_times",
        "mention_created",
        "scheduled_task_cancelled",
        "site_build_completed",
        "site_build_failed",
        "site_build_started",
        "site_deployment_completed",
        "site_deployment_failed",
        "site_deployment_started",
        "site_published",
        "storage_quota_exceeded",
        "storage_quota_warning",
        "suspicious_activity_detected",
        "user_deleted",
        "user_password_reset_completed",
        "user_updated",
        "webhook_created",
        "webhook_deleted",
        "webhook_delivery_failed",
        "webhook_delivery_succeeded",
        "webhook_updated",
    }
)
for _e in CATALOG:
    if _e.event_type in _NO_EMITTER:
        _e.enabled = False  # not offered for subscription — nothing ever emits it

# Quick lookup
CATALOG_BY_TYPE: dict[str, CatalogEntry] = {e.event_type: e for e in CATALOG}

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
    "System",
]


def get_event_variables(event_type: str) -> list[EventVariable]:
    """Return variables available for a given event type."""
    entry = CATALOG_BY_TYPE.get(event_type)
    return entry.variables if entry else []


def get_catalog_entry(event_type: str) -> CatalogEntry | None:
    return CATALOG_BY_TYPE.get(event_type)


def sync_notifier_options(session) -> int:
    """Ensure every enabled catalog event is a subscribable notifier option.

    The notifier-options catalog (``events_notifier_options``) is seeded from a static JSON that
    drifts behind ``CATALOG`` as new events are added — so an event the UI offers a "Connect" button
    for (e.g. ``incoming_webhook``) may be absent, and subscribing a notifier to it raises
    "Notification option 'core.<slug>' does not exist" → 400. This reconciles the catalog to the
    single source of truth: additive and idempotent — inserts missing ``core.<event_type>`` rows,
    never touches existing rows' enabled flags. Returns the number inserted.
    """
    from marvin.db.models.events.events import EventNotifierOptionsModel

    existing = {slug for (slug,) in session.query(EventNotifierOptionsModel.slug).all()}
    inserted = 0
    for entry in CATALOG:
        if not entry.enabled or entry.event_type in existing:
            continue
        opt = EventNotifierOptionsModel(session=session, name=entry.name, namespace="core", enabled=True)
        opt.slug = entry.event_type  # override decamelize(name); the subscribe validator matches on slug
        opt.description = entry.description
        session.add(opt)
        existing.add(entry.event_type)
        inserted += 1
    if inserted:
        session.commit()
    return inserted
