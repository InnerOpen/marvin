"""Wizards: a package's guided, multi-page setups, shipped as plain data.

A wizard is a list of steps that walks a person through making content, e.g. Screenplay Studio's "narrate a story": pick or create a
world, then a story, upload a script, cast the characters. Core knows nothing about stories: it only knows how to draw the five kinds of
step below and to carry a *context* from one step to the next (the slug of the world chosen, the story created). A package supplies the
definition; nothing in it is code, it names entry types and fields by slug and reads the context as ``${name}``.

Steps (each has ``id``, ``title`` and optional ``help`` and ``when``):

- ``option``: pick one of a few labelled values (``options: [{value, label}]``); sets the context key ``as``. Only there to branch on.
- ``choose``: pick an entry of ``entry_type`` (or create one), sets the context key ``as`` to its slug. ``scope`` ({field: "${key}"})
  narrows the list to entries whose field holds an earlier choice; ``create`` ({fields: [...], data: {field: "${key}" | literal}}) lets
  the person make a new one, arriving with ``data`` filled in; ``optional`` lets them skip it. ``create.upload`` ({field, accept?}) makes
  the new one from a file: the picture (or sound) goes into the asset ``field`` and the entry is named for what the person typed, or for
  the file when they typed nothing, so a wizard can start from "upload, or choose one".
- ``form``: edit some ``fields`` of the entry in context key ``entry``.
- ``upload``: a file for the entry in context key ``entry``. ``mode: "asset"`` stores it as an asset in ``field``; ``mode: "text"``
  reads it as text into ``field`` (a script, a beat sheet). ``accept`` lists extensions.
- ``list``: the entries of ``entry_type`` whose ``parent_field`` holds context key ``parent``, with the ``columns`` editable in place and
  ``add`` to make another.
- ``gallery``: the entries of ``entry_type`` as picture cards (a troupe of actors, a story's cast), scoped like a list (``parent_field`` holds
  context key ``parent``; both or neither). ``picture`` is the asset field shown, ``audio`` an asset field played from the card, ``subtitle``
  a field under the name, ``badges`` fields shown as pills. Actions, each optional: ``add`` ({fields, data?}: a form), ``upload`` ({field,
  accept?}: a file becomes a new entry, named for the file; ``accept`` is the file input's accept, ``image/*`` unless it says, e.g.,
  ``audio/*``), ``generate`` ({workflow, inputs, button, prompt?: {name, label}}: a run, as a run step, with a text the person types).
- ``run``: a button that starts the workflow ``workflow`` (by slug, one the same package brings) with ``inputs`` ({name: "${key}" | literal}),
  e.g. cutting the beats of a script once it is uploaded. ``requires`` ({entry, field}) keeps the button off until that field holds something.
  A workflow that is off is never turned on from here: the page says so.
- ``review``: ``checks``, each ``{label, query, op, value, step?}``: the query (entry-query spec: ``entry_type``, ``fields``, ``where``…) is
  counted and compared (``gt gte eq lte lt``) to a number; ``step`` names the step that makes it, linked when it fails. All passing means
  the wizard is done.

``next`` ([{text, href?}]) is shown at the end: what to do once the wizard is done, with paths inside the app.
``when`` ({ctx, op: eq|neq|set|unset, value?}) hides a step unless it holds, which is how an upload step follows the option chosen.
Progress is never stored: the context rides in the page's address and each step shows done from what exists.
"""

from __future__ import annotations

import re
from typing import Any

