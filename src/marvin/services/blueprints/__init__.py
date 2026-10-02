"""Blueprints — declarative descriptions of workspace structure that core ships and providers extend.

A blueprint says "here is a collection / entry type / scheduled task a workspace could have". It
creates nothing until applied, and applying creates what is missing without ever overwriting what
exists. Three consumers share the one schema: the catalog a user browses, what an integration
brings on install, and what the agent offers to create.
"""

from .apply import already_applied, apply_blueprint, apply_many, missing_requirements, outdated, update_blueprint
from .catalog import CORE_BLUEPRINTS, categories, get_blueprint, list_blueprints

__all__ = [
    "CORE_BLUEPRINTS",
    "already_applied",
    "apply_blueprint",
    "apply_many",
    "outdated",
    "update_blueprint",
    "categories",
    "get_blueprint",
    "list_blueprints",
    "missing_requirements",
]
