# Marvin Platform Architecture Review
**Date**: 2026-07-05  
**Reviewer**: Lead Architect (Simulation)  
**Status**: Critical Pre-Production Review

---

## Executive Summary

Marvin has successfully transitioned from "Mealie without recipes" to a **structured content operating system**. The core hierarchy is well-defined, patterns are consistent, and the foundation supports the vision. However, several architectural decisions need refinement before the platform scales.

**Overall Grade**: B+ (Good foundation, needs strategic refinement)

**Recommendation**: Address the 6 critical issues in "Technical Debt" before building additional features.

---

## 1. Architecture Consistency

### ✅ What's Working Well

**Repository Pattern**  
All repositories follow `GroupRepositoryGeneric` consistently:
- EntryTypesRepository
- EntriesRepository
- CollectionsRepository
- ResourcesRepository
- AssetsRepository
- APIClientsRepository

**Controller Pattern**  
All controllers follow `BaseUserController`:
- Consistent CRUD endpoints
- Proper authentication injection
- Standard error responses
- Workspace scoping via `self.repos`

**Schema Pattern**  
Consistent triads across the board:
- `XxxCreate` (input)
- `XxxUpdate` (partial)
- `XxxRead` (output)
- Optional: `XxxSummary` (list views)

**Naming Conventions**  
- Database: `snake_case` (entries, entry_types, entry_collections)
- Models: `PascalCase` (Entries, EntryTypes)
- JSON fields: `metadata_json`, `metadata_` (SQLAlchemy attribute mapping)
- Routes: `/api/resources`, `/api/entry-types` (kebab-case with plurals)

### ⚠️ Inconsistencies Found

**1. Junction Table Naming**
```
✅ entry_collections
✅ entry_resources  
✅ entry_assets
❌ Missing: entry_resources relationship back to Entries
```

**EntryResources** model has no back-references to Entries/Resources like EntryAssets does. This is an asymmetry that will cause confusion.

**2. Metadata Field Naming**
```python
# Entries model
metadata_json: Mapped[dict | None]  # ← "metadata_json"

# Resources model  
metadata_: Mapped[dict | None] = mapped_column("metadata", ...)  # ← "metadata"

# Assets model
metadata_: Mapped[dict | None] = mapped_column("metadata", ...)  # ← "metadata"
```

**Issue**: Entries uses `metadata_json` in the database. Resources/Assets use `metadata` in the database but `metadata_` in Python. This is confusing and breaks the pattern.

**Recommendation**: Standardize on `metadata` (database) + `metadata_` (Python attribute) everywhere. Rename Entries.metadata_json → metadata in a migration.

**3. Summary Schema Inheritance**

```python
# entries.py
class EntrySummary(EntryRead):  # Inherits ALL fields from EntryRead
    pass

# entry_types.py  
class EntryTypeSummary(EntryTypeRead):  # Same pattern
    pass

# collections.py
class CollectionSummary(_MarvinModel):  # Does NOT inherit from CollectionRead
    # Duplicates fields instead
```

**Issue**: Collections broke the pattern. Summary should inherit from Read or we should pick one approach and stick with it.

---

## 2. Data Model Review

### Table-by-Table Analysis

#### ✅ `entry_types`
```sql
✓ id, group_id, name, slug, icon, color, description
✓ sort_order (UI ordering)
✓ is_system (prevent deletion of built-in types)
✓ UNIQUE(group_id, slug)
✓ FK group_id → groups.id CASCADE
```

**Status**: Excellent. No changes needed.

**Missing**: Nothing critical. `metadata` column could be added later for extensibility.

#### ✅ `entries`
```sql
✓ id, group_id, entry_type_id, title, slug, summary, description
✓ content_markdown (core content)
✓ status (inbox → published workflow)
✓ published_at (temporal publishing)
✓ metadata_json (Astro frontmatter)
✓ UNIQUE(group_id, slug)
✓ INDEX(group_id, status) ← Good for publishing queries
✓ FK entry_type_id → entry_types RESTRICT ← Prevents accidental deletion
```

