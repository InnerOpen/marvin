"""Applying a blueprint to a workspace.

The contract, which every consumer relies on: **create what is missing, never overwrite what
exists.** A workspace may have customised its copy of a blueprint's object, and a blueprint is a
starting point rather than a template the workspace is held to. Applying twice is therefore safe,
and so is applying a newer provider's blueprint over an older install.

Nothing here commits — the caller owns the transaction, as with the smart-collection helpers.
"""

import re

from marvin.core.root_logger import get_logger
from marvin.schemas.platform.blueprints import (
    ACTS_WHEN_ENABLED_KINDS,
    PER_INTEGRATION_KINDS,
    Blueprint,
    BlueprintApplyResult,
)

logger = get_logger(__name__)

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class BlueprintParameterError(ValueError):
    """A parameter is missing, or names content this workspace does not have."""


def resolve_integration_id(session, group_id, blueprint: Blueprint, integration_id=None):
    """Which integration instance a per-connection blueprint wires up.

    The card that offers the blueprint knows its own integration and passes it. Falling back to
    "the one integration of this provider" is a convenience, not a guess: with two connections of
    the same provider there is no right answer, so it refuses rather than picking one.
    """
    if blueprint.kind not in PER_INTEGRATION_KINDS:
        return None
    if integration_id:
        return integration_id

    from marvin.db.models.groups.integrations import IntegrationModel

    rows = session.query(IntegrationModel).filter_by(group_id=group_id, provider=blueprint.source).all()
    if len(rows) == 1:
        return rows[0].id
    if not rows:
        raise BlueprintParameterError(f"no '{blueprint.source}' integration in this workspace to connect")
    raise BlueprintParameterError(f"this workspace has {len(rows)} '{blueprint.source}' integrations — say which one")


def resolve_parameters(session, group_id, blueprint: Blueprint, params: dict | None) -> dict:
    """Validate supplied parameters and fill in defaults.

    A picker parameter (`entry_type`, `collection`, `integration`) is checked against the workspace,
    so a blueprint can reference the user's own content — or connection — without naming it.
    """
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.entry_types import EntryTypes

    supplied = dict(params or {})
    resolved: dict = {}
    models = {"entry_type": EntryTypes, "collection": Collections, "integration": IntegrationModel}

    for parameter in blueprint.parameters:
        value = supplied.get(parameter.key, parameter.default)
        if value in (None, ""):
            if parameter.required:
                raise BlueprintParameterError(f"'{parameter.key}' is required ({parameter.label})")
            continue
        value = str(value).strip()
        model = models.get(parameter.kind)
        if model is not None and not session.query(model.id).filter_by(group_id=group_id, slug=value).first():
            raise BlueprintParameterError(f"no {parameter.kind.replace('_', ' ')} '{value}' in this workspace")
        resolved[parameter.key] = value

    return resolved


def substitute(value, params: dict):
    """Replace `{{key}}` throughout a string / list / dict, leaving other types alone.

    A lone `{{key}}` becomes the value itself rather than a string, so a parameter can fill a list
    element or a non-string field without stringifying it.
    """
    if isinstance(value, str):
        whole = _PLACEHOLDER.fullmatch(value.strip())
        if whole and whole.group(1) in params:
            return params[whole.group(1)]
        return _PLACEHOLDER.sub(lambda m: str(params.get(m.group(1), m.group(0))), value)
    if isinstance(value, list):
        return [substitute(v, params) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, params) for k, v in value.items()}
    return value


def missing_requirements(session, group_id, blueprint: Blueprint) -> list[str]:
    """Which of `blueprint.requires` this workspace does not satisfy."""
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.entry_types import EntryTypes

    models = {"entry_type": EntryTypes, "collection": Collections}
    missing = []
    for requirement in blueprint.requires:
        kind, _, slug = requirement.partition(":")
        model = models.get(kind)
        if model is None:
            continue
        if not session.query(model.id).filter_by(group_id=group_id, slug=slug).first():
            missing.append(requirement)
    return missing


def already_applied(session, group_id, blueprint: Blueprint, params: dict | None = None, integration_id=None) -> bool:
    """True when this workspace already has an object with the blueprint's (resolved) slug.

    A parameterised blueprint checked without parameters is judged by its defaults — the values an
    integration's card applies when nobody changes them. One with a parameter that has no default
    can't be judged blind, so it reads as not applied.
    """
    if blueprint.parameters and not params:
        if any(p.default in (None, "") for p in blueprint.parameters if p.required):
            return False
        params = {p.key: p.default for p in blueprint.parameters if p.default not in (None, "")}
    try:
        resolved = resolve_parameters(session, group_id, blueprint, params)
        target = resolve_integration_id(session, group_id, blueprint, integration_id)
    except BlueprintParameterError:
        return False
    slug = substitute(blueprint.slug, resolved)
    return _existing(session, group_id, blueprint, slug, target, resolved) is not None


