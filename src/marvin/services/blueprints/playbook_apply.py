"""An integration's Playbook blueprint: adding it, telling whether it was edited, and updating it.

It differs from every other kind in two ways, both on purpose:

* A Playbook is an entry, and the entry and asset writers **commit** (``EntryService.create``, ``attach_reference``,
  ``upload_asset``). So a Playbook is applied last by ``apply_many`` and this is the one place "apply never commits" does not hold.
* Entries have no ``source_integration_id`` / ``source_blueprint`` columns, so where it came from lives in
  ``metadata_json["installedBy"]`` (``PROVENANCE_KEY``): ``{source, integrationId, blueprint, hash, fileShas, assets}``. ``hash`` is
  the install hash (``playbook_hash`` of what was shipped); ``fileShas`` / ``assets`` are the shipped ``{path: sha256}`` and
  ``{path: asset id}``. A Playbook that carries the key from this provider is "applied"; any other entry with the name is a conflict.

It arrives as a **draft**: an admin reads the review and publishes it on the Playbooks page. A name that is taken is refused,
never renamed or adopted (an agent asks for a Playbook by name).
"""

from __future__ import annotations

from sqlalchemy.orm.attributes import flag_modified

from marvin.core.root_logger import get_logger
from marvin.db.models.platform.entries import Entries
from marvin.schemas.platform.blueprints import Blueprint, BlueprintApplyResult
from marvin.services.playbooks import PlaybookFileError, attach_reference, remove_reference
from marvin.services.playbooks.blueprint import PROVENANCE_KEY, declared_hash, package_of, playbook_hash
from marvin.services.playbooks.files import _links
from marvin.services.playbooks.importer import ImportRefused, _Upload, create_playbook_from_package, review_package, taken_where

logger = get_logger(__name__)


def applied_row(session, group_id, blueprint: Blueprint):
    """The Playbook this provider's blueprint made in the workspace (not in the Trash), or None."""
    from marvin.services.playbooks import playbook_type_id

    type_id = playbook_type_id(session, group_id)
    if type_id is None:
        return None
    row = session.query(Entries).filter(Entries.group_id == group_id, Entries.entry_type_id == type_id, Entries.slug == blueprint.slug).first()
    if row is None or row.status == "trashed":
        return None
    return row if provenance(row).get("source") == blueprint.source else None


def provenance(row) -> dict:
    found = (row.metadata_json or {}).get(PROVENANCE_KEY)
    return found if isinstance(found, dict) else {}


def blueprint_conflict(session, group_id, blueprint: Blueprint) -> str | None:
    """Why this Playbook can't be added: its name is taken by something that isn't this integration's Playbook. None when it is free
    or already applied."""
    if applied_row(session, group_id, blueprint) is not None:
        return None
    from marvin.services.playbooks.system import name_clash_message

    if clash := name_clash_message(blueprint.slug):
        return clash
    where = taken_where(session, group_id, blueprint.slug)
    if where is None:
        return None
    return f"The name '{blueprint.slug}' is already used by a Playbook or entry in this workspace{where}. Rename or remove that one to add this."


def provider_name(slug: str) -> str:
    """The provider's display name ("Buttondown"), or its slug when it isn't installed."""
    from marvin.services.integrations import INTEGRATIONS_AVAILABLE

    if INTEGRATIONS_AVAILABLE:
        from marvin.services.integrations import get_provider

        try:
            return get_provider(slug).name or slug
        except KeyError:
            pass
    return slug


def _services(session, group_id, actor_id, event_bus):
    from marvin.repos.repository_factory import AllRepositories
    from marvin.services.assets.asset_storage_service import AssetStorageService
    from marvin.services.entries.entry_service import EntryService

    return (
        EntryService(session, group_id, event_bus=event_bus, actor_id=actor_id),
        AssetStorageService.for_workspace(AllRepositories(session, group_id=group_id)),
    )