**Status**: Very good.

**Issues**:
1. **Field naming**: `metadata_json` should be `metadata` for consistency
2. **Missing author**: No `created_by` or `author_id` field
3. **Missing version tracking**: No `version` or `revision_number`

**Recommendation**: Add `created_by` (FK to users.id) now. Version tracking can wait.

#### ⚠️ `collections`
```sql
✓ id, group_id, name, slug, description
✓ is_smart (manual vs rule-based)
✓ smart_rules (JSON query definition)
✓ UNIQUE(group_id, slug)
```

**Status**: Good foundation.

**Missing**:
1. **No sort_order**: Collections should have display order like entry types
2. **No icon/color**: Collections should have visual identity like entry types
3. **No created_by**: Who made this collection?

**Smart rules status**: Field exists, engine doesn't. This is fine for MVP but document the roadmap clearly.

#### ✅ `entry_collections`
```sql
✓ id, entry_id, collection_id
✓ position (ordering within collection)
✓ UNIQUE(entry_id, collection_id)
✓ INDEX(entry_id), INDEX(collection_id)
```

**Status**: Perfect. Clean junction table with position ordering.

**Note**: Relationships have proper `overlaps` warnings fixed. Good.

#### ⚠️ `resources`
```sql
✓ id, group_id, slug, name, resource_type, description
✓ metadata (JSON extensibility)
✓ created_by (audit trail)
✓ UNIQUE(group_id, slug)
```

**Status**: Good.

**Issues**:
1. **No resource categories**: `resource_type` is free-text, not normalized
2. **No external_id**: Can't track "this is the same fabric from supplier X"
3. **No url**: Many resources (APIs, repos, suppliers) have URLs

**Recommendation**: Add `url`, `external_id`, `supplier_name` as optional fields.

#### ⚠️ `entry_resources`
```sql
✓ id, entry_id, resource_id
✓ role (e.g., "primary", "alternative")
✓ quantity, unit (e.g., "2 yards")
✓ UNIQUE(entry_id, resource_id)
```

**Status**: Good start.

**Missing**:
1. **No position**: Can't order resources in display
2. **No back-references**: EntryResources model has no .entry or .resource relationships
3. **Notes field**: Often need "substitute with X if Y unavailable"

**Critical**: Add relationships to EntryResources model like EntryAssets has.

#### ✅ `assets`
```sql
✓ id, group_id, slug, name, file_path, file_size, mime_type
✓ width, height (image metadata)
✓ alt_text (accessibility)
✓ description, metadata (extensibility)
✓ uploaded_by (audit trail)
✓ UNIQUE(group_id, slug)
```

**Status**: Excellent. Well thought out.

**Future additions** (not critical now):
- `hash` (SHA256 for deduplication)
- `original_filename` (preserve upload name)
- `folder` or `path` hierarchy

#### ✅ `entry_assets`
```sql
✓ id, entry_id, asset_id
✓ position (display order)
✓ role (hero, featured, inline, download)
✓ usage (material, process, detail)
✓ focal_point (cropping hint)
✓ caption (override alt_text per entry)
✓ metadata (placement-specific data)
✓ UNIQUE(entry_id, asset_id)
```

**Status**: Outstanding. This is exactly right.

**Relationships**: Properly defined with `overlaps` warnings handled.

---

### Hierarchy Validation

**Stated Hierarchy**:
```
Workspace (groups)
  ↓
Entry Types
  ↓
Entries
  ↓
Collections
  ↓
Resources
  ↓
Assets
```

**Actual Implementation**:
```
Workspace (groups)
  ↓
Entry Types ──┐
  ↓           ├─→ Entries ←──┬─→ Collections (M:M)
Resources ────┘             ├─→ Resources (M:M)
Assets ─────────────────────┴─→ Assets (M:M)
```

**Analysis**:

❌ **The hierarchy is incorrect.**

The diagram suggests:
- Collections contain Resources
- Resources contain Assets

But the implementation shows:
- **Entries** are the central node
- Collections, Resources, and Assets are **peer relationships** to Entries

