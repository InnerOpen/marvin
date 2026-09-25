"""Applying a blueprint to a workspace.

The contract, which every consumer relies on: **create what is missing, never overwrite what
exists.** A workspace may have customised its copy of a blueprint's object, and a blueprint is a
starting point rather than a template the workspace is held to. Applying twice is therefore safe,
and so is applying a newer provider's blueprint over an older install.

Nothing here commits — the caller owns the transaction, as with the smart-collection helpers.
"""

import re

from marvin.core.root_logger import get_logger
from marvin.schemas.platform.blueprints import Blueprint, BlueprintApplyResult

logger = get_logger(__name__)

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class BlueprintParameterError(ValueError):
    """A parameter is missing, or names content this workspace does not have."""


def resolve_parameters(session, group_id, blueprint: Blueprint, params: dict | None) -> dict:
    """Validate supplied parameters and fill in defaults.

    A picker parameter (`entry_type`, `collection`) is checked against the workspace, so a
    blueprint can reference the user's own content without the catalog ever naming it.
    """
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.entry_types import EntryTypes

    supplied = dict(params or {})
    resolved: dict = {}
    models = {"entry_type": EntryTypes, "collection": Collections}

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


def already_applied(session, group_id, blueprint: Blueprint, params: dict | None = None) -> bool:
    """True when this workspace already has an object with the blueprint's (resolved) slug.

    Always False for a parameterised blueprint with no parameters supplied — its slug isn't known
    until they are.
    """
    if blueprint.parameters and not params:
        return False
    try:
        slug = substitute(blueprint.slug, resolve_parameters(session, group_id, blueprint, params))
    except BlueprintParameterError:
        return False
    return _existing(session, group_id, blueprint.kind, slug) is not None


def apply_blueprint(session, group_id, blueprint: Blueprint, params: dict | None = None) -> BlueprintApplyResult:
    """Create the blueprint's object in this workspace, unless something already has that slug."""
    result = BlueprintApplyResult(slug=blueprint.slug, kind=blueprint.kind, created=False)

    try:
        resolved = resolve_parameters(session, group_id, blueprint, params)
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

    if _existing(session, group_id, blueprint.kind, slug) is not None:
        result.detail = f"a {blueprint.kind.replace('_', ' ')} with slug '{slug}' already exists — left as it is"
        return result

    _create(session, group_id, blueprint, resolved, slug, name)
    result.created = True
    logger.info("Blueprint applied: %s '%s' (%s)", blueprint.kind, slug, blueprint.source)
    return result


def apply_many(session, group_id, blueprints, params: dict | None = None) -> list[BlueprintApplyResult]:
    """Apply several, in order. Entry types first so collections/tasks that reference them fit.

    `params` is keyed by blueprint slug: {"<slug>": {"entry_type": "..."}}.
    """
    order = {"entry_type": 0, "collection": 1, "scheduled_task": 2}
    by_slug = params or {}
    return [apply_blueprint(session, group_id, b, by_slug.get(b.slug)) for b in sorted(blueprints, key=lambda b: order.get(b.kind, 99))]


# --- per-kind plumbing ---------------------------------------------------------------------------


def _models():
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.entry_types import EntryTypes
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    return {"entry_type": EntryTypes, "collection": Collections, "scheduled_task": ScheduledTaskModel}


def _existing(session, group_id, kind: str, slug: str):
    model = _models().get(kind)
    if model is None:
        return None
    return session.query(model).filter_by(group_id=group_id, slug=slug).first()


def _create(session, group_id, blueprint: Blueprint, params: dict, slug: str, name: str) -> None:
    payload = {**substitute(blueprint.payload, params), "slug": slug}
    payload.setdefault("name", name)

    if blueprint.kind == "scheduled_task":
        # Through the repository: it computes next_run_at, which a raw insert would leave null and
        # the scheduler would then never pick the task up.
        from marvin.repos.repository_factory import AllRepositories
        from marvin.schemas.platform.scheduled_tasks import ScheduledTaskCreate

        AllRepositories(session, group_id=group_id).scheduled_tasks.create(ScheduledTaskCreate(**payload))
        return

    if blueprint.kind == "collection":
        from marvin.db.models.platform.collections import Collections
        from marvin.services.collections.smart_collections import sync_collection

        collection = Collections(session=session, group_id=group_id, **payload)
        session.add(collection)
        session.flush()
        # Materialize membership now: a smart collection that sits empty until the next entry
        # event would look broken to whoever just created it.
        sync_collection(session, group_id, collection)
        return

    from marvin.db.models.platform.entry_types import EntryTypes

    session.add(EntryTypes(session=session, group_id=group_id, **payload))
    # Flush so the next blueprint in an apply_many run can see it: a collection that `requires`
    # this entry type checks the database, and an unflushed row would read as missing.
    session.flush()
