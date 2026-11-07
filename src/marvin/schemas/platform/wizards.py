"""Wizards a workspace's installed packages bring, as the Guided setups page reads them."""

from pydantic import Field

from marvin.schemas._marvin import _MarvinModel


class WizardSummary(_MarvinModel):
    """One guided setup in the list."""

    slug: str
    name: str
    description: str = ""
    steps: int = 0
    package: str
    """Slug of the package that brings it."""
    package_name: str


class WizardRead(WizardSummary):
    """A wizard with its definition (title, steps), as the wizard page draws it."""

    definition: dict = Field(default_factory=dict)