**Actual Hierarchy** (as implemented):

```
Workspace
  ├─ Entry Types (define schemas)
  ├─ Collections (group entries)
  ├─ Resources (reusable objects)
  ├─ Assets (files)
  └─ Entries (content)
       ├─ belongs to 1 Entry Type
       ├─ belongs to N Collections (M:M)
       ├─ references N Resources (M:M)
       └─ includes N Assets (M:M)
```

**Recommendation**: Update documentation to reflect that Entries are the hub, not a linear hierarchy.

---

## 3. Entry Model: "Everything is an Entry"

### Can Marvin Support These Without Code Changes?

| Content Type | Supported? | Notes |
|-------------|-----------|--------|
| **Page** | ✅ Yes | entry_type=page, content_markdown |
| **Project** | ✅ Yes | entry_type=project, metadata for project-specific fields |
| **Bench Note** | ✅ Yes | entry_type=bench-note, status=draft/published |
| **Product** | ✅ Yes | entry_type=product, resources for materials |
| **Guide** | ✅ Yes | entry_type=guide, collections for series |
| **Article** | ✅ Yes | entry_type=article, published_at for chronology |
| **Workflow** | ⚠️ Partial | entry_type=workflow, but no step ordering |
| **Recipe** | ✅ Yes | entry_type=recipe (Mealie legacy support) |

**Verdict**: ✅ **Yes, the Entry model is sufficiently generic.**

**Why it works**:
1. `entry_type_id` allows infinite content types
2. `metadata_json` provides type-specific fields
3. `content_markdown` is universal
4. Status workflow applies to all types
5. Collections group any entry type

**Limitation**: **Sequential content** (workflows, tutorials, recipes with steps) has no built-in ordering mechanism.

**Future Enhancement**: Consider adding `entry_steps` junction table:
```sql
entry_steps:
  - entry_id
  - step_number
  - step_type (text|image|code|embed)
  - content
  - metadata
```

But this can wait. Metadata JSON can encode steps for now.

---

## 4. Metadata Strategy

### Current Approach
```python
# Entries
metadata_json: dict | None  # Astro frontmatter + custom fields

# Example
{
  "author": "Jared",
  "tags": ["linen", "sewing"],
  "seo_title": "Custom SEO Title",
  "featured_image": "/assets/hero.jpg",
  "astro": {
    "layout": "project.astro",
    "draft": false
  },
  "custom_fields": {
    "difficulty": "intermediate",
    "time_estimate": "2 hours"
  }
}
```

### ✅ What's Right

**Flexibility**: Arbitrary fields without schema changes  
**Astro Compatibility**: Direct frontmatter mapping  
**Type-Specific Data**: Each entry type can have unique fields  

### ⚠️ What's Questionable

**Should these move to first-class columns?**

| Field | Current | Recommendation |
|-------|---------|----------------|
| `author` | metadata | **Move to `created_by` FK** |
| `tags` | metadata | Consider `tags` table (M:M) |
| `featured_image` | metadata | Use `entry_assets` with role="featured" |
| `seo_title` | metadata | Stay in metadata (override) |
| `difficulty` | metadata | Stay in metadata (type-specific) |

**Critical Issue**: **Author tracking**

Entries have NO `created_by` field. This is a serious oversight.

```python
# Current
entries:
  created_at: datetime  # When, but not WHO
  
# Should be
entries:
  created_by: UUID4  # FK to users.id
  created_at: datetime
```

**Recommendation**:
1. Add `created_by` to entries NOW (Phase 7)
2. Keep `metadata_json` for everything else
3. Add `tags` table in Phase 8 (after publishing API)
4. Featured images should use `entry_assets.role="hero"`

---

## 5. Collections Architecture

### Current Implementation

```python
# One Entry → Many Collections ✅
entry_collections:
  entry_id → entries
  collection_id → collections
  position: int
```

**Verdict**: ✅ **Perfect.**

### Is the Join Table Correct?

