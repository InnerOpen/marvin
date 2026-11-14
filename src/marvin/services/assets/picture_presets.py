"""Picture presets: a named, ordered recipe of picture treatments, kept on an entry type beside its templates.

A preset (schemas/platform/picture_presets.py: PicturePreset) lists steps with the arguments a workflow's ``media`` step
takes: ``crop`` (aspect; focus center, subject or a fixed point "x,y"), ``resize`` (width, height, fit), ``grade`` (a
named grade and/or brightness, contrast, saturation, warmth, vignette) and ``convert`` (format, quality). It lives on the
entry type (``entry_types.picture_presets_json``), so every template of the type can name it (``picture_preset``), it is
checked with them when saved, and a package brings it with the type.

Applied to a picture it makes ONE new picture: the steps run one after the other on the decoded image and it is encoded
once at the end (no loss from saving between steps). As a workflow's media step does (services/automation/actions/
media.py, whose storing, naming and subject detection are reused here):

- the original is never modified; the treated picture is a new asset with ``origin: derived`` and ``source_asset_id``
  naming the original, so the library shows it as a version of it;
- it is named ``<original slug>--preset-<hash8>``, the hash over the steps (not the preset's name) and the original's
  checksum: the same steps on the same picture are made once and reused, and editing a preset makes new pictures;
- it sends no ``asset_uploaded`` (an "image added" workflow can't trigger itself);
- a treated picture is never treated again: one asked for is traced back to its original first.

Doing it for many pictures runs in the background (:func:`start_job`): one job at a time per workspace, the others wait
their turn, each in a thread of its own with its own session, CHUNK_SIZE pictures per transaction. The backend has one
worker; requests go on being answered meanwhile (the heavy image work is Pillow and numpy, which let go of the GIL). A
job lives in memory: after a restart run it again, and what was made is reused.

For entries, the treated picture takes the original's place: the role (featured by default) and the asset field, but
only where they still hold the original (a picture someone has since changed is left alone, and said so).
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

OP = "preset"
MAX_PICTURES = 200
"""At most this many pictures or entries at once."""
CHUNK_SIZE = 10
"""Pictures per transaction in the background."""
MAX_ERRORS_KEPT = 10
LINEAGE_DEPTH = 5
"""How many versions back an original is looked for."""
LEFT_ALONE = {
    "approved": "approved: change its picture on its own page",
    "published": "published: change its picture on its own page",
    "archived": "archived: change its picture on its own page",
    "trashed": "in the Trash",
}


class PresetError(ValueError):
    """Something wrong with a preset or a request to use one, in words the person can act on."""


class PresetNotFound(PresetError):
    """No such entry type, preset, picture or entry in this workspace."""


# ── Saving ─────────────────────────────────────────────────────────────────────


def check_presets(presets) -> list[dict] | None:
    """The presets as they are stored (validated), or None for none. Raises PresetError naming the preset and what is wrong."""
    from pydantic import ValidationError

    from marvin.schemas.platform.picture_presets import PicturePreset

    if presets is None:
        return None
    if not isinstance(presets, list):
        raise PresetError("picture presets must be a list")
    out, seen = [], set()
    for i, item in enumerate(presets):
        if isinstance(item, PicturePreset):
            item = item.model_dump()
        try:
            p = PicturePreset.model_validate(item)
        except ValidationError as e:
            where = (item.get("slug") or item.get("name")) if isinstance(item, dict) else None
            first = e.errors()[0]
            raise PresetError(f"picture preset {where or i + 1}: {'.'.join(str(x) for x in first['loc'])}: {first['msg']}") from e
        if p.slug in seen:
            raise PresetError(f"picture preset '{p.slug}': two presets have this slug")
        seen.add(p.slug)
        try:
            recipe_of(p)
        except PresetError as e:
            raise PresetError(f"picture preset '{p.slug}': {e}") from e
        out.append(p.model_dump(mode="json", exclude_none=True))
    return out or None


def preset_slugs(presets) -> set[str]:
    return {p.get("slug") for p in (presets or []) if isinstance(p, dict) and p.get("slug")}


def preset_of(entry_type, slug: str):
    """The type's preset ``slug`` (a PicturePreset). PresetNotFound names the ones there are."""
    from marvin.schemas.platform.picture_presets import PicturePreset

    stored = [p for p in (entry_type.picture_presets_json or []) if isinstance(p, dict)]
    for p in stored:
        if p.get("slug") == str(slug or "").strip():
            return PicturePreset.model_validate(p)
    have = ", ".join(p.get("slug", "?") for p in stored) or "none yet: add one in the entry type's settings"
    raise PresetNotFound(f"entry type '{entry_type.slug}' has no picture preset '{slug}' (presets: {have})")


