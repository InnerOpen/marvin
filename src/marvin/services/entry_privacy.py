"""What a member sees of a submitter's IP address.

A form submission records where it came from on the entry itself: ``metadata_json.submission.ip_address`` (with the user agent and
referrer). Whoever reads the entry reads it, so every place that hands an entry's metadata to a member goes through here: an ADMIN or
above sees the address whole, anyone else sees it with its host part hidden (``203.0.113.x``; IPv6: the first three groups).

The places (grep ``entry_privacy`` for the list): the entries API and the collection entry list (routes/platform), the assistants'
and MCP's ``get_entry`` and ``find_entries`` (services/ai/tools/builtins.py), the snapshot diff (services/snapshots.py) and Audience
(services/audience.py). The publishing API serves a site, not a member, so it drops the address altogether (``strip_submission_ip``).

A member who saves an entry in the editor sends the metadata back as they read it, masked address included. The server recorded the
address, so ``keep_recorded_ip`` puts the stored one back instead of overwriting it with its masked form.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from marvin.db.models.users.roles import WorkspaceRole

IP_KEY = "ip_address"
SUBMISSION_KEY = "submission"


def mask_ip(ip: str | None) -> str | None:
    """An IP with its host part hidden: 203.0.113.x for IPv4, the first three groups for IPv6. Anything unparseable is hidden whole."""
    if not ip:
        return None
    try:
        address = ipaddress.ip_address(ip.strip())
    except ValueError:
        return "hidden"
    if address.version == 4:
        return ".".join(str(address).split(".")[:3] + ["x"])
    return ":".join(address.exploded.split(":")[:3]) + "::x"


def can_see_full_ip(user: Any, group_id) -> bool:
    """ADMIN and above (and platform admins). No user (a system caller) is treated as below: masked is the safe default."""
    from marvin.routes._base.checks import has_workspace_role

    return has_workspace_role(user, group_id, WorkspaceRole.ADMIN)


def recorded_ip(metadata: Any) -> str | None:
    """The IP a submission recorded in this entry metadata, or None."""
    submission = metadata.get(SUBMISSION_KEY) if isinstance(metadata, dict) else None
    ip = submission.get(IP_KEY) if isinstance(submission, dict) else None
    return ip if isinstance(ip, str) and ip else None


def _with_ip(metadata: dict, value: str | None, *, drop: bool = False) -> dict:
    submission = dict(metadata[SUBMISSION_KEY])
    if drop:
        submission.pop(IP_KEY, None)
    else:
        submission[IP_KEY] = value
    return {**metadata, SUBMISSION_KEY: submission}


def mask_submission_ip(metadata: Any) -> Any:
    """``metadata`` with the recorded IP masked (a copy; the argument is untouched). Anything without one comes back as it is."""
    ip = recorded_ip(metadata)
    return _with_ip(metadata, mask_ip(ip)) if ip is not None else metadata


def strip_submission_ip(metadata: Any) -> Any:
    """``metadata`` without the recorded IP at all: for the publishing API, which serves a site rather than a member."""
    return _with_ip(metadata, None, drop=True) if recorded_ip(metadata) is not None else metadata


def metadata_for(metadata: Any, full_ip: bool) -> Any:
    """What a reader may see of an entry's metadata."""
    return metadata if full_ip else mask_submission_ip(metadata)


def entry_for(entry, full_ip: bool):
    """An ``EntryRead`` as the reader may see it: the same entry, its metadata's IP masked unless ``full_ip``."""
    if full_ip or entry is None or recorded_ip(getattr(entry, "metadata_json", None)) is None:
        return entry
    return entry.model_copy(update={"metadata_json": mask_submission_ip(entry.metadata_json)})


def entries_for(entries, full_ip: bool) -> list:
    return [entry_for(e, full_ip) for e in entries]


def keep_recorded_ip(stored: Any, incoming: Any) -> Any:
    """Metadata a member sends back, with the IP the server recorded kept as it was (they only ever saw it masked)."""
    recorded = recorded_ip(stored)
    if recorded is None or not isinstance(incoming, dict) or recorded_ip(incoming) == recorded:
        return incoming
    if not isinstance(incoming.get(SUBMISSION_KEY), dict):
        incoming = {**incoming, SUBMISSION_KEY: {}}
    return _with_ip(incoming, recorded)


def mask_event_ips(data: Any) -> Any:
    """An event payload with every ``ip_address`` / ``ipAddress`` string masked (a copy): the ``form_submission_received`` event carries
    the submitter's address, and the Event Log's detail shows the payload to any member."""
    if isinstance(data, dict):
        return {k: (mask_ip(v) if k in ("ip_address", "ipAddress") and isinstance(v, str) else mask_event_ips(v)) for k, v in data.items()}
    if isinstance(data, list):
        return [mask_event_ips(v) for v in data]
    return data
