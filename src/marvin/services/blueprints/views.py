"""Views: a package's ways of looking at an entry, shipped as plain data.

A view draws one entry and its children in a shape the edit page cannot: today the one kind is ``timeline``, which lays a story out as
time, the way a video editor does. Core knows nothing about stories, beats or lines: the package declares which entry type is the *spine*
(the items laid end to end, a story's beats), which fields carry each item's seconds, picture and status, and which child types are drawn
in *lanes* under it (the speech lines of a beat, the sounds placed inside one). Nothing in a view is code: it names entry types and fields by
slug, and the page reads the entries through the entries API like anyone else.

A timeline definition::

    {
      "kind": "timeline", "title": "Timeline", "entry_type": "story",
      "spine": {
        "entry_type": "beat", "of": "story", "order": "number",
        "group": {"entry_type": "chapter", "field": "chapter", "order": "number"},
        "picture": "still", "text": "picture", "status": "status",
        "seconds": {"hold": "hold_seconds", "lead": "lead_seconds", "gap": "gap_seconds", "tail": "tail_seconds",
                    "defaults": {"hold": 4, "lead": 0.3, "gap": 0.25, "tail": 0.35}}
      },
      "lanes": [
        {"id": "lines", "title": "Lines", "entry_type": "speech-line", "of": "story", "in": "beat", "order": "number",
         "text": "text", "who": "speaker", "audio": "audio", "seconds": "duration_seconds", "estimate_from": "text", "status": "status"},
        {"id": "sounds", "title": "Sounds", "entry_type": "sound", "placed": {"field": "sounds", "ref": "sound", "at": "at"},
         "audio": "audio", "seconds": "duration_seconds", "volume": "volume", "status": "status"},
        {"id": "ambience", "title": "Ambience", "entry_type": "sound", "audio": "audio", "seconds": "duration_seconds", "loop": "loop",
         "volume": "volume",
         "bed": {"via": "scene", "entry_type": "scene", "field": "ambience", "volume": "ambience_volume", "item_volume": "ambience_volume"}},
        {"id": "music", "title": "Music", "entry_type": "sound", "bed": {"field": "music"}, "audio": "audio", "seconds": "duration_seconds",
         "loop": "loop", "volume": "volume"}
      ],
      "actions": [{"label": "Guided setup", "wizard": "narrate-a-story"}]
    }

- ``entry_type`` is the type the view is of (a story); the page opens as ``/workspace/views/<slug>?entry=<slug or id>``.
- ``spine``: the items laid out in time. ``of`` is the field on each that holds the entry's slug, ``order`` the field they sort by,
  ``group`` an optional type the items are grouped under (chapters: ``field`` on an item holds the group's slug). ``picture`` is an asset
  field, ``text`` a text shown when there is no picture, ``status`` a status field drawn as a dot. ``seconds`` names the fields that time an
  item: ``hold`` is how long an item with nothing in its lanes lasts; ``lead``, ``gap`` and ``tail`` are the silences around and between the
  pieces of a lane that has ``seconds``; ``defaults`` fill in when a field is empty.
- A ``lane`` is a child type drawn under the spine, in one of four shapes. ``in`` names the field that holds the spine item's slug (a line
  belongs to a beat; ``of`` is then required and scopes the lane's entries to the view's entry). ``placed`` says the spine item lists them:
  ``field`` is a JSON list on the item whose objects name a lane entry in ``ref`` and its offset in seconds in ``at`` (the entries come by
  those slugs, so a library sound shared by stories is found; ``of`` is optional). ``bed`` is a sound that runs under a stretch: ``field``
  names the lane entry's slug on the view's entry itself (a story's music, one block under everything), or on each spine item, or, with
  ``via`` and ``entry_type``, on the entry a spine item's ``via`` field names (a beat's scene names its ambience); consecutive items with the
  same bed merge into one block. ``bed.volume`` is the level field on that entry and ``bed.item_volume`` an override on the spine item.
  ``audio`` is an asset field, ``seconds`` a duration field, ``volume`` (0 to 1) and ``loop`` the lane entry's own level and whether it
  repeats, and ``estimate_from`` a text field whose length stands in for the seconds while there is no recording (drawn hatched). On a bed
  that runs under the whole story, ``bed.item_volume`` *replaces* the level while that spine item plays (a beat that takes the music to
  silence) and shows as steps in the block. ``cover`` is a video laid over each item's picture: ``field`` is the asset field, ``blend`` and
  ``opacity`` its settings; the item's own field wins, then the entry ``via`` (with ``entry_type``) names, then the view's entry itself, and a
  blend of ``none`` at one of them switches the overlay off from there up.
- ``actions`` are buttons on the page: each starts a ``wizard`` or a ``workflow`` the same package brings.
"""