MAX_STEPS = 40
MAX_NEXT = 6  # lines of "what to do next" at the end
STEP_KINDS = ("option", "choose", "form", "upload", "list", "gallery", "run", "review")
WHEN_OPS = ("eq", "neq", "set", "unset")
CHECK_OPS = ("gt", "gte", "eq", "lte", "lt")
UPLOAD_MODES = ("asset", "text")

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")  # a context key, or a workflow input
_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")  # an entry type's field key, which may be camelCase (sellOnline)
# A file input's accept: MIME patterns (audio/*, image/png) or extensions (.webp), comma-separated.
_ACCEPT_PART = r"(?:[a-z]+/(?:\*|[a-z0-9.+-]+)|\.[a-z0-9]{1,10})"
_ACCEPT = re.compile(rf"^\s*{_ACCEPT_PART}(?:\s*,\s*{_ACCEPT_PART})*\s*$", re.IGNORECASE)
MAX_SHOWN = 8
MAX_PREFILL = 12
RESERVED_KEYS = ("step", "notice")  # address parameters the page uses for itself: never a context key
_STEP_ID = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
_REF = re.compile(r"\$\{([^}]*)\}")
_EXT = re.compile(r"^\.[a-z0-9]{1,10}$")


def _is_field(value: Any) -> bool:
    return isinstance(value, str) and bool(_FIELD.match(value))


def _refs(value: Any) -> list[str]:
    """Every ``${name}`` inside a string, list or dict value."""
    if isinstance(value, str):
        return _REF.findall(value)
    if isinstance(value, list):
        return [r for item in value for r in _refs(item)]
    if isinstance(value, dict):
        return [r for item in value.values() for r in _refs(item)]
    return []


def _keys(value: Any, what: str) -> str | None:
    if not isinstance(value, list) or not value or not all(isinstance(k, str) and _FIELD.match(k) for k in value):
        return f"{what} must be a non-empty list of field keys"
    return None


def payload_problem(payload: dict, slug: str) -> str | None:
    """Why this wizard payload is not acceptable (None when it is). Pure: it looks at the definition alone, never at the workspace, so a
    package installs even before its entry types exist; a missing type is the wizard page's message to give."""
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        return f"wizard {slug!r} needs a title"
    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        return f"wizard {slug!r} needs at least one step"
    if problem := _check_next(payload.get("next"), slug):
        return problem
    if len(steps) > MAX_STEPS:
        return f"wizard {slug!r} has more than {MAX_STEPS} steps"
    known: set[str] = set()  # context keys set by an earlier step
    entries: set[str] = set()  # the ones a `choose` set: the only keys that name an entry
    seen: set[str] = set()
    for n, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            return f"step {n} of wizard {slug!r} is not an object"
        sid = step.get("id")
        label = f"step {sid!r} of wizard {slug!r}"
        if not isinstance(sid, str) or not _STEP_ID.match(sid):
            return f"step {n} of wizard {slug!r} needs an id of lowercase letters, digits, - or _"
        if sid in seen:
            return f"{label} is used twice"
        seen.add(sid)
        if not isinstance(step.get("title"), str) or not step["title"].strip():
            return f"{label} needs a title"
        kind = step.get("kind")
        if kind not in STEP_KINDS:
            return f"{label} has kind {kind!r}; it must be one of {', '.join(STEP_KINDS)}"
        if (
            (problem := _check_when(step.get("when"), known, label))
            or (problem := _check_step(step, kind, known, entries, label, seen - {sid}))
            or (problem := _check_show(step.get("show"), entries, label))
        ):
            return problem
        if kind in ("option", "choose"):
            known.add(step["as"])
        if kind == "choose":
            entries.add(step["as"])
    return _check_open(payload.get("open"), entries, slug) or _check_button(payload.get("button"), entries, seen, slug)


def _check_open(spec: Any, entries: set[str], slug: str) -> str | None:
    """``open``: the button at the end that opens what was made, ``{entry, label, view?}``; the entry is a key a choose step set. ``view`` is
    the slug of a view (the same package's) the entry opens in, instead of its edit page: a story opens as its timeline."""
    if spec is None:
        return None
    if not isinstance(spec, dict) or not isinstance(spec.get("label"), str) or not spec["label"].strip():
        return f"wizard {slug!r}: open is {{entry, label, view?}}, the button that opens what was made"
    if spec.get("entry") not in entries:
        return f"wizard {slug!r}: open names {spec.get('entry')!r}, which no choose step sets"
    if spec.get("view") is not None and not (isinstance(spec["view"], str) and _SLUG.match(spec["view"])):
        return f"wizard {slug!r}: open.view must be the slug of a view"
    return None


