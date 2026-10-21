"""The ``SKILL.md`` codec: the one place that reads and writes the Agent Skills file format (https://agentskills.io).

A ``SKILL.md`` is YAML frontmatter between ``---`` lines, then a markdown body. This module turns that text into a
``SkillDoc`` and back; the import (``services/playbooks/importer.py``) and, later, the export both go through it, so the two
cannot drift apart.

* Strict on what the standard requires: ``name`` (lowercase words joined by hyphens, at most 64 characters) and
  ``description`` (at most 1024). A file without them raises ``SkillFormatError`` with a message safe to show.
* Lenient on everything else. Keys this module doesn't know are kept in ``SkillDoc.extra`` with their values and written
  back out, so an import followed by an export loses nothing. A description with an unquoted colon (invalid YAML, common in
  real skills) is read by a line-based fallback instead of being refused.
* Two keys change shape on the way in. ``disable-model-invocation: true`` is the Playbook's ``manual_only``;
  ``allowed-tools`` is a space-separated string in the standard (a YAML list or commas, as other tools write it, is
  normalised to that) and the Playbook's ``allowed_tools`` field is the same string.

``SkillDoc.from_entry_data`` / ``to_entry_data`` map to and from a Playbook entry's ``data_json`` (name, description, body,
license, compatibility, allowed_tools, manual_only); keys that have no field there travel separately as ``extra``.
Round trip: ``parse_skill_md(render_skill_md(doc)) == doc``; the body is normalised to end with one newline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

NAME_MAX = 64
DESCRIPTION_MAX = 1024
COMPATIBILITY_MAX = 500
_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_FENCE = re.compile(r"^---[ \t]*$", re.MULTILINE)
_KNOWN = ("name", "description", "license", "compatibility", "allowed-tools", "allowed_tools", "disable-model-invocation")
_TRUE = {"true", "yes", "on", "1"}
MARVIN_PREFIX = "marvin-"
MARVIN_MANUAL_ONLY = "marvin-manual-only"


class SkillFormatError(ValueError):
    """The text is not a usable SKILL.md; the message says why and is safe to show."""


@dataclass
class SkillDoc:
    name: str
    description: str
    body: str = ""
    license: str = ""
    compatibility: str = ""
    allowed_tools: str = ""
    manual_only: bool = False
    extra: dict = field(default_factory=dict)
    """Frontmatter keys the standard (or this module) doesn't name, as read: kept so an export can write them back."""

    @classmethod
    def from_entry_data(cls, data: dict, extra: dict | None = None) -> SkillDoc:
        """A document from a Playbook entry's ``data_json`` (missing fields are empty) and its kept ``extra`` keys."""
        return cls(
            name=str(data.get("name") or ""),
            description=str(data.get("description") or ""),
            body=str(data.get("body") or ""),
            license=str(data.get("license") or ""),
            compatibility=str(data.get("compatibility") or ""),
            allowed_tools=str(data.get("allowed_tools") or ""),
            manual_only=data.get("manual_only") is True,
            extra=dict(extra or {}),
        )

    def to_entry_data(self) -> dict:
        """The Playbook's ``data_json`` for this document (``extra`` has no field there: keep it in the entry's metadata)."""
        return {
            "name": self.name,
            "description": self.description,
            "body": self.body,
            "license": self.license,
            "compatibility": self.compatibility,
            "allowed_tools": self.allowed_tools,
            "manual_only": self.manual_only,
        }


def split_tools(value: str) -> list[str]:
    """Tool names in an ``allowed-tools`` string: split on spaces and commas, but not inside parentheses
    (``Bash(git add:*) Read`` is two tools)."""
    tools, current, depth = [], "", 0
    for ch in str(value or ""):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if (ch.isspace() or ch == ",") and depth == 0:
            if current:
                tools.append(current)
            current = ""
        else:
            current += ch
    if current:
        tools.append(current)
    return tools


def _split(text: str) -> tuple[str, str]:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").lstrip()
    if not text.startswith("---"):
        raise SkillFormatError("A SKILL.md starts with a frontmatter block: a line of '---', then name and description, then '---'.")
    fences = list(_FENCE.finditer(text))
    if len(fences) < 2 or fences[0].start() != 0:
        raise SkillFormatError("The frontmatter has no closing '---' line.")
    return text[fences[0].end() : fences[1].start()], text[fences[1].end() :]


