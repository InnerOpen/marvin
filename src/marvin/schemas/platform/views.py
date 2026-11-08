"""Views a workspace's installed packages bring (a story's timeline), as the view page and an entry's page read them."""

from pydantic import Field

from marvin.schemas._marvin import _MarvinModel


class ViewSummary(_MarvinModel):
    """One view in the list."""

    slug: str
    name: str
    kind: str = ""
    """How it draws the entry: `timeline` is the one kind so far."""
    entry_type: str = ""
    """Slug of the entry type it is a view of."""
    package: str
    """Slug of the package that brings it."""
    package_name: str


class ViewRead(ViewSummary):
    """A view with its definition (spine, lanes, actions), as the view page draws it."""

    definition: dict = Field(default_factory=dict)
