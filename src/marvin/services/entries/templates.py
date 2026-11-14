"""Entry templates: named presets on an entry type for making entries from pictures, and for filling entries already made.

A template (schemas/platform/entry_templates.py: EntryTemplate) lives on its entry type (``entry_types.templates_json``),
is edited in the type's settings and can come with the type in a package. It holds a title pattern, summary and
description text, values for the type's fields, tags, collections, the status a new entry starts in (inbox by default,
never approved or published), the role a picture is attached with (``asset_role``, e.g. featured) and the type's asset
field the picture goes in (``asset_field``, e.g. image).

Text may use ``{asset.name}``, ``{asset.filename}``, ``{n}`` (the entry's number in this batch, from 1) and ``{date}``
(today, YYYY-MM-DD). Any other ``{…}`` is refused when the template is saved (:func:`check_templates`), so a title never
keeps a stray variable.

One service behind every door (REST ``POST /entries/from-template`` and ``/entries/apply-template``, the workflow steps
``create_entries_from_template`` and ``apply_template``, the assistants' ``create_draft``):

- :func:`plan_from_assets` — one row per picture: ``create`` a new entry, or ``fill`` the entry of this type that already
  has that picture (so running it twice never makes a second entry), or ``skip`` with the reason. Changes nothing.
- :func:`plan_for_entries` — one row per existing entry: ``fill`` or ``skip``. Changes nothing.
- :func:`execute` — does what a plan says. Nothing is made while any row has an ``error``.

Filling sets only what is empty (a missing, null, "" or [] value) unless ``replace``; tags and collections are only
added; the status of an existing entry is never changed; entries that are approved, published, archived or in the
Trash are left alone (change those one at a time). A new entry gets the picture both ways the editor gives it: the
asset field holds its id, and it is attached (``entry_assets``) with the template's role at position 0.

Bulk-friendly: everything a plan needs is read in a fixed number of queries, whatever the number of rows, and each chunk
of CHUNK_SIZE rows is written in one transaction with set-based INSERTs. No ``entry_created`` / ``entry_updated`` per entry
(their listeners are what made a bulk write slow, see bulk_delete.py): smart-collection membership is worked out here, once
per chunk, and one ``entry_template_applied`` says what was made and filled. Permissions are the caller's to check (the
route and the workflow steps do), as for one entry.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

VARIABLES = ("asset.name", "asset.filename", "n", "date")
ASSET_VARIABLES = ("asset.name", "asset.filename")
_VARIABLE = re.compile(r"\{([^{}]*)\}")
MAX_ROWS = 200
"""At most this many pictures or entries at once."""
CHUNK_SIZE = 100
"""Rows per transaction."""
LEFT_ALONE = {
    "approved": "approved: change it on its own page",
    "published": "published: change it on its own page",
    "archived": "archived: change it on its own page",
    "trashed": "in the Trash",
}
ASSET_FIELD_TYPES = ("asset", "asset-list")


class TemplateError(ValueError):
    """Something wrong with a template or a request to use one, in words the person can act on."""


class TemplateNotFound(TemplateError):
    """No such entry type, template, picture or entry in this workspace."""


# ── Saving ─────────────────────────────────────────────────────────────────────


def variables_in(text) -> list[str]:
    """The ``{…}`` variables a text uses, in order."""
    return [m.strip() for m in _VARIABLE.findall(text)] if isinstance(text, str) else []


def _strings(value):
    """Every string in a field value (a string, or the strings in a list)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            if isinstance(v, str):
                yield v


def _schema_fields(schema_json: dict | None) -> tuple[dict[str, dict], Any]:
    """(raw fields by key, the parsed EntryTypeSchemaDefinition or None when the schema holds a type it doesn't know)."""
    from marvin.schemas.platform.entry_type_schema import EntryTypeSchemaDefinition

    raw = {f.get("key"): f for f in ((schema_json or {}).get("fields") or []) if isinstance(f, dict) and f.get("key")}
    try:
        parsed = EntryTypeSchemaDefinition.model_validate(schema_json or {}) if raw else None
    except Exception:  # noqa: BLE001 — an unsupported field type is kept (the repo only warns); values then go unchecked
        parsed = None
    return raw, parsed


def _check_value(parsed, key: str, value) -> str | None:
    """Why ``value`` doesn't fit the field ``key``, or None."""
    from marvin.services.content_validator import ContentValidationError, ContentValidator

    field_schema = parsed.get_field(key) if parsed is not None else None
    if field_schema is None or value is None:
        return None
    try:
        ContentValidator()._validate_field(field_schema, value)
    except ContentValidationError as e:
        return e.message
    return None


