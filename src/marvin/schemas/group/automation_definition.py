"""The ONE structural declaration of a Flavor B automation ``definition``.

Until now the ``definition`` was a raw, unvalidated ``dict`` at every layer — the API schema, the DB
column, and the engine — with a parallel hand-authored TypeScript interface in the SDK as a second,
drift-prone source of truth, and *zero* structure validation on create/update (any dict persisted).

This module makes a Pydantic **discriminated union** that single declaration:

  * triggers discriminate on ``type`` (event / manual / schedule / chained / on_error /
    incoming_webhook / mcp),
  * actions discriminate on ``kind`` (operation / entry / emit_event / handler / webhook) — one model
    per registered executor, its previously-implicit ``action.get(...)`` reads now typed fields,
  * conditions are a recursive leaf-or-group,
  * plus the optional target selector.

From it fall out: structural validation at the write boundary (see ``services/automation/validation``)
and a JSON Schema advertised by ``/api/automations/options`` that the builder + SDK mirror.

Two deliberate departures from the rest of Marvin's API models:

  * **snake_case, not camelCase.** The engine reads the stored definition by exact snake_case key
    (``action.get("entity_slug")``, ``trig.get("event")``), so — unlike ``_MarvinModel`` with its
    ``camelize`` alias — these models keep field names verbatim. They validate the definition; they do
    NOT re-serialize it (storage keeps the raw dict), so the engine is untouched.
  * **``extra="allow"``.** Validation gates the *shape it knows* (discriminators, required fields,
    types) but never rejects an unknown extra key, so advanced or forward-compatible definitions still
    save. The semantic "this won't match anything" checks stay advisory (``validation.py``).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


class _DefnBase(BaseModel):
    # snake_case verbatim (no camelize), lenient on unknown keys, accept field name or alias.
    model_config = ConfigDict(extra="allow", populate_by_name=True)


# ── Triggers (discriminated on `type`) ────────────────────────────────────────
class EventTrigger(_DefnBase):
    """Runs when a Marvin event fires: `event` is a triggerable event name. An entry event's entry is `entry.*`."""

    type: Literal["event"] = "event"
    event: str


class RunInput(_DefnBase):
    """One thing the person (or agent) running a manual workflow fills in, read as ${input.<name>}. `type`: text, number,
    choice (one of `options`) or entry (an entry's id or slug — the run acts on it: ${entry.*}, entry steps)."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str | None = None
    type: Literal["text", "number", "choice", "entry"] = "text"
    options: list[str] | None = None
    required: bool = True
    default: str | float | None = None
    description: str | None = None

    @model_validator(mode="after")
    def _choice_has_options(self):
        if self.type == "choice" and not self.options:
            raise ValueError(f"input “{self.name}” is a choice: give it options")
        if self.type == "choice" and self.default is not None and str(self.default) not in self.options:
            raise ValueError(f"input “{self.name}”: its default isn't one of its options")
        return self


class ManualTrigger(_DefnBase):
    """Runs only when someone presses Run (or the run_workflow tool or the API runs it). `inputs` are what the run asks
    for — ${input.<name>}; an `entry` input is the entry the run acts on."""

    type: Literal["manual"]
    inputs: list[RunInput] | None = None

    @model_validator(mode="after")
    def _inputs_are_distinct(self):
        names = [i.name for i in self.inputs or []]
        if len(names) != len(set(names)):
            raise ValueError("two run inputs have the same name")
        if sum(i.type == "entry" for i in self.inputs or []) > 1:
            raise ValueError("a run acts on one entry: at most one input of type entry")
        return self


class ScheduleTrigger(_DefnBase):
    """Runs on a schedule: `schedule_type` interval (`schedule_config.interval_seconds`), cron
    (`cron_expression`, `timezone`) or once (`run_at`, ISO 8601)."""

    type: Literal["schedule"]
    schedule_type: str | None = None
    schedule_config: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _cron_can_run(self):
        # A cron schedule the scheduler can't compute would be saved and then never run.
        if self.schedule_type == "cron":
            from marvin.services import cron

            config = self.schedule_config or {}
            problem = cron.problem(config.get("cron_expression"), config.get("timezone"))
            if problem:
                raise ValueError(problem)
        return self


class ChainedTrigger(_DefnBase):
    """Runs after another workflow ran: `automation` is its slug or id (omitted or "any": every workflow)."""

    type: Literal["chained"]
    automation: str | None = None  # target automation (slug/id); None/"any" = every automation


class OnErrorTrigger(_DefnBase):
    """Runs after another workflow failed: `automation` is its slug or id (omitted or "any": every workflow)."""

    type: Literal["on_error"]
    automation: str | None = None


class IncomingWebhookTrigger(_DefnBase):
    """Runs when an incoming webhook is called: `webhook` is its slug (omitted or "any": any). The body is `event.payload.*`."""

    type: Literal["incoming_webhook"]
    webhook: str | None = None  # target incoming-webhook slug; None/"any" = any webhook


class McpTrigger(_DefnBase):
    """Runs when an MCP host calls the workflow's own tool, `marvin_wf_<slug>`."""

    type: Literal["mcp"]