def _check_button(spec: Any, entries: set[str], steps: set[str], slug: str) -> str | None:
    """``button``: a button on the page of an entry of ``entry_type`` that opens this setup on it, ``{entry_type, label, key, step?, also?}``.
    ``key`` is the choose step's context key the entry fills (so that step is already answered), ``step`` the step to open on, and ``also``
    carries more context from the entry's own fields ({context key: field key}), for the choices before ``key`` (a line's story)."""
    if spec is None:
        return None
    shape = f"wizard {slug!r}: button is {{entry_type, label, key, step?, also?}}, a button on an entry's page that opens this setup on it"
    if not isinstance(spec, dict) or not isinstance(spec.get("label"), str) or not spec["label"].strip():
        return shape
    if not (isinstance(spec.get("entry_type"), str) and _SLUG.match(spec["entry_type"])):
        return f"wizard {slug!r}: button.entry_type must be an entry type's slug"
    if spec.get("key") not in entries:
        return f"wizard {slug!r}: button.key {spec.get('key')!r} is not a key a choose step sets"
    if spec.get("step") is not None and spec["step"] not in steps:
        return f"wizard {slug!r}: button.step {spec.get('step')!r} is not a step of this wizard"
    also = spec.get("also")
    if also is not None:
        if not isinstance(also, dict) or len(also) > 4 or not all(k in entries and k != spec["key"] and _is_field(v) for k, v in also.items()):
            return f'wizard {slug!r}: button.also maps choose-step keys to field keys of the entry, e.g. {{"story": "story"}}'
    return None


def _check_show(spec: Any, entries: set[str], label: str) -> str | None:
    """``show`` on any step: a card above it with the chosen entry's own words, ``{entry, fields}``: ``entry`` is a key an earlier choose step
    set and ``fields`` (at most 8) the fields to read out, so someone recording a line sees the line, its direction and the rest."""
    if spec is None:
        return None
    if not isinstance(spec, dict) or spec.get("entry") not in entries:
        return f"{label}: show needs entry, a key an earlier choose step set"
    fields = spec.get("fields")
    if not isinstance(fields, list) or not fields or len(fields) > MAX_SHOWN or not all(_is_field(f) for f in fields):
        return f"{label}: show.fields is a list of 1 to {MAX_SHOWN} field keys"
    return None


def _check_next(lines: Any, slug: str) -> str | None:
    """``next``: what to do once the wizard is done, each ``{text, href?}``; an href is a path inside the app, never a full address."""
    if lines is None:
        return None
    if not isinstance(lines, list) or len(lines) > MAX_NEXT:
        return f"wizard {slug!r}: next is a list of at most {MAX_NEXT} {{text, href?}} lines"
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get("text"), str) or not line["text"].strip():
            return f"wizard {slug!r}: each next line needs text"
        href = line.get("href")
        if href is not None and (not isinstance(href, str) or not href.startswith("/") or href.startswith("//")):
            return f"wizard {slug!r}: a next line's href is a path in the app, starting with /"
    return None


def _check_when(when: Any, known: set[str], label: str) -> str | None:
    if when is None:
        return None
    if not isinstance(when, dict) or when.get("op") not in WHEN_OPS:
        return f"{label}: when must be {{ctx, op}} with op one of {', '.join(WHEN_OPS)}"
    if not isinstance(when.get("ctx"), str) or when["ctx"] not in known:
        return f"{label}: when names {when.get('ctx')!r}, which no earlier step sets"
    if when["op"] in ("eq", "neq") and not isinstance(when.get("value"), str):
        return f"{label}: when {when['op']} needs a text value"
    return None


