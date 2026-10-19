# Seed System Improvements

## Current State Analysis

### What Exists
1. **Abstract Seeder Pattern** (`src/marvin/repos/seed/abstract_seeder.py`)
   - Base class for all seeders
   - Provides common initialization (repos, logger, resources path, settings)
   - Defines abstract `seed()` method

2. **Seeder Service** (`src/marvin/services/seeders/seeder_service.py`)
   - Orchestrates seeding operations
   - Currently only has `seed_notifier_options()`
   - Called during group registration (but incomplete - line 217-220)

3. **Existing Seeder** (`src/marvin/repos/seed/seeders.py`)
   - `NotifierOptionSeeder` - Seeds event notifier options from JSON
   - Supports locale-specific overrides in `DATA_DIR/seeds/`
   - Loads from `resources/notifier_options/notifier_options.json`

4. **Where Seeding Happens**
   - **Global seed**: `src/marvin/db/init_db.py` - Seeds notifier options at app startup
   - **Group-specific seed**: `src/marvin/services/user/registration_service.py:208-220`
     - Currently incomplete (instantiates SeederService but doesn't call anything)
     - Has TODO/warning about missing implementation

### Resources Directory Structure
```
src/marvin/repos/seed/resources/
├── __init__.py
└── notifier_options/
    ├── __init__.py
    └── notifier_options.json
```

### User Override Location
Users can override seeds in: `DATA_DIR/seeds/notifier_options/{name}.json`

---

## Improvements Needed

### 1. Create Entry Types Seeder

**Goal**: Seed default entry types when a new workspace/group is created.

**Default Entry Types to Create**:
- Page (slug: `page`, icon: 📄, sort_order: 1)
- Project (slug: `project`, icon: 🚀, sort_order: 2)
- Article (slug: `article`, icon: 📝, sort_order: 3)
- Guide (slug: `guide`, icon: 📚, sort_order: 4)

**Implementation**:

#### Step 1: Create Resource File
**File**: `src/marvin/repos/seed/resources/entry_types/entry_types.json`
```json
[
    {
        "name": "Page",
        "slug": "page",
        "description": "General purpose content page",
        "icon": "📄",
        "sort_order": 1
    },
    {
        "name": "Project",
        "slug": "project",
        "description": "Project documentation or overview",
        "icon": "🚀",
        "sort_order": 2
    },
    {
        "name": "Article",
        "slug": "article",
        "description": "Blog post or article",
        "icon": "📝",
        "sort_order": 3
    },
    {
        "name": "Guide",
        "slug": "guide",
        "description": "How-to guide or tutorial",
        "icon": "📚",
        "sort_order": 4
    }
]
```

#### Step 2: Create `__init__.py` for Entry Types Resource
**File**: `src/marvin/repos/seed/resources/entry_types/__init__.py`
```python
"""Entry types seed resources."""

from pathlib import Path

entry_types = Path(__file__).parent / "entry_types.json"
```

#### Step 3: Create EntryTypesSeeder Class
**File**: `src/marvin/repos/seed/seeders.py` (add to existing file)
```python
from marvin.schemas.platform import EntryTypeCreate
from .resources import entry_types as default_entry_types_resource

class EntryTypesSeeder(AbstractSeeder):
    """
    A seeder for populating a workspace with default entry types.
    
    This seeder creates standard entry types (Page, Project, Article, Guide)
    when a new workspace is created. Entry types are group-scoped.
    """

    def get_file(self, name: str) -> pathlib.Path:
        """
        Determines the path to the entry types JSON file.
        
        Checks for locale-specific file in SEED_DIR first, falls back to default.
        """
        locale_specific_path = self.directories.SEED_DIR / "entry_types" / f"{name}.json"
        
        if locale_specific_path.exists():
            self.logger.info(f"Using locale-specific entry types file: {locale_specific_path}")
            return locale_specific_path
        else:
            default_path = getattr(default_entry_types_resource, "entry_types", None)
            if not isinstance(default_path, pathlib.Path) or not default_path.exists():
                raise FileNotFoundError("Default entry_types.json resource not found.")
            self.logger.info(f"Using default entry types file: {default_path}")
            return default_path

    def load_data(self, name: str) -> Generator[EntryTypeCreate, None, None]:
        """
        Loads entry type data from JSON file.
        
        Yields EntryTypeCreate schemas for each entry type.
        """
        json_file_path = self.get_file(name)
        file_content = json_file_path.read_text(encoding="utf-8")
        entry_types_data = json.loads(file_content)
        
        seen_slugs = set()
        for entry_type_dict in entry_types_data:
            slug = entry_type_dict.get("slug")
            if not slug:
                self.logger.warning(f"Skipping entry type without slug: {entry_type_dict}")
                continue
            
            if slug in seen_slugs:
                self.logger.warning(f"Skipping duplicate entry type slug: '{slug}'")
                continue
            
            seen_slugs.add(slug)
            try:
                yield EntryTypeCreate(**entry_type_dict)
            except Exception as e:
                self.logger.error(f"Error validating entry type '{slug}': {e}")

    def seed(self, name: str | None = None) -> None:
        """
        Seeds the database with default entry types for a workspace.
        
        Args:
            name: The seed configuration name (e.g., "entry_types")
        """
        if not name:
            name = "entry_types"
        
        self.logger.info(f"Seeding Entry Types for workspace from configuration: '{name}'")
        count_seeded = 0
        count_errors = 0
        
        for entry_type_schema in self.load_data(name):
            try:
                self.repos.entry_types.create(entry_type_schema)
                self.logger.debug(f"Successfully seeded entry type: {entry_type_schema.slug}")
                count_seeded += 1
            except Exception as e:
                self.logger.error(f"Failed to seed entry type '{entry_type_schema.slug}': {e}")
                count_errors += 1
        
        self.logger.info(f"Entry types seeding complete. Seeded: {count_seeded}, Errors: {count_errors}")
```

#### Step 4: Add Method to SeederService
**File**: `src/marvin/services/seeders/seeder_service.py`
```python
from marvin.repos.seed.seeders import NotifierOptionSeeder, EntryTypesSeeder

class SeederService(BaseService):
    # ... existing code ...
    
    def seed_entry_types(self, name: str | None = None) -> None:
        """
        Seeds the workspace with default entry types.
        
        This should be called when a new workspace/group is created.
        Requires group-scoped repositories.
        
        Args:
            name: Configuration name (defaults to "entry_types")
        """
        self.logger.info(f"Initiating seeding of entry types with configuration: '{name or 'default'}'")
        entry_types_seeder = EntryTypesSeeder(db=self.repos, logger=self.logger)
        entry_types_seeder.seed(name or "entry_types")
        self.logger.info(f"Completed seeding of entry types for configuration: '{name or 'default'}'")
    
    def seed_workspace_defaults(self) -> None:
        """
        Seeds all default data for a new workspace.
        
        This is a convenience method that calls all workspace-level seeders.
        Should be called with group-scoped repositories.
        """
        self.logger.info("Seeding all workspace defaults")
        self.seed_entry_types()
        # Future: self.seed_default_collections()
        # Future: self.seed_example_entries()
        self.logger.info("Completed seeding all workspace defaults")
```

#### Step 5: Wire Up to Group Creation
**File**: `src/marvin/services/user/registration_service.py`

Replace lines 208-220 with:
```python
# If a new group was created and seed_data flag is true, seed data for that group
if is_new_group_being_created and self.registration.seed_data:
    self.logger.info(f"Seeding initial data for new group '{target_group.name}'.")
    
    # Get group-scoped repositories for the new group
    from marvin.repos.repository_factory import AllRepositories
    group_scoped_repos = AllRepositories(self.repos.session, group_id=target_group.id)
    
    # Seed workspace defaults
    seeder_service = SeederService(group_scoped_repos)
    seeder_service.seed_workspace_defaults()
    
    self.logger.info(f"Completed seeding initial data for new group '{target_group.name}'.")
```

---

### 2. Additional Improvements

#### A. Add Collections Seeder (Future Enhancement)
**Purpose**: Seed example collections like "Featured", "Drafts", "Published"

**File**: `src/marvin/repos/seed/resources/collections/collections.json`
```json
[
    {
        "name": "Featured",
        "slug": "featured",
        "description": "Featured content for homepage",
        "is_smart": false
    },
    {
        "name": "Recent",
        "slug": "recent",
        "description": "Recently published content",
        "is_smart": true,
        "smart_rules": {
            "status": "published",
            "sort_by": "published_at",
            "limit": 10
        }
    }
]
```

#### B. Add Example Entries Seeder (Future Enhancement)
**Purpose**: Create a "Getting Started" guide entry

**File**: `src/marvin/repos/seed/resources/entries/welcome_entries.json`
```json
[
    {
        "title": "Welcome to Your Workspace",
        "slug": "welcome",
        "entry_type_slug": "guide",
        "status": "published",
        "summary": "Get started with your new workspace",
        "content_markdown": "# Welcome!\n\nThis is your first entry..."
    }
]
```

#### C. Improve Error Handling
Add better error handling for:
- Duplicate slug conflicts (catch IntegrityError)
- Missing group_id (validate before seeding)
- Partial seeding failures (log and continue)

#### D. Add Seeder Tests
**File**: `tests/unit/repos/seed/test_entry_types_seeder.py`
```python
def test_entry_types_seeder_loads_default_data():
    """Test that default entry types are loaded correctly."""
    # ...

def test_entry_types_seeder_creates_records():
    """Test that entry types are created in database."""
    # ...

def test_entry_types_seeder_handles_duplicates():
    """Test that duplicate slugs are handled gracefully."""
    # ...
```

---

## Implementation Order

1. ✅ Create `entry_types.json` resource file
2. ✅ Create `entry_types/__init__.py` resource module
3. ✅ Add `EntryTypesSeeder` class to `seeders.py`
4. ✅ Add `seed_entry_types()` method to `SeederService`
5. ✅ Add `seed_workspace_defaults()` method to `SeederService`
6. ✅ Update `registration_service.py` to call seeder
7. ⏭️ Test with new group creation
8. ⏭️ Add seeder tests
9. ⏭️ (Future) Add collections seeder
10. ⏭️ (Future) Add example entries seeder

---

## Testing Plan

### Manual Testing
1. Create a new user with new group and `seed_data=true`
2. Verify 4 entry types created (Page, Project, Article, Guide)
3. Verify sort_order is correct
4. Verify icons and descriptions are set
5. Test creating entries with seeded types

### Automated Testing
1. Unit tests for `EntryTypesSeeder.load_data()`
2. Unit tests for `EntryTypesSeeder.seed()`
3. Integration test for full workspace creation with seeding
4. Test locale override (custom entry_types.json in DATA_DIR/seeds/)

---

## User Customization

Users can override default entry types by creating:
```
DATA_DIR/seeds/entry_types/entry_types.json
```

This allows organizations to customize their default entry types without modifying code.

---

## Future Enhancements

1. **Seed on Demand**: Add API endpoint to re-seed workspace defaults
2. **Seed Profiles**: Support multiple seed profiles (minimal, standard, full)
3. **Conditional Seeding**: Only seed if workspace has no entry types
4. **Import/Export**: Allow exporting workspace structure as seed template
5. **Validation Rules**: Add entry type-specific validation rules in seed data
6. **Custom Fields**: Support custom field definitions in entry type seeds