# kind literal → model, so the union and the drift test both read from one place.
TRIGGER_MODELS: dict[str, type[_DefnBase]] = {
    "event": EventTrigger,
    "manual": ManualTrigger,
    "schedule": ScheduleTrigger,
    "chained": ChainedTrigger,
    "on_error": OnErrorTrigger,
    "incoming_webhook": IncomingWebhookTrigger,
    "mcp": McpTrigger,
}

Trigger = Annotated[
    EventTrigger | ManualTrigger | ScheduleTrigger | ChainedTrigger | OnErrorTrigger | IncomingWebhookTrigger | McpTrigger,
    Field(discriminator="type"),
]


# ── Actions (discriminated on `kind`) — one model per registered executor ──────
class _StepBase(_DefnBase):
    """What every step shares: `when` runs it only if its conditions hold at that point of the run (they can read
    `steps.<id>.output.*` and `previous.*` as well as the event and the item) — false records the step as skipped
    and the run goes on, so two steps with opposite `when`s are an if/else."""

    when: list[Condition] | Condition | None = None


# What an operation step's `write_back` map may write (beside `metadata.<key>`). Named fields only: an item's other
# columns (its storage key, its workspace) are never an AI output's to change, and an entry's title or status would
# move its page or publish it — its typed fields go through a `set_data` step reading the output.
WRITEBACK_FIELDS: dict[str, frozenset[str]] = {
    "entry": frozenset({"summary", "tags"}),
    "asset": frozenset({"alt_text", "description", "name", "tags"}),
    "resource": frozenset({"description", "name", "tags"}),
}


def writeback_field_ok(kind: str, field: str) -> bool:
    """Whether `field` is one an operation step's `write_back` map may write on a `kind` (entry | asset | resource)."""
    if field.startswith("metadata.") and len(field) > len("metadata."):
        return kind in WRITEBACK_FIELDS
    return field in WRITEBACK_FIELDS.get(kind, frozenset())


class OperationAction(_StepBase):
    """Runs an AI operation (`op`: its slug) on the entry, or (`entity_type`) an asset | resource. `op: "custom"` takes
    your own `prompt` (with ${…} templates) and `output_schema` (a JSON Schema object); `see` adds context: item,
    attachments, images, persona. `write_back`: true saves a built-in op's own fields on an entry; a map {output key:
    field} names them (entry summary/tags, asset alt_text/description/name/tags, resource description/name/tags,
    metadata.<key>)."""

    kind: Literal["operation"]
    op: str  # AI operation slug
    input: dict[str, Any] = Field(default_factory=dict)
    entity_type: str = "entry"  # unset: the target's or the triggering item's kind, else entry
    entity_id: str | None = None  # defaults to the run's $event.<entity_type>_id
    entity_slug: str | None = None  # preferred for webhook payloads; resolved at run time
    write_back: bool | dict[str, str] = False
    prompt: str | None = None  # op "custom" only: the instructions (≤ 8000 characters)
    output_schema: dict[str, Any] | None = None  # op "custom" only: the answer's JSON Schema (an object)
    see: list[Literal["item", "attachments", "images", "persona"]] | None = None  # op "custom" only; default ["item"]
    id: str | None = None  # addressable as $steps.<id>.output.*

    @field_validator("write_back")
    @classmethod
    def _write_back_fields(cls, value):
        if isinstance(value, dict):
            if not value:
                raise ValueError("write_back map is empty: name {output key: field}, or use true")
            unknown = sorted(f for f in value.values() if not any(writeback_field_ok(k, f) for k in WRITEBACK_FIELDS))
            if unknown:
                raise ValueError(
                    f"write_back can't write {', '.join(unknown)}: an entry takes summary, tags or metadata.<key>; an asset "
                    "alt_text, description, name, tags or metadata.<key>; a resource description, name, tags or metadata.<key>"
                )
        return value

    @model_validator(mode="after")
    def _custom_prompt(self):
        from marvin.services.ai.operations.custom import CUSTOM_OP, MAX_PROMPT_CHARS, schema_problems

        if self.op != CUSTOM_OP:
            if self.prompt is not None or self.output_schema is not None or self.see is not None:
                raise ValueError('prompt, output_schema and see go with op "custom" only')
            return self
        if not (self.prompt or "").strip():
            raise ValueError('op "custom" needs a prompt: the instructions for the AI')
        if len(self.prompt or "") > MAX_PROMPT_CHARS:
            raise ValueError(f"prompt is longer than {MAX_PROMPT_CHARS} characters")
        if problems := schema_problems(self.output_schema):
            raise ValueError("; ".join(problems))
        if self.write_back is True:
            raise ValueError("a custom prompt has no fields of its own to write: give write_back a map {output key: field}")
        return self


