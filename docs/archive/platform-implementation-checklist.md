# Marvin Platform Implementation Checklist

Use this checklist to track the first platform sprint.

## Branch

```text
marvin-platform-plan
```

## Sprint 1: Documentation

- [x] Add Marvin platform architecture plan.
- [x] Add data model notes.
- [x] Add publishing API notes.
- [x] Add site client notes.
- [x] Add AI intake notes as a future phase.

## Sprint 2: Database Migration

Add one Alembic migration for the first platform data slice.

- [x] entry_types
- [x] entries
- [ ] collections
- [ ] entry_collections
- [ ] resources
- [ ] entry_resources
- [ ] assets
- [ ] entry_assets
- [ ] site_clients

Rules:

- [x] Use existing `groups` table as the workspace boundary.
- [x] Add `group_id` to all workspace-scoped tables.
- [x] Do not rename `groups` yet.
- [x] Do not create a separate `workspaces` table yet.

## Sprint 3: Backend Models

- [x] Add SQLAlchemy models.
- [x] Add Pydantic schemas.
- [x] Add repositories.
- [x] Follow existing Marvin patterns.

## Sprint 4: Authenticated APIs

Authenticated user routes:

- [x] `GET /api/entry-types`
- [x] `POST /api/entry-types`
- [x] `GET /api/entry-types/{id}`
- [x] `PATCH /api/entry-types/{id}`
- [x] `DELETE /api/entry-types/{id}`
- [x] `GET /api/entries`
- [x] `POST /api/entries`
- [x] `GET /api/entries/{id}`
- [x] `PATCH /api/entries/{id}`
- [x] `DELETE /api/entries/{id}`

Rules:

- [x] Scope all entry type and entry queries to the current user's `group_id`.
- [x] Keep entry type slugs unique within a group.
- [x] Keep entry slugs unique within a group.
- [x] Prevent deleting entry types that are used by entries.

## Sprint 4.5: Tests

- [ ] Add route/repository tests for entry types.
- [ ] Add route/repository tests for entries.
- [ ] Add route/repository tests for collections.
- [x] Document missing tests because the project currently has no clear route/repository test pattern beyond shared test setup.

## Phase 1.5: Make Entries Feel Real

- [ ] Seed default entry types when workspace is created (Page, Project, Article, Guide)
- [ ] Wire seeding to group registration flow
- [ ] Support user-customizable seed templates
- [ ] Add status workflow validation (draft → review → published)

See: `/Volumes/Code/Marvin/SEED_IMPROVEMENTS.md`

## Phase 3: Publishing API

**This is where Marvin becomes special.**

Astro doesn't care about your admin API. It only talks to the publish API.

See: `/Volumes/Code/Marvin/docs/phase-3-publishing.md`

### Site Clients Table

- [ ] Run migration for site_clients table
- [ ] Add site client CRUD routes (create, list, update, revoke)
- [ ] Implement token generation (show plaintext once)
- [ ] Implement token hashing (bcrypt)

### Publishing Auth

- [ ] Create publishing auth middleware
- [ ] Validate site client tokens
- [ ] Enforce workspace matching
- [ ] Update last_used_at timestamp
- [ ] Add rate limiting (1000 req/hour per token)

### Publishing Routes

- [ ] `GET /api/publish/{workspace}` - Workspace info
- [ ] `GET /api/publish/{workspace}/entries` - List published entries
- [ ] `GET /api/publish/{workspace}/entries/{slug}` - Get published entry
- [ ] `GET /api/publish/{workspace}/pages/{slug}` - Get published page
- [ ] `GET /api/publish/{workspace}/articles/{slug}` - Get published article
- [ ] `GET /api/publish/{workspace}/projects/{slug}` - Get published project
- [ ] `GET /api/publish/{workspace}/collections/{slug}` - Get collection with entries
- [ ] `GET /api/publish/{workspace}/assets/{slug}` - Serve asset

### Publishing Rules

- [ ] Filter to `status = 'published'` only
- [ ] Exclude all admin fields
- [ ] Exclude draft/archived entries
- [ ] Generate frontmatter from structured data
- [ ] Return asset URLs and alt text
- [ ] Support pagination (page, limit)
- [ ] Support filtering (type, collection)

## Phase 4: Astro Integration

- [ ] Document Astro client library
- [ ] Example TypeScript fetch functions
- [ ] Example dynamic route ([...slug].astro)
- [ ] Example collection listing page
- [ ] Environment variable setup (.env.example)
- [ ] Frontmatter mapping examples
- [ ] Asset URL handling
- [ ] Error handling (404, 403, rate limit)

## Implementation Status

| Phase | Progress | Status | Notes |
|-------|----------|--------|-------|
| 1: Documentation | 100% | ✅ Complete | All architecture docs added, Phase 3 plan added |
| 2: Database Migration | 60% | 🚧 Partial | Entry types, entries, collections done; resources/assets/site_clients pending |
| 3: Backend Models | 60% | 🚧 Partial | Models exist for all tables, only 3 fully wired |
| 4: Authenticated APIs | 60% | 🚧 Partial | Entry types, entries, collections fully functional |
| 4.5: Tests | 10% | 🔴 Blocked | No test pattern established yet |
| 1.5: Make Entries Real | 0% | ⏳ Planned | Seeding plan ready for implementation |
| 3: Publishing API | 0% | ⏳ Planned | Full implementation plan documented |
| 4: Astro Integration | 0% | ⏳ Planned | Depends on Publishing API |

## Next Steps

1. **Test Database Migration**
   ```bash
   task py
   # In Python shell:
   from marvin.db.db_setup import init_db
   init_db()
   ```

2. **Test Authenticated APIs**
   ```bash
   curl -H "Authorization: Bearer <token>" \
     -X POST http://localhost:8000/api/entry-types \
     -H "Content-Type: application/json" \
     -d '{"name": "Article", "slug": "article"}'
   ```

3. **Add Focused Tests**
   - Add repository tests for group scoping and slug uniqueness.
   - Add route tests for authenticated CRUD behavior.
   - Add delete-prevention coverage for entry types in use.

## Future Work

- Smart collection rules engine
- Collections
- Resources
- Assets
- Site clients
- Publishing API
- Astro integration
- Asset transformation pipeline (resize, format conversion)
- Advanced permission scoping
- Webhook system for publish events
- AI-assisted intake (see ai-intake-future.md)


## Future Phase: AI Intake

Do not implement this yet.

- [ ] Voice note intake.
- [ ] Image upload intake.
- [ ] AI-generated draft entries.
- [ ] Suggested titles, summaries, tags, and collections.
- [ ] Human review before publish.