def apply_blueprint(session, group_id, blueprint: Blueprint, params: dict | None = None, integration_id=None, actor_id=None) -> BlueprintApplyResult:
    """Create the blueprint's object in this workspace, unless it is already there.

    `actor_id` is who applied it — recorded as a workflow's author, since a workflow runs with its
    author's privileges."""
    result = BlueprintApplyResult(slug=blueprint.slug, kind=blueprint.kind, created=False)

    try:
        resolved = resolve_parameters(session, group_id, blueprint, params)
        target = resolve_integration_id(session, group_id, blueprint, integration_id)
    except BlueprintParameterError as e:
        result.detail = str(e)
        return result

    slug = substitute(blueprint.slug, resolved)
    name = substitute(blueprint.name, resolved)
    result.slug, result.name = slug, name

    missing = missing_requirements(session, group_id, blueprint)
    if missing:
        result.detail = f"needs {', '.join(missing)}"
        return result

    if _existing(session, group_id, blueprint, slug, target, resolved) is not None:
        noun = blueprint.kind.replace("_", " ")
        if blueprint.kind in PER_INTEGRATION_KINDS:
            where = "already connected"
        elif blueprint.kind == "entry_fields":
            where = "already has every field"
        else:
            where = f"with slug '{slug}' already exists"
        result.detail = f"a {noun} {where} — left as it is"
        return result

    try:
        result.detail = _create(session, group_id, blueprint, resolved, slug, name, target, actor_id) or ""
    except BlueprintParameterError as e:
        result.detail = str(e)
        return result
    result.created = True
    logger.info("Blueprint applied: %s '%s' (%s)", blueprint.kind, slug, blueprint.source)
    return result


def apply_many(session, group_id, blueprints, params: dict | None = None, integration_id=None, actor_id=None) -> list[BlueprintApplyResult]:
    """Apply several, in order. Entry types (and their added fields) first so the collections, tasks
    and workflows that reference them fit; webhooks before the workflows they trigger.

    `params` is keyed by blueprint slug: {"<slug>": {"entry_type": "..."}}.
    """
    order = {"entry_type": 0, "entry_fields": 1, "collection": 2, "scheduled_task": 3, "incoming_webhook": 4, "workflow": 5}
    by_slug = params or {}
    return [
        apply_blueprint(session, group_id, b, by_slug.get(b.slug), actor_id=actor_id) for b in sorted(blueprints, key=lambda b: order.get(b.kind, 99))
    ]


# --- per-kind plumbing ---------------------------------------------------------------------------


def _models():
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.entry_types import EntryTypes
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    return {
        "entry_type": EntryTypes,
        "collection": Collections,
        "scheduled_task": ScheduledTaskModel,
        "incoming_webhook": WorkspaceIncomingWebhookModel,
        "workflow": WorkspaceAutomationModel,
    }


def _existing(session, group_id, blueprint: Blueprint, slug: str, integration_id=None, params: dict | None = None):
    if blueprint.kind == "entry_fields":
        # "Applied" means every declared field is already on the type; a type with only some of
        # them still has work to do.
        entry_type = _fields_target(session, group_id, blueprint, params or {})
        if entry_type is None:
            return None
        return entry_type if not _missing_fields(entry_type, blueprint, params or {}) else None

    if blueprint.kind == "event_subscription":
        # No slug in the database: a connection is identified by what it wires to what.
        from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel

        payload = blueprint.payload or {}
        return (
            session.query(IntegrationEventSubscriptionModel)
            .filter_by(
                group_id=group_id,
                integration_id=integration_id,
                event_type=payload.get("event_type"),
                action=payload.get("action"),
            )
            .first()
        )

    model = _models().get(blueprint.kind)
    if model is None:
        return None
    return session.query(model).filter_by(group_id=group_id, slug=slug).first()


