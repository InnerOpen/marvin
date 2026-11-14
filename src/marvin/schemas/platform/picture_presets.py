"""Picture presets (services/assets/picture_presets.py): a named, ordered recipe of picture treatments kept on an entry type
beside its templates, and the request and answer of treating pictures with one (POST /assets/apply-preset)."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from marvin.schemas._marvin import _MarvinModel
from marvin.schemas.group.automation_definition import MEDIA_ASPECT_PATTERN, MEDIA_FOCUS_PATTERN, MEDIA_GRADE_SETTINGS, MEDIA_OP_ARGS

PresetSlug = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")]
PRESET_OPS = ("crop", "resize", "grade", "convert")
MAX_PRESET_STEPS = 12


class PicturePresetStep(_MarvinModel):
    """One treatment, with the arguments a workflow's media step takes for that op: crop (aspect, focus center | subject |
    "x,y"), resize (width, height, fit), grade (a named grade preset and/or brightness, contrast, saturation, warmth,
    vignette), convert (format, quality)."""

    op: Literal["crop", "resize", "grade", "convert"]
    aspect: str | None = Field(default=None, pattern=MEDIA_ASPECT_PATTERN)
    focus: str | None = Field(default=None, pattern=MEDIA_FOCUS_PATTERN)
    width: int | None = Field(default=None, ge=1, le=10_000)
    height: int | None = Field(default=None, ge=1, le=10_000)
    fit: Literal["inside", "cover"] | None = None
    preset: str | None = None
    """grade: a named grade (built-in, or the workspace's media presets)."""
    brightness: float | None = Field(default=None, ge=0, le=3)
    """grade: 1 leaves it as it is, 1.1 is 10% brighter, 0.9 10% darker. Contrast and saturation alike."""
    contrast: float | None = Field(default=None, ge=0, le=3)
    saturation: float | None = Field(default=None, ge=0, le=3)
    warmth: float | None = Field(default=None, ge=0.5, le=1.5)
    """grade: above 1 warmer (more red, less blue), below 1 cooler."""
    vignette: float | None = Field(default=None, ge=0, le=1)
    """grade: how much the corners darken (0 none, 1 black)."""
    format: Literal["jpeg", "png", "webp"] | None = None
    quality: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def _shape(self):
        takes = MEDIA_OP_ARGS[self.op]
        given = [
            k
            for k in ("aspect", "focus", "width", "height", "fit", "preset", *MEDIA_GRADE_SETTINGS, "format", "quality")
            if getattr(self, k) is not None
        ]
        stray = [k for k in given if k not in takes]
        if stray:
            raise ValueError(f"{', '.join(stray)} {'goes' if len(stray) == 1 else 'go'} with another treatment: {self.op} takes {', '.join(takes)}")
        if self.op == "crop" and not self.aspect:
            raise ValueError("crop needs an aspect like 1:1, 4:5 or 16:9")
        if self.op == "resize" and not (self.width or self.height):
            raise ValueError("resize needs a width or a height")
        if self.op == "resize" and self.fit == "cover" and not (self.width and self.height):
            raise ValueError("fit cover needs both a width and a height")
        if self.op == "convert" and not self.format:
            raise ValueError("convert needs a format: jpeg, png or webp")
        if self.op == "grade" and not (self.preset or "").strip() and all(getattr(self, k) is None for k in MEDIA_GRADE_SETTINGS):
            raise ValueError(f"grade needs a preset or a setting ({', '.join(MEDIA_GRADE_SETTINGS)})")
        return self


class PicturePreset(_MarvinModel):
    """A named, ordered recipe of treatments, kept on an entry type (``picturePresets``) so its templates can name it
    (``picture_preset``) and a package can bring it with the type. Applied, it makes ONE new picture from each original
    (all the steps in one pass, encoded once), kept as a version of it; the original is never changed."""

    slug: PresetSlug
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    description: str | None = Field(default=None, max_length=500)
    steps: list[PicturePresetStep] = Field(min_length=1, max_length=MAX_PRESET_STEPS)


class ApplyPresetRequest(_MarvinModel):
    """Treat pictures with one of an entry type's picture presets (or the preset a template names). ``assets`` treats those
    pictures; ``entries`` treats each entry's picture and puts the treated one in the template's place for it (the role,
    featured by default, and the asset field). ``preview`` (the default) answers what would be made and changes nothing;
    with ``preview: false`` the work starts in the background and the answer is the job (GET /assets/apply-preset/jobs/{id})."""

    entry_type: str
    """The entry type's slug or id."""
    preset: str | None = None
    """The preset's slug; or name a template and its preset is used."""
    template: str | None = None
    assets: list[str] = Field(default_factory=list)
    """Asset ids or slugs. A version made from another picture is treated from its original."""
    entries: list[str] = Field(default_factory=list)
    """Entry ids or slugs: each gets its picture treated and the treated one in its place."""
    role: str | None = Field(default=None, max_length=40)
    """For entries: the role the treated picture takes (default: the template's treated_role, else featured)."""
    preview: bool = True

    @model_validator(mode="after")
    def _one_of_each(self):
        if not (self.preset or self.template):
            raise ValueError("name a preset, or a template that has one")
        if not (self.assets or self.entries):
            raise ValueError("name the pictures (assets) or the entries to treat")
        if self.assets and self.entries:
            raise ValueError("treat pictures (assets) or entries, not both at once")
        return self


class PresetPicture(_MarvinModel):
    id: str
    name: str
    url: str | None = None


class ApplyPresetRow(_MarvinModel):
    """One picture: ``create`` its treated version, ``reuse`` the one made before (same picture, same steps), or ``skip``."""

    action: Literal["create", "reuse", "skip"]
    source: PresetPicture | None = None
    """The original that is treated (a version asked for is traced back to it)."""
    slug: str | None = None
    """The treated picture's slug: <original>--preset-<hash8>, the same for the same steps on the same picture."""
    treated: PresetPicture | None = None
    """The treated picture, once made (or the one reused)."""
    entry_id: str | None = None
    entry_title: str | None = None
    place: bool = False
    """True when the treated picture will take the entry's role (and its asset field) in place of the original."""
    note: str | None = None


class ApplyPresetResult(_MarvinModel):
    """What a preset would do (preview), or the job doing it."""

    preview: bool
    entry_type: str
    preset: str
    preset_name: str
    steps: str
    """The steps in words: "crop 1:1, grade brightness 1.1, webp"."""
    total: int
    create: int
    reuse: int
    skip: int
    todo: int
    """create + reuse: what a workflow's apply step confirms (`confirm_total`)."""
    rows: list[ApplyPresetRow]
    text: str = ""
    job: "PresetJob | None" = None


class PresetJob(_MarvinModel):
    """A treatment running in the background (one at a time per workspace, the others wait their turn). Lost if the server
    restarts: run it again and what was made is reused."""

    id: str
    state: Literal["queued", "running", "done", "failed"]
    preset: str
    total: int
    done: int = 0
    made: int = 0
    reused: int = 0
    placed: int = 0
    failed: int = 0
    errors: list[str] = Field(default_factory=list)
    """The first few pictures that could not be treated, and why."""
    treated: dict[str, str] = Field(default_factory=dict)
    """Original asset id → treated asset id, as they are made."""
    started_at: str | None = None
    finished_at: str | None = None
    seconds: float | None = None
    text: str = ""


ApplyPresetResult.model_rebuild()