class EntryAction(_StepBase):
    """Changes an entry without AI: a status op, collection membership, a metadata/data write or a review
    request — or `create` makes one (`entry_type` slug, `title`, `data`, `metadata`, `status` inbox|draft; output
    entry_id/slug). `trash` / `restore` also act on an asset or a resource (`entity_type`; unset, the kind of the
    target's or the triggering item): `entity_slug` / `entity_id`, else the current one — never `entity_query`."""

    kind: Literal["entry"]
    op: Literal[
        "publish",
        "unpublish",
        "archive",
        "trash",
        "restore",
        "add_to_collection",
        "remove_from_collection",
        "set_metadata",
        "set_data",
        "request_review",
        "attach_asset",
        "create",
    ]
    entity_type: Literal["entry", "asset", "resource"] = "entry"  # trash / restore also act on an asset or resource
    entity_id: str | None = None
    entity_slug: str | None = None
    entity_query: dict[str, Any] | None = None  # find exactly one entry (target-selector vocabulary; values may be templates)
    if_none: Literal["fail", "skip"] | None = None  # entity_query matched nothing: fail the step (unset/"fail") or skip it quietly
    collection_id: str | None = None  # for add_to_collection / remove_from_collection…
    collection_slug: str | None = None  # …preferred: a collection slug/name (may be a $event.* template)
    metadata: dict[str, Any] | None = None  # for set_metadata: keys merged into metadata_json (values may be templates)
    data: dict[str, Any] | None = None  # for set_data: schema fields merged into data_json (validated; values may be templates)
    asset: str | None = None  # for attach_asset: the asset's id or slug (may be a template to a step's asset)
    role: str | None = None  # for attach_asset: the role to link it in (hero, cover…)
    reason: str | None = None  # for request_review: why it needs review, added to metadata_json.review_reasons (may be a template)
    entry_type: str | None = None  # for create: the new entry's type (a slug; may be a template)
    title: str | None = None  # for create (may be a template)
    status: Literal["inbox", "draft"] | None = None  # for create: default draft; publishing is a following publish step
    id: str | None = None

    @model_validator(mode="after")
    def _create_shape(self):
        if self.op == "create":
            if not (self.entry_type or "").strip() or not (self.title or "").strip():
                raise ValueError("create needs an entry_type (slug) and a title")
            if self.entity_id or self.entity_slug or self.entity_query:
                raise ValueError("create makes a new entry: drop entity_id / entity_slug / entity_query")
        elif self.entry_type is not None or self.title is not None or self.status is not None:
            raise ValueError("entry_type, title and status go with op create only")
        return self

    # Shapes that can only fail at run time are refused here, so the REST write gate (422) and an agent's draft
    # name them with their path (actions[0].entity_type) — see services/automation/actions/entry.py.
    @field_validator("entity_type")
    @classmethod
    def _item_ops_only(cls, value: str, info: ValidationInfo) -> str:
        op = info.data.get("op")  # absent when `op` itself failed — that error stands alone
        if op is not None and value != "entry" and op not in ("trash", "restore"):
            raise ValueError(f"only trash and restore act on an {value}; “{op}” acts on entries (drop entity_type)")
        return value

    @field_validator("entity_query")
    @classmethod
    def _entity_query_finds_entries(cls, value: dict[str, Any] | None, info: ValidationInfo) -> dict[str, Any] | None:
        kind = info.data.get("entity_type", "entry")
        if value is not None and kind != "entry":
            raise ValueError(
                f"entity_query finds entries only — a {kind} step acts on the current {kind} (an asset/resource target's "
                f"row, or the triggering one), or one named by entity_slug / entity_id"
            )
        return value


