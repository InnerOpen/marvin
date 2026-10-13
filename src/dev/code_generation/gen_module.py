"""Generate a new CRUD module with all boilerplate files and registration wiring."""

import subprocess
from pathlib import Path

from jinja2 import Template
from utils import (
    CodeKeys,
    MarvinPaths,
    ModuleTemplates,
    inject_inline,
    log,
)
from utils.naming import EntityNames, derive_names


def _render_template(template_path: Path, dest: Path, ctx: dict) -> None:
    tplt = Template(template_path.read_text())
    dest.write_text(tplt.render(**ctx))
    subprocess.run(["uv", "run", "ruff", "check", str(dest), "--fix"], capture_output=True)
    subprocess.run(["uv", "run", "ruff", "format", str(dest)], capture_output=True)


def _template_context(names: EntityNames) -> dict:
    return {
        "snake_singular": names.snake_singular,
        "snake_plural": names.snake_plural,
        "pascal_singular": names.pascal_singular,
        "pascal_plural": names.pascal_plural,
        "kebab_plural": names.kebab_plural,
        "route_prefix": names.route_prefix,
        "table_name": names.table_name,
    }


def _target_paths(names: EntityNames) -> dict[str, Path]:
    return {
        "db_model": MarvinPaths.db_models_platform / f"{names.snake_plural}.py",
        "schema": MarvinPaths.schemas_platform / f"{names.snake_plural}.py",
        "repo": MarvinPaths.repos_platform / f"{names.snake_plural}.py",
        "controller": MarvinPaths.routes_platform / f"{names.snake_plural}_controller.py",
    }


def _template_map() -> dict[str, Path]:
    return {
        "db_model": ModuleTemplates.db_model,
        "schema": ModuleTemplates.schema,
        "repo": ModuleTemplates.repo,
        "controller": ModuleTemplates.controller,
    }


def _check_existing(targets: dict[str, Path]) -> list[Path]:
    return [p for p in targets.values() if p.exists()]


def _render_files(names: EntityNames, targets: dict[str, Path]) -> None:
    ctx = _template_context(names)
    templates = _template_map()
    for key, template_path in templates.items():
        dest = targets[key]
        log.info(f"  Creating {dest.relative_to(MarvinPaths.db_models_platform.parent.parent.parent)}")
        _render_template(template_path, dest, ctx)


def _wire_model_init(names: EntityNames) -> None:
    init_path = MarvinPaths.db_models_platform / "__init__.py"
    inject_inline(
        init_path,
        CodeKeys.platform_model_imports,
        [
            f"from .{names.snake_plural} import {names.pascal_plural}",
        ],
    )
    inject_inline(
        init_path,
        CodeKeys.platform_model_all,
        [
            f'"{names.pascal_plural}",',
        ],
    )


def _wire_schema_init(names: EntityNames) -> None:
    init_path = MarvinPaths.schemas_platform / "__init__.py"
    inject_inline(
        init_path,
        CodeKeys.platform_schema_imports,
        [
            f"from .{names.snake_plural} import (",
            f"    {names.pascal_singular}Create,",
            f"    {names.pascal_singular}Read,",
            f"    {names.pascal_singular}Summary,",
            f"    {names.pascal_singular}Update,",
            ")",
        ],
    )
    inject_inline(
        init_path,
        CodeKeys.platform_schema_all,
        [
            f'"{names.pascal_singular}Create",',
            f'"{names.pascal_singular}Read",',
            f'"{names.pascal_singular}Summary",',
            f'"{names.pascal_singular}Update",',
        ],
    )


def _wire_repo_init(names: EntityNames) -> None:
    init_path = MarvinPaths.repos_platform / "__init__.py"
    inject_inline(
        init_path,
        CodeKeys.platform_repo_imports,
        [
            f"from .{names.snake_plural} import {names.pascal_plural}Repository",
        ],
    )
    inject_inline(
        init_path,
        CodeKeys.platform_repo_all,
        [
            f'"{names.pascal_plural}Repository",',
        ],
    )