# ── The recipe ─────────────────────────────────────────────────────────────────


def recipe_of(preset) -> list[dict]:
    """The preset's steps in canonical form, as the media step canonicalises its arguments (so "4x5" and "4:5", "1.10" and
    1.1, or a brightness of 1 and none, are one recipe and one picture). Raises PresetError for a step it can't do."""
    from marvin.services.automation.actions import media
    from marvin.services.automation.actions.base import AutomationActionError

    out = []
    for i, step in enumerate(preset.steps, start=1):
        raw = step.model_dump(exclude_none=True) if hasattr(step, "model_dump") else dict(step)
        op = raw.pop("op")
        try:
            if op == "crop":
                aspect = media.parse_aspect(raw.get("aspect"))
                if aspect is None:
                    raise AutomationActionError("crop needs an aspect like 1:1, 4:5 or 16:9")
                args = {"aspect": f"{aspect[0]}:{aspect[1]}", "focus": media.crop_focus(raw.get("focus"))}
            elif op == "resize":
                args = {k: int(raw[k]) for k in ("width", "height") if raw.get(k)}
                args["fit"] = raw.get("fit") or "inside"
            elif op == "grade":
                args = media.grade_settings(dict(raw))
                if (raw.get("preset") or "").strip():
                    args["preset"] = raw["preset"].strip()
            else:  # convert
                args = {}
            if raw.get("format"):
                args["format"] = raw["format"]
            if raw.get("quality"):
                args["quality"] = int(raw["quality"])
        except AutomationActionError as e:
            raise PresetError(f"step {i} ({op}): {e}") from e
        if op == "grade" and not args.get("preset") and not any(k in args for k in media.GRADE_SETTINGS):
            continue  # a grade left at "as it is": nothing to do, and nothing to tell apart
        out.append({"op": op, **args})
    if not out:
        raise PresetError("it does nothing: every step leaves the picture as it is")
    return out


def canonical(recipe: list[dict]) -> str:
    return json.dumps(recipe, sort_keys=True, separators=(",", ":"))


def treated_slug(src, recipe: list[dict]) -> str:
    """``<original slug>--preset-<hash8>``: the same steps on the same picture name the same asset."""
    from marvin.services.automation.actions.media import derivative_slug

    return derivative_slug(src, OP, {"steps": canonical(recipe)})


def steps_text(recipe: list[dict]) -> str:
    """The steps in words: "crop 1:1, grade brightness 1.1, webp"."""
    from marvin.services.automation.actions.media import _describe

    return ", ".join(_describe(s["op"], {k: v for k, v in s.items() if k != "op"}) for s in recipe)


def treat(data: bytes, recipe: list[dict], grades: dict, *, subject: list | None = None) -> bytes:
    """The picture after the recipe's steps: decoded once, each step on the image, encoded once (in the last format a
    step asked for, else the original's). ``grades`` are the workspace's named grades; ``subject`` the box (x, y, w, h
    in 0..1) a subject crop centres on (None: the centre)."""
    from marvin.services.ai.media import ops, transforms

    img, _ = transforms._load(data)
    fmt, quality = ops.format_of(data), None
    for step in recipe:
        op = step["op"]
        if op == "crop":
            focus = transforms.parse_focus(step["focus"])
            if focus == "subject":
                focus = (subject[0] + subject[2] / 2, subject[1] + subject[3] / 2) if subject else (0.5, 0.5)
            elif not isinstance(focus, tuple):
                focus = (0.5, 0.5)
            img = img.crop(transforms.aspect_box(img.size, media_aspect(step["aspect"]), focus))
        elif op == "resize":
            img = ops.resize_image(img, width=step.get("width"), height=step.get("height"), fit=step.get("fit") or "inside")
        elif op == "grade":
            params = dict(grades.get(step["preset"]) or {}) if step.get("preset") else {}
            params.update({k: step[k] for k in transforms.GRADE_SETTINGS if k in step})
            img = transforms.grade_image(img, params)
        fmt = step.get("format") or fmt
        quality = step.get("quality") or quality
    return ops.encode(img, fmt, quality)


