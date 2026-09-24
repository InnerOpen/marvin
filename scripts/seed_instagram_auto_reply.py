#!/usr/bin/env python3
"""
Instagram auto-reply seed.

Sets up the content side of the `marvin-integration-instagram` provider in one workspace: the rule
and log entry types, the scheduled task that runs the provider's `auto_reply` action, an optional
token-refresh task, and three sample rules as drafts. The integration itself (token + IG user id)
is created in Settings → Integrations; this script only prepares what the task reads and writes.

Idempotent by (workspace, slug): entry types are created or brought up to date, tasks and sample
rules are created only when missing (so edits made in the CMS survive a re-run). The auto-reply
task starts disabled and in dry-run — flip `task_config.args.dry_run` and `enabled` via
PATCH /api/scheduled-tasks/instagram-auto-reply once a dry run shows the right `would_send`.

Usage:
    uv run scripts/seed_instagram_auto_reply.py --workspace mash-burn-co
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from marvin.db.db_setup import session_context  # noqa: E402
from marvin.db.models.groups import Groups  # noqa: E402
from marvin.db.models.platform import Entries, EntryTypes  # noqa: E402
from marvin.repos.repository_factory import AllRepositories  # noqa: E402
from marvin.schemas.platform.scheduled_tasks import ScheduledTaskCreate  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

INTEGRATION_SLUG = "instagram"
RULES_TYPE = "ig-auto-reply"
LOG_TYPE = "ig-reply-log"
AUTO_REPLY_TASK = "instagram-auto-reply"
TOKEN_REFRESH_TASK = "instagram-token-refresh"
POLL_INTERVAL_SECONDS = 120
TOKEN_REFRESH_INTERVAL_SECONDS = 30 * 24 * 3600  # long-lived tokens last 60 days

# Internal content: never rendered, submitted or routed — the CMS is just the editor for it.
INTERNAL_CAPABILITIES = {"publishable": False, "submittable": False, "routable": False}

ENTRY_TYPES = [
    {
        "slug": RULES_TYPE,
        "name": "IG Auto-Reply Rule",
        "icon": "message-circle",
        "description": "Keyword → private-reply rule for Instagram comments. Only published rules apply.",
        "schema_json": {
            "fields": [
                {"key": "post_id", "label": "Post ID", "type": "text", "required": False, "placeholder": "* for all posts"},
                {"key": "keywords", "label": "Keywords (comma-separated)", "type": "text", "required": True},
                {"key": "reply", "label": "Reply DM", "type": "textarea", "required": True},
            ]
        },
        "capabilities_json": INTERNAL_CAPABILITIES,
    },
    {
        "slug": LOG_TYPE,
        "name": "IG Reply Log",
        "icon": "send",
        "description": "One entry per private reply sent. Its comment_id is what stops a comment being answered twice.",
        "schema_json": {
            "fields": [
                {"key": "comment_id", "label": "Comment ID", "type": "text", "required": True, "readOnly": True},
                {"key": "media_id", "label": "Post ID", "type": "text", "readOnly": True},
                {"key": "username", "label": "Commenter", "type": "text", "readOnly": True},
                {"key": "keyword", "label": "Matched keyword", "type": "text", "readOnly": True},
                {"key": "reply", "label": "Reply sent", "type": "textarea", "readOnly": True},
                {"key": "text", "label": "Comment text", "type": "textarea", "readOnly": True},
                {"key": "sent_at", "label": "Sent at", "type": "text", "readOnly": True},
            ]
        },
        "capabilities_json": INTERNAL_CAPABILITIES,
    },
]

AUTO_REPLY_TASK_CONFIG = {
    "integration": INTEGRATION_SLUG,
    "action": "auto_reply",
    "args": {"dry_run": True, "max_age_days": 7},
    "inputs": {
        "rules": {"entry_type": RULES_TYPE, "status": "published", "as": "records"},
        "skip_comment_ids": {"entry_type": LOG_TYPE, "as": "field", "field": "comment_id"},
    },
    "outputs": {
        "records_entry_type": LOG_TYPE,
        "slug_prefix": "ig-reply-",
        "slug_field": "comment_id",
        "title_template": "Reply to @{username} ({keyword})",
        "status": "draft",
    },
}

TASKS = [
    ScheduledTaskCreate(
        name="Instagram auto-reply",
        slug=AUTO_REPLY_TASK,
        description="Match recent comments against published IG Auto-Reply Rules and DM the reply. Starts disabled, in dry-run.",
        enabled=False,
        schedule_type="interval",
        schedule_config={"interval_seconds": POLL_INTERVAL_SECONDS},
        task_type="run_integration_action",
        task_config=AUTO_REPLY_TASK_CONFIG,
    ),
    ScheduledTaskCreate(
        name="Instagram token refresh",
        slug=TOKEN_REFRESH_TASK,
        description="Extend the long-lived Instagram token (60-day expiry). Starts disabled.",
        enabled=False,
        schedule_type="interval",
        schedule_config={"interval_seconds": TOKEN_REFRESH_INTERVAL_SECONDS},
        task_type="run_integration_action",
        task_config={"integration": INTEGRATION_SLUG, "action": "refresh_token"},
    ),
]

# From the n8n prototype. Created as drafts: publish the ones you want live.
SAMPLE_RULES = [
    {
        "slug": "ig-rule-size",
        "title": "Size",
        "data_json": {
            "post_id": "*",
            "keywords": "size, sizing, sizes",
            "reply": "Hey! Thanks for asking. Sizing runs true to a classic fit — measurements for every piece are on the product page. Happy to help you pick if you tell me your usual size.",
        },
    },
    {
        "slug": "ig-rule-link",
        "title": "Link",
        "data_json": {
            "post_id": "*",
            "keywords": "link, where, shop",
            "reply": "Here you go: https://mashandburn.co — everything current is on the Projects page. Thanks for the interest!",
        },
    },
    {
        "slug": "ig-rule-price",
        "title": "Price",
        "data_json": {
            "post_id": "*",
            "keywords": "price, cost, how much",
            "reply": "Thanks for asking! Prices are on each project page at https://mashandburn.co — pieces are made one at a time, so lead times are listed there too.",
        },
    },
]


def upsert_entry_types(session, workspace: Groups) -> dict[str, EntryTypes]:
    out = {}
    for spec in ENTRY_TYPES:
        et = session.query(EntryTypes).filter(EntryTypes.group_id == workspace.id, EntryTypes.slug == spec["slug"]).first()
        if et:
            for key in ("name", "icon", "description", "schema_json", "capabilities_json"):
                setattr(et, key, spec[key])
            logger.info("  ✓ Entry type '%s' updated", spec["slug"])
        else:
            et = EntryTypes(session=session, group_id=workspace.id, **spec)
            session.add(et)
            logger.info("  ✓ Entry type '%s' created", spec["slug"])
        session.commit()
        out[spec["slug"]] = et
    return out


def ensure_tasks(session, workspace: Groups) -> None:
    repos = AllRepositories(session, group_id=workspace.id)
    for task in TASKS:
        if repos.scheduled_tasks.get_by_slug(task.slug):
            logger.info("  ✓ Task '%s' exists (left as is)", task.slug)
            continue
        repos.scheduled_tasks.create(task)
        logger.info("  ✓ Task '%s' created (enabled=%s)", task.slug, task.enabled)


def ensure_sample_rules(session, workspace: Groups, rules_type: EntryTypes) -> None:
    for rule in SAMPLE_RULES:
        if session.query(Entries.id).filter(Entries.group_id == workspace.id, Entries.slug == rule["slug"]).first():
            logger.info("  ✓ Rule '%s' exists (left as is)", rule["slug"])
            continue
        session.add(
            Entries(
                session=session,
                group_id=workspace.id,
                entry_type_id=rules_type.id,
                title=rule["title"],
                slug=rule["slug"],
                status="draft",
                data_json=rule["data_json"],
            )
        )
        session.commit()
        logger.info("  ✓ Rule '%s' created as draft", rule["slug"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", required=True, help="workspace slug")
    args = parser.parse_args()

    with session_context() as session:
        workspace = session.query(Groups).filter(Groups.slug == args.workspace).first()
        if not workspace:
            logger.error("❌ Workspace '%s' not found", args.workspace)
            return 1
        logger.info("Workspace: %s (%s)", workspace.name, workspace.id)

        logger.info("1. Entry types")
        types = upsert_entry_types(session, workspace)
        logger.info("2. Scheduled tasks")
        ensure_tasks(session, workspace)
        logger.info("3. Sample rules")
        ensure_sample_rules(session, workspace, types[RULES_TYPE])

    logger.info("")
    logger.info("✅ Done. Next: Settings → Integrations → Instagram (token + IG user id), publish a rule,")
    logger.info("   then POST /api/scheduled-tasks/%s/execute and read GET /api/scheduled-tasks/log.", AUTO_REPLY_TASK)
    return 0


if __name__ == "__main__":
    sys.exit(main())
