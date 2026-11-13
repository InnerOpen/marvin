"""Entry schemas."""

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import UUID4, AliasChoices, BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from marvin.schemas._marvin import _MarvinModel

if TYPE_CHECKING:
    from .assets import EntryAssetRead
    from .collections import EntryCollectionRead
    from .resources import EntryResourceRead

ENTRY_STATUSES = {
    "inbox",
    "processing",
    "draft",
    "needs_review",
    "approved",
    "published",
    "archived",
    "trashed",
}

TRASHED = "trashed"
"""The Trash: an entry moved there by Delete (or the `trash` workflow op / trash_entries tool). Hidden from
every listing but the Trash collection, restorable, and permanently deleted only when the Trash is emptied."""


class AssetAttachment(BaseModel):
    asset_id: UUID4
    role: str | None = None
    position: int | None = None
    metadata: dict | None = None


class ResourceAttachment(BaseModel):
    resource_id: UUID4
    role: str | None = None
    position: int | None = None
    metadata: dict | None = None


class CollectionAttachment(BaseModel):
    collection_id: UUID4
    role: str | None = None
    metadata: dict | None = None


class EntryCreate(_MarvinModel):
    """Schema for creating an entry.

    BREAKING CHANGE: content_markdown removed, replaced with data_json.
    Entry content is now schema-driven based on entry_type.schema_json.
    """

    entry_type_id: UUID4
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    summary: str | None = None
    description: str | None = None
    data_json: dict = Field(
        default_factory=dict,
        description="Schema-driven content data (validated against entry_type.schema_json)",
        serialization_alias="dataJson",
    )
    status: str = "inbox"
    published_at: datetime | None = None
    publish_at: datetime | None = None
    expire_at: datetime | None = None
    metadata_json: dict | None = Field(
        default=None,
        description="Custom non-schema metadata (API keys, external IDs, etc.)",
        serialization_alias="metadataJson",
    )
    collection_ids: list[UUID4] | None = None
    collection_attachments: list[CollectionAttachment] | None = None
    asset_ids: list[UUID4] | None = None
    resource_ids: list[UUID4] | None = None
    asset_attachments: list[AssetAttachment] | None = None
    resource_attachments: list[ResourceAttachment] | None = None
    tag_ids: list[UUID4] | None = None
    """Existing tag IDs to apply to this entry (resolve typed names via POST /tags first)."""

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in ENTRY_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(ENTRY_STATUSES))}")
        if value == TRASHED:
            raise ValueError("an entry can't be created in the Trash")
        return value

    @model_validator(mode="after")
    def check_no_ambiguous_attachments(self):
        if self.asset_ids and self.asset_attachments:
            raise ValueError("Provide asset_ids or asset_attachments, not both")
        if self.resource_ids and self.resource_attachments:
            raise ValueError("Provide resource_ids or resource_attachments, not both")
        if self.collection_ids and self.collection_attachments:
            raise ValueError("Provide collection_ids or collection_attachments, not both")
        return self

    model_config = ConfigDict(from_attributes=True)


class EntryUpdate(_MarvinModel):
    """Schema for patching an entry.

    BREAKING CHANGE: content_markdown removed, replaced with data_json.
    Entry content is now schema-driven based on entry_type.schema_json.
    """

    entry_type_id: UUID4 | None = Field(default=None, validation_alias=AliasChoices("entry_type_id", "entryTypeId"))
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = None
    summary: str | None = None
    description: str | None = None
    data_json: dict | None = Field(
        default=None,
        description="Schema-driven content data (validated against entry_type.schema_json)",
        serialization_alias="dataJson",
    )
    status: str | None = None
    published_at: datetime | None = None
    publish_at: datetime | None = None
    expire_at: datetime | None = None
    metadata_json: dict | None = Field(
        default=None,
        description="Custom non-schema metadata (API keys, external IDs, etc.)",
        serialization_alias="metadataJson",
    )
    collection_ids: list[UUID4] | None = Field(default=None, validation_alias=AliasChoices("collection_ids", "collectionIds"))
    collection_attachments: list[CollectionAttachment] | None = Field(
        default=None, validation_alias=AliasChoices("collection_attachments", "collectionAttachments")
    )
    asset_ids: list[UUID4] | None = Field(default=None, validation_alias=AliasChoices("asset_ids", "assetIds"))
    resource_ids: list[UUID4] | None = Field(default=None, validation_alias=AliasChoices("resource_ids", "resourceIds"))
    asset_attachments: list[AssetAttachment] | None = Field(default=None, validation_alias=AliasChoices("asset_attachments", "assetAttachments"))
    resource_attachments: list[ResourceAttachment] | None = Field(
        default=None, validation_alias=AliasChoices("resource_attachments", "resourceAttachments")
    )
    tag_ids: list[UUID4] | None = Field(default=None, validation_alias=AliasChoices("tag_ids", "tagIds"))
    """Existing tag IDs to replace this entry's tags (resolve typed names via POST /tags first)."""

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in ENTRY_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(ENTRY_STATUSES))}")
        return value

    @field_validator("published_at", "publish_at", "expire_at", mode="before")
    @classmethod
    def validate_datetime_fields(cls, value: str | datetime | None) -> str | datetime | None:
        """Convert empty strings to None for datetime fields."""
        if value == "":
            return None
        return value

    @model_validator(mode="after")
    def check_no_ambiguous_attachments(self):
        if self.asset_ids and self.asset_attachments:
            raise ValueError("Provide asset_ids or asset_attachments, not both")
        if self.resource_ids and self.resource_attachments:
            raise ValueError("Provide resource_ids or resource_attachments, not both")
        if self.collection_ids and self.collection_attachments:
            raise ValueError("Provide collection_ids or collection_attachments, not both")
        return self

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ScheduledPublishBlock(_MarvinModel):
    """Why the Publish Scheduled Entries task is holding a due entry back (entries.scheduled_publish_blocked)."""

    waiting_for: str = "requirements"
    """"requirements" (the publish gate refused it) or "approval" (the workspace only publishes approved entries on schedule)."""
    reason: str = ""
    """One line: the issues joined, or "Waiting for approval"."""
    issues: list[str] = []
    """Each unmet requirement, as the publish gate words it."""
    at: datetime | None = None
    """When the task first held it back for this reason."""


