"""
This module defines the specialized repository for managing Group entities.

It provides the `RepositoryGroup` class, which extends `RepositoryGeneric`
to include group-specific operations such as automatic slug generation,
handling of unique name constraints with retries, and fetching groups
by name or slug/ID.
"""

from collections.abc import Iterable
from typing import cast
from uuid import UUID as PyUUID  # Alias UUID to avoid confusion with pydantic.UUID4

from pydantic import UUID4  # For type hinting
from slugify import slugify  # For generating URL-friendly slugs
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError  # For handling database constraint violations

from marvin.db.models.groups import Groups as GroupsModel  # Aliased for clarity
from marvin.schemas.group import GroupCreate, GroupRead, GroupUpdate
from marvin.services.group.workspace_rename import find_group_by_slug, slug_is_alias_of_another

from .repository_generic import RepositoryGeneric


class RepositoryGroup(RepositoryGeneric[GroupRead, GroupsModel]):
    """
    Specialized repository for Group entities.

    This repository handles CRUD operations for Groups, with additional logic
    for generating slugs from group names and ensuring unique names/slugs
    through a retry mechanism during creation.
    """

    def create(self, data: GroupCreate | dict) -> GroupRead:
        """
        Creates a new group with automatic slug generation and retry on name collision.

        If the initial name (and resulting slug) causes an IntegrityError (e.g., due
        to a unique constraint violation), it attempts to create the group with an
        appended counter (e.g., "Original Name (1)") up to a maximum number of attempts.

        Args:
            data (GroupCreate | dict): The data for the new group. Can be a
                                       Pydantic schema or a dictionary.

        Returns:
            GroupRead: The Pydantic schema of the created group.

        Raises:
            IntegrityError: If a unique group cannot be created after max_attempts.
        """
        if isinstance(data, GroupCreate):
            # Convert Pydantic model to dictionary for manipulation
            data_dict = data.model_dump()
        else:
            # Ensure we are working with a copy if it's a dictionary
            data_dict = data.copy()

        max_attempts = 10
        original_name = cast(str, data_dict["name"])  # Keep track of the original name for retries
        current_name = original_name

        attempts = 0
        while True:
            data_dict["name"] = current_name  # Use current (potentially modified) name
            data_dict["slug"] = slugify(current_name)  # Generate slug from current name
            if slug_is_alias_of_another(self.session, data_dict["slug"]):
                # A renamed workspace's old slug: taking it would hijack that workspace's old links.
                attempts += 1
                if attempts >= max_attempts:
                    raise ValueError(f"Can't find a free slug for '{original_name}'.")
                current_name = f"{original_name} ({attempts})"
                continue

            try:
                # Attempt to create the group using the generic superclass method
                created_group = super().create(data_dict)
                return created_group
            except IntegrityError:
                self.session.rollback()  # Rollback the failed transaction
                attempts += 1
                if attempts >= max_attempts:
                    # If max attempts reached, re-raise the last IntegrityError
                    raise

                # Modify name for the next attempt
                current_name = f"{original_name} ({attempts})"

    def create_many(self, data: Iterable[GroupCreate | dict]) -> list[GroupRead]:
        """
        Creates multiple groups, applying the specialized `create` logic for each.

        This method iterates over the provided data and calls the overridden `create`
        method for each item, ensuring that slug generation and name collision
        handling are applied individually.

        Args:
            data (Iterable[GroupCreate | dict]): An iterable of group data.

        Returns:
            list[GroupRead]: A list of created group schemas.
        """
        # Since `create` has special logic (slug generation, retry),
        # we call it for each item instead of using `super().create_many`.
        return [self.create(new_group_data) for new_group_data in data]

    def update(self, match_value: str | int | UUID4, new_data: GroupUpdate | dict, match_key: str | None = None) -> GroupRead:
        """
        Updates an existing group, automatically regenerating the slug if the name changes.

        Args:
            match_value (str | int | UUID4): The value to match for identifying the
                                             group to update (e.g., ID or current slug).
                                             The matching key is determined by `self.match_key`.
            new_data (GroupUpdate | dict): The new data for the group. If `name` is
                                           present, the `slug` will be updated accordingly.

        Returns:
            GroupRead: The Pydantic schema of the updated group.
        """
        if isinstance(new_data, GroupUpdate):
            data_dict = new_data.model_dump(exclude_unset=True)  # Prepare data for update
            if "name" in data_dict:  # If name is being updated, regenerate slug
                data_dict["slug"] = slugify(data_dict["name"])
        elif isinstance(new_data, dict):
            data_dict = new_data.copy()  # Work with a copy
            if "name" in data_dict:
                data_dict["slug"] = slugify(data_dict["name"])
        else:
            # Should not happen if type hints are respected
            raise TypeError("new_data must be of type GroupUpdate or dict")

        return super().update(match_value, data_dict, match_key=match_key)

    def update_many(self, data: Iterable[GroupUpdate | dict]) -> list[GroupRead]:
        """
        Updates multiple groups, applying the specialized `update` logic for each.

        This method iterates through the provided data, identifying each group by its 'id'
        (if data is a dict) or `group.id` (if data is a Pydantic model), and calls
        the overridden `update` method for each.

        Args:
            data (Iterable[GroupUpdate | dict]): An iterable of group update data.
                                                 Each item must contain an 'id' or be a model
                                                 with an `id` attribute.
        Returns:
            list[GroupRead]: A list of updated group schemas.
        """
        # Since `update` has special logic (slug generation),
        # we call it for each item.
        updated_groups = []
        for group_data in data:
            group_id = group_data.get("id") if isinstance(group_data, dict) else getattr(group_data, "id", None)
            if group_id is None:
                # Handle cases where ID is missing, e.g., skip or raise error
                # For now, let's assume ID is present or `update` will handle it.
                # Depending on `RepositoryGeneric.update`'s `match_key` this might fail.
                # If `match_key` is not 'id', this needs adjustment.
                # Assuming default `match_key` is 'id' for this example.
                raise ValueError("Group ID not found for update_many operation.")  # Or log and continue

            # The first argument to update is `match_value`. If the generic update uses 'id' as match_key:
            updated_groups.append(self.update(group_id, group_data))
        return updated_groups

    def get_by_name(self, name: str) -> GroupRead | None:
        """
        Retrieves a group by its exact name.

        Args:
            name (str): The name of the group to retrieve.

        Returns:
            GroupRead | None: The group schema if found, otherwise None.
        """
        db_group = self.session.execute(select(self.model).filter_by(name=name)).scalars().one_or_none()

        if db_group is None:
            return None
        return self.schema.model_validate(db_group)

    def get_by_slug_or_id(self, slug_or_id: str | PyUUID | UUID4) -> GroupRead | None:
        """
        Retrieves a group by its slug or ID.

        It first attempts to treat `slug_or_id` as a UUID. If that fails
        (or if it's not a UUID type), it then tries to match by slug, including slugs the group
        had before a rename.

        Args:
            slug_or_id (str | PyUUID | UUID4): The slug (string) or ID (UUID) of the group.

        Returns:
            GroupRead | None: The group schema if found, otherwise None.
        """
        if isinstance(slug_or_id, PyUUID):  # Check if it's already a UUID object
            return self.get_one(slug_or_id, key="id")  # Use 'id' as the key for lookup
        elif isinstance(slug_or_id, str):
            # Try to convert string to UUID first, in case an ID was passed as string
            try:
                uuid_obj = PyUUID(slug_or_id)
                # If conversion succeeds, it might be an ID
                group_by_id = self.get_one(uuid_obj, key="id")
                if group_by_id:
                    return group_by_id
            except ValueError:
                # Conversion to UUID failed, so it's likely a slug
                pass
            # If not found by ID (or wasn't a valid UUID string), try by slug — current, then former
            # (a renamed workspace keeps answering to its old slug, see services.group.workspace_rename).
            group = find_group_by_slug(self.session, slug_or_id)
            return self.schema.model_validate(group) if group else None

        return None  # Should not be reached if type hints are correct

    def get_all_models(self) -> list[GroupsModel]:
        """
        Get all groups in the system as raw ORM model instances.

        Distinct from the generic ``get_all`` (which returns ``GroupRead`` schemas);
        callers that need the ORM objects (e.g. relationship access) use this.

        Returns:
            List of all group model instances.
        """
        stmt = select(self.model).order_by(self.model.name)
        return list(self.session.execute(stmt).scalars().all())
