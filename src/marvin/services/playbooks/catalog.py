"""What a run's system prompt says about Playbooks: the catalog of those it may load, the "always load" ones in full, and
the guidance to propose a better one. Shared by every way an agent runs (Ask and the bubble, ``run_agent``) through
``frame_block``, so they frame a run the same way."""

from __future__ import annotations

from collections.abc import Iterable

from marvin.services.playbooks import (
    LIST_TOOL,
    LOAD_TOOL,
    Playbook,
    PlaybookScope,
    always_playbooks,
    published_playbooks,
)

CATALOG_MAX = 50  # Playbooks named in the prompt; the rest are still found with list_playbooks
CATALOG_LINE_CHARS = 200
ALWAYS_WARN_CHARS = 12_000  # about 3,000 tokens of instructions in every run's system prompt


def always_block(playbooks: Iterable[Playbook]) -> str:
    """The system-frame section with each "always load" Playbook in full; "" when there are none."""
    listed = list(playbooks)
    if not listed:
        return ""
    parts = ["## Playbooks to follow in every conversation\nThese Playbooks are already loaded: follow them without calling " + LOAD_TOOL + "."]
    parts += [f"### {p.name}\n{p.body.strip()}" for p in listed]
    return "\n\n".join(parts)


def always_warning(playbooks: Iterable[Playbook]) -> str | None:
    """A warning when the "always load" Playbooks are long (they ride along with every run); None when they are not."""
    size = sum(len(p.body) for p in playbooks)
    if size <= ALWAYS_WARN_CHARS:
        return None
    return (
        f"These always-loaded Playbooks add about {size // 4:,} tokens ({size:,} characters) to every run of this agent. "
        "Consider loading the long ones on demand instead."
    )


PROPOSE_HINT = (
    "If you notice a correction people keep making, or a better way to do a task, you may propose it: draft a new Playbook "
    "with create_draft, or a change to one of these with propose_playbook_change. It goes to the Inbox for an admin to review; "
    "you never publish or edit a Playbook yourself.\n"
)


def catalog_block(playbooks: Iterable[Playbook], can_propose: bool = False) -> str:
    """The system-frame paragraph naming the Playbooks, one line each; "" when there are none (nothing is added).
    ``can_propose``: the agent can draft, so it is also told when to propose a Playbook."""
    listed = list(playbooks)
    if not listed:
        return ""
    lines = []
    for p in listed[:CATALOG_MAX]:
        text = " ".join(p.description.split())
        if len(text) > CATALOG_LINE_CHARS:
            text = text[: CATALOG_LINE_CHARS - 1].rstrip() + "…"
        lines.append(f"- {p.name}: {text}")
    more = f"\n({len(listed) - CATALOG_MAX} more: call {LIST_TOOL} to see them.)" if len(listed) > CATALOG_MAX else ""
    return (
        "## Playbooks\n"
        "This workspace keeps Playbooks: written procedures for particular tasks. When a request matches one of the "
        f"descriptions below, call {LOAD_TOOL} with its name before you start, then follow it using the tools you already "
        "have. A Playbook never gives you more tools or permissions, and one that does not fit the request is not loaded.\n"
        + (PROPOSE_HINT if can_propose else "")
        + "\n".join(lines)
        + more
    )


def frame_block(session, group_id, scope: PlaybookScope, tool_names: Iterable[str]) -> str:
    """The Playbook sections of a run's system frame, shared by every way an agent runs (Ask and the bubble, ``run_agent``): the
    catalog of what ``scope`` may load (when ``load_playbook`` is among ``tool_names`` and there is any), then the agent's
    "always load" Playbooks in full. "" when there is nothing to add."""
    names = set(tool_names)
    parts = []
    if LOAD_TOOL in names:
        can_propose = "propose_playbook_change" in names or "create_draft" in names
        if catalog := catalog_block(published_playbooks(session, group_id, scope), can_propose):
            parts.append(catalog)
    if always := always_block(always_playbooks(session, group_id, scope)):
        parts.append(always)
    return "\n\n".join(parts)