class EmitEventAction(_StepBase):
    """Sends a Marvin event (`event`: an emittable event name) for other workflows and subscribers. A workspace's own
    `custom.<name>` event carries `payload` (its registered fields, values may be templates) and an optional `message`."""

    kind: Literal["emit_event"]
    event: str  # internal event name to re-emit
    entity_id: str | None = None
    payload: dict[str, Any] | None = None  # custom.<name> events: {field: value}, held to the event's registered fields
    message: str | None = None  # custom.<name> and site events: the event's text (may be a template)
    id: str | None = None


MAX_CHOICES = 8


class ApprovalAction(_StepBase):
    """Waits for a person to approve or deny. The run parks here, `approvers` (members at that workspace role or above)
    are asked `message`, and the run goes on from the next step once one decides — or when it expires — with
    ${steps.<id>.output.decision}: approved | denied | expired | stale (the entry changed after it was asked). An
    integration action that requires approval may follow it (it runs only when approved). `choices` (2–8 labels,
    templates allowed, or a template to a list, e.g. ${steps.ideas.output.titles}) asks them to pick one: approving
    sets ${steps.<id>.output.choice} (the label) and .choice_index (from 0); denying picks none. `image` shows a picture
    with the question — a template to a picture URL, e.g. a step's generated asset (${steps.cover.output.images.0.asset.url})
    or ${entry.image} — so the approver sees what they decide on."""

    kind: Literal["approval"]
    message: str  # what the approvers are asked (templates allowed)
    approvers: Literal["editor", "admin"] = "editor"
    expires_in_hours: int = Field(default=72, ge=1, le=720)
    choices: list[str] | str | None = None  # 2–8 labels, or one template to a list
    # A picture shown with the question: a template to an asset URL (${steps.cover.output.images.0.asset.url}, ${entry.image}).
    image: str | None = None
    id: str | None = None

    @field_validator("choices")
    @classmethod
    def _two_to_eight_choices(cls, value):
        if isinstance(value, list) and not 2 <= len(value) <= MAX_CHOICES:
            raise ValueError(f"choices needs 2 to {MAX_CHOICES} to pick from (or a template to a list)")
        return value


class HandlerAction(_StepBase):
    """Runs an allowlisted internal job (`task`), e.g. request_site_rebuild."""

    kind: Literal["handler"]
    task: str  # allowlisted scheduled-task handler
    config: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None


class WebhookAction(_StepBase):
    """Calls one of the workspace's outgoing webhooks (`webhook_id`), or a raw `url`, with a JSON `body`."""

    kind: Literal["webhook"]
    webhook_id: str | None = None  # a configured workspace webhook…
    url: str | None = None  # …or (advanced) a raw url
    method: str | None = None  # raw-url form only: GET | POST (default) | PUT | PATCH | DELETE
    body: dict[str, Any] = Field(default_factory=dict)
    secret_ref: str | None = None  # optional secret ref, sent as `Authorization: <auth_scheme> <secret>`
    auth_scheme: str | None = None  # Bearer (default) | Token | … — some APIs (Buttondown) reject Bearer
    id: str | None = None


class IntegrationAction(_StepBase):
    """Runs a connected integration's action (`integration`: its slug, `action`: the action key) with `args` — or,
    with `capability` instead of `action`, whichever of its actions offers that (`notify`: `title`, `body`). An image.*
    action's pictures are kept as assets (output `images: [{asset}]`); `attach_as` links them to the run's entry, `tags` tags them.
    `source` (an image.* action that works on a picture, e.g. image.edit) is that picture, as a media step's source: it
    is passed as image_b64 and the result is kept as a version of it."""

    kind: Literal["integration"]
    integration: str  # the workspace integration's slug
    action: str | None = None  # the provider action key…
    capability: str | None = None  # …or a capability it offers (`notify`), whatever the provider
    args: dict[str, Any] = Field(default_factory=dict)  # values may be templates; result → $steps.<id>.output
    # An image.* action's pictures are kept as assets (output `images: [{asset}]`); attach_as links them to the run's
    # entry in this role.
    attach_as: str | None = None
    tags: list[str] | None = None  # …and these tags put on them
    source: str | None = None  # the picture an image.* action works on (an asset, ${entry.image}, role:<role>, a step's)
    id: str | None = None

    @model_validator(mode="after")
    def _action_or_capability(self):
        if not (self.action or self.capability):
            raise ValueError("an integration step needs `action` (the provider action key) or `capability` (e.g. notify)")
        return self