from __future__ import annotations

import re
from typing import Any

VIEW_KINDS = ("timeline",)
MAX_LANES = 6
MAX_ACTIONS = 6
SECONDS_KEYS = ("hold", "lead", "gap", "tail")

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_ID = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")


def _field(spec: dict, key: str, label: str, *, required: bool = False) -> str | None:
    value = spec.get(key)
    if value is None:
        return f"{label} needs {key}, a field key" if required else None
    return None if isinstance(value, str) and _NAME.match(value) else f"{label}: {key} must be a field key"


def _fields(spec: dict, keys: tuple[str, ...], label: str) -> str | None:
    return next((problem for key in keys if (problem := _field(spec, key, label))), None)


def _slug(spec: dict, key: str, label: str) -> str | None:
    value = spec.get(key)
    return None if isinstance(value, str) and _SLUG.match(value) else f"{label} needs {key}, an entry type slug"


def payload_problem(payload: dict, slug: str) -> str | None:
    """Why this view payload is not acceptable (None when it is). Pure: it looks at the definition alone, never at the workspace, so a package
    installs even before its entry types exist; a missing type is the view page's message to give."""
    label = f"view {slug!r}"
    if payload.get("kind") not in VIEW_KINDS:
        return f"{label} has kind {payload.get('kind')!r}; it must be one of {', '.join(VIEW_KINDS)}"
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        return f"{label} needs a title"
    if problem := _slug(payload, "entry_type", label):
        return problem
    spine = payload.get("spine")
    if not isinstance(spine, dict):
        return f"{label} needs a spine: the entry type laid out in time, {{entry_type, of, ...}}"
    if problem := _check_spine(spine, f"{label} spine"):
        return problem
    lanes = payload.get("lanes", [])
    if not isinstance(lanes, list) or len(lanes) > MAX_LANES:
        return f"{label}: lanes is a list of at most {MAX_LANES}"
    seen: set[str] = set()
    for n, lane in enumerate(lanes, 1):
        if not isinstance(lane, dict):
            return f"lane {n} of {label} is not an object"
        lid = lane.get("id")
        if not isinstance(lid, str) or not _ID.match(lid):
            return f"lane {n} of {label} needs an id of lowercase letters, digits, - or _"
        if lid in seen:
            return f"lane {lid!r} of {label} is used twice"
        seen.add(lid)
        if problem := _check_lane(lane, f"lane {lid!r} of {label}"):
            return problem
    return _check_actions(payload.get("actions"), label)


def _check_spine(spine: dict, label: str) -> str | None:
    if (problem := _slug(spine, "entry_type", label)) or (problem := _field(spine, "of", label, required=True)):
        return problem
    if problem := _fields(spine, ("order", "picture", "text", "status", "title"), label):
        return problem
    group = spine.get("group")
    if group is not None:
        if not isinstance(group, dict):
            return f"{label}: group is {{entry_type, field, order?}}"
        if (problem := _slug(group, "entry_type", f"{label} group")) or (problem := _field(group, "field", f"{label} group", required=True)):
            return problem
        if problem := _field(group, "order", f"{label} group"):
            return problem
    seconds = spine.get("seconds")
    if seconds is None:
        return None
    if not isinstance(seconds, dict):
        return f"{label}: seconds names the fields that time an item, {{hold, lead, gap, tail, defaults}}"
    if problem := _fields(seconds, SECONDS_KEYS, f"{label} seconds"):
        return problem
    defaults = seconds.get("defaults", {})
    if not isinstance(defaults, dict) or any(k not in SECONDS_KEYS for k in defaults):
        return f"{label}: seconds.defaults holds numbers for {', '.join(SECONDS_KEYS)}"
    bad = next((k for k, v in defaults.items() if isinstance(v, bool) or not isinstance(v, int | float) or v < 0), None)
    return None if bad is None else f"{label}: seconds.defaults.{bad} must be a number of seconds, 0 or more"


