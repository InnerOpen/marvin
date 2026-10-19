# Frontend API Call Audit

**Date**: 2026-07-10
**Purpose**: Document all direct fetch() calls in frontend pages and plan SDK migration strategy

## Executive Summary

The Marvin frontend has inconsistent API access patterns. Some pages use direct `fetch()` calls while SDK functions exist but aren't utilized. The main issue: **SDK functions are TypeScript and cannot be imported in client-side `<script>` tags**.

**Key Findings**:
- 5 pages use direct fetch() calls
- Email template SDK files were using non-existent `apiClient` (FIXED)
- Mix of correct and incorrect API routes
- No standardized pattern for client-side API access

## Pages with Direct fetch() Calls

### 1. /admin/email-settings.astro
**Status**: ✅ Routes correct, uses fetch() instead of SDK
**Location**: Client-side `<script>` tags
**API Calls**:
- `GET /api/admin/email/templates/{id}` - Load template for editing
- `POST /api/admin/email/templates` - Create template
- `PATCH /api/admin/email/templates/{id}` - Update template
- `DELETE /api/admin/email/templates/{id}` - Delete template
- `POST /api/admin/email/templates/{id}/test` - Send test email
- `POST /api/admin/email` - Send generic test email

**SDK Functions Available**:
- ✅ `getSystemEmailTemplate()`
- ✅ `createSystemEmailTemplate()`
- ✅ `updateSystemEmailTemplate()`
- ✅ `deleteSystemEmailTemplate()`
- ✅ `sendSystemTemplateTestEmail()`
- ❌ Missing: generic test email function

**Migration Strategy**: Keep fetch() for client-side code OR move to server-side form handling

---

### 2. /workspace/settings/email.astro
**Status**: ✅ Routes correct (after fix)
**Location**: Client-side `<script>` tags
**API Calls**:
- `GET /api/platform/workspaces/{id}/email-templates/{id}` - Load template
- `POST /api/platform/workspaces/{id}/email-templates` - Create template
- `PATCH /api/platform/workspaces/{id}/email-templates/{id}` - Update template
- `DELETE /api/platform/workspaces/{id}/email-templates/{id}` - Delete template
- `POST /api/platform/workspaces/{id}/email-templates/{id}/test` - Test email ✅ FIXED
- `POST /api/admin/email` - Send generic test email

**SDK Functions Available**:
- ✅ `listEmailTemplates()`
- ✅ `getEmailTemplate()`
- ✅ `createEmailTemplate()`
- ✅ `updateEmailTemplate()`
- ✅ `deleteEmailTemplate()`
- ❌ Missing: workspace template test email function

**Recent Fix**: Changed `/api/groups/{id}/email-templates/{id}/test` → `/api/platform/workspaces/{id}/email-templates/{id}/test`

**Migration Strategy**: Keep fetch() for client-side code

---

### 3. /forgot.astro
**Status**: ⚠️ Uses hardcoded API URL
**Location**: Server-side Astro frontmatter
**API Calls**:
- `POST {MARVIN_API_URL}/api/users/forgot-password`

**Issues**:
- Uses `import.meta.env.MARVIN_API_URL` with fallback instead of SDK config
- Should use SDK function for consistency

**SDK Functions**:
- ❌ Missing: `sendPasswordResetEmail()` function in users SDK

**Migration Strategy**: Create users SDK with password reset function

---

### 4. /workspace/scheduled-tasks.astro
**Status**: ✅ Routes correct, extensive API usage
**Location**: Client-side `<script>` tags
**API Calls**:
- `GET /api/platform/scheduled-tasks/task-types?detailed=true` - List task types
- `GET /api/platform/scheduled-tasks` - List tasks
- `POST /api/platform/scheduled-tasks` - Create task
- `POST /api/platform/scheduled-tasks/{id}/execute` - Execute task
- `DELETE /api/platform/scheduled-tasks/{id}` - Delete task
- `PATCH /api/platform/scheduled-tasks/{id}` - Update task
- `GET /api/platform/scheduled-tasks/{id}/history?limit=50` - Get task history

**SDK Functions**:
- ❌ No scheduled tasks SDK exists

**Migration Strategy**: Create comprehensive scheduled tasks SDK module

---

### 5. /workspace/settings/general.astro
**Status**: ✅ Single export endpoint
**Location**: Client-side `<script>` tag
**API Calls**:
- `GET /api/platform/workspace/export/pretty` - Export workspace data

**SDK Functions**:
- ❌ Missing: workspace export function

**Migration Strategy**: Add to workspace SDK

---

## SDK Status

### Fixed SDK Files ✅
1. `/frontend/src/lib/api/emailTemplates.ts` - Workspace email templates
   - Fixed: `apiClient` → `fetchApi`
   - Fixed: `/groups/` → `/platform/workspaces/`
   - Fixed: `group_id` → `workspace_id`