# What each media op takes beside source / attach_as — the media step's executor reads the same table
# (services/automation/actions/media.py).
MEDIA_OP_ARGS: dict[str, tuple[str, ...]] = {
    "resize": ("width", "height", "fit", "format", "quality"),
    "crop": ("aspect", "focus", "format", "quality"),
    "convert": ("format", "quality"),
    "grade": ("preset", "format", "quality"),
    "inspect": (),
    "palette": ("colors",),
    "render": ("template", "html", "width", "height", "fields", "images", "format", "quality"),
    "extract_text": ("ocr",),
    "pages": ("page", "count", "width", "format", "quality"),
    "find_sensitive": ("find",),
    "redact": ("boxes", "find", "format", "quality"),
    "zip": ("files", "name"),
    "watermark": ("text", "logo", "position", "opacity", "size", "format", "quality"),
}
MEDIA_ARG_FIELDS = (
    *("width", "height", "fit", "aspect", "focus", "format", "quality", "preset", "colors", "template", "html", "fields", "images"),
    *("ocr", "page", "count", "find", "boxes", "files", "name", "text", "logo", "position", "opacity", "size"),
)
MEDIA_ASPECT_PATTERN = r"^\s*[1-9]\d{0,2}\s*[:x/]\s*[1-9]\d{0,2}\s*$"


