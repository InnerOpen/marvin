"""Applying a blueprint to a workspace.

The contract, which every consumer relies on: **create what is missing, never overwrite what
exists.** A workspace may have customised its copy of a blueprint's object, and a blueprint is a
starting point rather than a template the workspace is held to. Applying twice is therefore safe,
and so is applying a newer provider's blueprint over an older install.

Nothing here commits — the caller owns the transaction, as with the smart-collection helpers.
"""

from marvin.core.root_logger import get_logger
from marvin.schemas.platform.blueprints import Blueprint, BlueprintApplyResult

logger = get_logger(__name__)


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


def already_applied(session, group_id, blueprint: Blueprint) -> bool:
    """True when this workspace already has an object with the blueprint's slug."""
    return _existing(session, group_id, blueprint) is not None


def apply_blueprint(session, group_id, blueprint: Blueprint) -> BlueprintApplyResult:
    """Create the blueprint's object in this workspace, unless something already has that slug."""
    result = BlueprintApplyResult(slug=blueprint.slug, kind=blueprint.kind, created=False)

    missing = missing_requirements(session, group_id, blueprint)
    if missing:
        result.detail = f"needs {', '.join(missing)}"
        return result

    if _existing(session, group_id, blueprint) is not None:
        result.detail = f"a {blueprint.kind.replace('_', ' ')} with slug '{blueprint.slug}' already exists — left as it is"
        return result

    _create(session, group_id, blueprint)
    result.created = True
    logger.info("Blueprint applied: %s '%s' (%s)", blueprint.kind, blueprint.slug, blueprint.source)
    return result


def apply_many(session, group_id, blueprints) -> list[BlueprintApplyResult]:
    """Apply several, in order. Entry types first so collections/tasks that reference them fit."""
    order = {"entry_type": 0, "collection": 1, "scheduled_task": 2}
    return [apply_blueprint(session, group_id, b) for b in sorted(blueprints, key=lambda b: order.get(b.kind, 99))]


# --- per-kind plumbing ---------------------------------------------------------------------------


def _models():
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.entry_types import EntryTypes
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

    return {"entry_type": EntryTypes, "collection": Collections, "scheduled_task": ScheduledTaskModel}


def _existing(session, group_id, blueprint: Blueprint):
    model = _models().get(blueprint.kind)
    if model is None:
        return None
    return session.query(model).filter_by(group_id=group_id, slug=blueprint.slug).first()


def _create(session, group_id, blueprint: Blueprint) -> None:
    payload = {**blueprint.payload, "slug": blueprint.slug}

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
