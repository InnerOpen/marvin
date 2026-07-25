"""Complete workspace seed loader for importing workspace data from JSON."""

import json
import zipfile
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

from marvin.core.root_logger import get_logger
from marvin.repos.repository_factory import AllRepositories

if TYPE_CHECKING:
    from marvin.schemas.group.group import GroupRead


class WorkspaceSeedLoader:
    """Loads complete workspace data from seed files.

    Supports the full workspace seed format including:
    - workspace metadata
    - site configuration
    - collections
    - entry_types
    - entries (with collection assignments)
    - resources
    - assets
    """

    def __init__(self, repos: AllRepositories, logger=None):
        """Initialize loader with repository access.

        Args:
            repos: Repository factory for database operations
            logger: Optional logger instance
        """
        self.repos = repos
        self.logger = logger or get_logger(__name__)
        self._seed_user_id: str | None  # lazily cached by _get_seed_user_id (guarded by hasattr)

    def load_seed_file(
        self, seed_file: Path, overwrite: bool = False, target_group_id: str | None = None, backup_key: str | None = None
    ) -> dict[str, int]:
        """Load a complete workspace seed from a JSON file.

        Args:
            seed_file: Path to workspace seed JSON file
            overwrite: When True, existing records matched by slug are updated
            target_group_id: When set, import into this workspace instead of reading from JSON.
                             Used for owner-scoped imports to prevent cross-workspace access.
            backup_key: Per-workspace backup key used to decrypt secret values. When omitted,
                        the target workspace's stored key is tried, else secrets import valueless.

        Returns:
            Dictionary with counts by type
        """
        self.logger.info(f"Loading workspace seed from: {seed_file}")

        with open(seed_file) as f:
            data = json.load(f)

        return self._load_data(data, zip_file=None, overwrite=overwrite, target_group_id=target_group_id, backup_key=backup_key)

    def load_seed_zip(
        self, zip_path: Path, overwrite: bool = False, target_group_id: str | None = None, backup_key: str | None = None
    ) -> dict[str, int]:
        """Load a workspace seed bundle from a zip file (JSON + asset binaries).

        Args:
            zip_path: Path to workspace bundle zip file
            overwrite: When True, existing records matched by slug are updated
            target_group_id: When set, import into this workspace instead of reading from JSON.
                             Used for owner-scoped imports to prevent cross-workspace access.
            backup_key: Per-workspace backup key used to decrypt secret values. When omitted,
                        the target workspace's stored key is tried, else secrets import valueless.

        Returns:
            Dictionary with counts by type
        """
        self.logger.info(f"Loading workspace bundle from: {zip_path}")

        with zipfile.ZipFile(zip_path, "r") as zf:
            # Find the root-level JSON file (name varies by export date/slug)
            json_name = next(
                (n for n in zf.namelist() if n.endswith(".json") and "/" not in n),
                "workspace-export.json",  # fallback for older bundles
            )
            with zf.open(json_name) as f:
                data = json.load(f)

            return self._load_data(data, zip_file=zf, overwrite=overwrite, target_group_id=target_group_id, backup_key=backup_key)

    def _load_data(  # noqa: C901 — orchestrates the full seed load; splitting would spread tightly-coupled steps
        self,
        data: dict[str, Any],
        zip_file: zipfile.ZipFile | None = None,
        overwrite: bool = False,
        target_group_id: str | None = None,
        backup_key: str | None = None,
    ) -> dict[str, int]:
        """Load workspace data from a parsed dict, optionally extracting asset binaries from a zip.

        Args:
            data: Parsed workspace seed dict
            zip_file: Open ZipFile for binary extraction, or None for metadata-only
            overwrite: When True, existing records matched by slug are updated
            target_group_id: When set, bypass workspace resolution from JSON and import
                             directly into this workspace (owner-scoped import path).
            backup_key: Per-workspace backup key used to decrypt secret values.

        Returns:
            Dictionary with counts by type
        """
        self._overwrite = overwrite
        self._backup_key = backup_key
        results = {
            "collections": 0,
            "tags": 0,
            "entry_types": 0,
            "entries": 0,
            "resources": 0,
            "assets": 0,
            "variables": 0,
            "secrets": 0,
            "ai_settings": 0,
            "integrations": 0,
            "ai_providers": 0,
            "mcp_servers": 0,
            "smtp_profiles": 0,
            "webhooks": 0,
            "incoming_webhooks": 0,
            "automations": 0,
            "scheduled_tasks": 0,
            "forms": 0,
            "email_templates": 0,
            "email_subscriptions": 0,
            "integration_subscriptions": 0,
            "errors": 0,
        }

        # 0. Resolve workspace: use caller-supplied ID (owner path) or read from JSON (admin path)
        workspace_data = data.get("workspace")
        workspace = None
        if target_group_id:
            from marvin.repos.all_repositories import get_repositories

            self.repos = get_repositories(self.repos.session, group_id=target_group_id)
            workspace = self.repos.groups.get_one(target_group_id)
            self.logger.info(f"Importing into caller's workspace: {workspace.name if workspace else target_group_id}")

            site_data = data.get("site")
            if site_data:
                self._update_site_preferences(site_data)
        elif workspace_data:
            workspace = self._ensure_workspace(workspace_data)
            from marvin.repos.all_repositories import get_repositories

            self.repos = get_repositories(self.repos.session, group_id=workspace.id)
            self.logger.info(f"Using workspace: {workspace.name} ({workspace.slug})")

            site_data = data.get("site")
            if site_data:
                self._update_site_preferences(site_data)

        # 1. Collections
        collections_data = data.get("collections", [])
        if collections_data:
            self.logger.info(f"Creating {len(collections_data)} collections...")
            for coll_data in collections_data:
                try:
                    self._create_collection(coll_data)
                    results["collections"] += 1
                except Exception as e:
                    self.logger.error(f"Failed to create collection {coll_data.get('slug')}: {e}")
                    results["errors"] += 1

        # 1.5 Tags — recreate the vocabulary (slug + name + color) before entries so entry tag
        # links resolve. Find-or-create by slug, so re-importing is idempotent.
        tags_data = data.get("tags", [])
        if tags_data:
            self.logger.info(f"Creating {len(tags_data)} tags...")
            for tag_data in tags_data:
                try:
                    self._create_tag(tag_data)
                    results["tags"] += 1
                except Exception as e:
                    self.logger.error(f"Failed to create tag {tag_data.get('slug')}: {e}")
                    results["errors"] += 1

        # 2. Entry Types
        entry_types_data = data.get("entry_types", [])
        if entry_types_data:
            self.logger.info(f"Creating {len(entry_types_data)} entry types...")
            for et_data in entry_types_data:
                try:
                    self._create_entry_type(et_data)
                    results["entry_types"] += 1
                except Exception as e:
                    self.logger.error(f"Failed to create entry type {et_data.get('slug')}: {e}")
                    results["errors"] += 1

        # 3. Resources (before entries so entry-resource links can resolve)
        resources_data = data.get("resources", [])
        if resources_data:
            self.logger.info(f"Creating {len(resources_data)} resources...")
            for res_data in resources_data:
                try:
                    self._create_resource(res_data)
                    results["resources"] += 1
                except Exception as e:
                    self.logger.error(f"Failed to create resource {res_data.get('slug')}: {e}")
                    results["errors"] += 1

        # 4. Assets (before entries so entry-asset links can resolve)
        assets_data = data.get("assets", [])
        if assets_data:
            self.logger.info(f"Importing {len(assets_data)} assets...")
            results["assets"] = self._import_assets(assets_data, zip_file)

        # 5. Entries
        entries_data = data.get("entries", [])
        if entries_data:
            self.logger.info(f"Creating {len(entries_data)} entries...")
            for entry_data in entries_data:
                try:
                    self._create_entry(entry_data)
                    results["entries"] += 1
                except Exception as e:
                    self.logger.error(f"Failed to create entry {entry_data.get('slug')}: {e}")
                    results["errors"] += 1

        # 6. Workspace settings: variables, AI policy, secrets. Scoped to the resolved workspace, so
        # they are skipped on a metadata-only load that never bound a group_id.
        if self.repos.group_id:
            variables_data = data.get("variables", [])
            if variables_data:
                self.logger.info(f"Importing {len(variables_data)} variables...")
                results["variables"] = self._import_variables(variables_data)

            ai_data = data.get("ai_settings")
            if ai_data and self._import_ai_settings(ai_data):
                results["ai_settings"] = 1

            secrets_data = data.get("secrets", [])
            if secrets_data:
                self.logger.info(f"Importing {len(secrets_data)} secrets...")
                results["secrets"] = self._import_secrets(secrets_data)

            # 7. Connections & config. Dependency order: providers→models, integrations→subscriptions,
            # templates→subscriptions. Credentials are referenced by secret_ref (restored in secrets).
            results["ai_providers"] = self._import_ai_providers(data.get("ai_providers", []))
            results["integrations"] = self._import_integrations(data.get("integrations", []))
            results["mcp_servers"] = self._import_mcp_servers(data.get("mcp_servers", []))
            results["smtp_profiles"] = self._import_smtp_profiles(data.get("smtp_profiles", []))
            results["webhooks"] = self._import_webhooks(data.get("webhooks", []))
            results["incoming_webhooks"] = self._import_incoming_webhooks(data.get("incoming_webhooks", []))
            results["email_templates"] = self._import_email_templates(data.get("email_templates", []))
            results["email_subscriptions"] = self._import_email_subscriptions(data.get("email_subscriptions", []))
            results["integration_subscriptions"] = self._import_integration_subscriptions(data.get("integration_subscriptions", []))
            results["automations"] = self._import_automations(data.get("automations", []))
            results["scheduled_tasks"] = self._import_scheduled_tasks(data.get("scheduled_tasks", []))
            results["forms"] = self._import_forms(data.get("forms", []))

        self.logger.info(
            f"Seed loaded: {results['collections']} collections, "
            f"{results['tags']} tags, "
            f"{results['entry_types']} entry types, "
            f"{results['entries']} entries, "
            f"{results['resources']} resources, "
            f"{results['assets']} assets, "
            f"{results['variables']} variables, "
            f"{results['secrets']} secrets, "
            f"{results['ai_settings']} AI settings, "
            f"{results['errors']} errors"
        )
        self.logger.info(
            f"Connections loaded: {results['integrations']} integrations, {results['ai_providers']} AI providers, "
            f"{results['mcp_servers']} MCP servers, {results['smtp_profiles']} SMTP profiles, {results['webhooks']} webhooks, "
            f"{results['incoming_webhooks']} incoming webhooks, {results['automations']} automations, "
            f"{results['scheduled_tasks']} scheduled tasks, {results['forms']} forms, {results['email_templates']} email templates, "
            f"{results['email_subscriptions']} email subs, {results['integration_subscriptions']} integration subs"
        )

        # 6. Send owner invitation emails if provided (admin path only — owner already has access)
        if workspace_data and workspace and not target_group_id:
            owner_emails = []
            if workspace_data.get("ownerEmail"):
                owner_emails.append(workspace_data["ownerEmail"])
            if workspace_data.get("ownerEmails"):
                owner_emails.extend(workspace_data["ownerEmails"])

            for owner_email in owner_emails:
                try:
                    self._send_owner_invitation(owner_email, workspace)
                except Exception as e:
                    self.logger.error(f"Failed to send owner invitation to {owner_email}: {e}")
                    results["errors"] += 1

        return results

    def _import_assets(self, assets_data: list[dict[str, Any]], zip_file: zipfile.ZipFile | None) -> int:
        """Import assets, uploading binaries from zip if available.

        Args:
            assets_data: List of asset metadata dicts from seed
            zip_file: Open ZipFile containing binaries under files/, or None

        Returns:
            Count of assets imported
        """
        from datetime import UTC, datetime

        from marvin.services.assets.asset_storage_service import AssetStorageService
        from marvin.services.storage.provider_factory import get_storage_provider

        storage_provider = get_storage_provider()
        zip_names = set(zip_file.namelist()) if zip_file else set()
        workspace = self.repos.groups.get_one(self.repos.group_id)
        workspace_slug = (workspace.slug if workspace else None) or "workspace"
        user_id = self._get_seed_user_id()
        count = 0

        for asset in assets_data:
            slug = asset["slug"]

            existing = self.repos.assets.multi_query({"slug": slug})
            if existing and not self._overwrite:
                self.logger.debug(f"Asset already exists: {slug}")
                continue

            zip_path = f"files/{asset['storageKey']}"
            has_binary = zip_file is not None and zip_path in zip_names

            # checksum is NOT NULL but the bundle doesn't carry it — compute from the binary when we
            # have it, else derive a stable value from the storage key. Keeps restore backend-portable.
            import hashlib

            checksum_val = asset.get("checksum")

            if has_binary:
                assert zip_file is not None  # has_binary is only set when a zip is present
                try:
                    raw_bytes = zip_file.read(zip_path)
                    binary_data = BytesIO(raw_bytes)
                    checksum_val = checksum_val or hashlib.sha256(raw_bytes).hexdigest()

                    storage_service = AssetStorageService(self.repos, storage_provider)
                    new_storage_key = storage_service.generate_storage_key(
                        workspace_slug=workspace_slug,
                        filename=asset.get("originalFilename") or f"{slug}.{asset.get('extension', 'bin')}",
                        upload_date=datetime.now(UTC),
                    )

                    storage_provider.put(new_storage_key, binary_data, asset.get("mimeType", "application/octet-stream"))
                    new_public_url = storage_provider.get_public_url(new_storage_key)
                except Exception as e:
                    self.logger.error(f"Failed to store binary for asset {slug}: {e}")
                    continue
            else:
                if zip_file is not None:
                    self.logger.warning(f"Asset binary not found in bundle, skipping: {slug}")
                new_storage_key = asset.get("storageKey", "")
                new_public_url = None  # validator computes correct URL at read time

            if not user_id:
                self.logger.warning(f"No user found for asset creation, skipping: {slug}")
                continue

            create_data = {
                "group_id": self.repos.group_id,
                "slug": slug,
                "name": asset.get("name", slug),
                "original_filename": asset.get("originalFilename"),
                # `filename` is NOT NULL but older/portable bundles may not carry it — derive from the
                # original filename (the same stem the uploader would compute) so restore works on any
                # backend (Postgres enforces the NOT NULL that SQLite let slide).
                "filename": asset.get("filename") or Path(asset.get("originalFilename") or slug).stem,
                "checksum": checksum_val or hashlib.sha256((new_storage_key or slug).encode()).hexdigest(),
                "extension": asset.get("extension"),
                "file_size": asset.get("fileSize"),
                "mime_type": asset.get("mimeType"),
                "asset_type": asset.get("assetType"),
                "storage_provider": asset.get("storageProvider", "local"),
                "storage_key": new_storage_key,
                "public_url": new_public_url,
                "alt_text": asset.get("altText"),
                "description": asset.get("description"),
                "width": asset.get("width"),
                "height": asset.get("height"),
                "metadata_json": asset.get("metadataJson"),
                "uploaded_by": user_id,
            }
            create_data = {k: v for k, v in create_data.items() if v is not None}

            from marvin.db.models.platform import AssetTags

            tag_slugs = asset.get("tags", [])

            try:
                if existing and self._overwrite:
                    if has_binary:
                        update_data = {
                            "storage_key": new_storage_key,
                            "file_size": asset.get("fileSize"),
                            "public_url": None,
                            "metadata_json": asset.get("metadataJson"),
                            "alt_text": asset.get("altText"),
                            "description": asset.get("description"),
                            "name": asset.get("name", slug),
                        }
                    else:
                        update_data = {
                            "name": asset.get("name", slug),
                            "alt_text": asset.get("altText"),
                            "description": asset.get("description"),
                            "metadata_json": asset.get("metadataJson"),
                        }
                    update_data = {k: v for k, v in update_data.items() if v is not None}
                    self.repos.assets.update(existing[0].id, update_data)
                    self.logger.info(f"Overwrote asset: {slug}")
                    asset_id = existing[0].id
                    self.repos.session.query(AssetTags).filter(AssetTags.asset_id == asset_id).delete()
                    self.repos.session.commit()
                else:
                    created = self.repos.assets.create(create_data)
                    self.logger.info(f"Imported asset: {slug}")
                    asset_id = created.id
                if tag_slugs:
                    self._link_tags(AssetTags, "asset_id", asset_id, tag_slugs)
                count += 1
            except Exception as e:
                self.logger.error(f"Failed to create asset record {slug}: {e}")

        return count

    def _ensure_workspace(self, data: dict[str, Any]) -> "GroupRead":
        """Create workspace if it doesn't exist, or return existing one.

        Args:
            data: Workspace data from seed file

        Returns:
            GroupRead: The workspace/group
        """
        from marvin.schemas.group.group import GroupCreate
        from marvin.services.group.group_service import GroupService

        # Check if workspace exists by slug (if provided) or by name
        existing_groups = None

        if data.get("slug"):
            # Try to find by slug first
            existing_groups = self.repos.groups.multi_query({"slug": data["slug"]})
            if existing_groups:
                self.logger.info(f"Workspace found by slug: {data['slug']}")
                return existing_groups[0]

        # If no slug or slug not found, try to find by name
        existing_groups = self.repos.groups.multi_query({"name": data["name"]})
        if existing_groups:
            self.logger.info(f"Workspace found by name: {data['name']}")
            return existing_groups[0]

        # Create new workspace if not found
        group_create = GroupCreate(
            name=data["name"],
            slug=data.get("slug"),  # Optional, will be auto-generated if not provided
        )

        workspace = GroupService.create_group(self.repos, group_create)
        self.logger.info(f"Created workspace: {workspace.name} ({workspace.slug})")
        return workspace

    def _update_site_preferences(self, data: dict[str, Any]) -> None:
        """Update site preferences for the workspace.

        Args:
            data: Site configuration data from seed file
        """
        # Map camelCase JSON fields to snake_case database fields
        update_data = {
            "site_title": data.get("title"),
            "site_tagline": data.get("tagline"),
            "site_description": data.get("description"),
            "site_canonical_url": data.get("canonicalUrl"),
            "site_logo": data.get("logo"),
            "site_favicon": data.get("favicon"),
            "site_locale": data.get("locale"),
            "site_timezone": data.get("timezone"),
            "site_contact_email": data.get("contactEmail"),
            "site_social_json": data.get("social"),
            "site_metadata_json": data.get("metadataJson"),
        }

        # Remove None values to avoid overwriting existing data with nulls
        update_data = {k: v for k, v in update_data.items() if v is not None}

        if update_data:
            # Update preferences using the preferences repository
            # Use multi_query to find by group_id, then update by group_id (not id)
            prefs_list = self.repos.group_preferences.multi_query({"group_id": self.repos.group_id})
            if prefs_list:
                # Update using group_id as the match key
                self.repos.group_preferences.update(self.repos.group_id, update_data, match_key="group_id")
                self.logger.info(f"Updated site preferences ({len(update_data)} fields)")
            else:
                self.logger.warning("Group preferences not found - cannot update site settings")

    def _create_collection(self, data: dict[str, Any]) -> None:
        """Create a collection if it doesn't exist, or update it when overwrite is enabled.

        Args:
            data: Collection data from seed file
        """
        # Marvin's workflow collections (inbox/drafts/needs-review/approved/archive) are seeded per
        # workspace and locked from create/edit — trying to recreate or overwrite them on restore
        # fails with a 403. They are status-driven, so entries land in them by status regardless;
        # skip them entirely.
        from marvin.services.collections.system_collections import SYSTEM_COLLECTION_SLUGS

        if data["slug"] in SYSTEM_COLLECTION_SLUGS:
            self.logger.debug(f"Skipping system collection (Marvin-managed, auto-seeded): {data['slug']}")
            return

        existing = self.repos.collections.multi_query({"slug": data["slug"]})

        create_data = {
            "name": data["name"],
            "slug": data["slug"],
            "description": data.get("description"),
            "sort_order": data.get("sortOrder", 0),
            "icon": data.get("icon"),
            "color": data.get("color"),
            "metadata_json": data.get("metadataJson"),
        }

        if existing:
            if self._overwrite:
                self.repos.collections.update(existing[0].id, create_data)
                self.logger.info(f"Overwrote collection: {data['slug']}")
            else:
                self.logger.debug(f"Collection already exists: {data['slug']}")
            return

        self.repos.collections.create(create_data)
        self.logger.info(f"Created collection: {data['slug']}")

    def _create_entry_type(self, data: dict[str, Any]) -> None:
        """Create an entry type if it doesn't exist, or update it when overwrite is enabled.

        Args:
            data: Entry type data from seed file
        """
        # Check both slug AND group_id to respect UNIQUE (group_id, slug) constraint
        existing = self.repos.entry_types.multi_query({"slug": data["slug"], "group_id": self.repos.group_id})

        create_data = {
            "name": data["name"],
            "slug": data["slug"],
            "icon": data.get("icon"),
            "color": data.get("color"),
            "description": data.get("description"),
            "sort_order": data.get("sortOrder", 0),
            "content_schema": data.get("schemaJson", {}),
        }

        if existing:
            if self._overwrite:
                self.repos.entry_types.update(existing[0].id, create_data)
                self.logger.info(f"Overwrote entry type: {data['slug']}")
            else:
                self.logger.debug(f"Entry type already exists in workspace: {data['slug']}")
            return

        self.repos.entry_types.create(create_data)
        self.logger.info(f"Created entry type: {data['slug']}")

    def _create_entry(self, data: dict[str, Any]) -> None:
        """Create an entry with collection assignments, or update it when overwrite is enabled.

        Args:
            data: Entry data from seed file
        """
        existing_list = self.repos.entries.multi_query({"slug": data["slug"]})

        # Get entry type - handle explicit scope or auto-prefer workspace over system
        entry_type_slug = data["entryType"]
        entry_type_scope = data.get("entryTypeScope")  # Optional: "system", "workspace", or None

        if entry_type_scope == "system":
            entry_types = self.repos.entry_types.multi_query({"slug": entry_type_slug, "group_id": None})
        elif entry_type_scope == "workspace":
            entry_types = self.repos.entry_types.multi_query({"slug": entry_type_slug, "group_id": self.repos.group_id})
        else:
            # Auto-prefer: workspace type first, then system type
            entry_types = self.repos.entry_types.multi_query({"slug": entry_type_slug, "group_id": self.repos.group_id})
            if not entry_types:
                entry_types = self.repos.entry_types.multi_query({"slug": entry_type_slug})

        if not entry_types:
            scope_msg = f" (scope: {entry_type_scope})" if entry_type_scope else ""
            raise ValueError(f"Entry type not found: {entry_type_slug}{scope_msg}")

        entry_type = entry_types[0]

        if existing_list:
            if not self._overwrite:
                self.logger.debug(f"Entry already exists: {data['slug']}")
                return

            existing = existing_list[0]

            # Update content fields only — do not change entry_type_id
            update_data = {
                "title": data["title"],
                "slug": data["slug"],
                "status": data.get("status", "draft"),
                "summary": data.get("summary"),
                "description": data.get("description"),
                "data_json": data.get("data", {}),
                "metadata_json": data.get("metadataJson"),
                "publish_at": data.get("publishAt"),
                "expire_at": data.get("expireAt"),
            }
            self.repos.entries.update(existing.id, update_data)
            self.logger.info(f"Overwrote entry: {data['slug']}")

            # Clear junction rows and rebuild from bundle
            from marvin.db.models.platform import EntryAssets, EntryCollections, EntryResources, EntryTags

            self.repos.session.query(EntryCollections).filter(EntryCollections.entry_id == existing.id).delete()
            self.repos.session.query(EntryResources).filter(EntryResources.entry_id == existing.id).delete()
            self.repos.session.query(EntryAssets).filter(EntryAssets.entry_id == existing.id).delete()
            self.repos.session.query(EntryTags).filter(EntryTags.entry_id == existing.id).delete()
            self.repos.session.commit()

            entry_id = existing.id
        else:
            create_data = {
                "entry_type_id": entry_type.id,
                "title": data["title"],
                "slug": data["slug"],
                "status": data.get("status", "draft"),
                "summary": data.get("summary"),
                "description": data.get("description"),
                "data_json": data.get("data", {}),
                "metadata_json": data.get("metadataJson"),
                "publish_at": data.get("publishAt"),
                "expire_at": data.get("expireAt"),
            }

            entry = self.repos.entries.create(create_data)
            self.logger.info(f"Created entry: {data['slug']} (type: {entry_type_slug})")
            entry_id = entry.id

        # Handle collection assignments
        collection_assignments = data.get("collections", [])
        if collection_assignments:
            self._assign_to_collections(entry_id, collection_assignments)

        # Handle resource assignments
        resource_assignments = data.get("resources", [])
        if resource_assignments:
            self._assign_to_resources(entry_id, resource_assignments)

        # Handle asset assignments
        asset_assignments = data.get("assets", [])
        if asset_assignments:
            self._assign_to_assets(entry_id, asset_assignments)

        # Handle tag membership (slug list) — resolve/create each tag and link it.
        tag_slugs = data.get("tags", [])
        if tag_slugs:
            self._assign_to_tags(entry_id, tag_slugs)

    def _get_seed_user_id(self) -> str | None:
        """Get a user ID for seed-created records.

        Returns the first admin user's ID, or the first user if no admin exists.
        """
        if hasattr(self, "_seed_user_id"):
            return self._seed_user_id

        from marvin.db.models.users import Users

        admin = self.repos.session.query(Users).filter(Users.admin == True).first()  # noqa: E712
        if admin:
            self._seed_user_id = admin.id
            return self._seed_user_id

        user = self.repos.session.query(Users).first()
        self._seed_user_id = user.id if user else None
        return self._seed_user_id

    def _create_resource(self, data: dict[str, Any]) -> None:
        """Create a resource if it doesn't exist, or update it when overwrite is enabled.

        Args:
            data: Resource data from seed file
        """
        existing = self.repos.resources.multi_query({"slug": data["slug"]})

        user_id = self._get_seed_user_id()
        if not user_id:
            self.logger.warning(f"No user found for resource creation, skipping: {data['slug']}")
            return

        create_data = {
            "group_id": self.repos.group_id,
            "name": data["name"],
            "slug": data["slug"],
            "resource_type": data.get("resourceType", "material"),
            "description": data.get("description"),
            "url": data.get("url"),
            "external_id": data.get("externalId"),
            "metadata_json": data.get("metadataJson"),
            "created_by": user_id,
        }

        from marvin.db.models.platform import ResourceTags

        tag_slugs = data.get("tags", [])

        if existing:
            if self._overwrite:
                self.repos.resources.update(existing[0].id, create_data)
                self.logger.info(f"Overwrote resource: {data['slug']}")
                self.repos.session.query(ResourceTags).filter(ResourceTags.resource_id == existing[0].id).delete()
                self.repos.session.commit()
                if tag_slugs:
                    self._link_tags(ResourceTags, "resource_id", existing[0].id, tag_slugs)
            else:
                self.logger.debug(f"Resource already exists: {data['slug']}")
            return

        resource = self.repos.resources.create(create_data)
        self.logger.info(f"Created resource: {data['slug']}")
        if tag_slugs:
            self._link_tags(ResourceTags, "resource_id", resource.id, tag_slugs)

    def _assign_to_resources(self, entry_id: str, assignments: list[dict[str, Any]]) -> None:
        """Link an entry to resources with role and position.

        Args:
            entry_id: UUID of the entry
            assignments: List of {slug: str, role?: str, position?: int} dicts
        """
        for assignment in assignments:
            resource_slug = assignment["slug"]
            role = assignment.get("role")
            position = assignment.get("position", 0)

            resources = self.repos.resources.multi_query({"slug": resource_slug})
            if not resources:
                self.logger.warning(f"Resource not found: {resource_slug}")
                continue

            resource = resources[0]

            try:
                from marvin.db.models.platform import EntryResources

                junction = EntryResources(
                    entry_id=entry_id,
                    resource_id=resource.id,
                    role=role,
                    position=position,
                    metadata_json=assignment.get("metadataJson"),
                )
                self.repos.session.add(junction)
                self.repos.session.commit()
                self.logger.debug(f"Linked resource: {resource_slug} (role: {role})")
            except Exception as e:
                self.repos.session.rollback()
                self.logger.error(f"Failed to link resource {resource_slug}: {e}")

    def _create_tag(self, data: dict[str, Any]) -> None:
        """Create (or find) a tag from the exported vocabulary. Idempotent by slug.

        Args:
            data: {slug, name, color?} dict from the seed file
        """
        from marvin.schemas.platform import TagCreate

        name = data.get("name") or data.get("slug")
        # TagsRepository.create is find-or-create by slug, so re-import doesn't duplicate.
        self.repos.tags.create(TagCreate(name=name, slug=data.get("slug"), color=data.get("color")))

    def _import_variables(self, variables_data: list[dict[str, Any]]) -> int:
        """Create/update workspace variables (plaintext) by slug. Idempotent unless overwrite."""
        from marvin.db.models.groups.variables import WorkspaceVariable

        count = 0
        for v in variables_data:
            slug = v.get("slug")
            if not slug:
                continue
            existing = self.repos.session.query(WorkspaceVariable).filter_by(group_id=self.repos.group_id, slug=slug).first()
            try:
                if existing:
                    if not self._overwrite:
                        self.logger.debug(f"Variable already exists: {slug}")
                        continue
                    existing.name = v.get("name", slug)
                    existing.description = v.get("description")
                    existing.value = v.get("value", existing.value)
                else:
                    self.repos.session.add(
                        WorkspaceVariable(
                            session=self.repos.session,
                            group_id=self.repos.group_id,
                            name=v.get("name", slug),
                            slug=slug,
                            description=v.get("description"),
                            value=v.get("value", ""),
                        )
                    )
                self.repos.session.commit()
                count += 1
                self.logger.info(f"Imported variable: {slug}")
            except Exception as e:
                self.repos.session.rollback()
                self.logger.error(f"Failed to import variable {slug}: {e}")
        return count

    def _import_ai_settings(self, ai_data: dict[str, Any]) -> bool:
        """Upsert the workspace AI policy row. Existing settings are left alone unless overwrite."""
        from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

        # camelCase bundle key -> model attribute
        field_map = {
            "enabled": "enabled",
            "credentialMode": "credential_mode",
            "provider": "provider",
            "model": "model",
            "secretRef": "secret_ref",
            "approvalMode": "approval_mode",
            "invocationSources": "invocation_sources",
            "operationOverrides": "operation_overrides",
            "budgetConfig": "budget_config",
            "loggingConfig": "logging_config",
            "moderationConfig": "moderation_config",
            "mediaPresets": "media_presets",
            "externalMcpEnabled": "external_mcp_enabled",
            "assistantName": "assistant_name",
            "personaPrompt": "persona_prompt",
            "defaultRegister": "default_register",
        }

        row = self.repos.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.repos.group_id).first()
        if row and not self._overwrite:
            self.logger.debug("AI settings already exist; skipping (use overwrite to replace)")
            return False

        try:
            if row is None:
                row = WorkspaceAISettingsModel(session=self.repos.session, group_id=self.repos.group_id)
                self.repos.session.add(row)
            for json_key, attr in field_map.items():
                if json_key in ai_data and hasattr(row, attr):
                    setattr(row, attr, ai_data[json_key])
            self.repos.session.commit()
            self.logger.info("Imported AI settings")
            return True
        except Exception as e:
            self.repos.session.rollback()
            self.logger.error(f"Failed to import AI settings: {e}")
            return False

    def _resolve_backup_key(self) -> str | None:
        """The operator-supplied backup key, or the workspace's stored key (same-workspace restore)."""
        if self._backup_key:
            return self._backup_key
        from marvin.services.backup.keys import get_stored_backup_key

        return get_stored_backup_key(self.repos.session, self.repos.group_id)

    def _store_secret_value(self, row, slug: str, value: str) -> None:
        """Persist a decrypted secret value using the configured backend (mirrors the secrets API)."""
        from marvin.core.config import get_app_settings

        if get_app_settings().SECRET_BACKEND == "database":
            from marvin.services.secrets.backends.database import _get_fernet

            row.encrypted_value = _get_fernet().encrypt(value.encode()).decode()
        else:
            row.encrypted_value = "_backend_managed_"
            try:
                from marvin.services.secrets import get_secret_backend

                get_secret_backend().set(slug, value, self.repos.group_id)
            except Exception as e:
                self.logger.error(f"Failed to store secret '{slug}' in backend: {e}")

    def _import_secrets(self, secrets_data: list[dict[str, Any]]) -> int:
        """Recreate workspace secrets, decrypting values with the backup key when available.

        Without a usable key (or for metadata-only entries) a secret is created as a valueless shell
        that the operator re-enters later. Existing secrets are skipped unless overwrite.
        """
        from marvin.db.models.groups.secrets import WorkspaceSecret
        from marvin.services.backup.keys import decrypt_secret_value

        backup_key = self._resolve_backup_key()
        count = 0
        shells = 0

        for s in secrets_data:
            slug = s.get("slug")
            if not slug:
                continue
            existing = self.repos.session.query(WorkspaceSecret).filter_by(group_id=self.repos.group_id, slug=slug).first()
            if existing and not self._overwrite:
                self.logger.debug(f"Secret already exists: {slug}")
                continue

            value = None
            token = s.get("encryptedBackupValue")
            if token and backup_key:
                try:
                    value = decrypt_secret_value(token, backup_key)
                except Exception:
                    self.logger.warning(f"Could not decrypt secret '{slug}' with the provided backup key")

            try:
                row = existing or WorkspaceSecret(
                    session=self.repos.session,
                    group_id=self.repos.group_id,
                    name=s.get("name", slug),
                    slug=slug,
                    encrypted_value="_backend_managed_",
                )
                row.name = s.get("name", slug)
                row.description = s.get("description")
                if value is not None:
                    self._store_secret_value(row, slug, value)
                else:
                    shells += 1
                    if not existing:
                        row.encrypted_value = "_backend_managed_"
                if not existing:
                    self.repos.session.add(row)
                self.repos.session.commit()
                count += 1
                self.logger.info(f"Imported secret: {slug}{'' if value is not None else ' (no value — needs re-entry)'}")
            except Exception as e:
                self.repos.session.rollback()
                self.logger.error(f"Failed to import secret {slug}: {e}")

        if shells:
            self.logger.warning(f"{shells} secret(s) imported without a value (no/invalid backup key) — re-enter them in the workspace")
        return count

    # ── Connections & config ────────────────────────────────────────────────────────────────────
    def _upsert(self, model, key_field: str, key_value, values: dict):
        """Find a group-scoped row by (group_id, key_field==key_value); create it, or update it when
        overwrite is on. Returns (row, skipped) where skipped is True only for an existing row left
        untouched. Commits."""
        existing = (
            self.repos.session.query(model).filter(model.group_id == self.repos.group_id, getattr(model, key_field) == key_value).first()
        )
        if existing:
            if not self._overwrite:
                return existing, True
            for k, v in values.items():
                setattr(existing, k, v)
            self.repos.session.commit()
            return existing, False
        row = model(session=self.repos.session, group_id=self.repos.group_id, **{key_field: key_value}, **values)
        self.repos.session.add(row)
        self.repos.session.commit()
        return row, False

    def _import_simple(self, model, key_field: str, rows: list[dict[str, Any]], build) -> int:
        """Upsert a list of rows keyed by `key_field`. `build(d)` maps a bundle dict to (key, values);
        return (None, _) to skip a row. Rolls back and logs per-row on error."""
        if not self.repos.group_id or not rows:
            return 0
        count = 0
        for d in rows:
            try:
                key, values = build(d)
                if key is None:
                    continue
                _, skipped = self._upsert(model, key_field, key, values)
                if not skipped:
                    count += 1
            except Exception as e:
                self.repos.session.rollback()
                self.logger.error(f"Failed to import {model.__tablename__} row {d.get('slug') or d.get('name')}: {e}")
        return count

    def _import_integrations(self, rows: list[dict[str, Any]]) -> int:
        from marvin.db.models.groups.integrations import IntegrationModel

        return self._import_simple(
            IntegrationModel,
            "slug",
            rows,
            lambda d: (
                d.get("slug"),
                {
                    "provider": d.get("provider"),
                    "name": d.get("name", d.get("slug")),
                    "enabled": d.get("enabled", True),
                    "config": d.get("config"),
                    "secret_ref": d.get("secretRef"),
                },
            ),
        )

    def _import_ai_providers(self, rows: list[dict[str, Any]]) -> int:
        if not self.repos.group_id or not rows:
            return 0
        from marvin.db.models.groups.ai_providers import AIModelModel, AIProviderModel

        count = 0
        for d in rows:
            slug = d.get("slug")
            if not slug:
                continue
            try:
                provider, skipped = self._upsert(
                    AIProviderModel,
                    "slug",
                    slug,
                    {
                        "name": d.get("name", slug),
                        "provider_type": d.get("providerType"),
                        "secret_ref": d.get("secretRef"),
                        "base_url": d.get("baseUrl"),
                        "enabled": d.get("enabled", True),
                        "is_default": d.get("isDefault", False),
                        "metadata_json": d.get("metadataJson"),
                    },
                )
                if skipped:
                    continue
                count += 1
                for m in d.get("models", []):
                    mid = m.get("modelId")
                    if not mid:
                        continue
                    existing_m = (
                        self.repos.session.query(AIModelModel)
                        .filter(AIModelModel.provider_id == provider.id, AIModelModel.model_id == mid)
                        .first()
                    )
                    mvals = {
                        "name": m.get("name", mid),
                        "is_default": m.get("isDefault", False),
                        "context_window": m.get("contextWindow"),
                        "max_output_tokens": m.get("maxOutputTokens"),
                        "supports_vision": m.get("supportsVision", False),
                        "supports_tools": m.get("supportsTools", False),
                        "enabled": m.get("enabled", True),
                    }
                    if existing_m:
                        if self._overwrite:
                            for k, v in mvals.items():
                                setattr(existing_m, k, v)
                    else:
                        self.repos.session.add(
                            AIModelModel(session=self.repos.session, group_id=self.repos.group_id, provider_id=provider.id, model_id=mid, **mvals)
                        )
                    self.repos.session.commit()
            except Exception as e:
                self.repos.session.rollback()
                self.logger.error(f"Failed to import AI provider {slug}: {e}")
        return count

    def _import_mcp_servers(self, rows: list[dict[str, Any]]) -> int:
        from marvin.db.models.groups.mcp_servers import WorkspaceMcpServerModel

        seed_user = self._get_seed_user_id()
        return self._import_simple(
            WorkspaceMcpServerModel,
            "slug",
            rows,
            lambda d: (
                d.get("slug"),
                {
                    "name": d.get("name", d.get("slug")),
                    "transport": d.get("transport"),
                    "url": d.get("url"),
                    "secret_ref": d.get("secretRef"),
                    "enabled": d.get("enabled", True),
                    "allowed_tools": d.get("allowedTools"),
                    "created_by": seed_user,
                },
            ),
        )

    def _import_smtp_profiles(self, rows: list[dict[str, Any]]) -> int:
        from marvin.db.models.groups.smtp_profiles import WorkspaceSMTPProfileModel

        # secret_ref is carried verbatim; it names the SMTP-password secret restored in the secrets
        # section under the same slug, so it resolves even though the profile gets a new id.
        return self._import_simple(
            WorkspaceSMTPProfileModel,
            "name",
            rows,
            lambda d: (
                d.get("name"),
                {
                    "host": d.get("host"),
                    "port": d.get("port", 587),
                    "username": d.get("username"),
                    "secret_ref": d.get("secretRef"),
                    "from_name": d.get("fromName"),
                    "from_email": d.get("fromEmail"),
                    "auth_strategy": d.get("authStrategy", "TLS"),
                    "is_active": d.get("isActive", False),
                },
            ),
        )

    def _import_webhooks(self, rows: list[dict[str, Any]]) -> int:
        if not self.repos.group_id or not rows:
            return 0
        from datetime import datetime

        from marvin.db.models.groups.webhooks import GroupWebhooksModel, Method
        from marvin.services.event_bus_service.event_types import WebhookMode

        def build(d):
            url = d.get("url")
            if not url:
                return None, None
            try:
                method = Method(d["method"]) if d.get("method") else Method.POST
            except ValueError:
                method = Method.POST
            wt = None
            if d.get("webhookType"):
                try:
                    wt = WebhookMode(d["webhookType"])
                except ValueError:
                    wt = None
            st = None
            if d.get("scheduledTime"):
                try:
                    st = datetime.fromisoformat(d["scheduledTime"])
                except ValueError:
                    st = None
            return url, {
                "name": d.get("name"),
                "method": method,
                "webhook_type": wt,
                "enabled": d.get("enabled", False),
                "subscribed_events": d.get("subscribedEvents"),
                "headers_json": d.get("headersJson"),
                "custom_payload": d.get("customPayload"),
                "scheduled_time": st,
            }

        return self._import_simple(GroupWebhooksModel, "url", rows, build)

    def _import_incoming_webhooks(self, rows: list[dict[str, Any]]) -> int:
        if not self.repos.group_id or not rows:
            return 0
        from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel

        def build(d):
            slug = d.get("slug")
            if not slug:
                return None, None
            token = d.get("token")
            if token:
                # The token is globally unique — drop it if another webhook already holds it, so
                # the import doesn't fail. Deny-by-default until an admin re-mints one.
                clash = self.repos.session.query(WorkspaceIncomingWebhookModel).filter(WorkspaceIncomingWebhookModel.token == token).first()
                if clash and not (clash.group_id == self.repos.group_id and clash.slug == slug):
                    self.logger.warning(f"Incoming webhook '{slug}': token already in use, importing without it")
                    token = None
            return slug, {
                "name": d.get("name", slug),
                "description": d.get("description"),
                "enabled": d.get("enabled", False),
                "token": token,
            }

        return self._import_simple(WorkspaceIncomingWebhookModel, "slug", rows, build)

    def _import_automations(self, rows: list[dict[str, Any]]) -> int:
        from marvin.db.models.groups.automations import WorkspaceAutomationModel

        seed_user = self._get_seed_user_id()
        return self._import_simple(
            WorkspaceAutomationModel,
            "slug",
            rows,
            lambda d: (
                d.get("slug"),
                {
                    "name": d.get("name", d.get("slug")),
                    "enabled": d.get("enabled", True),
                    "definition": d.get("definition"),
                    "created_by": seed_user,
                },
            ),
        )

    def _import_scheduled_tasks(self, rows: list[dict[str, Any]]) -> int:
        from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

        return self._import_simple(
            ScheduledTaskModel,
            "slug",
            rows,
            lambda d: (
                d.get("slug"),
                {
                    "name": d.get("name", d.get("slug")),
                    "description": d.get("description"),
                    "enabled": d.get("enabled", True),
                    "schedule_type": d.get("scheduleType"),
                    "schedule_config": d.get("scheduleConfig") or {},
                    "task_type": d.get("taskType"),
                    "task_config": d.get("taskConfig") or {},
                    "retry_policy": d.get("retryPolicy"),
                },
            ),
        )

    def _import_forms(self, rows: list[dict[str, Any]]) -> int:
        from marvin.db.models.platform.forms import Forms

        return self._import_simple(
            Forms,
            "slug",
            rows,
            lambda d: (
                d.get("slug"),
                {
                    "name": d.get("name", d.get("slug")),
                    "description": d.get("description"),
                    "schema_json": d.get("schemaJson") or {},
                    "settings_json": d.get("settingsJson"),
                    "metadata_json": d.get("metadataJson"),
                    "status": d.get("status", "draft"),
                },
            ),
        )

    def _import_email_templates(self, rows: list[dict[str, Any]]) -> int:
        from marvin.db.models.groups.email_templates import EmailTemplateModel

        return self._import_simple(
            EmailTemplateModel,
            "template_type",
            rows,
            lambda d: (
                d.get("templateType"),
                {
                    "name": d.get("name", d.get("templateType")),
                    "description": d.get("description"),
                    "subject": d.get("subject", ""),
                    "custom_html": d.get("customHtml"),
                    "body_markdown": d.get("bodyMarkdown"),
                    "available_variables": d.get("availableVariables"),
                    "enabled": d.get("enabled", True),
                },
            ),
        )

    def _import_email_subscriptions(self, rows: list[dict[str, Any]]) -> int:
        if not self.repos.group_id or not rows:
            return 0
        from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel
        from marvin.db.models.groups.email_templates import EmailTemplateModel

        count = 0
        for d in rows:
            try:
                template = None
                if d.get("templateType"):
                    template = (
                        self.repos.session.query(EmailTemplateModel)
                        .filter(EmailTemplateModel.group_id == self.repos.group_id, EmailTemplateModel.template_type == d["templateType"])
                        .first()
                    )
                if template is None and d.get("templateName"):
                    template = (
                        self.repos.session.query(EmailTemplateModel)
                        .filter(EmailTemplateModel.group_id == self.repos.group_id, EmailTemplateModel.name == d["templateName"])
                        .first()
                    )
                if template is None:
                    self.logger.warning(f"Email subscription skipped — template '{d.get('templateType')}' not found")
                    continue

                existing = (
                    self.repos.session.query(EmailEventSubscriptionModel)
                    .filter(
                        EmailEventSubscriptionModel.group_id == self.repos.group_id,
                        EmailEventSubscriptionModel.template_id == template.id,
                        EmailEventSubscriptionModel.event_type == d.get("eventType"),
                        EmailEventSubscriptionModel.recipient_type == d.get("recipientType"),
                        EmailEventSubscriptionModel.recipient_field == d.get("recipientField"),
                        EmailEventSubscriptionModel.recipient_email == d.get("recipientEmail"),
                    )
                    .first()
                )
                if existing:
                    if not self._overwrite:
                        continue
                    existing.enabled = d.get("enabled", True)
                else:
                    self.repos.session.add(
                        EmailEventSubscriptionModel(
                            session=self.repos.session,
                            group_id=self.repos.group_id,
                            template_id=template.id,
                            event_type=d.get("eventType"),
                            recipient_type=d.get("recipientType"),
                            recipient_field=d.get("recipientField"),
                            recipient_email=d.get("recipientEmail"),
                            enabled=d.get("enabled", True),
                        )
                    )
                self.repos.session.commit()
                count += 1
            except Exception as e:
                self.repos.session.rollback()
                self.logger.error(f"Failed to import email subscription: {e}")
        return count

    def _import_integration_subscriptions(self, rows: list[dict[str, Any]]) -> int:
        if not self.repos.group_id or not rows:
            return 0
        from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel
        from marvin.db.models.groups.integrations import IntegrationModel

        count = 0
        for d in rows:
            try:
                integration = None
                if d.get("integrationSlug"):
                    integration = (
                        self.repos.session.query(IntegrationModel)
                        .filter(IntegrationModel.group_id == self.repos.group_id, IntegrationModel.slug == d["integrationSlug"])
                        .first()
                    )
                if integration is None:
                    self.logger.warning(f"Integration subscription skipped — integration '{d.get('integrationSlug')}' not found")
                    continue

                existing = (
                    self.repos.session.query(IntegrationEventSubscriptionModel)
                    .filter(
                        IntegrationEventSubscriptionModel.group_id == self.repos.group_id,
                        IntegrationEventSubscriptionModel.integration_id == integration.id,
                        IntegrationEventSubscriptionModel.event_type == d.get("eventType"),
                        IntegrationEventSubscriptionModel.action == d.get("action"),
                    )
                    .first()
                )
                if existing:
                    if not self._overwrite:
                        continue
                    existing.args = d.get("args")
                    existing.enabled = d.get("enabled", True)
                else:
                    self.repos.session.add(
                        IntegrationEventSubscriptionModel(
                            session=self.repos.session,
                            group_id=self.repos.group_id,
                            integration_id=integration.id,
                            event_type=d.get("eventType"),
                            action=d.get("action"),
                            args=d.get("args"),
                            enabled=d.get("enabled", True),
                        )
                    )
                self.repos.session.commit()
                count += 1
            except Exception as e:
                self.repos.session.rollback()
                self.logger.error(f"Failed to import integration subscription: {e}")
        return count

    def _link_tags(self, junction_cls, fk_field: str, entity_id: str, tag_slugs: list[str]) -> None:
        """Link an entity to tags by slug through its junction table, creating missing tags.

        Shared by entries/assets/resources — pass the junction model (EntryTags/AssetTags/
        ResourceTags) and its owning FK column name ("entry_id"/"asset_id"/"resource_id").
        """
        for slug in tag_slugs:
            tag = self.repos.tags.find_or_create(slug)
            if tag is None:
                continue
            try:
                exists = (
                    self.repos.session.query(junction_cls).filter(getattr(junction_cls, fk_field) == entity_id, junction_cls.tag_id == tag.id).first()
                )
                if exists is None:
                    self.repos.session.add(junction_cls(**{fk_field: entity_id, "tag_id": tag.id}))
                    self.repos.session.commit()
                    self.logger.debug(f"Tagged {fk_field}={entity_id} with: {slug}")
            except Exception as e:
                self.repos.session.rollback()
                self.logger.error(f"Failed to tag {fk_field}={entity_id} with {slug}: {e}")

    def _assign_to_tags(self, entry_id: str, tag_slugs: list[str]) -> None:
        """Link an entry to tags by slug, creating any missing tag on the fly."""
        from marvin.db.models.platform import EntryTags

        self._link_tags(EntryTags, "entry_id", entry_id, tag_slugs)

    def _assign_to_collections(self, entry_id: str, assignments: list[dict[str, Any]]) -> None:
        """Assign an entry to collections with order.

        Args:
            entry_id: UUID of the entry
            assignments: List of {slug: str, order: int} dicts
        """
        for assignment in assignments:
            collection_slug = assignment["slug"]
            order = assignment.get("order", 0)

            # Look up collection
            collections = self.repos.collections.multi_query({"slug": collection_slug})
            if not collections:
                self.logger.warning(f"Collection not found: {collection_slug}")
                continue

            collection = collections[0]

            # Create junction record
            try:
                # Use the EntryCollections model directly
                from marvin.db.models.platform import EntryCollections

                junction = EntryCollections(
                    entry_id=entry_id,
                    collection_id=collection.id,
                    sort_order=order,
                )
                self.repos.session.add(junction)
                self.repos.session.commit()
                self.logger.debug(f"Added to collection: {collection_slug} (order: {order})")
            except Exception as e:
                self.repos.session.rollback()
                self.logger.error(f"Failed to add to collection {collection_slug}: {e}")

    def _assign_to_assets(self, entry_id: str, assignments: list[dict[str, Any]]) -> None:
        """Link an entry to assets with role and position.

        Args:
            entry_id: UUID of the entry
            assignments: List of {slug: str, role?: str, position?: int, metadataJson?: dict} dicts
        """
        for assignment in assignments:
            asset_slug = assignment["slug"]

            assets = self.repos.assets.multi_query({"slug": asset_slug})
            if not assets:
                self.logger.warning(f"Asset not found: {asset_slug}")
                continue

            try:
                from marvin.db.models.platform import EntryAssets

                junction = EntryAssets(
                    entry_id=entry_id,
                    asset_id=assets[0].id,
                    position=assignment.get("position", 0),
                    role=assignment.get("role"),
                    metadata_json=assignment.get("metadataJson"),
                )
                self.repos.session.add(junction)
                self.repos.session.commit()
                self.logger.debug(f"Linked asset: {asset_slug}")
            except Exception as e:
                self.repos.session.rollback()
                self.logger.error(f"Failed to link asset {asset_slug}: {e}")

    def _send_owner_invitation(self, owner_email: str, workspace) -> None:
        """Create an owner-level invitation token and send it via email.

        Args:
            owner_email: Email address to send the invitation to
            workspace: The workspace GroupRead object
        """
        from marvin.core.config import get_app_settings
        from marvin.core.security import url_safe_token
        from marvin.schemas.group.invite_token import InviteTokenSave
        from marvin.services.email.email_service import EmailService

        settings = get_app_settings()

        # Check if SMTP is enabled
        if not settings.SMTP_ENABLED:
            self.logger.warning(f"SMTP not enabled - cannot send owner invitation to {owner_email}")
            self.logger.info(f"Owner invitation token should be created manually for: {owner_email}")
            return

        # Create an owner-level invitation token with unlimited uses
        token_data = InviteTokenSave(
            token=url_safe_token(),
            group_id=self.repos.group_id,
            uses_left=-1,  # Unlimited uses for owner
            workspace_role="OWNER",
        )

        created_token = self.repos.group_invite_tokens.create(token_data)
        self.logger.info(f"Created owner invitation token for {owner_email}: {created_token.token}")

        # Construct registration URL
        registration_url = f"{settings.BASE_URL}/register?token={created_token.token}"

        # ALWAYS display the registration URL in logs (in case email fails)
        self.logger.info("=" * 80)
        self.logger.info(f"OWNER INVITATION LINK: {registration_url}")
        self.logger.info(f"Recipient: {owner_email}")
        self.logger.info(f"Token: {created_token.token}")
        self.logger.info("=" * 80)

        # Send invitation email
        try:
            email_service = EmailService()
            success = email_service.send_invitation(
                recipient_address=owner_email,
                invitation_url=registration_url,
                group_id=str(self.repos.group_id) if self.repos.group_id else None,
            )

            if success:
                self.logger.info(f"✓ Owner invitation email sent to {owner_email}")
            else:
                self.logger.warning(f"✗ Failed to send owner invitation email to {owner_email}")
                self.logger.warning("Please share the registration link manually (see above)")
        except Exception as e:
            self.logger.error(f"✗ Error sending owner invitation email: {e}")
            self.logger.warning("Please share the registration link manually (see above)")
