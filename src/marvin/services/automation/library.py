"""Workflow Library recipes: a definition with `{{setup}}` placeholders, and how one is configured.

A library recipe (docs/workflow-library/recipes/<id>.json) is a workflow definition in Marvin's own
format with one addition: where it needs a reference the installing workspace must supply — an entry
type slug, a collection, an integration connection, an outgoing webhook's id — it holds a *setup
placeholder*, ``{{name}}``, declared in the recipe's ``<id>.vars.json`` with a type. Configuring a recipe
substitutes each placeholder with the workspace's value and yields a plain definition for
``POST /api/automations`` (or ``draft_workflow``).

Placeholders are deliberately NOT Marvin's run-time templates: ``${entry.title}`` / ``$event.entry_id``
are resolved by the engine when a workflow runs (services/automation/matcher.py) and must reach the saved
definition untouched. Substitution therefore walks the parsed JSON and replaces placeholders *as values*:

* a string that is exactly ``{{name}}`` becomes the variable's value with its declared type (a boolean
  stays a boolean, an object stays an object, a string stays a string);
* a longer string with ``{{name}}`` inside it takes the value's text in that spot — allowed only for
  string-like variables, since a boolean or an object has no place inside a sentence;
* everything else — including every ``${…}`` — is left exactly as it was.

So a placeholder can never be mistaken for a template, a template is never rewritten, and a value's type
is never flattened to text.

Marvin has one more ``{{…}}`` form: a workspace secret reference, ``{{API_KEY}}``, resolved when a step
runs (services/secrets/resolver.py ``SLUG_RE``, integrations/arg_secrets.py). Its names are UPPER_CASE by
convention; setup placeholders are lower_case, and only those are substituted — an upper-case reference
passes through to the saved definition, where the engine resolves it.
"""

from __future__ import annotations

import re
from typing import Any

PLACEHOLDER = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")

# A variable's declared type → the Python types its value may have. Everything not listed here is a
# string-like reference (a slug, an id, a field key, an event name) and must be given as text.
_TYPED: dict[str, tuple[type, ...]] = {
    "boolean": (bool,),
    "integer": (int,),
    "number": (int, float),
    "object": (dict,),
    "list": (list,),
}


class RecipeConfigError(ValueError):
    """A recipe could not be configured: a placeholder has no value, a value has the wrong type, or a
    placeholder that needs text sits inside a sentence with a non-text value."""


def placeholders(node: Any) -> set[str]:
    """Every ``{{name}}`` the recipe mentions, in values and in keys."""
    found: set[str] = set()
    if isinstance(node, str):
        found.update(PLACEHOLDER.findall(node))
    elif isinstance(node, dict):
        for key, value in node.items():
            found.update(placeholders(key))
            found.update(placeholders(value))
    elif isinstance(node, list):
        for item in node:
            found.update(placeholders(item))
    return found


def _check_type(name: str, value: Any, declared: dict) -> None:
    kind = str(declared.get("type", "string"))
    allowed = _TYPED.get(kind)
    if allowed is None:
        if not isinstance(value, str):
            raise RecipeConfigError(f"setup variable '{name}' ({kind}) must be text, got {type(value).__name__}")
        return
    if isinstance(value, bool) and bool not in allowed:  # bool is an int to Python, not to a recipe
        raise RecipeConfigError(f"setup variable '{name}' ({kind}) must be a {kind}, got a boolean")
    if not isinstance(value, allowed):
        raise RecipeConfigError(f"setup variable '{name}' ({kind}) must be a {kind}, got {type(value).__name__}")


def configure(recipe: Any, values: dict[str, Any], variables: dict[str, dict]) -> Any:
    """The recipe with every ``{{name}}`` replaced by ``values[name]``, typed per ``variables[name]``.

    ``variables`` is the recipe's vars schema ``{name: {type, description, …}}``. Every placeholder must be
    declared and given a value (a declared variable the recipe doesn't use is fine). Returns a new
    structure; ``recipe`` is not modified.
    """
    used = placeholders(recipe)
    undeclared = sorted(used - set(variables))
    if undeclared:
        raise RecipeConfigError(f"recipe uses undeclared setup variable(s): {', '.join(undeclared)}")
    missing = sorted(name for name in used if name not in values)
    if missing:
        raise RecipeConfigError(f"missing setup value(s): {', '.join(missing)}")
    for name in used:
        _check_type(name, values[name], variables[name])
    return _substitute(recipe, values, variables)


def _substitute(node: Any, values: dict[str, Any], variables: dict[str, dict]) -> Any:
    if isinstance(node, str):
        whole = PLACEHOLDER.fullmatch(node.strip())
        if whole:
            return values[whole.group(1)]  # typed: the value as given, whatever its JSON type
        if "{{" not in node:
            return node

        def text(match: re.Match) -> str:
            name = match.group(1)
            if variables[name].get("type", "string") in _TYPED:
                raise RecipeConfigError(f"setup variable '{name}' is not text, so it can't be embedded in {node!r}")
            return str(values[name])

        return PLACEHOLDER.sub(text, node)
    if isinstance(node, dict):
        return {_substitute(k, values, variables): _substitute(v, values, variables) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute(item, values, variables) for item in node]
    return node


def unresolved(node: Any) -> set[str]:
    """Placeholders still present after configuring — a configured recipe must have none before it is
    offered as runnable JSON."""
    return placeholders(node)
