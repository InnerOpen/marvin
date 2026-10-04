"""
This module provides specific seeder implementations for various data types
within the Marvin application.

Currently, it includes:
- `SystemEntryTypeSeeder`: For seeding system-level entry types from a JSON file.
"""

import json
import pathlib
from collections.abc import Generator

# from functools import cached_property # This import was not used
from marvin.schemas.platform import EntryTypeCreate

from .abstract_seeder import AbstractSeeder  # Base seeder class
from .resources import system_entry_types as default_system_entry_types_resource


class SystemEntryTypeSeeder(AbstractSeeder):
    """
    A seeder for populating the database with system-level entry types.

    System entry types are globally available to all workspaces and cannot
    be modified or deleted. They have group_id=NULL and is_system=True.
    """

    def get_file(self, name: str) -> pathlib.Path:
        """
        Determines the path to the system entry types JSON file.

        Args:
            name (str): The name of the seeder configuration (e.g., "system_entry_types").

        Returns:
            pathlib.Path: The path to the JSON file to be loaded.
        """
        # Construct path for user-overrideable seed data
        locale_specific_path = self.directories.SEED_DIR / "system_entry_types" / f"{name}.json"

        if locale_specific_path.exists():
            self.logger.info(f"Using locale-specific system entry types file: {locale_specific_path}")
            return locale_specific_path
        else:
            # Fallback to the default packaged resource file
            default_path = getattr(default_system_entry_types_resource, "system_entry_types", None)
            if not isinstance(default_path, pathlib.Path) or not default_path.exists():
                raise FileNotFoundError("Default system_entry_types.json resource not found or configured incorrectly.")
            self.logger.info(f"Using default system entry types file: {default_path}")
            return default_path

    def load_data(self, name: str) -> Generator[EntryTypeCreate, None, None]:
        """
        Loads system entry type data from the determined JSON file.

        Args:
            name (str): The name of the seeder configuration, passed to `get_file`.

        Yields:
            Generator[EntryTypeCreate, None, None]: A generator of
                Pydantic schemas ready for database insertion.
        """
        json_file_path = self.get_file(name)
        file_content = json_file_path.read_text(encoding="utf-8")
        entry_types_data = json.loads(file_content)

        seen_slugs = set()  # To track slugs and avoid duplicates
        for entry_type_dict in entry_types_data:
            slug = entry_type_dict.get("slug")
            if not slug:
                self.logger.warning(f"Skipping entry type due to missing 'slug': {entry_type_dict}")
                continue

            if slug in seen_slugs:
                self.logger.warning(f"Skipping duplicate entry type slug: '{slug}'")
                continue

            seen_slugs.add(slug)
            try:
                yield EntryTypeCreate(**entry_type_dict)
            except Exception as e:  # Catch Pydantic validation errors or other issues
                self.logger.error(f"Error validating entry type data '{slug}': {e}. Data: {entry_type_dict}")

    def seed(self, name: str | None = None) -> None:
        """
        Seeds the database with system entry types.

        System entry types are created with group_id=NULL so they're globally
        available to all workspaces. Uses upsert logic based on slug to avoid duplicates.

        Args:
            name (str): The name of the seeder configuration, typically
                        "system_entry_types", which is passed to `load_data`.
        """
        name = name or "system_entry_types"
        self.logger.info(f"Seeding System Entry Types from configuration: '{name}'")
        count_seeded = 0
        count_updated = 0
        count_errors = 0

        from marvin.db.models.platform.entry_types import EntryTypes

        for entry_type_schema in self.load_data(name):
            try:
                # Check if system entry type with this slug already exists
                # Query the table directly, not through the repository
                existing = (
                    self.repos.session.query(EntryTypes)
                    .filter(
                        EntryTypes.slug == entry_type_schema.slug,
                        EntryTypes.group_id.is_(None),
                    )
                    .first()
                )

                if existing:
                    # Update existing system entry type
                    # Remap Pydantic field names to DB column names
                    field_to_column = {
                        "content_schema": "schema_json",
                        "rendering": "rendering_json",
                        "capabilities": "capabilities_json",
                        "recipe": "recipe_json",
                    }
                    for key, value in entry_type_schema.model_dump(exclude_unset=True).items():
                        column_name = field_to_column.get(key, key)
                        setattr(existing, column_name, value)
                    self.repos.session.commit()
                    self.logger.debug(f"Updated system entry type: {entry_type_schema.slug}")
                    count_updated += 1
                else:
                    # Create new system entry type with group_id=NULL
                    # Create using raw SQLAlchemy insert to bypass repository and auto_init validation
                    from sqlalchemy import insert

                    insert_stmt = insert(EntryTypes.__table__).values(
                        group_id=None,
                        name=entry_type_schema.name,
                        slug=entry_type_schema.slug,
                        icon=entry_type_schema.icon,
                        color=entry_type_schema.color,
                        description=entry_type_schema.description,
                        sort_order=entry_type_schema.sort_order,
                        is_system=entry_type_schema.is_system,
                        # Raw insert bypasses the ORM default=False, and the schema field is optional
                        # (None) — coerce so a NOT NULL boolean column never receives NULL (Postgres).
                        is_rendered=bool(entry_type_schema.is_rendered),
                        schema_json=entry_type_schema.content_schema or {},
                        rendering_json=entry_type_schema.rendering,
                        capabilities_json=entry_type_schema.capabilities,
                        recipe_json=entry_type_schema.recipe,
                    )
                    self.repos.session.execute(insert_stmt)
                    self.repos.session.commit()
                    self.logger.debug(f"Created system entry type: {entry_type_schema.slug}")
                    count_seeded += 1

            except Exception as e:  # Catch database errors or other issues
                # Postgres aborts the whole transaction on a failed statement; roll back so the next
                # item — and everything init_db does after this seeder — isn't poisoned. (SQLite got
                # away without this because each item commits individually.)
                self.repos.session.rollback()
                self.logger.error(f"Failed to seed system entry type '{entry_type_schema.slug}': {e}")
                count_errors += 1

        self.logger.info(f"System entry types seeding complete. Created: {count_seeded}, Updated: {count_updated}, Errors: {count_errors}")