**Yes.** The junction table supports:
- Many-to-many without duplication
- Position-based ordering within each collection
- Same entry can appear in multiple collections at different positions

**Example**:
```
Entry "Linen Napkins" (#42):
  - Collection "Featured" (position 1)
  - Collection "Table Linens" (position 5)
  - Collection "Gift Ideas" (position 3)
```

Each appearance is independent. ✅

### Smart Collections

**Current State**:
- ✅ `is_smart` field exists
- ✅ `smart_rules` JSON field exists
- ❌ Rules engine NOT implemented

**Recommendation**: This is correct staging.

Manual collections are sufficient for MVP. Smart collections are a Phase 8 enhancement. The schema supports it when ready.

---

## 6. Resources Model

### Does It Correctly Model Reusable Objects?

**Test Cases**:

| Resource Type | Works? | Notes |
|--------------|--------|--------|
| Fabric | ✅ Yes | resource_type="fabric", metadata={color, weight, supplier} |
| Supplier | ⚠️ Partial | Works but needs `url`, `contact_email` |
| Tool | ✅ Yes | resource_type="tool" |
| Book | ⚠️ Partial | Needs `isbn`, `url` |
| GitHub Repo | ❌ No | Needs `url` (critical), `external_id` |
| API | ❌ No | Needs `url` (critical), `api_key_location` |
| Person | ⚠️ Partial | Should this be a resource or link to users table? |

**Verdict**: ⚠️ **Works for physical objects, falls short for digital/external resources.**

### Missing Fields

```python
# Should add
resources:
  url: str | None  # External link (GitHub, supplier site, API docs)
  external_id: str | None  # Supplier SKU, ISBN, repo path
  supplier_name: str | None  # Quick reference
```

**Recommendation**: Add these 3 fields in Phase 7 before Resources become critical.

### Would This Scale?

**Concerns**:
1. **No resource categories**: `resource_type` is free-text, no normalization
2. **No resource relationships**: Can't say "Resource A is alternative to Resource B"
3. **No resource versioning**: Fabric dye lots change

**For MVP**: ✅ Sufficient  
**For scale**: ⚠️ Will need resource categories table and version tracking

---

## 7. Assets vs Resources

### Are They Cleanly Separated?

**Yes.** ✅

**Resource**: Reusable object (fabric, tool, supplier)  
**Asset**: Uploaded file (image, PDF, video)

**Clear distinction**:
- Resources have no `file_path`
- Assets are **always** files
- Resources can be referenced by multiple entries
- Assets can (currently) belong to multiple entries

### Could One Asset Belong to Multiple Entries?

**Current**: ✅ **Yes**, via `entry_assets` junction table

**Should it?** ✅ **Yes**.

**Use case**: Hero image for a product line
```
Asset "Product Hero" (#123):
  - Entry "Cotton Tote" (role=hero)
  - Entry "Linen Tote" (role=hero)
  - Entry "Product Line Overview" (role=featured)
```

This is correct. Don't constrain to 1:1.

### Architecture Decision ✅

Assets **should** support M:M with entries. Current implementation is correct.

---

## 8. Future Compatibility Check

### Can Current Schema Support Future Features?

| Feature | Supported? | How | Gaps |
|---------|-----------|-----|------|
| **Publishing API** | ✅ Yes | `status=published`, API clients table exists | None |
| **Astro** | ✅ Yes | `metadata_json` maps to frontmatter | None |
| **AI Intake** | ✅ Yes | Create entries via API, metadata for AI context | Add `source` field |
| **Voice Notes** | ⚠️ Partial | Store as asset, transcribe to content_markdown | Need audio processing |
| **Image Analysis** | ✅ Yes | AI-generated alt_text, metadata extraction | None |
| **Templates** | ⚠️ Partial | Entry type can be "template", but no inheritance | Need template engine |
| **Smart Collections** | ✅ Yes | Schema exists, engine deferred | Build rules engine |
| **Knowledge Graph** | ⚠️ No | No entity relationships, no triple store | Major addition |
| **Version History** | ❌ No | No version tracking fields | Need `entry_versions` table |
| **API Clients** | ✅ Yes | Already implemented | None |
| **Custom Fields** | ✅ Yes | `metadata_json` supports arbitrary fields | UI for field definitions |

