"""Core-owned blueprints for social engagement: the shared auto-reply rule and log, their collections and the engine's task.

Unlike the rest of the core catalog these name their own content (``social-auto-reply``, ``social-reply-log``): the
engagement engine (services/integrations/social_engagement.py) reads and writes exactly these types, so core — not a
network's plugin — owns them, and one set serves every network. They are suggestions like any core blueprint (nothing is
created until a workspace applies them), applied together from Settings → Blueprints; the engine says so when the log
type is missing. The task starts disabled and in rehearsal.

Instagram's ``ig-auto-reply`` / ``ig-reply-log`` types (its plugin's blueprints) stay as they are: the engine reads the rules
as rules for network instagram and the log as "already answered" (services/integrations/social_rules.py).
"""

from marvin.schemas.platform.blueprints import Blueprint

from ..integrations.social_rules import LOG_TYPE, RULE_TYPE

CATEGORY_SOCIAL = "Social"
TASK_SLUG = "social-engagement"
ENGINE_INTERVAL_SECONDS = 5 * 60
RULES_ICON = "💬"
SENT_ICON = "📤"
SOCIAL_COLOR = "#6366F1"

# Internal content, like Instagram's: never rendered, submitted or routed — the CMS is just the editor for it.
_INTERNAL = {"publishable": False, "submittable": False, "routable": False}

_RULE_FIELDS = [
    {
        "key": "keywords",
        "label": "Keywords (comma-separated)",
        "type": "text",
        "required": True,
        "helpText": "A whole word or phrase, any case: “price” matches “What's the price?” but not “priceless”.",
    },
    {
        "key": "reply",
        "label": "Reply",
        "type": "textarea",
        "required": True,
        "helpText": "Sent exactly as written. Publishing the rule approves this text.",
    },
    {
        "key": "networks",
        "label": "Networks (empty = any)",
        "type": "text",
        "placeholder": "e.g. instagram, mastodon",
        "helpText": "Integration slugs or network names, comma-separated.",
    },
    {
        "key": "post",
        "label": "Post (empty = any)",
        "type": "text",
        "placeholder": "a post id or URL",
        "helpText": "A rule for one post wins over a rule for any post.",
    },
    {
        "key": "reply_as",
        "label": "Reply as",
        "type": "select",
        "options": ["private", "public", "both"],
        "defaultValue": "private",
        "helpText": "Private is a direct reply to the commenter; public answers in the thread. A network that can't do the mode is skipped.",
    },
    {"key": "also_like", "label": "Also like the comment", "type": "boolean", "defaultValue": False},
    {
        "key": "kinds",
        "label": "Answers (comma-separated)",
        "type": "text",
        "defaultValue": "comment, reply",
        "helpText": "comment and reply are answers on your own posts. Add mention to also answer people tagging you elsewhere.",
    },
]

_LOG_FIELDS = [
    {"key": key, "label": label, "type": kind, "readOnly": True, **({"required": True} if key == "comment_id" else {})}
    for key, label, kind in (
        ("network", "Network", "text"),
        ("integration", "Integration", "text"),
        ("comment_id", "Comment ID", "text"),
        ("rule", "Rule", "text"),
        ("mode", "Mode", "text"),
        ("rehearsal", "Rehearsal (nothing was sent)", "boolean"),
        ("reply_id", "Reply ID", "text"),
        ("when", "When", "text"),
        ("post_id", "Post ID", "text"),
        ("author", "Commenter", "text"),
        ("keyword", "Matched keyword", "text"),
        ("comment", "Comment", "textarea"),
        ("reply", "Reply", "textarea"),
        ("url", "Link", "text"),
        ("liked", "Liked", "boolean"),
        ("public_reply_id", "Public reply ID (mode both)", "text"),
        ("error", "Note", "text"),
    )
]

SOCIAL_BLUEPRINTS: tuple[Blueprint, ...] = (
    Blueprint(
        kind="entry_type",
        slug=RULE_TYPE,
        name="Social auto-reply rule",
        category=CATEGORY_SOCIAL,
        description="A keyword and the reply it triggers, on any connected network. Only published rules fire; drafts are inert.",
        payload={
            "name": "Social auto-reply rule",
            "icon": RULES_ICON,
            "color": SOCIAL_COLOR,
            "description": "Keyword → reply rule for comments on connected social networks. Publishing a rule approves its reply text.",
            "schema_json": {"fields": _RULE_FIELDS},
            "capabilities_json": _INTERNAL,
        },
    ),
    Blueprint(
        kind="entry_type",
        slug=LOG_TYPE,
        name="Social reply log",
        category=CATEGORY_SOCIAL,
        description="One entry per comment answered (or, in rehearsal, that would have been). It is what stops a comment being answered twice.",
        payload={
            "name": "Social reply log",
            "icon": SENT_ICON,
            "color": SOCIAL_COLOR,
            "description": "One entry per automated reply: network, comment, rule, mode, rehearsal or sent.",
            "schema_json": {"fields": _LOG_FIELDS},
            "capabilities_json": _INTERNAL,
        },
    ),
    Blueprint(
        kind="collection",
        slug="social-auto-reply-rules",
        name="Social — Auto-reply rules",
        category=CATEGORY_SOCIAL,
        description="Your keyword replies in one place. Draft rules are inert; published ones fire.",
        requires=(f"entry_type:{RULE_TYPE}",),
        payload={
            "name": "Social — Auto-reply rules",
            "description": "Keyword replies for every connected network.",
            "icon": RULES_ICON,
            "color": SOCIAL_COLOR,
            "is_smart": True,
            "is_public": False,
            "smart_rules": {"entry_types": [RULE_TYPE], "match": "all"},
        },
    ),
    Blueprint(
        kind="collection",
        slug="social-replies",
        name="Social — Replies",
        category=CATEGORY_SOCIAL,
        description="Every automated reply, newest first — rehearsal entries show what would have been sent.",
        requires=(f"entry_type:{LOG_TYPE}",),
        payload={
            "name": "Social — Replies",
            "description": "Every automated reply (and rehearsal) across networks.",
            "icon": SENT_ICON,
            "color": SOCIAL_COLOR,
            "is_smart": True,
            "is_public": False,
            "smart_rules": {"entry_types": [LOG_TYPE], "match": "all"},
        },
    ),
    Blueprint(
        kind="scheduled_task",
        slug=TASK_SLUG,
        name="Social engagement",
        category=CATEGORY_SOCIAL,
        description="Every 5 minutes: read new comments on each network and reply under the published rules. Starts disabled, in rehearsal.",
        requires=(f"entry_type:{LOG_TYPE}",),
        payload={
            "name": "Social engagement",
            "description": (
                "Reads new comments on every connected network and answers keyword matches under published rules. "
                "Starts disabled and in rehearsal (logs what it would send); set rehearsal to false to send."
            ),
            "enabled": False,
            "schedule_type": "interval",
            "schedule_config": {"interval_seconds": ENGINE_INTERVAL_SECONDS},
            "task_type": "social_engagement",
            "task_config": {"rehearsal": True, "max_replies": 20, "max_age_days": 7, "limit": 50},
        },
    ),
)