def media_aspect(text: str) -> tuple[int, int]:
    from marvin.services.automation.actions.media import parse_aspect

    return parse_aspect(text)


def _uses_subject(recipe: list[dict]) -> bool:
    return any(s["op"] == "crop" and s.get("focus") == "subject" for s in recipe)


def _centred(recipe: list[dict]) -> list[dict]:
    """The recipe with its subject crops centred (no vision model, or no subject found): what was really made."""
    return [{**s, "focus": "center"} if s["op"] == "crop" and s.get("focus") == "subject" else s for s in recipe]


# ── Planning ───────────────────────────────────────────────────────────────────


@dataclass(eq=False)
class Row:
    action: str  # create | reuse | skip
    source: Any = None  # the original (Assets row)
    slug: str | None = None
    treated: Any = None  # the treated Assets row, when made before
    entry: Any = None
    note: str | None = None
    place: bool = False
    # Taken when the plan is made, so doing it never reloads a row (a commit expires them all):
    source_id: Any = None
    entry_id: Any = None
    picture: dict | None = None
    treated_picture: dict | None = None


@dataclass
class Plan:
    entry_type: Any
    preset: Any
    recipe: list
    rows: list
    role: str | None = None  # entries: the role the treated picture takes
    asset_field: str | None = None  # entries: the asset field it goes in
    grades: dict = field(default_factory=dict)

    def summary(self) -> dict:
        counts = {a: sum(1 for r in self.rows if r.action == a) for a in ("create", "reuse", "skip")}
        return {**counts, "todo": counts["create"] + counts["reuse"], "total": len(self.rows)}


def resolve(session, group_id, entry_type_ref, preset_slug=None, template_slug=None):
    """(entry type, preset, the template or None) for a request naming a preset, or a template that has one."""
    from marvin.services.entries.templates import TemplateError, resolve_type, template_of

    try:
        entry_type = resolve_type(session, group_id, entry_type_ref)
    except TemplateError as e:
        raise PresetNotFound(str(e)) from e
    template = None
    if template_slug:
        try:
            template = template_of(entry_type, template_slug)
        except TemplateError as e:
            raise PresetNotFound(str(e)) from e
        if not preset_slug:
            if not template.picture_preset:
                raise PresetError(f"template '{template.slug}' has no picture preset: choose one in its settings, or name a preset")
            preset_slug = template.picture_preset
    return entry_type, preset_of(entry_type, preset_slug), template


def _check_size(refs, what: str) -> list[str]:
    from marvin.services.entries.templates import _dedupe

    refs = _dedupe(refs)
    if not refs:
        raise PresetError(f"no {what} given")
    if len(refs) > MAX_PICTURES:
        raise PresetError(f"at most {MAX_PICTURES} {what} at once ({len(refs)} given): do them in parts")
    return refs


def originals(session, group_id, assets: list) -> dict:
    """{asset id: its original} for these Assets rows: a version made by Marvin (origin derived) is traced back through
    ``source_asset_id`` to the picture it was made from, one query per generation (LINEAGE_DEPTH at most); any other
    picture is its own original. A treated picture is so never treated again."""
    from marvin.db.models.platform.assets import Assets

    found = {a.id: a for a in assets}
    root = {a.id: a for a in assets}
    for _ in range(LINEAGE_DEPTH):
        up = {aid: a.source_asset_id for aid, a in root.items() if a.origin == "derived" and a.source_asset_id is not None}
        wanted = {s for s in up.values() if s not in found}
        if wanted:
            for a in session.query(Assets).filter(Assets.group_id == group_id, Assets.id.in_(wanted)):
                found[a.id] = a
        moved = False
        for aid, src in up.items():
            if src in found:
                root[aid] = found[src]
                moved = True
        if not moved:
            break
    return root


def treated_of(session, group_id, sources: list, recipe: list) -> dict:
    """{original id: its treated picture} for those already made with this recipe (one query; a subject crop made
    centred, for want of a vision model or a subject, counts)."""
    from marvin.db.models.platform.assets import Assets

    if not sources:
        return {}
    wanted = {treated_slug(s, recipe): s.id for s in sources}
    if _uses_subject(recipe):
        wanted.update({treated_slug(s, _centred(recipe)): s.id for s in sources})
    out = {}
    for a in session.query(Assets).filter(Assets.group_id == group_id, Assets.slug.in_(list(wanted))):
        out.setdefault(wanted[a.slug], a)
    return out