# Fields EntryRead.model_validate fills from an entry row's junction rows (and tag_names). Read as attributes, they would
# lazy-load the plain relationships of the same name (`Entries.collections`, `.assets`, `.resources`) only to throw them
# away: three queries per entry, most of a list's time (measured 2026-11-13).
_FROM_JUNCTIONS = ("tags", "collections", "assets", "resources")


class EntryRead(_MarvinModel):
    """Schema for reading an entry.

    BREAKING CHANGE: content_markdown removed, replaced with data_json.
    Entry content is now schema-driven based on entry_type.schema_json.
    """

    id: UUID4
    group_id: UUID4
    entry_type_id: UUID4
    title: str
    slug: str
    summary: str | None = None
    description: str | None = None
    data_json: dict = Field(
        default_factory=dict,
        description="Schema-driven content data",
        serialization_alias="dataJson",
    )
    status: str
    published_at: datetime | None = None
    publish_at: datetime | None = None
    expire_at: datetime | None = None
    metadata_json: dict | None = Field(
        default=None,
        description="Custom non-schema metadata",
        serialization_alias="metadataJson",
    )
    suggestion_json: dict | None = Field(
        default=None,
        description="Pending AI-proposed changes staged for review (write-back)",
        serialization_alias="suggestionJson",
    )
    scheduled_publish_blocked: ScheduledPublishBlock | None = None
    """Set while the entry's publish_at has arrived but the scheduled publish is holding it back, and why."""
    created_by: UUID4 | None = None
    created_at: datetime | None = None
    update_at: datetime | None = None
    resources: list["EntryResourceRead"] = []
    """Resources referenced by this entry with placement info."""
    assets: list["EntryAssetRead"] = []
    """Assets included in this entry with placement info."""
    collections: list["EntryCollectionRead"] = []
    """Collections this entry belongs to, with placement info."""
    tags: list[str] = []
    """Tag slugs applied to this entry (shared vocabulary)."""
    order: int | None = None
    """Sort order within a collection. Only populated when querying entries for a specific collection."""
    page_url: str | None = None
    """Absolute URL of the entry's page on the workspace's site (its type's page URL pattern joined to the
    workspace's Canonical URL). Only populated on a single-entry read; null when either isn't configured.
    Not gated on status — a draft's URL isn't live until it is published."""

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def loader_options(cls):
        """What `model_validate` reads off a row, loaded up front: one query per relationship for the whole page
        (selectin), not one join of all four, whose rows multiply per entry (3 collections x 2 assets x 3 tags is 18
        copies of the entry, its JSON columns decoded each time)."""
        from sqlalchemy.orm import selectinload

        from marvin.db.models.platform import Entries, EntryAssets, EntryCollections, EntryResources
        from marvin.db.models.platform.assets import Assets

        return [
            selectinload(Entries.entry_collections).joinedload(EntryCollections.collection),
            selectinload(Entries.entry_assets).joinedload(EntryAssets.asset).selectinload(Assets.tags),  # EntryAssetRead lists them
            selectinload(Entries.entry_resources).joinedload(EntryResources.resource),
            selectinload(Entries.tags),
        ]

    @classmethod
    def model_validate(cls, obj, **kwargs):
        """Custom validation to extract collection IDs and build asset/resource details."""
        is_row = hasattr(obj, "entry_collections")
        data = {field: getattr(obj, field, None) for field in cls.model_fields if not (is_row and field in _FROM_JUNCTIONS)}

        # `obj.tags` is the ORM relationship (Tag objects); the schema field is list[str] of slugs.
        # tag_names is the property over the junction — use it so validation gets strings, not rows.
        if "tags" in cls.model_fields:
            data["tags"] = list(getattr(obj, "tag_names", None) or [])

        # Collections come from the junction rows only (they carry the placement fields). The plain
        # `collections` relationship can be loaded later than `entry_collections` and disagree with it —
        # e.g. after the smart-collection listener commits a membership in its own session — so it
        # must never feed this field. (An object without junction rows — an EntryRead being re-validated —
        # keeps the summaries it already has.)
        if hasattr(obj, "entry_collections"):
            data["collections"] = []
        if hasattr(obj, "entry_collections") and obj.entry_collections:
            from marvin.schemas.platform.collections import EntryCollectionRead

            collections = []
            for junction in obj.entry_collections:
                if hasattr(junction, "collection") and junction.collection:
                    c = junction.collection
                    collections.append(
                        EntryCollectionRead(
                            id=c.id,
                            name=c.name,
                            slug=c.slug,
                            icon=c.icon,
                            color=c.color,
                            role=junction.role,
                            placement_metadata=junction.metadata_json,
                            sort_order=junction.sort_order,
                        )
                    )
            data["collections"] = collections

            if obj.entry_collections and hasattr(obj.entry_collections[0], "sort_order"):
                data["order"] = obj.entry_collections[0].sort_order

        if hasattr(obj, "entry_assets") and obj.entry_assets:
            from marvin.schemas.platform.assets import EntryAssetRead

            assets = []
            for junction in obj.entry_assets:
                # An asset in the Trash is out of sight; its link stays for a restore (services/trash.py).
                if hasattr(junction, "asset") and junction.asset and getattr(junction.asset, "trashed_at", None) is None:
                    asset_data = {
                        **{k: getattr(junction.asset, k, None) for k in EntryAssetRead.model_fields if hasattr(junction.asset, k)},
                        "role": junction.role,
                        "position": junction.position,
                        "placement_metadata": junction.metadata_json,
                    }
                    assets.append(asset_data)
            data["assets"] = assets

        if hasattr(obj, "entry_resources") and obj.entry_resources:
            from marvin.schemas.platform.resources import EntryResourceRead

            resources = []
            for junction in obj.entry_resources:
                if hasattr(junction, "resource") and junction.resource and getattr(junction.resource, "trashed_at", None) is None:
                    resource_data = {
                        **{k: getattr(junction.resource, k, None) for k in EntryResourceRead.model_fields if hasattr(junction.resource, k)},
                        "role": junction.role,
                        "position": junction.position,
                        "placement_metadata": junction.metadata_json,
                    }
                    resources.append(resource_data)
            data["resources"] = resources

        return super().model_validate(data, **kwargs)


