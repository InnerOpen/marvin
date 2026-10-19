# Marvin SDK Architecture Plan

**Status**: Planning Document  
**Created**: 2026-07-06  
**Purpose**: Comprehensive plan for building TypeScript SDKs for all Marvin APIs

---

## Executive Summary

Marvin has **4 distinct API surfaces** that need SDK coverage:

1. ✅ **Publishing API** (`/api/publish`) - SDK exists at `packages/marvin-sdk`
2. ⚠️ **Platform API** (`/api/platform`) - Partial (frontend code only, not packaged)
3. ❌ **Admin API** (`/api/admin`) - No SDK
4. ❌ **Auth/User APIs** (`/api/auth`, `/api/users`) - No SDK

**Current State**: We have a well-architected Publishing SDK but it's not published to npm. The CLI duplicates SDK functionality, and the frontend has tightly-coupled API client code.

**Recommended Approach**: Unified monorepo package `@marvin/sdk` with subpath exports for different API surfaces, sharing a common core.

---

## API Landscape Overview

### 1. Publishing API (`/api/publish/{workspace_slug}`)

**Purpose**: Read-only content delivery for external sites  
**Auth**: API client tokens (`marvin_sk_*`) via Bearer  
**Consumers**: External sites (Astro, Next.js), static site generators  
**Existing SDK**: ✅ Yes - `packages/marvin-sdk/` (1,038 lines, TypeScript)

**Endpoints**:
- `GET /{workspace_slug}` - Workspace info
- `GET /{workspace_slug}/site` - Site configuration
- `GET /{workspace_slug}/entries` - List published entries (paginated)
- `GET /{workspace_slug}/entries/{slug}` - Get single entry
- `GET /{workspace_slug}/collections` - List collections (paginated)
- `GET /{workspace_slug}/collections/{slug}` - Get collection + entries
- `GET /{workspace_slug}/assets` - List assets (paginated)
- `GET /{workspace_slug}/assets/{slug}` - Get asset metadata
- `GET /{workspace_slug}/resources` - List resources (paginated)
- `GET /{workspace_slug}/resources/{slug}` - Get resource
- `GET /{workspace_slug}/resources/{slug}/entries` - Get resource's entries

**Key Features**:
- All endpoints filter by `status = 'published'`
- Supports incremental builds via `updated_since` parameter
- Includes related data (collections, resources, assets per entry)
- Pagination with `limit` and `offset`

---

### 2. Platform API (`/api/platform`)

**Purpose**: Workspace content management (CRUD)  
**Auth**: User session tokens (JWT or `marvin_tk_*`)  
**Consumers**: Marvin admin frontend, workspace management tools  
**Existing SDK**: ⚠️ Partial - Frontend has `lib/api/*.ts` but not packaged

**Endpoints**:
- `/entry-types` - GET (list entry types)
- `/entries` - GET, POST, PATCH, DELETE (CRUD entries)
- `/entries/{id}/collections` - GET, POST, DELETE (manage entry-collection links)
- `/collections` - GET, POST, PATCH, DELETE (CRUD collections)
- `/api-clients` - GET, POST, PATCH, DELETE (manage API clients)
- `/api-clients/{id}/rotate-token` - POST (regenerate API token)
- `/api-clients/{id}/preview` - GET (preview publishing payload)
- `/resources` - GET, POST, PATCH, DELETE (CRUD resources)
- `/assets` - GET, POST, PATCH, DELETE (CRUD assets)
- `/workspaces/{id}/members` - GET, POST, PATCH, DELETE (manage members)

**Key Features**:
- All endpoints workspace-scoped via user's `group_id`
- Role-based access control (OWNER > ADMIN > EDITOR > AUTHOR > VIEWER)
- Supports workspace member management
- API client token management for Publishing API

---

### 3. Admin API (`/api/admin`)

**Purpose**: Platform-level administrative operations  
**Auth**: Admin user session (requires `admin=true` flag)  
**Consumers**: Marvin admin UI, super admin tools  
**Existing SDK**: ❌ No

