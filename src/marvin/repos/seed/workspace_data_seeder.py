"""Workspace data seeder for creating entries from seed files."""

import json
from pathlib import Path
from typing import Any

from marvin.core.root_logger import get_logger
from marvin.repos.repository_factory import AllRepositories


class WorkspaceDataSeeder:
    """Seeds workspace entries from JSON files in the seeds directory.

    Expected JSON format:
    {
        "entry_types": [
            {
                "name": "Project",
                "slug": "project",
                "icon": "🧥",
                "color": "#7C4A2D",
                "description": "A project entry type",
                "sortOrder": 100,
                "schemaJson": {
                    "fields": [...]
                }
            }
        ],
        "entries": [
            {
                "entry_type": "project",  # entry type slug
                "slug": "my-project",
                "title": "My Project",
                "status": "published",
                "summary": "Short description",
                "data": {
                    # Fields matching the entry type's schema
                    "overview": "Project overview markdown...",
                    "status": "active"
                },
                "metadata": {
                    # Optional metadata
                    "legacy_id": "project-001"
                },
                "collections": ["featured"],  # Optional collection slugs
                "publish_at": "2026-01-01T00:00:00Z",  # Optional
                "expire_at": null
            }
        ]
    }
    """

    def __init__(self, repos: AllRepositories, logger=None):
        """Initialize seeder with repository access.

        Args:
            repos: Repository factory for database operations
            logger: Optional logger instance
        """
        self.repos = repos
        self.logger = logger or get_logger(__name__)

    def seed_from_directory(self, seed_dir: Path) -> dict[str, int]:
        """Seed entries from all JSON files in the given directory.

        Args:
            seed_dir: Path to directory containing seed JSON files

        Returns:
            Dictionary with counts: {created: int, updated: int, errors: int}
        """
        if not seed_dir.exists():
            self.logger.debug(f"Seed directory does not exist: {seed_dir}")
            return {"created": 0, "updated": 0, "errors": 0}

        if not seed_dir.is_dir():
            self.logger.warning(f"Seed path is not a directory: {seed_dir}")
            return {"created": 0, "updated": 0, "errors": 0}

        results = {"created": 0, "updated": 0, "errors": 0}

        # Process all .json files in the directory (excluding workspace-*.json files
        # which are handled by WorkspaceSeedLoader)
        json_files = sorted([f for f in seed_dir.glob("*.json") if not f.name.startswith("workspace-")])

        if not json_files:
            self.logger.debug(f"No JSON files found in: {seed_dir}")
            return results

        self.logger.info(f"Processing {len(json_files)} seed file(s) from: {seed_dir}")

        for json_file in json_files:
            try:
                self.logger.info(f"Seeding from: {json_file.name}")
                file_results = self._seed_from_file(json_file)
                results["created"] += file_results["created"]
                results["updated"] += file_results["updated"]
                results["errors"] += file_results["errors"]
            except Exception as e:
                self.logger.error(f"Failed to process seed file {json_file.name}: {e}")
                results["errors"] += 1

        self.logger.info(f"Workspace seeding complete. Created: {results['created']}, Updated: {results['updated']}, Errors: {results['errors']}")

        return results

    def _seed_from_file(self, json_file: Path) -> dict[str, int]:
        """Process a single seed file.

        Args:
            json_file: Path to JSON seed file

        Returns:
            Dictionary with counts for this file
        """
        results = {"created": 0, "updated": 0, "errors": 0}

        # Load JSON data
        with open(json_file) as f:
            data = json.load(f)

        # Validate structure
        if not isinstance(data, dict):
            raise ValueError(f"Seed file must be a JSON object, got: {type(data)}")

        # Process entry types first (if present)
        entry_types = data.get("entry_types", [])
        if entry_types:
            if not isinstance(entry_types, list):
                raise ValueError(f"'entry_types' must be an array, got: {type(entry_types)}")

            self.logger.info(f"Found {len(entry_types)} entry types to seed in {json_file.name}")

            for idx, entry_type_data in enumerate(entry_types):
                try:
                    self._seed_entry_type(entry_type_data)
                    results["created"] += 1
                except Exception as e:
                    self.logger.error(f"Failed to seed entry type #{idx + 1} in {json_file.name}: {e}")
                    results["errors"] += 1

        # Process entries (if present)
        entries = data.get("entries", [])
        if entries:
            if not isinstance(entries, list):
                raise ValueError(f"'entries' must be an array, got: {type(entries)}")

            self.logger.info(f"Found {len(entries)} entries to seed in {json_file.name}")

            for idx, entry_data in enumerate(entries):
                try:
                    self._seed_entry(entry_data)
                    results["created"] += 1
                except Exception as e:
                    self.logger.error(f"Failed to seed entry #{idx + 1} in {json_file.name}: {e}")
                    results["errors"] += 1

        return results

    def _seed_entry_type(self, entry_type_data: dict[str, Any]) -> None:
        """Create or update a single entry type from seed data.

        Args:
            entry_type_data: Entry type definition from seed file
        """
        # Validate required fields
        if "slug" not in entry_type_data:
            raise ValueError("Entry type must have 'slug' field")

        if "name" not in entry_type_data:
            raise ValueError("Entry type must have 'name' field")

        # Check if entry type already exists in THIS workspace (not system types)
        # Need to check both slug AND group_id to respect UNIQUE (group_id, slug) constraint
        existing_types = self.repos.entry_types.multi_query({"slug": entry_type_data["slug"], "group_id": self.repos.group_id})

        if existing_types:
            # Entry type exists in workspace - skip for now (idempotent behavior)
            self.logger.debug(f"Entry type already exists in workspace, skipping: {entry_type_data['slug']}")
            return

        # Prepare entry type data
        create_data = {
            "name": entry_type_data["name"],
            "slug": entry_type_data["slug"],
            "icon": entry_type_data.get("icon"),
            "color": entry_type_data.get("color"),
            "description": entry_type_data.get("description"),
            "sort_order": entry_type_data.get("sortOrder", 0),
            "content_schema": entry_type_data.get("schemaJson", {}),
            "rendering": entry_type_data.get("renderingJson"),
            "capabilities": entry_type_data.get("capabilitiesJson"),
            "recipe": entry_type_data.get("recipeJson"),
            "page_url_pattern": entry_type_data.get("pageUrlPattern"),
        }

        # Create entry type
        entry_type = self.repos.entry_types.create(create_data)
        self.logger.info(f"Created entry type: {entry_type.slug}")

    def _seed_entry(self, entry_data: dict[str, Any]) -> None:
        """Create or update a single entry from seed data.

        Args:
            entry_data: Entry definition from seed file
        """
        # Validate required fields
        if "entry_type" not in entry_data:
            raise ValueError("Entry must have 'entry_type' field")

        if "slug" not in entry_data:
            raise ValueError("Entry must have 'slug' field")

        if "title" not in entry_data:
            raise ValueError("Entry must have 'title' field")

        # Get entry type - handle explicit scope or auto-prefer workspace over system
        entry_type_slug = entry_data["entry_type"]
        entry_type_scope = entry_data.get("entry_type_scope")  # Optional: "system", "workspace", or None

        if entry_type_scope == "system":
            # Explicitly use system type
            entry_types = self.repos.entry_types.multi_query({"slug": entry_type_slug, "group_id": None})
        elif entry_type_scope == "workspace":
            # Explicitly use workspace type
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

        # Check if entry already exists by slug
        existing_entries = self.repos.entries.multi_query({"slug": entry_data["slug"]})

        if existing_entries:
            # Entry exists - skip for now (idempotent behavior)
            # Later we can add update logic if needed
            self.logger.debug(f"Entry already exists, skipping: {entry_data['slug']}")
            return

        # Prepare entry data
        create_data = {
            "entry_type_id": entry_type.id,
            "title": entry_data["title"],
            "slug": entry_data["slug"],
            "status": entry_data.get("status", "draft"),
            "summary": entry_data.get("summary"),
            "description": entry_data.get("description"),
            "data_json": entry_data.get("data", {}),
            "metadata_json": entry_data.get("metadata"),
            "publish_at": entry_data.get("publish_at"),
            "expire_at": entry_data.get("expire_at"),
        }

        # Create entry
        entry = self.repos.entries.create(create_data)
        self.logger.info(f"Created entry: {entry.slug} (type: {entry_type_slug})")

        # Handle collections if specified
        collection_slugs = entry_data.get("collections", [])
        if collection_slugs:
            # TODO: Add entries to collections
            # This requires looking up collections by slug and creating junction records
            self.logger.debug(f"Collections specified but not yet implemented: {collection_slugs}")
