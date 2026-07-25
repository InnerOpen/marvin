"""Platform workspace import/export/backup endpoints."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, Query, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from marvin.repos.seed.workspace_exporter import WorkspaceExporter
from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader
from marvin.routes._base import BaseUserController, controller

router = APIRouter(prefix="/workspace")


def _backup_meta(path: Path) -> dict:
    stat = path.stat()
    return {
        "filename": path.name,
        "size": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="seconds"),
    }


@controller(router)
class WorkspaceController(BaseUserController):
    """Workspace import/export/backup routes."""

    @router.get("/export", summary="Export Workspace")
    def export_workspace(self, include_system_types: bool = False) -> Response:
        """Export the current workspace to JSON format.

        The exported JSON can be used as a seed file for workspace restoration
        or migration to another instance.

        Args:
            include_system_types: Whether to include system entry types in export

        Returns:
            JSON response with workspace data
        """
        exporter = WorkspaceExporter(self.repos)
        export_data = exporter.export_workspace(include_system_types=include_system_types)

        return JSONResponse(
            content=export_data,
            headers={
                "Content-Disposition": 'attachment; filename="workspace-export.json"',
            },
        )

    @router.get("/export/pretty", summary="Export Workspace (Pretty)")
    def export_workspace_pretty(self, include_system_types: bool = False) -> Response:
        """Export workspace with pretty-printed JSON.

        Args:
            include_system_types: Whether to include system entry types

        Returns:
            Pretty-printed JSON response
        """
        exporter = WorkspaceExporter(self.repos)
        export_data = exporter.export_workspace(include_system_types=include_system_types)

        pretty_json = json.dumps(export_data, indent=2, ensure_ascii=False)

        return Response(
            content=pretty_json,
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="workspace-export.json"',
            },
        )

    @router.post("/backups", summary="Create Workspace Backup")
    def create_backup(self, include_system_types: bool = False) -> dict:
        """Create a backup bundle and persist it to BACKUP_DIR.

        Returns metadata and a stable download URL for the created file.

        Args:
            include_system_types: Whether to include system entry types

        Returns:
            {filename, size, created_at, download_url}
        """
        exporter = WorkspaceExporter(self.repos)
        zip_path = exporter.export_workspace_bundle(
            include_system_types=include_system_types,
            temp_dir=self.directories.BACKUP_DIR,
        )

        meta = _backup_meta(zip_path)
        meta["download_url"] = f"/api/platform/workspace/backups/{zip_path.name}"
        return meta

    @router.get("/backup-key", summary="Get/Create Workspace Backup Key")
    def get_backup_key(self) -> dict:
        """Return this workspace's backup key, minting it on first request.

        Backed-up secret values are encrypted with this key. Keep it safe — restoring the secrets
        onto another instance requires supplying it. It is never included in a bundle.

        Requires workspace OWNER or platform SUPER_ADMIN — it unlocks every secret in any backup of
        this workspace, so it is gated exactly like import.

        Returns:
            {workspace_slug, backup_key, filename}
        """
        from fastapi import HTTPException
        from fastapi import status as http_status

        from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
        from marvin.services.backup.keys import get_or_create_backup_key

        is_super_admin = self.user.platform_role == PlatformRole.SUPER_ADMIN
        is_owner = self.user.has_workspace_role(self.group_id, WorkspaceRole.OWNER)
        if not (is_super_admin or is_owner):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Revealing the workspace backup key requires OWNER or SUPER_ADMIN role.",
            )

        workspace = self.repos.groups.get_one(self.group_id)
        key = get_or_create_backup_key(self.repos.session, self.group_id)
        slug = workspace.slug if workspace else "workspace"
        return {
            "workspace_slug": slug,
            "backup_key": key,
            "filename": f"marvin-backup-key-{slug}.txt",
        }

    @router.get("/backups", summary="List Workspace Backups")
    def list_backups(self) -> list:
        """List all backup zips for the current workspace, newest first.

        Returns:
            List of {filename, size, created_at} dicts
        """
        workspace = self.repos.groups.get_one(self.group_id)
        slug = workspace.slug if workspace else None

        backup_dir = self.directories.BACKUP_DIR
        if not backup_dir.exists():
            return []

        zips = sorted(backup_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)

        if slug:
            zips = [p for p in zips if p.name.startswith(f"{slug}-")]

        return [_backup_meta(p) for p in zips]

    @router.get("/backups/{filename}", summary="Download Workspace Backup")
    def download_backup(self, filename: str) -> Response:
        """Download a named backup zip.

        Validates the filename (must be .zip, no path traversal, must match
        the current workspace's slug prefix).

        Args:
            filename: Zip filename as returned by create_backup / list_backups

        Returns:
            Zip file download
        """
        from fastapi import HTTPException, status

        if not filename.endswith(".zip") or "/" in filename or "\\" in filename or ".." in filename:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename")

        workspace = self.repos.groups.get_one(self.group_id)
        slug = workspace.slug if workspace else None
        if slug and not filename.startswith(f"{slug}-"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        zip_path = self.directories.BACKUP_DIR / filename
        if not zip_path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")

        return FileResponse(
            path=str(zip_path),
            media_type="application/zip",
            filename=filename,
        )

    @router.post("/import", summary="Import Workspace Bundle")
    async def import_workspace(
        self,
        file: UploadFile = File(...),
        overwrite: bool = Query(
            False,
            description=(
                "When true, existing records matched by slug are updated with bundle data. "
                "⚠️ This will overwrite entries, collections, resources, and assets "
                "that exist in the workspace. Entry junction rows (→asset, →collection, "
                "→resource) are cleared and rebuilt from the bundle."
            ),
        ),
        backup_key: str | None = Form(
            None,
            description=(
                "Per-workspace backup key to decrypt secret values. Omit to restore secrets as "
                "valueless shells; when restoring into the workspace that made the backup, the "
                "stored key is tried automatically."
            ),
        ),
    ) -> dict:
        """Import a workspace bundle into the current workspace.

        Requires workspace OWNER or SUPER_ADMIN role.

        Args:
            file: Zip bundle file (from /backups)
            overwrite: When True, existing records matched by slug are updated
            backup_key: Per-workspace backup key for decrypting secret values

        Returns:
            Import counts by type
        """
        from fastapi import HTTPException
        from fastapi import status as http_status

        from marvin.db.models.users.roles import PlatformRole, WorkspaceRole

        is_super_admin = self.user.platform_role == PlatformRole.SUPER_ADMIN
        is_owner = self.user.has_workspace_role(self.group_id, WorkspaceRole.OWNER)

        if not (is_super_admin or is_owner):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Importing a workspace bundle requires OWNER or SUPER_ADMIN role.",
            )

        zip_path = self.directories.TEMP_DIR / f"{uuid4()}-import.zip"
        try:
            content = await file.read()
            zip_path.write_bytes(content)

            from marvin.repos.all_repositories import get_repositories

            instance_repos = get_repositories(self.repos.session, group_id=None)
            loader = WorkspaceSeedLoader(instance_repos)
            results = loader.load_seed_zip(zip_path, overwrite=overwrite, target_group_id=self.group_id, backup_key=backup_key)

            return {"imported": results}
        finally:
            zip_path.unlink(missing_ok=True)
