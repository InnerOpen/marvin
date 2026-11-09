"""Wizards a workspace's installed packages bring, as the Guided setups page reads them."""

from pydantic import Field

from marvin.schemas._marvin import _MarvinModel


class WizardButton(_MarvinModel):
    """A button an entry's page shows to open a setup on that entry."""

    entry_type: str
    label: str
    key: str
    """The context key the entry fills (a choose step's `as`)."""
    step: str | None = None
    also: dict[str, str] = Field(default_factory=dict)
    """More context from the entry's own fields: {context key: field key}."""


class WizardSummary(_MarvinModel):
    """One guided setup in the list."""

    slug: str
    name: str
    description: str = ""
    steps: int = 0
    package: str
    """Slug of the package that brings it."""
    package_name: str
    button: WizardButton | None = None
    """Where an entry's page offers this setup, when the wizard says so."""


class WizardRead(WizardSummary):
    """A wizard with its definition (title, steps), as the wizard page draws it."""

    definition: dict = Field(default_factory=dict)
