"""Correlation id — one id shared by every event + execution in a single causal chain.

A user publishes an entry → that emits ``entry_updated`` + ``entry_published`` → an automation reacts
and re-emits ``entry_archived`` → another automation calls a webhook. That is *one* causal chain, and
being able to see it as one thread is the difference between a readable audit log and a pile of
unrelated rows.

The mechanism is an **ambient scope** (a ``ContextVar``), not a parameter threaded through every
call: whoever roots a chain opens a :func:`correlation_scope`, and every ``dispatch(...)`` inside it
(directly, or via EntryService / the automation engine's re-emissions) inherits the same id — read
synchronously at dispatch-call time, so it is baked into the ``Event`` even when publishing is
deferred to a background task. Callers may still pass an explicit ``correlation_id`` to ``dispatch``
to override.

Roots that open a scope: the automation engine (per triggering event, so a whole reaction cascade
shares the triggering event's id) and EntryService's multi-event mutations (so ``entry_updated`` and
its transition event share one id). Anything dispatched entirely outside a scope simply mints its own
id — every event is always correlatable, chain or not.
"""

import uuid
from contextlib import contextmanager
from contextvars import ContextVar

# The correlation id in effect on the current call stack (None when no chain is open).
current_correlation_id: ContextVar[str | None] = ContextVar("current_correlation_id", default=None)

# The workflows whose runs are on the current call stack (their keys: the automation id). Like the correlation id it is
# read synchronously by ``dispatch`` and baked into the ``Event`` (``caused_by_workflows``), so an event a run sends
# still says which workflows caused it after the run has ended — when a deferred webhook delivery of it fails.
workflows_running: ContextVar[frozenset[str]] = ContextVar("automations_running", default=frozenset())

# The reaction depth work on the current call stack is at least (the loop guard's hop count). A workflow's agent step sets it
# to its run's depth + 1 around the agent, whose tools save entries through services that know nothing of the run: whatever
# they dispatch still counts as a hop of the chain. ``dispatch`` takes the larger of this and the depth it was given.
reaction_depth_floor: ContextVar[int] = ContextVar("reaction_depth_floor", default=0)


def new_correlation_id() -> str:
    return uuid.uuid4().hex


@contextmanager
def correlation_scope(correlation_id: str | None = None):
    """Open a correlation scope. With an explicit id, use it (root a chain at a known id, e.g. the
    triggering event's). With ``None``, **inherit** the ambient id if a chain is already open, else
    **mint** a fresh one. Yields the resolved id and restores the previous scope on exit."""
    resolved = correlation_id or current_correlation_id.get() or new_correlation_id()
    token = current_correlation_id.set(resolved)
    try:
        yield resolved
    finally:
        current_correlation_id.reset(token)


@contextmanager
def reaction_depth_at_least(depth: int):
    """Everything dispatched inside carries a reaction depth of at least ``depth`` (see ``reaction_depth_floor``)."""
    token = reaction_depth_floor.set(max(depth, reaction_depth_floor.get()))
    try:
        yield
    finally:
        reaction_depth_floor.reset(token)
