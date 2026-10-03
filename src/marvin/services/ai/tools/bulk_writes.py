"""Big bulk writes ask first — the one gate every bulk-write tool shares.

A bulk tool (attach_tag with a `filter` and a list of `tags`, …) can change hundreds of links in one
call. An agent once attached a workspace's whole tag vocabulary to every untagged asset (490 links
in one go) because the workspace let it write directly. Whatever the matrix or the approval mode
says, a call whose size crosses the thresholds below is not run unasked:

- on a run that can park (a thread to pause on), it becomes an "Ask first" pending call whose
  approval card lists the targets × items (`approval_preview`);
- where nothing can park (MCP `run_agent`, a delegated child, a surface without a thread), the tool
  answers with a refusal telling the model to work in smaller steps or ask the user (`refusal`).

A tool opts in by passing `bulk_write=` to `register_tool`: a function that sizes one call without
writing anything. `bind` turns a spec into the agent's (run, approval_check) pair.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

# More links than this (targets × items) in one call asks first.
BULK_WRITE_ASK_THRESHOLD = 20
# More distinct items (tags) than this onto more than one target asks first, however small the
# product: "a handful of tags on each of these" is normal; a vocabulary sprayed across a set is not.
BULK_WRITE_ASK_ITEMS = 5
# How many target names the approval card lists before "and N more".
PREVIEW_MAX_TARGETS = 50


@dataclass(frozen=True)
class BulkWrite:
    """What one bulk-write call would change: every (target × item) pair is one link."""

    action: str  # "attach" | "detach"
    item_kind: str  # "tag" | "image" …
    items: list[str]
    target_type: str  # "entry" | "asset" | "resource"
    target_ids: list = field(default_factory=list)
    # Names for the card, looked up only when a preview is built: ids → labels (same order).
    label_targets: Callable[[list], list[str]] | None = None

    @property
    def links(self) -> int:
        return len(self.target_ids) * len(self.items)


def needs_approval(write: BulkWrite | None) -> bool:
    """True when the call is too big to run without the user's go-ahead."""
    if write is None:
        return False
    if write.links > BULK_WRITE_ASK_THRESHOLD:
        return True
    return len(write.items) > BULK_WRITE_ASK_ITEMS and len(write.target_ids) > 1


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def summary(write: BulkWrite) -> str:
    verb = "Attach" if write.action == "attach" else "Detach"
    prep = "to" if write.action == "attach" else "from"
    return (
        f"{verb} {_plural(len(write.items), write.item_kind)} {prep} {_plural(len(write.target_ids), write.target_type)} "
        f"({_plural(write.links, 'link')})"
    )


def approval_preview(write: BulkWrite) -> dict:
    """What the approval card shows: the summary line, then the targets and the items in full."""
    shown = write.target_ids[:PREVIEW_MAX_TARGETS]
    labels = write.label_targets(shown) if write.label_targets else [str(i) for i in shown]
    return {
        "summary": summary(write),
        "action": write.action,
        "links": write.links,
        "targetType": write.target_type,
        "targetCount": len(write.target_ids),
        "targets": labels,
        "itemKind": write.item_kind,
        "items": list(write.items),
    }


def refusal(write: BulkWrite) -> str:
    """The tool result where the run can't park: say why, and what to do instead."""
    return json.dumps(
        {
            "error": (
                f"Not done: {summary(write)} is too large to apply without the user's approval, and this run "
                "cannot pause to ask. Work in smaller steps — choose the tags that fit EACH target from what that "
                "target is, a few at a time — or ask the user to confirm in a conversation where they can approve it."
            ),
            "targets": len(write.target_ids),
            "items": len(write.items),
            "links": write.links,
            "limit": BULK_WRITE_ASK_THRESHOLD,
        }
    )


def size_call(spec, ctx, args: dict) -> BulkWrite | None:
    """Size one call; a sizing failure is not a reason to block — the handler reports bad input itself."""
    try:
        return spec.bulk_write(ctx, args)
    except Exception:  # noqa: BLE001 — the handler surfaces the real error to the model
        return None


def bind(spec, ctx, *, can_park: bool) -> tuple[Callable[[dict], str], Callable[[dict], dict | None] | None]:
    """The agent's (run, approval_check) for a registry tool.

    No `bulk_write` → the plain handler, no check. On a run that can park, the loop asks
    `approval_check` before each call and pends the big ones (the handler runs only once approved).
    Otherwise the handler itself is guarded: a big call answers with `refusal` and writes nothing.
    """

    def run(args: dict) -> str:
        return spec.handler(ctx, args)

    if getattr(spec, "bulk_write", None) is None:
        return run, None

    if can_park:

        def approval_check(args: dict) -> dict | None:
            write = size_call(spec, ctx, args)
            return approval_preview(write) if needs_approval(write) else None

        return run, approval_check

    def guarded(args: dict) -> str:
        write = size_call(spec, ctx, args)
        return refusal(write) if needs_approval(write) else spec.handler(ctx, args)

    return guarded, None