def _create(session, group_id, blueprint: Blueprint, params: dict, slug: str, name: str, integration_id=None, actor_id=None) -> str | None:
    """Create the object. Returns an optional note for the result (what fields were added)."""
    payload = substitute(blueprint.payload, params)

    if blueprint.kind == "entry_fields":
        return _add_fields(session, group_id, blueprint, params)

    if blueprint.kind in ACTS_WHEN_ENABLED_KINDS:
        # Applying gives you the wiring; switching it on is a separate, deliberate act. A
        # subscription or task that started sending the moment it was created would be a nasty
        # surprise on an integration someone was only setting up.
        payload["enabled"] = False

    if blueprint.kind == "event_subscription":
        from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel

        session.add(
            IntegrationEventSubscriptionModel(
                session=session,
                group_id=group_id,
                integration_id=integration_id,
                event_type=payload.get("event_type"),
                action=payload.get("action"),
                args=payload.get("args") or {},
                enabled=False,
            )
        )
        session.flush()
        return

    payload = {**payload, "slug": slug}
    payload.setdefault("name", name)

    if blueprint.kind == "scheduled_task":
        # Through the repository: it computes next_run_at, which a raw insert would leave null and
        # the scheduler would then never pick the task up.
        from marvin.repos.repository_factory import AllRepositories
        from marvin.schemas.platform.scheduled_tasks import ScheduledTaskCreate

        AllRepositories(session, group_id=group_id).scheduled_tasks.create(ScheduledTaskCreate(**payload))
        return

    if blueprint.kind == "incoming_webhook":
        from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel

        # No token: minting one is what opens the endpoint, and that stays an admin's deliberate act.
        allowed = ("name", "description", "signature_scheme", "signature_header", "signing_secret_ref", "signature_url", "signature_config")
        session.add(
            WorkspaceIncomingWebhookModel(
                session=session, group_id=group_id, enabled=False, token=None, slug=slug, **{k: payload[k] for k in allowed if k in payload}
            )
        )
        session.flush()
        return None

    if blueprint.kind == "workflow":
        from marvin.db.models.groups.automations import WorkspaceAutomationModel
        from marvin.services.automation.validation import structural_issues

        definition = payload.get("definition") or {}
        issues = structural_issues(definition)
        if issues:
            raise BlueprintParameterError(f"workflow definition is invalid: {issues}")
        session.add(
            WorkspaceAutomationModel(
                session=session,
                group_id=group_id,
                name=payload["name"],
                slug=slug,
                enabled=False,
                definition=definition,
                created_by=actor_id,
            )
        )
        session.flush()
        return None

    if blueprint.kind == "collection":
        from marvin.db.models.platform.collections import Collections
        from marvin.services.collections.smart_collections import sync_collection

        collection = Collections(session=session, group_id=group_id, **payload)
        session.add(collection)
        session.flush()
        # Materialize membership now: a smart collection that sits empty until the next entry
        # event would look broken to whoever just created it.
        sync_collection(session, group_id, collection)
        return None

    from marvin.db.models.platform.entry_types import EntryTypes

    session.add(EntryTypes(session=session, group_id=group_id, **payload))
    # Flush so the next blueprint in an apply_many run can see it: a collection that `requires`
    # this entry type checks the database, and an unflushed row would read as missing.
    session.flush()
    return None


def _fields_target(session, group_id, blueprint: Blueprint, params: dict):
    """The existing entry type an entry_fields blueprint extends, or None."""
    from marvin.db.models.platform.entry_types import EntryTypes

    slug = substitute((blueprint.payload or {}).get("entry_type"), params)
    if not slug:
        return None
    return session.query(EntryTypes).filter_by(group_id=group_id, slug=str(slug)).first()


def _missing_fields(entry_type, blueprint: Blueprint, params: dict) -> list[dict]:
    present = {f.get("key") for f in ((entry_type.schema_json or {}).get("fields") or [])}
    declared = substitute((blueprint.payload or {}).get("fields") or [], params)
    return [f for f in declared if f.get("key") not in present]


def _add_fields(session, group_id, blueprint: Blueprint, params: dict) -> str:
    """Append the declared fields the type lacks. Existing fields — even ones with a declared key —
    are left exactly as they are: the workspace may have customised them."""
    from sqlalchemy.orm.attributes import flag_modified

    from marvin.schemas.platform.entry_type_schema import EntryTypeSchemaDefinition

    entry_type = _fields_target(session, group_id, blueprint, params)
    if entry_type is None:
        target = substitute((blueprint.payload or {}).get("entry_type"), params)
        raise BlueprintParameterError(f"no entry type '{target}' in this workspace to add fields to")
    missing = _missing_fields(entry_type, blueprint, params)
    schema = dict(entry_type.schema_json or {})
    schema["fields"] = [*(schema.get("fields") or []), *missing]
    try:
        EntryTypeSchemaDefinition.model_validate(schema)
    except Exception as e:  # noqa: BLE001 — surface the schema rule that failed, don't half-apply
        raise BlueprintParameterError(f"the fields don't fit entry type '{entry_type.slug}': {e}") from e
    entry_type.schema_json = schema
    flag_modified(entry_type, "schema_json")
    session.flush()
    return f"added {', '.join(f['key'] for f in missing)} to '{entry_type.slug}'"