class _Step:
    """One step being checked: its label for messages, and the context keys the steps before it set."""

    def __init__(self, step: dict, known: set[str], entries: set[str], label: str, step_ids: set[str] | None = None):
        self.step, self.known, self.entries, self.label = step, known, entries, label
        self.step_ids = step_ids or set()  # the ids of the steps before this one

    def ctx(self, key: str) -> str | None:
        """`key` of this step names the entry an earlier `choose` step picked."""
        value = self.step.get(key)
        if not isinstance(value, str):
            return f"{self.label}: {key} must name a context key"
        if value in self.entries:
            return None
        if value in self.known:
            return f"{self.label}: {key} names {value!r}, which is an option, not an entry an earlier step chose"
        return f"{self.label}: {key} names {value!r}, which no earlier step sets"

    def refs_known(self, value: Any, what: str) -> str | None:
        bad = next((r for r in _refs(value) if r not in self.known), None)
        return None if bad is None else f"{self.label}: {what} uses ${{{bad}}}, which no earlier step sets"

    def entry_type(self) -> str | None:
        found = self.step.get("entry_type")
        return None if isinstance(found, str) and _SLUG.match(found) else f"{self.label} needs an entry_type slug"

    def sets_context(self) -> str | None:
        key = self.step.get("as")
        if not isinstance(key, str) or not _NAME.match(key):
            return f"{self.label} needs `as`, the context key it sets"
        if key in RESERVED_KEYS:
            return f"{self.label}: `as` cannot be {key!r}, the page uses that name itself"
        if key in self.known:
            return f"{self.label}: `as` {key!r} is already set by an earlier step"
        return None


def _check_option(s: _Step) -> str | None:
    options = s.step.get("options")
    valid = isinstance(options, list) and all(
        isinstance(o, dict) and isinstance(o.get("value"), str) and o["value"] and isinstance(o.get("label"), str) for o in options
    )
    if not valid or len(options) < 2:
        return f"{s.label} needs at least two options, each with a value and a label"
    if len({o["value"] for o in options}) != len(options):
        return f"{s.label} has two options with the same value"
    return s.sets_context()


def _check_upload_spec(s: _Step, upload: Any, what: str) -> str | None:
    """`upload` of a gallery or of a choose step's `create`: {field, accept?}, the asset field a file goes into and the file input's accept."""
    if not (isinstance(upload, dict) and _is_field(upload.get("field"))):
        return f"{s.label}: {what} needs the asset field the file goes into"
    if upload.get("accept") is not None and not (isinstance(upload["accept"], str) and _ACCEPT.match(upload["accept"])):
        return f"{s.label}: {what}.accept is a file input's accept, like audio/* or image/png,.webp"
    if upload.get("seconds") is not None and not _is_field(upload["seconds"]):
        return f"{s.label}: {what}.seconds is the number field that takes the sound's length, measured in the browser"
    return None


def _check_create(s: _Step, create: Any) -> str | None:
    if not isinstance(create, dict):
        return f"{s.label}: create must be an object like {{fields: [...], data: {{...}}}}"
    if create.get("fields") is not None and (problem := _keys(create["fields"], f"{s.label}: create.fields")):
        return problem
    if create.get("data") is not None and not isinstance(create["data"], dict):
        return f"{s.label}: create.data must be an object"
    if create.get("upload") is not None and (problem := _check_upload_spec(s, create["upload"], "create.upload")):
        return problem
    return s.refs_known(create.get("data"), "create.data")


def _check_choose(s: _Step) -> str | None:
    scope, create = s.step.get("scope"), s.step.get("create")
    if scope is not None and (not isinstance(scope, dict) or not all(_is_field(k) for k in scope)):
        return f"{s.label}: scope must map field keys to values"
    for key in ("picture", "subtitle"):  # a pick with a picture is drawn as tiles, not a plain list
        if s.step.get(key) is not None and not _is_field(s.step[key]):
            return f"{s.label}: {key} must be a field key"
    return s.sets_context() or s.entry_type() or s.refs_known(scope, "scope") or (create is not None and _check_create(s, create)) or None


def _check_form(s: _Step) -> str | None:
    return s.ctx("entry") or _keys(s.step.get("fields"), f"{s.label}: fields")


def _check_upload(s: _Step) -> str | None:
    accept = s.step.get("accept", [])
    if s.step.get("mode") not in UPLOAD_MODES:
        return f"{s.label}: mode must be asset or text"
    if not _is_field(s.step.get("field")):
        return f"{s.label} needs the field key the file goes into"
    if not isinstance(accept, list) or not all(isinstance(a, str) and _EXT.match(a) for a in accept):
        return f"{s.label}: accept is a list of extensions like .fountain"
    return s.ctx("entry")


