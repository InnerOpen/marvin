"""Admin workspace backup/restore endpoints — super admin can target any workspace by ID."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import UUID4

from marvin.repos.seed.workspace_exporter import WorkspaceExporter
from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader
from marvin.routes._base import BaseAdminController, controller

router = APIRouter(prefix="/backups")


def _backup_meta(path: Path) -> dict:
    stat = path.stat()
    return {
        "filename": path.name,
        "size": stat.st_size,
        "created_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="seconds"),
    }


@controller(router)
class AdminBackupsController(BaseAdminController):
    """Admin-level workspace backup and import — targets any workspace by ID."""

    @router.post("/workspaces/{workspace_id}", summary="Admin: Create Workspace Backup")
    def create_backup(self, workspace_id: UUID4) -> dict:
        """Create a backup bundle for any workspace and persist to BACKUP_DIR.

        Args:
            workspace_id: ID of the workspace to export

        Returns:
            {filename, size, created_at, download_url}
        """
        from marvin.repos.all_repositories import get_repositories

        workspace_repos = get_repositories(self.repos.session, group_id=workspace_id)
        workspace = workspace_repos.groups.get_one(workspace_id)
        if not workspace:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

        exporter = WorkspaceExporter(workspace_repos)
        zip_path = exporter.export_workspace_bundle(temp_dir=self.directories.BACKUP_DIR)

        meta = _backup_meta(zip_path)
        meta["download_url"] = f"/api/admin/backups/{zip_path.name}"
        meta["workspace_slug"] = workspace.slug
        return meta

    @router.get("/workspaces/{workspace_id}/key", summary="Admin: Get/Create Workspace Backup Key")
    def get_backup_key(self, workspace_id: UUID4) -> dict:
        """Return the workspace's backup key, minting it on first request.

        Secret values in a backup are encrypted with this key. Save it somewhere safe — restoring
        the secrets onto another instance requires supplying it. It is never included in a bundle.

        Returns:
            {workspace_slug, backup_key, filename}
        """
        from marvin.repos.all_repositories import get_repositories
        from marvin.services.backup.keys import get_or_create_backup_key

        workspace_repos = get_repositories(self.repos.session, group_id=workspace_id)
        workspace = workspace_repos.groups.get_one(workspace_id)
        if not workspace:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

        key = get_or_create_backup_key(self.repos.session, workspace_id)
        return {
            "workspace_slug": workspace.slug,
            "backup_key": key,
            "filename": f"marvin-backup-key-{workspace.slug}.txt",
        }

    @router.get("", summary="Admin: List All Backups")
    def list_backups(self, workspace_slug: str | None = None) -> list:
        """List backup zips, newest first.

        Args:
            workspace_slug: When provided, only return backups for that workspace.

        Returns:
            List of {filename, size, created_at, workspace_slug} dicts
        """
        backup_dir = self.directories.BACKUP_DIR
        if not backup_dir.exists():
            return []

        pattern = f"{workspace_slug}-backup-*.zip" if workspace_slug else "*.zip"
        zips = sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

        result = []
        for p in zips:
            meta = _backup_meta(p)
            # Parse workspace slug from filename prefix (slug-backup-date-token.zip)
            parts = p.stem.split("-backup-", 1)
            meta["workspace_slug"] = parts[0] if len(parts) == 2 else ""
            result.append(meta)

        return result

    @router.get("/{filename}", summary="Admin: Download Backup")
    def download_backup(self, filename: str) -> Response:
        """Download any named backup zip.

        Args:
            filename: Zip filename as returned by list_backups or create_backup

        Returns:
            Zip file download
        """
        if not filename.endswith(".zip") or "/" in filename or "\\" in filename or ".." in filename:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename")

        zip_path = self.directories.BACKUP_DIR / filename
        if not zip_path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")

        return FileResponse(
            path=str(zip_path),
            media_type="application/zip",
            filename=filename,
        )

    @router.post("/workspaces/{workspace_id}/import", summary="Admin: Import Workspace Bundle")
    async def import_workspace_bundle(
        self,
        workspace_id: UUID4,
        file: UploadFile = File(...),
        overwrite: bool = Query(
            False,
            description=(
                "When true, existing records matched by slug are updated. "
                "⚠️ Overwrites entries, collections, resources, and assets. "
                "Junction rows are cleared and rebuilt from the bundle."
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
        """Import a workspace bundle into a specific workspace.

        Args:
            workspace_id: ID of the target workspace
            file: Zip bundle file
            overwrite: When True, existing records matched by slug are updated
            backup_key: Per-workspace backup key for decrypting secret values

        Returns:
            Import counts by type
        """
        from marvin.repos.all_repositories import get_repositories

        workspace_repos = get_repositories(self.repos.session, group_id=None)
        workspace = workspace_repos.groups.get_one(workspace_id)
        if not workspace:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

        zip_path = self.directories.TEMP_DIR / f"{uuid4()}-admin-import.zip"
        try:
            content = await file.read()
            zip_path.write_bytes(content)

            loader = WorkspaceSeedLoader(workspace_repos)
            results = loader.load_seed_zip(zip_path, overwrite=overwrite, target_group_id=str(workspace_id), backup_key=backup_key)

            return {"imported": results}
        finally:
            zip_path.unlink(missing_ok=True)
