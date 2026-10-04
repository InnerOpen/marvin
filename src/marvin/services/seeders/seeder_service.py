"""
This module defines the `SeederService`, which is responsible for orchestrating
database seeding operations within the Marvin application.

It uses specific seeder classes (e.g., `SystemEntryTypeSeeder`) to populate
the database with initial or default data for various parts of the application.
"""

from marvin.repos.repository_factory import AllRepositories  # For accessing data repositories
from marvin.repos.seed.seeders import SystemEntryTypeSeeder  # Specific seeders

# The line `# $from marvin.repos.seeders` seems like a placeholder or an artifact;
# actual seeder classes are imported directly.
from marvin.services import BaseService  # Base service class for common functionalities


class SeederService(BaseService):
    """
    Service layer for coordinating database seeding operations.

    This service instantiates and calls appropriate seeder classes to populate
    the database with initial data, such as system entry types.
    It relies on an `AllRepositories` instance for database access passed to the seeders.
    """

    def __init__(self, repos: AllRepositories) -> None:
        """
        Initializes the SeederService.

        Args:
            repos (AllRepositories): An instance of `AllRepositories` providing
                                     access to all data repositories needed by the seeders.
        """
        super().__init__()  # Initialize BaseService (likely for settings, logger)
        self.repos: AllRepositories = repos
        """Provides access to all data repositories, passed to individual seeders."""
        # self.logger is inherited from BaseService.

    def seed_system_entry_types(self, name: str | None = None) -> None:
        """
        Seeds the database with system-level entry types.

        Instantiates `SystemEntryTypeSeeder` and calls its `seed` method.
        System entry types are globally available to all workspaces and
        are created with group_id=NULL.

        Args:
            name (str | None, optional): The name of the seeder configuration or
                                         data file to use (e.g., "system_entry_types").
                                         Passed to the seeder's `seed` method.
                                         If None, the seeder might use a default.
        """
        self.logger.info(f"Initiating seeding of system entry types with configuration: '{name or 'default'}'")
        # Instantiate the specific seeder for system entry types
        system_entry_type_seeder = SystemEntryTypeSeeder(db=self.repos, logger=self.logger)
        # Execute the seed operation
        system_entry_type_seeder.seed(name)
        self.logger.info(f"Completed seeding of system entry types for configuration: '{name or 'default'}'")