### Critical Gaps

**1. Version History**

Entries have no version tracking. Every edit overwrites.

**Future requirement**:
```sql
entry_versions:
  id, entry_id, version_number
  title, content_markdown, metadata_json (snapshot)
  created_by, created_at
  change_summary
```

**Impact**: Medium. Workaround = external version control for markdown files.

**2. Knowledge Graph / Relationships**

No way to model:
- "Entry A references Entry B"
- "Entry A is a prerequisite for Entry B"
- "Entry A is a variation of Entry B"

**Future requirement**:
```sql
entry_relationships:
  id, from_entry_id, to_entry_id
  relationship_type (prerequisite|variation|reference|related)
  metadata
```

**Impact**: High for advanced use cases (learning paths, dependencies).

**3. Entry Templates**

No template inheritance system.

**Current workaround**: Create template entries, clone via API.

**Future requirement**: Template engine with field inheritance and overrides.

**Impact**: Low. Current approach works for MVP.

---

## 9. Mealie Comparison

### What Concepts Have We Generalized?

| Mealie | Marvin | Generalization |
|--------|--------|----------------|
| Recipe | Entry | ✅ Any content type |
| Cookbook | Collection | ✅ Any grouping |
| Ingredient | Resource | ✅ Any reusable object |
| Recipe Image | Asset | ✅ Any file type |
| Recipe Category | Entry Type | ✅ User-defined schemas |
| Recipe Status | Entry Status | ✅ Same workflow |

### What Concepts Remain Recipe-Specific?

**None in the data model.** ✅

The only recipe-specific code would be:
- UI components (recipe card display)
- Seeded entry types (if we include a "recipe" type)
- Import scripts (from Mealie/other recipe managers)

But the **schema** is fully generic.

### What Did We Improve?

| Improvement | Impact |
|-------------|--------|
| **Workspace scoping** | ✅ Multi-tenant from day 1 |
| **Publishing API** | ✅ Read-only external access |
| **API Clients** | ✅ Proper security model |
| **Entry Types** | ✅ User-defined content schemas |
| **Metadata JSON** | ✅ Extensible without migrations |
| **Smart collections** | ✅ Schema supports rule-based (engine pending) |
| **Resources** | ✅ Broader than ingredients |
| **Asset metadata** | ✅ Width/height/alt-text/focal point |

**Biggest Win**: **Marvin is no longer a recipe manager.** It's a content operating system that *could* manage recipes.

---

## 10. Technical Debt

### Critical Issues (Fix Before Scaling)

#### 🔴 1. Inconsistent Metadata Naming

**Problem**:
```python
Entries.metadata_json  # ← Database column name
Resources.metadata_    # ← Python attr, DB is "metadata"
Assets.metadata_       # ← Python attr, DB is "metadata"
```

**Impact**: Confusing for developers, error-prone queries

**Fix**:
```sql
ALTER TABLE entries RENAME COLUMN metadata_json TO metadata;
```

Update schemas to use `metadata_` everywhere.

**Effort**: 30 minutes  
**Priority**: HIGH

#### 🔴 2. Missing `created_by` on Entries

**Problem**: No author tracking on entries

**Impact**: Can't filter "my entries", no audit trail, no attribution

**Fix**:
```sql
ALTER TABLE entries ADD COLUMN created_by UUID REFERENCES users(id) ON DELETE SET NULL;
```

Backfill with first user in workspace or NULL.

**Effort**: 1 hour  
**Priority**: CRITICAL

#### 🔴 3. EntryResources Missing Relationships

**Problem**: EntryResources model has no back-references

```python
# EntryAssets has:
entry: Mapped["Entries"]
asset: Mapped["Assets"]

# EntryResources missing:
# entry: Mapped["Entries"]
# resource: Mapped["Resources"]
```

