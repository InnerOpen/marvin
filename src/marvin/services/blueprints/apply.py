"""Applying a blueprint to a workspace.

The contract, which every consumer relies on: **create what is missing, never overwrite what
exists.** A workspace may have customised its copy of a blueprint's object, and a blueprint is a
starting point rather than a template the workspace is held to. Applying twice is therefore safe,
and so is applying a newer provider's blueprint over an older install.

Nothing here commits — the caller owns the transaction, as with the smart-collection helpers — except a ``playbook`` blueprint: a
Playbook is an entry with files, and the entry and asset writers commit, so it is applied last and commits (``playbook_apply``).
"""

import re

from marvin.core.root_logger import get_logger
from marvin.schemas.platform.blueprints import (
    ACTS_WHEN_ENABLED_KINDS,
    CORE_SOURCE,
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


def installed_by(session, group_id, blueprint: Blueprint, integration_id=None) -> dict:
    """The "installed by" columns for every row this blueprint creates — the one place they're set.

    ``source_blueprint`` is the blueprint's slug. ``source_integration_id`` is the provider's
    connection in this workspace: the one the card passed (when it is this provider's), else the only
    one of that provider. None for a core blueprint, or when it can't be told — a wrong "installed by"
    is worse than none, since uninstalling may one day act on it.
    """
    source = None
    if blueprint.source != CORE_SOURCE:
        from marvin.db.models.groups.integrations import IntegrationModel

        chosen = session.get(IntegrationModel, integration_id) if integration_id else None
        if chosen is not None and str(chosen.group_id) == str(group_id) and chosen.provider == blueprint.source:
            source = chosen.id
        else:
            rows = session.query(IntegrationModel.id).filter_by(group_id=group_id, provider=blueprint.source).limit(2).all()
            source = rows[0][0] if len(rows) == 1 else None
    return {"source_integration_id": source, "source_blueprint": blueprint.slug}


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
        if parameter.kind == "integration" and parameter.key not in supplied:
            # A provider can only guess its connection's slug ("square"); the workspace named it
            # ("square_integration"). With exactly one connection of that provider, that's the one.
            value = _connection_slug(session, group_id, blueprint.source, value)
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


def _connection_slug(session, group_id, provider: str, default):
    """`default` when the workspace has a connection by that slug; otherwise the slug of its only
    connection of `provider`; otherwise `default` (which validation then refuses with a reason)."""
    from marvin.db.models.groups.integrations import IntegrationModel

    if default and session.query(IntegrationModel.id).filter_by(group_id=group_id, slug=str(default)).first():
        return default
    rows = session.query(IntegrationModel.slug).filter_by(group_id=group_id, provider=provider).limit(2).all()
    return rows[0][0] if len(rows) == 1 else default


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
    integration's card applies when nobody changes them (an `integration` parameter resolves to the
    workspace's own connection). One with a parameter that has no default can't be judged blind, so it
    reads as not applied.
    """
    if blueprint.parameters and not params:
        if any(p.default in (None, "") for p in blueprint.parameters if p.required and p.kind != "integration"):
            return False
        params = None  # resolve_parameters fills the defaults
    try:
        resolved = resolve_parameters(session, group_id, blueprint, params)
        target = resolve_integration_id(session, group_id, blueprint, integration_id)
    except BlueprintParameterError:
        return False
    slug = substitute(blueprint.slug, resolved)
    return _existing(session, group_id, blueprint, slug, target, resolved) is not None


def apply_blueprint(
    session, group_id, blueprint: Blueprint, params: dict | None = None, integration_id=None, actor_id=None, event_bus=None
) -> BlueprintApplyResult:
    """Create the blueprint's object in this workspace, unless it is already there.

    `actor_id` is who applied it — recorded as a workflow's author, since a workflow runs with its
    author's privileges, and as a Playbook's creator. `event_bus` is the request's, for the events a Playbook's entry emits."""
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

    if blueprint.kind == "playbook" and _existing(session, group_id, blueprint, slug) is None:
        from .playbook_apply import blueprint_conflict

        if conflict := blueprint_conflict(session, group_id, blueprint):
            result.detail = conflict
            return result

    if _existing(session, group_id, blueprint, slug, target, resolved) is not None:
        noun = blueprint.kind.replace("_", " ")
        if blueprint.kind in PER_INTEGRATION_KINDS:
            where = "already connected"
        elif blueprint.kind == "entry_fields":
            where = "already has every field and setting"
        else:
            where = f"with slug '{slug}' already exists"
        result.detail = f"a {noun} {where} — left as it is"
        return result

    try:
        provenance = installed_by(session, group_id, blueprint, target or integration_id)
        result.detail = _create(session, group_id, blueprint, resolved, slug, name, target, actor_id, provenance, event_bus) or ""
    except BlueprintParameterError as e:
        result.detail = str(e)
        return result
    result.created = True
    logger.info("Blueprint applied: %s '%s' (%s)", blueprint.kind, slug, blueprint.source)
    return result


def apply_many(
    session, group_id, blueprints, params: dict | None = None, integration_id=None, actor_id=None, event_bus=None
) -> list[BlueprintApplyResult]:
    """Apply several, in order. Entry types (and their added fields) first so the collections, tasks
    and workflows that reference them fit; webhooks before the workflows they trigger; Playbooks last, because
    adding one commits (the one exception to "apply never commits").

    `params` is keyed by blueprint slug: {"<slug>": {"entry_type": "..."}}.
    """
    order = {"entry_type": 0, "entry_fields": 1, "collection": 2, "scheduled_task": 3, "incoming_webhook": 4, "workflow": 5, "playbook": 6}
    by_slug = params or {}
    return [
        apply_blueprint(session, group_id, b, by_slug.get(b.slug), integration_id=integration_id, actor_id=actor_id, event_bus=event_bus)
        for b in sorted(blueprints, key=lambda b: order.get(b.kind, 99))
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
    if blueprint.kind == "playbook":
        # Applied = this provider's Playbook of that name, not in the Trash; any other entry with the name is a conflict.
        from .playbook_apply import applied_row

        return applied_row(session, group_id, blueprint)

    if blueprint.kind == "entry_fields":
        # "Applied" means every declared field is already on the type and every declared submission setting stored;
        # a type with only some of them still has work to do.
        entry_type = _fields_target(session, group_id, blueprint, params or {})
        if entry_type is None:
            return None
        done = not _missing_fields(entry_type, blueprint, params or {}) and not _missing_submission(entry_type, blueprint)
        return entry_type if done else None

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


def _create(
    session,
    group_id,
    blueprint: Blueprint,
    params: dict,
    slug: str,
    name: str,
    integration_id=None,
    actor_id=None,
    provenance: dict | None = None,
    event_bus=None,
) -> str | None:
    """Create the object, stamped with `provenance` (see `installed_by`). Returns an optional note for
    the result (what fields were added)."""
    provenance = provenance or {}

    if blueprint.kind == "playbook":
        from .playbook_apply import create_playbook

        try:
            return create_playbook(session, group_id, blueprint, provenance.get("source_integration_id"), actor_id, event_bus)
        except ValueError as e:
            raise BlueprintParameterError(str(e)) from e

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
                **provenance,
            )
        )
        session.flush()
        return

    payload = {**payload, "slug": slug}
    payload.setdefault("name", name)

    if blueprint.kind == "scheduled_task":
        # Through the repository: it computes next_run_at, which a raw insert would leave null and
        # the scheduler would then never pick the task up.
        from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
        from marvin.repos.repository_factory import AllRepositories
        from marvin.schemas.platform.scheduled_tasks import ScheduledTaskCreate

        created = AllRepositories(session, group_id=group_id).scheduled_tasks.create(ScheduledTaskCreate(**payload))
        task = session.get(ScheduledTaskModel, created.id)
        for column, value in provenance.items():  # not part of the API's create schema
            setattr(task, column, value)
        session.flush()
        return

    if blueprint.kind == "incoming_webhook":
        from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel

        # No token: minting one is what opens the endpoint, and that stays an admin's deliberate act.
        allowed = ("name", "description", "signature_scheme", "signature_header", "signing_secret_ref", "signature_url", "signature_config")
        session.add(
            WorkspaceIncomingWebhookModel(
                session=session,
                group_id=group_id,
                enabled=False,
                token=None,
                slug=slug,
                **{k: payload[k] for k in allowed if k in payload},
                **provenance,
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
                source_definition_hash=definition_hash(definition),
                **provenance,
            )
        )
        session.flush()
        return None

    if blueprint.kind == "collection":
        from marvin.db.models.platform.collections import Collections
        from marvin.services.collections.smart_collections import sync_collection

        collection = Collections(session=session, group_id=group_id, **{**payload, **provenance})
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


def _missing_submission(entry_type, blueprint: Blueprint) -> dict:
    """The declared submission settings (payload.submission: destination and/or kind) the type doesn't store yet. A setting someone
    already stored, even one different from the declared value, is theirs and is left alone. A type that isn't a form stores none, so
    everything declared is missing (and applying it is refused with the reason)."""
    from marvin.services.entry_listing import submission_settings

    declared = (blueprint.payload or {}).get("submission") or {}
    stored = submission_settings(entry_type) or {}
    return {k: v for k, v in declared.items() if k in ("destination", "kind") and k not in stored}


def _set_submission(session, entry_type, settings: dict) -> str:
    """Store the missing submission settings on a form (through the same default the entry type editor applies: choosing a destination
    sets whether the type is listed) and let its entries' derived data follow if that changed."""
    from sqlalchemy.orm.attributes import flag_modified

    from marvin.repos.platform.entry_types import follow_listing
    from marvin.schemas.platform.entry_type_rendering import CapabilitiesDefinition
    from marvin.services.entry_listing import is_listed_type, submission_settings, with_destination_default

    if submission_settings(entry_type) is None:
        raise BlueprintParameterError(f"entry type '{entry_type.slug}' is not a form (submittable), so its submission settings can't be set")
    old = dict(entry_type.capabilities_json or {})
    was_listed = is_listed_type(entry_type)
    new = with_destination_default(old, {**old, "submission": {**(old.get("submission") or {}), **settings}})
    try:
        CapabilitiesDefinition.model_validate(new)
    except Exception as e:  # noqa: BLE001 — surface the rule that failed, don't half-apply
        raise BlueprintParameterError(f"the submission settings don't fit entry type '{entry_type.slug}': {e}") from e
    entry_type.capabilities_json = new
    flag_modified(entry_type, "capabilities_json")
    session.flush()
    if is_listed_type(entry_type) != was_listed:
        follow_listing(session, entry_type, commit=False)
    return f"set {', '.join(f'{k} {v}' for k, v in settings.items())} on '{entry_type.slug}'"


def _add_fields(session, group_id, blueprint: Blueprint, params: dict) -> str:
    """Append the declared fields the type lacks and set the declared submission settings it doesn't store. Existing fields — even
    ones with a declared key — and stored settings are left exactly as they are: the workspace may have customised them."""
    from sqlalchemy.orm.attributes import flag_modified

    from marvin.schemas.platform.entry_type_schema import EntryTypeSchemaDefinition

    entry_type = _fields_target(session, group_id, blueprint, params)
    if entry_type is None:
        target = substitute((blueprint.payload or {}).get("entry_type"), params)
        raise BlueprintParameterError(f"no entry type '{target}' in this workspace to add fields to")
    notes = []
    missing = _missing_fields(entry_type, blueprint, params)
    if missing:
        schema = dict(entry_type.schema_json or {})
        schema["fields"] = [*(schema.get("fields") or []), *missing]
        try:
            EntryTypeSchemaDefinition.model_validate(schema)
        except Exception as e:  # noqa: BLE001 — surface the schema rule that failed, don't half-apply
            raise BlueprintParameterError(f"the fields don't fit entry type '{entry_type.slug}': {e}") from e
        entry_type.schema_json = schema
        flag_modified(entry_type, "schema_json")
        session.flush()
        notes.append(f"added {', '.join(f['key'] for f in missing)} to '{entry_type.slug}'")
    settings = _missing_submission(entry_type, blueprint)
    if settings:
        notes.append(_set_submission(session, entry_type, settings))
    return "; ".join(notes)


# --- updating what an integration declared earlier ------------------------------------------------
#
# Apply never overwrites, so a workspace keeps whatever version of a blueprint it applied. When the
# provider ships a new version, the card offers an explicit Update instead — for workflows, whose
# steps are the provider's logic (a fix there should reach everyone who applied it), and for Playbooks,
# the provider's written know-how (``playbook_apply``).

UPDATABLE_KINDS = ("workflow", "playbook")


def _canonical(value) -> str:
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _declared_and_existing(session, group_id, blueprint: Blueprint, params: dict | None):
    """(resolved declared payload, existing row) — or (None, None) when there is nothing to compare."""
    if blueprint.kind not in UPDATABLE_KINDS:
        return None, None
    try:
        resolved = resolve_parameters(session, group_id, blueprint, params)
    except BlueprintParameterError:
        return None, None
    row = _existing(session, group_id, blueprint, substitute(blueprint.slug, resolved), None, resolved)
    return (substitute(blueprint.payload, resolved), row) if row is not None else (None, None)


def definition_hash(definition) -> str:
    import hashlib

    return hashlib.sha256(_canonical(definition or {}).encode()).hexdigest()


def blueprint_state(row_definition, stored_hash: str | None, declared_definition) -> str:
    """``state_from_hashes`` for a workflow's definition."""
    return state_from_hashes(definition_hash(row_definition), stored_hash, definition_hash(declared_definition))


def state_from_hashes(have: str, stored_hash: str | None, declared: str) -> str:
    """How an applied workflow or Playbook stands against its provider's current version, from the hash of what it is now
    (`have`), of what was installed (`stored_hash`) and of what the provider declares now:

    - `current`: the same steps as the provider declares now.
    - `update`: untouched since install, and the provider has a newer version — safe to update.
    - `edited`: changed in this workspace, the provider has nothing new — nothing to offer.
    - `edited_update`: changed here *and* the provider has a newer version — updating replaces the edits.
    - `differs`: no install hash recorded (installed before it was) — can't tell an edit from an old version.
    """
    if have == declared:
        return "current"
    if not stored_hash:
        return "differs"
    if have == stored_hash:
        return "update"
    return "edited" if declared == stored_hash else "edited_update"


# States in which an Update is worth offering. `edited` has nothing new to take.
UPDATE_STATES = ("update", "edited_update", "differs")
# States where Update would discard changes made here, so it needs `replace_edits`.
REPLACES_EDITS = ("edited", "edited_update", "differs")


def blueprint_state_of(session, group_id, blueprint: Blueprint, params: dict | None = None) -> str | None:
    """`blueprint_state` for this workspace's copy, or None when there is nothing to compare."""
    declared, row = _declared_and_existing(session, group_id, blueprint, params)
    if row is None:
        return None
    if blueprint.kind == "playbook":
        from .playbook_apply import state_of

        return state_of(session, row, blueprint)
    return blueprint_state(row.definition, row.source_definition_hash, declared.get("definition"))


def outdated(session, group_id, blueprint: Blueprint, params: dict | None = None) -> bool:
    """True when an Update is worth offering: the provider declares something this workspace's workflow
    doesn't have, and it isn't an edited copy with nothing new to take (see `blueprint_state`)."""
    return blueprint_state_of(session, group_id, blueprint, params) in UPDATE_STATES


def update_blueprint(
    session,
    group_id,
    blueprint: Blueprint,
    params: dict | None = None,
    replace_edits: bool = False,
    integration_id=None,
    actor_id=None,
    event_bus=None,
) -> BlueprintApplyResult:
    """Replace an applied workflow's steps with the provider's current version. Whether it is
    switched on is kept; the new definition must pass structural validation first.

    A Playbook's update replaces its text and files, keeps its id and status, and commits (see ``playbook_apply``);
    ``integration_id`` rebinds it to that connection (a Playbook whose integration was removed and added again).

    A workflow changed in this workspace (`edited`, `edited_update`) or of unknown history (`differs`)
    is refused unless `replace_edits`: the update would silently discard those changes. `edited` has
    nothing new to take, so even then it is only rewritten when forced — that is how someone returns an
    edited copy to the integration's version."""
    result = BlueprintApplyResult(slug=blueprint.slug, kind=blueprint.kind, created=False)
    if blueprint.kind not in UPDATABLE_KINDS:
        result.detail = f"a {blueprint.kind.replace('_', ' ')} can't be updated from its blueprint"
        return result
    declared, row = _declared_and_existing(session, group_id, blueprint, params)
    if row is None:
        result.detail = "not applied in this workspace — add it instead"
        return result
    if blueprint.kind == "playbook":
        from .playbook_apply import update_playbook

        return update_playbook(session, group_id, blueprint, row, integration_id, actor_id, replace_edits, event_bus)
    definition = declared.get("definition") or {}
    from marvin.services.automation.validation import structural_issues

    issues = structural_issues(definition)
    if issues:
        result.detail = f"the new workflow definition is invalid: {issues}"
        return result
    state = blueprint_state(row.definition, row.source_definition_hash, definition)
    if state == "current":
        result.detail = "already up to date"
        if not row.source_definition_hash:
            row.source_definition_hash = definition_hash(definition)  # it matches the provider's, so it is unedited
            session.flush()
        return result
    if state in REPLACES_EDITS and not replace_edits:
        result.needs_confirmation = True
        result.detail = "This workflow was changed in this workspace; updating replaces those changes."
        return result
    row.definition = definition
    row.source_definition_hash = definition_hash(definition)
    session.flush()
    result.slug, result.name, result.updated = row.slug, row.name, True
    result.detail = "updated to the integration's current version"
    logger.info("Blueprint updated: workflow '%s' (%s)", row.slug, blueprint.source)
    return result