def _check_lane(lane: dict, label: str) -> str | None:
    if not isinstance(lane.get("title"), str) or not lane["title"].strip():
        return f"{label} needs a title"
    if problem := _slug(lane, "entry_type", label):
        return problem
    shapes = [k for k in ("in", "placed", "bed", "cover") if lane.get(k) is not None]
    if len(shapes) != 1:
        return (
            f"{label}: one of `in` (the field holding the spine item's slug), `placed` ({{field, ref, at}}), "
            "`bed` ({field, via?}) or `cover` ({field, via?})"
        )
    if problem := _field(lane, "of", label, required=shapes == ["in"]):
        return problem
    if shapes == ["in"] and (problem := _field(lane, "in", label)):
        return problem
    if (placed := lane.get("placed")) is not None:
        if not isinstance(placed, dict):
            return f"{label}: placed is {{field, ref, at}}"
        for key in ("field", "ref", "at"):
            if problem := _field(placed, key, f"{label} placed", required=True):
                return problem
    if (bed := lane.get("bed")) is not None:
        if not isinstance(bed, dict):
            return f"{label}: bed is {{field, via?, entry_type?, volume?, item_volume?}}"
        if problem := _field(bed, "field", f"{label} bed", required=True):
            return problem
        if problem := _fields(bed, ("via", "volume", "item_volume", "muffled"), f"{label} bed"):
            return problem
        if (bed.get("via") is None) != (bed.get("entry_type") is None):
            return f"{label}: bed.via (the spine item's field naming the entry) and bed.entry_type go together"
        if bed.get("entry_type") is not None and (problem := _slug(bed, "entry_type", f"{label} bed")):
            return problem
    if (cover := lane.get("cover")) is not None:
        if problem := _check_cover(cover, label):
            return problem
    if (opens := lane.get("open")) is not None:
        if not isinstance(opens, dict):
            return f"{label}: open is {{wizard}}, the guided setup a piece opens on instead of its own page"
        if problem := _slug(opens, "wizard", f"{label} open"):
            return problem
    return _fields(lane, ("order", "text", "who", "audio", "seconds", "volume", "loop", "estimate_from", "status"), label)


def _check_cover(cover: Any, label: str) -> str | None:
    if not isinstance(cover, dict):
        return f"{label}: cover is {{field, blend?, opacity?, via?, entry_type?}}"
    if problem := _field(cover, "field", f"{label} cover", required=True):
        return problem
    if problem := _fields(cover, ("blend", "opacity", "via"), f"{label} cover"):
        return problem
    if (cover.get("via") is None) != (cover.get("entry_type") is None):
        return f"{label}: cover.via (the spine item's field naming the entry) and cover.entry_type go together"
    if cover.get("entry_type") is not None:
        return _slug(cover, "entry_type", f"{label} cover")
    return None


def _check_actions(actions: Any, label: str) -> str | None:
    if actions is None:
        return None
    if not isinstance(actions, list) or len(actions) > MAX_ACTIONS:
        return f"{label}: actions is a list of at most {MAX_ACTIONS} buttons, each {{label, wizard}} or {{label, workflow}}"
    for action in actions:
        if not isinstance(action, dict) or not isinstance(action.get("label"), str) or not action["label"].strip():
            return f"{label}: each action needs a label"
        targets = [k for k in ("wizard", "workflow") if action.get(k) is not None]
        if len(targets) != 1 or not isinstance(action[targets[0]], str) or not _SLUG.match(action[targets[0]]):
            return f"{label}: action {action['label']!r} names either a wizard or a workflow by slug"
    return None
