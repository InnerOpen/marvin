"""The built-in blueprint catalog, and the registry providers extend.

Everything here is a *description*. Nothing is created until someone applies it — see `apply.py`.

The catalog exists because smart-collection rules are otherwise folklore: `published_within_days`
landed in 2026-09, `target_type: asset|resource` has always been supported and is effectively
unknown, and a blank entry-type schema is a blank page. Each blueprint below is one answer to
"what can this do?", written to be read.
"""

from marvin.schemas.platform.blueprints import Blueprint

CATEGORY_EDITORIAL = "Editorial"
CATEGORY_HOUSEKEEPING = "Housekeeping"
CATEGORY_MEDIA = "Media"
CATEGORY_CONTENT_MODELS = "Content models"

# --- collections -------------------------------------------------------------------------------

_COLLECTIONS = [
    Blueprint(
        kind="collection",
        slug="recently-published",
        name="Recently published",
        description="Everything published in the last 30 days. The window rolls, so entries leave on their own.",
        category=CATEGORY_EDITORIAL,
        payload={
            "name": "Recently published",
            "description": "Published in the last 30 days",
            "icon": "🗞️",
            "is_smart": True,
            "is_public": False,
            "smart_rules": {"statuses": ["published"], "published_within_days": 30, "match": "all"},
        },
    ),
    Blueprint(
        kind="collection",
        slug="new-this-week",
        name="New this week",
        description="Anything created in the last 7 days, whatever its status — a look at what is in flight.",
        category=CATEGORY_EDITORIAL,
        payload={
            "name": "New this week",
            "description": "Created in the last 7 days",
            "icon": "🌱",
            "is_smart": True,
            "is_public": False,
            "smart_rules": {"created_within_days": 7, "match": "all"},
        },
    ),
    Blueprint(
        kind="collection",
        slug="stale-drafts",
        name="Stale drafts",
        description="Drafts nobody has touched lately. Pair with a status filter to find work that stalled.",
        category=CATEGORY_HOUSEKEEPING,
        payload={
            "name": "Stale drafts",
            "description": "Drafts, excluding anything created in the last 30 days",
            "icon": "🧊",
            "is_smart": True,
            "is_public": False,
            # No "older than" dimension yet: this collects all drafts, and the name sets the
            # expectation. A negated window is the obvious next dimension if this proves useful.
            "smart_rules": {"statuses": ["draft"], "match": "all"},
        },
    ),
    Blueprint(
        kind="collection",
        slug="all-images",
        name="All images",
        description="An asset collection, not an entry one — collections can group assets and resources too.",
        category=CATEGORY_MEDIA,
        payload={
            "name": "All images",
            "description": "Every image asset in the workspace",
            "icon": "🖼️",
            "is_smart": True,
            "is_public": False,
            "target_type": "asset",
            "smart_rules": {"asset_types": ["image"], "match": "all"},
        },
    ),
    Blueprint(
        kind="collection",
        slug="vector-artwork",
        name="Vector artwork",
        description="SVG only, matched on exact MIME type — finer than the image/document buckets.",
        category=CATEGORY_MEDIA,
        payload={
            "name": "Vector artwork",
            "description": "SVG assets",
            "icon": "✒️",
            "is_smart": True,
            "is_public": False,
            "target_type": "asset",
            "smart_rules": {"mime_types": ["image/svg+xml"], "match": "all"},
        },
    ),
]

# --- entry types -------------------------------------------------------------------------------
# A blank schema is the hardest part of a new entry type; these are starting points, not doctrine.

