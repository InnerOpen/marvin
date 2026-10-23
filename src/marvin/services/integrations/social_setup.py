"""Social's plumbing: what a workspace needs for Social, made on its own and never offered as a setup step.

Social isn't an integration, it is a feature the networks' plugins light up: it appears when the workspace has an enabled
integration that offers a ``social.*`` capability (a network that can post, read comments, reply…), and not before. Nothing here
is something a person applies or switches on:

* **the rule type** (``social-auto-reply``, an internal entry type: ``listed: false``) is created the first time it is needed — when
  the first social integration is connected, or on the first visit to Social (``ensure_rule_type``);
* **the engine's scheduled task** (``social-engagement``, every 5 minutes) is created and enabled while an enabled integration
  offers ``social.comments``, and disabled when none does (``reconcile``). It reads each network for the inbox and the
  new-comment trigger whatever the network's auto-reply mode is;
* **auto-reply is per network**: ``integrations.state.social.auto_reply`` is ``off`` (the default), ``rehearsal`` (dry runs,
  recorded on the item) or ``on`` (live) — ``get_mode`` / ``set_mode``. A task that still carries the old task-wide
  ``rehearsal`` setting has it mapped onto the networks once (``map_legacy_rehearsal``).

``reconcile`` runs when an integration is created, changed or deleted, on a visit to Social, and hourly for every workspace
(``reconcile_social_engagement``, a system task) so a workspace that already had a network when this shipped gets its task.
"""

from __future__ import annotations

from dataclasses import dataclass

from marvin.core.root_logger import get_logger

from .social import SOCIAL_COMMENTS, SOCIAL_REPLY
from .social_rules import RULE_TYPE

logger = get_logger(__name__)

OFF, REHEARSAL, ON = "off", "rehearsal", "on"
AUTO_REPLY_MODES = (OFF, REHEARSAL, ON)
STATE_KEY = "social"
TASK_SLUG = "social-engagement"
TASK_TYPE = "social_engagement"
ENGINE_INTERVAL_SECONDS = 5 * 60
SOCIAL_PREFIX = "social."

RULES_ICON = "💬"
SOCIAL_COLOR = "#6366F1"
RULE_TYPE_NAME = "Social auto-reply rule"

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
        "label": "Networks (empty = every network)",
        "type": "text",
        "placeholder": "e.g. instagram, mastodon",
        "helpText": "Integration slugs, comma-separated. Empty applies to every network; a rule for one network wins over one for all.",
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
        "helpText": (
            "comment and reply are answers on your own posts. Add mention to also answer people tagging you elsewhere, and message "
            "(story_reply, story_mention) to answer direct messages — by a direct message back."
        ),
    },
    {
        "key": "cooldown_hours",
        "label": "Cool-down for direct messages (hours)",
        "type": "number",
        "defaultValue": 24,
        "helpText": (
            "After someone is answered by direct message, no rule answers them again for this long; only their newest message is "
            "answered. 0 turns it off. A rule answers only messages sent after it was published."
        ),
    },
]

RULE_TYPE_PAYLOAD = {
    "name": RULE_TYPE_NAME,
    "icon": RULES_ICON,
    "color": SOCIAL_COLOR,
    "description": "Keyword → reply rule for comments on connected social networks. Publishing a rule approves its reply text.",
    "schema_json": {"fields": _RULE_FIELDS},
    # Internal: edited from Social › a network › Rules, never listed with the workspace's content (services/entry_listing.py).
    "capabilities_json": {"publishable": False, "submittable": False, "routable": False, "listed": False},
}


@dataclass(frozen=True)
class SocialNetwork:
    """An enabled integration that offers at least one ``social.*`` capability."""

    row: object
    provider: object
    capabilities: frozenset[str]

    @property
    def reads_comments(self) -> bool:
        return SOCIAL_COMMENTS in self.capabilities

    @property
    def can_reply(self) -> bool:
        return SOCIAL_REPLY in self.capabilities


