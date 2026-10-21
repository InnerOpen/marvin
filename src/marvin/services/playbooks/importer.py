"""Import a ``SKILL.md`` file or a skill folder (zip) as a draft Playbook, and review what it asks for.

Two layers, so the risky part is testable without a database:

* ``read_package(filename, data)``: bytes in, a ``Package`` out (the parsed ``SkillDoc``, the raw text, the other files with
  their relative paths). Pure. Everything in a zip is read in memory, member by member, with caps; **nothing is ever extracted
  to disk** and no member name is used as a path, so a traversal name has nothing to traverse. A bad package raises
  ``ImportRefused`` (message safe to show, ``status_code`` 400 or 413).
* ``review_package(package, tool_names)``: pure again. The findings an editor reads before publishing: tools requested (and
  which Marvin lacks), every link and referenced file, scripts, and warnings from a simple keyword/URL heuristic. It is a
  prompt to read the Playbook, not a security check, and says so (``DISCLAIMER``).
* ``import_playbook(...)``: creates the **draft** entry, uploads each file as an asset and attaches it under its path
  (``attach_reference``), and stores the findings on the entry (``metadata_json``). Never publishes.

Stored on the entry: ``metadata_json["importReview"]`` (the review below) and ``metadata_json["frontmatterExtra"]`` (unknown
frontmatter keys, JSON-safe, for the export to write back). The review's keys are camelCase because the editor reads it as is.

Limits (module constants, so tests can lower them): ``UPLOAD_MAX`` bytes uploaded, ``MEMBER_MAX`` per file once unpacked,
``TOTAL_MAX`` unpacked in all, ``MEMBERS_MAX`` entries in the zip, ``playbooks.FILES_MAX`` reference files. A zip's member
sizes are never trusted: each is read with a bound, so a few kilobytes that unpack to gigabytes stop at ``MEMBER_MAX``.

Name clash: the Playbook's name is its slug, and slugs are unique per workspace across all entries. A taken name is
**refused** (409) rather than suffixed: an agent asks for a Playbook by name and an export must give the name back, so a
silent ``-2`` would break both. The caller may send another ``name`` with the import.
"""

from __future__ import annotations

import io
import json
import posixpath
import re
import stat
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from marvin.core.root_logger import get_logger
from marvin.services.ai.tool_gateway import resolve_tool_name
from marvin.services.playbooks import FILES_MAX, PlaybookFileError, attach_reference, ensure_playbook_type, normalize_path, parse_allowed_tools
from marvin.services.playbooks.skill_md import SkillDoc, SkillFormatError, check_name, parse_skill_md

logger = get_logger(__name__)

UPLOAD_MAX = 10 * 1024 * 1024
MEMBER_MAX = 5 * 1024 * 1024
TOTAL_MAX = 25 * 1024 * 1024
MEMBERS_MAX = 500
ARCHIVE_MAX = 30 * 1024 * 1024  # a whole repository archive from GitHub (only the skill folder in it is read, under the limits above)
SKILL_FILE = "SKILL.md"