def _picture(asset) -> dict | None:
    from marvin.services.entries.templates import _picture as picture

    p = picture(asset)
    return {k: p[k] for k in ("id", "name", "url")} if p else None


def _rows_for(session, group_id, recipe, pairs: list) -> list:
    """One row per (source, entry or None) pair: create, reuse, or skip (in the Trash)."""
    sources = [s for s, _ in pairs if s is not None and s.trashed_at is None]
    made = treated_of(session, group_id, sources, recipe)
    rows = []
    for src, entry in pairs:
        row = Row(action="create", source=src, entry=entry)
        if src is None:
            row.action, row.note = "skip", "it has no picture"
        elif src.trashed_at is not None:
            row.action, row.note = "skip", "the picture is in the Trash"
        else:
            row.slug = treated_slug(src, recipe)
            if (t := made.get(src.id)) is not None:
                if t.trashed_at is not None:
                    row.action, row.note = "skip", f"its treated picture ({t.slug}) is in the Trash: restore it, or delete it to make it again"
                else:
                    row.action, row.treated, row.slug = "reuse", t, t.slug
        rows.append(row)
    return rows


def plan_for_assets(session, group_id, entry_type_ref, assets, *, preset=None, template=None) -> Plan:
    """One row per picture (in the order given, each original once): ``create`` its treated version, ``reuse`` the one
    made before, or ``skip``. Reads only."""
    import sqlalchemy as sa

    from marvin.db.models.platform.assets import Assets
    from marvin.services.ai.media import transforms
    from marvin.services.entries.templates import _ids_and_slugs

    refs = _check_size(assets, "pictures")
    entry_type, p, _ = resolve(session, group_id, entry_type_ref, preset, template)
    recipe = _recipe(p, session, group_id)
    ids, slugs = _ids_and_slugs(refs)
    conditions = [c for c in (Assets.id.in_(ids) if ids else None, Assets.slug.in_(slugs) if slugs else None) if c is not None]
    found = session.query(Assets).filter(Assets.group_id == group_id, sa.or_(*conditions)).all()
    by_ref = {**{str(a.id): a for a in found}, **{a.slug: a for a in found}}
    missing = [r for r in refs if r not in by_ref]
    if missing:
        raise PresetNotFound(f"no picture {', '.join(repr(r) for r in missing[:5])}{' …' if len(missing) > 5 else ''} in this workspace")
    root = originals(session, group_id, found)
    pairs, seen = [], set()
    for r in refs:
        src = root[by_ref[r].id]
        if src.id in seen:
            continue
        seen.add(src.id)
        pairs.append((src, None))
    rows = _rows_for(session, group_id, recipe, pairs)
    for row in rows:
        if row.action != "skip" and not transforms.can_transform(row.source.mime_type):
            row.action, row.note = "skip", f"not a picture Marvin can treat ({row.source.mime_type or 'unknown type'}: jpeg, png or webp)"
    return _settled(Plan(entry_type=entry_type, preset=p, recipe=recipe, rows=rows))


