"""
Integration task handler: run a provider action on a schedule.

Nothing in core polls a provider on its own — actions run on demand (the test-fire endpoint) or on
an event (subscriptions). This handler is the third path: a scheduled task that calls one action of
one workspace integration, feeds it entries as arguments, and persists whatever records the action
returns as entries. The provider stays pure (config + secret + http in, dicts out); the workspace's
content is the state.

Deliberately NOT on AUTOMATION_ALLOWED_HANDLERS: an action may have side effects (send a DM), so it
runs only as a scheduled task an admin created, never from an automation.
"""

from collections import defaultdict

from marvin.core.root_logger import get_logger
from marvin.db.db_setup import session_context
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.services.event_bus_service.event_bus_service import EventBusService

from . import ScheduledTaskHandler, TaskHandlerRegistry

logger = get_logger(__name__)

DEFAULT_SLUG_FIELD = "comment_id"
DEFAULT_RECORD_STATUS = "draft"
INTEGRATION_SOURCE_TAG = "scheduled_tasks"


class RunIntegrationActionHandler(ScheduledTaskHandler):
    """
    Call one provider action for one workspace integration, on a schedule.

    Configuration (task_config):
    - integration: str — the integration's per-workspace slug
    - action: str — the provider action key
    - args: dict — static arguments passed to the action
    - inputs: {arg_name: {entry_type, status?, as: "records" | "field", field?}} — entries loaded
      into the arguments: "records" passes each entry's data_json (+ slug, title), "field" passes
      a list of one data_json field's values
    - outputs: {records_entry_type, slug_prefix?, slug_field?, title_template?, status?} — how the
      action's returned `records` become entries; a record whose slug already exists is skipped
      (that is the dedupe), and `secret_update` in the result rotates the integration's credential
    """

    name = "Run Integration Action"
    description = "Call a provider action on a schedule; feed it entries, persist returned records as entries"
    config_schema = {
        "type": "object",
        "required": ["integration", "action"],
        "properties": {
            "integration": {"type": "string", "description": "Integration slug in this workspace"},
            "action": {"type": "string", "description": "Provider action key"},
            "args": {"type": "object", "description": "Static arguments for the action"},
            "inputs": {
                "type": "object",
                "description": "Argument name → {entry_type, status?, as: 'records'|'field', field?}; entries loaded into the arguments",
            },
            "outputs": {
                "type": "object",
                "description": "{records_entry_type, slug_prefix?, slug_field?, title_template?, status?}; how returned records become entries",
            },
        },
    }

    def execute(self, task: ScheduledTaskModel, event_bus: EventBusService) -> str | None:
        if not task.group_id:
            return "Skipped: run_integration_action needs a workspace (integrations are per-workspace)"

        from marvin.services.integrations import INTEGRATIONS_AVAILABLE

        if not INTEGRATIONS_AVAILABLE:
            return "Skipped: integrations SDK not installed"

        # Imported here so this module loads without the SDK (integrations are optional).
        from marvin.db.models.groups.integrations import IntegrationModel
        from marvin.services.integrations import IntegrationContext, build_http, get_provider
        from marvin.services.secrets.resolver import resolve_secret

        cfg = task.task_config or {}
        slug, action = cfg.get("integration"), cfg.get("action")
        if not slug or not action:
            return "Skipped: task_config needs 'integration' and 'action'"
        gid = task.group_id

        with session_context() as session:
            row = session.query(IntegrationModel).filter_by(group_id=gid, slug=slug).first()
            if row is None:
                return f"Skipped: integration '{slug}' not found in this workspace"
            if not row.enabled:
                return f"Skipped: integration '{slug}' is disabled"
            try:
                provider = get_provider(row.provider)
            except KeyError:
                return f"Skipped: provider '{row.provider}' is not installed"

            secret = resolve_secret(row.secret_ref, gid) if row.secret_ref else None
            ctx = IntegrationContext(config=row.config or {}, secret=secret, logger=logger, http=build_http())

            args = dict(cfg.get("args") or {})
            for arg_name, spec in (cfg.get("inputs") or {}).items():
                args[arg_name] = _load_input(session, gid, spec)

            # A ValueError from the provider propagates: the scheduler logs a failed execution
            # with the message, which is exactly what an operator wants to see.
            result = provider.run_action(action, args, ctx) or {}

            created = _persist_records(session, gid, cfg.get("outputs") or {}, result.get("records") or [])
            if result.get("secret_update"):
                _rotate_secret(session, row, gid, result["secret_update"])

        summary = _summary(slug, action, result, created)
        logger.info("Integration action: %s", summary)
        # Quiet on a routine nothing-happened run: polling every couple of minutes, most runs find
        # no new work, and logging each one drowns the runs that mattered. None means "not worth a
        # row" — the listener still logs it when a person triggered the run by hand.
        if not _worth_logging(result, created):
            return None
        return summary


