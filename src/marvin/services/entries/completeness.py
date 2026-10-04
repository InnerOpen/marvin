"""Entry completeness contract.

One evaluator that answers "is this entry complete for its type?" from the type's
schema (required fields) + recipe (required assets, resource extracts, tags). It is the
single source the publish gate uses to BLOCK on missing-required, and that AI authoring
uses to WARN so compose/revise can self-correct. Non-required gaps are always warnings,
never blockers — so "required on anything" (field, asset role, resource type, tags) is
declared in the type and enforced here, uniformly, for AI / Chat / backend publishing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from marvin.schemas.platform.entry_type_recipe import EntryTypeRecipe
from marvin.schemas.platform.entry_type_schema import EntryTypeSchemaDefinition

logger = logging.getLogger(__name__)

# Values that count as "not filled in".
_EMPTY: tuple = (None, "", [], {})

# Links whose target is empty or a bare "#" — a stand-in for a URL nobody had (an AI draft once listed six
# works as `[Title](#)`). Published, they go nowhere. A real in-page anchor (`#section`) is a link and passes.
_PLACEHOLDER_MD_LINK = re.compile(r"\[([^\]]*)\]\(\s*#?\s*\)")
_PLACEHOLDER_HTML_LINK = re.compile(r"""<a\b[^>]*?\bhref\s*=\s*(?:"\s*#?\s*"|'\s*#?\s*')[^>]*>(.*?)</a\s*>""", re.IGNORECASE | re.DOTALL)
_HTML_TAG = re.compile(r"<[^>]+>")
# Field types whose text is rendered as formatted content with links. Plain text/textarea fields and raw
# `html` embeds (where `href="#"` can be a legitimate script hook) are left alone.
_LINKABLE_FIELD_TYPES = frozenset({"markdown", "richtext"})


@dataclass
class CompletenessIssue:
    kind: str  # "field" | "asset" | "resource" | "tag" | "link" | "expiry"
    key: str  # field key / asset role / resource type / "*"
    message: str
    blocking: bool


@dataclass
class CompletenessReport:
    blocking: list[CompletenessIssue] = field(default_factory=list)
    warnings: list[CompletenessIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when nothing required is missing (optional gaps don't count)."""
        return not self.blocking

    def blocking_messages(self) -> list[str]:
        return [i.message for i in self.blocking]

    def warning_messages(self) -> list[str]:
        return [i.message for i in self.warnings]


def parse_schema(schema_json: dict | None) -> EntryTypeSchemaDefinition | None:
    if not schema_json:
        return None
    try:
        return EntryTypeSchemaDefinition.model_validate(schema_json)
    except Exception as e:  # noqa: BLE001 — a malformed schema must not break publishing
        logger.warning("completeness: could not parse schema_json: %s", e)
        return None


def parse_recipe(recipe_json: dict | None) -> EntryTypeRecipe | None:
    if not recipe_json:
        return None
    try:
        return EntryTypeRecipe.model_validate(recipe_json)
    except Exception as e:  # noqa: BLE001
        logger.warning("completeness: could not parse recipe_json: %s", e)
        return None


def placeholder_link_texts(text: str | None) -> list[str]:
    """Texts of the placeholder links in markdown/HTML — `[text](#)`, `[text]()`, `href="#"`, `href=""`.
    In-page anchors (`#section`) are real links and are not reported."""
    if not text or not isinstance(text, str):
        return []
    found = [m.group(1).strip() for m in _PLACEHOLDER_MD_LINK.finditer(text)]
    found += [_HTML_TAG.sub("", m.group(1)).strip() for m in _PLACEHOLDER_HTML_LINK.finditer(text)]
    return [t or "(no text)" for t in found]


def linkable_text_fields(schema_json: dict | None) -> list[tuple[str, str]]:
    """`(key, label)` of the schema fields whose text renders as markup. Read from the raw schema, not
    the parsed one: a field type the parser doesn't know (e.g. a preserved `richtext`) still counts."""
    fields = (schema_json or {}).get("fields") if isinstance(schema_json, dict) else None
    out = []
    for f in fields or []:
        if isinstance(f, dict) and f.get("key") and f.get("type") in _LINKABLE_FIELD_TYPES:
            out.append((str(f["key"]), str(f.get("label") or f["key"])))
    return out