def plan_for_entries(session, group_id, entry_type_ref, entries, *, preset=None, template=None, role=None) -> Plan:
    """One row per entry (in the order given): its picture (the one in the template's asset field, else the one attached
    in the role, else its first attached one; a treated one traced back to its original) treated, and the treated one put
    in its place. ``skip`` for an entry with no picture, of another type, or approved, published, archived or in the
    Trash (change those one at a time). Reads only."""
    import sqlalchemy as sa

    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.entries import Entries
    from marvin.services.ai.media import transforms
    from marvin.services.entries.templates import _ids_and_slugs, _links

    refs = _check_size(entries, "entries")
    entry_type, p, tmpl = resolve(session, group_id, entry_type_ref, preset, template)
    recipe = _recipe(p, session, group_id)
    role = (role or (tmpl.treated_role if tmpl is not None else None) or "featured").strip()
    asset_field = tmpl.asset_field if tmpl is not None else None
    ids, slugs = _ids_and_slugs(refs)
    conditions = [c for c in (Entries.id.in_(ids) if ids else None, Entries.slug.in_(slugs) if slugs else None) if c is not None]
    found = session.query(Entries).filter(Entries.group_id == group_id, sa.or_(*conditions)).all()
    by_ref = {**{str(e.id): e for e in found}, **{e.slug: e for e in found}}
    missing = [r for r in refs if r not in by_ref]
    if missing:
        raise PresetNotFound(f"no entry {', '.join(repr(r) for r in missing[:5])}{' …' if len(missing) > 5 else ''} in this workspace")
    chosen = []
    for r in refs:
        if by_ref[r] not in chosen:
            chosen.append(by_ref[r])
    links = _links(session, [e.id for e in chosen])
    picks: dict = {}
    for e in chosen:
        in_field = (e.data_json or {}).get(asset_field) if asset_field else None
        in_field = in_field[0] if isinstance(in_field, list) and in_field else in_field
        attached = sorted(links["by_entry"].get(e.id, []), key=lambda a: (a[2] != role, a[1]))
        pick = in_field if isinstance(in_field, str) and in_field else (str(attached[0][0]) if attached else None)
        try:
            picks[e.id] = uuid.UUID(pick) if pick else None
        except ValueError:
            picks[e.id] = None
    wanted = {i for i in picks.values() if i}
    pictures = list(session.query(Assets).filter(Assets.group_id == group_id, Assets.id.in_(wanted))) if wanted else []
    root = originals(session, group_id, pictures)
    pairs = []
    for e in chosen:
        src = root.get(picks.get(e.id))
        pairs.append((src, e))
    rows = _rows_for(session, group_id, recipe, pairs)
    for row in rows:
        e = row.entry
        if e.entry_type_id != entry_type.id:
            row.action, row.note = "skip", f"not an entry of type {entry_type.name}"
        elif e.status in LEFT_ALONE:
            row.action, row.note = "skip", LEFT_ALONE[e.status]
        elif row.action != "skip" and not transforms.can_transform(row.source.mime_type):
            row.action, row.note = "skip", f"its picture is not one Marvin can treat ({row.source.mime_type or 'unknown type'})"
        if row.action != "skip":
            treated_id = row.treated.id if row.treated is not None else None
            held = {a[0] for a in links["by_entry"].get(e.id, []) if a[2] == role}
            row.place = treated_id is None or treated_id not in held
    return _settled(Plan(entry_type=entry_type, preset=p, recipe=recipe, rows=rows, role=role, asset_field=asset_field))


def _recipe(preset, session=None, group_id=None) -> list:
    """The preset's recipe, its named grades checked against the workspace's (a misspelt one would otherwise grade nothing)."""
    try:
        recipe = recipe_of(preset)
    except PresetError as e:
        raise PresetError(f"picture preset '{preset.slug}': {e}") from e
    named = [s["preset"] for s in recipe if s["op"] == "grade" and s.get("preset")]
    if named and session is not None:
        from marvin.services.ai.media.enrichment import grade_presets

        known = grade_presets(session, group_id)
        if unknown := [n for n in named if n not in known]:
            raise PresetError(f"picture preset '{preset.slug}': no grade '{unknown[0]}' (grades: {', '.join(sorted(known))})")
    return recipe


def _settled(plan: Plan) -> Plan:
    for r in plan.rows:
        r.source_id = r.source.id if r.source is not None else None
        r.entry_id = r.entry.id if r.entry is not None else None
        r.picture = _picture(r.source)
        r.treated_picture = _picture(r.treated)
    return plan


# ── Answers ────────────────────────────────────────────────────────────────────


def describe(plan: Plan, *, preview: bool = True, job: dict | None = None) -> dict:
    """The answer (ApplyPresetResult) for a plan."""
    s = plan.summary()
    rows = [
        {
            "action": r.action,
            "source": r.picture,
            "slug": r.slug,
            "treated": r.treated_picture,
            "entry_id": str(r.entry_id) if r.entry_id is not None else None,
            "entry_title": r.entry.title if r.entry is not None else None,
            "place": r.place and r.action != "skip",
            "note": r.note,
        }
        for r in plan.rows
    ]
    said = []
    if s["create"]:
        said.append(f"treat {s['create']} picture{'s' if s['create'] != 1 else ''}")
    if s["reuse"]:
        said.append(f"reuse {s['reuse']} treated before")
    if s["skip"]:
        said.append(f"leave {s['skip']}")
    placed = sum(1 for r in plan.rows if r.place and r.action != "skip")
    if placed:
        said.append(f"put the treated picture in {placed} entr{'y' if placed == 1 else 'ies'} as {plan.role}")
    return {
        "preview": preview,
        "entry_type": plan.entry_type.slug,
        "preset": plan.preset.slug,
        "preset_name": plan.preset.name,
        "steps": steps_text(plan.recipe),
        **s,
        "rows": rows,
        "text": ", ".join(said) or "nothing to do",
        "job": job,
    }


