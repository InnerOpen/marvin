"""Copy a system Playbook to customise it: a draft Playbook of the workspace, with its own name and no link back.

The copy is the workspace's own (editable, exportable, no update link). ``metadata_json["copiedFrom"]`` records where it came from
(name, label, version, hash). Once the copy is *published* it replaces its original in that workspace (``system.system_states``
reads ``copiedFrom``); unpublishing or trashing it brings the original back. If the system Playbook changes upstream the copy only
gets a hint (``upstream``): nothing is merged, a person reads the new version and edits the copy.
"""

from __future__ import annotations

from marvin.services.playbooks.importer import Imported, ImportRefused, Package, PackageFile, create_playbook_from_package
from marvin.services.playbooks.skill_md import SkillDoc, SkillFormatError, check_name, render_skill_md
from marvin.services.playbooks.system import COPIED_FROM, SystemPlaybook, system_playbook


def suggested_name(playbook: SystemPlaybook) -> str:
    """The name without its prefix (``marvin-alt-text`` gives ``alt-text``): what the workspace would call its own."""
    prefix = f"{playbook.owner}-"
    bare = playbook.name.removeprefix(prefix) if playbook.name.startswith(prefix) else playbook.name
    return bare or playbook.name


def copy_system_playbook(session, playbook: SystemPlaybook, *, group_id, user_id, entries, assets, name: str | None = None) -> Imported:
    """The draft copy of ``playbook`` under ``name`` (the suggested one when omitted). Raises ``ImportRefused`` (409) for a taken name or
    a system Playbook's name, and 400 for an unusable one."""
    wanted = (name or "").strip() or suggested_name(playbook)
    try:
        check_name(wanted)
    except SkillFormatError as e:
        raise ImportRefused(f"The name can't be used: {e}") from None
    doc = SkillDoc(
        name=wanted,
        description=playbook.description,
        body=playbook.body,
        allowed_tools=playbook.allowed_tools,
        manual_only=playbook.manual_only,
    )
    package = Package(
        kind="system",
        doc=doc,
        text=render_skill_md(doc),
        files=[PackageFile(path, text.encode()) for path, text in playbook.files],
    )
    return create_playbook_from_package(
        session,
        package,
        group_id=group_id,
        user_id=user_id,
        entries=entries,
        assets=assets,
        review_source={"kind": "system", "label": playbook.label, "version": playbook.version, "name": playbook.name},
        metadata={COPIED_FROM: {"name": playbook.name, "label": playbook.label, "version": playbook.version, "hash": playbook.hash}},
        taken_advice="Choose another name for your copy.",
    )


def upstream(metadata: dict | None) -> dict | None:
    """What a copy's list row shows about its original: ``{name, label, version, current_version, upstream_changed}``, or None for a
    Playbook that is not a copy. ``upstream_changed`` compares the original's hash now with the one recorded when the copy was made
    (or last marked as seen)."""
    found = (metadata or {}).get(COPIED_FROM)
    if not isinstance(found, dict) or not found.get("name"):
        return None
    now = system_playbook(str(found["name"]))
    return {
        "name": str(found["name"]),
        "label": str(found.get("label") or ""),
        "version": str(found.get("version") or ""),
        "current_version": now.version if now else None,
        "upstream_changed": now is not None and now.hash != found.get("hash"),
    }


def mark_seen(session, entry) -> bool:
    """Record the original's current hash and version on a copy, so its hint goes away until the original changes again (committed)."""
    from sqlalchemy.orm.attributes import flag_modified

    found = (entry.metadata_json or {}).get(COPIED_FROM)
    now = system_playbook(str((found or {}).get("name") or "")) if isinstance(found, dict) else None
    if now is None:
        return False
    entry.metadata_json = {**(entry.metadata_json or {}), COPIED_FROM: {**found, "version": now.version, "hash": now.hash}}
    flag_modified(entry, "metadata_json")
    session.commit()
    return True
