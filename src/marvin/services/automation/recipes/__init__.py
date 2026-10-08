"""The Workflow Library's one store: recipe definitions, their setup-variable schemas and the catalogue.

Every file here ships with the package (hatchling includes package data), so the authoring guide, the
``draft_workflow`` tool and the docs read the same recipes:

* ``<id>.json`` — a whole workflow document ``{"name", "definition"}`` in Marvin's own format, with
  ``{{lower_case}}`` setup placeholders where a workspace reference is needed (services/automation/library.py);
* ``<id>.vars.json`` — ``{"recipe", "variables": {name: {type, description, example?}}}``, the placeholders' schema;
* ``catalogue.json`` — the metadata for every recipe (status, prerequisites, side effects, …) and the
  capability gaps the roadmap ranks. Metadata stays out of the workflow JSON.

docs/workflow-library/ explains the library and renders ``catalogue.md`` from the catalogue
(scripts/render_workflow_library.py); tests/test_workflow_library.py holds every recipe to its status.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..library import configure

if TYPE_CHECKING:
    from ..authoring import WorkspaceRefs

DIR = Path(__file__).parent

# Statuses a recipe may be offered under (the guide's examples, a Library copy): it validates and runs today.
RUNNABLE_STATUSES = frozenset({"verified-current", "supported-after-configuration"})


class UnknownRecipe(KeyError):
    pass


@lru_cache(maxsize=1)
def catalogue() -> dict:
    return json.loads((DIR / "catalogue.json").read_text(encoding="utf-8"))


def entries() -> list[dict]:
    """Every catalogue entry, in catalogue order."""
    return list(catalogue()["recipes"])


def entry(recipe_id: str) -> dict:
    for item in catalogue()["recipes"]:
        if item["id"] == recipe_id:
            return item
    raise UnknownRecipe(recipe_id)


def workflow_recipe_ids() -> list[str]:
    """The recipes that are workflows with a definition file (not configuration-only, not ideas)."""
    return [r["id"] for r in catalogue()["recipes"] if r["shape"] == "workflow"]


def load_recipe(recipe_id: str) -> dict:
    """The recipe's whole workflow document ``{name, definition}``, placeholders included."""
    path = DIR / f"{recipe_id}.json"
    if not path.exists():
        raise UnknownRecipe(recipe_id)
    return json.loads(path.read_text(encoding="utf-8"))


def load_vars(recipe_id: str) -> dict[str, dict]:
    """The recipe's setup variables ``{name: {type, description, example?}}`` (empty when it has none)."""
    path = DIR / f"{recipe_id}.vars.json"
    if not path.exists():
        raise UnknownRecipe(recipe_id)
    return dict(json.loads(path.read_text(encoding="utf-8")).get("variables") or {})


def instantiate(recipe_id: str, values: dict[str, Any]) -> dict:
    """The recipe's document with its placeholders substituted (typed, templates untouched) — what a Library
    copy or ``draft_workflow(recipe=…)`` hands to the write path. Raises RecipeConfigError on a bad value."""
    return configure(load_recipe(recipe_id), values, load_vars(recipe_id))


def missing_prerequisites(item: dict, refs: WorkspaceRefs) -> list[str]:
    """Why this workspace can't run the recipe as it stands: a provider it needs that isn't connected (and
    enabled), an AI operation it can't run here, a job not on the allowlist. Empty: it is offered."""
    reasons: list[str] = []
    connected = {i["provider"] for i in refs.integrations if i.get("enabled")}
    for need in (item.get("prerequisites") or {}).get("integrations") or []:
        if need["provider"] not in connected:
            reasons.append(f"needs a connected {need['provider']} integration")
    requires = item.get("requires") or {}
    for op in requires.get("operations") or []:
        if refs.operations is None:
            reasons.append("needs AI operations, which can't run from workflows here")
            break
        if op not in {o["op"] for o in refs.operations}:
            reasons.append(f"needs the AI operation {op}")
    allowed = {h["task"] for h in refs.handlers}
    for task in requires.get("handlers") or []:
        if task not in allowed:
            reasons.append(f"needs the job {task}")
    return reasons


def offered(refs: WorkspaceRefs) -> list[dict]:
    """The workflow recipes this workspace can draft today: runnable status, and every prerequisite met."""
    return [r for r in catalogue()["recipes"] if r["shape"] == "workflow" and r["status"] in RUNNABLE_STATUSES and not missing_prerequisites(r, refs)]


def example(item: dict) -> dict:
    """A recipe as the authoring guide presents it: the definition with its placeholders, and what each
    placeholder wants, so a model fills them from the workspace's own names."""
    doc = load_recipe(item["id"])
    return {
        "recipe": item["id"],
        "title": item["title"],
        "outcome": item["outcome"],
        "status": item["status"],
        "definition": doc["definition"],
        "setup_variables": load_vars(item["id"]),
        "draft": f'draft_workflow(recipe="{item["id"]}", vars={{…}}) fills the {{{{placeholders}}}} and saves it switched off.',
    }