# ── Doing ──────────────────────────────────────────────────────────────────────


@dataclass
class Work:
    """What a job does, without ORM rows (it runs in another thread, with its own session): treat each source, and for
    an entry put the treated picture in ``role`` and ``asset_field`` where they still hold the original."""

    entry_type_id: Any
    preset_slug: str
    preset_name: str
    recipe: list
    items: list  # [(source id, entry id or None)]
    role: str | None = None
    asset_field: str | None = None


def work_of(plan: Plan) -> Work:
    items = [(r.source_id, r.entry_id if r.place else None) for r in plan.rows if r.action != "skip"]
    return Work(
        entry_type_id=plan.entry_type.id,
        preset_slug=plan.preset.slug,
        preset_name=plan.preset.name,
        recipe=plan.recipe,
        items=items,
        role=plan.role,
        asset_field=plan.asset_field,
    )


def execute(session, group_id, work: Work, *, actor_id=None, progress=None, chunk_size: int = CHUNK_SIZE) -> dict:
    """Treat every picture of ``work`` (reusing what was made before) and put each treated one in its entry's place,
    ``chunk_size`` pictures per transaction. A picture that fails is counted and named, and the rest go on. Returns
    {made, reused, placed, failed, errors, treated: {original id: treated id}, seconds}."""
    from marvin.db.models.platform.assets import Assets
    from marvin.services.ai.media.enrichment import grade_presets

    started = time.monotonic()
    grades = grade_presets(session, group_id)
    out = {"made": 0, "reused": 0, "placed": 0, "failed": 0, "errors": [], "treated": {}, "notes": []}
    context: dict = {"_step": {"step_id": f"preset:{work.preset_slug}"}}
    detector = None
    if _uses_subject(work.recipe):
        from marvin.services.automation.actions.media import _subject_detector

        detector, _ = _subject_detector(session, group_id)
    done = 0
    step = max(1, chunk_size)
    for start in range(0, len(work.items), step):
        part = work.items[start : start + step]
        sources = {a.id: a for a in session.query(Assets).filter(Assets.group_id == group_id, Assets.id.in_({s for s, _ in part}))}
        placing = []
        for source_id, entry_id in part:
            src = sources.get(source_id)
            try:
                if src is None or src.trashed_at is not None:
                    raise PresetError("the picture is gone or in the Trash")
                treated, reused = _treated(session, group_id, src, work, grades, detector, context, actor_id=actor_id)
                out["reused" if reused else "made"] += 1
                out["treated"][str(src.id)] = str(treated.id)
                if entry_id is not None:
                    placing.append((entry_id, src.id, treated.id))
            except Exception as e:  # noqa: BLE001 — one bad picture never stops the others
                session.rollback()
                out["failed"] += 1
                if len(out["errors"]) < MAX_ERRORS_KEPT:
                    out["errors"].append(f"{getattr(src, 'name', None) or source_id}: {e}")
                logger.warning(f"picture preset {work.preset_slug}: {source_id}: {e}")
        if placing:
            placed, notes = _place(session, work, placing)
            out["placed"] += placed
            out["notes"] += notes
        session.commit()
        done += len(part)
        if progress is not None:
            progress(done, out)
        time.sleep(0)  # let the request threads in between chunks
    out["seconds"] = round(time.monotonic() - started, 3)
    return out


