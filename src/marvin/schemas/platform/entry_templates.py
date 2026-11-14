"""Entry templates (services/entries/templates.py): named presets on an entry type, and the requests and answers of making
entries from pictures with one (POST /entries/from-template) or filling existing entries with one (POST /entries/apply-template)."""

from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from marvin.schemas._marvin import _MarvinModel

TemplateSlug = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")]


class EntryTemplate(_MarvinModel):
    """A named preset for entries of one type, kept on the type (`templates`) and edited in its settings; a package can
    bring them with the type. Text may use the variables {asset.name}, {asset.filename}, {n} (the entry's number in the
    batch, from 1) and {date} (today, YYYY-MM-DD); any other {…} is refused when the template is saved."""

    slug: TemplateSlug
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    description: str | None = Field(default=None, max_length=500)
    """What the template is for, shown where it is picked."""
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)] = "{asset.name}"
    """The entry's title: `{asset.name}` names it after its picture."""
    summary: str | None = Field(default=None, max_length=2000)
    entry_description: str | None = Field(default=None, max_length=20000)
    """The entry's description text (the template's own `description` says what the template is for)."""
    fields: dict[str, Any] = Field(default_factory=dict)
    """Values for the type's fields, by field key; checked against the type's schema when saved."""
    tags: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]] = Field(default_factory=list)
    """Tag names or slugs to add (made when missing)."""
    collections: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]] = Field(default_factory=list)
    """Slugs of (hand-picked) collections to add each entry to."""
    status: Literal["inbox", "draft", "needs_review"] = "inbox"
    """Where a new entry starts. A template never approves or publishes."""
    asset_role: str | None = Field(default="featured", max_length=40)
    """The role the picture is attached with (entry_assets.role), e.g. featured."""
    asset_field: str | None = None
    """The type's asset field the picture is put in (e.g. image), or none."""


class EntriesFromTemplateRequest(_MarvinModel):
    """Make one entry per picture with a template. `preview` (the default) answers what would be made and changes nothing.
    A picture that already has an entry of this type fills that entry instead of making a second one."""

    entry_type: str
    """The entry type's slug or id."""
    template: str
    """The template's slug."""
    assets: list[str] = Field(min_length=1)
    """Asset ids (or slugs), one entry each, in this order ({n} counts in it)."""
    preview: bool = True
    replace: bool = False
    """Fill only empty values (the default), or replace what an existing entry already has."""


class EntriesApplyTemplateRequest(_MarvinModel):
    """Fill existing entries of the template's type with it. `preview` (the default) answers what would change and changes
    nothing; only empty values are filled unless `replace`."""

    entry_type: str
    template: str
    entries: list[str] = Field(min_length=1)
    """Entry ids (or slugs)."""
    preview: bool = True
    replace: bool = False


class EntryTemplatePicture(_MarvinModel):
    id: str
    name: str
    filename: str
    url: str | None = None


class EntryTemplateRow(_MarvinModel):
    """One entry the template would make (`create`) or fill (`fill`), or leaves alone (`skip`, with the reason)."""

    action: Literal["create", "fill", "skip"]
    entry_id: str | None = None
    """The existing entry filled or left alone; after a create, the new entry."""
    title: str
    """The title the entry will have."""
    asset: EntryTemplatePicture | None = None
    """The picture."""
    changes: dict[str, Any] = Field(default_factory=dict)
    """What would be set: title, summary, description, status and the type's fields by key (only what changes)."""
    tags: list[str] = Field(default_factory=list)
    """Tags it would gain."""
    collections: list[str] = Field(default_factory=list)
    """Collections it would join."""
    attach: bool = False
    """True when the picture would be attached (with the template's role)."""
    note: str | None = None
    """Why it is skipped, or what is left out."""
    error: str | None = None
    """What stops it (nothing is made while any row has one)."""


class EntryTemplateResult(_MarvinModel):
    """What a template would do (preview) or did."""

    preview: bool
    entry_type: str
    template: str
    total: int
    """Rows: one per picture or entry asked for."""
    create: int
    fill: int
    skip: int
    todo: int
    """create + fill: what a workflow's create/apply step confirms (`confirm_total`)."""
    errors: int
    """Rows with an error: while there are any, nothing is made or changed."""
    rows: list[EntryTemplateRow]
    created: int = 0
    updated: int = 0
    entry_ids: list[str] = Field(default_factory=list)
    """The entries made or filled, in row order."""
    seconds: float | None = None
    text: str = ""
    """In words: "make 12 artworks, fill 2, leave 1"."""