**Endpoints**:
- `/admin/about` - GET (platform version/info)
- `/admin/debug` - Various (debug utilities)
- `/admin/email` - POST (send test emails)
- `/admin/users` - GET, POST, PUT, DELETE (user CRUD)
- `/admin/users/unlock` - POST (unlock locked accounts)
- `/admin/users/password-reset-token` - POST (generate reset tokens)
- `/admin/groups` - GET, POST, PUT, DELETE (workspace CRUD)
- `/admin/maintenance` - Various (maintenance operations)
- `/admin/platform/*` - Various (admin views of platform data)

**Key Features**:
- Requires `admin=true` on user account
- Platform-level operations (not workspace-scoped)
- User and workspace management
- System maintenance utilities

---

### 4. Auth/User APIs (`/api/auth`, `/api/users`)

**Purpose**: User authentication, registration, password management  
**Auth**: Mixed (public + authenticated endpoints)  
**Consumers**: Login flows, user management UIs  
**Existing SDK**: ❌ No

**Endpoints**:
- `/api/auth/token` - POST (login, get JWT)
- `/api/auth/refresh` - GET (refresh token)
- `/api/users` - POST (user registration)
- `/api/users/forgot-password` - POST (request reset)
- `/api/users/{id}` - GET, PATCH (user profile)
- `/api/users/api-tokens` - GET, POST, DELETE (manage user API tokens)
- `/api/users/workspaces/activate` - POST (activate workspace)

---

## Recommended SDK Architecture

### Option A: Unified Package with Subpath Exports (RECOMMENDED)

```
@marvin/sdk
├── /publish     → Publishing API (external sites)
├── /platform    → Platform API (workspace management)
├── /admin       → Admin API (platform admin)
└── /auth        → Auth API (authentication)
```

**Installation**:
```bash
npm install @marvin/sdk
```

**Usage**:
```typescript
// External site (publishing)
import { createPublishingClient } from '@marvin/sdk/publish';
const client = createPublishingClient({
  apiUrl: 'https://marvin.example.com',
  token: 'marvin_sk_...',
  workspaceSlug: 'mash-and-burn-co'
});

// Workspace management
import { createPlatformClient } from '@marvin/sdk/platform';
const platform = createPlatformClient({
  apiUrl: 'https://marvin.example.com',
  userToken: 'marvin_tk_...'
});

// Admin tools
import { createAdminClient } from '@marvin/sdk/admin';
const admin = createAdminClient({
  apiUrl: 'https://marvin.example.com',
  adminToken: '...'
});
```

