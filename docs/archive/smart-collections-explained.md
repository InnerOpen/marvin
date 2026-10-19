# Smart Collections Explained

## The Concept

Collections in Marvin come in two flavors:

### 1. Manual Collections (What we have now)
You explicitly add/remove entries to the collection.

**Example:** "Featured Products"
- You manually add `linen-napkins` entry
- You manually add `canvas-tote` entry  
- You manually remove `discontinued-item` entry

**How it works:**
- Admin clicks "Add to Collection" on an entry
- Creates a record in `entry_collections` junction table
- Collection shows exactly what you put in it

### 2. Smart Collections (Not yet implemented)
The collection automatically populates based on rules you define.

**Example:** "Recently Published"
- Rule: Show entries where `status = published`
- Rule: Sort by `published_at` descending
- Rule: Limit to 10 most recent

**How it works:**
- You define rules in `smart_rules` JSON
- Collection dynamically queries entries matching the rules
- No manual entry management needed
- Content appears/disappears automatically as it matches rules

## Real-World Examples

### Manual Collection Use Cases
- **"Featured"** - Hand-picked best content (editorial control)
- **"Summer 2026"** - Seasonal collection you curate
- **"Gift Guide"** - Specific items you want to showcase together
- **"Getting Started"** - Carefully ordered tutorial sequence

### Smart Collection Use Cases
- **"Recent Articles"** - Last 10 published articles (auto-updates)
- **"All Projects"** - Every entry where `entry_type = project`
- **"Draft Queue"** - Entries with `status = draft` (work in progress view)
- **"Linen Products"** - Entries where metadata contains `material: linen`
- **"This Month"** - Entries published in current month
- **"Popular"** - Entries sorted by view count (once we track that)

## How Smart Rules Work

### The Schema (What exists now)

```python
class Collections:
    is_smart: bool              # True if collection uses rules
    smart_rules: dict | None    # JSON defining the query
```

### Example Smart Rules JSON

**Recently Published:**
```json
{
  "filters": {
    "status": "published"
  },
  "sort": {
    "field": "published_at",
    "direction": "desc"
  },
  "limit": 10
}
```

**All Articles:**
```json
{
  "filters": {
    "entry_type": "article"
  },
  "sort": {
    "field": "title",
    "direction": "asc"
  }
}
```

**Linen Products:**
```json
{
  "filters": {
    "entry_type": "product",
    "metadata.material": "linen",
    "status": "published"
  },
  "sort": {
    "field": "created_at",
    "direction": "desc"
  }
}
```

**This Month's Posts:**
```json
{
  "filters": {
    "status": "published",
    "published_at": {
      "gte": "2026-07-01",
      "lt": "2026-08-01"
    }
  },
  "sort": {
    "field": "published_at",
    "direction": "desc"
  }
}
```

## The Missing Piece: Rules Engine

**Status:** Field exists, engine doesn't.

Currently you can:
- ✅ Create a collection with `is_smart: true`
- ✅ Store arbitrary JSON in `smart_rules`
- ❌ Collection won't actually populate based on rules

To make it work, we need:

### 1. Rules Engine Service

**File:** `src/marvin/services/collections/rules_engine.py`

```python
class SmartCollectionRulesEngine:
    """
    Evaluates smart collection rules and returns matching entries.
    """
    
    def evaluate(
        self,
        rules: dict,
        group_id: UUID4,
        session: Session
    ) -> list[Entry]:
        """
        Execute smart collection rules as a database query.
        
        Args:
            rules: The smart_rules JSON from collection
            group_id: Workspace to query within
            session: Database session
            
        Returns:
            List of entries matching the rules
        """
        query = session.query(Entries).filter(Entries.group_id == group_id)
        
        # Apply filters
        if "filters" in rules:
            query = self._apply_filters(query, rules["filters"])
        
        # Apply sorting
        if "sort" in rules:
            query = self._apply_sort(query, rules["sort"])
        
        # Apply limit
        if "limit" in rules:
            query = query.limit(rules["limit"])
        
        return query.all()
    
    def _apply_filters(self, query, filters: dict):
        """Apply filter conditions to query."""
        for field, value in filters.items():
            if field == "status":
                query = query.filter(Entries.status == value)
            elif field == "entry_type":
                query = query.join(EntryTypes).filter(EntryTypes.slug == value)
            elif field.startswith("metadata."):
                # JSON field query
                json_path = field.split(".", 1)[1]
                query = query.filter(Entries.metadata[json_path].astext == str(value))
            elif isinstance(value, dict):
                # Range query (gte, lt, etc)
                if "gte" in value:
                    query = query.filter(getattr(Entries, field) >= value["gte"])
                if "lt" in value:
                    query = query.filter(getattr(Entries, field) < value["lt"])
        return query
    
    def _apply_sort(self, query, sort_config: dict):
        """Apply sorting to query."""
        field = sort_config.get("field", "created_at")
        direction = sort_config.get("direction", "desc")
        
        column = getattr(Entries, field)
        if direction == "desc":
            query = query.order_by(column.desc())
        else:
            query = query.order_by(column.asc())
        
        return query
```

### 2. Modify Collection Queries

When fetching a collection's entries:

**Current (manual only):**
```python
def get_collection_entries(collection_id):
    # Query junction table
    return session.query(Entries).join(
        EntryCollections
    ).filter(
        EntryCollections.collection_id == collection_id
    ).all()
```