def _load_input(session, gid, spec: dict) -> list:
    """Entries → action argument. Same query vocabulary as the automation selector.

    Ordered oldest-first, deliberately. A provider that treats its input as a priority list — the
    Instagram matcher takes the first rule whose keyword hits — would otherwise get whatever order
    the database happened to return, so a comment matching two rules could get a different reply on
    different runs. Oldest-first makes it explicable: the rule you wrote first wins.
    """
    from marvin.db.models.platform.entries import Entries
    from marvin.services.automation.selector import _entries_query

    q = _entries_query(session, gid, {"entry_type": spec.get("entry_type"), "status": spec.get("status")})
    q = q.order_by(Entries.created_at.asc(), Entries.id.asc())
    mode = spec.get("as") or "records"
    if mode == "field":
        field = spec.get("field") or DEFAULT_SLUG_FIELD
        return [e.data_json.get(field) for e in q if (e.data_json or {}).get(field)]
    return [{**(e.data_json or {}), "slug": e.slug, "title": e.title} for e in q]


def _persist_records(session, gid, outputs: dict, records: list[dict]) -> int:
    """Store each returned record as an entry, keyed by slug. Existing slugs are skipped, not
    suffixed — the repo would auto-suffix on collision, and a duplicate log entry would defeat the
    dedupe the log exists for."""
    entry_type_slug = outputs.get("records_entry_type")
    if not records or not entry_type_slug:
        return 0

    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_types import EntryTypes
    from marvin.services.entries.entry_service import EntryService

    entry_type = session.query(EntryTypes).filter_by(group_id=gid, slug=entry_type_slug).first()
    if entry_type is None:
        raise ValueError(f"outputs.records_entry_type '{entry_type_slug}' does not exist in this workspace")

    prefix = outputs.get("slug_prefix") or ""
    slug_field = outputs.get("slug_field") or DEFAULT_SLUG_FIELD
    title_template = outputs.get("title_template") or "{slug}"
    status = outputs.get("status") or DEFAULT_RECORD_STATUS
    service = EntryService(session, gid, integration_id=INTEGRATION_SOURCE_TAG)

    created = 0
    for record in records:
        key = record.get(slug_field)
        if not key:
            logger.warning("Integration record without '%s' skipped: %s", slug_field, list(record))
            continue
        slug = f"{prefix}{key}"
        if session.query(Entries.id).filter_by(group_id=gid, slug=slug).first():
            continue
        title = title_template.format_map(defaultdict(str, {**record, "slug": slug}))
        service.create({"entry_type_id": entry_type.id, "title": title, "slug": slug, "status": status, "data_json": record})
        created += 1
    return created


def _rotate_secret(session, row, gid, value: str) -> None:
    """Write a provider-issued replacement credential (e.g. a refreshed token). Never logged."""
    from marvin.services.secrets import get_secret_backend

    ref = row.secret_ref or f"INTEGRATION_{row.slug.upper()}"
    get_secret_backend().set(ref, value, gid)
    row.secret_ref = ref
    session.commit()
    logger.info("Integration '%s': credential rotated by provider", row.slug)


def _worth_logging(result: dict, created: int) -> bool:
    """Did this run actually do anything? Sends, new records, failures and rotations all count."""
    if created or result.get("secret_update"):
        return True
    if result.get("sent") or result.get("matched"):
        return True
    if any("failed" in str(s.get("reason", "")) for s in (result.get("skipped") or [])):
        return True
    # A dry run that found matches is interesting; one that found nothing is not.
    return bool(result.get("would_send"))


def _summary(slug: str, action: str, result: dict, created: int) -> str:
    counts = " ".join(f"{k}={result[k]}" for k in ("checked", "matched", "sent") if k in result)
    if isinstance(result.get("skipped"), list):
        counts += f" skipped={len(result['skipped'])}"
    if result.get("dry_run"):
        counts += " (dry run)"
    entries = f" → {created} log entr{'y' if created == 1 else 'ies'}"
    rotated = " · credential rotated" if result.get("secret_update") else ""
    return f"{slug}.{action}: {counts.strip() or 'ok'}{entries}{rotated}"


TaskHandlerRegistry.register("run_integration_action", RunIntegrationActionHandler)