def check_templates(templates, schema_json: dict | None, presets=None) -> list[dict] | None:
    """The templates as they are stored (validated, defaults filled in), or None for none. Raises TemplateError naming the
    template and what is wrong: a slug used twice, an unknown variable, a field the type doesn't have or a value that
    doesn't fit it, an asset field that isn't an asset field, a picture preset the type doesn't have. Checked against
    ``schema_json`` and ``presets`` (the type's picture presets), as they will be stored with them."""
    from pydantic import ValidationError

    from marvin.schemas.platform.entry_templates import EntryTemplate
    from marvin.services.assets.picture_presets import preset_slugs

    if templates is None:
        return None
    if not isinstance(templates, list):
        raise TemplateError("templates must be a list")
    raw, parsed = _schema_fields(schema_json)
    out, seen = [], set()
    for i, item in enumerate(templates):
        if isinstance(item, EntryTemplate):
            item = item.model_dump()
        try:
            t = EntryTemplate.model_validate(item)
        except ValidationError as e:
            where = item.get("slug") or item.get("name") if isinstance(item, dict) else None
            first = e.errors()[0]
            raise TemplateError(f"template {where or i + 1}: {'.'.join(str(p) for p in first['loc'])}: {first['msg']}") from e
        name = f"template '{t.slug}'"
        if t.slug in seen:
            raise TemplateError(f"{name}: two templates have this slug")
        seen.add(t.slug)
        texts = [("title", t.title), ("summary", t.summary), ("description", t.entry_description)]
        texts += [(f"field {key}", s) for key, value in t.fields.items() for s in _strings(value)]
        for where, text in texts:
            unknown = [v for v in variables_in(text) if v not in VARIABLES]
            if unknown:
                raise TemplateError(
                    f"{name}: {where} uses {', '.join('{' + v + '}' for v in unknown)}, which is not a variable "
                    f"(use {', '.join('{' + v + '}' for v in VARIABLES)})"
                )
        for key, value in t.fields.items():
            if raw and key not in raw:
                raise TemplateError(f"{name}: '{key}' is not a field of this entry type (fields: {', '.join(raw)})")
            if not variables_in(value) and (why := _check_value(parsed, key, value)):
                raise TemplateError(f"{name}: field {key}: {why}")
        if t.asset_field:
            kind = (raw.get(t.asset_field) or {}).get("type")
            if kind not in ASSET_FIELD_TYPES:
                asset_fields = [k for k, f in raw.items() if f.get("type") in ASSET_FIELD_TYPES]
                said = f"(asset fields: {', '.join(asset_fields)})" if asset_fields else "(this type has no asset field)"
                raise TemplateError(f"{name}: the picture goes in '{t.asset_field}', which is not an asset field {said}")
            if t.asset_field in t.fields:
                raise TemplateError(f"{name}: field {t.asset_field} is where the picture goes; leave it out of the field values")
        if t.picture_preset and t.picture_preset not in (have := preset_slugs(presets)):
            raise TemplateError(
                f"{name}: there is no picture preset '{t.picture_preset}' on this type "
                f"({'presets: ' + ', '.join(sorted(have)) if have else 'it has none yet: add one in its settings'})"
            )
        out.append(t.model_dump(mode="json"))
    return out or None


def template_of(entry_type, slug: str):
    """The type's template ``slug`` (an EntryTemplate). TemplateNotFound names the ones there are."""
    from marvin.schemas.platform.entry_templates import EntryTemplate

    stored = [t for t in (entry_type.templates_json or []) if isinstance(t, dict)]
    for t in stored:
        if t.get("slug") == str(slug or "").strip():
            return EntryTemplate.model_validate(t)
    have = ", ".join(t.get("slug", "?") for t in stored) or "none yet: add one in the entry type's settings"
    raise TemplateNotFound(f"entry type '{entry_type.slug}' has no template '{slug}' (templates: {have})")


def resolve_type(session, group_id, ref):
    """The workspace's entry type by slug or id."""
    from marvin.db.models.platform.entry_types import EntryTypes

    ref = str(ref or "").strip()
    q = session.query(EntryTypes).filter(EntryTypes.group_id == group_id)
    try:
        row = q.filter(EntryTypes.id == uuid.UUID(ref)).first()
    except ValueError:
        row = q.filter(EntryTypes.slug == ref).first()
    if row is None:
        raise TemplateNotFound(f"no entry type '{ref}' in this workspace")
    return row


# ── Planning ───────────────────────────────────────────────────────────────────


@dataclass(eq=False)  # rows are told apart by identity (a dict of them, as _slugs keeps)
class Row:
    action: str  # create | fill | skip
    n: int
    title: str
    entry: Any = None
    asset: Any = None
    changes: dict = field(default_factory=dict)
    data: dict | None = None  # a new entry's data_json
    slug: str | None = None
    tags: list = field(default_factory=list)  # slugs to add
    collections: list = field(default_factory=list)  # Collections rows to join
    attach: bool = False
    position: int = 0
    note: str | None = None
    error: str | None = None
    # Taken when the plan is made, so doing it and answering never reload a row (a commit expires them all):
    entry_id: Any = None
    asset_id: Any = None
    picture: dict | None = None
    update: dict | None = None  # a fill's new column values
    # With a picture preset: the picture the entry gets (the treated one when made before, else the original until the
    # treated one is made in the background and takes its place), and the role it is attached with.
    treated: Any = None
    attach_id: Any = None
    attach_role: str | None = None
    treated_picture: dict | None = None
    pending: bool = False  # the treated picture is still to be made (or put in place) for this entry


def _settled(rows: list) -> list:
    """The rows with what doing and answering need taken from their ORM objects now."""
    for r in rows:
        r.entry_id = r.entry.id if r.entry is not None else None
        r.asset_id = r.asset.id if r.asset is not None else None
        r.picture = _picture(r.asset)
        r.collections = [(c.id, c.slug) for c in r.collections]
        if r.attach_id is None:
            r.attach_id = r.asset_id
        r.treated_picture = _picture(r.treated)
    return rows


@dataclass
class Plan:
    entry_type: Any
    template: Any
    rows: list
    replace: bool
    tag_names: dict  # slug -> name, for the tags a template adds
    existing_tags: dict  # slug -> Tags row
    preset: Any = None  # the template's picture preset (PicturePreset), when it has one
    recipe: list | None = None

    def summary(self) -> dict:
        counts = {a: sum(1 for r in self.rows if r.action == a) for a in ("create", "fill", "skip")}
        return {**counts, "todo": counts["create"] + counts["fill"], "errors": sum(1 for r in self.rows if r.error), "total": len(self.rows)}


