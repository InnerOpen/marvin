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

Installed integrations add their own (SDK 0.9.0 ``IntegrationProvider.recipes``): each joins the Library as
``<provider>.<id>``, catalogue-shaped, with a ``source`` naming the plugin, offered once that provider is connected.
One is taken only if the SDK's ``check_recipe`` passes and its definition, filled with each variable's example, has
no structural issue; anything else is skipped with a warning, never shown and never breaking the Library.
"""

from __future__ import annotations

import copy
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..library import RecipeConfigError, configure

if TYPE_CHECKING:
    from ..authoring import WorkspaceRefs

DIR = Path(__file__).parent
logger = logging.getLogger(__name__)

# Statuses a recipe may be offered under (the guide's examples, a Library copy): it validates and runs today.
RUNNABLE_STATUSES = frozenset({"verified-current", "supported-after-configuration"})


class UnknownRecipe(KeyError):
    pass


class RecipeUnavailable(Exception):
    """The recipe exists but isn't offered in this workspace; `reasons` say why (a provider that isn't
    connected, a status that doesn't run here)."""

    def __init__(self, recipe_id: str, reasons: list[str]):
        super().__init__(f"{recipe_id}: {'; '.join(reasons)}")
        self.recipe_id = recipe_id
        self.reasons = reasons


@lru_cache(maxsize=1)
def catalogue() -> dict:
    return json.loads((DIR / "catalogue.json").read_text(encoding="utf-8"))


def entries() -> list[dict]:
    """Every recipe: the catalogue's, in catalogue order, then the installed integrations'."""
    return [*catalogue()["recipes"], *(p["entry"] for p in plugin_recipes().values())]


def entry(recipe_id: str) -> dict:
    for item in catalogue()["recipes"]:
        if item["id"] == recipe_id:
            return item
    if recipe_id in (plugins := plugin_recipes()):
        return plugins[recipe_id]["entry"]
    raise UnknownRecipe(recipe_id)


def workflow_recipe_ids() -> list[str]:
    """The recipes that are workflows with a definition file (not configuration-only, not ideas)."""
    return [r["id"] for r in catalogue()["recipes"] if r["shape"] == "workflow"]


def load_recipe(recipe_id: str) -> dict:
    """The recipe's whole workflow document ``{name, definition}``, placeholders included."""
    if recipe_id in (plugins := plugin_recipes()):
        return copy.deepcopy(plugins[recipe_id]["document"])
    path = DIR / f"{recipe_id}.json"
    if not path.exists():
        raise UnknownRecipe(recipe_id)
    return json.loads(path.read_text(encoding="utf-8"))


def load_vars(recipe_id: str) -> dict[str, dict]:
    """The recipe's setup variables ``{name: {type, description, example?}}`` (empty when it has none)."""
    if recipe_id in (plugins := plugin_recipes()):
        return copy.deepcopy(plugins[recipe_id]["variables"])
    path = DIR / f"{recipe_id}.vars.json"
    if not path.exists():
        raise UnknownRecipe(recipe_id)
    return dict(json.loads(path.read_text(encoding="utf-8")).get("variables") or {})


def recipe_version(recipe_id: str) -> str:
    """A short fingerprint of the recipe as it ships now (its workflow and its setup variables): stored on a workflow
    made from it, so a later change to the recipe shows as "the recipe has changed since"."""
    import hashlib

    entry(recipe_id)  # a catalogue id, or UnknownRecipe — never a path someone typed
    doc = {"recipe": load_recipe(recipe_id), "vars": load_vars(recipe_id)}
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()[:16]


def instantiate(recipe_id: str, values: dict[str, Any]) -> dict:
    """The recipe's document with its placeholders substituted (typed, templates untouched) — what a Library
    copy or ``draft_workflow(recipe=…)`` hands to the write path. Raises RecipeConfigError on a bad value."""
    return configure(load_recipe(recipe_id), values, load_vars(recipe_id))


def missing_prerequisites(item: dict, refs: WorkspaceRefs) -> list[str]:
    """Why this workspace can't run the recipe as it stands: a provider it needs that isn't connected (and
    enabled), an AI operation it can't run here, a job not on the allowlist. Empty: it is offered."""
    reasons: list[str] = []
    connected = {i["provider"] for i in refs.integrations if i.get("enabled")}
    able = {c for i in refs.integrations if i.get("enabled") for c in (i.get("capabilities") or [])}
    for need in (item.get("prerequisites") or {}).get("integrations") or []:
        # A provider by name (Buttondown, n8n…), or any connected integration that can do something (notify).
        if need.get("capability"):
            if need["capability"] not in able:
                reasons.append(f"needs a connected integration that can {need['capability']} ({need.get('examples') or 'Slack or Apprise'})")
        elif need["provider"] not in connected:
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
    return [r for r in entries() if r["shape"] == "workflow" and r["status"] in RUNNABLE_STATUSES and not missing_prerequisites(r, refs)]


