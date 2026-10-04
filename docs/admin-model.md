# Admin Model

Marvin implements a comprehensive role-based authorization system with two distinct levels:
1. **Platform-level roles** - Control access to platform-wide operations
2. **Workspace-level roles** - Control access within specific workspaces

## Platform Roles

Platform roles determine a user's access to platform-level operations. Each user has exactly ONE platform role.

### PlatformRole Enum

```python
class PlatformRole(Enum):
    NONE = "NONE"           # Standard user (no platform privileges)
    SUPER_ADMIN = "SUPER_ADMIN"  # Platform administrator
```

### SUPER_ADMIN (Platform Administrator)

A **Super Admin** has unrestricted platform-level privileges across all workspaces.

**Permissions:**
- View and manage all workspaces (not limited by workspace membership)
- Create/edit/delete workspaces
- Manage workspace settings for any workspace
- Manage users across the platform
- Access all publishing configurations
- Perform platform-level operations

**Access:**
- Can bypass workspace membership checks (configurable per-endpoint)
- Access admin routes under `/api/admin/*`
- Full access to user management operations

**Notes:**
- Super admins are rare - typically only the platform owner/operators
- Should be reserved for platform administrators only
- Can optionally be required to have explicit workspace membership for sensitive operations

### NONE (Standard User)

Standard users with no platform-level privileges.

**Characteristics:**
- Default for all regular users
- Must have explicit workspace membership to access workspace content
- Cannot perform platform-level operations
- Access controlled entirely by workspace roles

## Workspace Roles

Workspace roles determine what a user can do within a specific workspace. Users can be members of multiple workspaces with different roles in each.

### WorkspaceRole Enum

```python
class WorkspaceRole(Enum):
    OWNER = "OWNER"      # Workspace owner (highest privilege)
    ADMIN = "ADMIN"      # Workspace administrator
    EDITOR = "EDITOR"    # Content editor
    AUTHOR = "AUTHOR"    # Content author
    VIEWER = "VIEWER"    # Read-only viewer
```

### Role Hierarchy

Roles follow a privilege hierarchy where higher roles include all permissions of lower roles:

```
OWNER (5) ≥ ADMIN (4) ≥ EDITOR (3) ≥ AUTHOR (2) ≥ VIEWER (1)
```

### OWNER

Full control over the workspace.

**Permissions:**
- Everything an ADMIN can do
- Transfer ownership (future)
- Delete the workspace (future)

**Typical Use:**
- One OWNER per workspace
- Creator of the workspace

### ADMIN

Workspace administrator with management capabilities.

**Permissions:**
- Manage workspace settings: integrations (and running their checks and actions), outgoing and
  incoming webhooks, workflows, scheduled tasks, SMTP profiles, email templates and their event
  subscriptions, variables and secrets, AI providers and MCP servers, export and backups. These
  routes refuse lower roles with a 403 for reads as well as writes, except the integration provider
  catalog, webhook and task-type lists, secret slugs, email templates, workspace preferences and
  AI settings, which member pages read.
- Manage workspace members (invite/remove, see invite tokens)
- Manage entry types and collections
- Create/edit/delete all entries
- Manage assets
- Configure publishing (API clients, site settings)

**Typical Use:**
- Workspace administrators and managers
- Users who need full workspace management capabilities

### EDITOR

Content editor who can manage all content.

**Permissions:**
- Create entries
- Edit all entries (not just their own)
- Upload and manage assets
- Organize content into collections

**Cannot:**
- Manage workspace settings
- Invite/remove users
- Configure publishing

**Typical Use:**
- Content editors
- Users who need to manage content but not workspace settings

### AUTHOR

Content author who can create and manage their own content.

**Permissions:**
- Create entries (owned by them)
- Edit their own entries
- Upload assets

**Cannot:**
- Edit others' entries
- Manage workspace settings
- Invite users

**Typical Use:**
- Content contributors
- Guest authors
- External collaborators

### VIEWER

Read-only viewer.

**Permissions:**
- View published content
- View workspace content they have access to

**Cannot:**
- Create or edit content
- Manage anything

**Typical Use:**
- Read-only stakeholders
- External reviewers
- Note: For true read-only external access, use API clients instead

## Database Schema

### Users Table