**Impact**: Inconsistent, harder to query junction table

**Fix**: Add relationships like EntryAssets has

**Effort**: 15 minutes  
**Priority**: HIGH

#### 🟡 4. Collections Missing Display Fields

**Problem**: Collections have no `sort_order`, `icon`, `color`

**Impact**: Can't order collections in UI, no visual identity

**Fix**:
```sql
ALTER TABLE collections ADD COLUMN sort_order INT DEFAULT 0;
ALTER TABLE collections ADD COLUMN icon VARCHAR;
ALTER TABLE collections ADD COLUMN color VARCHAR;
```

**Effort**: 30 minutes  
**Priority**: MEDIUM

#### 🟡 5. EntrySummary Inheritance Inconsistency

**Problem**: `EntrySummary` inherits from `EntryRead` but `CollectionSummary` doesn't inherit from `CollectionRead`

**Impact**: Inconsistent schema patterns

**Fix**: Pick one approach:
- Option A: All summaries inherit from Read (add `pass`)
- Option B: All summaries duplicate fields

Recommendation: Option A (less code).

**Effort**: 10 minutes  
**Priority**: LOW

#### 🟡 6. Resources Need URL Fields

**Problem**: Resources for APIs, repos, suppliers have nowhere to store URLs

**Impact**: Can't link to external resources

**Fix**:
```sql
ALTER TABLE resources ADD COLUMN url VARCHAR;
ALTER TABLE resources ADD COLUMN external_id VARCHAR;
```

**Effort**: 20 minutes  
**Priority**: MEDIUM

### Tech Debt Summary

| Issue | Priority | Effort | Phase |
|-------|----------|--------|-------|
| Metadata naming | 🔴 HIGH | 30m | Phase 7 |
| Entries.created_by | 🔴 CRITICAL | 1h | Phase 7 |
| EntryResources relationships | 🔴 HIGH | 15m | Phase 7 |
| Collections display fields | 🟡 MEDIUM | 30m | Phase 8 |
| Schema inheritance | 🟡 LOW | 10m | Phase 8 |
| Resources URL fields | 🟡 MEDIUM | 20m | Phase 7 |

**Total debt**: ~2.5 hours to clear critical path.

---

## 11. Recommended Roadmap

### Ranked by Architectural Value

#### Tier 1: Foundation (Do First)
1. **Fix Technical Debt** (2.5 hours)
   - Why: Prevents compounding issues
   - Impact: Code quality, maintainability

2. **Publishing API** (Already started)
   - Why: Core value proposition
   - Impact: Enables Astro integration

3. **API Client Management** (Already done)
   - Why: Security boundary for publishing
   - Impact: Multi-site support

#### Tier 2: Core Features
4. **Entry Authoring Experience**
   - Why: Users need to create content
   - What: Markdown editor, preview, media uploads
   - Impact: Usability

5. **Asset Upload & Management**
   - Why: Phase 6 only has metadata
   - What: Multipart upload, file storage, serving
   - Impact: Completeness

6. **Collections Management UI**
   - Why: Schema exists, UI doesn't
   - What: Drag-drop reordering, add/remove entries
   - Impact: Content organization

#### Tier 3: Advanced Features
7. **Smart Collections Engine**
   - Why: Makes collections actually powerful
   - What: Rules engine, query builder UI
   - Impact: Automation, reduced manual work
   - Complexity: Low (100-200 LOC)

8. **Relationships**
   - Why: Content is interconnected
   - What: Entry-to-entry links, prerequisites, variations
   - Impact: Knowledge graph foundation

9. **Custom Fields UI**
   - Why: Metadata JSON works, but UI needed
   - What: Visual field editor per entry type
   - Impact: User experience

#### Tier 4: Power Features
10. **Version History**
    - Why: Audit trail, rollback capability
    - What: Entry versions table, diff UI
    - Impact: Trust, safety

11. **Templates**
    - Why: Reduce repetitive work
    - What: Template entries, inheritance system
    - Impact: Efficiency

