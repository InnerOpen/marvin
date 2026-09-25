"""
Workspace Blueprints API.

The catalog of structure a workspace *could* have — collections, entry types and scheduled tasks
that core ships and installed providers contribute — plus applying one to this workspace.

Reads are catalog + this workspace's state against it (`applied`, `available`). Applying creates
what is missing and never overwrites what exists, so a repeat call is a no-op rather than a
surprise: the response says what happened for each blueprint.
"""

from fastapi import APIRouter, HTTPException, Query, status

from marvin.core.root_logger import get_logger
from marvin.routes._base import BaseUserController, controller
from marvin.schemas.platform.blueprints import BlueprintApplyResult, BlueprintRead
from marvin.services.blueprints import (
    already_applied,
    apply_blueprint,
    apply_many,
    categories,
    get_blueprint,
    list_blueprints,
    missing_requirements,
)

router = APIRouter(prefix="/groups/blueprints")
logger = get_logger(__name__)


@controller(router)
class BlueprintsController(BaseUserController):
    """Browse the blueprint catalog and apply blueprints to the active workspace."""

    def _to_read(self, blueprint) -> BlueprintRead:
        missing = missing_requirements(self.session, self.group_id, blueprint)
        return BlueprintRead(
            **blueprint.model_dump(),
            available=not missing,
            missing_requirements=missing,
            applied=already_applied(self.session, self.group_id, blueprint),
        )

    @router.get("", response_model=list[BlueprintRead])
    def list_catalog(
        self,
        kind: str | None = Query(None, description="collection | entry_type | scheduled_task"),
        category: str | None = Query(None),
        source: str | None = Query(None, description="'core', or a provider slug"),
    ):
        """The catalog, annotated with what this workspace can do about each entry."""
        return [self._to_read(b) for b in list_blueprints(kind=kind, category=category, source=source)]

    @router.get("/categories", response_model=list[str])
    def list_categories(self):
        """Category names in catalog order — core's first, then each provider's."""
        return categories()

    @router.get("/{slug}", response_model=BlueprintRead)
    def get_one(self, slug: str, source: str | None = Query(None)):
        """One blueprint, including the payload — this is what a prefilled editor reads."""
        blueprint = get_blueprint(slug, source=source)
        if blueprint is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No blueprint '{slug}'.")
        return self._to_read(blueprint)

    @router.post("/{slug}/apply", response_model=BlueprintApplyResult)
    def apply_one(self, slug: str, source: str | None = Query(None)):
        """Create this blueprint's object in the active workspace, if it isn't there already."""
        blueprint = get_blueprint(slug, source=source)
        if blueprint is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No blueprint '{slug}'.")

        result = apply_blueprint(self.session, self.group_id, blueprint)
        self.session.commit()
        logger.info("Blueprint '%s' applied to %s: created=%s", slug, self.group_id, result.created)
        return result

    @router.post("/apply", response_model=list[BlueprintApplyResult])
    def apply_several(self, slugs: list[str], source: str | None = Query(None)):
        """Apply several at once — what an integration install offers. Entry types are created
        before the collections and tasks that reference them, whatever order they arrive in."""
        blueprints = []
        for slug in slugs:
            blueprint = get_blueprint(slug, source=source)
            if blueprint is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No blueprint '{slug}'.")
            blueprints.append(blueprint)

        results = apply_many(self.session, self.group_id, blueprints)
        self.session.commit()
        return results