def _treated(session, group_id, src, work: Work, grades: dict, detector, context: dict, *, actor_id):
    """(the treated picture of ``src``, reused?): the one made before with these steps, else made now."""
    from marvin.db.models.platform.assets import Assets
    from marvin.services.automation.actions import media

    recipe = work.recipe
    subject = None
    if _uses_subject(recipe) and detector is None:
        recipe = _centred(recipe)
    slug = treated_slug(src, recipe)
    existing = session.query(Assets).filter(Assets.group_id == group_id, Assets.slug == slug).first()
    if existing is None and _uses_subject(recipe):  # made centred before because no subject was found: not asked again
        centred = session.query(Assets).filter(Assets.group_id == group_id, Assets.slug == treated_slug(src, _centred(recipe))).first()
        existing = centred if centred is not None and (centred.metadata_json or {}).get("focus_note") else None
    if existing is not None:
        if existing.trashed_at is not None:
            raise PresetError(f"its treated picture ({slug}) is in the Trash: restore it, or delete it to make it again")
        return existing, True
    data = media._read_bytes(session, group_id, src)
    if _uses_subject(recipe):
        subject = media._detect_subject(session, group_id, detector, src, data, user_id=actor_id)
        if not subject:
            recipe = _centred(recipe)
            slug = treated_slug(src, recipe)
            again = session.query(Assets).filter(Assets.group_id == group_id, Assets.slug == slug).first()
            if again is not None and again.trashed_at is None:
                return again, True
    produced = treat(data, recipe, grades, subject=subject)
    extra = {"picture_preset": work.preset_slug, "preset_name": work.preset_name, "preset_steps": steps_text(recipe)}
    if recipe is not work.recipe:
        extra["focus_note"] = "no subject found (or no vision model): cropped from the centre"
    # Stored, metadata and all, in one write that commits: a later picture's failure (a rollback) can't undo it.
    asset = media._store(session, group_id, OP, {"preset": work.preset_slug}, src, produced, slug, context, user_id=actor_id, extra=extra)
    return asset, False


def _place(session, work: Work, placing: list) -> tuple[int, list]:
    """Put each treated picture in its entry's place, set-based: the link in ``work.role`` that holds the original is
    moved to the treated picture (or the treated one is attached in the role when the entry has none there), and the
    asset field is switched where it holds the original (or is empty). Where the role or the field now holds another
    picture (changed by someone since), it is left alone and said so. Does not commit."""
    import sqlalchemy as sa

    from marvin.db.models._model_utils.datetime import get_utc_now
    from marvin.db.models.platform.entries import Entries
    from marvin.db.models.platform.entry_assets import EntryAssets

    entry_ids = {e for e, _, _ in placing}
    entries = {e.id: e for e in session.query(Entries).filter(Entries.id.in_(entry_ids))}
    links: dict = {}
    for link in session.query(EntryAssets).filter(EntryAssets.entry_id.in_(entry_ids)):
        links.setdefault(link.entry_id, []).append(link)
    role, field_key = work.role or "featured", work.asset_field
    placed, notes, now = 0, [], get_utc_now()
    for entry_id, original_id, treated_id in placing:
        entry = entries.get(entry_id)
        if entry is None or entry.status in LEFT_ALONE:
            notes.append(f"{getattr(entry, 'title', entry_id)}: left as it is ({LEFT_ALONE.get(getattr(entry, 'status', ''), 'gone')})")
            continue
        mine = links.get(entry_id, [])
        by_asset = {link.asset_id: link for link in mine}  # an asset is attached to an entry once (one role)
        treated_link, original_link = by_asset.get(treated_id), by_asset.get(original_id)
        in_role = [link for link in mine if link.role == role]
        changed = False
        if treated_link is not None and treated_link.role == role:
            if original_link is not None and original_link.role == role:  # both in the role: the original's link goes
                session.delete(original_link)
                changed = True
        elif treated_link is not None:
            notes.append(f"{entry.title}: the treated picture is attached already, as {treated_link.role}; left as it is")
        elif original_link is not None and original_link.role == role:
            original_link.asset_id = treated_id
            changed = True
        elif not in_role:
            session.add(EntryAssets(id=uuid.uuid4(), entry_id=entry_id, asset_id=treated_id, role=role, position=0))
            changed = True
        else:
            notes.append(f"{entry.title}: its {role} picture was changed since; left as it is")
        if field_key:
            data = dict(entry.data_json or {})
            current = data.get(field_key)
            if current in (None, "", []) or current == str(original_id):
                data[field_key] = str(treated_id)
            elif isinstance(current, list) and current and current[0] == str(original_id):
                data[field_key] = [str(treated_id), *[v for v in current[1:] if v != str(treated_id)]]
            if data != (entry.data_json or {}):
                session.execute(sa.update(Entries).where(Entries.id == entry_id).values(data_json=data, update_at=now))
                changed = True
        placed += 1 if changed else 0
    session.flush()
    return placed, notes


# ── In the background ──────────────────────────────────────────────────────────

_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_queues: dict[str, deque] = {}
_running: set[str] = set()
KEEP_JOBS = 50


def job_status(group_id, job_id: str) -> dict | None:
    """A job of this workspace (queued, running, or finished since the server started), or None."""
    with _lock:
        job = _jobs.get(str(job_id))
        if job is None or job["group_id"] != str(group_id):
            return None
        return _public(job)