class MediaAction(_StepBase):
    """Makes an image from an image or a PDF page, or reads one (facts, colours, text). `resize`, `crop`, `convert` and `grade` save a
    NEW asset (the original is never changed) with its lineage and return `asset` {id, slug, url, width, height}; the
    same op on the same picture reuses it. `inspect` returns width, height, orientation, aspect, sharpness; `palette`
    returns colors. `render` fills a template (`template`: a built-in one, or the step's own `html`) with `fields` and
    `images` and screenshots it into a new asset. `source`: an asset id or slug (default ${asset.id}), ${steps.<id>.output.asset.id}, or role:<role>
    (the entry's asset in that role). `attach_as` links the new asset to the run's entry in that role. `extract_text`
    reads a PDF's text page by page (a scanned page, or a picture, by the vision model: `ocr`); `pages` saves PDF pages
    as pictures; `find_sensitive` lists faces, plates and personal text (vision); `redact` blurs them (or `boxes`); `zip`
    bundles `files` (entries with their files, or assets) and a manifest.json into a new ZIP asset; `watermark` lays
    `text` and/or a `logo` over a copy (position, opacity, size)."""

    kind: Literal["media"]
    op: Literal[
        "resize", "crop", "convert", "grade", "inspect", "palette", "render", "extract_text", "pages", "find_sensitive", "redact", "zip", "watermark"
    ]
    source: str | None = None  # default ${asset.id}
    width: int | None = Field(default=None, ge=1, le=10_000)  # resize: at most this wide (never upscales)
    height: int | None = Field(default=None, ge=1, le=10_000)  # resize: at most this tall
    fit: Literal["inside", "cover"] | None = None  # resize: inside (default) keeps it all; cover fills width × height
    aspect: str | None = Field(default=None, pattern=MEDIA_ASPECT_PATTERN)  # crop: 1:1, 4:5, 16:9…
    focus: Literal["center", "subject"] | None = None  # crop: subject asks a vision model where the subject is
    format: Literal["jpeg", "png", "webp", "pdf"] | None = None  # convert; re-encodes any op that makes an image; pdf: a printed render
    quality: int | None = Field(default=None, ge=1, le=100)  # jpeg / webp quality (default 90)
    preset: str | None = None  # grade: a colour preset (built-in or the workspace's)
    colors: int | None = Field(default=None, ge=1, le=16)  # palette: how many (default 5)
    template: str | None = None  # render: a built-in template (card, quote, poster, trading-card, meme, side-by-side, comic-4, newspaper)
    html: str | None = Field(default=None, max_length=200_000)  # render: or the step's own HTML/CSS ({{ fields.x }}, {{ images.y }})
    fields: dict[str, Any] | None = None  # render: the template's text (templates allowed)
    # render: picture name → an asset (id, slug, URL, ${steps.<id>.output.asset.id}, role:<role>) — or a list of them, or a
    # collect step's ${steps.<id>.output.rows} (the grid and moodboard templates)
    images: dict[str, str | list[str]] | None = None
    ocr: Literal["auto", "never"] | None = None  # extract_text: read a scanned page or a picture with the vision model (auto)
    page: int | None = Field(default=None, ge=1, le=10_000)  # pages: the first page to save (default 1)
    count: int | None = Field(default=None, ge=1, le=10)  # pages: how many from `page` (default 1)
    find: list[Literal["face", "plate", "text"]] | None = None  # find_sensitive / redact: what to look for (default all)
    boxes: list[Any] | str | None = None  # redact: regions [{box: [x, y, w, h]}] or boxes (0..1), e.g. ${steps.x.output.regions}
    files: list[Any] | str | None = None  # zip: a gather step's rows (entries bring their files) or assets, e.g. ${steps.x.output.rows}
    name: str | None = Field(default=None, max_length=200)  # zip: the archive's name (templates allowed)
    text: str | None = Field(default=None, max_length=200)  # watermark: its text (templates allowed, e.g. © ${site.url})
    logo: str | None = None  # watermark: a picture laid over it too (an asset id or slug — a transparent PNG)
    position: Literal["bottom-right", "bottom-left", "top-right", "top-left", "center", "tiled"] | None = None  # watermark
    opacity: int | None = Field(default=None, ge=1, le=100)  # watermark: percent (default 60)
    size: int | None = Field(default=None, ge=1, le=100)  # watermark: its width, percent of the picture's (default 25)
    attach_as: str | None = None  # link the new asset to the run's entry in this role
    attach_to: str | None = None  # …or to this entry (id or slug; e.g. ${steps.draft.output.entry_id}, one the run created)
    tags: list[str] | None = None  # tag the new asset (e.g. web-sizes), so the library and smart collections can find them
    id: str | None = None

    @model_validator(mode="after")
    def _op_shape(self):
        takes = MEDIA_OP_ARGS[self.op]
        stray = [k for k in MEDIA_ARG_FIELDS if getattr(self, k) is not None and k not in takes]
        if stray:
            raise ValueError(
                f"{', '.join(stray)} {'goes' if len(stray) == 1 else 'go'} with another op: {self.op} takes {', '.join(takes) or 'nothing'}"
            )
        if self.op == "watermark" and not (self.text or self.logo):
            raise ValueError("a watermark needs text or a logo")
        if self.format == "pdf" and self.op != "render":
            raise ValueError("format pdf is for a render (printed to a PDF); an image op makes jpeg, png or webp")
        if self.op == "resize" and not (self.width or self.height):
            raise ValueError("resize needs a width or a height")
        if self.op == "resize" and self.fit == "cover" and not (self.width and self.height):
            raise ValueError("fit cover needs both a width and a height")
        if self.op == "crop" and not self.aspect:
            raise ValueError("crop needs an aspect like 1:1, 4:5 or 16:9")
        if self.op == "convert" and not self.format:
            raise ValueError("convert needs a format: jpeg, png or webp")
        if self.op == "grade" and not (self.preset or "").strip():
            raise ValueError("grade needs a preset")
        if self.op == "render":
            if bool(self.template) == bool(self.html):
                raise ValueError("render needs a template (a built-in one) or its own html — one of them")
            if self.source:
                raise ValueError("render takes its pictures in `images` (name → asset), not `source`")
        if self.attach_to and not self.attach_as:
            raise ValueError("attach_to names the entry to link the new asset to: it goes with attach_as (the role)")
        if self.op in ("inspect", "palette") and (self.attach_as or self.tags):
            raise ValueError(f"{self.op} makes no image, so there is nothing to attach_as or tag")
        return self