def _empty(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _render(text, values: dict):
    """``text`` with its variables filled in from ``values``; raises KeyError(variable) when one has no value (a picture's
    name with no picture). Lists are rendered item by item; anything else comes back as it is."""
    if isinstance(text, list):
        return [_render(v, values) for v in text]
    if not isinstance(text, str):
        return text

    def one(m):
        name = m.group(1).strip()
        if values.get(name) is None:
            raise KeyError(name)
        return str(values[name])

    return _VARIABLE.sub(one, text)


def _values(asset, n: int, today: str) -> dict:
    return {
        "asset.name": (asset.name or asset.original_filename or asset.filename) if asset is not None else None,
        "asset.filename": (asset.original_filename or asset.filename) if asset is not None else None,
        "n": n,
        "date": today,
    }


UNNAMED_TAG = "Needs a name"
_CAMERA_NAME = re.compile(r"^(img|dsc|dscn|dscf|pxl|mvimg|photo|image|screenshot|scan|p)[\s_-]*\d", re.IGNORECASE)


def _bare(text: str) -> str:
    return re.sub(r"[\s_.-]+", " ", re.sub(r"\.[a-z0-9]{2,5}$", "", str(text or "").strip(), flags=re.IGNORECASE)).strip().lower()


def named_after_file(title: str, asset=None) -> bool:
    """True when ``title`` is a camera's or a scanner's file name (IMG_4491, "img 4491", DSC_0042.jpeg, PXL_2024…, or
    only digits and codes): nobody has named the picture yet. A file someone named ("Snowy Owl.jpg") is a name."""
    plain = _bare(title)
    return bool(plain) and (bool(_CAMERA_NAME.match(plain)) or not re.search(r"[a-z]{3,}", plain))


def _ids_and_slugs(refs) -> tuple[list, list]:
    ids, slugs = [], []
    for ref in refs:
        ref = str(ref or "").strip()
        if not ref:
            continue
        try:
            ids.append(uuid.UUID(ref))
        except ValueError:
            slugs.append(ref)
    return ids, slugs


def _dedupe(refs) -> list[str]:
    seen, out = set(), []
    for ref in refs or []:
        key = str(ref or "").strip()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _check_size(refs, what: str) -> list[str]:
    refs = _dedupe(refs)
    if not refs:
        raise TemplateError(f"no {what} given")
    if len(refs) > MAX_ROWS:
        raise TemplateError(f"{len(refs)} {what} is more than {MAX_ROWS} at once: do them in parts")
    return refs


def _collections(session, group_id, template) -> list:
    from marvin.db.models.platform.collections import Collections

    if not template.collections:
        return []
    rows = {c.slug: c for c in session.query(Collections).filter(Collections.group_id == group_id, Collections.slug.in_(template.collections))}
    missing = [s for s in template.collections if s not in rows]
    if missing:
        raise TemplateError(f"template '{template.slug}': no collection {', '.join(repr(s) for s in missing)} in this workspace")
    smart = [s for s in template.collections if rows[s].is_smart]
    if smart:
        raise TemplateError(
            f"template '{template.slug}': {', '.join(repr(s) for s in smart)} is a smart collection, which fills itself from its rules"
        )
    return [rows[s] for s in template.collections]


def _tags(session, group_id, template, extra: tuple = ()) -> tuple[dict, dict]:
    """(slug -> name for the template's tags and ``extra`` ones, slug -> the Tags rows that exist). Reads only: missing tags
    are made on execute."""
    from slugify import slugify

    from marvin.db.models.platform import Tags

    names = {}
    for raw in (*template.tags, *extra):
        slug = slugify(raw)
        if slug and slug not in names:
            names[slug] = raw.strip()
    existing = {t.slug: t for t in session.query(Tags).filter(Tags.group_id == group_id, Tags.slug.in_(list(names)))} if names else {}
    return names, existing


def _start(session, group_id, entry_type_ref, template_slug):
    from marvin.services.playbooks import PLAYBOOK_TYPE

    entry_type = resolve_type(session, group_id, entry_type_ref)
    if entry_type.slug == PLAYBOOK_TYPE:  # a Playbook has its own rules (names, publishing by admins): one at a time
        raise TemplateError("Playbooks are written one at a time, not from a template")
    template = template_of(entry_type, template_slug)
    _, parsed = _schema_fields(entry_type.schema_json)
    return entry_type, template, parsed, datetime.now(UTC).date().isoformat()


def _asset_value(entry_type, field_key: str, asset_id: str, current):
    """What the asset field holds with the picture in it (an id, or a list of ids with it first)."""
    kind = next((f.get("type") for f in ((entry_type.schema_json or {}).get("fields") or []) if f.get("key") == field_key), "asset")
    if kind == "asset-list":
        rest = [v for v in (current if isinstance(current, list) else []) if v != asset_id]
        return [asset_id, *rest]
    return asset_id


def _fill(
    row: Row,
    entry,
    entry_type,
    template,
    parsed,
    values: dict,
    replace: bool,
    *,
    attached: set,
    entry_tags: set,
    member_of: set,
    collections,
    versions: dict | None = None,
) -> Row:
    """Work out what filling ``entry`` with the template changes (only empty values unless ``replace``). ``versions``: a
    picture's versions (by its id) that count as holding it (a treated one)."""
    versions = versions or {}
    if entry.status in LEFT_ALONE:
        row.action, row.note = "skip", LEFT_ALONE[entry.status]
        return row
    left_out, changes, data = [], {}, dict(entry.data_json or {})

    def offer(label: str, text, current):
        if text is None or (not replace and not _empty(current)):
            return None
        try:
            new = _render(text, values)
        except KeyError:
            left_out.append(label)
            return None
        return new if new != current else None

    if replace and (new := offer("title", template.title, entry.title)):
        changes["title"] = row.title = new
    for label, text, current in (("summary", template.summary, entry.summary), ("description", template.entry_description, entry.description)):
        if (new := offer(label, text, current)) is not None:
            changes[label] = new
    fields = {}
    for key, value in template.fields.items():
        new = offer(key, value, data.get(key))
        if new is not None:
            if why := _check_value(parsed, key, new):
                row.error = f"{key}: {why}"
            fields[key] = new
    asset = row.asset
    # The picture, and (with a picture preset) its versions: an entry holding any of them holds this picture.
    family = {str(asset.id), *(str(v) for v in versions.get(asset.id, ()))} if asset is not None else set()
    put = str(row.attach_id or asset.id) if asset is not None else None
    if asset is not None and template.asset_field:
        current = data.get(template.asset_field)
        holds = current in family or (isinstance(current, list) and bool(current) and current[0] in family)
        if not holds and (replace or _empty(current)):
            fields[template.asset_field] = _asset_value(entry_type, template.asset_field, put, current)
    if fields:
        changes["fields"] = fields
    row.changes = changes
    row.attach = asset is not None and not any((entry.id, uuid.UUID(i)) in attached for i in family)
    row.tags = [s for s in row.tags if s not in entry_tags]
    row.collections = [c for c in collections if c.id not in member_of]
    if left_out:
        row.note = f"no picture to name it from: left out {', '.join(left_out)}"
    if not (changes or row.attach or row.tags or row.collections):
        row.action = "skip"
        row.note = row.note or "it already has everything this template sets"
    else:
        row.update = {key: changes[key] for key in ("title", "summary", "description") if key in changes}
        if fields:
            row.update["data_json"] = {**data, **fields}
    return row


def _new_entry(row: Row, entry_type, template, parsed, values: dict, overrides: dict | None = None) -> Row:
    """Work out a new entry from the template and its picture. ``overrides`` (title, summary, description, fields) are values
    the caller gave word for word (an assistant passing on what the person said): they win over the template's."""
    from marvin.services.content_validator import ContentValidationError, ContentValidator

    overrides = overrides or {}
    data = {key: _render(value, values) for key, value in template.fields.items()}
    if template.asset_field:
        data[template.asset_field] = _asset_value(entry_type, template.asset_field, str(row.attach_id or row.asset.id), None)
    data.update({k: v for k, v in (overrides.get("fields") or {}).items() if v is not None})
    row.title = str(overrides.get("title") or "").strip() or _render(template.title, values).strip() or values["asset.name"]
    row.data = data
    changes: dict = {"title": row.title, "status": template.status}
    for label, text in (("summary", template.summary), ("description", template.entry_description)):
        if overrides.get(label):
            changes[label] = str(overrides[label])
        elif text:
            changes[label] = _render(text, values)
    changes["fields"] = data
    row.changes = changes
    row.attach = True
    if parsed is not None:
        try:
            ContentValidator().validate_content(parsed, data)
        except ContentValidationError as e:
            row.error = f"{e.field_key}: {e.message}" if getattr(e, "field_key", None) else e.message
    return row


def plan_from_assets(
    session,
    group_id,
    entry_type_ref,
    template_slug,
    assets,
    *,
    replace: bool = False,
    overrides: dict | None = None,
    mark_unnamed: bool = False,
    titles: dict | None = None,
) -> Plan:
    """One row per picture (in the order given): ``create``, or ``fill`` for a picture that an entry of this type already
    has (in its asset field or attached), or ``skip``. ``overrides`` (title, summary, description, fields) win over the
    template's values on a new entry (see _new_entry); ``titles`` (by picture id) win over its title. ``mark_unnamed``: a
    new entry whose title is only a camera's file name (IMG_4491) gets the tag "Needs a name". Reads only.

    With a template that names a picture preset, each picture is first traced back to its original (a treated picture
    asked for stands for the one it was made from), an entry holding a version of it holds it, and the entry gets the
    treated picture (made before), or the original until the treated one is made in the background (see :func:`execute`)."""
    import sqlalchemy as sa

    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_assets import EntryAssets

    refs = _check_size(assets, "pictures")
    entry_type, template, parsed, today = _start(session, group_id, entry_type_ref, template_slug)
    preset, recipe = _preset(session, entry_type, template)
    ids, slugs = _ids_and_slugs(refs)
    conditions = [c for c in (Assets.id.in_(ids) if ids else None, Assets.slug.in_(slugs) if slugs else None) if c is not None]
    found = session.query(Assets).filter(Assets.group_id == group_id, sa.or_(*conditions)).all()
    by_ref = {**{str(a.id): a for a in found}, **{a.slug: a for a in found}}
    missing = [r for r in refs if r not in by_ref]
    if missing:
        raise TemplateNotFound(f"no picture {', '.join(repr(r) for r in missing[:5])}{' …' if len(missing) > 5 else ''} in this workspace")
    if preset is not None:
        from marvin.services.assets.picture_presets import originals

        root = originals(session, group_id, found)
        by_ref = {r: root[a.id] for r, a in by_ref.items()}
    pictures = []
    for r in refs:
        if by_ref[r] not in pictures:
            pictures.append(by_ref[r])
    asset_ids = [a.id for a in pictures]
    versions: dict = {}  # with a preset: each picture's versions (the treated ones among them), which an entry may hold instead
    if preset is not None:
        for vid, sid in session.query(Assets.id, Assets.source_asset_id).filter(Assets.group_id == group_id, Assets.source_asset_id.in_(asset_ids)):
            versions.setdefault(sid, set()).add(vid)
    stands_for = {v: sid for sid, vs in versions.items() for v in vs}
    held_ids = [*asset_ids, *stands_for]

    # The entries of this type that already have these pictures (or, with a preset, a version of one): attached, or in the asset field.
    has = sa.select(EntryAssets.entry_id).where(EntryAssets.asset_id.in_(held_ids))
    held = Entries.id.in_(has)
    if template.asset_field:
        held = sa.or_(held, Entries.data_json[template.asset_field].as_string().in_([str(i) for i in held_ids]))
    existing = (
        session.query(Entries)
        .filter(Entries.group_id == group_id, Entries.entry_type_id == entry_type.id, Entries.status != "trashed", held)
        .order_by(Entries.created_at, Entries.id)
        .all()
    )
    links = _links(session, [e.id for e in existing])
    owner: dict = {}
    for e in existing:
        in_field = (e.data_json or {}).get(template.asset_field) if template.asset_field else None
        for aid in asset_ids:
            if aid in owner:
                continue
            family = [aid, *versions.get(aid, ())]
            if any((e.id, i) in links["attached"] or in_field == str(i) or (isinstance(in_field, list) and str(i) in in_field) for i in family):
                owner[aid] = e
    collections = _collections(session, group_id, template)
    tag_names, existing_tags = _tags(session, group_id, template, (UNNAMED_TAG,) if mark_unnamed else ())
    unnamed_slug = next((slug for slug, name in tag_names.items() if name == UNNAMED_TAG), None) if mark_unnamed else None
    template_tags = [t for t in tag_names if t != unnamed_slug or UNNAMED_TAG in template.tags]
    treated = _treated_of(session, group_id, pictures, recipe) if preset is not None else {}
    rows, claimed = [], {}  # an existing entry gets one row: two of its pictures in one batch must not fill it twice
    for n, asset in enumerate(pictures, start=1):
        row = Row(action="create", n=n, title="", asset=asset, tags=list(template_tags), collections=list(collections))
        values = _values(asset, n, today)
        if preset is not None and asset.trashed_at is None:
            _with_treated(row, asset, template, treated.get(asset.id))
        if asset.trashed_at is not None:
            row.action, row.title, row.note = "skip", asset.name, "the picture is in the Trash"
        elif (entry := owner.get(asset.id)) is not None and entry.id in claimed:
            row.action, row.entry, row.title = "skip", entry, entry.title
            row.note = f"another picture of the same entry ('{claimed[entry.id]}') fills it"
        elif entry is not None:
            claimed[entry.id] = asset.name
            row.action, row.entry, row.title = "fill", entry, entry.title
            _fill(row, entry, entry_type, template, parsed, values, replace, collections=collections, versions=versions, **_held(links, entry.id))
            if preset is not None:
                _picture_pending(row, entry, links)
        else:
            given = str((titles or {}).get(str(asset.id)) or "").strip()
            _new_entry(row, entry_type, template, parsed, values, {**(overrides or {}), "title": given} if given else overrides)
            if unnamed_slug and named_after_file(row.title):
                row.tags.append(unnamed_slug)
                row.note = f"named after its file: give it a name (tagged {UNNAMED_TAG})"
        rows.append(row)
    _slugs(session, group_id, [r for r in rows if r.action == "create"])
    return Plan(
        entry_type=entry_type,
        template=template,
        rows=_settled(rows),
        replace=replace,
        tag_names=tag_names,
        existing_tags=existing_tags,
        preset=preset,
        recipe=recipe,
    )


def _preset(session, entry_type, template) -> tuple:
    """(the template's picture preset, its recipe), or (None, None) when it names none."""
    if not template.picture_preset:
        return None, None
    from marvin.services.assets import picture_presets

    try:
        preset = picture_presets.preset_of(entry_type, template.picture_preset)
        return preset, picture_presets._recipe(preset, session, entry_type.group_id)
    except picture_presets.PresetError as e:
        raise TemplateError(f"template '{template.slug}': {e}") from e


def _treated_of(session, group_id, pictures: list, recipe) -> dict:
    from marvin.services.assets.picture_presets import treated_of

    return {sid: t for sid, t in treated_of(session, group_id, [p for p in pictures if p.trashed_at is None], recipe).items() if t.trashed_at is None}


def _with_treated(row: Row, asset, template, treated) -> None:
    """A row of a template with a picture preset: the entry gets the treated picture (in the treated role), or the
    original until the treated one is made (``pending``)."""
    row.treated = treated
    row.attach_id = treated.id if treated is not None else asset.id
    row.attach_role = template.treated_role or "featured"
    row.pending = treated is None
    if treated is None:
        row.note = "its treated picture is made in the background and then takes the original's place"


def _picture_pending(row: Row, entry, links: dict) -> None:
    """With a picture preset: whether the entry still needs its treated picture made or put in place. An entry with
    nothing else to fill is then still a ``fill`` (of its picture); one left alone (approved, published, …) stays so."""
    if entry.status in LEFT_ALONE:
        row.pending = False
        return
    row.pending = not _shows(links, entry.id, row.treated, row.attach_role)
    if row.pending and row.action == "skip":
        row.action, row.note = "fill", "only its picture: the treated one takes the original's place"


def _shows(links: dict, entry_id, treated, role: str | None) -> bool:
    """True when the entry has the treated picture attached in ``role`` already."""
    return treated is not None and any(a[0] == treated.id and a[2] == role for a in links["by_entry"].get(entry_id, []))


def plan_for_entries(session, group_id, entry_type_ref, template_slug, entries, *, replace: bool = False) -> Plan:
    """One row per entry (in the order given): ``fill`` or ``skip``. An entry's picture (for {asset.name}, and to put in
    the asset field and attach) is the one in its asset field, else the one attached with the template's role, else its
    first attached one. Reads only."""
    import sqlalchemy as sa

    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.entries import Entries

    refs = _check_size(entries, "entries")
    entry_type, template, parsed, today = _start(session, group_id, entry_type_ref, template_slug)
    preset, recipe = _preset(session, entry_type, template)
    ids, slugs = _ids_and_slugs(refs)
    conditions = [c for c in (Entries.id.in_(ids) if ids else None, Entries.slug.in_(slugs) if slugs else None) if c is not None]
    found = session.query(Entries).filter(Entries.group_id == group_id, sa.or_(*conditions)).all()
    by_ref = {**{str(e.id): e for e in found}, **{e.slug: e for e in found}}
    missing = [r for r in refs if r not in by_ref]
    if missing:
        raise TemplateNotFound(f"no entry {', '.join(repr(r) for r in missing[:5])}{' …' if len(missing) > 5 else ''} in this workspace")
    chosen = []
    for r in refs:
        if by_ref[r] not in chosen:
            chosen.append(by_ref[r])
    links = _links(session, [e.id for e in chosen])
    picture_ids: dict = {}
    for e in chosen:
        in_field = (e.data_json or {}).get(template.asset_field) if template.asset_field else None
        in_field = in_field[0] if isinstance(in_field, list) and in_field else in_field
        attached = sorted(links["by_entry"].get(e.id, []), key=lambda a: (a[2] != template.asset_role, a[1]))
        pick = in_field if isinstance(in_field, str) and in_field else (str(attached[0][0]) if attached else None)
        try:
            picture_ids[e.id] = uuid.UUID(pick) if pick else None
        except ValueError:
            picture_ids[e.id] = None
    wanted = {i for i in picture_ids.values() if i}
    pictures = {a.id: a for a in session.query(Assets).filter(Assets.group_id == group_id, Assets.id.in_(wanted))} if wanted else {}
    versions: dict = {}
    treated: dict = {}
    if preset is not None and pictures:  # the entry's picture may be a treated one: its original names it and is treated
        from marvin.services.assets.picture_presets import originals

        root = originals(session, group_id, list(pictures.values()))
        for asset_id, original in root.items():
            if original.id != asset_id:
                versions.setdefault(original.id, set()).add(asset_id)
        pictures = {asset_id: root[asset_id] for asset_id in pictures}
        treated = _treated_of(session, group_id, list({a.id: a for a in pictures.values()}.values()), recipe)
        for original_id, t in treated.items():
            versions.setdefault(original_id, set()).add(t.id)
    collections = _collections(session, group_id, template)
    tag_names, existing_tags = _tags(session, group_id, template)
    rows = []
    for n, e in enumerate(chosen, start=1):
        asset = pictures.get(picture_ids.get(e.id))
        if asset is not None and asset.trashed_at is not None:
            asset = None
        row = Row(action="fill", n=n, title=e.title, entry=e, asset=asset, tags=list(tag_names), collections=list(collections))
        if preset is not None and asset is not None:
            _with_treated(row, asset, template, treated.get(asset.id))
        if e.entry_type_id != entry_type.id:
            row.action, row.note = "skip", f"not an entry of type {entry_type.name}"
        else:
            values = _values(asset, n, today)
            _fill(row, e, entry_type, template, parsed, values, replace, collections=collections, versions=versions, **_held(links, e.id))
            if preset is not None and asset is not None:
                _picture_pending(row, e, links)
        rows.append(row)
    return Plan(
        entry_type=entry_type,
        template=template,
        rows=_settled(rows),
        replace=replace,
        tag_names=tag_names,
        existing_tags=existing_tags,
        preset=preset,
        recipe=recipe,
    )


def _links(session, entry_ids: list) -> dict:
    """What these entries already have, in three queries: attachments, tags, collections."""
    from marvin.db.models.platform import Tags
    from marvin.db.models.platform.entry_assets import EntryAssets
    from marvin.db.models.platform.entry_collections import EntryCollections
    from marvin.db.models.platform.entry_tags import EntryTags

    out: dict = {"attached": set(), "by_entry": {}, "tags": {}, "collections": {}, "max_position": {}}
    if not entry_ids:
        return out
    for entry_id, asset_id, position, role in session.query(
        EntryAssets.entry_id, EntryAssets.asset_id, EntryAssets.position, EntryAssets.role
    ).filter(EntryAssets.entry_id.in_(entry_ids)):
        out["attached"].add((entry_id, asset_id))
        out["by_entry"].setdefault(entry_id, []).append((asset_id, position, role))
        out["max_position"][entry_id] = max(out["max_position"].get(entry_id, -1), position or 0)
    for entry_id, slug in (
        session.query(EntryTags.entry_id, Tags.slug).join(Tags, Tags.id == EntryTags.tag_id).filter(EntryTags.entry_id.in_(entry_ids))
    ):
        out["tags"].setdefault(entry_id, set()).add(slug)
    for entry_id, collection_id in session.query(EntryCollections.entry_id, EntryCollections.collection_id).filter(
        EntryCollections.entry_id.in_(entry_ids)
    ):
        out["collections"].setdefault(entry_id, set()).add(collection_id)
    return out


def _held(links: dict, entry_id) -> dict:
    return {
        "attached": links["attached"],
        "entry_tags": links["tags"].get(entry_id, set()),
        "member_of": links["collections"].get(entry_id, set()),
    }


def _slugs(session, group_id, rows: list) -> None:
    """A free slug for each new entry, in one query: as the repository does (-2, -3, … on a clash), new ones included."""
    import sqlalchemy as sa
    from slugify import slugify

    from marvin.db.models.platform.entries import Entries

    if not rows:
        return
    bases = {r: slugify(r.title) or "entry" for r in rows}
    wanted = sorted(set(bases.values()))
    like = [Entries.slug.like(f"{b}-%") for b in wanted]
    taken = {s for (s,) in session.query(Entries.slug).filter(Entries.group_id == group_id, sa.or_(Entries.slug.in_(wanted), *like))}
    for r in rows:
        slug, n = bases[r], 2
        while slug in taken:
            slug, n = f"{bases[r]}-{n}", n + 1
        taken.add(slug)
        r.slug = slug


# ── Answers ────────────────────────────────────────────────────────────────────


def _picture(asset) -> dict | None:
    if asset is None:
        return None
    try:
        from marvin.services.storage.provider_factory import asset_public_url

        url = asset_public_url(asset) if getattr(asset, "storage_key", None) else asset.public_url
    except Exception:  # noqa: BLE001 — a picture with no URL is still named
        url = getattr(asset, "public_url", None)
    return {"id": str(asset.id), "name": asset.name, "filename": asset.original_filename or asset.filename, "url": url}


def describe(plan: Plan, *, preview: bool = True, done: dict | None = None) -> dict:
    """The answer (EntryTemplateResult) for a plan, and after ``execute`` what it did."""
    from .bulk_delete import _plural

    s = plan.summary()
    rows = [
        {
            "action": r.action,
            "entry_id": str(r.entry_id) if r.entry_id is not None else ((done or {}).get("made") or {}).get(r.n),
            "title": r.title,
            "asset": r.picture,
            "changes": r.changes if r.action != "skip" else {},
            "tags": [plan.tag_names[t] for t in r.tags] if r.action != "skip" else [],
            "collections": [slug for _, slug in r.collections] if r.action != "skip" else [],
            "attach": r.attach and r.action != "skip",
            "note": r.note,
            "error": r.error,
            "treated": r.treated_picture if r.action != "skip" else None,
        }
        for r in plan.rows
    ]
    said = []
    if s["create"]:
        said.append(f"{'made' if done else 'make'} {s['create']} {_plural(plan.entry_type.name, s['create'])}")
    if s["fill"]:
        said.append(f"{'filled' if done else 'fill'} {s['fill']}")
    if s["skip"]:
        said.append(f"{'left' if done else 'leave'} {s['skip']}")
    text = ", ".join(said) or "nothing to do"
    if s["errors"] and not done:
        text += f" — {s['errors']} with a problem: nothing is made until it is fixed"
    pending = sum(1 for r in plan.rows if r.pending and r.action != "skip")
    if plan.preset is not None and pending:
        text += f"; {pending} picture{'s' if pending != 1 else ''} {'being' if done else 'to be'} treated with {plan.preset.name} in the background"
    out = {
        "preview": preview,
        "entry_type": plan.entry_type.slug,
        "template": plan.template.slug,
        **s,
        "rows": rows,
        "text": text,
        "picture_preset": plan.preset.slug if plan.preset is not None else None,
    }
    if done:
        out.update({k: done[k] for k in ("created", "updated", "entry_ids", "seconds")})
        out["treatment_job"] = done.get("treatment_job")
    return out


# ── Doing ──────────────────────────────────────────────────────────────────────


def execute(
    session,
    group_id,
    plan: Plan,
    *,
    actor_id=None,
    event_bus=None,
    integration_id: str = "entry_management",
    reaction_depth: int = 0,
    chunk_size: int = CHUNK_SIZE,
) -> dict:
    """Make and fill what ``plan`` says, CHUNK_SIZE rows per transaction. Refuses (TemplateError) while any row has an
    error. Returns the plan's answer with ``created``, ``updated``, ``entry_ids`` and ``seconds``."""
    from marvin.services.assets.scope import is_ask_file, move_to_library

    problems = [r for r in plan.rows if r.error]
    if problems:
        first = problems[0]
        raise TemplateError(f"{len(problems)} of {len(plan.rows)} cannot be done; first, '{first.title}': {first.error}. Nothing was changed.")
    started = time.monotonic()
    work = [r for r in plan.rows if r.action != "skip"]
    asks = [r.asset.id for r in work if r.attach and r.asset is not None and is_ask_file(r.asset)]  # before any commit
    if asks:  # an entry shows only library pictures: a chat attachment moves there, as attach_asset does
        move_to_library(session, group_id, asks, actor_id=actor_id, event_bus=event_bus, commit=False)
    tag_ids = _make_tags(session, group_id, plan)
    smart = _smart_collections(session, group_id)
    made: dict = {}
    created = updated = 0
    for start in range(0, len(work), max(1, chunk_size)):
        part = work[start : start + max(1, chunk_size)]
        made.update(_write_chunk(session, group_id, plan, part, tag_ids, actor_id))
        _sync_smart(session, group_id, [r.entry_id if r.entry_id is not None else made[r.n] for r in part], smart)
        session.commit()
        created += sum(1 for r in part if r.action == "create")
        updated += sum(1 for r in part if r.action == "fill")
    entry_ids = [str(r.entry_id if r.entry_id is not None else made[r.n]) for r in work]
    done = {
        "created": created,
        "updated": updated,
        "entry_ids": entry_ids,
        "seconds": round(time.monotonic() - started, 3),
        "made": {n: str(i) for n, i in made.items()},
        "treatment_job": _treat_later(group_id, plan, work, made, actor_id),
    }
    result = describe(plan, preview=False, done=done)
    if work:
        try:
            _emit(
                session, group_id, plan, result, actor_id=actor_id, event_bus=event_bus, integration_id=integration_id, reaction_depth=reaction_depth
            )
        except Exception as e:  # noqa: BLE001 — the entries are made; a lost event is logged
            logger.error(f"entry template: could not send entry_template_applied: {e}", exc_info=True)
    return result


def _treat_later(group_id, plan: Plan, work: list, made: dict, actor_id) -> str | None:
    """With a picture preset: start the background job that makes the treated pictures not made yet and puts each in
    its entry's place (the treated role and the asset field, where they still hold the original). Its id, or None."""
    if plan.preset is None:
        return None
    from marvin.services.assets import picture_presets

    items = [(r.asset_id, r.entry_id if r.entry_id is not None else made[r.n]) for r in work if r.pending and r.asset_id is not None]
    if not items:
        return None
    job = picture_presets.start_job(
        group_id,
        picture_presets.Work(
            entry_type_id=plan.entry_type.id,
            preset_slug=plan.preset.slug,
            preset_name=plan.preset.name,
            recipe=plan.recipe,
            items=items,
            role=plan.template.treated_role or "featured",
            asset_field=plan.template.asset_field,
        ),
        actor_id=actor_id,
    )
    return job["id"]


def _make_tags(session, group_id, plan: Plan) -> dict:
    """slug -> id for the template's tags, making the missing ones (one INSERT)."""
    import sqlalchemy as sa

    from marvin.db.models.platform import Tags

    wanted = {t for r in plan.rows if r.action != "skip" for t in r.tags}
    ids = {slug: t.id for slug, t in plan.existing_tags.items()}
    new = [{"id": uuid.uuid4(), "group_id": group_id, "name": plan.tag_names[s], "slug": s} for s in sorted(wanted) if s not in ids]
    if new:
        session.execute(sa.insert(Tags), new)
        ids.update({t["slug"]: t["id"] for t in new})
    return ids


def _write_chunk(session, group_id, plan: Plan, rows: list, tag_ids: dict, actor_id) -> dict:
    """Insert the new entries and their links, and apply the fills, set-based. Returns {row n: new entry id}. Does not commit."""
    import sqlalchemy as sa

    from marvin.db.models._model_utils.datetime import get_utc_now
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_assets import EntryAssets
    from marvin.db.models.platform.entry_collections import EntryCollections
    from marvin.db.models.platform.entry_tags import EntryTags

    now = get_utc_now()
    template, made, entries, assets, tags, members = plan.template, {}, [], [], [], []
    links = _links(session, [r.entry_id for r in rows if r.entry_id is not None])
    updates = []
    for r in rows:
        if r.action == "create":
            entry_id = uuid.uuid4()
            made[r.n] = entry_id
            entries.append(
                {
                    "id": entry_id,
                    "group_id": group_id,
                    "entry_type_id": plan.entry_type.id,
                    "title": r.title,
                    "slug": r.slug,
                    "summary": r.changes.get("summary"),
                    "description": r.changes.get("description"),
                    "data_json": r.data or {},
                    "status": template.status,
                    "created_by": actor_id,
                }
            )
            position = 0
        else:
            entry_id = r.entry_id
            if r.update:
                updates.append({"id": entry_id, **r.update, "update_at": now})
            position = links["max_position"].get(entry_id, -1) + 1
            if (entry_id, r.attach_id) in links["attached"]:
                r.attach = False  # attached since the plan was made
        if r.attach and r.attach_id is not None:
            role = r.attach_role or template.asset_role
            assets.append({"id": uuid.uuid4(), "entry_id": entry_id, "asset_id": r.attach_id, "role": role, "position": position})
        have_tags = links["tags"].get(entry_id, set())
        tags += [{"id": uuid.uuid4(), "entry_id": entry_id, "tag_id": tag_ids[s]} for s in r.tags if s not in have_tags]
        have = links["collections"].get(entry_id, set())
        members += [{"id": uuid.uuid4(), "entry_id": entry_id, "collection_id": c, "sort_order": 0} for c, _ in r.collections if c not in have]
    if entries:
        session.execute(sa.insert(Entries), entries)
    if updates:  # the fills: one UPDATE by primary key for them all
        session.execute(sa.update(Entries), updates)
    for model, values in ((EntryAssets, assets), (EntryTags, tags), (EntryCollections, members)):
        if values:
            session.execute(sa.insert(model), values)
    return made


def _smart_collections(session, group_id) -> list:
    from marvin.db.models.platform.collections import Collections

    return [c for c in session.query(Collections).filter_by(group_id=group_id, is_smart=True).all() if (c.target_type or "entry") == "entry"]


def _sync_smart(session, group_id, entry_ids: list, smart: list) -> None:
    """Smart-collection membership for these entries, as the listener keeps it for one: a query per smart collection,
    whatever the number of entries. Does not commit."""
    from sqlalchemy.orm import selectinload

    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_collections import EntryCollections
    from marvin.services.collections.smart_collections import matches_rules

    if not smart or not entry_ids:
        return
    rows = (
        session.query(Entries)
        .options(selectinload(Entries.entry_type), selectinload(Entries.tags))
        .filter(Entries.id.in_(entry_ids))
        .execution_options(populate_existing=True)
        .all()
    )
    for collection in smart:
        held = {
            i
            for (i,) in session.query(EntryCollections.entry_id).filter(
                EntryCollections.collection_id == collection.id, EntryCollections.entry_id.in_(entry_ids)
            )
        }
        want = {e.id for e in rows if matches_rules(e, collection.smart_rules, "entry")}
        add = [{"id": uuid.uuid4(), "entry_id": i, "collection_id": collection.id, "sort_order": 0} for i in want - held]
        if add:
            session.execute(EntryCollections.__table__.insert(), add)
        if gone := held - want:
            session.query(EntryCollections).filter(EntryCollections.collection_id == collection.id, EntryCollections.entry_id.in_(gone)).delete(
                synchronize_session=False
            )


def _emit(session, group_id, plan: Plan, result: dict, *, actor_id, event_bus, integration_id: str, reaction_depth: int) -> None:
    from marvin.db.models.groups import Groups
    from marvin.services.event_bus_service.event_types import EventEntryTemplateAppliedData, EventOperation, EventTypes

    if event_bus is None:
        from marvin.services.event_bus_service.event_bus_service import EventBusService

        event_bus = EventBusService(bg_tasks=None)
    group = session.get(Groups, group_id)
    event_bus.dispatch(
        integration_id=integration_id,
        group_id=group_id,
        event_type=EventTypes.entry_template_applied,
        document_data=EventEntryTemplateAppliedData(
            operation=EventOperation.create if result["created"] else EventOperation.update,
            workspace_id=group_id,
            workspace_name=getattr(group, "name", None),
            entry_type=plan.entry_type.slug,
            template=plan.template.slug,
            template_name=plan.template.name,
            created=result["created"],
            updated=result["updated"],
            entry_ids=result["entry_ids"],
        ),
        message=f"Template '{plan.template.name}': {result['text']}",
        user_id=actor_id,
        reaction_depth=reaction_depth,
    )