def _upload(assets, package_name, path, data, group_id, actor_id):
    import posixpath
    import uuid

    from marvin.schemas.platform import AssetUploadRequest
    from marvin.services.assets.scope import PLAYBOOK

    name = posixpath.basename(path)
    return assets.upload_asset(
        upload_file=_Upload(name, data),  # type: ignore[arg-type]
        upload_request=AssetUploadRequest(
            slug=f"{package_name}-{uuid.uuid4().hex[:10]}", name=name, metadata_json={"playbook": package_name, "path": path}, scope=PLAYBOOK
        ),
        group_id=group_id,
        user_id=actor_id,
    )


def _installed_by(blueprint: Blueprint, integration_id, package, entry_id, session) -> dict:
    from marvin.services.playbooks import reference_files
    from marvin.services.playbooks.blueprint import declared_file_shas

    return {
        "source": blueprint.source,
        "integrationId": str(integration_id) if integration_id else None,
        "blueprint": blueprint.slug,
        "hash": declared_hash(package),
        "fileShas": declared_file_shas(package),
        "assets": {f.path: f.asset_id for f in reference_files(session, entry_id)},
    }


def create_playbook(session, group_id, blueprint: Blueprint, integration_id, actor_id, event_bus=None) -> str:
    """Add the Playbook as a draft with its files and its review (source: the integration). Commits. Returns a note for the result
    (files the asset store turned down). Raises ``ValueError`` (the card shows it) when it can't be added."""
    if actor_id is None:  # the entry's creator and the files' uploader are recorded: a Playbook is added by a person
        raise ValueError("a Playbook is added by a person: no one is recorded as adding it")
    entries, assets = _services(session, group_id, actor_id, event_bus)
    package = package_of(blueprint)
    review_source = {"kind": "integration", "provider": blueprint.source, "name": provider_name(blueprint.source)}
    try:
        done = create_playbook_from_package(
            session,
            package,
            group_id=group_id,
            user_id=actor_id,
            entries=entries,
            assets=assets,
            review_source=review_source,
            metadata={},
            taken_advice="Rename or remove that one to add this.",
        )
    except ImportRefused as e:
        raise ValueError(str(e)) from e
    row = session.get(Entries, done.entry.id)
    row.metadata_json = {**(row.metadata_json or {}), PROVENANCE_KEY: _installed_by(blueprint, integration_id, package, row.id, session)}
    flag_modified(row, "metadata_json")
    session.commit()
    skipped = done.review.get("skipped") or []
    logger.info("Blueprint applied: playbook '%s' (%s) as a draft", blueprint.slug, blueprint.source)
    return "; ".join(f"'{s['path']}' not added: {s['reason']}" for s in skipped)


def current_files(session, row) -> dict[str, str]:
    """``{path: sha256}`` of the Playbook's reference files as stored now (the asset's own checksum: assets are never edited in place)."""
    return {path: asset.checksum for path, _link, asset in _links(session, row.id)}


def state_of(session, row, blueprint: Blueprint) -> str:
    """How an applied Playbook stands against what its integration ships now (``state_from_hashes``)."""
    from .apply import state_from_hashes

    have = playbook_hash(row.data_json, current_files(session, row))
    return state_from_hashes(have, provenance(row).get("hash"), declared_hash(package_of(blueprint)))