class CollectAction(_StepBase):
    """Gathers the entries, assets or resources a query matches into one output (many → one). For a digest, a report, a
    contact sheet: `entity` and `query` are a target's (dates may be relative: -7d, now); output `rows` (each
    like ${entry.*} / ${asset.*}, plus any extra `fields` paths such as data.body), `count`, `total`, and `text` — a ready
    list for an AI prompt. Asset queries leave versions out unless they ask, as targets do. `only_invalid` (entries) keeps
    the ones breaking their type's current rules, each with `problem`."""

    kind: Literal["collect"]
    entity: Literal["entry", "asset", "resource"] = "entry"
    query: dict[str, Any] = Field(default_factory=dict)
    fields: list[str] | None = None  # extra paths per row beyond the defaults, e.g. data.body, metadata.price
    limit: int = Field(default=25, ge=1, le=250)  # at most this many rows (the target cap)
    only_invalid: bool = False  # entries: only those breaking their type's current rules, each with its `problem`
    id: str | None = None


class FetchAction(_StepBase):
    """Reads a web address, or checks the links in a text — public addresses only. `url`: output `status`, `ok`,
    `content_type`, `title`, `text` and `json` (an API's answer), and with `find` (phrases, any case) `found`; `links`
    (a text, e.g. ${entry.data.body}; relative links resolve against `base`, default the site URL): output `checked`,
    `broken` [{url, status, error}], `broken_count` and `text`. A dead link or server is output, never a failed step; a
    dry run doesn't fetch."""

    kind: Literal["fetch"]
    url: str | None = None
    method: Literal["GET", "HEAD"] = "GET"
    find: str | list[str] | None = None  # phrases to look for on the page, ignoring case → output `found`
    links: str | None = None
    base: str | None = None
    id: str | None = None

    @model_validator(mode="after")
    def _one_mode(self):
        if bool(self.url) == (self.links is not None):
            raise ValueError("a fetch step takes `url` (one address) or `links` (a text whose links to check)")
        return self


class WaitAction(_StepBase):
    """Waits, then goes on — the run is kept and resumed later. `for`: a span (30m, 12h, 3d, 2w); or `until`: a date
    or a date and time (e.g. ${entry.data.event_date}, or one every entry has: ${entry.publish_at}, ${entry.expire_at},
    ${entry.published_at}), moved by `offset` (-7d: a week before) and, for a date, at `at`
    (default 09:00) — in the workspace's time zone. A moment already past goes on at once (output late). Output
    waited_until, resumed_at. A year at most; the entry going to the Trash, the workflow switched off or this step
    removed, cancels the wait (an edit elsewhere in the workflow applies when it goes on)."""

    kind: Literal["wait"]
    for_: str | None = Field(default=None, alias="for", pattern=r"^\s*\d{1,4}\s*[mhdwMHDW]\s*$")
    until: str | None = None
    offset: str | None = Field(default=None, pattern=r"^\s*[+-]?\d{1,4}\s*[mhdwMHDW]\s*$")
    at: str | None = Field(default=None, pattern=r"^\s*([01]?\d|2[0-3]):[0-5]\d\s*$")
    id: str | None = None

    @model_validator(mode="after")
    def _for_or_until(self):
        if bool(self.for_) == bool(self.until):
            raise ValueError("a wait step takes `for` (a span, e.g. 3d) or `until` (a date), one of them")
        if self.for_ and (self.offset or self.at):
            raise ValueError("offset and at go with `until`, not `for`")
        return self


# A repeat's inner steps: any step but a wait, an approval or another repeat (a run can't park mid-loop).
RepeatStep = Annotated[
    OperationAction | EntryAction | EmitEventAction | HandlerAction | WebhookAction | IntegrationAction | MediaAction | CollectAction | FetchAction,
    Field(discriminator="kind"),
]
MAX_REPEAT_ITEMS = 25
MAX_REPEAT_STEPS = 5
# Names a repeat's item can't take: they'd hide what a run already reads.
RESERVED_ITEM_NAMES = frozenset({"event", "entry", "asset", "resource", "steps", "previous", "input", "site", "error", "depth", "each"})


