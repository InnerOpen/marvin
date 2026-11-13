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
  those slugs, so a library sound shared by stories is found; ``of`` is optional; ``volume`` names the key inside each cue that holds its own
  level (0 to 1), which replaces the sound's own for that cue and gets a slider in the cue editor; ``filter`` limits what the item's page offers to
  pick
  to entries whose fields hold those values, e.g. ``{"kind": "effect"}``). ``bed`` is a sound that runs under a stretch: ``field``
  names the lane entry's slug on the view's entry itself (a story's music, one block under everything), or on each spine item, or, with
  ``via`` and ``entry_type``, on the entry a spine item's ``via`` field names (a beat's scene names its ambience); consecutive items with the
  same bed merge into one block. ``bed.volume`` is the level field on that entry and ``bed.item_volume`` an override on the spine item;
  a level set there *replaces* the sound's own (not multiplied), and ``bed.default_volume`` (0 to 1) plays when none is set.
  ``bed.fade_in`` / ``bed.fade_out`` name the sound's fade fields (seconds), ``bed.default_fade_in`` / ``default_fade_out`` what the render does
  when they are empty, and ``bed.end_fade`` a field on the view's entry for how long every bed fades out at the end of the film; the block
  draws them and Play follows them; ``bed.start_fade`` is the same for the start of the film, and ``bed.entry_fade_in`` /
  ``entry_fade_out`` (on the entry) and ``bed.item_fade_in`` / ``item_fade_out`` (on each item) make the lane's own fades cascade: the sound's,
  then the entry's, then the item's. ``bed.item_field`` (a field on each spine item) names that item's own sound, winning over the ``via``
  entry's, and ``bed.entry_field`` / ``bed.entry_volume`` name a sound under the whole film and its level: it plays together with the others,
  as the render layers them. ``bed.duck`` is a field on the view's entry holding none, light or strong: how far the bed goes down under each
  The story's bed can be turned down (or muffled) where the story is: ``bed.entry_item_volume`` is a field on each spine item (a beat's level for
  the story's bed), ``bed.entry_via_volume`` and ``bed.entry_via_muffled`` fields on the entry the item's ``via`` names (a scene's level, and
  whether it is heard from inside). The item's level wins over the entry's, which wins over the story's; the block shows each stretch as a
  step, says who set it (the story, a scene or a beat) and marks the muffled ones.
  spoken line.
  ``order`` is the field the lane's entries sort by (a number: those with none come after, by slug), ``off`` a boolean field that leaves an
  entry out when it is on (not timed, drawn or played: tried out and set aside); ``audio`` is an asset field, ``seconds`` a duration field,
  ``volume`` (0 to 1) and ``loop`` the lane entry's own level and whether it repeats, and ``estimate_from`` a text field whose length stands
  in for the seconds while there is no recording (drawn hatched). On a bed that runs under the whole story, ``bed.item_volume`` *replaces*
  the level while that spine item plays (a beat that takes the music to silence) and shows as steps in the block. ``cover`` is a video laid
  over each item's picture: ``field`` is the asset field, ``blend`` and ``opacity`` its settings; the item's own field wins, then the entry
  ``via`` (with ``entry_type``) names, then the view's entry itself, and a blend of ``none`` at one of them switches the overlay off from
  there up. ``marks`` writes one choice per spine item in its block, for something about the shot that is not sound or picture (the camera's
  move, the time of day): ``field`` holds the choice (a select's value), read from the item, else the entry ``via`` (with ``entry_type``)
  names, else the view's entry, so a scene or a story can set it for the beats that do not; ``labels`` and ``icons`` ({value: text}) say how
  a value reads, and ``other`` ({field, label}) names what the item shows when it has no choice of its own but that other field holds
  something of its own (an exact camera move written out): it wins over what the scene or the story chose, not over the item's own choice.
- ``spine.review`` ({ready, keep, redo}) puts Keep and Redo buttons on each item whose ``spine.status`` is one of ``ready`` (a still that was
  made and waits to be looked at): Keep writes the status ``keep``, Redo the status ``redo`` into the item's status field, and the page shows
  the new status at once. What the package does with those statuses (a redo made again) is its own workflows' business.
- ``spine.bands`` adds bands over the strip, each wrapping the consecutive items that share a value in its ``field`` (the beats of one scene),
  titled by the ``entry_type`` entry that value names; at most two. They draw only: nothing is reordered.
- ``spine.cards`` adds a title card (``intro``) and an end card (``outro``): each reads its ``title`` field (the card exists when it has
  text) and ``seconds`` field (else ``default_seconds``) from the view's entry. A card is laid out as an item of its own, so everything after it
  starts when the render starts it; the package's render must make the same cards.
- ``spine.scene_break`` ({field, seconds}) adds a pause where a scene ends: after an item whose next item holds a different value in ``field``
  (both non-empty), the view's entry's ``seconds`` field (when above 0) of quiet, part of the item's length; the render must add the same.
- ``spine.run`` puts a small button on each item that runs a ``workflow`` for just that item: ``entry`` is the workflow input that gets the
  entry's slug, ``item`` the input that gets the item's ``field`` value (a beat's number), ``inputs`` fixed values (a draft's quality).
- ``actions`` are buttons on the page: each starts a ``wizard`` or a ``workflow`` the same package brings. A workflow action with ``run``
  (``{entry, inputs?}``) starts it at once, ``entry`` naming the input that gets the entry's slug, and the page follows the job it makes.
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
    if problem := _slug(payload, "entry_type", label) or _field(payload, "aspect", label):
        return problem
    spine = payload.get("spine")
    if not isinstance(spine, dict):
        return f"{label} needs a spine: the entry type laid out in time, {{entry_type, of, ...}}"
    if (
        problem := _check_spine(spine, f"{label} spine")
        or _check_item_run(spine.get("run"), f"{label} spine")
        or _check_review(spine, f"{label} spine")
        or _check_bands(spine.get("bands"), f"{label} spine")
        or _check_cards(spine.get("cards"), f"{label} spine")
        or _check_scene_break(spine.get("scene_break"), f"{label} spine")
    ):
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


MAX_BANDS = 2
CARD_KINDS = ("intro", "outro")


def _check_scene_break(spec: Any, label: str) -> str | None:
    """`spine.scene_break`: {field, seconds}: a pause after an item whose next item holds a different value in `field`."""
    if spec is None:
        return None
    if not isinstance(spec, dict):
        return f"{label}: scene_break is {{field, seconds}}"
    return _fields({k: spec.get(k) for k in ("field", "seconds")}, ("field", "seconds"), f"{label} scene_break") or next(
        (f"{label} scene_break needs {k}, a field key" for k in ("field", "seconds") if spec.get(k) is None), None
    )


def _check_cards(cards: Any, label: str) -> str | None:
    """`spine.cards`: a title card before the items and an end card after them, from fields on the view's entry."""
    if cards is None:
        return None
    if not isinstance(cards, dict) or any(k not in CARD_KINDS for k in cards):
        return f"{label}: cards is {{intro?, outro?}}, each {{title, seconds?, default_seconds?, label?}}"
    for kind, card in cards.items():
        where = f"{label} cards.{kind}"
        if not isinstance(card, dict):
            return f"{where} is {{title, seconds?, default_seconds?, label?}}"
        if (problem := _field(card, "title", where, required=True)) or (problem := _field(card, "seconds", where)):
            return problem
        if not _number_between(card, "default_seconds", 0.1, 60):
            return f"{where}: default_seconds must be a number of seconds from 0.1 to 60"
        if card.get("label") is not None and (not isinstance(card["label"], str) or not card["label"].strip() or len(card["label"]) > 30):
            return f"{where}: label is a short text"
    return None


def _check_bands(bands: Any, label: str) -> str | None:
    """`spine.bands`: extra bands over the strip, each wrapping the consecutive items that share a value (the beats of one scene)."""
    if bands is None:
        return None
    if not isinstance(bands, list) or len(bands) > MAX_BANDS:
        return f"{label}: bands is a list of at most {MAX_BANDS}, each {{entry_type, field, id?, title?}}"
    seen: set[str] = set()
    for band in bands:
        if not isinstance(band, dict):
            return f"{label}: each band is {{entry_type, field, id?, title?}}"
        if (problem := _slug(band, "entry_type", f"{label} band")) or (problem := _field(band, "field", f"{label} band", required=True)):
            return problem
        if band.get("id") is not None and not (isinstance(band["id"], str) and _ID.match(band["id"])):
            return f"{label}: band id must be a short lowercase name"
        if band.get("title") is not None and (not isinstance(band["title"], str) or not band["title"].strip() or len(band["title"]) > 40):
            return f"{label}: band title is a short text"
        key = band.get("id") or band["field"]
        if key in seen:
            return f"{label}: band {key!r} is used twice"
        seen.add(key)
    return None


def _check_item_run(run: Any, label: str) -> str | None:
    """`spine.run`: a button on each item that runs a workflow for just that item (a quick draft of one beat)."""
    if run is None:
        return None
    shape = f"{label}: run is {{workflow, entry, item, field, label?, inputs?}}"
    if not isinstance(run, dict):
        return shape
    if not isinstance(run.get("workflow"), str) or not _SLUG.match(run["workflow"]):
        return f"{label}: run.workflow is the slug of a workflow the package brings"
    if problem := _fields(run, ("entry", "item", "field"), f"{label} run"):
        return problem
    if any(run.get(k) is None for k in ("entry", "item", "field")):
        return shape
    if run.get("label") is not None and (not isinstance(run["label"], str) or not run["label"].strip() or len(run["label"]) > 40):
        return f"{label}: run.label is a short text"
    return _check_run({"entry": run["entry"], "inputs": run.get("inputs")}, ["workflow"], "run", label)


def _check_review(spine: dict, label: str) -> str | None:
    """`spine.review`: Keep and Redo buttons on the items whose status says they are waiting to be looked at (a still that was made)."""
    review = spine.get("review")
    if review is None:
        return None
    shape = f"{label}: review is {{ready: [statuses], keep: status, redo: status}}"
    if not isinstance(review, dict):
        return shape
    if not isinstance(spine.get("status"), str):
        return f"{label}: review writes the item's status, so the spine needs `status`, the field that holds it"
    ready = review.get("ready")
    if not isinstance(ready, list) or not 1 <= len(ready) <= 6 or any(not isinstance(v, str) or not _ID.match(v) for v in ready):
        return f'{label}: review.ready is one to six statuses (the ones that show the buttons), e.g. ["made"]'
    for key in ("keep", "redo"):
        if not isinstance(review.get(key), str) or not _ID.match(review[key]):
            return f"{label}: review.{key} is the status the {key} button writes"
    return None


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


def _number_between(spec: dict, key: str, low: float, high: float) -> bool:
    value = spec.get(key)
    return value is None or (not isinstance(value, bool) and isinstance(value, int | float) and low <= value <= high)


def _check_bed(bed: Any, label: str) -> str | None:
    if not isinstance(bed, dict):
        return f"{label}: bed is {{field, via?, entry_type?, volume?, item_volume?}}"
    if problem := _field(bed, "field", f"{label} bed", required=True):
        return problem
    if problem := _fields(
        bed,
        (
            "via",
            "volume",
            "item_volume",
            "muffled",
            "fade_in",
            "fade_out",
            "start_fade",
            "end_fade",
            "entry_fade_in",
            "entry_fade_out",
            "item_fade_in",
            "item_fade_out",
            "duck",
            "item_field",
            "entry_field",
            "entry_volume",
            "entry_item_volume",
            "entry_via_volume",
            "entry_via_muffled",
        ),
        f"{label} bed",
    ):
        return problem
    if (bed.get("via") is None) != (bed.get("entry_type") is None):
        return f"{label}: bed.via (the spine item's field naming the entry) and bed.entry_type go together"
    if bed.get("entry_type") is not None and (problem := _slug(bed, "entry_type", f"{label} bed")):
        return problem
    for key in ("default_fade_in", "default_fade_out"):
        if not _number_between(bed, key, 0, 30):
            return f"{label}: bed.{key} must be a number of seconds from 0 to 30"
    if not _number_between(bed, "default_volume", 0, 1):
        return f"{label}: bed.default_volume must be a number from 0 to 1"
    return None


def _check_lane(lane: dict, label: str) -> str | None:
    if not isinstance(lane.get("title"), str) or not lane["title"].strip():
        return f"{label} needs a title"
    if problem := _slug(lane, "entry_type", label):
        return problem
    shapes = [k for k in ("in", "placed", "bed", "cover", "marks") if lane.get(k) is not None]
    if len(shapes) != 1:
        return (
            f"{label}: one of `in` (the field holding the spine item's slug), `placed` ({{field, ref, at}}), "
            "`bed` ({field, via?}), `cover` ({field, via?}) or `marks` ({field, via?})"
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
        if problem := _field(placed, "volume", f"{label} placed"):  # the key inside each cue holding its own level (0 to 1)
            return problem
        if (filt := placed.get("filter")) is not None and not (
            isinstance(filt, dict) and filt and all(_NAME.match(k) and isinstance(v, str) and v for k, v in filt.items())
        ):
            return f"{label}: placed.filter is {{field: text}}, the values an entry must hold to be offered (kind: effect)"
    if (bed := lane.get("bed")) is not None and (problem := _check_bed(bed, label)):
        return problem
    if (cover := lane.get("cover")) is not None:
        if problem := _check_cover(cover, label):
            return problem
    if (marks := lane.get("marks")) is not None and (problem := _check_marks(marks, label)):
        return problem
    if (opens := lane.get("open")) is not None:
        if not isinstance(opens, dict):
            return f"{label}: open is {{wizard}}, the guided setup a piece opens on instead of its own page"
        if problem := _slug(opens, "wizard", f"{label} open"):
            return problem
    return _fields(lane, ("order", "off", "text", "who", "audio", "waveform", "seconds", "volume", "loop", "estimate_from", "status"), label)


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


MAX_MARK_WORDS = 40  # how many values a marks lane may name, and the longest a label or icon may be
_MARK_TEXT = 40


def _check_marks(marks: Any, label: str) -> str | None:
    if not isinstance(marks, dict):
        return f"{label}: marks is {{field, via?, entry_type?, labels?, icons?, other?}}"
    if problem := _field(marks, "field", f"{label} marks", required=True):
        return problem
    if problem := _field(marks, "via", f"{label} marks"):
        return problem
    if (marks.get("via") is None) != (marks.get("entry_type") is None):
        return f"{label}: marks.via (the spine item's field naming the entry) and marks.entry_type go together"
    if marks.get("entry_type") is not None and (problem := _slug(marks, "entry_type", f"{label} marks")):
        return problem
    for key in ("labels", "icons"):
        words = marks.get(key)
        if words is None:
            continue
        if not (
            isinstance(words, dict)
            and 0 < len(words) <= MAX_MARK_WORDS
            and all(isinstance(k, str) and k and isinstance(v, str) and v.strip() and len(v) <= _MARK_TEXT for k, v in words.items())
        ):
            return f"{label}: marks.{key} is {{value: text}}, at most {MAX_MARK_WORDS} values and {_MARK_TEXT} characters each"
    if (other := marks.get("other")) is not None:
        if not isinstance(other, dict) or not isinstance(other.get("label"), str) or not other["label"].strip() or len(other["label"]) > _MARK_TEXT:
            return f"{label}: marks.other is {{field, label}}, what an item shows when that field holds something of its own"
        return _field(other, "field", f"{label} marks.other", required=True)
    return None


def _check_run(run: Any, targets: list[str], action_label: str, label: str) -> str | None:
    """`run` makes a workflow action start the workflow at once: {entry: the input that receives the entry's slug, inputs?: fixed values}."""
    if targets != ["workflow"]:
        return f"{label}: action {action_label!r} runs a workflow, so it needs `workflow`, not a wizard"
    if not isinstance(run, dict) or not isinstance(run.get("entry"), str) or not _NAME.match(run["entry"]):
        return f"{label}: action {action_label!r} run is {{entry, inputs?}}: entry is the workflow input that gets the entry's slug"
    inputs = run.get("inputs")
    if inputs is not None and not (
        isinstance(inputs, dict) and len(inputs) <= 8 and all(_NAME.match(k) and isinstance(v, str | int | float | bool) for k, v in inputs.items())
    ):
        return f"{label}: action {action_label!r} run.inputs is up to 8 input names with text, number or yes/no values"
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
        if (run := action.get("run")) is not None and (problem := _check_run(run, targets, action["label"], label)):
            return problem
    return None