def capabilities_of(provider) -> frozenset[str]:
    """The ``social.*`` capabilities a provider's actions declare."""
    found = {getattr(a, "capability", None) for a in getattr(provider, "actions", ()) or ()}
    return frozenset(c for c in found if isinstance(c, str) and c.startswith(SOCIAL_PREFIX))


def social_networks(session, group_id) -> list[SocialNetwork]:
    """The workspace's enabled integrations that offer any ``social.*`` capability, by slug."""
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.services.integrations import INTEGRATIONS_AVAILABLE, get_provider

    if not INTEGRATIONS_AVAILABLE:
        return []
    out = []
    for row in session.query(IntegrationModel).filter_by(group_id=group_id, enabled=True).order_by(IntegrationModel.slug):
        try:
            provider = get_provider(row.provider)
        except KeyError:
            continue
        if caps := capabilities_of(provider):
            out.append(SocialNetwork(row, provider, caps))
    return out


# ── the per-network auto-reply mode ──────────────────────────────────────────────────────────────────────────────


def get_mode(row) -> str:
    """The integration's auto-reply mode (``off`` when never set, or set to something unknown)."""
    state = (row.state or {}).get(STATE_KEY)
    mode = state.get("auto_reply") if isinstance(state, dict) else None
    return mode if mode in AUTO_REPLY_MODES else OFF


def set_mode(session, row, mode: str) -> None:
    """Store the mode on the integration (committed)."""
    if mode not in AUTO_REPLY_MODES:
        raise ValueError(f"auto-reply is one of {', '.join(AUTO_REPLY_MODES)}")
    state = dict(row.state or {})
    social = dict(state.get(STATE_KEY) or {})
    social["auto_reply"] = mode
    row.state = {**state, STATE_KEY: social}
    session.commit()


def map_legacy_rehearsal(session, group_id, task) -> bool:
    """A task that still has the old task-wide ``rehearsal`` setting: carry it onto every network that has no mode yet
    (``rehearsal: false`` → ``on``, anything else → ``rehearsal``), then drop the setting so it is mapped once and a network
    connected later starts ``off``. True when there was something to map."""
    config = dict(task.task_config or {})
    if "rehearsal" not in config:
        return False
    flag = config.pop("rehearsal")
    mode = ON if flag is False or str(flag).lower() in ("false", "0", "no", "off") else REHEARSAL
    for net in social_networks(session, group_id):
        social = (net.row.state or {}).get(STATE_KEY)
        if not (isinstance(social, dict) and social.get("auto_reply") in AUTO_REPLY_MODES):
            set_mode(session, net.row, mode)
    task.task_config = config
    session.commit()
    return True


# ── the rule type and the task ───────────────────────────────────────────────────────────────────────────────────


def ensure_rule_type(session, group_id):
    """The workspace's ``social-auto-reply`` entry type, created when it is missing (committed). Returns its id."""
    from marvin.db.models.platform.entry_types import EntryTypes

    found = session.query(EntryTypes).filter_by(group_id=group_id, slug=RULE_TYPE).first()
    if found is not None:
        _add_missing_fields(session, found)
        return found.id
    created = EntryTypes(session=session, group_id=group_id, slug=RULE_TYPE, **RULE_TYPE_PAYLOAD)
    session.add(created)
    session.commit()
    logger.info("social: created the %s entry type for workspace %s", RULE_TYPE, group_id)
    return created.id


def _add_missing_fields(session, entry_type) -> None:
    """A rule type made before a field existed (the cool-down) gains it, after the fields it has; nothing it has changes."""
    schema = dict(entry_type.schema_json or {})
    fields = list(schema.get("fields") or [])
    have = {f.get("key") for f in fields if isinstance(f, dict)}
    missing = [f for f in _RULE_FIELDS if f["key"] not in have]
    if missing:
        entry_type.schema_json = {**schema, "fields": fields + [dict(f) for f in missing]}
        session.commit()


def engine_task(session, group_id):
    """The workspace's engine task (the oldest of its type), or None."""
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    return session.query(ScheduledTaskModel).filter_by(group_id=group_id, task_type=TASK_TYPE).order_by(ScheduledTaskModel.created_at).first()