2. `/frontend/src/lib/api/admin/emailTemplates.ts` - Admin email templates
   - Fixed: `apiClient` → `fetchApi`
   - Added: `/api` prefix to all routes

3. `/frontend/src/lib/api/client.ts` - Core API client
   - ✅ Working: `fetchApi()` function with retry logic
   - ✅ Working: `getAuthToken()` for SSR

### Missing SDK Modules
1. **Users SDK** - Password reset, user management
2. **Scheduled Tasks SDK** - Full CRUD for scheduled tasks
3. **Workspace SDK** - Workspace export, settings

### Missing SDK Functions
1. `sendWorkspaceTemplateTestEmail()` - Test workspace email template
2. `sendGenericTestEmail()` - Send basic test email
3. All scheduled tasks functions
4. Workspace export function

---

## Technical Challenges

### 1. TypeScript in Client-Side Code
**Problem**: SDK functions are TypeScript modules that cannot be imported in `<script>` tags.

**Example**:
```astro
<script>
  // ❌ This doesn't work - TypeScript not available in client-side script
  import { getEmailTemplate } from '@/lib/api/emailTemplates';

  // ✅ This works - plain JavaScript fetch
  const response = await fetch('/api/...');
</script>
```

**Solutions**:
- **Option A**: Keep fetch() in client-side code, use SDK in SSR
- **Option B**: Create JavaScript client-side API wrapper
- **Option C**: Move to server-side form handling (progressive enhancement)

### 2. Inconsistent API Access Patterns
**Problem**: Mix of SDK usage, fetch() calls, and hardcoded URLs

**Current State**:
- SSR code: Sometimes SDK, sometimes fetch()
- Client-side: Always fetch()
- Routes: Mix of correct and incorrect paths

**Recommendation**: Standardize on:
- SSR: Use SDK functions
- Client-side: Use fetch() with documented patterns
- Routes: Always use correct /api/platform/* paths

---

## Migration Strategy

### Phase 1: Fix Critical Issues ✅ DONE
- [x] Fix broken emailTemplates.ts (apiClient → fetchApi)
- [x] Fix broken admin/emailTemplates.ts
- [x] Fix incorrect workspace email test route

### Phase 2: Create Missing SDK Functions
- [ ] Add workspace email template test function
- [ ] Add generic test email function
- [ ] Create users SDK with password reset
- [ ] Create scheduled tasks SDK
- [ ] Add workspace export function

### Phase 3: Standardize Patterns
- [ ] Document: "Use SDK in SSR, fetch() in client-side"
- [ ] Create examples for both patterns
- [ ] Update all SSR code to use SDK
- [ ] Ensure all fetch() calls use correct routes

### Phase 4: Future Enhancement
- [ ] Consider building client-side API wrapper
- [ ] Evaluate progressive enhancement approach
- [ ] Add comprehensive error handling

---

## Recommendations

### Short Term (Now)
1. ✅ **Keep current fetch() usage in client-side code** - It works and changing it is complex
2. ✅ **Use SDK functions in SSR** - Better type safety and consistency
3. ✅ **Ensure all routes are correct** - No more /groups/, use /platform/workspaces/
4. **Add missing SDK functions** - Complete coverage for all API endpoints

### Long Term (Future)
1. **Create client-side API module** - If fetch() usage becomes problematic
2. **Progressive enhancement** - Move complex client-side logic to server
3. **Comprehensive SDK** - Cover all API endpoints with typed functions

### Testing
1. Test all email template operations in both admin and workspace contexts
2. Verify SMTP test email delivery works
3. Check scheduled tasks CRUD operations
4. Test workspace export functionality

---

## Lessons Learned

1. **Don't create SDK functions without verifying imports** - The `apiClient` bug went unnoticed
2. **TypeScript client-side limitations** - Need clear separation of SSR vs client code
3. **Route consistency matters** - The /groups/ vs /platform/workspaces/ mixup caused bugs
4. **Audit before migration** - Understanding the full scope prevents scope creep

---

## Appendix: API Route Reference

### Admin Routes
- `/api/admin/email/templates` - System email templates
- `/api/admin/email/templates/{id}` - Specific template
- `/api/admin/email/templates/{id}/test` - Test template
- `/api/admin/email` - Generic test email

### Workspace Routes
- `/api/platform/workspaces/{id}/email-templates` - Workspace templates
- `/api/platform/workspaces/{id}/email-templates/{id}` - Specific template
- `/api/platform/workspaces/{id}/email-templates/{id}/test` - Test template
- `/api/platform/workspace/export/pretty` - Export workspace

### Scheduled Tasks Routes
- `/api/platform/scheduled-tasks` - List/create tasks
- `/api/platform/scheduled-tasks/{id}` - Specific task
- `/api/platform/scheduled-tasks/{id}/execute` - Execute task
- `/api/platform/scheduled-tasks/{id}/history` - Task history
- `/api/platform/scheduled-tasks/task-types` - Available task types

### User Routes
- `/api/users/forgot-password` - Password reset request