def _wire_repo_factory(names: EntityNames) -> None:
    factory_path = MarvinPaths.repo_factory
    inject_inline(
        factory_path,
        CodeKeys.factory_repo_imports,
        [
            f"{names.pascal_plural}Repository,",
        ],
    )
    inject_inline(
        factory_path,
        CodeKeys.factory_repo_properties,
        [
            "",
            "@cached_property",
            f"def {names.snake_plural}(self) -> {names.pascal_plural}Repository:",
            f'    """Provides access to workspace-scoped {names.snake_singular} records."""',
            f"    return {names.pascal_plural}Repository(self.session, self.group_id)",
        ],
    )


def _wire_route_init(names: EntityNames) -> None:
    init_path = MarvinPaths.routes_platform / "__init__.py"
    inject_inline(
        init_path,
        CodeKeys.platform_route_imports,
        [
            f"{names.snake_plural}_controller,",
        ],
    )
    inject_inline(
        init_path,
        CodeKeys.platform_route_includes,
        [
            f'router.include_router({names.snake_plural}_controller.router, tags=["Platform: {names.pascal_plural}"])',
        ],
    )


def _format_modified_files(targets: dict[str, Path]) -> None:
    registration_files = [
        MarvinPaths.db_models_platform / "__init__.py",
        MarvinPaths.schemas_platform / "__init__.py",
        MarvinPaths.repos_platform / "__init__.py",
        MarvinPaths.repo_factory,
        MarvinPaths.routes_platform / "__init__.py",
    ]
    all_files = list(targets.values()) + registration_files
    for f in all_files:
        subprocess.run(["uv", "run", "ruff", "check", str(f), "--fix"], capture_output=True)
        subprocess.run(["uv", "run", "ruff", "format", str(f)], capture_output=True)


def _print_event_snippet(names: EntityNames) -> None:
    log.info("")
    log.info("Event types are NOT auto-wired. Add the following to event_types.py:")
    log.info("")
    print(f"""
@dataclass
class Event{names.pascal_singular}Data(EventDocumentDataBase):
    operation: EventOperation
    {names.snake_singular}_id: UUID4
    {names.snake_singular}_name: str
    workspace_id: UUID4


# Add to EventTypes enum:
#   {names.snake_singular}_created = "{names.snake_singular}_created"
#   {names.snake_singular}_updated = "{names.snake_singular}_updated"
#   {names.snake_singular}_deleted = "{names.snake_singular}_deleted"
""")


def main(entity: str, plural_override: str | None = None, dry_run: bool = False) -> None:
    names = derive_names(entity, plural_override)
    targets = _target_paths(names)

    log.info(f"Module: {names.pascal_singular} ({names.snake_plural})")
    log.info("")

    existing = _check_existing(targets)
    if existing:
        paths_str = ", ".join(str(p) for p in existing)
        raise SystemExit(f"Aborting: files already exist: {paths_str}")

    if dry_run:
        log.info("[dry-run] Would create:")
        for label, path in targets.items():
            log.info(f"  {label}: {path}")
        log.info("")
        log.info("[dry-run] Would modify:")
        log.info(f"  {MarvinPaths.db_models_platform / '__init__.py'}")
        log.info(f"  {MarvinPaths.schemas_platform / '__init__.py'}")
        log.info(f"  {MarvinPaths.repos_platform / '__init__.py'}")
        log.info(f"  {MarvinPaths.repo_factory}")
        log.info(f"  {MarvinPaths.routes_platform / '__init__.py'}")
        _print_event_snippet(names)
        return

    log.info("Creating files...")
    _render_files(names, targets)

    log.info("Wiring registration files...")
    _wire_model_init(names)
    _wire_schema_init(names)
    _wire_repo_init(names)
    _wire_repo_factory(names)
    _wire_route_init(names)

    log.info("Formatting...")
    _format_modified_files(targets)

    log.info("")
    log.info("Module created successfully!")
    _print_event_snippet(names)