def _public(job: dict) -> dict:
    out = {k: v for k, v in job.items() if k not in ("group_id", "work", "actor_id", "notes")}
    out["treated"] = dict(job["treated"])
    out["errors"] = list(job["errors"])
    return out


def start_job(group_id, work: Work, *, actor_id=None) -> dict:
    """Queue ``work`` for the workspace and return the job as it starts (``queued`` behind another, or ``running``)."""
    key = str(group_id)
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "group_id": key,
        "state": "queued",
        "preset": work.preset_slug,
        "total": len(work.items),
        "done": 0,
        "made": 0,
        "reused": 0,
        "placed": 0,
        "failed": 0,
        "errors": [],
        "treated": {},
        "started_at": None,
        "finished_at": None,
        "seconds": None,
        "text": f"waiting to treat {len(work.items)} picture{'s' if len(work.items) != 1 else ''}",
        "work": work,
        "actor_id": actor_id,
    }
    with _lock:
        _jobs[job_id] = job
        _forget_old()
        _queues.setdefault(key, deque()).append(job_id)
        starting = key not in _running
        if starting:
            _running.add(key)
        snapshot = _public(job)
    if starting:
        threading.Thread(target=_drain, args=(group_id,), name=f"picture-preset-{key[:8]}", daemon=True).start()
    return snapshot


def _forget_old() -> None:
    finished = [j for j in _jobs.values() if j["state"] in ("done", "failed")]
    for j in finished[: max(0, len(finished) - KEEP_JOBS)]:
        _jobs.pop(j["id"], None)


def _drain(group_id) -> None:
    """Run the workspace's queued jobs one after another, then stop."""
    key = str(group_id)
    while True:
        with _lock:
            queue = _queues.get(key)
            if not queue:
                _running.discard(key)
                _queues.pop(key, None)
                return
            job = _jobs[queue.popleft()]
        _run_job(group_id, job)


def _set(job: dict, **fields) -> None:
    with _lock:
        job.update(fields)


def _run_job(group_id, job: dict) -> None:
    from marvin.db.db_setup import session_context

    work: Work = job["work"]
    _set(job, state="running", started_at=datetime.now(UTC).isoformat(), text=f"treating {job['total']} pictures")

    def progress(done: int, so_far: dict) -> None:
        _set(
            job,
            done=done,
            made=so_far["made"],
            reused=so_far["reused"],
            placed=so_far["placed"],
            failed=so_far["failed"],
            errors=list(so_far["errors"]),
            treated=dict(so_far["treated"]),
            text=f"treated {done} of {job['total']}",
        )

    try:
        with session_context() as session:
            result = execute(session, group_id, work, actor_id=job["actor_id"], progress=progress)
        text = f"treated {result['made'] + result['reused']} of {job['total']} ({result['made']} made, {result['reused']} reused)"
        if result["placed"]:
            text += f", {result['placed']} entr{'y' if result['placed'] == 1 else 'ies'} now show the treated picture"
        if result["failed"]:
            text += f"; {result['failed']} failed"
        _set(
            job,
            state="done",
            done=job["total"],
            made=result["made"],
            reused=result["reused"],
            placed=result["placed"],
            failed=result["failed"],
            errors=list(result["errors"]) + list(result["notes"])[:MAX_ERRORS_KEPT],
            treated=dict(result["treated"]),
            seconds=result["seconds"],
            finished_at=datetime.now(UTC).isoformat(),
            text=text,
        )
        logger.info(f"picture preset {work.preset_slug}: {text} in {result['seconds']} s, workspace {group_id}")
    except Exception as e:  # noqa: BLE001 — a background job must never take the worker down
        logger.error(f"picture preset {work.preset_slug} failed in workspace {group_id}: {e}", exc_info=True)
        _set(job, state="failed", errors=[str(e)], finished_at=datetime.now(UTC).isoformat(), text=f"stopped: {e}")


def wait(job_id: str, timeout: float = 30.0) -> dict | None:
    """Block until a job is finished (tests, and a workflow step that must hand the treated pictures on); None when unknown."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _lock:
            job = _jobs.get(job_id)
            if job is None:
                return None
            if job["state"] in ("done", "failed"):
                return _public(job)
        time.sleep(0.05)
    with _lock:
        job = _jobs.get(job_id)
        return _public(job) if job else None