def _check_list(s: _Step) -> str | None:
    if not _is_field(s.step.get("parent_field")):
        return f"{s.label} needs parent_field, the field that holds the parent's slug"
    return (
        s.entry_type()
        or s.ctx("parent")
        or _keys(s.step.get("columns"), f"{s.label}: columns")
        or s.refs_known(s.step.get("create_data"), "create_data")
    )


def _check_one_check(s: _Step, check: Any) -> str | None:
    if not isinstance(check, dict) or not isinstance(check.get("label"), str) or not isinstance(check.get("query"), dict):
        return f"{s.label}: each check needs a label and a query"
    value = check.get("value")
    if check.get("op") not in CHECK_OPS or not isinstance(value, int) or isinstance(value, bool):
        return f"{s.label}: each check compares with one of {', '.join(CHECK_OPS)} to a whole number"
    if not isinstance(check["query"].get("entry_type"), str):
        return f"{s.label}: each check's query needs an entry_type"
    if check.get("step") is not None and check["step"] not in s.step_ids:
        return f"{s.label}: check {check['label']!r} names step {check['step']!r}, which is not before it"
    return s.refs_known(check["query"], "a check")


def _check_run(s: _Step) -> str | None:
    inputs = s.step.get("inputs", {})
    if not isinstance(s.step.get("workflow"), str) or not _SLUG.match(s.step["workflow"]):
        return f"{s.label} needs the slug of the workflow it runs"
    if not isinstance(inputs, dict) or not all(_NAME.match(str(k)) and isinstance(v, str) for k, v in inputs.items()):
        return f"{s.label}: inputs must map the workflow's input names to text"
    if s.step.get("button") is not None and not isinstance(s.step["button"], str):
        return f"{s.label}: button must be text"
    requires = s.step.get("requires")
    if requires is not None:
        if not isinstance(requires, dict) or not _is_field(requires.get("field")):
            return f"{s.label}: requires must be {{entry, field}}, the field that has to hold something before it can run"
        if (problem := _Step(requires, s.known, s.entries, s.label).ctx("entry")) is not None:
            return problem
    return s.refs_known(inputs, "inputs")


def _check_add_extras(s: _Step, add: Any) -> str | None:
    """What a gallery's ``add`` form may carry beyond fields and data: ``open`` (shown open), ``title``, ``prefill`` ({field: "key.field"}: start
    from the chosen entry's own value, a take from its line's words), ``file`` (a Record/Upload box in the form, as ``upload``) and ``buttons``
    (up to 3 ways to save, each ``{label, data?, file?}``: its data is added to the entry, ``file`` is "required" or "none")."""
    if not isinstance(add, dict):
        return None
    if add.get("open") is not None and not isinstance(add["open"], bool):
        return f"{s.label}: add.open is true or false"
    if add.get("title") is not None and not (isinstance(add["title"], str) and add["title"].strip() and len(add["title"]) <= 60):
        return f"{s.label}: add.title is a short heading for the form"
    if (prefill := add.get("prefill")) is not None:
        if not isinstance(prefill, dict) or len(prefill) > MAX_PREFILL or not all(_is_field(k) for k in prefill):
            return f'{s.label}: add.prefill maps up to {MAX_PREFILL} field keys to "key.field", an entry an earlier step chose and one of its fields'
        for value in prefill.values():
            for source in str(value).split("|"):  # "a.x|a.y": the first of them that has a value
                key, _, field = source.partition(".")
                if key not in s.entries or not _is_field(field):
                    return (
                        f"{s.label}: add.prefill {value!r} must be keys an earlier choose step set, each a dot and a field key (several joined by |)"
                    )
    if add.get("file") is not None and (problem := _check_upload_spec(s, add["file"], "add.file")):
        return problem
    if (buttons := add.get("buttons")) is not None:
        if not isinstance(buttons, list) or not 1 <= len(buttons) <= 3:
            return f"{s.label}: add.buttons is a list of 1 to 3 buttons"
        for b in buttons:
            if not isinstance(b, dict) or not isinstance(b.get("label"), str) or not b["label"].strip():
                return f"{s.label}: each add button needs a label"
            data = b.get("data")
            if data is not None and not (
                isinstance(data, dict) and all(_is_field(k) and isinstance(v, str | int | float | bool) for k, v in data.items())
            ):
                return f"{s.label}: a button's data maps field keys to text, numbers or true/false"
            if b.get("file") not in (None, "required", "none"):
                return f"{s.label}: a button's file is required or none"
    return None