**With smart collection support:**
```python
def get_collection_entries(collection_id):
    collection = get_collection(collection_id)
    
    if collection.is_smart and collection.smart_rules:
        # Use rules engine
        engine = SmartCollectionRulesEngine()
        return engine.evaluate(
            rules=collection.smart_rules,
            group_id=collection.group_id,
            session=session
        )
    else:
        # Use manual junction table
        return session.query(Entries).join(
            EntryCollections
        ).filter(
            EntryCollections.collection_id == collection_id
        ).all()
```

### 3. Hybrid Collections (Both Manual + Smart)

You could have a collection that:
- Uses smart rules to auto-populate
- **Plus** manually pinned entries that always show first

**Example:** "Featured" collection
- Smart rule: Recent high-quality entries
- Manual pins: Editor's top 3 picks (always at top)

## UI Implications

### Collection Create/Edit Form

**Manual Collection:**
```
Name: Featured Products
Slug: featured
Type: ○ Smart  ● Manual

[No rules to configure]
```

**Smart Collection:**
```
Name: Recent Articles
Slug: recent-articles
Type: ● Smart  ○ Manual

Rules:
  Filter by:
    - Entry Type: Article
    - Status: Published
  
  Sort by: Published Date (newest first)
  
  Limit: 10 entries
  
[Preview: Shows current entries that match]
```

### Entry Management View

**Manual Collection:**
- Shows "Add to Collection" button on entries
- Shows drag-to-reorder in collection view
- Can remove entries manually

**Smart Collection:**
- No "Add to Collection" button (auto-populated)
- Shows read-only list of matching entries
- Shows "Edit Rules" to change criteria
- Preview updates live as you edit rules

## Implementation Phases

### Phase 1: Manual Collections (✅ Done)
- Create/update/delete collections
- Add/remove entries via junction table
- Position-based ordering

### Phase 2: Smart Rules Engine (Not started)
- Define rules JSON schema
- Build rules engine service
- Modify get_collection_entries to use engine
- Add rules validation

### Phase 3: Rules UI (Not started)
- Rule builder interface
- Live preview of matching entries
- Validation and error messages
- Rule templates (recent, popular, by-type)

### Phase 4: Hybrid Collections (Future)
- Combine smart rules + manual pins
- Priority/position for pinned items
- Rules determine rest of collection

## Rules Schema Design

### Proposed Standard Format

```typescript
{
  "filters": {
    // Direct field matches
    "status": "published",
    "entry_type": "article",
    
    // Metadata queries
    "metadata.color": "blue",
    "metadata.price": { "lte": 50 },
    
    // Date ranges
    "published_at": {
      "gte": "2026-01-01",
      "lt": "2026-12-31"
    },
    
    // Text search
    "title": { "contains": "linen" }
  },
  
  "sort": {
    "field": "published_at",
    "direction": "desc"  // or "asc"
  },
  
  "limit": 10,
  
  "offset": 0  // For pagination
}
```

### Operators Supported

- **Equality:** `"status": "published"`
- **Range:** `"price": { "gte": 10, "lte": 100 }`
- **Contains:** `"title": { "contains": "linen" }`
- **In:** `"status": { "in": ["draft", "review"] }`
- **Exists:** `"metadata.color": { "exists": true }`
- **Date relative:** `"published_at": { "days_ago": 7 }`

## Why Smart Collections Matter

### For Content Managers
- **"Recent Articles"** updates automatically
- **"Draft Queue"** shows what needs work
- **"This Month"** collection builds itself
- Less manual maintenance

### For Developers (Astro sites)
- Single API call gets dynamic content
- No client-side filtering needed
- Collections stay fresh without deploys
- Can build "Latest Posts" widgets easily

### For Marvin Platform
- More powerful than static lists
- Reduces manual work
- Enables dynamic homepages
- Makes collections actually useful

## Current Status

| Feature | Status | Notes |
|---------|--------|-------|
| Manual collections | ✅ Complete | Add/remove entries, position ordering |
| `is_smart` field | ✅ Exists | Database column present |
| `smart_rules` field | ✅ Exists | JSON column present |
| Rules engine | ❌ Not implemented | No query generation |
| Rules validation | ❌ Not implemented | JSON can be anything |
| UI for rules | ❌ Not implemented | No way to build rules |
| Hybrid collections | ❌ Not planned | Smart + manual |

## Decision Point

**Do we need smart collections now?**

**Arguments for waiting:**
- Manual collections work fine for MVP
- Publishing API is more critical
- Can add rules engine later without breaking changes
- Schema already supports it

**Arguments for implementing:**
- Makes collections much more useful
- "Recent Articles" is a common use case
- Demo looks better with auto-updating collections
- Rules engine isn't that complex (100-200 lines)

**Recommendation:** 
Wait until after Publishing API. Manual collections are sufficient for Phase 3. Smart collections are a nice-to-have enhancement for Phase 5 or 6.

## Quick Implementation (If Desired)

If you want a minimal smart collections MVP:

**1 hour work:**
- Write rules engine service (50 lines)
- Support 3 filters: status, entry_type, published_at
- Support 1 sort: any field, asc/desc
- Support limit
- Modify get_collection_entries to check `is_smart`

**Result:**
- Can create "Recent Articles" collection
- Can create "All Projects" collection
- Can create "Recently Published" collection
- No UI needed (hand-write JSON for now)

Let me know if you want me to implement this quick version!