_ENTRY_TYPES = [
    Blueprint(
        kind="entry_type",
        slug="changelog-entry",
        name="Changelog entry",
        description="Dated, versioned release notes: version, date, kind of change, the notes themselves.",
        category=CATEGORY_CONTENT_MODELS,
        payload={
            "name": "Changelog entry",
            "icon": "📋",
            "description": "One released change",
            "schema_json": {
                "fields": [
                    {"key": "version", "label": "Version", "type": "text", "required": True, "placeholder": "1.4.0"},
                    {"key": "released_on", "label": "Released on", "type": "text"},
                    {"key": "change_kind", "label": "Kind", "type": "text", "placeholder": "added / fixed / removed"},
                    {"key": "notes", "label": "Notes", "type": "markdown", "required": True},
                ]
            },
        },
    ),
    Blueprint(
        kind="entry_type",
        slug="faq",
        name="FAQ",
        description="A question, its answer, and a category to group by.",
        category=CATEGORY_CONTENT_MODELS,
        payload={
            "name": "FAQ",
            "icon": "❓",
            "description": "One question and its answer",
            "schema_json": {
                "fields": [
                    {"key": "question", "label": "Question", "type": "text", "required": True},
                    {"key": "answer", "label": "Answer", "type": "markdown", "required": True},
                    {"key": "category", "label": "Category", "type": "text"},
                ]
            },
        },
    ),
    Blueprint(
        kind="entry_type",
        slug="testimonial",
        name="Testimonial",
        description="A quote, who said it, and what they do — the shape every site eventually needs.",
        category=CATEGORY_CONTENT_MODELS,
        payload={
            "name": "Testimonial",
            "icon": "💬",
            "description": "Something a customer said",
            "schema_json": {
                "fields": [
                    {"key": "quote", "label": "Quote", "type": "textarea", "required": True},
                    {"key": "attribution", "label": "Said by", "type": "text", "required": True},
                    {"key": "role", "label": "Role or company", "type": "text"},
                ]
            },
        },
    ),
]

CORE_BLUEPRINTS: tuple[Blueprint, ...] = tuple(_COLLECTIONS + _ENTRY_TYPES)


def list_blueprints(*, kind: str | None = None, category: str | None = None, source: str | None = None) -> list[Blueprint]:
    """The catalog: core blueprints plus whatever installed providers contribute.

    Provider blueprints are appended, not merged — a provider cannot redefine a core blueprint,
    because its own are filed under its own `source` and `category`.
    """
    items = list(CORE_BLUEPRINTS) + _provider_blueprints()
    if kind:
        items = [b for b in items if b.kind == kind]
    if category:
        items = [b for b in items if b.category == category]
    if source:
        items = [b for b in items if b.source == source]
    return items


def get_blueprint(slug: str, *, source: str | None = None) -> Blueprint | None:
    """One blueprint by slug. Slugs are unique per source; pass `source` to disambiguate."""
    for blueprint in list_blueprints(source=source):
        if blueprint.slug == slug:
            return blueprint
    return None


def categories() -> list[str]:
    """Every category currently represented, core first then providers', each once."""
    seen: list[str] = []
    for blueprint in list_blueprints():
        if blueprint.category not in seen:
            seen.append(blueprint.category)
    return seen


def _provider_blueprints() -> list[Blueprint]:
    """Blueprints declared by installed integration providers.

    Integrations are an optional feature and a provider declares `content` only if it has any, so
    this returns nothing rather than failing when the SDK is absent or a provider predates the
    contract. A malformed declaration is skipped with a warning — one bad provider must not empty
    the catalog.
    """
    from marvin.core.root_logger import get_logger
    from marvin.services.integrations import INTEGRATIONS_AVAILABLE

    if not INTEGRATIONS_AVAILABLE:
        return []

    from marvin.services.integrations import list_providers

    logger = get_logger(__name__)
    found: list[Blueprint] = []
    for provider in list_providers():
        for raw in getattr(provider, "content", ()) or ():
            try:
                data = raw if isinstance(raw, dict) else raw.__dict__
                found.append(Blueprint(**{**data, "source": provider.slug, "category": data.get("category") or provider.name}))
            except Exception as e:  # noqa: BLE001 — one bad provider must not break the catalog
                logger.warning("provider %s declared an unusable blueprint: %s", getattr(provider, "slug", "?"), e)
    return found