class EntryQueryRequest(_MarvinModel):
    """A structured search: `spec` takes the keys the assistants' find_entries takes (entry_types, status, tags,
    collection, where [{field, op, value}], query, has_images, created_/updated_/published_ after|before, sort…),
    all ANDed. See services/entries/query.py."""

    spec: dict = {}
    limit: int = 200
    offset: int = 0


class EntryQueryResult(_MarvinModel):
    entries: list[EntryRead]
    total: int
    """Every match, not only this page."""
    note: str | None = None
    """Why a condition can't match anything (an unknown tag, a status that isn't one), when it can't."""
    unknown_ops: list[str] = []
    """Comparison operators the engine doesn't know: it refuses the search, and `note` lists the valid ones."""


class EntryBulkDeleteRequest(_MarvinModel):
    """A bulk delete (services/entries/bulk_delete.py): the entries `spec` selects (an entry query, the keys of
    POST /entries/query; it must narrow by type, fields, entries, a collection, tags, text or where), moved to the Trash
    (`mode` trash, restorable) or deleted for good (`mode` permanent, ADMIN/OWNER). `confirmTotal` is the total the
    preview counted: required to delete, and nothing is done when the selection no longer has that many."""

    spec: dict
    mode: Literal["trash", "permanent"] = "trash"
    confirm_total: int | None = None
    description: str | None = Field(default=None, max_length=300)
    """What the entries are, for the summary event ("what the import made for The Last Onion")."""


class EntryBulkDeleteType(_MarvinModel):
    entry_type: str
    """The entry type's slug."""
    name: str
    count: int


class EntryBulkDeletePreview(_MarvinModel):
    """What a bulk delete would remove now. Nothing is changed by asking."""

    mode: str
    total: int
    """Pass this back as `confirmTotal` to delete them."""
    by_type: dict[str, int]
    """Entry type slug → how many."""
    types: list[EntryBulkDeleteType]
    """The same counts with the types' names, most first."""
    text: str
    """The counts in words: "144 scenes, 600 beats and 770 speech lines"."""
    published: int
    """How many are on the site now (their going asks for a site rebuild)."""
    in_trash: int
    """How many are already in the Trash (only a permanent delete selects those)."""


class EntryBulkDeleteJob(_MarvinModel):
    """A bulk delete running in the background, or the workspace's last one since the server started."""

    state: Literal["running", "done", "failed"]
    mode: str
    description: str | None = None
    total: int
    done: int
    """Entries handled so far (it works in chunks of 500)."""
    started_at: str
    finished_at: str | None = None
    error: str | None = None
    result: dict | None = None
    """When done, as the service returns it: `deleted`, `by_type`, `types`, `text`, `published`, `chunks`, `seconds`."""