SCRIPT_DIR = "scripts"
SCRIPT_EXTENSIONS = {".sh", ".bash", ".zsh", ".fish", ".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".php", ".ps1", ".bat", ".cmd"}
JUNK_NAMES = {".ds_store", "thumbs.db"}
JUNK_DIRS = {"__macosx", ".git"}

DISCLAIMER = (
    "This is a keyword and link check, not a guarantee. It can miss risky wording and flag harmless text. "
    "Read the Playbook and its files yourself before you publish it."
)
WARNINGS_MAX = 50
EXCERPT_MAX = 160


class ImportRefused(ValueError):
    """The upload can't be imported; the message says why and is safe to show."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class PackageFile:
    path: str
    data: bytes


@dataclass
class Package:
    kind: str  # "skill_md" | "zip"
    doc: SkillDoc
    text: str
    files: list[PackageFile] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)


# ── Reading ──────────────────────────────────────────────────────────────────


def _decode(data: bytes, what: str) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportRefused(f"{what} is not UTF-8 text.") from None


def _parse(text: str) -> SkillDoc:
    try:
        return parse_skill_md(text)
    except SkillFormatError as e:
        raise ImportRefused(f"SKILL.md can't be used: {e}") from None


def _safe_name(raw: str) -> str | None:
    """A member name as a clean relative path ('' for a directory), or None when it points outside the package."""
    name = raw.replace("\\", "/")
    if not name or "\x00" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def _junk(path: str) -> bool:
    parts = path.lower().split("/")
    return parts[-1] in JUNK_NAMES or any(p in JUNK_DIRS for p in parts[:-1]) or parts[0] in JUNK_DIRS


def _read_bounded(zf: zipfile.ZipFile, info: zipfile.ZipInfo, path: str, used: int) -> bytes:
    with zf.open(info) as member:
        data = member.read(MEMBER_MAX + 1)
    if len(data) > MEMBER_MAX:
        raise ImportRefused(f"'{path}' is too large once unpacked (the limit is {MEMBER_MAX // 1048576} MB a file).", 413)
    if used + len(data) > TOTAL_MAX:
        raise ImportRefused(f"The folder is too large once unpacked (the limit is {TOTAL_MAX // 1048576} MB in all).", 413)
    return data


def _read_zip(data: bytes, subdir: str | None = None) -> Package:
    """A zip as a Package. With ``subdir`` (the GitHub import) the zip is a whole repository archive: its one top folder is
    dropped and only the files under ``subdir`` ('' for the repository root) are read; the rest is never opened and counts
    toward no limit. SKILL.md must then sit exactly at ``subdir``."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ImportRefused("That is not a readable zip file.") from None
    with zf:
        infos = zf.infolist()
        prefix = None
        if subdir is not None:
            top = next((p.split("/")[0] for i in infos if (p := i.filename.replace("\\", "/").lstrip("/")) and "/" in p), "")
            prefix = f"{top}/{subdir}/" if subdir else f"{top}/"
            infos = [i for i in infos if i.filename.replace("\\", "/").startswith(prefix)]
        if len(infos) > MEMBERS_MAX:
            raise ImportRefused(f"The zip holds {len(infos)} entries; at most {MEMBERS_MAX} are accepted.", 413)
        if sum(i.file_size for i in infos) > TOTAL_MAX * 4:  # a declared size is only a hint, but an absurd one is enough to refuse
            raise ImportRefused("The folder is too large once unpacked.", 413)
        members: list[tuple[str, zipfile.ZipInfo]] = []
        skipped: list[dict] = []
        for info in infos:
            path = _safe_name(info.filename)
            if path is None:
                raise ImportRefused(f"The zip holds an unsafe path ('{info.filename[:80]}'): paths must stay inside the folder.")
            if prefix is not None:
                path = path[len(prefix) :]
            if not path or info.is_dir() or _junk(path):
                continue
            if info.flag_bits & 0x1:
                raise ImportRefused("The zip is password-protected.")
            if stat.S_ISLNK(info.external_attr >> 16):
                skipped.append({"path": path, "reason": "a link, not a file"})
                continue
            members.append((path, info))

        if prefix is not None:
            if SKILL_FILE not in {p for p, _ in members}:
                raise ImportRefused("That folder has no SKILL.md, so it is not a skill.")
            root = ""
        else:
            skills = [p for p, _ in members if posixpath.basename(p) == SKILL_FILE and p.count("/") <= 1]
            if not skills:
                raise ImportRefused("The zip has no SKILL.md at its top or in its one top-level folder.")
            if SKILL_FILE in skills:
                root = ""
            elif len(skills) == 1:
                root = posixpath.dirname(skills[0]) + "/"
            else:
                raise ImportRefused(f"The zip holds more than one skill ({len(skills)} SKILL.md files); import them one at a time.")

        used, files, text = 0, [], ""
        for path, info in members:
            if not path.startswith(root):
                skipped.append({"path": path, "reason": "outside the skill's folder"})
                continue
            rel = path[len(root) :]
            if rel == SKILL_FILE:
                raw = _read_bounded(zf, info, path, used)
                text = _decode(raw, "SKILL.md")
                continue
            if len(files) >= FILES_MAX:
                raise ImportRefused(f"A Playbook holds at most {FILES_MAX} reference files; this folder has more.", 413)
            raw = _read_bounded(zf, info, path, used)
            used += len(raw)
            try:
                rel = normalize_path(rel)
            except PlaybookFileError as e:
                skipped.append({"path": rel[:80], "reason": str(e)})
                continue
            files.append(PackageFile(rel, raw))
    return Package("zip" if subdir is None else "github", _parse(text), text, sorted(files, key=lambda f: f.path), skipped)


def read_repo_archive(data: bytes, subdir: str) -> Package:
    """A repository archive (a GitHub zipball) narrowed to the skill folder at ``subdir``. Same limits as ``read_package``,
    in memory only. Raises ImportRefused."""
    return _read_zip(data, subdir)


def read_package(filename: str, data: bytes) -> Package:
    """A SKILL.md or a zip (told by its first bytes) as a Package. Raises ImportRefused; reads nothing outside memory."""
    if len(data) > UPLOAD_MAX:
        raise ImportRefused(f"The upload is over the {UPLOAD_MAX // 1048576} MB limit.", 413)
    if not data:
        raise ImportRefused("The upload is empty.")
    if data[:2] == b"PK":
        return _read_zip(data)
    text = _decode(data, "The file")
    return Package("skill_md", _parse(text), text)


# ── Reviewing ────────────────────────────────────────────────────────────────

_URL = re.compile(r"https?://[^\s)>\]\"'`]+", re.I)
_MD_LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_FOLDER_PATH = re.compile(r"(?<![\w/.-])((?:references|scripts|assets|templates|examples|resources|docs|agents)/[\w./-]*[\w-])", re.I)
_SECRET_WORD = re.compile(
    r"\b(api[ _-]?keys?|secrets?|credentials?|passwords?|passwd|private[ _-]?keys?|ssh[ _-]keys?"
    r"|(?:access|auth|bearer|oauth|api|refresh|session)[ _-]?tokens?)\b|(?<![\w])\.env\b",
    re.I,
)
_SECRET_VALUE = re.compile(
    r"sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}|xox[abprs]-[A-Za-z0-9-]{10,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?i:(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9/+_-]{16,})"
)
_SEND_VERB = re.compile(r"\b(send|post|upload|forward|transmit|submit|exfiltrat\w*|e-?mail|share|push|leak|curl|wget)\b", re.I)
_SEND_TO_OUTSIDE = re.compile(r"\b(external|remote|third[- ]party|outside)\s+(server|host|url|site|endpoint|service|address|domain|party)\b", re.I)
_BARE_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_TEXT_SCAN_MAX = 512 * 1024


def is_script(path: str) -> bool:
    """A file Marvin would never run: under ``scripts/`` or with an executable-looking extension."""
    return path.split("/")[0].lower() == SCRIPT_DIR or posixpath.splitext(path)[1].lower() in SCRIPT_EXTENSIONS


def _mask(match: re.Match) -> str:
    return match.group(0)[:4] + "…[hidden]"


def _excerpt(line: str) -> str:
    line = _SECRET_VALUE.sub(_mask, line.strip())
    return line if len(line) <= EXCERPT_MAX else line[: EXCERPT_MAX - 1] + "…"


def _warnings(texts: list[tuple[str, str]]) -> tuple[list[dict], int]:
    found, omitted = [], 0
    for where, text in texts:
        for number, line in enumerate(text.splitlines(), 1):
            kinds = []
            if _SECRET_VALUE.search(line):
                kinds.append("secret_value")
            if _SECRET_WORD.search(line):
                kinds.append("secret_word")
            if (_SEND_VERB.search(line) and (_URL.search(line) or _BARE_IP.search(line))) or (
                _SEND_VERB.search(line) and _SEND_TO_OUTSIDE.search(line)
            ):
                kinds.append("sends_data")
            for kind in kinds:
                if len(found) >= WARNINGS_MAX:
                    omitted += 1
                else:
                    found.append({"kind": kind, "file": where, "line": number, "excerpt": _excerpt(line)})
    return found, omitted


def _links(body: str, paths: set[str]) -> list[dict]:
    """Every URL and file the SKILL.md points at, once each, in order of appearance, with whether the file is in the package."""
    found: dict[str, dict] = {}

    def add(target: str, line: int):
        if target in found:
            return
        if _URL.match(target):
            found[target] = {"target": target, "kind": "url", "found": None, "line": line}
            return
        bare = target.split("#", 1)[0].split("?", 1)[0]
        if not bare or target.startswith(("#", "mailto:")):
            return
        try:
            clean = normalize_path(bare)
        except PlaybookFileError:
            clean = None  # '../elsewhere': points out of the package
        key = clean or bare
        if key not in found:
            found[key] = {"target": key, "kind": "file", "found": clean in paths if clean else False, "line": line}

    for number, line in enumerate(body.splitlines(), 1):
        for target in _MD_LINK.findall(line):
            add(target, number)
        for url in _URL.findall(line):
            add(url.rstrip(".,;:"), number)
        for target in _FOLDER_PATH.findall(line):
            add(target, number)
        for path in paths:  # a shipped file named in plain text (`tests.md`) counts as referenced
            if re.search(rf"(?<![\w/.-]){re.escape(path)}(?![\w-])", line):
                add(path, number)
    return list(found.values())


def _readable(file: PackageFile) -> str | None:
    if len(file.data) > _TEXT_SCAN_MAX:
        return None
    try:
        return file.data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def review_package(package: Package, tool_names: set[str] | frozenset[str]) -> dict:
    """What an editor should look at before publishing (see the module docstring); JSON-safe, camelCase keys."""
    paths = {f.path for f in package.files}
    links = _links(package.text, paths)
    mentioned = {link["target"] for link in links}
    scanned = [(SKILL_FILE, package.text)] + [(f.path, t) for f in package.files if (t := _readable(f)) is not None]
    warnings, omitted = _warnings(scanned)
    # Same reading as the run (ticket 07): a token that names no Marvin tool is ignored when the Playbook runs.
    tools = []
    for token in parse_allowed_tools(package.doc.allowed_tools):
        resolved = resolve_tool_name(token, tool_names)
        tools.append({"name": token, "tool": resolved, "available": resolved is not None})
    return {
        "source": {"kind": package.kind},
        "tools": tools,
        "narrowsTools": any(t["available"] for t in tools),
        "links": links,
        "files": [{"path": f.path, "size": len(f.data), "script": is_script(f.path), "referenced": f.path in mentioned} for f in package.files],
        "scripts": [f.path for f in package.files if is_script(f.path)],
        "skipped": list(package.skipped),
        "warnings": warnings,
        "warningsOmitted": omitted,
        "extraKeys": sorted(package.doc.extra),
        "disclaimer": DISCLAIMER,
    }


# ── Importing ────────────────────────────────────────────────────────────────


@dataclass
class Imported:
    entry: Any
    review: dict
    file_count: int


def _taken_message(session, group_id, name) -> str | None:
    from marvin.db.models.platform.entries import Entries

    row = session.query(Entries.status).filter(Entries.group_id == group_id, Entries.slug == name).first()
    if row is None:
        return None
    where = " (it is in the Trash)" if row[0] == "trashed" else ""
    return (
        f"The name '{name}' is already used by a Playbook or entry in this workspace{where}. "
        "A Playbook's name must be unique: change the name in SKILL.md, or choose a new name for this import."
    )


def _json_safe(value: dict) -> dict:
    return json.loads(json.dumps(value, default=str))


def import_playbook(session, *, group_id, user_id, filename: str, data: bytes, entries, assets, name: str | None = None) -> Imported:
    """Create a draft Playbook from an upload. ``entries`` is an ``EntryService`` and ``assets`` an ``AssetStorageService`` of
    this workspace. Raises ImportRefused (bad package, name taken, too big) before anything is written; a file the asset
    store turns down is skipped and listed in the review rather than failing the import."""
    package = read_package(filename, data)
    return import_package(session, package, group_id=group_id, user_id=user_id, filename=filename, entries=entries, assets=assets, name=name)


def import_package(
    session, package: Package, *, group_id, user_id, filename: str, entries, assets, name: str | None = None, source: dict | None = None
) -> Imported:
    """``import_playbook`` from a Package already read (the upload, or a GitHub folder). ``source`` is recorded on the review
    and the entry (``metadata_json["source"]``) as the draft's provenance."""
    from marvin.schemas.platform import AssetUploadRequest
    from marvin.services.ai.tools import list_tools
    from marvin.services.assets.asset_storage_service import AssetRejected

    if name is not None and name.strip():
        try:
            package.doc.name = check_name(name.strip())
        except SkillFormatError as e:
            raise ImportRefused(f"The new name can't be used: {e}") from None
    doc = package.doc
    if message := _taken_message(session, group_id, doc.name):
        raise ImportRefused(message, 409)

    review = review_package(package, {t.name for t in list_tools()})
    review["source"] = {"kind": package.kind, "filename": (filename or "")[:200], "importedAt": datetime.now(UTC).isoformat()}
    metadata = {"importReview": review}
    if source:
        review["source"] = {**review["source"], **source}
        metadata["source"] = dict(source)
    if doc.extra:
        metadata["frontmatterExtra"] = _json_safe(doc.extra)
    entry = entries.create(
        {
            "entry_type_id": ensure_playbook_type(session, group_id),
            "title": doc.name,
            "slug": doc.name,
            "status": "draft",
            "data_json": doc.to_entry_data(),
            "metadata_json": metadata,
            "created_by": user_id,
        }
    )

    attached = 0
    for file in package.files:
        slug = f"{doc.name}-{uuid.uuid4().hex[:10]}"
        upload = _Upload(posixpath.basename(file.path), file.data)
        try:
            asset = assets.upload_asset(
                upload_file=upload,  # type: ignore[arg-type]
                upload_request=AssetUploadRequest(
                    slug=slug, name=posixpath.basename(file.path), metadata_json={"playbook": doc.name, "path": file.path}
                ),
                group_id=group_id,
                user_id=user_id,
            )
            attach_reference(session, group_id, entry.id, asset.id, file.path)
            attached += 1
        except (AssetRejected, PlaybookFileError) as e:
            review["skipped"].append({"path": file.path, "reason": str(e)})
            review["files"] = [f for f in review["files"] if f["path"] != file.path]
            review["scripts"] = [p for p in review["scripts"] if p != file.path]
    if attached != len(package.files):  # keep the stored review in step with what was kept
        from sqlalchemy.orm.attributes import flag_modified

        row = session.get(type(entry), entry.id)
        row.metadata_json = {**(row.metadata_json or {}), "importReview": review}
        flag_modified(row, "metadata_json")
        session.commit()
    logger.info("playbooks: imported %s (%s, %d files) into workspace %s", doc.name, package.kind, attached, group_id)
    return Imported(entry=entry, review=review, file_count=attached)


class _Upload:
    """The few parts of a FastAPI ``UploadFile`` that ``upload_asset`` reads: a filename and a seekable file object."""

    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self.file = io.BytesIO(data)
