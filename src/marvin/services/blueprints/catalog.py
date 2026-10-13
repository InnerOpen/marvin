"""The built-in blueprint catalog, and the registry providers extend.

Everything here is a *description*. Nothing is created until someone applies it — see `apply.py`.

The catalog exists because smart-collection rules are otherwise folklore: `published_within_days`
landed in 2026-09, `target_type: asset|resource` has always been supported and is effectively
unknown, and a blank entry-type schema is a blank page. Each blueprint below is one answer to
"what can this do?", written to be read.
"""

from marvin.schemas.platform.blueprints import Blueprint, BlueprintParameter

CATEGORY_EDITORIAL = "Editorial"
CATEGORY_MEDIA = "Media"

# Status buckets are not here on purpose: every workspace already gets locked system collections
# for inbox/drafts/needs-review/approved/archive (services/collections/system_collections.py), and
# a blueprint duplicating one of those slugs could never be applied.
#
# Core ships **collection examples only**, and only ones that work in any workspace on day one.
# Naming content is the workspace owner's business, so nothing here invents an entry type or
# hardcodes a slug — where a rule needs one, the blueprint asks for it as a parameter. Entry-type
# and scheduled-task blueprints exist in the schema for providers, which legitimately own the names
# of the content their integration requires.

_COLLECTIONS = [
    Blueprint(
        kind="collection",
        slug="recently-published",
        name="Recently published",
        description="Everything published in the last 30 days. The window rolls, so entries leave on their own.",
        category=CATEGORY_EDITORIAL,
        payload={
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
        description="Anything created in the last 7 days, whatever its status — what is in flight.",
        category=CATEGORY_EDITORIAL,
        payload={
            "description": "Created in the last 7 days",
            "icon": "🌱",
            "is_smart": True,
            "is_public": False,
            "smart_rules": {"created_within_days": 7, "match": "all"},
        },
    ),
    Blueprint(
        kind="collection",
        slug="all-{{entry_type}}",
        name="All {{entry_type}}",
        description="Everything of one type, whichever type you pick. Shows how an entry-type rule works.",
        category=CATEGORY_EDITORIAL,
        parameters=[
            BlueprintParameter(
                key="entry_type",
                label="Which type?",
                kind="entry_type",
                help="Pick one of this workspace's entry types — the collection then tracks it automatically.",
            )
        ],
        payload={
            "description": "Every entry of this type",
            "icon": "🗂️",
            "is_smart": True,
            "is_public": False,
            "smart_rules": {"entry_types": ["{{entry_type}}"], "match": "all"},
        },
    ),
    Blueprint(
        kind="collection",
        slug="published-{{entry_type}}",
        name="Published {{entry_type}}",
        description="One type, published only — two dimensions combined, which is how most useful rules are built.",
        category=CATEGORY_EDITORIAL,
        parameters=[BlueprintParameter(key="entry_type", label="Which type?", kind="entry_type")],
        payload={
            "description": "Published entries of this type",
            "icon": "📗",
            "is_smart": True,
            "is_public": False,
            "smart_rules": {"entry_types": ["{{entry_type}}"], "statuses": ["published"], "match": "all"},
        },
    ),
    Blueprint(
        kind="collection",
        slug="all-images",
        name="All images",
        description="An asset collection, not an entry one — collections can group assets and resources too.",
        category=CATEGORY_MEDIA,
        payload={
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
            "description": "SVG assets",
            "icon": "✒️",
            "is_smart": True,
            "is_public": False,
            "target_type": "asset",
            "smart_rules": {"mime_types": ["image/svg+xml"], "match": "all"},
        },
    ),
]

CORE_BLUEPRINTS: tuple[Blueprint, ...] = tuple(_COLLECTIONS)


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