```python
class Users(SqlAlchemyBase):
    # Platform role (one per user)
    platform_role: Mapped[PlatformRole] = mapped_column(
        SqlAlchemyEnum(PlatformRole),
        nullable=False,
        default=PlatformRole.NONE,
    )
    
    # Legacy group association (DEPRECATED - use workspace_memberships)
    group_id: Mapped[GUID] = mapped_column(GUID, ForeignKey("groups.id"))
    
    # Workspace memberships (many-to-many via WorkspaceMembers)
    workspace_memberships: Mapped[list["WorkspaceMembers"]] = orm.relationship(...)
    
    # DEPRECATED fields (kept for backward compatibility)
    admin: Mapped[bool | None]  # DEPRECATED: Use workspace roles
    is_superuser: Mapped[bool]  # DEPRECATED: Use platform_role
    can_manage: Mapped[bool | None]  # DEPRECATED: Use workspace roles
    can_invite: Mapped[bool | None]  # DEPRECATED: Use workspace roles
```

### WorkspaceMembers Table

Junction table tracking user-workspace relationships with roles.

```python
class WorkspaceMembers(SqlAlchemyBase):
    id: Mapped[GUID] = mapped_column(GUID, primary_key=True)
    user_id: Mapped[GUID] = mapped_column(GUID, ForeignKey("users.id"))
    group_id: Mapped[GUID] = mapped_column(GUID, ForeignKey("groups.id"))
    workspace_role: Mapped[WorkspaceRole] = mapped_column(
        SqlAlchemyEnum(WorkspaceRole),
        nullable=False,
    )
    
    # Unique constraint: one membership per user-workspace pair
    __table_args__ = (
        UniqueConstraint("user_id", "group_id", name="uq_workspace_member"),
    )
```

## Authorization Helpers

### Platform-Level Authorization

```python
from marvin.core.dependencies.dependencies import (
    get_current_superuser,  # Original name (backward compatible)
    get_platform_admin,     # New alias (clearer naming)
)

# Require platform admin
@router.post("/api/admin/workspaces")
async def create_workspace(
    user: PrivateUser = Depends(get_platform_admin)
):
    # Only SUPER_ADMIN can reach here
    ...
```

### Workspace-Level Authorization

```python
from marvin.core.dependencies.dependencies import (
    require_workspace_owner,
    require_workspace_admin,
    require_workspace_editor,
    require_workspace_author,
    require_workspace_viewer,
    require_workspace_member,
)

# Require ADMIN role or higher
@router.put("/api/workspaces/{workspace_id}/settings")
async def update_settings(
    workspace_id: UUID4,
    user: PrivateUser = Depends(require_workspace_admin())
):
    # Only ADMIN or OWNER can reach here
    # Platform admins can bypass (default)
    ...

# Require EDITOR role or higher
@router.post("/api/workspaces/{workspace_id}/entries")
async def create_entry(
    workspace_id: UUID4,
    user: PrivateUser = Depends(require_workspace_editor())
):
    # EDITOR, ADMIN, or OWNER can reach here
    ...

# Block platform admin bypass for sensitive operations
@router.delete("/api/workspaces/{workspace_id}/permanent-delete")
async def permanent_delete(
    workspace_id: UUID4,
    user: PrivateUser = Depends(
        require_workspace_admin(allow_platform_admin=False)
    )
):
    # Platform admins need explicit ADMIN role
    ...
```

### Custom Role Requirements

```python
from marvin.core.dependencies.dependencies import require_workspace_role
from marvin.db.models.users.roles import WorkspaceRole

@router.post("/api/workspaces/{workspace_id}/drafts")
async def create_draft(
    workspace_id: UUID4,
    user: PrivateUser = Depends(
        require_workspace_role(WorkspaceRole.AUTHOR)
    )
):
    # AUTHOR, EDITOR, ADMIN, or OWNER can reach here
    ...
```

## User Model Helper Methods

### Platform Admin Check

```python
user = await get_current_user(...)

# Check if user is platform admin
if user.is_platform_admin:
    # User has SUPER_ADMIN platform role
    ...
```

### Workspace Role Check

```python
# Get user's role in a workspace
role = user.get_workspace_role(workspace_id)
if role == WorkspaceRole.ADMIN:
    # User is admin in this workspace
    ...

# Check if user has at least a specific role
if user.has_workspace_role(workspace_id, WorkspaceRole.EDITOR):
    # User is EDITOR, ADMIN, or OWNER
    ...
```

## Implementation Patterns

### Group Scoping

All workspace-scoped resources use these patterns:

```python
# Repository layer - scoped by group_id
repos = get_repositories(session, group_id=current_user.group_id)
entry = repos.entries.get_one(entry_id)  # Automatically scoped

# Direct queries - manual filtering
entry = session.query(Entries).filter(
    Entries.group_id == current_user.group_id,
    Entries.id == entry_id
).first()
```

