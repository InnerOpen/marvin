"""Workspace exporter for dumping workspace data to JSON format."""

import json
import zipfile
from pathlib import Path
from typing import Any

from marvin.core.root_logger import get_logger
from marvin.repos.repository_factory import AllRepositories


class WorkspaceExporter:
    """Exports complete workspace data to JSON format.

    Produces the same format that WorkspaceSeedLoader imports:
    - collections
    - entry_types (workspace-scoped only)
    - entries (with collection, asset, and resource assignments)
    - assets (metadata only, no binary files)
    - resources
    """

    def __init__(self, repos: AllRepositories, logger=None):
        """Initialize exporter with repository access.

        Args:
            repos: Repository factory for database operations
            logger: Optional logger instance
        """
        self.repos = repos
        self.logger = logger or get_logger(__name__)

    def export_workspace(self, include_system_types: bool = False) -> dict[str, Any]:
        """Export complete workspace data to JSON-serializable dict.

        Args:
            include_system_types: Whether to include system entry types in export

        Returns:
            Dictionary with workspace data in seed format
        """
        self.logger.info("Exporting workspace data...")

        export_data: dict[str, Any] = {
            "version": 1,
            "workspace": self._export_workspace_metadata(),
            "site": self._export_site_preferences(),
            "collections": self._export_collections(),
            "tags": self._export_tags(),
            "entry_types": self._export_entry_types(include_system_types),
            "entries": self._export_entries(),
            "assets": self._export_assets(),
            "resources": self._export_resources(),
            "variables": self._export_variables(),
            "ai_settings": self._export_ai_settings(),
            "secrets": self._export_secrets(),
            # Connections & config (credentials travel via the secrets section above, referenced by
            # secret_ref). Notifiers are intentionally omitted — Apprise is moving to an integration.
            "integrations": self._export_integrations(),
            "ai_providers": self._export_ai_providers(),
            "mcp_servers": self._export_mcp_servers(),
            "smtp_profiles": self._export_smtp_profiles(),
            "webhooks": self._export_webhooks(),
            "incoming_webhooks": self._export_incoming_webhooks(),
            "automations": self._export_automations(),
            "scheduled_tasks": self._export_scheduled_tasks(),
            "forms": self._export_forms(),
            "email_templates": self._export_email_templates(),
            "email_subscriptions": self._export_email_subscriptions(),
            "integration_subscriptions": self._export_integration_subscriptions(),
        }

        self.logger.info(
            f"Export complete: {len(export_data['collections'])} collections, "
            f"{len(export_data['tags'])} tags, "
            f"{len(export_data['entry_types'])} entry types, "
            f"{len(export_data['entries'])} entries, "
            f"{len(export_data['assets'])} assets, "
            f"{len(export_data['resources'])} resources, "
            f"{len(export_data['variables'])} variables, "
            f"{len(export_data['secrets'])} secrets, "
            f"{'1' if export_data['ai_settings'] else '0'} AI settings, "
            f"{len(export_data['integrations'])} integrations, "
            f"{len(export_data['ai_providers'])} AI providers, "
            f"{len(export_data['mcp_servers'])} MCP servers, "
            f"{len(export_data['smtp_profiles'])} SMTP profiles, "
            f"{len(export_data['webhooks'])} webhooks, "
            f"{len(export_data['incoming_webhooks'])} incoming webhooks, "
            f"{len(export_data['automations'])} automations, "
            f"{len(export_data['scheduled_tasks'])} scheduled tasks, "
            f"{len(export_data['forms'])} forms, "
            f"{len(export_data['email_templates'])} email templates, "
            f"{len(export_data['email_subscriptions'])} email subscriptions, "
            f"{len(export_data['integration_subscriptions'])} integration subscriptions"
        )

        return export_data

    def export_workspace_bundle(self, include_system_types: bool = False, temp_dir: Path | None = None) -> Path:
        """Export workspace metadata + all asset binaries into a zip bundle.

        Args:
            include_system_types: Whether to include system entry types
            temp_dir: Directory to write the zip file into (defaults to system temp)

        Returns:
            Path to the created zip file
        """
        import secrets
        from datetime import UTC, datetime

        from marvin.services.storage.provider_factory import get_storage_provider

        export_data = self.export_workspace(include_system_types=include_system_types)

        workspace = self.repos.groups.get_one(self.repos.group_id)
        workspace_slug = workspace.slug if workspace else "workspace"

        if temp_dir is None:
            import tempfile

            temp_dir = Path(tempfile.gettempdir())

        token = secrets.token_hex(8)
        basename = f"{workspace_slug}-backup-{datetime.now(UTC).date().isoformat()}-{token}"
        zip_path = temp_dir / f"{basename}.zip"
        storage_provider = get_storage_provider()

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            json_content = json.dumps(export_data, indent=2, ensure_ascii=False)
            zf.writestr(f"{basename}.json", json_content)

            for asset in export_data["assets"]:
                storage_key = asset["storageKey"]
                try:
                    file_data = storage_provider.get(storage_key)
                    zf.writestr(f"files/{storage_key}", file_data.read())
                except FileNotFoundError:
                    self.logger.warning(f"Asset binary missing from storage, skipping binary: {storage_key}")
                except Exception as e:
                    self.logger.warning(f"Failed to read asset {storage_key}: {e}")

        self.logger.info(f"Bundle exported to: {zip_path}")
        return zip_path

    def _export_workspace_metadata(self) -> dict[str, Any]:
        """Export workspace metadata.

        Returns:
            Dictionary with workspace name and owner emails
        """
        workspace = self.repos.groups.get_one(self.repos.group_id)

        if not workspace:
            return {}

        # Get all workspace members with OWNER role
        from marvin.db.models.users.workspace_members import WorkspaceMembers

        owner_members = (
            self.repos.session.query(WorkspaceMembers)
            .filter(
                WorkspaceMembers.group_id == self.repos.group_id,
                WorkspaceMembers.workspace_role == "OWNER",
            )
            .all()
        )

        # Get owner emails
        owner_emails = []
        for member in owner_members:
            user = self.repos.users.get_one(member.user_id)
            if user and user.email:
                owner_emails.append(user.email)

        result: dict[str, Any] = {
            "name": workspace.name,
            # Note: slug NOT exported to prevent conflicts on re-import
            # The workspace will be matched by name, keeping its existing slug
        }

        # Only add ownerEmails if there are any
        if owner_emails:
            result["ownerEmails"] = owner_emails

        return result

    def _export_site_preferences(self) -> dict[str, Any]:
        """Export site preferences/configuration.

        Returns:
            Dictionary with site configuration fields
        """
        prefs_list = self.repos.group_preferences.multi_query({"group_id": self.repos.group_id})

        if not prefs_list:
            return {}

        prefs = prefs_list[0]

        return {
            "title": prefs.site_title,
            "tagline": prefs.site_tagline,
            "description": prefs.site_description,
            "canonicalUrl": prefs.site_canonical_url,
            "logo": prefs.site_logo,
            "favicon": prefs.site_favicon,
            "locale": prefs.site_locale,
            "timezone": prefs.site_timezone,
            "contactEmail": prefs.site_contact_email,
            "social": prefs.site_social_json,
            "metadataJson": prefs.site_metadata_json,
        }

    def _export_collections(self) -> list[dict[str, Any]]:
        """Export all collections.

        Returns:
            List of collection dicts in seed format
        """
        collections = self.repos.collections.get_all(
            limit=None,  # Get all
            order_by="sort_order",
        )

        exported = []
        for coll in collections:
            exported.append(
                {
                    "name": coll.name,
                    "slug": coll.slug,
                    "description": coll.description,
                    "sortOrder": coll.sort_order,
                    "icon": coll.icon,
                    "color": coll.color,
                    "metadataJson": coll.metadata_json,
                }
            )

        return exported

    def _export_tags(self) -> list[dict[str, Any]]:
        """Export the workspace tag vocabulary (slug is the identity; name + color for display).

        Per-entry membership is exported as a slug list on each entry (see _export_entries), so a
        restore can recreate the vocabulary and relink entries without losing display names/colors.
        """
        tags = self.repos.tags.get_all(limit=None, order_by="slug")
        return [{"name": tag.name, "slug": tag.slug, "color": tag.color} for tag in tags]

    def _export_entry_types(self, include_system: bool) -> list[dict[str, Any]]:
        """Export entry types.

        Args:
            include_system: Whether to include system entry types

        Returns:
            List of entry type dicts in seed format
        """
        # Get all entry types (includes workspace and system types via repository filters)
        entry_types = self.repos.entry_types.get_all(
            limit=None,  # Get all
            order_by="sort_order",
        )

        exported = []
        for et in entry_types:
            # Skip system types unless requested
            if not include_system and et.group_id is None:
                continue

            exported.append(
                {
                    "name": et.name,
                    "slug": et.slug,
                    "icon": et.icon,
                    "color": et.color,
                    "description": et.description,
                    "sortOrder": et.sort_order,
                    "schemaJson": et.content_schema,
                    "renderingJson": et.rendering,
                    "capabilitiesJson": et.capabilities,
                    "recipeJson": et.recipe,
                }
            )

        return exported

    def _export_entries(self) -> list[dict[str, Any]]:
        """Export all entries with their collection assignments.

        Returns:
            List of entry dicts in seed format
        """
        entries = self.repos.entries.get_all(
            limit=None,  # Get all
            order_by="slug",
        )

        exported = []
        for entry in entries:
            # Get entry type
            entry_type = self.repos.entry_types.get_one(entry.entry_type_id)
            if not entry_type:
                self.logger.warning(f"Entry type not found for entry: {entry.slug}")
                continue

            # Get collection assignments
            collections_data = self._get_entry_collections(entry.id)

            entry_dict = {
                "entryType": entry_type.slug,
                "title": entry.title,
                "slug": entry.slug,
                "status": entry.status,
                "summary": entry.summary,
                "description": entry.description,
                "data": entry.data_json,
                "metadataJson": entry.metadata_json,
                "publishAt": entry.publish_at.isoformat() if entry.publish_at else None,
                "expireAt": entry.expire_at.isoformat() if entry.expire_at else None,
            }

            # Add entryTypeScope if using a system type (for explicit re-import)
            if entry_type.group_id is None:
                entry_dict["entryTypeScope"] = "system"

            # Only add collections array if there are any
            if collections_data:
                entry_dict["collections"] = collections_data

            assets_data = self._get_entry_assets(entry.id)
            if assets_data:
                entry_dict["assets"] = assets_data

            resources_data = self._get_entry_resources(entry.id)
            if resources_data:
                entry_dict["resources"] = resources_data

            # Tag membership as a slug list — EntryRead.tags is already the slug list (see T4);
            # resolved against the exported vocabulary on import.
            tag_slugs = list(entry.tags or [])
            if tag_slugs:
                entry_dict["tags"] = tag_slugs

            exported.append(entry_dict)

        return exported

    def _get_entry_collections(self, entry_id: str) -> list[dict[str, Any]]:
        """Get collection assignments for an entry.

        Args:
            entry_id: UUID of the entry

        Returns:
            List of {slug: str, order: int} dicts
        """
        from marvin.db.models.platform import EntryCollections

        # Query junction table
        assignments = self.repos.session.query(EntryCollections).filter(EntryCollections.entry_id == entry_id).all()

        collections_data = []
        for assignment in assignments:
            # Get collection to get its slug
            collection = self.repos.collections.get_one(assignment.collection_id)
            if collection:
                collections_data.append(
                    {
                        "slug": collection.slug,
                        "order": assignment.sort_order,
                    }
                )

        return collections_data

    def _get_entry_assets(self, entry_id: str) -> list[dict[str, Any]]:
        """Get asset assignments for an entry.

        Args:
            entry_id: UUID of the entry

        Returns:
            List of {slug, position, role, ...} dicts
        """
        from marvin.db.models.platform import EntryAssets

        assignments = self.repos.session.query(EntryAssets).filter(EntryAssets.entry_id == entry_id).order_by(EntryAssets.position).all()

        assets_data = []
        for assignment in assignments:
            asset = self.repos.assets.get_one(assignment.asset_id)
            if asset:
                entry_asset = {"slug": asset.slug, "position": assignment.position}
                if assignment.role:
                    entry_asset["role"] = assignment.role
                if assignment.metadata_json:
                    entry_asset["metadataJson"] = assignment.metadata_json
                assets_data.append(entry_asset)

        return assets_data

    def _get_entry_resources(self, entry_id: str) -> list[dict[str, Any]]:
        """Get resource assignments for an entry.

        Args:
            entry_id: UUID of the entry

        Returns:
            List of {slug, position, role, ...} dicts
        """
        from marvin.db.models.platform import EntryResources

        assignments = self.repos.session.query(EntryResources).filter(EntryResources.entry_id == entry_id).order_by(EntryResources.position).all()

        resources_data = []
        for assignment in assignments:
            resource = self.repos.resources.get_one(assignment.resource_id)
            if resource:
                entry_resource = {"slug": resource.slug, "position": assignment.position}
                if assignment.role:
                    entry_resource["role"] = assignment.role
                if assignment.metadata_json:
                    entry_resource["metadataJson"] = assignment.metadata_json
                resources_data.append(entry_resource)

        return resources_data

    def _export_assets(self) -> list[dict[str, Any]]:
        """Export all asset metadata (no binary files).

        Returns:
            List of asset dicts in seed format
        """
        assets = self.repos.assets.get_all(
            limit=None,
            order_by="slug",
        )

        exported = []
        for asset in assets:
            asset_dict = {
                "name": asset.name,
                "slug": asset.slug,
                "originalFilename": asset.original_filename,
                # filename + checksum are NOT NULL on the asset — carry them so the bundle is
                # self-complete and restores on any backend without the importer having to derive.
                "filename": asset.filename,
                "checksum": asset.checksum,
                "extension": asset.extension,
                "fileSize": asset.file_size,
                "mimeType": asset.mime_type,
                "assetType": asset.asset_type,
                "storageProvider": asset.storage_provider,
                "storageKey": asset.storage_key,
            }

            if asset.width is not None:
                asset_dict["width"] = asset.width
            if asset.height is not None:
                asset_dict["height"] = asset.height
            if asset.public_url:
                asset_dict["publicUrl"] = asset.public_url
            if asset.alt_text:
                asset_dict["altText"] = asset.alt_text
            if asset.description:
                asset_dict["description"] = asset.description
            if asset.metadata_json:
                asset_dict["metadataJson"] = asset.metadata_json
            tag_slugs = list(getattr(asset, "tags", None) or [])
            if tag_slugs:
                asset_dict["tags"] = tag_slugs

            exported.append(asset_dict)

        return exported

    def _export_resources(self) -> list[dict[str, Any]]:
        """Export all resources.

        Returns:
            List of resource dicts in seed format
        """
        resources = self.repos.resources.get_all(
            limit=None,
            order_by="slug",
        )

        exported = []
        for resource in resources:
            resource_dict = {
                "name": resource.name,
                "slug": resource.slug,
                "resourceType": resource.resource_type,
            }

            if resource.description:
                resource_dict["description"] = resource.description
            if resource.url:
                resource_dict["url"] = resource.url
            if resource.external_id:
                resource_dict["externalId"] = resource.external_id
            if resource.metadata_json:
                resource_dict["metadataJson"] = resource.metadata_json
            tag_slugs = list(getattr(resource, "tags", None) or [])
            if tag_slugs:
                resource_dict["tags"] = tag_slugs

            exported.append(resource_dict)

        return exported

    def _export_variables(self) -> list[dict[str, Any]]:
        """Export workspace variables (plaintext by design — safe to carry in the bundle)."""
        from marvin.db.models.groups.variables import WorkspaceVariable

        rows = (
            self.repos.session.query(WorkspaceVariable)
            .filter(WorkspaceVariable.group_id == self.repos.group_id)
            .order_by(WorkspaceVariable.slug)
            .all()
        )
        return [{"name": v.name, "slug": v.slug, "description": v.description, "value": v.value} for v in rows]

    def _export_ai_settings(self) -> dict[str, Any] | None:
        """Export the workspace AI policy row (config only — references secrets by slug, no key material)."""
        from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

        row = self.repos.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.repos.group_id).first()
        if not row:
            return None

        return {
            "enabled": row.enabled,
            "credentialMode": row.credential_mode,
            "provider": row.provider,
            "model": row.model,
            "secretRef": row.secret_ref,
            "approvalMode": row.approval_mode,
            "invocationSources": row.invocation_sources,
            "operationOverrides": row.operation_overrides,
            "budgetConfig": row.budget_config,
            "loggingConfig": row.logging_config,
            "moderationConfig": row.moderation_config,
            "mediaPresets": row.media_presets,
            "externalMcpEnabled": row.external_mcp_enabled,
            "assistantName": row.assistant_name,
            "personaPrompt": row.persona_prompt,
            "defaultRegister": row.default_register,
        }

    def _export_secrets(self) -> list[dict[str, Any]]:
        """Export workspace secrets with values wrapped by the per-workspace backup key.

        Names/slugs/descriptions travel in the clear so a keyless restore can still recreate the
        secret shells; only the value is encrypted under the backup key. A secret whose value can't
        be resolved (e.g. an external backend miss) is exported metadata-only.
        """
        from marvin.db.models.groups.secrets import WorkspaceSecret
        from marvin.services.backup.keys import encrypt_secret_value, get_or_create_backup_key
        from marvin.services.secrets import get_secret_backend

        rows = (
            self.repos.session.query(WorkspaceSecret)
            .filter(WorkspaceSecret.group_id == self.repos.group_id)
            .order_by(WorkspaceSecret.slug)
            .all()
        )
        if not rows:
            return []

        backup_key = get_or_create_backup_key(self.repos.session, self.repos.group_id)
        backend = get_secret_backend()

        exported = []
        for secret in rows:
            item: dict[str, Any] = {"name": secret.name, "slug": secret.slug, "description": secret.description}
            try:
                value = backend.get(secret.slug, self.repos.group_id)
            except Exception as e:
                self.logger.warning(f"Could not read secret '{secret.slug}' for export: {e}")
                value = None

            if value is not None:
                item["encryptedBackupValue"] = encrypt_secret_value(value, backup_key)
            else:
                self.logger.warning(f"Secret '{secret.slug}' exported as metadata-only (value could not be resolved)")

            exported.append(item)

        return exported

    def _group_rows(self, model, order_col="slug"):
        """Fetch all rows of a group-scoped model for this workspace, ordered for stable output."""
        col = getattr(model, order_col, None)
        q = self.repos.session.query(model).filter(model.group_id == self.repos.group_id)
        return q.order_by(col).all() if col is not None else q.all()

    def _export_integrations(self) -> list[dict[str, Any]]:
        """External service connections. Credential is not on the row — only secret_ref (see secrets)."""
        from marvin.db.models.groups.integrations import IntegrationModel

        return [
            {
                "provider": r.provider,
                "name": r.name,
                "slug": r.slug,
                "enabled": r.enabled,
                "config": r.config,
                "secretRef": r.secret_ref,
            }
            for r in self._group_rows(IntegrationModel)
        ]

    def _export_ai_providers(self) -> list[dict[str, Any]]:
        """AI provider connections with their model catalog nested. Credential via secret_ref."""
        from marvin.db.models.groups.ai_providers import AIModelModel, AIProviderModel

        out = []
        for r in self._group_rows(AIProviderModel):
            models = (
                self.repos.session.query(AIModelModel)
                .filter(AIModelModel.provider_id == r.id)
                .order_by(AIModelModel.model_id)
                .all()
            )
            out.append(
                {
                    "name": r.name,
                    "slug": r.slug,
                    "providerType": r.provider_type,
                    "secretRef": r.secret_ref,
                    "baseUrl": r.base_url,
                    "enabled": r.enabled,
                    "isDefault": r.is_default,
                    "metadataJson": r.metadata_json,
                    "models": [
                        {
                            "name": m.name,
                            "modelId": m.model_id,
                            "isDefault": m.is_default,
                            "contextWindow": m.context_window,
                            "maxOutputTokens": m.max_output_tokens,
                            "supportsVision": m.supports_vision,
                            "supportsTools": m.supports_tools,
                            "enabled": m.enabled,
                        }
                        for m in models
                    ],
                }
            )
        return out

    def _export_mcp_servers(self) -> list[dict[str, Any]]:
        """External MCP server connections. Credential via secret_ref."""
        from marvin.db.models.groups.mcp_servers import WorkspaceMcpServerModel

        return [
            {
                "name": r.name,
                "slug": r.slug,
                "transport": r.transport,
                "url": r.url,
                "secretRef": r.secret_ref,
                "enabled": r.enabled,
                "allowedTools": r.allowed_tools,
            }
            for r in self._group_rows(WorkspaceMcpServerModel)
        ]

    def _export_smtp_profiles(self) -> list[dict[str, Any]]:
        """SMTP connections. The password lives in the secrets section, referenced by secretRef."""
        from marvin.db.models.groups.smtp_profiles import WorkspaceSMTPProfileModel

        return [
            {
                "name": r.name,
                "host": r.host,
                "port": r.port,
                "username": r.username,
                "secretRef": r.secret_ref,
                "fromName": r.from_name,
                "fromEmail": r.from_email,
                "authStrategy": r.auth_strategy,
                "isActive": r.is_active,
            }
            for r in self._group_rows(WorkspaceSMTPProfileModel, order_col="name")
        ]

    def _export_webhooks(self) -> list[dict[str, Any]]:
        """Outgoing webhooks. {{SLUG}} references in headers resolve to secrets at send time."""
        from marvin.db.models.groups.webhooks import GroupWebhooksModel

        return [
            {
                "name": r.name,
                "url": str(r.url) if r.url is not None else None,
                # method/webhook_type are Python enums — export the plain value (json-serializable).
                "method": getattr(r.method, "value", r.method),
                "webhookType": getattr(r.webhook_type, "value", r.webhook_type),
                "enabled": r.enabled,
                "subscribedEvents": r.subscribed_events,
                "headersJson": r.headers_json,
                "customPayload": r.custom_payload,
                "scheduledTime": r.scheduled_time.isoformat() if r.scheduled_time else None,
            }
            for r in self._group_rows(GroupWebhooksModel, order_col="name")
        ]

    def _export_incoming_webhooks(self) -> list[dict[str, Any]]:
        """Inbound webhook endpoints. The token is carried so restored URLs keep working."""
        from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel

        return [
            {
                "name": r.name,
                "slug": r.slug,
                "description": r.description,
                "enabled": r.enabled,
                "token": r.token,
            }
            for r in self._group_rows(WorkspaceIncomingWebhookModel)
        ]

    def _export_automations(self) -> list[dict[str, Any]]:
        """Automation definitions (self-contained JSON referencing other objects by slug)."""
        from marvin.db.models.groups.automations import WorkspaceAutomationModel

        return [
            {"name": r.name, "slug": r.slug, "enabled": r.enabled, "definition": r.definition}
            for r in self._group_rows(WorkspaceAutomationModel)
        ]

    def _export_scheduled_tasks(self) -> list[dict[str, Any]]:
        """Scheduled task definitions. Runtime state (last/next run, counters) is not exported."""
        from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel

        return [
            {
                "name": r.name,
                "slug": r.slug,
                "description": r.description,
                "enabled": r.enabled,
                "scheduleType": r.schedule_type,
                "scheduleConfig": r.schedule_config,
                "taskType": r.task_type,
                "taskConfig": r.task_config,
                "retryPolicy": r.retry_policy,
            }
            for r in self._group_rows(ScheduledTaskModel)
        ]

    def _export_forms(self) -> list[dict[str, Any]]:
        """Form definitions. Submissions are not exported."""
        from marvin.db.models.platform.forms import Forms

        return [
            {
                "slug": r.slug,
                "name": r.name,
                "description": r.description,
                "schemaJson": r.schema_json,
                "settingsJson": r.settings_json,
                "metadataJson": r.metadata_json,
                "status": getattr(r.status, "value", r.status),
            }
            for r in self._group_rows(Forms)
        ]

    def _export_email_templates(self) -> list[dict[str, Any]]:
        """Workspace email templates (keyed by template_type on restore)."""
        from marvin.db.models.groups.email_templates import EmailTemplateModel

        return [
            {
                "templateType": r.template_type,
                "name": r.name,
                "description": r.description,
                "subject": r.subject,
                "customHtml": r.custom_html,
                "bodyMarkdown": r.body_markdown,
                "availableVariables": r.available_variables,
                "enabled": r.enabled,
            }
            for r in self._group_rows(EmailTemplateModel, order_col="template_type")
        ]

    def _export_email_subscriptions(self) -> list[dict[str, Any]]:
        """Email event subscriptions. The template FK is exported as its type for re-resolution."""
        from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel
        from marvin.db.models.groups.email_templates import EmailTemplateModel

        out = []
        for r in self._group_rows(EmailEventSubscriptionModel, order_col="event_type"):
            template = self.repos.session.query(EmailTemplateModel).filter(EmailTemplateModel.id == r.template_id).first()
            out.append(
                {
                    "templateType": template.template_type if template else None,
                    "templateName": template.name if template else None,
                    "eventType": r.event_type,
                    "recipientType": r.recipient_type,
                    "recipientField": r.recipient_field,
                    "recipientEmail": r.recipient_email,
                    "enabled": r.enabled,
                }
            )
        return out

    def _export_integration_subscriptions(self) -> list[dict[str, Any]]:
        """Integration event subscriptions. The integration FK is exported as its slug."""
        from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel
        from marvin.db.models.groups.integrations import IntegrationModel

        out = []
        for r in self._group_rows(IntegrationEventSubscriptionModel, order_col="event_type"):
            integration = self.repos.session.query(IntegrationModel).filter(IntegrationModel.id == r.integration_id).first()
            out.append(
                {
                    "integrationSlug": integration.slug if integration else None,
                    "eventType": r.event_type,
                    "action": r.action,
                    "args": r.args,
                    "enabled": r.enabled,
                }
            )
        return out
