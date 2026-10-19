# Future Improvements

This document tracks potential enhancements and optimizations for future development.

## Performance & Caching

### Implement ETag Caching with `cache_key`

**Status:** Not Implemented
**Priority:** Low
**Effort:** Medium

The `cache_key` field exists in the User model but is currently unused (hardcoded to `"1234"`).

**Current State:**
- Field defined: `src/marvin/db/models/users/users.py:173`
- Included in UserRead schema but not actively used
- Default value: `"1234"` for all users

**Proposed Implementation:**
1. Generate unique cache_key per user (UUID or timestamp-based)
2. Update cache_key when user data changes (profile updates, role changes)
3. Use cache_key in ETag headers for user endpoints:
   - `GET /api/users/self` → `ETag: "{cache_key}"`
   - Client sends `If-None-Match: "{cache_key}"` on subsequent requests
   - Return `304 Not Modified` if cache_key matches
4. Reduces bandwidth for frequently polled user endpoints

**Benefits:**
- Reduce server load on user profile endpoints
- Faster response times for cached requests
- Better mobile/low-bandwidth experience
- Standard HTTP caching pattern

**Considerations:**
- Need to update cache_key on any user mutation
- Test with workspace role changes
- Document cache invalidation strategy
- Consider cache_key for other frequently-read resources (workspaces, collections)

**References:**
- RFC 7232 (HTTP Conditional Requests)
- FastAPI Response Headers: https://fastapi.tiangolo.com/advanced/response-headers/

---

## Authentication & Security

### API Client Permission Enforcement

**Status:** Not Implemented
**Priority:** High
**Effort:** Medium

API clients have a `permissions` field (e.g., `read:published_entries`, `read:collections`) but these permissions are **not currently enforced** in the Publishing API.

**Current State:**
- Permissions stored in `api_clients` table
- Default permissions set on creation
- Publishing API validates token but doesn't check permissions
- Any valid API client can access all Publishing API endpoints

**Proposed Implementation:**
1. Create `PermissionChecker` utility (drafted in `src/marvin/core/permissions.py`)
2. Update `get_publishing_context()` dependency to return permission checker
3. Add permission checks to all Publishing API endpoints:
   - Entries: `read:published_entries`, `read:draft_entries`, `read:all_entries`
   - Collections: `read:collections`
   - Assets: `read:assets`
   - Resources: `read:resources`
4. Return 403 Forbidden if permission not granted

**Permissions to Add:**
- `read:published_entries` - Only published entries (default for new clients)
- `read:draft_entries` - Access draft entries (for preview environments)
- `read:all_entries` - Access entries of any status
- `read:collections` - Access collections
- `read:assets` - Access assets
- `read:resources` - Access resources

**Benefits:**
- Principle of least privilege
- Separate production/preview API clients
- Audit trail of what each client can access
- Defense against token leakage

**Note:** Platform API (used by CLI/SDK) uses workspace roles (VIEWER, AUTHOR, EDITOR, ADMIN, OWNER) which ARE enforced via `require_workspace_role()` dependencies.

---

### Password Reset Flow
- Email-based password reset tokens
- Token expiration (24 hours)
- Rate limiting on reset requests

### Two-Factor Authentication (2FA)
- TOTP-based 2FA
- Backup codes
- Remember device option

---

## Workspace Features

### Workspace Invitations (✅ Completed v0.2.0)
- ✅ Role-based invitations (VIEWER, AUTHOR, EDITOR, ADMIN, OWNER)
- ✅ Frontend UI for role selection
- ✅ SDK and CLI support

### Workspace Settings
- Custom workspace domains
- Workspace-level API rate limits
- Workspace branding (logo, colors)

---

## Content Management

### Asset Management
- Image optimization pipeline
- CDN integration
- Asset versioning

### Version Control for Entries
- Entry revision history
- Restore to previous version
- Compare versions

---

## Developer Experience

### API Rate Limiting
- Per-workspace limits
- Per-user limits
- Better rate limit headers

### Webhooks
- Webhook retry logic
- Webhook signature verification
- Webhook event filtering

---

## Infrastructure

### Database
- PostgreSQL support (currently SQLite)
- Database connection pooling
- Query performance optimization

### Observability
- Structured logging with correlation IDs
- Metrics export (Prometheus)
- Distributed tracing

---

## Documentation

### API Documentation
- Interactive API explorer improvements
- Code examples in multiple languages
- Postman collection generation

### User Guides
- Workspace management guide
- Content modeling best practices
- Integration examples

---

*Last updated: 2026-07-08*