### Admin Routes vs Publishing Routes

**Admin Routes** (`/api/admin/*`, `/api/entries`, etc.):
- Require user authentication (JWT token)
- Check workspace membership and roles
- Return all entry states (draft, review, published)
- Include admin metadata (created_by, internal notes, etc.)
- Write operations allowed based on role

**Publishing Routes** (`/api/publish/{workspace_slug}/*`):
- Require API client token authentication (`marvin_sk_*`)
- Scoped to workspace associated with the API client
- Only return `status = 'published'` entries
- Exclude all admin fields
- Read-only operations only

### Site Client Permissions

Site clients (API tokens for publishing) are:
- Scoped to one workspace
- Read-only (cannot create/edit/delete)
- Can only see published content
- Cannot impersonate users or access admin APIs

See: `docs/site-clients-and-publishing.md`

## Migration Path

### From Boolean Flags to Roles

The migration (`3dd1c8a4ed25_add_role_based_authorization.py`) automatically:

1. **Platform roles**: Converts `is_superuser=True` to `platform_role=SUPER_ADMIN`
2. **Workspace memberships**: Creates workspace_members records for all users
   - `admin=True` → `WorkspaceRole.ADMIN`
   - `admin=False` → `WorkspaceRole.AUTHOR`
3. **Preserves legacy fields**: `admin`, `is_superuser`, etc. kept for backward compatibility

### Deprecated Fields

These fields are deprecated but preserved for backward compatibility:

| Field | Replacement | Status |
|-------|------------|--------|
| `admin` | Workspace roles (ADMIN, etc.) | DEPRECATED |
| `is_superuser` | `platform_role` | DEPRECATED |
| `can_manage` | Workspace roles | DEPRECATED |
| `can_invite` | Workspace roles | DEPRECATED |
| `can_organize` | Workspace roles | DEPRECATED |
| `advanced` | Workspace roles | DEPRECATED |

### Migration Strategy

**Phase 1: Coexistence** (Current)
- New role system active
- Legacy fields preserved
- Both systems work in parallel
- New code uses roles, old code uses flags

**Phase 2: Gradual Migration**
- Update routes one-by-one to use role-based dependencies
- Test each migration
- Keep deprecated dependencies available

**Phase 3: Deprecation Warnings**
- Log warnings when legacy fields are used
- Update documentation to recommend new approach
- Migration guide for custom code

**Phase 4: Removal** (Future)
- Remove deprecated fields from database
- Remove old dependency functions
- Clean up migration code

## Default Seed Data

### Admin User (Production)
- **Username**: admin
- **Platform Role**: `SUPER_ADMIN`
- **Workspace Role**: `OWNER` in default workspace
- Full platform and workspace access

### Development Users (Non-Production)

| Username | Platform Role | Workspace Role | Use Case |
|----------|--------------|----------------|----------|
| jason    | NONE         | ADMIN          | Workspace administrator testing |
| bob      | NONE         | EDITOR         | Content editor testing |
| sarah    | NONE         | AUTHOR         | Content author testing |
| sammy    | NONE         | VIEWER         | Read-only viewer testing |

## Security Principles

1. **Default to workspace scoping**: All queries should filter by `group_id` unless explicitly platform-level
2. **Workspace isolation**: Never leak data between workspaces
3. **Least privilege**: Assign minimum required role
4. **Explicit authorization**: Check workspace membership and role before any operation
5. **Platform admin bypass optional**: Sensitive operations can require explicit membership
6. **Separate concerns**: Admin routes and publishing routes use different auth mechanisms
7. **Role hierarchy**: Higher roles include all lower role permissions

## Error Responses

### Not a Platform Admin
```json
{
  "detail": "Super admin privileges required. This operation requires platform-level access."
}
```
Status: `403 Forbidden`

### Not a Workspace Member
```json
{
  "detail": "Access denied. You are not a member of this workspace."
}
```
Status: `403 Forbidden`

### Insufficient Role
```json
{
  "detail": "Access denied. Required role: ADMIN, your role: EDITOR"
}
```
Status: `403 Forbidden`

## Related Documentation

- `docs/marvin-platform-plan.md` - Platform architecture
- `docs/site-clients-and-publishing.md` - Publishing API security model
- `docs/platform-implementation-checklist.md` - Implementation phases
- `src/marvin/db/models/users/roles.py` - Role definitions and helper functions
- `src/marvin/core/dependencies/dependencies.py` - Authorization dependencies