def unavailable_reasons(item: dict, refs: WorkspaceRefs) -> list[str]:
    """Why this workspace isn't offered the recipe — empty when it is (see ``offered``)."""
    if item["shape"] == "workflow" and item["status"] in RUNNABLE_STATUSES:
        return missing_prerequisites(item, refs)
    return missing_prerequisites(item, refs) or [f"its status is {item['status']} (not runnable)"]


def configure_for(session, group_id, recipe_id: str, values: Any, refs: WorkspaceRefs | None = None) -> dict:
    """The recipe as this workspace would save it: ``{name, definition}`` with its setup values filled in —
    the one path the Library's "Use recipe" and the agent's ``draft_workflow(recipe=…)`` share. Saves
    nothing. Raises UnknownRecipe, RecipeUnavailable (not offered here) or RecipeConfigError (a value is
    missing or mistyped)."""
    from ..authoring import workspace_refs

    item = entry(recipe_id)
    reasons = unavailable_reasons(item, refs or workspace_refs(session, group_id))
    if reasons:
        raise RecipeUnavailable(recipe_id, reasons)
    if values is not None and not isinstance(values, dict):
        raise RecipeConfigError("vars must be an object of setup variable values.")
    return instantiate(recipe_id, dict(values or {}))


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


# ── recipes from installed integrations ──────────────────────────────────────


def plugin_recipes() -> dict[str, dict]:
    """``{"<provider>.<id>": {"entry", "document", "variables"}}`` for every installed provider's valid recipes. Built
    once per set of installed providers (a test that registers a stand-in gets a fresh read)."""
    from marvin_integration_sdk import INTEGRATION_REGISTRY

    return _plugin_recipes(tuple(sorted((slug, id(p)) for slug, p in INTEGRATION_REGISTRY.items())))


@lru_cache(maxsize=4)
def _plugin_recipes(_installed: tuple) -> dict[str, dict]:
    from marvin_integration_sdk import INTEGRATION_REGISTRY

    found: dict[str, dict] = {}
    for slug in sorted(INTEGRATION_REGISTRY):
        provider = INTEGRATION_REGISTRY[slug]
        for recipe in getattr(provider, "recipes", ()) or ():
            rid = f"{slug}.{getattr(recipe, 'id', '?')}"
            problems = _recipe_problems(recipe, provider)
            if problems:
                logger.warning(f"Skipping workflow recipe {rid} from the {slug} integration: {'; '.join(problems)}")
                continue
            found[rid] = {
                "entry": _plugin_entry(rid, recipe, provider),
                "document": {"name": recipe.title, "definition": copy.deepcopy(recipe.definition)},
                "variables": copy.deepcopy(dict(recipe.variables)),
            }
    return found


def _recipe_problems(recipe, provider) -> list[str]:
    """The SDK's shape check, then Marvin's own: the definition filled with every variable's example must pass every
    check of an agent's draft that doesn't depend on the workspace (authoring.draft_issues)."""
    from marvin_integration_sdk import check_recipe

    from ..validation import item_target_issues, query_issues, structural_issues, unknown_key_issues

    try:
        problems = check_recipe(recipe, provider)
        if problems:
            return problems
        examples = {name: spec["example"] for name, spec in recipe.variables.items()}
        definition = configure(copy.deepcopy(recipe.definition), examples, dict(recipe.variables))
    except RecipeConfigError as e:
        return [f"its examples don't fit its variables ({e})"]
    except Exception as e:  # noqa: BLE001 — a plugin's odd object must never break the Library
        return [f"unreadable ({type(e).__name__}: {e})"]
    issues = structural_issues(definition) or query_issues(definition) + item_target_issues(definition) + unknown_key_issues(definition)
    return [f"{i.get('path') or i.get('where') or 'definition'}: {i['message']}" for i in issues]


def _plugin_entry(rid: str, recipe, provider) -> dict:
    """A plugin recipe in the catalogue's shape (what the Library, the guide and configure_for read)."""
    from marvin.services.integrations.loader import source_of

    trigger = recipe.definition.get("trigger") or {}
    category = recipe.category or provider.name
    return {
        "id": rid,
        "title": recipe.title,
        "outcome": recipe.outcome,
        "category": category,
        "category_slug": "-".join("".join(c if c.isalnum() else " " for c in category.lower()).split()),
        "tags": [*recipe.tags, provider.slug],
        "trigger": {"type": trigger.get("type") or "manual", "event": trigger.get("event")},
        "status": "supported-after-configuration",
        "shape": "workflow",
        "runnable": True,
        "setup_variables": [{"name": name, **spec} for name, spec in recipe.variables.items()],
        "prerequisites": {"integrations": [{"provider": provider.slug}]},
        "side_effects": [dict(e) for e in recipe.side_effects],
        "supporting_objects": [
            {"kind": "integration_connection", "name": provider.name, "required": True, "purpose": f"The {provider.name} connection it runs through."}
        ],
        "dependencies": [],
        "source": {"provider": provider.slug, "name": provider.name, **(source_of(provider.slug) or {"package": None, "version": None})},
    }
