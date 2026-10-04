"""Action-executor registry for Flavor B automations.

Each action `kind` registers an executor here; the engine dispatches by kind. Mirrors
OPERATION_REGISTRY / TOOL_REGISTRY. Flavor B is NOT AI-specific — the engine and most executors have
no AI dependency; the `operation` kind is the only AI-coupled one, and it's reachable only when an
automation names an AI operation (and AI is enabled + the `automation` source is allowed).

Executor contract:
    execute(session, group_id, action: dict, context: dict, *, user_id=None,
            authorizer_role=ROLE_OWNER, dry_run=False) -> dict
`context` carries {event, entry?, previous, depth}. `authorizer_role` is the *current* numeric role
of the automation's author — the authority the action runs under (definer's rights, see authz.py);
executors gate their privilege against it. When `dry_run` is True the executor still gates + resolves
its inputs (interpolation, target lookup) but does NOT execute — it returns a preview of what it
*would* do instead of performing it. Return a dict (becomes `$previous` for the next step). Raise
:class:`AutomationActionError` on any failure — the engine logs and stops that pipeline.
"""

from collections.abc import Callable

from marvin.services.ai.operations.base import ROLE_OWNER


class AutomationActionError(Exception):
    """An action could not run (unknown kind, gate denied, missing config, or execution failed).

    ``code`` is an optional stable reason a failure handler can branch on or show (an integration's
    refusal, e.g. ``blocked``) — the message stays the human-readable account."""

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class IntegrationStepError(AutomationActionError):
    """An integration step's provider call failed — everything the engine needs to apply the
    provider's error policy (`services/integrations/errors.py`) without asking the provider again.

    ``policy`` is the resolved Handle as a dict (None: the provider declares none, or the SDK predates
    policies — the step fails as it always has). ``detail`` is the provider's own message, without
    the "<provider>.<action> failed:" prefix. ``seed`` is the idempotency seed the call ran with, so a
    retry of it reuses the same one."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        detail: str,
        integration_id,
        integration_slug: str,
        provider: str,
        provider_name: str,
        action_key: str,
        policy: dict | None = None,
        partial: dict | None = None,
        retry_after: float | None = None,
        seed: str | None = None,
    ) -> None:
        super().__init__(message, code=code)
        self.detail = detail
        self.integration_id = integration_id
        self.integration_slug = integration_slug
        self.provider = provider
        self.provider_name = provider_name
        self.action_key = action_key
        self.policy = policy
        self.partial = partial
        self.retry_after = retry_after
        self.seed = seed


ACTION_EXECUTORS: dict[str, Callable] = {}


def register_action(kind: str) -> Callable:
    """Decorator: register an executor for an action `kind`."""

    def deco(fn: Callable) -> Callable:
        ACTION_EXECUTORS[kind] = fn
        return fn

    return deco


def available_kinds() -> list[str]:
    """Action kinds that have a registered executor (drives the builder's options)."""
    return sorted(ACTION_EXECUTORS)


def run_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=ROLE_OWNER, dry_run=False) -> dict:
    """Dispatch one action to its registered executor by `kind`."""
    kind = action.get("kind")
    fn = ACTION_EXECUTORS.get(kind) if isinstance(kind, str) else None
    if fn is None:
        raise AutomationActionError(f"unsupported action kind '{kind}'")
    out = fn(session, group_id, action, context, user_id=user_id, authorizer_role=authorizer_role, dry_run=dry_run)
    return out if isinstance(out, dict) else {}
