"""
This module defines the `RegistrationService` for handling new user registrations
within the Marvin application.

It encapsulates the business logic for user creation, including validation of
username and email uniqueness, processing of group invitation tokens, creation
of new groups if specified, and assignment of initial permissions.
"""

from logging import Logger  # For type hinting logger
from uuid import uuid4  # For generating UUIDs if needed (e.g., for preferences)

from fastapi import HTTPException, status  # For raising HTTP exceptions

# Marvin core, repository, schema, and service imports
from marvin.core.security import hash_password  # For hashing new user passwords
from marvin.repos.repository_factory import AllRepositories  # Central repository access
from marvin.schemas.group import GroupCreate, GroupRead  # Pydantic schemas for Group
from marvin.schemas.group.preferences import GroupPreferencesCreate  # Schema for creating group preferences
from marvin.schemas.user import PrivateUser, UserCreate  # Pydantic schemas for User
from marvin.schemas.user.registration import UserRegistrationCreate  # Schema for registration data
from marvin.services.group.group_service import GroupService  # Service for group creation
from marvin.services.seeders.seeder_service import SeederService  # Service for seeding data (e.g., for new groups)


class RegistrationService:
    """
    Service layer for handling the user registration process.

    This service manages the creation of new users, including validation checks,
    group assignment (either via token or new group creation), and setting
    initial permissions. It interacts with various repositories for data
    persistence and other services for tasks like group creation or data seeding.
    """

    logger: Logger
    """Logger instance for logging registration events and errors."""
    repos: AllRepositories
    """Instance of `AllRepositories` for database interactions."""
    registration: UserRegistrationCreate  # Stores the current registration data being processed
    """
    The `UserRegistrationCreate` data for the user currently being registered.
    This attribute is set by the `register_user` method.
    """

    def __init__(self, logger: Logger, repos: AllRepositories) -> None:  # Renamed `db` to `db_repos`
        """
        Initializes the RegistrationService.

        Args:
            logger (Logger): An instance of a logger for logging messages.
            db_repos (AllRepositories): An instance of `AllRepositories` providing
                                     access to all necessary data repositories.
        """
        self.logger = logger
        self.repos = repos
        # `self.registration` will be set when `register_user` is called.

    def _create_new_user(self, target_group: GroupRead, is_new_group: bool) -> PrivateUser:  # Renamed params
        """
        Creates a new user record in the database with specified details and permissions.

        The user's password is hashed before storage. Initial permissions
        (`can_invite`, `can_manage`, `can_organize`) are set to True if `is_new_group`
        is True (i.e., the user created the group, making them its initial admin).

        Args:
            target_group (GroupRead): The group the new user will belong to.
            is_new_group (bool): True if this user is being created as part of
                                 registering a new group.

        Returns:
            PrivateUser: The Pydantic schema of the newly created user.

        Note:
            The original code had a `# TODO: problem with repository type, not type here`
            and `type: ignore` on `self.repos.users.create(new_user)`. This implies
            a potential type mismatch or issue with how the `users` repository's `create`
            method is typed or expects data, versus the `UserCreate` schema.
            Assuming `UserCreate` is compatible or that the type hint on repo is broad.
        """
        # Prepare user data for creation using the UserCreate schema
        new_user_data = UserCreate(
            email=self.registration.email,
            username=self.registration.username,
            password=hash_password(self.registration.password),  # Hash the password
            full_name=self.registration.full_name,
            advanced=self.registration.advanced,  # From registration form
            group=target_group.name,  # Assign to the target group by name (repo might resolve to ID)
            # UserCreate's validator for `group` handles object with name attribute
            # Initial permissions: if it's a new group, the creator gets full permissions for that group.
            can_invite=is_new_group,
            can_manage=is_new_group,
            can_organize=is_new_group,
            # `admin` (system-wide) status is not set here, defaults to False as per UserCreate.
        )

        # Create the user via the users repository
        # TODO: Address the type ignore: "problem with repository type, not type here"
        # This suggests self.repos.users.create might expect a dict or a different Pydantic model.
        # For now, assuming it works with UserCreate or a compatible dict.
        created_user = self.repos.users.create(new_user_data)  # type: ignore
        self.logger.info(f"User '{created_user.username}' created successfully in group '{target_group.name}'.")

        # Add user to workspace_members with appropriate role
        from marvin.db.models.users.workspace_members import WorkspaceMembers

        # Determine role: OWNER for new group creators, otherwise use token's specified role
        if is_new_group:
            workspace_role = "OWNER"
        else:
            # Get role from the invitation token (stored in self.registration context)
            # The token was fetched earlier in register_user, we need to pass it down
            workspace_role = getattr(self, "_invite_token_role", "EDITOR")

        workspace_member = WorkspaceMembers(
            session=self.repos.session,
            user_id=created_user.id,
            group_id=target_group.id,
            workspace_role=workspace_role,
        )
        self.repos.session.add(workspace_member)
        self.repos.session.commit()  # Commit the workspace membership
        self.logger.info(f"User '{created_user.username}' added to workspace '{target_group.name}' with role '{workspace_role}'.")

        return created_user

    def _register_new_group(self) -> GroupRead:
        """
        Creates a new group based on the information provided in `self.registration`.

        This internal method is called when a user registers and specifies a new group
        to be created. It also initializes default preferences for the new group.

        Returns:
            GroupRead: The Pydantic schema of the newly created group.

        Note:
            Relies on `self.registration` having been set by `register_user` and
            containing `group` (new group name) and `private` (privacy setting).
        """
        if not self.registration.group:  # Should be validated before calling this method
            raise ValueError("Group name must be provided in registration data to create a new group.")

        self.logger.info(f"Registering new group: {self.registration.group}")
        # Prepare data for the new group
        group_creation_data = GroupCreate(name=self.registration.group)

        # Prepare default preferences for the new group
        # A UUID for preferences `group_id` is generated here but `GroupService.create_group`
        # will assign the actual new group's ID to `prefs.group_id`.
        # This `group_id=uuid4()` is effectively a placeholder if `prefs_data` is passed to `create_group`.
        # `GroupPreferencesCreate` now includes all fields, so they can be set from `self.registration`.
        group_preferences_data = GroupPreferencesCreate(
            group_id=uuid4(),  # Placeholder, will be overridden by GroupService.create_group
            private_group=self.registration.private,  # Use privacy setting from registration form
            # first_day_of_week will use its default from GroupPreferencesCreate schema
        )

        # Use GroupService to create the group and its preferences
        # `self.repos` is passed, which should be a non-group-scoped repository instance.
        newly_created_group = GroupService.create_group(self.repos, group_creation_data, group_preferences_data)
        self.logger.info(f"New group '{newly_created_group.name}' (ID: {newly_created_group.id}) created successfully.")
        return newly_created_group

    def register_user(self, registration_data: UserRegistrationCreate) -> PrivateUser:  # Renamed `registration`
        """
        Handles the overall user registration process.

        Validates inputs, checks for existing username/email, processes group tokens
        or creates new groups, creates the user, and handles post-registration actions
        like data seeding (if applicable) and token usage updates.

        Args:
            registration_data (UserRegistrationCreate): Data submitted by the user for registration.

        Returns:
            PrivateUser: The Pydantic schema of the successfully registered user.

        Raises:
            HTTPException (409 Conflict): If the username or email already exists.
            HTTPException (400 Bad Request): If group information is missing or a
                                           group token is invalid.
        """
        self.registration = registration_data  # Store registration data for use in helper methods

        # Check for existing username or email to prevent duplicates
        if self.registration.username and self.repos.users.get_by_username(self.registration.username):
            self.logger.warning(f"Registration attempt with existing username: {self.registration.username}")
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists.")
        if self.repos.users.get_one(self.registration.email, key="email"):  # Email is always required
            self.logger.warning(f"Registration attempt with existing email: {self.registration.email}")
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email address already registered.")

        target_group: GroupRead | None = None
        is_new_group_being_created = False  # Flag to indicate if a new group was created in this process
        group_invite_token_entry = None  # To store details of a used group token

        # Determine the group for the new user:
        if self.registration.group_token:  # User is registering with a group invitation token
            self.logger.info(f"Processing registration with group token for user: {self.registration.email}")
            group_invite_token_entry = self.repos.group_invite_tokens.get_one(self.registration.group_token, key="token")  # Use key="token"
            if not group_invite_token_entry or group_invite_token_entry.uses_left == 0:  # Check if token is valid and has uses left
                self.logger.warning("Invalid or expired group token used")
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired group invitation token.")

            target_group = self.repos.groups.get_one(group_invite_token_entry.group_id)
            if target_group is None:  # Should not happen if token is valid and DB consistent
                self.logger.error(f"Group ID {group_invite_token_entry.group_id} from token not found.")
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Group associated with token not found.")

            # Store the token's workspace role for use when creating workspace membership
            self._invite_token_role = group_invite_token_entry.workspace_role

        elif self.registration.group:  # User is specifying a new group name to create
            is_new_group_being_created = True
            target_group = self._register_new_group()  # This creates the group and its preferences
        else:  # Neither token nor new group name provided
            self.logger.warning(f"Registration attempt without group token or new group name for email: {self.registration.email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A group invitation token or a new group name must be provided for registration.",
            )

        if not target_group:  # Should have been set by one of the above branches
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Group assignment failed during registration.")

        self.logger.info(f"Proceeding to create user '{self.registration.username or self.registration.email}' in group '{target_group.name}'.")
        # Create the new user, associated with the determined group
        new_user = self._create_new_user(target_group, is_new_group_being_created)

        # If a new group was created and seed_data flag is true, seed data for that group
        if is_new_group_being_created and self.registration.seed_data:
            self.logger.info(f"Seeding initial data for new group '{target_group.name}'.")
            # `self.repos` is non-group-scoped here, which is fine for SeederService if it handles scoping.
            # However, SeederService might expect group-scoped repos or take group_id.
            # For now, assuming SeederService can work with non-scoped repos or this needs adjustment.
            # A group-scoped repo for the new group:
            # new_group_repos = get_repositories(self.repos.session, group_id=target_group.id)
            # seeder_service = SeederService(new_group_repos)
            # seeder_service.seed_all_for_group() # Example method
            _ = SeederService(self.repos)  # Original code instantiates but doesn't call specific seed methods here.
            # This implies SeederService might have a default seed or this is incomplete.
            # Assuming it's a placeholder or setup for future specific seeding calls.
            self.logger.warning("`registration.seed_data` was True, but no specific seeding called in RegistrationService after group creation.")

        # If a group invitation token was used, decrement its uses or delete it
        if group_invite_token_entry and new_user:  # Ensure user creation was successful
            # Check if token is unlimited (-1) - if so, don't decrement
            if group_invite_token_entry.uses_left == -1:
                self.logger.info(f"Unlimited invitation token used: {group_invite_token_entry.id} (uses_left stays at -1)")
                # No action needed - unlimited tokens are never decremented or deleted
            else:
                # Decrement limited tokens
                group_invite_token_entry.uses_left -= 1
                if group_invite_token_entry.uses_left <= 0:
                    self.logger.info(f"Deleting used group invitation token: {group_invite_token_entry.id}")
                    self.repos.group_invite_tokens.delete(group_invite_token_entry.token, match_key="token")
                else:
                    self.logger.info(
                        f"Updating uses_left for group invitation token: {group_invite_token_entry.token} to {group_invite_token_entry.uses_left}"
                    )
                    # The update method expects a Pydantic schema or dict.
                    # `group_invite_token_entry` is likely a Pydantic Read schema.
                    # We need to pass an Update schema or compatible dict.
                    from marvin.schemas.group.invite_token import InviteTokenUpdate  # Local import

                    update_data = InviteTokenUpdate(
                        id=group_invite_token_entry.id,  # Assuming ID is needed for update by PK
                        uses_left=group_invite_token_entry.uses_left,
                        group_id=group_invite_token_entry.group_id,  # Pass required fields for the schema
                        token=group_invite_token_entry.token,
                    )
                    self.repos.group_invite_tokens.update(group_invite_token_entry.token, update_data)  # Update by ID
                    # Commit the token update
                    self.repos.group_invite_tokens.session.commit()

        self.logger.info(f"User '{new_user.username}' successfully registered with ID {new_user.id}.")
        return new_user