def update_playbook(
    session, group_id, blueprint: Blueprint, row, integration_id, actor_id, replace_edits: bool, event_bus=None
) -> BlueprintApplyResult:
    """Replace an applied Playbook's text and files with its integration's current version (committed). Its id and status are kept,
    so a published one is used by agents with the new text at once; the text goes through ``EntryService.update`` (the old version
    stays in its history). Changes made here, or a history that can't be told, need ``replace_edits`` first."""
    from .apply import REPLACES_EDITS

    result = BlueprintApplyResult(slug=blueprint.slug, kind=blueprint.kind, created=False, name=row.slug)
    package = package_of(blueprint)
    state = state_of(session, row, blueprint)
    mine = provenance(row)
    if state == "current":
        result.detail = "already up to date"
        if integration_id and str(mine.get("integrationId") or "") != str(integration_id):
            row.metadata_json = {**(row.metadata_json or {}), PROVENANCE_KEY: {**mine, "integrationId": str(integration_id)}}
            flag_modified(row, "metadata_json")
            session.commit()
        return result
    if state in REPLACES_EDITS and not replace_edits:
        result.needs_confirmation = True
        result.detail = "This Playbook was changed in this workspace; updating replaces those changes."
        return result

    entries, assets = _services(session, group_id, actor_id, event_bus)
    # The text first, with the review and provenance, so history holds the old version whatever happens to the files.
    review = review_package(package, _tool_names())
    previous = (row.metadata_json or {}).get("importReview") or {}
    review["source"] = {
        **(previous.get("source") or {}),
        "kind": "integration",
        "provider": blueprint.source,
        "name": provider_name(blueprint.source),
    }
    data = {**(row.data_json or {}), **package.doc.to_entry_data()}
    entry_id = row.id
    metadata = {k: v for k, v in (row.metadata_json or {}).items() if k != "frontmatterExtra"}
    if package.doc.extra:
        from marvin.services.playbooks.importer import _json_safe

        metadata["frontmatterExtra"] = _json_safe(package.doc.extra)
    metadata["importReview"] = review
    metadata[PROVENANCE_KEY] = mine  # rewritten below once the files are in place
    entries.update(entry_id, {"data_json": data, "metadata_json": metadata})

    skipped = _sync_files(session, group_id, entry_id, package, assets, actor_id, event_bus, review)
    row = session.get(Entries, entry_id)
    metadata = dict(row.metadata_json or {})
    metadata["importReview"] = review
    metadata[PROVENANCE_KEY] = _installed_by(blueprint, integration_id or mine.get("integrationId"), package, entry_id, session)
    row.metadata_json = metadata
    flag_modified(row, "metadata_json")
    session.commit()
    result.updated = True
    result.detail = "updated to the integration's current version" + ("; " + "; ".join(skipped) if skipped else "")
    logger.info("Blueprint updated: playbook '%s' (%s)", blueprint.slug, blueprint.source)
    return result


def _tool_names() -> set[str]:
    from marvin.services.ai.tools import list_tools

    return {t.name for t in list_tools()}


def _sync_files(session, group_id, entry_id, package, assets, actor_id, event_bus, review) -> list[str]:
    """Make the Playbook's reference files the shipped ones: new or changed files are uploaded and attached, files no longer shipped
    are taken off and their asset trashed, unchanged files are left. Returns notes for the files that couldn't be added."""
    from marvin.services import trash
    from marvin.services.assets.asset_storage_service import AssetRejected
    from marvin.services.playbooks.blueprint import sha

    have = {path: (link, asset) for path, link, asset in _links(session, entry_id)}
    shipped = {f.path: f for f in package.files}
    skipped: list[str] = []
    for path, (_link, asset) in have.items():
        if path not in shipped or asset.checksum != sha(shipped[path].data):
            remove_reference(session, group_id, entry_id, path)
            trash.trash(session, group_id, trash.ASSET, asset.id, actor_id=actor_id, event_bus=event_bus)
    for path, file in shipped.items():
        if path in have and have[path][1].checksum == sha(file.data):
            continue
        try:
            asset = _upload(assets, package.doc.name, path, file.data, group_id, actor_id)
            attach_reference(session, group_id, entry_id, asset.id, path)
        except Exception as e:  # noqa: BLE001 — a file the store turns down must not undo the text that already changed
            if not isinstance(e, AssetRejected | PlaybookFileError):
                raise
            skipped.append(f"'{path}' not added: {e}")
            review["skipped"] = [*review.get("skipped", []), {"path": path, "reason": str(e)}]
            review["files"] = [f for f in review.get("files", []) if f["path"] != path]
    return skipped