def reconcile(session, group_id) -> dict:
    """Make the workspace's plumbing match its networks (see the module docstring): the rule type once any network offers a
    ``social.*`` capability, and the engine task enabled while one offers ``social.comments``, disabled when none does.
    Idempotent; committed. Returns ``{networks, reading, task}`` (``task``: created | enabled | disabled | none | unchanged)."""
    networks = social_networks(session, group_id)
    reading = [n for n in networks if n.reads_comments]
    if networks:
        ensure_rule_type(session, group_id)
    task = engine_task(session, group_id)
    outcome = "unchanged"
    if reading:
        if task is None:
            _create_task(session, group_id)
            outcome = "created"
        elif not task.enabled:
            task.enabled = True
            if task.next_run_at is None:
                from datetime import UTC, datetime

                task.next_run_at = datetime.now(UTC)
            session.commit()
            outcome = "enabled"
    elif task is not None and task.enabled:
        task.enabled = False
        session.commit()
        outcome = "disabled"
    elif task is None:
        outcome = "none"
    return {"networks": len(networks), "reading": len(reading), "task": outcome}


def _create_task(session, group_id) -> None:
    from marvin.repos.repository_factory import AllRepositories
    from marvin.schemas.platform.scheduled_tasks import ScheduledTaskCreate

    AllRepositories(session, group_id=group_id).scheduled_tasks.create(
        ScheduledTaskCreate(
            name="Social engagement",
            slug=TASK_SLUG,
            description=(
                "Made and switched on by Marvin while a connected network reads comments: fills the Social inbox, announces each new "
                "comment to workflows (social_comment_received) and sends the auto-replies of the networks switched on."
            ),
            enabled=True,
            schedule_type="interval",
            schedule_config={"interval_seconds": ENGINE_INTERVAL_SECONDS},
            task_type=TASK_TYPE,
            task_config={"max_replies": 20, "max_age_days": 7, "limit": 50},
        )
    )
    session.commit()
    logger.info("social: created the engagement task for workspace %s", group_id)


def reconcile_all(session) -> dict:
    """``reconcile`` for every workspace that has an integration or an engine task (the hourly system task). One workspace
    failing never stops the rest."""
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    done = {"workspaces": 0, "created": 0, "enabled": 0, "disabled": 0, "failed": 0}
    with_tasks = session.query(ScheduledTaskModel.group_id).filter(ScheduledTaskModel.task_type == TASK_TYPE, ScheduledTaskModel.group_id.isnot(None))
    group_ids = {r[0] for r in session.query(IntegrationModel.group_id).distinct()} | {r[0] for r in with_tasks.distinct()}
    for gid in group_ids:
        try:
            outcome = reconcile(session, gid)["task"]
        except Exception as e:  # noqa: BLE001
            session.rollback()
            done["failed"] += 1
            logger.warning("social: reconcile failed for workspace %s: %s", gid, e)
            continue
        done["workspaces"] += 1
        if outcome in done:
            done[outcome] += 1
    return done


def summary(session, group_id) -> dict:
    """What the sidebar and the Social pages need: ``show`` (an enabled integration offers a ``social.*`` capability — Social is
    hidden otherwise), the ``new`` inbox count and each such integration with its auto-reply mode and new count."""
    from . import social_inbox

    counts = social_inbox.new_counts(session, group_id)
    nets = social_networks(session, group_id)
    return {
        "show": bool(nets),
        "new": sum(counts.get(n.row.slug, 0) for n in nets),
        "integrations": [
            {
                "slug": n.row.slug,
                "name": n.row.name,
                "provider": n.row.provider,
                "network": n.row.provider,
                "capabilities": sorted(n.capabilities),
                "reads_comments": n.reads_comments,
                "can_reply": n.can_reply,
                "auto_reply": get_mode(n.row),
                "new": counts.get(n.row.slug, 0),
            }
            for n in nets
        ],
    }
