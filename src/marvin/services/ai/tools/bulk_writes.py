"""Big bulk writes ask first — the one gate every bulk-write tool shares.

A bulk tool (attach_tag with a `filter` and a list of `tags`, …) can change hundreds of links in one
call. An agent once attached a workspace's whole tag vocabulary to every untagged asset (490 links
in one go) because the workspace let it write directly. Whatever the matrix or the approval mode
says, a call whose size crosses the thresholds below is not run unasked:

- on a run that can park (a thread to pause on), it becomes an "Ask first" pending call whose
  approval card lists the targets × items (`approval_preview`);
- where nothing can park (MarvinMCP's direct invoke, MCP `run_agent`, a delegated child, a surface without
  a thread), the tool answers with a refusal saying what it would have changed and to narrow the call or
  run it where the user can approve it (`refusal`) — and writes nothing.

A tool opts in by passing `bulk_write=` to `register_tool`: a function that sizes one call without
writing anything. `bind` turns a spec into the agent's (run, approval_check) pair.

The same gate serves tools whose ask is about *what* a call touches rather than how much: such a tool
passes `ask_first=`, a function that looks at one call and returns an `AskFirst` (the card's preview and
the refusal for runs that can't park) when the user must say yes — `archive_entries` on a published
entry, which takes it off the site. Both gates apply wherever the gate applies: a caller nobody can be asked
on behalf of (`unattended`) gets the refusal for either.
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
                f"Not done: {summary(write)} is too large to apply without the user's approval, and this call "
                "cannot pause to ask. Work in smaller steps — narrow the targets, and choose the tags that fit EACH "
                "target from what that target is, a few at a time — or run it from the Ask page or an agent "
                "conversation, where the user can approve it."
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


@dataclass(frozen=True)
class AskFirst:
    """One call an `ask_first` tool wants the user to approve."""

    preview: dict  # the approval card: `summary` plus the targets (same keys as `approval_preview`)
    refusal: str  # the tool result where the run can't park: why, and what to do instead


# A gate looks at one call: None → run it; (preview, refusal) → it needs the user's go-ahead.
Gate = Callable[[dict], tuple[dict, str] | None]


def _bulk_gate(spec, ctx) -> Gate | None:
    if getattr(spec, "bulk_write", None) is None:
        return None

    def gate(args: dict) -> tuple[dict, str] | None:
        write = size_call(spec, ctx, args)
        return (approval_preview(write), refusal(write)) if needs_approval(write) else None

    return gate


def _ask_first_gate(spec, ctx) -> Gate | None:
    ask = getattr(spec, "ask_first", None)
    if ask is None:
        return None

    def gate(args: dict) -> tuple[dict, str] | None:
        try:
            flagged = ask(ctx, args)
        except Exception:  # noqa: BLE001 — a check failure is not a reason to block; the handler reports bad input
            return None
        return (flagged.preview, flagged.refusal) if flagged is not None else None

    return gate


def _first_hit(gates: list[Gate], args: dict) -> tuple[dict, str] | None:
    for gate in gates:
        hit = gate(args)
        if hit is not None:
            return hit
    return None


def bind(spec, ctx, *, can_park: bool) -> tuple[Callable[[dict], str], Callable[[dict], dict | None] | None]:
    """The agent's (run, approval_check) for a registry tool.

    No `bulk_write` / `ask_first` → the plain handler, no check. On a run that can park, the loop asks
    `approval_check` before each call and pends the flagged ones (the handler runs only once approved).
    Otherwise the handler itself is guarded: a flagged call answers with its refusal and writes nothing.
    """
    gates = [g for g in (_bulk_gate(spec, ctx), _ask_first_gate(spec, ctx)) if g is not None]

    def run(args: dict) -> str:
        return spec.handler(ctx, args)

    if not gates:
        return run, None

    if can_park:

        def approval_check(args: dict) -> dict | None:
            hit = _first_hit(gates, args)
            return hit[0] if hit is not None else None

        return run, approval_check

    def guarded(args: dict) -> str:
        hit = _first_hit(gates, args)
        return hit[1] if hit is not None else spec.handler(ctx, args)

    return guarded, None


def unattended(spec, ctx) -> Callable[[dict], str]:
    """The handler for a caller nobody can be asked on behalf of (MarvinMCP's direct invoke, the stateless
    MCP `run_agent`): a call either gate flags — too big, or an `ask_first` tool's — answers with its refusal
    and writes nothing. Everything else runs as it would anywhere."""
    return bind(spec, ctx, can_park=False)[0]
