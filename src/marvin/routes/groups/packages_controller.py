"""
Workspace Packages API.

A package is a named, versioned bundle of blueprints (entry types, workflows, collections...) that a workspace installs, uploads, builds from
its own content, downloads and removes. Installing follows the blueprints' rules: create what is missing, never overwrite, and everything that
acts when on starts disabled; switching a package's workflows on is a separate, deliberate call. All of it changes workspace structure, so
all of it is for owners and admins.
"""

import json

from fastapi import APIRouter, Body, HTTPException, Query, Response, status

from marvin.core.root_logger import get_logger
from marvin.routes._base import BaseUserController, controller
from marvin.schemas.platform.packages import PackageEnableResult, PackageExportRequest, PackageRead, PackageResult
from marvin.services.blueprints import packages as service
from marvin.services.blueprints.packages import PackageError

router = APIRouter(prefix="/groups/packages")
logger = get_logger(__name__)


def _as_json(manifest) -> dict:
    return manifest.model_dump(mode="json", by_alias=True)


@controller(router)
class PackagesController(BaseUserController):
    """Install, upload, download, group and remove packages in the active workspace."""

    def _manage(self) -> None:
        self.checks.can_manage_settings(self.group_id)

    def _manifest(self, body: dict):
        try:
            return service.parse_manifest(body)
        except PackageError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    @router.get("", response_model=list[PackageRead])
    def list_packages(self):
        """The packages installed here, with how many of each kind they hold."""
        self._manage()
        return service.list_packages(self.session, self.group_id)

    @router.post("/preview", response_model=PackageResult)
    def preview(self, body: dict = Body(..., description="The package file's JSON")):
        """What installing this package would do, item by item. Changes nothing."""
        self._manage()
        return service.preview(self.session, self.group_id, self._manifest(body), actor_id=self.user.id)

    @router.post("/install", response_model=PackageResult)
    def install(self, body: dict = Body(..., description="The package file's JSON")):
        """Install it: create what is missing (disabled), group it under the package, keep the manifest. Re-installing adds what is missing."""
        self._manage()
        try:
            result = service.install(self.session, self.group_id, self._manifest(body), actor_id=self.user.id, event_bus=self.event_bus)
        except PackageError as e:
            self.session.rollback()
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        self.session.commit()
        return result

    @router.post("/update/preview", response_model=PackageResult)
    def update_preview(
        self,
        body: dict = Body(..., description="The package file's JSON, a newer version of one already installed"),
        replace_edits: bool = Query(False, description="Count a workflow or Playbook changed in this workspace as one to replace"),
    ):
        """What updating this package would do, item by item: what is missing would be made, what is here would be brought up to this file.
        Changes nothing."""
        self._manage()
        try:
            return service.update(
                self.session, self.group_id, self._manifest(body), replace_edits=replace_edits, preview_only=True, actor_id=self.user.id
            )
        except PackageError as e:
            self.session.rollback()
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    @router.post("/update", response_model=PackageResult)
    def update(
        self,
        body: dict = Body(..., description="The package file's JSON, a newer version of one already installed"),
        replace_edits: bool = Query(False, description="Go ahead although a workflow or Playbook was changed in this workspace"),
    ):
        """Bring the installed package up to this file: create what is missing (disabled), replace the steps of the workflows and the text of the
        Playbooks it installed (one changed here is left unless `replace_edits`), and add the fields and lookups its entry types lack.
        Nothing is removed."""
        self._manage()
        try:
            result = service.update(
                self.session, self.group_id, self._manifest(body), replace_edits=replace_edits, actor_id=self.user.id, event_bus=self.event_bus
            )
        except PackageError as e:
            self.session.rollback()
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        self.session.commit()
        return result

    @router.post("/export")
    def export(self, request: PackageExportRequest):
        """Bundle chosen workflows, entry types and collections of this workspace into a package file (returned as JSON). With `adopt`, also
        group them into the package here, so they collapse together on the Workflows page."""
        self._manage()
        try:
            manifest = service.export(self.session, self.group_id, request, actor_id=self.user.id)
        except PackageError as e:
            self.session.rollback()
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        self.session.commit()
        return _as_json(manifest)

    @router.get("/{slug}/download")
    def download(self, slug: str):
        """The package as the file it was installed from (or built as), ready to upload into another workspace."""
        self._manage()
        try:
            manifest = service.manifest_of(self.session, self.group_id, slug)
        except LookupError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
        return Response(
            content=json.dumps(_as_json(manifest), indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{slug}.marvin-package.json"'},
        )

    @router.post("/{slug}/enable", response_model=PackageEnableResult)
    def enable(self, slug: str):
        """Switch on the package's workflows. The deliberate step after an install: they run with the privileges of whoever installed them."""
        self._manage()
        try:
            return service.enable(self.session, self.group_id, slug, actor_id=self.user.id, event_bus=self.event_bus)
        except LookupError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
        except PackageError as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e

    @router.delete("/{slug}")
    def remove(self, slug: str):
        """Ungroup the package: what it created stays exactly as it is, in no package."""
        self._manage()
        try:
            ungrouped = service.remove(self.session, self.group_id, slug)
        except LookupError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
        self.session.commit()
        return {"ungrouped": ungrouped}
