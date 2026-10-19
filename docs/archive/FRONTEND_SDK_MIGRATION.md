# Frontend SDK Migration Plan

## Overview

Migrate the Marvin frontend from custom API client code to use the official `@inneropen/marvin-sdk` package.

**Current State:**
- Custom API client in `/frontend/src/lib/api/` with ~13 modules
- Direct `fetch()` calls with retry logic and error handling
- Separate modules for: entries, collections, resources, assets, workspaces, etc.

**Target State:**
- Single SDK dependency: `@inneropen/marvin-sdk@^1.3.0`
- Platform API client for all CRUD operations
- Cleaner code with SDK handling HTTP layer

**Benefits:**
- ✅ Centralized SDK maintenance (bug fixes, features)
- ✅ TypeScript types from OpenAPI spec
- ✅ Consistent API usage across CLI and frontend
- ✅ Less code to maintain in frontend

## Migration Strategy

### Phase 1: Install SDK & Create Adapter Layer
1. Install `@inneropen/marvin-sdk` in frontend
2. Create SDK client factory in `src/lib/sdk.ts`
3. Keep existing API modules temporarily as thin wrappers

### Phase 2: Migrate API Modules (one at a time)
1. **entries.ts** → Use `sdk.entries.*`
2. **collections.ts** → Use `sdk.collections.*`
3. **resources.ts** → Use `sdk.resources.*`
4. **platform.ts** (assets, apiClients) → Use `sdk.assets.*` and `sdk.apiClients.*`
5. **entryTypes.ts** → Use `sdk.entryTypes.*`
6. **workspaces.ts** → Use `sdk.workspaces.*`
7. **workspaceMembers.ts** → Use `sdk.workspaceMembers.*`
8. **workspaceSettings.ts** → Use `sdk.workspaceSettings.*`
9. **invites.ts** → Use `sdk.invites.*`

### Phase 3: Update Astro Pages
1. Replace API imports with SDK imports
2. Test each page for regressions
3. Remove old API modules

### Phase 4: Cleanup
1. Remove `src/lib/api/` directory (except `config.ts` and `types.ts` if needed)
2. Update tests
3. Document SDK usage patterns

## File Changes

### Files to Create:
- `frontend/src/lib/sdk.ts` - SDK client factory

### Files to Modify:
- `frontend/package.json` - Add SDK dependency
- All `.astro` files importing from `lib/api/*`

### Files to Remove (after migration):
- `frontend/src/lib/api/client.ts` - Replaced by SDK
- `frontend/src/lib/api/entries.ts` - Replaced by SDK
- `frontend/src/lib/api/collections.ts` - Replaced by SDK
- `frontend/src/lib/api/resources.ts` - Replaced by SDK
- `frontend/src/lib/api/platform.ts` - Replaced by SDK
- `frontend/src/lib/api/entryTypes.ts` - Replaced by SDK
- `frontend/src/lib/api/workspaces.ts` - Replaced by SDK
- `frontend/src/lib/api/workspaceMembers.ts` - Replaced by SDK
- `frontend/src/lib/api/workspaceSettings.ts` - Replaced by SDK
- `frontend/src/lib/api/invites.ts` - Replaced by SDK

### Files to Keep:
- `frontend/src/lib/api/config.ts` - Still needed for environment config
- `frontend/src/lib/api/types.ts` - May need to import from SDK instead

## Implementation Steps

### Step 1: Install SDK
```bash
cd /Volumes/Code/Marvin/frontend
npm install @inneropen/marvin-sdk@^1.3.0
```

### Step 2: Create SDK Factory (`src/lib/sdk.ts`)
```typescript
import { createPlatformClient } from '@inneropen/marvin-sdk/platform';
import type { PlatformClient } from '@inneropen/marvin-sdk/platform';
import { getApiUrl } from './api/config';

/**
 * Create a Platform API client for SSR contexts (Astro pages)
 * @param authToken - User auth token from Astro.cookies
 */
export function createSdkClient(authToken: string): PlatformClient {
  const apiUrl = getApiUrl(''); // Get base API URL
  
  return createPlatformClient({
    apiUrl,
    userToken: authToken,
  });
}
```

### Step 3: Example Migration - entries.ts

**Before:**
```typescript
import { fetchApi } from "./client";
import type { EntryRead, EntryCreate } from "./types";

export async function listEntries(authToken?: string): Promise<EntryRead[]> {
  return fetchApi<EntryRead[]>('/api/platform/entries', {}, authToken);
}

export async function createEntry(data: EntryCreate, authToken?: string): Promise<EntryRead> {
  return fetchApi<EntryRead>('/api/platform/entries', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }, authToken);
}
```

**After:**
```typescript
import { createSdkClient } from '../sdk';
import type { PlatformEntry, PlatformEntryCreate } from '@inneropen/marvin-sdk/platform';

export async function listEntries(authToken: string): Promise<PlatformEntry[]> {
  const sdk = createSdkClient(authToken);
  return sdk.entries.list();
}

export async function createEntry(data: PlatformEntryCreate, authToken: string): Promise<PlatformEntry> {
  const sdk = createSdkClient(authToken);
  return sdk.entries.create(data);
}
```

### Step 4: Update Astro Pages

**Before:**
```typescript
import { listEntries, createEntry } from '../lib/api/entries';
import { getAuthToken } from '../lib/api/client';

const authToken = getAuthToken(Astro.cookies);
const entries = await listEntries(authToken);
```

**After (Option 1 - via wrapper):**
```typescript
import { listEntries, createEntry } from '../lib/api/entries';
import { getAuthToken } from '../lib/api/client';

const authToken = getAuthToken(Astro.cookies);
const entries = await listEntries(authToken);
```

**After (Option 2 - direct SDK):**
```typescript
import { createSdkClient } from '../lib/sdk';
import { getAuthToken } from '../lib/api/client';

const authToken = getAuthToken(Astro.cookies);
if (!authToken) throw new Error('Not authenticated');

const sdk = createSdkClient(authToken);
const entries = await sdk.entries.list();
```

## Testing Checklist

For each migrated module:
- [ ] List operations work
- [ ] Get by ID works
- [ ] Create works
- [ ] Update works  
- [ ] Delete works
- [ ] Error handling works (401, 404, 500)
- [ ] TypeScript types are correct
- [ ] No console errors

## Rollout Plan

1. **Week 1**: Install SDK, create adapter, migrate 2-3 modules
2. **Week 2**: Migrate remaining modules
3. **Week 3**: Update all pages, remove old code
4. **Week 4**: Testing and cleanup

## Risk Mitigation

- Keep old API modules until all pages are migrated
- Test each module migration independently
- Can rollback by reverting package.json and SDK imports

## Notes

- The SDK uses slightly different type names (e.g., `PlatformEntry` vs `EntryRead`)
- Auth token is required for SDK (no optional parameters)
- SDK handles all HTTP logic internally (no need for fetchApi)