def _lenient_pairs(head: str) -> dict:
    """Top-level ``key: value`` lines of frontmatter that is not valid YAML; indented lines continue the previous value."""
    pairs: dict[str, str] = {}
    key = None
    for line in head.split("\n"):
        match = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if match and not line[:1].isspace():
            key = match.group(1)
            pairs[key] = match.group(2).strip()
        elif key and line.strip() and line[:1].isspace():
            pairs[key] = f"{pairs[key]} {line.strip()}".strip()
    for k, v in pairs.items():
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            pairs[k] = v[1:-1]
    return pairs


def _text(front: dict, key: str, *, required: bool = False) -> str:
    value = front.get(key)
    if value is None or value == "":
        if required:
            raise SkillFormatError(f"The frontmatter needs a {key}.")
        return ""
    if not isinstance(value, str):
        raise SkillFormatError(f"The frontmatter's {key} must be text.")
    return value.strip()


def _tools(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list | tuple):
        value = " ".join(str(v) for v in value)
    if not isinstance(value, str):
        raise SkillFormatError("The frontmatter's allowed-tools must be a space-separated list of tool names.")
    return " ".join(split_tools(value))


def check_name(name: str) -> str:
    """The name, or SkillFormatError when it isn't a valid Playbook name (also how an import's renamed name is checked)."""
    if len(name) > NAME_MAX:
        raise SkillFormatError(f"The name is at most {NAME_MAX} characters.")
    if not _NAME_RE.match(name):
        raise SkillFormatError("The name is lowercase letters and digits joined by single hyphens, like 'release-notes'.")
    return name


def parse_skill_md(text: str) -> SkillDoc:
    """Read a SKILL.md. Raises SkillFormatError when it has no frontmatter or a missing or invalid name or description."""
    head, rest = _split(text)
    try:
        front = yaml.safe_load(head)
    except yaml.YAMLError:
        front = _lenient_pairs(head)
    if front is None:
        front = {}
    if not isinstance(front, dict):
        raise SkillFormatError("The frontmatter must be 'key: value' lines.")
    front = {str(k): v for k, v in front.items()}

    name = check_name(_text(front, "name", required=True))
    description = _text(front, "description", required=True)
    if len(description) > DESCRIPTION_MAX:
        raise SkillFormatError(f"The description is at most {DESCRIPTION_MAX} characters.")
    compatibility = _text(front, "compatibility")
    if len(compatibility) > COMPATIBILITY_MAX:
        raise SkillFormatError(f"The compatibility note is at most {COMPATIBILITY_MAX} characters.")

    extra = {k: v for k, v in front.items() if k not in _KNOWN}
    marvin = _take_marvin_settings(extra)
    manual = front.get("disable-model-invocation")
    body = rest.strip("\n")
    return SkillDoc(
        name=name,
        description=description,
        body=body + "\n" if body.strip() else "",
        license=_text(front, "license"),
        compatibility=compatibility,
        allowed_tools=_tools(front.get("allowed-tools", front.get("allowed_tools"))),
        manual_only=any(str(v).strip().lower() in _TRUE for v in (manual, marvin.get(MARVIN_MANUAL_ONLY))),
        extra=extra,
    )


def _take_marvin_settings(extra: dict) -> dict:
    """Remove Marvin's own keys from ``extra["metadata"]`` (they are Playbook fields, not another tool's keys) and return them.
    Other tools' metadata stays; an emptied ``metadata`` goes."""
    metadata = extra.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    marvin = {k: v for k, v in metadata.items() if str(k).startswith(MARVIN_PREFIX)}
    rest = {k: v for k, v in metadata.items() if k not in marvin}
    if rest:
        extra["metadata"] = rest
    elif marvin:
        del extra["metadata"]
    return marvin


def render_skill_md(doc: SkillDoc) -> str:
    """The SKILL.md text for a document: standard keys first, in a fixed order, empty optional ones left out, then ``extra``."""
    head: dict = {"name": doc.name, "description": doc.description}
    if doc.license:
        head["license"] = doc.license
    if doc.compatibility:
        head["compatibility"] = doc.compatibility
    if doc.allowed_tools:
        head["allowed-tools"] = doc.allowed_tools
    if doc.manual_only:
        head["disable-model-invocation"] = True
    head.update({k: v for k, v in doc.extra.items() if k not in head})
    if doc.manual_only and isinstance(head.get("metadata", {}), dict):
        # Marvin's own settings: the standard's free-form `metadata` map (string keys and values), under keys other tools skip.
        head["metadata"] = {**head.get("metadata", {}), MARVIN_MANUAL_ONLY: "true"}
    dumped = yaml.safe_dump(head, sort_keys=False, allow_unicode=True, width=10**6, default_flow_style=False)
    body = doc.body.strip("\n")
    return f"---\n{dumped}---\n" + (f"\n{body}\n" if body.strip() else "")