12. **Knowledge Graph**
    - Why: Advanced content relationships
    - What: Triple store, graph queries, visualization
    - Impact: Discovery, recommendations

### Phase Recommendation

**Phase 7**: 
- Fix all technical debt ← MUST DO
- Complete asset upload/serving
- Add `created_by` to entries

**Phase 8**:
- Smart collections engine
- Collections UI improvements
- Custom fields UI

**Phase 9**:
- Entry relationships
- Version history
- Templates

**Phase 10+**:
- Knowledge graph
- AI intake
- Advanced publishing features

---

## 12. Critical Design Decisions

### ✅ Decisions That Are Correct

1. **Workspace = Groups**: Don't rename the table yet. Correct.
2. **Entry as Universal Content**: Perfect generalization.
3. **Junction Tables**: All M:M relationships modeled correctly.
4. **Metadata JSON**: Right balance of flexibility vs structure.
5. **API Clients Separate from Users**: Critical security boundary.
6. **Publishing Status Filter**: Only `status=published` via API.
7. **Slug Uniqueness per Workspace**: UNIQUE(group_id, slug) everywhere.

### ⚠️ Decisions to Revisit

1. **No Entry Author**: Add `created_by` NOW.
2. **Metadata Naming**: Standardize on `metadata` column.
3. **No Version History**: Plan for this in schema (future).
4. **No Entry Relationships**: Will limit knowledge graph (future).
5. **Collections Lack Visual Identity**: Add icon/color/sort_order.

### ❌ Decisions That Need Immediate Change

**None.** All issues are refinements, not fundamental flaws.

---

## Final Verdict

### Strengths
✅ Clean, consistent architecture  
✅ Generic content model  
✅ Proper workspace isolation  
✅ Good publishing API foundation  
✅ Extensible via metadata JSON  
✅ Well-structured repositories and controllers  

### Weaknesses
⚠️ Missing author tracking (critical)  
⚠️ Inconsistent metadata naming  
⚠️ Collections missing display fields  
⚠️ Resources limited for digital content  
⚠️ No version history plan  

### Recommendation

**Ship Phase 7 with tech debt fixes, then proceed with confidence.**

The foundation is solid. The generalization from Mealie to Marvin is successful. Fix the 6 technical debt items (~2.5 hours), then build features.

**Grade**: B+ → A- (after tech debt cleared)

---

## Appendix: Diff of Recommended Changes

```sql
-- PHASE 7 MIGRATION: Fix Technical Debt

-- 1. Standardize metadata naming
ALTER TABLE entries RENAME COLUMN metadata_json TO metadata;

-- 2. Add author tracking
ALTER TABLE entries ADD COLUMN created_by UUID REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX idx_entries_created_by ON entries(created_by);

-- 3. Collections visual identity
ALTER TABLE collections ADD COLUMN sort_order INTEGER DEFAULT 0 NOT NULL;
ALTER TABLE collections ADD COLUMN icon VARCHAR(255);
ALTER TABLE collections ADD COLUMN color VARCHAR(50);

-- 4. Resources external links
ALTER TABLE resources ADD COLUMN url VARCHAR(2048);
ALTER TABLE resources ADD COLUMN external_id VARCHAR(255);

-- 5. Entry resources position
ALTER TABLE entry_resources ADD COLUMN position INTEGER DEFAULT 0 NOT NULL;
CREATE INDEX idx_entry_resources_position ON entry_resources(entry_id, position);
```

```python
# EntryResources model - add relationships
class EntryResources(SqlAlchemyBase):
    # ... existing fields ...
    
    # Add these:
    entry: Mapped["Entries"] = orm.relationship(
        "Entries",
        foreign_keys=[entry_id],
        overlaps="entries,resources",
    )
    resource: Mapped["Resources"] = orm.relationship(
        "Resources",
        foreign_keys=[resource_id],
        overlaps="entries,resources",
    )
```

```python
# CollectionSummary - inherit from Read
class CollectionSummary(CollectionRead):
    """Summary schema for a collection (inherits from Read)."""
    pass
```

**End of Review**