**Pros**:
- Single package to install
- Consistent API surface
- Shared types and utilities
- Tree-shakeable (unused modules don't bloat bundle)

**Cons**:
- Larger package size (mitigated by tree-shaking)
- Different auth contexts in one package

---

### Option B: Separate Packages (Alternative)

```
@marvin/publishing-sdk  → External sites
@marvin/platform-sdk    → Workspace management
@marvin/admin-sdk       → Platform admin
```

**Pros**:
- Clear separation of concerns
- Smaller package sizes
- Independent versioning

**Cons**:
- More packages to maintain
- Duplicated utilities/types
- Users need to install multiple packages

---

### Recommendation: Option A (Unified)

**Rationale**:
1. Most use cases need 2+ APIs (e.g., CLI needs Publishing + Platform)
2. Shared types (Entry, Collection, Asset) across APIs
3. Tree-shaking handles bundle size concerns
4. Simpler developer experience
5. Follows patterns of AWS SDK, Google Cloud SDK

---

## Monorepo Structure

```
packages/
  marvin-sdk/                    # Main SDK package
    src/
      index.ts                   # Root exports
      core/                      # Shared utilities
        http/                    # HTTP client base
        auth/                    # Auth strategies
        errors/                  # Error classes
        cache/                   # Caching utilities
        pagination/              # Pagination helpers
      publish/                   # Publishing API module
        index.ts
        client.ts
        entries.ts
        collections.ts
        resources.ts
        assets.ts
      platform/                  # Platform API module (NEW)
        index.ts
        client.ts
        entries.ts
        collections.ts
        workspaces.ts
        apiClients.ts
      admin/                     # Admin API module (NEW)
        index.ts
        client.ts
        users.ts
        workspaces.ts
      auth/                      # Auth API module (NEW)
        index.ts
        client.ts
        login.ts
        register.ts
      types/                     # Shared types
        common.ts
        entry.ts
        collection.ts
        resource.ts
        asset.ts
    package.json
    tsconfig.json
    README.md

  marvin-cli/                    # CLI tool (uses SDK)
    src/
      index.ts
      commands/
    package.json
```

---

## Authentication Patterns

### Strategy Pattern for Auth

```typescript
// Core auth interface
export interface AuthStrategy {
  injectAuth(headers: Headers): void;
  handleUnauthorized?(): Promise<void>;
}

// Publishing API: Bearer Token
export class BearerTokenAuth implements AuthStrategy {
  constructor(private token: string) {}
  
  injectAuth(headers: Headers): void {
    headers.set('Authorization', `Bearer ${this.token}`);
  }
}

// Platform/Admin API: Session Token
export class SessionAuth implements AuthStrategy {
  constructor(private sessionToken?: string) {}
  
  injectAuth(headers: Headers): void {
    if (this.sessionToken) {
      headers.set('Authorization', `Bearer ${this.sessionToken}`);
    }
    // Cookies handled automatically via credentials: 'include'
  }
  
  async handleUnauthorized(): Promise<void> {
    // Redirect to login or throw
  }
}

// Base HTTP Client
export abstract class BaseHttpClient {
  constructor(
    protected config: ClientConfig,
    protected authStrategy: AuthStrategy
  ) {}

  protected async request<T>(
    endpoint: string,
    options?: RequestOptions
  ): Promise<T> {
    const headers = new Headers(options?.headers);
    this.authStrategy.injectAuth(headers);
    
    // Retry logic, error handling, response parsing
    const response = await fetch(endpoint, { ...options, headers });
    
    if (!response.ok) {
      if (response.status === 401 && this.authStrategy.handleUnauthorized) {
        await this.authStrategy.handleUnauthorized();
      }
      throw new MarvinApiError(response.status, response.statusText, endpoint);
    }
    
    return response.json();
  }
}
```

---

## Type Safety Strategy

### Current Approach: Manual Types

**Keep for now** - Good for stability during rapid iteration

```typescript
// packages/marvin-sdk/src/types/entry.ts
export interface Entry {
  slug: string;
  title: string;
  entryType: string;
  summary?: string;
  contentMarkdown?: string;
  publishedAt?: string;
  metadata?: Record<string, unknown>;
  collections?: string[];
  resources?: Resource[];
  assets?: Asset[];
}
```

### Future Enhancement: OpenAPI Generation

```bash
# Generate types from FastAPI's OpenAPI schema
curl http://localhost:8000/openapi.json -o packages/marvin-sdk/openapi.json
npx openapi-typescript packages/marvin-sdk/openapi.json -o packages/marvin-sdk/src/types/generated.ts
```

**Hybrid Approach (Long-term)**:
- Base types generated from OpenAPI (ensures backend/frontend alignment)
- Enhanced types hand-written (richer object models like Entry, Workspace classes)
- Similar to Stripe's pattern: Generated base + manual enhancements

---

## Implementation Roadmap

### Phase 1: Publish Existing SDK ✅ (Current State)

**Status**: Publishing SDK exists but not published to npm

**Tasks**:
1. ✅ Publishing SDK is ready (`packages/marvin-sdk`)
2. ⬜ Add build tooling (tsup or tsc)
3. ⬜ Add package.json exports configuration
4. ⬜ Publish to npm as `@marvin/sdk@1.0.0`
5. ⬜ Migrate CLI to use published package
6. ⬜ Update Mash & Burn Co. site to use npm package

**Current CLI Duplication**:
- `apps/cli/marvin-cli/src/marvin-sdk.ts` (191 lines) duplicates functionality
- Should migrate to use `@marvin/sdk/publish`

---

### Phase 2: Extract Shared Core (1-2 days)

**Goal**: Create reusable core utilities for all SDK modules

**Tasks**:
1. Create `packages/marvin-sdk/src/core/` directory
2. Extract HTTP client base from existing publishing SDK
3. Extract error classes (`MarvinApiError`, `MarvinAuthError`)
4. Extract retry logic and rate limiting
5. Add auth strategy interface
6. Extract pagination helpers
7. Update publishing SDK to use core utilities

**Files to Create**:
```
packages/marvin-sdk/src/core/
  http/
    client.ts          # BaseHttpClient
    types.ts           # RequestOptions, ClientConfig
  auth/
    strategies.ts      # AuthStrategy interface
    bearerToken.ts     # BearerTokenAuth
    session.ts         # SessionAuth
  errors/
    index.ts           # MarvinApiError classes
  pagination/
    helpers.ts         # paginate() generator
    types.ts           # PaginatedResponse<T>
  utils/
    queryString.ts     # Query parameter builder
```

---

### Phase 3: Add Platform API Module (3-5 days)

**Goal**: Add workspace management capabilities to SDK

**Tasks**:
1. Create `packages/marvin-sdk/src/platform/` module
2. Implement session-based auth strategy
3. Extract frontend API client structure from `frontend/src/lib/api/*.ts`
4. Add workspace/user/collection management methods
5. Add entry CRUD operations
6. Add API client (site client) management
7. Add comprehensive types for platform API

**Files to Create**:
```
packages/marvin-sdk/src/platform/
  index.ts               # Platform SDK exports
  client.ts              # PlatformClient class
  entries.ts             # EntryManager (CRUD)
  collections.ts         # CollectionManager (CRUD)
  resources.ts           # ResourceManager (CRUD)
  assets.ts              # AssetManager (CRUD)
  workspaces.ts          # WorkspaceManager
  apiClients.ts          # APIClientManager
  types.ts               # Platform-specific types
```

**Example Usage**:
```typescript
import { createPlatformClient } from '@marvin/sdk/platform';

const platform = createPlatformClient({
  apiUrl: process.env.MARVIN_API_URL,
  userToken: process.env.MARVIN_USER_TOKEN,
});

// Create entry
const entry = await platform.entries.create({
  title: 'New Project',
  slug: 'new-project',
  entryTypeSlug: 'project',
  status: 'draft',
  contentMarkdown: '# My New Project\n\nDetails here...',
});

// Rotate API client token
const newToken = await platform.apiClients.rotateToken('client-id');
console.log('New token:', newToken.token);
```

---

### Phase 4: Add Admin API Module (2-3 days)

**Goal**: Add platform administration capabilities

**Tasks**:
1. Create `packages/marvin-sdk/src/admin/` module
2. Implement admin-level auth validation
3. Add user management methods
4. Add workspace management methods
5. Add platform-level operations

**Files to Create**:
```
packages/marvin-sdk/src/admin/
  index.ts               # Admin SDK exports
  client.ts              # AdminClient class
  users.ts               # UserManager (platform-level)
  workspaces.ts          # WorkspaceManager (create/delete)
  maintenance.ts         # MaintenanceManager
  types.ts               # Admin-specific types
```

---

### Phase 5: Add Auth API Module (1-2 days)

**Goal**: Add authentication flow support

**Tasks**:
1. Create `packages/marvin-sdk/src/auth/` module
2. Add login/logout methods
3. Add registration support
4. Add password reset flows
5. Add token refresh logic

**Files to Create**:
```
packages/marvin-sdk/src/auth/
  index.ts               # Auth SDK exports
  client.ts              # AuthClient class
  login.ts               # LoginManager
  register.ts            # RegistrationManager
  passwordReset.ts       # PasswordResetManager
  types.ts               # Auth-specific types
```

---

### Phase 6: CLI Integration (1 day)

**Goal**: Migrate CLI to use unified SDK

**Tasks**:
1. Update CLI to import from `@marvin/sdk/publish`
2. Add platform SDK for workspace management commands
3. Remove duplicate SDK code from `apps/cli/marvin-cli/src/marvin-sdk.ts`
4. Update CLI commands to use new SDK methods
5. Test all CLI commands

**Before**:
```typescript
// apps/cli/marvin-cli/src/marvin-sdk.ts
export function createMarvinClient(config) {
  // 191 lines of duplicated SDK code
}
```

**After**:
```typescript
// apps/cli/marvin-cli/src/index.ts
import { createPublishingClient } from '@marvin/sdk/publish';
import { createPlatformClient } from '@marvin/sdk/platform';

const publish = createPublishingClient({ ... });
const platform = createPlatformClient({ ... });
```

---

### Phase 7: Frontend Migration (3-5 days)

**Goal**: Migrate admin frontend to use SDK

**Tasks**:
1. Replace `frontend/src/lib/api/*.ts` with SDK imports
2. Update Astro pages to use platform SDK
3. Handle session-based auth in browser context
4. Test all admin UI workflows
5. Remove old API client code

**Before**:
```typescript
// frontend/src/lib/api/entries.ts
export async function getEntries() {
  const response = await fetch('/api/platform/entries', {
    credentials: 'include',
  });
  return response.json();
}
```

**After**:
```typescript
// frontend/src/lib/marvin.ts
import { createPlatformClient } from '@marvin/sdk/platform';

export const platform = createPlatformClient({
  apiUrl: import.meta.env.PUBLIC_API_URL,
  // Session handled via cookies automatically
});

// frontend/src/pages/entries/index.astro
const entries = await platform.entries.list();
```

---

### Phase 8: Documentation & Examples (2-3 days)

**Goal**: Comprehensive documentation for SDK

**Tasks**:
1. Write API reference docs (JSDoc → generated)
2. Create usage examples for each API surface
3. Write migration guides (CLI, frontend)
4. Create integration tutorials (Astro, Next.js)
5. Add TypeScript examples
6. Document authentication patterns

**Documentation Structure**:
```
packages/marvin-sdk/
  README.md              # Overview, installation
  docs/
    publishing/
      README.md          # Publishing API guide
      examples.md        # Code examples
    platform/
      README.md          # Platform API guide
      examples.md        # Code examples
    admin/
      README.md          # Admin API guide
      examples.md        # Code examples
    auth/
      README.md          # Auth API guide
      examples.md        # Code examples
    guides/
      astro-integration.md
      nextjs-integration.md
      cli-usage.md
    api-reference/       # Generated from JSDoc
```

---

## Build & Distribution

### Package Configuration

```json
// packages/marvin-sdk/package.json
{
  "name": "@marvin/sdk",
  "version": "1.0.0",
  "type": "module",
  "main": "./dist/index.js",
  "module": "./dist/index.mjs",
  "types": "./dist/index.d.ts",
  "exports": {
    ".": {
      "import": "./dist/index.mjs",
      "require": "./dist/index.js",
      "types": "./dist/index.d.ts"
    },
    "./publish": {
      "import": "./dist/publish/index.mjs",
      "require": "./dist/publish/index.js",
      "types": "./dist/publish/index.d.ts"
    },
    "./platform": {
      "import": "./dist/platform/index.mjs",
      "require": "./dist/platform/index.js",
      "types": "./dist/platform/index.d.ts"
    },
    "./admin": {
      "import": "./dist/admin/index.mjs",
      "require": "./dist/admin/index.js",
      "types": "./dist/admin/index.d.ts"
    },
    "./auth": {
      "import": "./dist/auth/index.mjs",
      "require": "./dist/auth/index.js",
      "types": "./dist/auth/index.d.ts"
    }
  },
  "files": ["dist/**/*", "README.md"],
  "scripts": {
    "build": "tsup src/index.ts src/publish/index.ts src/platform/index.ts src/admin/index.ts src/auth/index.ts --format esm,cjs --dts",
    "dev": "tsup --watch",
    "prepublishOnly": "npm run build"
  },
  "dependencies": {},
  "devDependencies": {
    "tsup": "^8.0.0",
    "typescript": "^5.0.0"
  }
}
```

### Build Tool: tsup

**Why tsup**:
- Zero config TypeScript bundler
- Supports ESM + CJS simultaneously
- Automatic .d.ts generation
- Tree-shakeable output
- Fast builds

```bash
# Build command generates:
dist/
  index.js              # CJS bundle
  index.mjs             # ESM bundle
  index.d.ts            # TypeScript definitions
  publish/
    index.js
    index.mjs
    index.d.ts
  platform/
    index.js
    index.mjs
    index.d.ts
  # ... etc
```

---

## Error Handling Strategy

```typescript
// packages/marvin-sdk/src/core/errors/index.ts

export class MarvinApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public endpoint: string,
    public body?: unknown
  ) {
    super(`Marvin API error: ${status} ${statusText} at ${endpoint}`);
    this.name = 'MarvinApiError';
  }
  
  get isClientError(): boolean {
    return this.status >= 400 && this.status < 500;
  }
  
  get isServerError(): boolean {
    return this.status >= 500;
  }
  
  get isRetryable(): boolean {
    return this.isServerError || this.status === 429;
  }
}

export class MarvinAuthError extends MarvinApiError {
  constructor(endpoint: string, body?: unknown) {
    super(401, 'Unauthorized', endpoint, body);
    this.name = 'MarvinAuthError';
  }
}

export class MarvinRateLimitError extends MarvinApiError {
  constructor(
    endpoint: string,
    public retryAfter?: number,
    body?: unknown
  ) {
    super(429, 'Too Many Requests', endpoint, body);
    this.name = 'MarvinRateLimitError';
  }
}

export class MarvinNotFoundError extends MarvinApiError {
  constructor(endpoint: string, body?: unknown) {
    super(404, 'Not Found', endpoint, body);
    this.name = 'MarvinNotFoundError';
  }
}
```

---

## Pagination Strategy

```typescript
// packages/marvin-sdk/src/core/pagination/helpers.ts

export interface PaginatedResponse<T> {
  data: T[];
  meta: {
    total: number;
    page: number;
    limit: number;
    offset: number;
  };
}

export async function* paginate<T>(
  fetcher: (offset: number, limit: number) => Promise<PaginatedResponse<T>>,
  limit: number = 50
): AsyncGenerator<T[], void, undefined> {
  let offset = 0;
  let hasMore = true;
  
  while (hasMore) {
    const response = await fetcher(offset, limit);
    yield response.data;
    
    offset += limit;
    hasMore = offset < response.meta.total;
  }
}

// Usage example:
for await (const entries of paginate((offset, limit) => 
  client.entries.list({ offset, limit })
)) {
  console.log(`Got ${entries.length} entries`);
  // Process batch
}
```

---

## Testing Strategy

### Unit Tests (Jest/Vitest)

```typescript
// packages/marvin-sdk/src/publish/__tests__/client.test.ts

import { describe, it, expect, vi } from 'vitest';
import { createPublishingClient } from '../client';

describe('PublishingClient', () => {
  it('should fetch entries', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        data: [{ slug: 'test', title: 'Test' }],
        meta: { total: 1, page: 1, limit: 10, offset: 0 }
      })
    });
    
    const client = createPublishingClient({
      apiUrl: 'http://test',
      token: 'test-token',
      workspaceSlug: 'test'
    });
    
    const entries = await client.entries.list();
    expect(entries).toHaveLength(1);
    expect(entries[0].slug).toBe('test');
  });
});
```

### Integration Tests (Against Live API)

```typescript
// packages/marvin-sdk/integration/__tests__/publish.test.ts

import { createPublishingClient } from '@marvin/sdk/publish';

describe('Publishing API Integration', () => {
  const client = createPublishingClient({
    apiUrl: process.env.TEST_API_URL!,
    token: process.env.TEST_SITE_TOKEN!,
    workspaceSlug: 'test-workspace'
  });
  
  it('should fetch real entries', async () => {
    const entries = await client.entries.list({ limit: 5 });
    expect(Array.isArray(entries)).toBe(true);
  });
});
```

---

## Package Versioning Strategy

**Semantic Versioning (semver)**:
- `1.0.0` - Initial stable release
- `1.1.0` - New features (backward compatible)
- `1.0.1` - Bug fixes
- `2.0.0` - Breaking changes

**Pre-releases**:
- `1.0.0-alpha.1` - Alpha releases
- `1.0.0-beta.1` - Beta releases
- `1.0.0-rc.1` - Release candidates

**Tag Strategy**:
```bash
# Publish beta
npm version 1.0.0-beta.1
npm publish --tag beta

# Publish stable
npm version 1.0.0
npm publish
```

---

## Migration Paths

### For Existing `packages/marvin-sdk` Users

Currently, `packages/marvin-sdk` is used internally via file paths. After publishing:

**Before**:
```json
{
  "dependencies": {
    "@marvin/sdk": "file:../../packages/marvin-sdk"
  }
}
```

**After**:
```json
{
  "dependencies": {
    "@marvin/sdk": "^1.0.0"
  }
}
```

### For CLI (`apps/cli/marvin-cli`)

**Before** (duplicated SDK):
```typescript
import { createMarvinClient } from './marvin-sdk';
const client = createMarvinClient({ ... });
```

**After** (use published SDK):
```typescript
import { createPublishingClient } from '@marvin/sdk/publish';
const client = createPublishingClient({ ... });
```

### For Frontend (`frontend/src/lib/api/*.ts`)

**Before** (custom fetch calls):
```typescript
export async function getEntries() {
  const response = await fetch('/api/platform/entries', {
    credentials: 'include',
  });
  return response.json();
}
```

**After** (use SDK):
```typescript
import { createPlatformClient } from '@marvin/sdk/platform';

export const platform = createPlatformClient({
  apiUrl: import.meta.env.PUBLIC_API_URL,
});

export const getEntries = () => platform.entries.list();
```

---

## Success Criteria

### Phase 1: Publishing SDK Published
- [ ] Package published to npm as `@marvin/sdk@1.0.0`
- [ ] CLI migrated to use npm package
- [ ] Mash & Burn Co. site using npm package
- [ ] Documentation complete

### Phase 2: Shared Core Extracted
- [ ] `core/` module created with shared utilities
- [ ] Publishing SDK refactored to use core
- [ ] Unit tests passing
- [ ] No breaking changes to public API

### Phase 3: Platform SDK Added
- [ ] Platform module complete with CRUD operations
- [ ] Frontend can use SDK for API calls
- [ ] Session auth working in browser
- [ ] Integration tests passing

### Phase 4: Admin SDK Added
- [ ] Admin module complete
- [ ] User/workspace management working
- [ ] Admin UI can use SDK
- [ ] Proper admin auth validation

### Phase 5: Auth SDK Added
- [ ] Login/logout flows working
- [ ] Registration working
- [ ] Password reset working
- [ ] Token refresh working

### Phase 6-8: Full Migration
- [ ] CLI 100% using SDK (no duplicate code)
- [ ] Frontend 100% using SDK (no custom API client)
- [ ] Full API reference documentation
- [ ] Integration guides for Astro, Next.js
- [ ] Example projects

---

## Open Questions

1. **npm Registry**: Publish to public npm or private GitHub Packages?
   - **Recommendation**: Start with public npm (easier for external sites)

2. **OpenAPI Generation**: When to implement?
   - **Recommendation**: Phase 9 (after manual types proven stable)

3. **Caching Layer**: Should SDK include built-in caching?
   - **Recommendation**: Yes, optional via config (see current SDK's cache support)

4. **Browser vs Node**: Support both environments?
   - **Recommendation**: Yes (fetch API works in both)

5. **React Hooks**: Should we add React-specific utilities?
   - **Recommendation**: Separate package `@marvin/sdk-react` (future)

---

## Next Steps

**Immediate Actions** (this week):
1. Review this plan with team
2. Decide on npm vs GitHub Packages
3. Set up build tooling in `packages/marvin-sdk`
4. Publish first beta: `@marvin/sdk@1.0.0-beta.1`
5. Test beta in CLI

**Short-term** (next 2 weeks):
1. Publish stable `@marvin/sdk@1.0.0` (publishing only)
2. Extract shared core
3. Start platform SDK module

**Medium-term** (next 4-6 weeks):
1. Complete platform SDK
2. Complete admin SDK
3. Complete auth SDK
4. Migrate CLI and frontend
5. Write documentation

---

## References

- [Marvin Roadmap](/docs/MARVIN_ROADMAP.md)
- [Publishing API Documentation](/docs/PUBLISHING-API-COMPLETE.md)
- [Existing SDK](/packages/marvin-sdk/)
- [CLI Tool](/apps/cli/marvin-cli/)

---

**Last Updated**: 2026-07-06  
**Status**: Planning - Ready for Review
