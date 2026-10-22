"""A Playbook an integration ships (``ContentBlueprint(kind="playbook")``): checking it, reading it as a package, and hashing it.

The SDK's ``playbook_blueprint`` checks the same things before a plugin ships, but a plugin's declaration is not trusted: the
catalog and the blueprint schema run ``payload_problem`` again. Pure functions here; the database work is
``services/blueprints/playbook_apply.py``.

The payload is ``{"skill_md": <SKILL.md text>, "files": {<relative path>: <text>}}``: text only, no scripts, capped.
``playbook_hash`` is the install hash that tells an edited Playbook from an untouched one (see ``blueprint_state``): the content a
published change would copy (``CHANGE_KEYS``) and the checksum of each reference file.
"""

from __future__ import annotations

import hashlib
import json
import posixpath

from marvin.services.playbooks import PlaybookFileError, normalize_path
from marvin.services.playbooks.proposals import CHANGE_KEYS
from marvin.services.playbooks.skill_md import SkillFormatError, parse_skill_md

PROVENANCE_KEY = "installedBy"  # metadata_json[PROVENANCE_KEY]: {source, integrationId, blueprint, hash, fileShas, assets}
TEXT_EXTENSIONS = (".md", ".txt", ".json", ".csv", ".yaml")
SKILL_MAX = 64 * 1024
FILE_MAX = 64 * 1024
FILES_MAX = 20
TOTAL_MAX = 256 * 1024


def payload_problem(payload, slug: str) -> str | None:
    """Why a Playbook blueprint's payload can't be taken (safe to show), or None. Checks the shape, the caps, every path, the
    SKILL.md itself, and that its name is the blueprint's slug."""
    from marvin.services.playbooks.importer import SKILL_FILE, is_script

    if not isinstance(payload, dict) or not isinstance(payload.get("skill_md"), str):
        return "a playbook blueprint needs payload.skill_md (the SKILL.md text)"
    files = payload.get("files", {})
    if not isinstance(files, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()):
        return "payload.files must map a relative path to its text"
    if len(files) > FILES_MAX:
        return f"a shipped Playbook holds at most {FILES_MAX} reference files"
    if len(payload["skill_md"].encode()) > SKILL_MAX:
        return f"SKILL.md is over {SKILL_MAX // 1024} KB"
    total = len(payload["skill_md"].encode())
    for path, text in files.items():
        try:
            clean = normalize_path(path)
        except PlaybookFileError as e:
            return f"file '{path[:80]}': {e}"
        if clean != path or clean == SKILL_FILE:
            return f"file '{path[:80]}' must be a clean relative path other than SKILL.md"
        if is_script(path):
            return f"file '{path}' is a script; shipped Playbooks are text only"
        if posixpath.splitext(path)[1].lower() not in TEXT_EXTENSIONS:
            return f"file '{path}' must be one of {', '.join(TEXT_EXTENSIONS)}"
        size = len(text.encode())
        if size > FILE_MAX:
            return f"file '{path}' is over {FILE_MAX // 1024} KB"
        total += size
    if total > TOTAL_MAX:
        return f"the folder is over {TOTAL_MAX // 1024} KB in all"
    try:
        doc = parse_skill_md(payload["skill_md"])
    except SkillFormatError as e:
        return f"SKILL.md can't be used: {e}"
    if doc.name != slug:
        return f"the SKILL.md name '{doc.name}' must equal the blueprint slug '{slug}'"
    return None


def package_of(blueprint):
    """The importer ``Package`` (``kind="integration"``) for a Playbook blueprint whose payload passed ``payload_problem``."""
    from marvin.services.playbooks.importer import Package, PackageFile

    payload = blueprint.payload
    return Package(
        kind="integration",
        doc=parse_skill_md(payload["skill_md"]),
        text=payload["skill_md"],
        files=[PackageFile(path, text.encode()) for path, text in sorted((payload.get("files") or {}).items())],
    )


def sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def declared_file_shas(package) -> dict[str, str]:
    return {f.path: sha(f.data) for f in package.files}


def _content(data: dict | None) -> dict:
    data = data or {}
    return {k: (data.get(k) is True if k == "manual_only" else str(data.get(k) or "")) for k in CHANGE_KEYS}


def playbook_hash(data: dict | None, file_shas: dict[str, str]) -> str:
    """The content of a Playbook (``data_json``'s ``CHANGE_KEYS`` fields) and its files as ``{path: sha256}``, hashed."""
    blob = json.dumps({"data": _content(data), "files": dict(sorted(file_shas.items()))}, sort_keys=True, separators=(",", ":"))
    return sha(blob)


def declared_data(package) -> dict:
    return _content(package.doc.to_entry_data())


def declared_hash(package) -> str:
    return playbook_hash(package.doc.to_entry_data(), declared_file_shas(package))
