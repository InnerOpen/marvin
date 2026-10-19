# Frontend SDK Migration Status

## ✅ Completed

### 1. SDK Installation
- Installed `@inneropen/marvin-sdk@^1.3.0` in frontend

### 2. SDK Factory Created
- `src/lib/sdk.ts` - Creates Platform API clients for Astro SSR

### 3. API Modules Migrated to SDK
All core API modules now use the SDK instead of direct HTTP calls:

| Module | Status | Notes |
|--------|--------|-------|
| **entries.ts** | ✅ Migrated | All 8 methods using SDK |
| **collections.ts** | ✅ Migrated | 5 methods using SDK |
| **resources.ts** | ✅ Migrated | 5 methods using SDK |
| **platform.ts** | ✅ Migrated | Assets + API clients (7 methods) |
| **entryTypes.ts** | ✅ Migrated | 2 methods using SDK |
| **workspaces.ts** | ✅ Migrated | 7 methods using SDK |
| **workspaceMembers.ts** | ✅ Migrated | 5 methods using SDK |
| **invites.ts** | ⏸️ Not migrated | SDK doesn't have invites module yet |
| **workspaceSettings.ts** | ⏸️ Not migrated | SDK doesn't have workspace settings yet |

### 4. Type Re-exports
All migrated modules re-export SDK types with legacy names for backward compatibility:
- `EntryRead` → `PlatformEntry`
- `CollectionRead` → `PlatformCollection`
- `ResourceRead` → `PlatformResource`
- etc.

## ⚠️ Known Issues

### 1. Missing SDK Methods
These frontend methods don't have SDK equivalents yet:
- `collections.getEntries(collectionId)` - Get entries in a collection
- `resources.getEntries(resourceId)` - Get entries referencing a resource

**Temporary workaround:** These methods currently return empty arrays. Need to either:
- Add these endpoints to the SDK, or
- Use a different approach in the frontend

### 2. Auth Token Required
SDK methods now require authToken (not optional). Added checks in:
- `WorkspaceSwitcher.astro` - Checks for authToken before calling API

### 3. Field Name Changes
SDK uses camelCase field names instead of snake_case:
- `focal_point` → `focalPoint`
- `alt_text` → `altText`
- `mime_type` → `mimeType`

**Impact:** Components using these fields need updating:
- `EntryCard.astro` - Uses asset fields
- `sample-data.ts` - Test data needs field name updates

### 4. Type Mismatches
Some frontend types don't match SDK types exactly:
- `MarvinEntry` expects `groupId` and `entryTypeId` fields
- SDK types may have different field structures

## 📝 TODO

### High Priority
1. **Fix field name references** in components:
   - Update `EntryCard.astro` to use camelCase field names
   - Update `sample-data.ts` test data

2. **Add missing SDK methods**:
   - Add `collections.getEntries()` to SDK
   - Add `resources.getEntries()` to SDK

3. **Test all pages** to ensure SDK integration works

### Medium Priority
1. **Add invites module to SDK**
   - Migrate `invites.ts` when SDK supports it

2. **Add workspace settings to SDK**
   - Migrate `workspaceSettings.ts` when SDK supports it

3. **Type alignment**:
   - Review type mismatches between frontend and SDK
   - Update frontend types to match SDK where appropriate

### Low Priority
1. **Remove old client.ts** (keep config.ts):
   - Once all pages are tested and working
   - Remove `fetchApi` and related code

2. **Clean up type re-exports**:
   - Consider importing SDK types directly in components
   - Remove legacy type names

## 🧪 Testing Checklist

- [ ] List entries page works
- [ ] View entry details works
- [ ] Create entry works
- [ ] Update entry works
- [ ] Delete entry works
- [ ] Collections CRUD works
- [ ] Resources CRUD works
- [ ] Assets list works
- [ ] API clients management works
- [ ] Workspace switching works
- [ ] Workspace members management works
- [ ] Entry types list works

## 📊 Migration Progress

**Overall: 75% Complete**

- ✅ SDK Installed
- ✅ SDK Factory Created
- ✅ 7/9 API modules migrated
- ⏸️ 2/9 modules pending SDK support
- ⚠️ Type/field name fixes needed
- ⏳ Testing incomplete

## Next Steps

1. Run TypeScript check and fix remaining errors
2. Test basic CRUD operations
3. Add missing SDK methods or workarounds
4. Full integration testing
5. Deploy and monitor