def _check_gallery(s: _Step) -> str | None:
    step = s.step
    scoped = [k for k in ("parent", "parent_field") if step.get(k) is not None]
    if len(scoped) == 1:
        return f"{s.label}: parent and parent_field go together (or neither)"
    if scoped and not _is_field(step.get("parent_field")):
        return f"{s.label}: parent_field must be a field key"
    for key in ("picture", "audio", "subtitle"):
        if step.get(key) is not None and not _is_field(step[key]):
            return f"{s.label}: {key} must be a field key"
    if step.get("badges") is not None and (problem := _keys(step["badges"], f"{s.label}: badges")):
        return problem
    if step.get("layout") not in (None, "cards", "list"):
        return f"{s.label}: layout is cards (the default) or list"
    if (name := step.get("name")) is not None:
        if not isinstance(name, dict) or name.get("from") not in s.entries or not isinstance(name.get("noun"), str) or not name["noun"].strip():
            return f"{s.label}: name is {{from, noun}}: from is a key an earlier choose step set, noun the word that follows its title (take)"
    if (hi := step.get("highlight")) is not None and not (
        isinstance(hi, dict) and _is_field(hi.get("field")) and isinstance(hi.get("value"), str) and isinstance(hi.get("label"), str)
    ):
        return f"{s.label}: highlight is {{field, value, label}}, the card whose field has that value is marked with the label"
    if step.get("added") is not None and not (isinstance(step["added"], str) and step["added"].strip()):
        return f"{s.label}: added is the line shown after one is added or uploaded"
    if step.get("add") is not None and (
        (problem := _check_create(s, step["add"])) and (problem := problem.replace("create", "add")) or (problem := _check_add_extras(s, step["add"]))
    ):
        return problem
    if (approve := step.get("approve")) is not None and not (
        isinstance(approve, list) and 1 <= len(approve) <= 3 and all(isinstance(w, str) and _SLUG.match(w) for w in approve)
    ):
        return f"{s.label}: approve is a list of up to 3 workflow slugs whose approvals are shown on this step"
    if (upload := step.get("upload")) is not None and (problem := _check_upload_spec(s, upload, "upload")):
        return problem
    if (gen := step.get("generate")) is not None:
        if not isinstance(gen, dict):
            return f"{s.label}: generate must be an object like a run step"
        prompt = gen.get("prompt")
        if prompt is not None and not (isinstance(prompt, dict) and _NAME.match(str(prompt.get("name"))) and isinstance(prompt.get("label"), str)):
            return f"{s.label}: generate.prompt needs a name and a label"
        typed = {prompt["name"]} if isinstance(prompt, dict) else set()
        if problem := _check_run(_Step(gen, s.known | typed, s.entries, f"{s.label} generate")):
            return problem
    return s.entry_type() or (s.ctx("parent") if scoped else None)


def _check_review(s: _Step) -> str | None:
    checks = s.step.get("checks")
    if not isinstance(checks, list) or not checks:
        return f"{s.label} needs checks"
    return next((problem for check in checks if (problem := _check_one_check(s, check))), None)


_CHECKS = {
    "option": _check_option,
    "choose": _check_choose,
    "form": _check_form,
    "upload": _check_upload,
    "list": _check_list,
    "gallery": _check_gallery,
    "run": _check_run,
    "review": _check_review,
}


def _check_step(step: dict, kind: str, known: set[str], entries: set[str], label: str, seen: set[str] | None = None) -> str | None:
    return _CHECKS[kind](_Step(step, known, entries, label, seen))
