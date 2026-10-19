Entry Type Schema System Architecture Plan                                                                   │
│                                                                                                              │
│ Context                                                                                                      │
│                                                                                                              │
│ Marvin CMS currently assumes all Entries are Markdown-based content with a fixed structure (content_markdown + metadata_json). This limits its ability to model diverse content types like Projects, Navigation Items, FAQs, Products, Events, Patterns, Materials, Suppliers, etc.                                                 │
│                                                                                                              │
│ This plan transforms Entry Types from simple categorizations into schema-driven content models that define:  │
│ - What fields exist                                                                                          │
│ - How they are edited                                                                                        │
│ - Validation rules                                                                                           │
│ - Default values                                                                                             │
│ - (Future) UI layout                                                                                         │
│                                                                                                              │
│ The goal is to evolve Marvin from a Markdown CMS into a schema-driven content platform where entirely new content models can be created without backend code changes.                                                  │
│                                                                                                              │
│ Migration Strategy: Complete replacement - remove content_markdown, replace with schema-driven data_json. This is a breaking change requiring coordinated backend + SDK updates.                                       │
│                                                                                                              │
│ ---                                                                                                          │
│ Current State                                                                                                │
│                                                                                                              │
│ Database Schema                                                                                              │
│                                                                                                              │
│ Entry Types Table:                                                                                           │
│ id, group_id, name, slug, icon, color, description, sort_order, is_system                                    │
│                                                                                                              │
│ Entries Table:                                                                                               │
│ id, group_id, entry_type_id, title, slug, summary, description,                                              │
│ content_markdown (TEXT),  ← REMOVING                                                                         │
│ status, published_at, metadata_json (JSON),                                                                  │
│ created_by                                                                      │
│                                                                                 │
│ Key Constraints:                                                                                             │
│ - content_markdown is optional TEXT colu                                        │
│ - metadata_json is unstructured JSON with no validation (will remain for custom metadata)                    │
│ - Entry Type has CASCADE delete preventi                                        │
│ - Slug immutability for published entries (SEO protection)                                                   │
│                                                                                 │
│ Current Assumptions (Breaking)                                                                               │
│                                                                                 │
│ - ❌ Every Entry has optional Markdown content (content_markdown) - REMOVING                                 │
│ - ✅ Custom fields go into unstructured non-schema metadata)                    │
│ - ❌ Publishing API exposes content_markdown as-is - CHANGING to dataJson                                    │
│ - ❌ SDK assumes contentMarkdown properton                                      │
│ - ❌ Frontend hardcodes knowledge about entry structure - CHANGING to schema-driven                          │
│                                                                                 │
│ ---                                                                                                          │
│ Vision: Schema-Driven Content Models                                            │
│                                                                                                              │
│ Entry Type as Schema Definition                                                 │
│                                                                                                              │
│ Entry Types define the editing experienc                                        │
│                                                                                                              │
│ {                                                                               │
│   "fields": [                                                                                                │
│     {                                                                           │
│       "key": "body",                                                                                         │
│       "label": "Body",                                                          │
│       "type": "markdown",                                                                                    │
│       "required": true,                                                         │
│       "placeholder": "Enter content...",                                                                     │
│       "helpText": "Main content area"                                           │
│     },                                                                                                       │
│     {                                                                           │
│       "key": "heroImage",                                                                                    │
│       "label": "Hero Image",                                                    │
│       "type": "asset",                                                                                       │
│       "required": false                                                         │
│     },                                                                                                       │
│     {                                                                           │
│       "key": "difficulty",                                                                                   │
│       "label": "Difficulty",                                                    │
│       "type": "select",                                                                                      │
│       "options": ["beginner", "intermedi                                        │
│       "defaultValue": "beginner"                                                                             │
│     }                                                                           │
│   ]                                                                                                          │
│ }                                                                               │
│                                                                                                              │
│ Field Types (Supported)                                                         │
│                                                                                                              │
│ Phase 1 (Initial Implementation):                                               │
│ - text - Single-line text input                                                                              │
│ - textarea - Multi-line plain text                                              │
│ - markdown - Markdown editor                                                                                 │
│ - number - Numeric input                                                        │
│ - boolean - Toggle/checkbox                                                                                  │
│ - select - Dropdown selection                                                   │
│ - date - Date picker                                                                                         │
│ - datetime - Date + time picker                                                 │
│ - asset - Single asset reference                                                                             │
│ - asset-list - Multiple asset references                                        │
│ - resource - Single resource reference                                                                       │
│ - resource-list - Multiple resource refe                                        │
│ - json - Free-form JSON object                                                                               │
│                                                                                 │
│ Phase 2 (Future):                                                                                            │
│ - richtext - Rich text editor                                                   │
│ - code - Code editor with syntax highlighting                                                                │
│ - color - Color picker                                                          │
│ - url, email, phone - Specialized text inputs                                                                │
│ - entry, entry-list - Entry references                                          │
│ - collection, collection-list - Collection references                                                        │
│ - tags - Tag input                                                              │
│ - slug, generated-slug - Slug fields                                                                         │
│ - repeater - Repeatable field groups                                            │
│ - object - Nested object structure                                                                           │
│                                                                                 │
│ Field Validation (Extensible)                                                                                │
│                                                                                 │
│ {                                                                                                            │
│   "key": "price",                                                               │
│   "type": "number",                                                                                          │
│   "required": true,                                                             │
│   "min": 0,                                                                                                  │
│   "max": 10000,                                                                 │
│   "helpText": "Product price in USD"                                                                         │
│ }                                                                               │
│                                                                                                              │
│ Supported Validation (Phase 1):                                                 │
│ - required - Field is mandatory                                                                              │
│ - defaultValue - Default when not provid                                        │
│ - placeholder - Input placeholder text                                                                       │
│ - helpText - Help text for editors                                              │
│ - min, max - Numeric/string length constraints                                                               │
│ - pattern - Regex validation (for text f                                        │
│ - options - Valid values (for select fields)                                                                 │
│ - readOnly - Non-editable field                                                 │
│                                                                                                              │
│ ---                                                                             │
│ Migration Strategy (Breaking Change)                                                                         │
│                                                                                 │
│ Phase 1: Database Schema Changes                                                                             │
│                                                                                 │
│ Add new column to entry_types table:                                                                         │
│ ALTER TABLE entry_types                                                         │
│   ADD COLUMN schema_json JSONB;                                                                              │
│                                                                                 │
│ Replace content column in entries table:                                                                     │
│ -- Add new column                                                               │
│ ALTER TABLE entries                                                                                          │
│   ADD COLUMN data_json JSONB;                                                   │
│                                                                                                              │
│ -- Migrate existing data (see migration                                         │
│ -- DROP old column (after migration completes)                                                               │
│ ALTER TABLE entries                                                             │
│   DROP COLUMN content_markdown;                                                                              │
│                                                                                 │
│ Keep metadata_json:                                                                                          │
│ - metadata_json remains for custom, non-                                        │
│ - Use case: API keys, external IDs, CMS-specific config that isn't part of the content model                 │
│                                                                                 │
│ Phase 2: Data Migration (Before Column Drop)                                                                 │
│                                                                                 │
│ Migration script migrates all entries:                                                                       │
│                                                                                 │
│ def upgrade():                                                                                               │
│     # 1. Add schema_json to entry_types                                         │
│     op.add_column('entry_types', sa.Column('schema_json', JSONB(), nullable=True))                           │
│                                                                                 │
│     # 2. Add data_json to entries                                                                            │
│     op.add_column('entries', sa.Column('=True))                                 │
│                                                                                                              │
│     # 3. Create default schemas for syst                                        │
│     connection = op.get_bind()                                                                               │
│                                                                                 │
│     # Default schema for Page, Article, etc. - single markdown field                                         │
│     default_schema = {                                                          │
│         "fields": [                                                                                          │
│             {                                                                   │
│                 "key": "body",                                                                               │
│                 "label": "Content",                                             │
│                 "type": "markdown",                                                                          │
│                 "required": False                                               │
│             }                                                                                                │
│         ]                                                                       │
│     }                                                                                                        │
│                                                                                 │
│     # Update all entry types to have default schema                                                          │
│     connection.execute(                                                         │
│         sa.text("""                                                                                          │
│             UPDATE entry_types                                                  │
│             SET schema_json = :schema                                                                        │
│             WHERE schema_json IS NULL                                           │
│         """),                                                                                                │
│         {"schema": json.dumps(default_sc                                        │
│     )                                                                                                        │
│                                                                                 │
│     # 4. Migrate all entries: content_markdown → data_json                                                   │
│     connection.execute(                                                         │
│         sa.text("""                                                                                          │
│             UPDATE entries                                                      │
│             SET data_json = jsonb_build_object('body', content_markdown)                                     │
│             WHERE content_markdown IS NO                                        │
│         """)                                                                                                 │
│     )                                                                           │
│                                                                                                              │
│     # 5. Set empty object for entries wi                                        │
│     connection.execute(                                                                                      │
│         sa.text("""                                                             │
│             UPDATE entries                                                                                   │
│             SET data_json = '{}'::jsonb                                         │
│             WHERE data_json IS NULL                                                                          │
│         """)                                                                    │
│     )                                                                                                        │
│                                                                                 │
│     # 6. Make data_json NOT NULL                                                                             │
│     op.alter_column('entries', 'data_jso                                        │
│                                                                                                              │
│     # 7. Drop old column                                                        │
│     op.drop_column('entries', 'content_markdown')                                                            │
│                                                                                 │
│ def downgrade():                                                                                             │
│     # Reverse migration                                                         │
│     op.add_column('entries', sa.Column('content_markdown', sa.Text(), nullable=True))                        │
│                                                                                 │
│     connection = op.get_bind()                                                                               │
│     connection.execute(                                                         │
│         sa.text("""                                                                                          │
│             UPDATE entries                                                      │
│             SET content_markdown = data_json->>'body'                                                        │
│             WHERE data_json ? 'body'                                            │
│         """)                                                                                                 │
│     )                                                                           │
│                                                                                                              │
│     op.drop_column('entries', 'data_json                                        │
│     op.drop_column('entry_types', 'schema_json')                                                             │
│                                                                                 │
│ Phase 3: Default Schema Structure                                                                            │
│                                                                                 │
│ All existing entry types get this default schema:                                                            │
│ {                                                                               │
│   "fields": [                                                                                                │
│     {                                                                           │
│       "key": "body",                                                                                         │
│       "label": "Content",                                                       │
│       "type": "markdown",                                                                                    │
│       "required": false                                                         │
│     }                                                                                                        │
│   ]                                                                             │
│ }                                                                                                            │
│                                                                                 │
│ Entry data_json structure after migration:                                                                   │
│ {                                                                               │
│   "body": "# Original markdown content here"                                                                 │
│ }                                                                               │
│                                                                                                              │
│ New entry types can define custom schema                                        │
│ {                                                                                                            │
│   "fields": [                                                                   │
│     {"key": "question", "label": "Question", "type": "text", "required": true},                              │
│     {"key": "answer", "label": "Answer",d": true},                              │
│     {"key": "category", "label": "Category", "type": "select", "options": ["general", "technical"]}          │
│   ]                                                                             │
│ }                                                                                                            │
│                                                                                 │
│ ---                                                                                                          │
│ Database Changes                                                                │
│                                                                                                              │
│ Migration File: 2026-07-09-00.00.00_add_                                        │
│                                                                                                              │
│ def upgrade():                                                                  │
│     # Add schema_json to entry_types                                                                         │
│     op.add_column('entry_types',                                                │
│         sa.Column('schema_json', JSONB(), nullable=True))                                                    │
│                                                                                 │
│     # Add content_json to entries                                                                            │
│     op.add_column('entries',                                                    │
│         sa.Column('content_json', JSONB(), nullable=True))                                                   │
│                                                                                 │
│     # No data migration yet - purely additive                                                                │
│                                                                                 │
│ def downgrade():                                                                                             │
│     op.drop_column('entries', 'content_j                                        │
│     op.drop_column('entry_types', 'schema_json')                                                             │
│                                                                                 │
│ Updated Models                                                                                               │
│                                                                                 │
│ entry_types.py:                                                                                              │
│ class EntryTypes(SqlAlchemyBase, BaseMix                                        │
│     # ...existing fields...                                                                                  │
│     schema_json: Mapped[dict] = mapped_c                                        │
│         "schema_json", JSONB, nullable=False, default=dict, server_default="{}"                              │
│     )                                                                           │
│     # After migration, all entry types MUST have a schema                                                    │
│                                                                                 │
│ entries.py:                                                                                                  │
│ class Entries(SqlAlchemyBase, BaseMixins                                        │
│     # ...existing fields...                                                                                  │
│     # REMOVED: content_markdown                                                 │
│     data_json: Mapped[dict] = mapped_column(                                                                 │
│         "data_json", JSONB, nullable=Falult="{}"                                │
│     )                                                                                                        │
│     metadata_json: Mapped[dict | None] =                                        │
│         "metadata_json", sa.JSON, nullable=True                                                              │
│     )                                                                           │
│     # metadata_json remains for non-schema custom fields                                                     │
│                                                                                 │
│ ---                                                                                                          │
│ Schema Validation                                                               │
│                                                                                                              │
│ Pydantic Schema Models                                                          │
│                                                                                                              │
│ Pattern: Discriminated Union for Field T                                        │
│                                                                                                              │
│ Following Marvin's existing pattern frompe: Literal["cron", "interval",         │"once"]):                                                                                                    │
│                                                                                 │
│ # schemas/platform/entry_type_schema.py                                                                      │
│                                                                                 │
│ from typing import Literal, Union                                                                            │
│ from pydantic import Field, Discriminato                                        │
│                                                                                                              │
│ class BaseFieldSchema(_MarvinModel):                                            │
│     key: str = Field(..., description="Field identifier (used in content_json)")                             │
│     label: str = Field(..., description=                                        │
│     required: bool = Field(default=False)                                                                    │
│     defaultValue: Any | None = Field(defue")                                    │
│     placeholder: str | None = None                                                                           │
│     helpText: str | None = Field(default                                        │
│     readOnly: bool = Field(default=False, alias="read_only")                                                 │
│                                                                                 │
│ class TextFieldSchema(BaseFieldSchema):                                                                      │
│     type: Literal["text"]                                                       │
│     min: int | None = Field(default=None, description="Min length")                                          │
│     max: int | None = Field(default=None                                        │
│     pattern: str | None = Field(default=None, description="Regex pattern")                                   │
│                                                                                 │
│ class MarkdownFieldSchema(BaseFieldSchema):                                                                  │
│     type: Literal["markdown"]                                                   │
│                                                                                                              │
│ class NumberFieldSchema(BaseFieldSchema)                                        │
│     type: Literal["number"]                                                                                  │
│     min: float | None = None                                                    │
│     max: float | None = None                                                                                 │
│                                                                                 │
│ class SelectFieldSchema(BaseFieldSchema):                                                                    │
│     type: Literal["select"]                                                     │
│     options: list[str] = Field(..., description="Valid options")                                             │
│                                                                                 │
│ class AssetFieldSchema(BaseFieldSchema):                                                                     │
│     type: Literal["asset"]                                                      │
│                                                                                                              │
│ # ... more field types ...                                                      │
│                                                                                                              │
│ FieldSchema = Union[                                                            │
│     TextFieldSchema,                                                                                         │
│     MarkdownFieldSchema,                                                        │
│     NumberFieldSchema,                                                                                       │
│     SelectFieldSchema,                                                          │
│     AssetFieldSchema,                                                                                        │
│     # ... etc                                                                   │
│ ]                                                                                                            │
│                                                                                 │
│ class EntryTypeSchemaDefinition(_MarvinModel):                                                               │
│     """Entry type schema definition"""                                          │
│     fields: list[FieldSchema] = Field(default_factory=list)                                                  │
│                                                                                 │
│ Schema Validation in Entry Type CRUD                                                                         │
│                                                                                 │
│ entry_types.py repository:                                                                                   │
│ def create(self, data: EntryTypeCreate)                                         │
│     # Validate schema_json if provided                                                                       │
│     if hasattr(data, 'schema_json') and                                         │
│         # Validate against EntryTypeSchemaDefinition                                                         │
│         try:                                                                    │
│             EntryTypeSchemaDefinition.model_validate(data.schema_json)                                       │
│         except ValidationError as e:                                            │
│             raise HTTPException(                                                                             │
│                 status_code=400,                                                │
│                 detail=f"Invalid schema definition: {e}"                                                     │
│             )                                                                   │
│     # ... continue with creation                                                                             │
│                                                                                 │
│ Content Validation Against Schema                                                                            │
│                                                                                 │
│ entries.py repository:                                                                                       │
│ def _validate_content_against_schema(                                           │
│     self,                                                                                                    │
│     entry_type: EntryTypes,                                                     │
│     content_json: dict                                                                                       │
│ ) -> None:                                                                      │
│     """Validate entry content against entry type schema"""                                                   │
│     if not entry_type.schema_json:                                              │
│         return  # No schema = no validation (legacy behavior)                                                │
│                                                                                 │
│     schema_def = EntryTypeSchemaDefinition.model_validate(                                                   │
│         entry_type.schema_json                                                  │
│     )                                                                                                        │
│                                                                                 │
│     # Check required fields                                                                                  │
│     for field in schema_def.fields:                                             │
│         if field.required and field.key not in content_json:                                                 │
│             raise ValueError(f"Required g")                                     │
│                                                                                                              │
│         # Type-specific validation                                              │
│         if field.key in content_json:                                                                        │
│             value = content_json[field.k                                        │
│             # Validate based on field.type                                                                   │
│             # (number ranges, string len                                        │
│                                                                                                              │
│ ---                                                                             │
│ API Changes                                                                                                  │
│                                                                                 │
│ Entry Type Schemas                                                                                           │
│                                                                                 │
│ Update EntryTypeCreate and EntryTypeRead:                                                                    │
│ class EntryTypeCreate(_MarvinModel):                                            │
│     name: str                                                                                                │
│     slug: str | None = None                                                     │
│     icon: str | None = None                                                                                  │
│     color: str | None = None                                                    │
│     description: str | None = None                                                                           │
│     sort_order: int = 0                                                         │
│     is_system: bool = False                                                                                  │
│     schema_json: dict | None = Field(                                           │
│         default=None,                                                                                        │
│         validation_alias=AliasChoices("s                                        │
│     )                                                                                                        │
│                                                                                 │
│     @field_validator("schema_json")                                                                          │
│     @classmethod                                                                │
│     def validate_schema(cls, value: dict | None) -> dict | None:                                             │
│         if value is None:                                                       │
│             return None                                                                                      │
│         # Validate against EntryTypeSche                                        │
│         EntryTypeSchemaDefinition.model_validate(value)                                                      │
│         return value                                                            │
│                                                                                                              │
│ Entry Content                                                                   │
│                                                                                                              │
│ Update EntryCreate and EntryUpdate:                                             │
│ class EntryCreate(_MarvinModel):                                                                             │
│     entry_type_id: UUID4                                                        │
│     title: str                                                                                               │
│     slug: str | None = None                                                     │
│     summary: str | None = None                                                                               │
│     description: str | None = None                                              │
│                                                                                                              │
│     # Schema-driven content (REQUIRED af                                        │
│     data_json: dict = Field(                                                                                 │
│         default_factory=dict,                                                   │
│         validation_alias=AliasChoices("data_json", "dataJson", "data")                                       │
│     )                                                                           │
│                                                                                                              │
│     # Custom metadata (optional, for non                                        │
│     metadata_json: dict | None = Field(                                                                      │
│         default=None,                                                           │
│         validation_alias=AliasChoices("metadata_json", "metadataJson", "metadata")                           │
│     )                                                                           │
│                                                                                                              │
│     # ... rest of fields (status, collec_ids)                                   │
│                                                                                                              │
│     @model_validator(mode='after')                                              │
│     def validate_data_against_schema(self):                                                                  │
│         # Validate data_json against ent                                        │
│         # See ContentValidator section below                                                                 │
│         return self                                                             │
│                                                                                                              │
│ EntryRead response:                                                             │
│ class EntryRead(_MarvinModel):                                                                               │
│     id: UUID4                                                                   │
│     group_id: UUID4                                                                                          │
│     entry_type_id: UUID4                                                        │
│     title: str                                                                                               │
│     slug: str                                                                   │
│     summary: str | None = None                                                                               │
│     description: str | None = None                                              │
│                                                                                                              │
│     # Schema-driven content                                                     │
│     data_json: dict = Field(                                                                                 │
│         ...,                                                                    │
│         serialization_alias="dataJson"  # Expose as "dataJson" in JSON                                       │
│     )                                                                           │
│                                                                                                              │
│     # Custom metadata                                                           │
│     metadata_json: dict | None = Field(                                                                      │
│         default=None,                                                           │
│         serialization_alias="metadataJson"                                                                   │
│     )                                                                           │
│                                                                                                              │
│     status: str                                                                 │
│     published_at: datetime | None = None                                                                     │
│     created_by: UUID4 | None = None                                             │
│     created_at: datetime | None = None                                                                       │
│     update_at: datetime | None = None                                           │
│                                                                                                              │
│     # Relationships                                                             │
│     resources: list[ResourceSummary] = []                                                                    │
│     assets: list[EntryAssetRead] = []                                           │
│     collections: list[UUID4] = []                                                                            │
│     order: int | None = None                                                    │
│                                                                                                              │
│ Publishing API Changes (Breaking)                                               │
│                                                                                                              │
│ Update PublishedEntryRead:                                                      │
│ class PublishedEntryRead(_MarvinModel):                                                                      │
│     """                                                                         │
│     Schema for published entries in the publishing API.                                                      │
│                                                                                 │
│     BREAKING CHANGE: content_markdown removed, replaced with data/dataJson.                                  │
│     """                                                                         │
│                                                                                                              │
│     slug: str                                                                   │
│     """URL-friendly identifier for the entry."""                                                             │
│                                                                                 │
│     title: str                                                                                               │
│     """Entry title."""                                                          │
│                                                                                                              │
│     entry_type: str                                                             │
│     """Entry type slug (e.g., 'page', 'article', 'project')."""                                              │
│                                                                                 │
│     summary: str | None = None                                                                               │
│     """Optional short description/summar                                        │
│                                                                                                              │
│     # BREAKING: Removed content_markdown                                        │
│     # NEW: Schema-driven content                                                                             │
│     data: dict = Field(                                                         │
│         ...,                                                                                                 │
│         description="Entry content as de                                        │
│     )                                                                                                        │
│     """Entry content structured accordin                                        │
│                                                                                                              │
│     published_at: datetime | None = None                                        │
│     """Timestamp when the entry was published."""                                                            │
│                                                                                 │
│     metadata: dict | None = None                                                                             │
│     """Custom non-schema metadata as JSO                                        │
│                                                                                                              │
│     collections: list[PublishedCollectio                                        │
│     """Collections this entry belongs to."""                                                                 │
│                                                                                 │
│     resources: list[PublishedResourceRead] = []                                                              │
│     """Resources referenced by this entr                                        │
│                                                                                                              │
│     assets: list[PublishedAssetRead] = [                                        │
│     """Assets included in this entry."""                                                                     │
│                                                                                 │
│ Publishing controller logic:                                                                                 │
│ def build_published_entry(entry: Entries                                        │
│     # ... build collections, resources, assets lists ...                                                     │
│                                                                                 │
│     return PublishedEntryRead(                                                                               │
│         slug=entry.slug,                                                        │
│         title=entry.title,                                                                                   │
│         entry_type=entry.entry_type.slugknown",                                 │
│         summary=entry.summary,                                                                               │
│         data=entry.data_json,  # Schema-                                        │
│         metadata=entry.metadata_json,  # Custom metadata                                                     │
│         published_at=entry.published_at,                                        │
│         collections=collections,                                                                             │
│         resources=resources,                                                    │
│         assets=assets,                                                                                       │
│     )                                                                           │
│                                                                                                              │
│ ---                                                                             │
│ SDK Impact (Breaking Changes Required)                                                                       │
│                                                                                 │
│ TypeScript Type Changes                                                                                      │
│                                                                                 │
│ Publishing SDK (marvin-sdk) - BREAKING:                                                                      │
│                                                                                 │
│ Current:                                                                                                     │
│ export interface MarvinEntry {                                                  │
│   id: string;                                                                                                │
│   title: string;                                                                │
│   slug: string;                                                                                              │
│   summary?: string;                                                             │
│   description?: string;                                                                                      │
│   contentMarkdown?: string;  // ← REMOVI                                        │
│   metadata?: Record<string, unknown>;                                                                        │
│   status: string;                                                               │
│   publishedAt?: string;                                                                                      │
│   // ...                                                                        │
│ }                                                                                                            │
│                                                                                 │
│ New:                                                                                                         │
│ export interface MarvinEntry {                                                  │
│   id: string;                                                                                                │
│   title: string;                                                                │
│   slug: string;                                                                                              │
│   summary?: string;                                                             │
│   description?: string;                                                                                      │
│                                                                                 │
│   // BREAKING: Replaced contentMarkdown with dataJson                                                        │
│   dataJson: Record<string, any>;  // Req                                        │
│                                                                                                              │
│   metadata?: Record<string, unknown>;  /                                        │
│   status: string;                                                                                            │
│   publishedAt?: string;                                                         │
│   // ... rest                                                                                                │
│ }                                                                               │
│                                                                                                              │
│ Entry class helper - BREAKING:                                                  │
│                                                                                                              │
│ Current:                                                                        │
│ export class Entry {                                                                                         │
│   get contentMarkdown() { return this.da                                        │
│   // ...                                                                                                     │
│ }                                                                               │
│                                                                                                              │
│ New:                                                                            │
│ export class Entry {                                                                                         │
│   constructor(                                                                  │
│     private data: MarvinEntry,                                                                               │
│     private http: MarvinHttpClient,                                             │
│     private workspaceSlug: string                                                                            │
│   ) {}                                                                          │
│                                                                                                              │
│   // REMOVED: get contentMarkdown()                                             │
│                                                                                                              │
│   // NEW: Structured content access                                             │
│   get dataJson() {                                                                                           │
│     return this.data.dataJson;                                                  │
│   }                                                                                                          │
│                                                                                 │
│   // Convenience: access specific fields with type safety                                                    │
│   field<T = any>(key: string): T | undef                                        │
│     return this.dataJson[key] as T;                                                                          │
│   }                                                                             │
│                                                                                                              │
│   // Convenience: check if field exists                                         │
│   hasField(key: string): boolean {                                                                           │
│     return key in this.dataJson;                                                │
│   }                                                                                                          │
│                                                                                 │
│   // ... existing getters (id, title, slug, etc.)                                                            │
│ }                                                                               │
│                                                                                                              │
│ Migration Guide for SDK Users                                                   │
│                                                                                                              │
│ Before (Old SDK):                                                               │
│ import { MarvinClient } from '@marvin/sdk';                                                                  │
│ import { marked } from 'marked';                                                │
│                                                                                                              │
│ const marvin = new MarvinClient({ /* con                                        │
│ const entry = await marvin.entry('about-us');                                                                │
│                                                                                 │
│ // Access markdown content                                                                                   │
│ const markdown = entry.contentMarkdown |                                        │
│ const html = marked.parse(markdown);                                                                         │
│                                                                                 │
│ After (New SDK):                                                                                             │
│ import { MarvinClient } from '@marvin/sd                                        │
│ import { marked } from 'marked';                                                                             │
│                                                                                 │
│ const marvin = new MarvinClient({ /* config */ });                                                           │
│ const entry = await marvin.entry('about-                                        │
│                                                                                                              │
│ // Access schema-driven content                                                 │
│ const markdown = entry.field<string>('body') || '';  // 'body' is default markdown field                     │
│ const html = marked.parse(markdown);                                            │
│                                                                                                              │
│ // Or direct access                                                             │
│ const markdown = entry.dataJson.body || '';                                                                  │
│                                                                                 │
│ // For custom entry types (e.g., Project):                                                                   │
│ const difficulty = entry.field<string>('                                        │
│ const heroImage = entry.field<string>('heroImage');  // Asset UUID                                           │
│                                                                                 │
│ SDK Version Strategy                                                                                         │
│                                                                                 │
│ Recommendation: Major version bump (v2.0.0)                                                                  │
│                                                                                 │
│ Breaking changes:                                                                                            │
│ 1. ❌ MarvinEntry.contentMarkdown remove                                        │
│ 2. ❌ Entry.contentMarkdown getter removed → Entry.field() method                                            │
│ 3. ❌ Publishing API response shape chan                                        │
│                                                                                                              │
│ Migration path:                                                                 │
│ 1. Release SDK v2.0.0 simultaneously with backend breaking change                                            │
│ 2. Provide migration guide in SDK CHANGE                                        │
│ 3. Update all examples and documentation                                                                     │
│ 4. Deprecation period not possible (back)                                       │
│                                                                                                              │
│ ---                                                                             │
│ Editor Implementation (Future)                                                                               │
│                                                                                 │
│ Schema-Driven Form Rendering                                                                                 │
│                                                                                 │
│ Frontend editor loads Entry Type schema:                                                                     │
│ // Fetch entry type schema                                                      │
│ const entryType = await marvin.platform.entryTypes.get(entryTypeId);                                         │
│                                                                                 │
│ if (entryType.schemaJson) {                                                                                  │
│   // Render dynamic form from schema                                            │
│   entryType.schemaJson.fields.forEach(field => {                                                             │
│     renderField(field);  // Dynamic fiel                                        │
│   });                                                                                                        │
│ } else {                                                                        │
│   // Fall back to legacy Markdown editor                                                                     │
│   renderMarkdownEditor();                                                       │
│ }                                                                                                            │
│                                                                                 │
│ Field renderer mapping:                                                                                      │
│ function renderField(field: FieldSchema)                                        │
│   switch (field.type) {                                                                                      │
│     case 'markdown':                                                            │
│       return <MarkdownEditor field={field} />;                                                               │
│     case 'text':                                                                │
│       return <TextInput field={field} />;                                                                    │
│     case 'select':                                                              │
│       return <Select options={field.options} field={field} />;                                               │
│     case 'asset':                                                               │
│       return <AssetPicker field={field} />;                                                                  │
│     // ... etc                                                                  │
│   }                                                                                                          │
│ }                                                                               │
│                                                                                                              │
│ Form submission:                                                                │
│ // Collect values from schema-driven form                                                                    │
│ const contentJson = {                                                           │
│   body: markdownValue,                                                                                       │
│   heroImage: selectedAssetId,                                                   │
│   difficulty: selectedDifficulty,                                                                            │
│ };                                                                              │
│                                                                                                              │
│ await marvin.platform.entries.update(ent                                        │
│   contentJson,                                                                                               │
│ });                                                                             │
│                                                                                                              │
│ ---                                                                             │
│ Example Content Models                                                                                       │
│                                                                                 │
│ Page (Default)                                                                                               │
│                                                                                 │
│ {                                                                                                            │
│   "fields": [                                                                   │
│     {                                                                                                        │
│       "key": "markdown",                                                        │
│       "label": "Content",                                                                                    │
│       "type": "markdown",                                                       │
│       "required": false                                                                                      │
│     }                                                                           │
│   ]                                                                                                          │
│ }                                                                               │
│                                                                                                              │
│ Project                                                                         │
│                                                                                                              │
│ {                                                                               │
│   "fields": [                                                                                                │
│     {"key": "overview", "label": "Overviuired": true},                          │
│     {"key": "heroImage", "label": "Hero Image", "type": "asset"},                                            │
│     {"key": "gallery", "label": "Gallery                                        │
│     {"key": "status", "label": "Status", "type": "select", "options": ["planning", "in-progress",            │
│ "complete"]},                                                                   │
│     {"key": "difficulty", "label": "Difficulty", "type": "select", "options": ["beginner", "intermediate",   │
│ "advanced"]},                                                                   │
│     {"key": "startedDate", "label": "Started", "type": "date"},                                              │
│     {"key": "completedDate", "label": "C                                        │
│     {"key": "relatedResources", "label": "Related Resources", "type": "resource-list"}                       │
│   ]                                                                             │
│ }                                                                                                            │
│                                                                                 │
│ FAQ                                                                                                          │
│                                                                                 │
│ {                                                                                                            │
│   "fields": [                                                                   │
│     {"key": "question", "label": "Question", "type": "text", "required": true},                              │
│     {"key": "answer", "label": "Answer",d": true},                              │
│     {"key": "category", "label": "Category", "type": "select", "options": ["general", "technical",           │
│ "billing"]}                                                                     │
│   ]                                                                                                          │
│ }                                                                               │
│                                                                                                              │
│ Navigation Item                                                                 │
│                                                                                                              │
│ {                                                                               │
│   "fields": [                                                                                                │
│     {"key": "label", "label": "Label", "ue},                                    │
│     {"key": "href", "label": "URL", "type": "text", "required": true},                                       │
│     {"key": "openInNewTab", "label": "Opean", "defaultValue": false},           │
│     {"key": "icon", "label": "Icon", "type": "text"}                                                         │
│   ]                                                                             │
│ }                                                                                                            │
│                                                                                 │
│ Material (Crafts/Sewing)                                                                                     │
│                                                                                 │
│ {                                                                                                            │
│   "fields": [                                                                   │
│     {"key": "supplier", "label": "Supplier", "type": "resource", "required": false},                         │
│     {"key": "composition", "label": "Com                                        │
│     {"key": "weight", "label": "Weight", "type": "text"},                                                    │
│     {"key": "width", "label": "Width", "                                        │
│     {"key": "color", "label": "Color", "type": "text"},                                                      │
│     {"key": "origin", "label": "Origin C                                        │
│     {"key": "care", "label": "Care Instructions", "type": "textarea"},                                       │
│     {"key": "photos", "label": "Photos",                                        │
│   ]                                                                                                          │
│ }                                                                               │
│                                                                                                              │
│ ---                                                                             │
│ Implementation Phases                                                                                        │
│                                                                                 │
│ Phase 1: Backend Foundation (Week 1)                                                                         │
│                                                                                 │
│ - [ ] Create Pydantic schema models for field definitions (entry_type_schema.py)                             │
│ - [ ] Create ContentValidator service fot schemas                               │
│ - [ ] Add unit tests for schema validation logic                                                             │
│ - [ ] Add unit tests for content validat                                        │
│                                                                                                              │
│ Phase 2: Database Migration (Week 1-2)                                          │
│                                                                                                              │
│ - [ ] Write Alembic migration: add schem                                        │
│ - [ ] Write Alembic migration: add data_json to entries                                                      │
│ - [ ] Write migration logic: populate deypes                                    │
│ - [ ] Write migration logic: migrate content_markdown → data_json.body                                       │
│ - [ ] Write migration logic: drop conten                                        │
│ - [ ] Test migration up/down on development database                                                         │
│ - [ ] Verify all existing entries migrat                                        │
│                                                                                                              │
│ Phase 3: API Updates (Week 2)                                                   │
│                                                                                                              │
│ - [ ] Update EntryTypes model with schem                                        │
│ - [ ] Update Entries model: remove content_markdown, add data_json                                           │
│ - [ ] Update Entry Type schemas (Create/a_json                                  │
│ - [ ] Update Entry schemas (Create/Update/Read) to use data_json                                             │
│ - [ ] Update Publishing API schemas: rema                                       │
│ - [ ] Update Entry repository: integrate ContentValidator                                                    │
│ - [ ] Update Entry Type repository: validate                                    │
│ - [ ] Update Publishing controller: return data instead of content_markdown                                  │
│ - [ ] Add integration tests for CRUD wit                                        │
│                                                                                                              │
│ Phase 4: SDK Updates (Week 2)                                                   │
│                                                                                                              │
│ - [ ] Update SDK TypeScript types: removon                                      │
│ - [ ] Update Entry class: remove contentMarkdown getter, add field() helper                                  │
│ - [ ] Update Platform API types (if usin                                        │
│ - [ ] Update all SDK examples and documentation                                                              │
│ - [ ] Release SDK v2.0.0 with breaking c                                        │
│ - [ ] Write migration guide for SDK users                                                                    │
│                                                                                 │
│ Phase 5: Editor Support (Week 3+)                                                                            │
│                                                                                 │
│ - [ ] Build schema-driven form renderer in frontend                                                          │
│ - [ ] Create field component library (ma etc.)                                  │
│ - [ ] Add schema editor UI for creating/modifying entry types                                                │
│ - [ ] Update entry editor to render from                                        │
│ - [ ] Add asset/resource picker components for reference fields                                              │
│ - [ ] Test all field types in editor                                            │
│                                                                                                              │
│ Phase 6: Deployment (Week 3-4)                                                  │
│                                                                                                              │
│ - [ ] Run migration on staging environme                                        │
│ - [ ] Verify all entries migrated correctly                                                                  │
│ - [ ] Test Publishing API breaking chang                                        │
│ - [ ] Deploy backend + frontend together (coordinated)                                                       │
│ - [ ] Update SDK users with migration gu                                        │
│ - [ ] Monitor for issues                                                                                     │
│                                                                                 │
│ ---                                                                                                          │
│ Testing Strategy                                                                │
│                                                                                                              │
│ Unit Tests                                                                      │
│                                                                                                              │
│ - Schema validation (valid/invalid field                                        │
│ - Content validation against schema (required fields, type checking)                                         │
│ - Backward compatibility (entries withou                                        │
│ - Migration up/down                                                                                          │
│                                                                                 │
│ Integration Tests                                                                                            │
│                                                                                 │
│ - Entry CRUD with schema-driven content                                                                      │
│ - Publishing API with both content forma                                        │
│ - SDK compatibility                                                                                          │
│                                                                                 │
│ End-to-End Tests                                                                                             │
│                                                                                 │
│ - Create entry type with schema                                                                              │
│ - Create entry using schema                                                     │
│ - Fetch via Publishing API                                                                                   │
│ - Render in SDK                                                                 │
│                                                                                                              │
│ ---                                                                             │
│ Rollback Strategy                                                                                            │
│                                                                                 │
│ Before Migration Runs                                                                                        │
│                                                                                 │
│ - No changes deployed, safe to abort                                                                         │
│                                                                                 │
│ After Migration, Before Column Drop                                                                          │
│                                                                                 │
│ - Migration stores content_markdown → data_json.body                                                         │
│ - Downgrade migration reverses: data_jso                                        │
│ - Both columns exist temporarily, safe rollback                                                              │
│                                                                                 │
│ After Column Drop (Point of No Return)                                                                       │
│                                                                                 │
│ - content_markdown column dropped                                                                            │
│ - Rolling back requires:                                                        │
│   a. Re-run downgrade migration (adds column back)                                                           │
│   b. Extract data_json.body → content_ma                                        │
│   c. Drop data_json and schema_json                                                                          │
│   d. Rollback SDK to v1.x                                                       │
│   e. Rollback Publishing API changes                                                                         │
│                                                                                 │
│ Risk: Data loss if entries use non-body fields (custom schemas)                                              │
│                                                                                 │
│ Emergency Rollback Procedure                                                                                 │
│                                                                                 │
│ # 1. Rollback database migration                                                                             │
│ alembic downgrade -1                                                            │
│                                                                                                              │
│ # 2. Rollback backend deployment                                                │
│ # (restore previous version)                                                                                 │
│                                                                                 │
│ # 3. Notify SDK users to pin to v1.x                                                                         │
│ # (v2.0.0 won't work with old backend)                                          │
│                                                                                                              │
│ # 4. Verify system operational                                                  │
│ # All entries should have content_markdown restored from data_json.body                                      │
│                                                                                 │
│ Prevention: Test migration thoroughly on staging with production data snapshot                               │
│                                                                                 │
│ ---                                                                                                          │
│ Files to Create/Modify                                                          │
│                                                                                                              │
│ Database                                                                        │
│                                                                                                              │
│ - Create: src/marvin/alembic/versions/20ype_schemas.py                          │
│                                                                                                              │
│ Models                                                                          │
│                                                                                                              │
│ - Update: src/marvin/db/models/platform/on)                                     │
│ - Update: src/marvin/db/models/platform/entries.py (remove content_markdown, add data_json)                  │
│                                                                                 │
│ Schemas                                                                                                      │
│                                                                                 │
│ - Create: src/marvin/schemas/platform/entry_type_schema.py (field definitions, ContentValidator)             │
│ - Update: src/marvin/schemas/platform/en field)                                 │
│ - Update: src/marvin/schemas/platform/entries.py (replace content_markdown with data_json)                   │
│ - Update: src/marvin/schemas/publishing.with data)                              │
│                                                                                                              │
│ Services                                                                        │
│                                                                                                              │
│ - Create: src/marvin/services/content_van against schema_json)                  │
│                                                                                                              │
│ Repositories                                                                    │
│                                                                                                              │
│ - Update: src/marvin/repos/platform/entrson)                                    │
│ - Update: src/marvin/repos/platform/entries.py (validate data_json, integrate ContentValidator)              │
│                                                                                 │
│ Controllers                                                                                                  │
│                                                                                 │
│ - Update: src/marvin/routes/platform/entry_types_controller.py (accept schema_json)                          │
│ - Update: src/marvin/routes/platform/entta_json)                                │
│ - Update: src/marvin/routes/publish/publishing_controller.py (return data instead of content_markdown)       │
│                                                                                 │
│ SDK (separate repo: ~/Code/marvin-sdk)                                                                       │
│                                                                                 │
│ - Update: src/types/index.ts (replace contentMarkdown with dataJson)                                         │
│ - Update: src/entries/entry.ts (remove celd() helper)                           │
│ - Update: src/platform/entries.ts (update Platform API types if needed)                                      │
│ - Update: README.md (update examples)                                           │
│ - Update: examples.md (update all code examples)                                                             │
│ - Update: CHANGELOG.md (document breakin                                        │
│ - Create: MIGRATION.md (migration guide for v1 → v2)                                                         │
│                                                                                 │
│ Tests                                                                                                        │
│                                                                                 │
│ - Create: tests/unit/test_entry_type_schema_validation.py (field schema validation)                          │
│ - Create: tests/unit/test_content_validaagainst schema)                         │
│ - Create: tests/integration/test_schema_driven_entries.py (end-to-end CRUD)                                  │
│ - Create: tests/integration/test_contentc)                                      │
│ - Update: Existing entry tests to use data_json instead of content_markdown                                  │
│                                                                                 │
│ ---                                                                                                          │
│ Verification Plan                                                               │
│                                                                                                              │
│ Manual Verification                                                             │
│                                                                                                              │
│ 1. Create schema-driven Entry Type:                                             │
│   - POST /api/platform/entry-types with schemaJson                                                           │
│   - Verify schema validates correctly                                           │
│   - Verify GET returns schema                                                                                │
│ 2. Create Entry with schema:                                                    │
│   - POST /api/platform/entries with contentJson                                                              │
│   - Verify content validates against sch                                        │
│   - Verify required fields enforced                                                                          │
│   - Verify field type validation works                                          │
│ 3. Publishing API:                                                                                           │
│   - GET entry via /api/publish/{workspac                                        │
│   - Verify both content_markdown and content fields present                                                  │
│   - Verify backward compatibility with e                                        │
│ 4. SDK compatibility:                                                                                        │
│   - Fetch entry via SDK                                                         │
│   - Verify entry.content accessor works                                                                      │
│   - Verify entry.contentMarkdown still w                                        │
│                                                                                                              │
│ Automated Tests                                                                 │
│                                                                                                              │
│ # Run unit tests                                                                │
│ pytest tests/unit/test_entry_type_schema_validation.py -v                                                    │
│                                                                                 │
│ # Run integration tests                                                                                      │
│ pytest tests/integration/test_schema_dri                                        │
│                                                                                                              │
│ # Run full test suite                                                           │
│ pytest tests/ -v                                                                                             │
│                                                                                 │
│ Database Verification                                                                                        │
│                                                                                 │
│ -- Verify columns exist                                                                                      │
│ \d entry_types;                                                                 │
│ \d entries;                                                                                                  │
│                                                                                 │
│ -- Check schema_json structure                                                                               │
│ SELECT id, name, schema_json FROM entry_T NULL;                                 │
│                                                                                                              │
│ -- Check content_json structure                                                 │
│ SELECT id, title, content_json FROM entries WHERE content_json IS NOT NULL;                                  │
│                                                                                 │
│ ---                                                                                                          │
│ Open Questions for User                                                         │
│                                                                                                              │
│ None - plan is complete and ready for im                                        │
│                                                                                                              │
│ ---                                                                             │
│ Breaking Change Coordination                                                                                 │
│                                                                                 │
│ This is a coordinated breaking change requiring simultaneous updates across:                                 │
│                                                                                 │
│ 1. Backend (Marvin server)                                                                                   │
│   - Database migration removes content_m                                        │
│   - API responses change shape                                                                               │
│   - Must deploy before or simultaneously                                        │
│ 2. Frontend (Marvin admin)                                                                                   │
│   - Forms must send dataJson instead of                                         │
│   - Editor must render from schema                                                                           │
│   - Must deploy simultaneously with back                                        │
│ 3. SDK (marvin-sdk v2.0.0)                                                                                   │
│   - Type definitions change                                                     │
│   - Must be released before or simultaneously with backend                                                   │
│   - Users must upgrade to v2.0.0                                                │
│ 4. External Consumers                                                                                        │
│   - Sites using Publishing API must upda                                        │
│   - Sites using SDK must upgrade to v2.0.0                                                                   │
│   - Migration guide required                                                    │
│                                                                                                              │
│ Deployment Strategy                                                             │
│                                                                                                              │
│ Option A: Big Bang (Recommended for MVP)                                        │
│ - Deploy backend + frontend together                                                                         │
│ - Release SDK v2.0.0 simultaneously                                             │
│ - Accept downtime during deployment                                                                          │
│ - Notify all API consumers in advance                                           │
│                                                                                                              │
│ Option B: API Versioning (Future conside                                        │
│ - Create /api/v2/publish alongside /api/publish                                                              │
│ - Support both APIs for deprecation peri                                        │
│ - More complex but safer for external consumers                                                              │
│                                                                                 │
│ Communication Plan                                                                                           │
│                                                                                 │
│ Before Deployment:                                                                                           │
│ 1. Announce breaking change 2 weeks in a                                        │
│ 2. Provide migration guide for SDK users                                                                     │
│ 3. Provide migration guide for Publishin                                        │
│ 4. Test migration on staging with production data                                                            │
│                                                                                 │
│ During Deployment:                                                                                           │
│ 1. Put system in maintenance mode                                               │
│ 2. Run migration                                                                                             │
│ 3. Deploy backend                                                               │
│ 4. Deploy frontend                                                                                           │
│ 5. Release SDK v2.0.0                                                           │
│ 6. Verify system operational                                                                                 │
│                                                                                 │
│ After Deployment:                                                                                            │
│ 1. Monitor for errors                                                           │
│ 2. Support users migrating their code                                                                        │
│ 3. Update all documentation                                                     │
│                                                                                                              │
│ ---                                                                             │
│ Summary                                                                                                      │
│                                                                                 │
│ This architecture transforms Marvin from a Markdown CMS into a schema-driven content platform through a      │
│ breaking change migration:                                                      │
│                                                                                                              │
│ 1. Clean replacement - Remove content_mariven data_json                         │
│ 2. Validation framework - Pydantic-based schema validation following existing patterns (discriminated        │
│ unions, JSONB)                                                                  │
│ 3. Flexible content models - Support diverse content types (Page, Project, FAQ, Material, etc.) without      │
│ backend changes                                                                 │
│ 4. Breaking but necessary - Coordinated backend + SDK update required, but enables unlimited content model   │
│ flexibility                                                                     │
│ 5. Future-proof - Room for UI layout, advanced field types, conditional validation, and extensibility        │
│                                                                                 │
│ The implementation follows Marvin's existing patterns:                                                       │
│ - JSONB columns for structured data (likuled_tasks.schedule_config)             │
│ - Pydantic discriminated unions (like schedule_type: Literal["cron", "interval", "once"])                    │
│ - Repository-layer validation with dedic                                        │
│ - Alembic migrations with up/down paths                                                                      │
│                                                                                 │
│ Migration Risk: Medium-High due to breaking changes, mitigated by:                                           │
│ - Thorough testing on staging                                                   │
│ - Data migration in same transaction as schema change                                                        │
│ - Downgrade path available (though risky                                        │
│ - Clear communication to all stakeholders