def evaluate_completeness(
    *,
    schema: EntryTypeSchemaDefinition | None,
    recipe: EntryTypeRecipe | None,
    data_json: dict | None,
    title: str | None = None,
    asset_roles: list[str] | None = None,
    resource_types: list[str] | None = None,
    tags: list[str] | None = None,
    link_fields: list[tuple[str, str]] | None = None,
    summary: str | None = None,
    description: str | None = None,
) -> CompletenessReport:
    """Evaluate an entry's state against its type's contract.

    All inputs are primitives so the same evaluator serves the publish gate (state from a
    persisted entry) and AI authoring (state from a freshly-composed draft). `link_fields`
    (from ``linkable_text_fields``), `summary` and `description` are scanned for placeholder
    links, which block like a missing required field.
    """
    data = data_json or {}
    asset_roles = asset_roles or []
    resource_types = resource_types or []
    tags = tags or []
    report = CompletenessReport()

    def add(kind: str, key: str, message: str, blocking: bool) -> None:
        (report.blocking if blocking else report.warnings).append(CompletenessIssue(kind=kind, key=key, message=message, blocking=blocking))

    # Title is the entry's identity — always required.
    if not (title or "").strip():
        add("field", "title", "Title is required.", True)

    # ── Fields (schema): required → block, optional-but-empty → warn ──────────
    if schema:
        for f in schema.fields:
            if getattr(f, "read_only", False):
                continue
            present = data.get(f.key) not in _EMPTY
            if getattr(f, "required", False):
                if not present:
                    add("field", f.key, f"Required field '{f.label}' is empty.", True)
            elif not present:
                add("field", f.key, f"Optional field '{f.label}' is empty.", False)

    # ── Assets (recipe): per-role minimums + overall minimum ─────────────────
    if recipe and recipe.assets:
        counts: dict[str, int] = {}
        for r in asset_roles:
            counts[r] = counts.get(r, 0) + 1
        total = len(asset_roles)

        overall_min = getattr(recipe.assets, "min", 0) or 0
        if total < overall_min:
            add("asset", "*", f"Needs at least {overall_min} image(s); has {total}.", True)

        for role in recipe.assets.roles or []:
            role_min = getattr(role, "min", 0) or 0
            need = role_min if role_min else (1 if getattr(role, "required", False) else 0)
            if need <= 0:
                continue
            have = counts.get(role.role, 0)
            if have < need:
                add("asset", role.role, f"Needs {need} '{role.role}' image(s); has {have}.", True)

    # ── Resources (recipe.extract): required resource types ──────────────────
    if recipe and recipe.resources:
        counts = {}
        for t in resource_types:
            counts[t] = counts.get(t, 0) + 1
        for ex in recipe.resources.extract or []:
            ex_min = getattr(ex, "min", 0) or 0
            need = ex_min if ex_min else (1 if getattr(ex, "required", False) else 0)
            if need <= 0:
                continue
            have = counts.get(ex.type, 0)
            if have < need:
                add("resource", ex.type, f"Needs {need} '{ex.type}' resource(s); has {have}.", True)

    # ── Tags (recipe.tags) ───────────────────────────────────────────────────
    tags_rule = getattr(recipe, "tags", None) if recipe else None
    if tags_rule:
        tag_min = getattr(tags_rule, "min", 0) or 0
        need = tag_min if tag_min else (1 if getattr(tags_rule, "required", False) else 0)
        if need > 0 and len(tags) < need:
            add("tag", "*", f"Needs at least {need} tag(s); has {len(tags)}.", True)

    # ── Placeholder links: a link to nowhere is never publish-ready ──────────
    scanned = [(key, label, data.get(key)) for key, label in (link_fields or [])]
    scanned += [("summary", "Summary", summary), ("description", "Description", description)]
    for key, label, value in scanned:
        texts = placeholder_link_texts(value)
        if texts:
            quoted = ", ".join(f"'{t}'" for t in texts)
            add("link", key, f"'{label}' has placeholder link(s) with no real URL: {quoted}. Add the URL or remove the link.", True)

    return report


def evaluate_entry(entry, entry_type, *, data_json=None, title=None, summary=None, description=None) -> CompletenessReport:
    """Evaluate a persisted ORM entry against its type. `data_json`/`title`/`summary`/`description`
    override the entry's stored values so a pending update can be projected before it's applied."""
    schema = parse_schema(getattr(entry_type, "schema_json", None)) if entry_type else None
    recipe = parse_recipe(getattr(entry_type, "recipe_json", None)) if entry_type else None
    asset_roles = [ea.role for ea in getattr(entry, "entry_assets", []) or [] if getattr(ea, "role", None)]
    resource_types = [r.resource_type for r in getattr(entry, "resources", []) or []]
    tags = list(getattr(entry, "tag_names", []) or [])
    return evaluate_completeness(
        schema=schema,
        recipe=recipe,
        data_json=data_json if data_json is not None else getattr(entry, "data_json", None),
        title=title if title is not None else getattr(entry, "title", None),
        asset_roles=asset_roles,
        resource_types=resource_types,
        tags=tags,
        link_fields=linkable_text_fields(getattr(entry_type, "schema_json", None)) if entry_type else None,
        summary=summary if summary is not None else getattr(entry, "summary", None),
        description=description if description is not None else getattr(entry, "description", None),
    )


def as_utc(value: datetime | str | None) -> datetime | None:
    """A timestamp as an aware UTC datetime. Naive values are UTC (how entries store them); an
    unparseable string is None — the repository rejects it, not this check."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def expiry_issue(expire_at: datetime | str | None, *, now: datetime | None = None) -> CompletenessIssue | None:
    """The publish blocker for an expiration date that has already passed, or None.

    Not part of the type's contract, but it blocks the same way: the Unpublish Expired Entries
    task archives a published entry whose expire_at <= now, so publishing it would only last until
    the next run. Shown in UTC — the server doesn't know the viewer's zone."""
    expires = as_utc(expire_at)
    if expires is None or expires > (now or datetime.now(UTC)):
        return None
    when = f"{expires:%b} {expires.day}, {expires:%Y %H:%M} UTC"
    return CompletenessIssue(
        kind="expiry",
        key="expire_at",
        message=f"The expiration date ({when}) has passed — clear it or set a later date.",
        blocking=True,
    )