class RepeatAction(_StepBase):
    """Runs its `steps` (1–5) once per item of `for_each` (e.g. ${steps.people.output.rows}): the item is ${<as>.*}
    (as: default item), its place ${each.number}/${each.count}; inner steps read each other's output for that item. No
    wait/approval/repeat inside. limit ≤ 25; on_item_error stop (default) or continue. Output count, done, failed,
    results, errors."""

    kind: Literal["repeat"]
    for_each: str | list
    as_: str = Field(default="item", alias="as", pattern=r"^[a-z][a-z0-9_]{0,30}$")
    steps: list[RepeatStep] = Field(min_length=1, max_length=MAX_REPEAT_STEPS)
    limit: int = Field(default=MAX_REPEAT_ITEMS, ge=1, le=MAX_REPEAT_ITEMS)
    on_item_error: Literal["stop", "continue"] = "stop"
    id: str | None = None

    @field_validator("as_")
    @classmethod
    def _not_reserved(cls, name: str) -> str:
        if name in RESERVED_ITEM_NAMES:
            raise ValueError(f"“{name}” is already something a run reads: name the item something else (person, row, item)")
        return name


ACTION_MODELS: dict[str, type[_DefnBase]] = {
    "operation": OperationAction,
    "entry": EntryAction,
    "emit_event": EmitEventAction,
    "handler": HandlerAction,
    "webhook": WebhookAction,
    "integration": IntegrationAction,
    "approval": ApprovalAction,
    "media": MediaAction,
    "collect": CollectAction,
    "fetch": FetchAction,
    "wait": WaitAction,
    "repeat": RepeatAction,
}

Action = Annotated[
    OperationAction
    | EntryAction
    | EmitEventAction
    | HandlerAction
    | WebhookAction
    | IntegrationAction
    | ApprovalAction
    | MediaAction
    | CollectAction
    | FetchAction
    | WaitAction
    | RepeatAction,
    Field(discriminator="kind"),
]


# ── Conditions (recursive: a leaf {field, op, value} OR a group {all|any|not}) ─
class Condition(_DefnBase):
    """A leaf `{field, op, value}`, or a group `{all: [...]}` / `{any: [...]}` / `{not: {...}}`."""

    # Leaf:
    field: str | None = None
    op: str | None = None
    value: Any = None
    # Group (nestable; `not` is a Python keyword → aliased):
    all: list[Condition] | None = None
    any: list[Condition] | None = None
    not_: Condition | None = Field(default=None, alias="not")


# ── Target selector (the "FROM" clause) ───────────────────────────────────────
class Target(_DefnBase):
    """Run on a query of entries, assets or resources instead of the trigger's one item: each match runs the steps
    as `entry`, `asset` or `resource` (`query`: that entity's keys, see the authoring guide's target section)."""

    entity: Literal["entry", "asset", "resource"] = "entry"
    query: dict[str, Any] = Field(default_factory=dict)


# ── The whole definition ──────────────────────────────────────────────────────
class AutomationDefinition(_DefnBase):
    trigger: Trigger | None = None
    target: Target | None = None
    # A top-level list is an implicit AND; a single group dict is also accepted (JSON-mode advanced).
    conditions: list[Condition] | Condition | None = None
    actions: list[Action] = Field(default_factory=list)
    # Steps run when a step of `actions` fails, in the same run and on the same entry, with the failure
    # as `${error.*}` (message, code, step, kind, at). The run still counts as failed.
    on_failure: list[Action] | None = None
    # How a failing integration step is handled. "policy" (the default) applies the integration's own
    # error policy — send the entry to review, retry later, alert admins, or carry on. "fail" opts this
    # workflow out: its integration steps fail as plain failures (the connection's admin alert still
    # fires). A workflow with on_failure steps runs those instead of the policy either way.
    integration_errors: Literal["policy", "fail"] | None = None

    @field_validator("on_failure")
    @classmethod
    def _no_waiting_on_failure(cls, steps):
        if steps and any(getattr(s, "kind", None) == "approval" for s in steps):
            raise ValueError("an approval step can't run in on_failure: the failed run ends there")
        return steps

    @model_validator(mode="before")
    @classmethod
    def _default_trigger_type(cls, data: Any) -> Any:
        """A trigger without an explicit ``type`` means "event" (the engine's default). The
        discriminated union needs the tag present, so fill it in before validation."""
        if isinstance(data, dict):
            trig = data.get("trigger")
            if isinstance(trig, dict) and "type" not in trig:
                data = {**data, "trigger": {**trig, "type": "event"}}
        return data


Condition.model_rebuild()
for _step_model in ACTION_MODELS.values():
    _step_model.model_rebuild()


def definition_json_schema() -> dict:
    """The definition's JSON Schema — advertised by /api/automations/options so the builder + SDK
    mirror one declaration instead of hand-maintaining a parallel shape."""
    return AutomationDefinition.model_json_schema(by_alias=True)
