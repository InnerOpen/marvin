"""Renaming a workspace — name and slug — without breaking what other systems keep.

Nothing in the database stores a workspace's slug (the current workspace is ``users.active_group_id``),
but things outside it do: Publishing API URLs (``/api/publish/{workspace_slug}/...``, e.g. a site's
``MARVIN_WORKSPACE_SLUG``), CLI ``--workspace`` arguments and backup file names (``{slug}-backup-…``).
So a slug change keeps the old slug as an alias (``group_slug_aliases``) and every slug lookup goes
through :func:`find_group_by_slug`, which falls back to the aliases.

Rules: a current slug always wins over an alias; a workspace can't take a slug that is another
workspace's alias (old links would silently start serving the wrong workspace's content); renaming
back to one of its own old slugs just drops that alias.
"""

from slugify import slugify
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from marvin.db.models.groups import Groups, GroupSlugAlias


class WorkspaceRenameError(ValueError):
    """The requested name or slug can't be used (empty, or taken)."""


def find_group_by_slug(session: Session, slug: str) -> Groups | None:
    """The workspace whose slug is ``slug`` — or, failing that, the one that used to have it."""
    group = session.execute(select(Groups).where(Groups.slug == slug)).scalar_one_or_none()
    if group is None:
        group = session.execute(
            select(Groups).join(GroupSlugAlias, GroupSlugAlias.group_id == Groups.id).where(GroupSlugAlias.slug == slug)
        ).scalar_one_or_none()
    return group


def slug_is_alias_of_another(session: Session, slug: str, group_id=None) -> bool:
    """Whether ``slug`` is a former slug of a workspace other than ``group_id``."""
    query = select(GroupSlugAlias.id).where(GroupSlugAlias.slug == slug)
    if group_id is not None:
        query = query.where(GroupSlugAlias.group_id != group_id)
    return session.execute(query.limit(1)).first() is not None


def former_slugs(session: Session, group_id) -> list[str]:
    """Slugs the workspace had before, oldest first."""
    rows = session.execute(select(GroupSlugAlias.slug).where(GroupSlugAlias.group_id == group_id).order_by(GroupSlugAlias.created_at))
    return list(rows.scalars())


def rename_workspace(session: Session, group: Groups, *, name: str, slug: str | None = None) -> Groups:
    """Give ``group`` a new name and slug, keeping its old slug resolvable.

    ``slug`` is slugified; omitted or blank, it is derived from ``name``. Flushes, doesn't commit.

    Raises:
        WorkspaceRenameError: blank name or slug, or one another workspace has (or had).
    """
    name = (name or "").strip()
    if not name:
        raise WorkspaceRenameError("A workspace name is required.")
    new_slug = slugify((slug or "").strip() or name)
    if not new_slug:
        raise WorkspaceRenameError("The slug needs at least one letter or digit.")

    other = Groups.id != group.id
    if session.execute(select(Groups.id).where(Groups.name == name, other)).first():
        raise WorkspaceRenameError(f"Another workspace is already named '{name}'.")
    if session.execute(select(Groups.id).where(Groups.slug == new_slug, other)).first():
        raise WorkspaceRenameError(f"Another workspace already uses the slug '{new_slug}'.")
    if slug_is_alias_of_another(session, new_slug, group.id):
        raise WorkspaceRenameError(f"The slug '{new_slug}' used to belong to another workspace; links using it still lead there.")

    old_slug = group.slug
    if new_slug != old_slug:
        if old_slug and not session.execute(select(GroupSlugAlias.id).where(GroupSlugAlias.slug == old_slug)).first():
            session.add(GroupSlugAlias(session=session, group_id=group.id, slug=old_slug))
        # Back to one of its own former slugs: it is the current slug again, not an alias.
        session.execute(delete(GroupSlugAlias).where(GroupSlugAlias.slug == new_slug, GroupSlugAlias.group_id == group.id))
    group.name = name
    group.slug = new_slug
    session.flush()
    return group
