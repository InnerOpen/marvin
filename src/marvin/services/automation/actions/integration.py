"""`integration` action — run one action of a workspace integration (provider) and keep its result.

The step's return value is the provider's result dict, so later steps read it as
`$steps.<id>.output.<key>` — e.g. Square's `create_listing` returns the checkout URL and catalog ids,
and a following `entry` `set_metadata` step stores them on the entry that was published.

Runs with the workspace's stored integration credentials, so it needs the same privilege as calling
a webhook. A provider action that declares `requires_approval` is refused: a workflow runs unattended,
with nobody to approve it.

A provider failure is raised as :class:`IntegrationStepError`, carrying the provider's error code and
its resolved error policy, which the engine applies (`services/integrations/errors.py`): review, retry,
notify, or carry on.
"""

from ..matcher import interpolate
from .base import AutomationActionError, IntegrationStepError, register_action


def _declared_action(provider, key: str):
    for declared in getattr(provider, "actions", ()) or ():
        if getattr(declared, "key", None) == key:
            return declared
    return None


@register_action("integration")
def run_integration_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    from ..authz import INTEGRATION_ACTION_MIN_ROLE, ROLE_OWNER, require_role

    slug, key = action.get("integration"), action.get("action")
    if not slug or not key:
        raise AutomationActionError("integration action needs `integration` (the integration's slug) and `action` (the provider action key)")
    require_role(ROLE_OWNER if authorizer_role is None else authorizer_role, INTEGRATION_ACTION_MIN_ROLE, f"integration action '{slug}.{key}'")

    from marvin.services.integrations import INTEGRATIONS_AVAILABLE

    if not INTEGRATIONS_AVAILABLE:
        raise AutomationActionError("integrations are not available on this install (SDK not installed)")

    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.services.integrations import IntegrationContext, build_http, get_provider
    from marvin.services.secrets.resolver import resolve_secret

    row = session.query(IntegrationModel).filter_by(group_id=group_id, slug=slug).first()
    if row is None:
        raise AutomationActionError(f"integration '{slug}' not found in this workspace")
    if not row.enabled:
        raise AutomationActionError(f"integration '{slug}' is disabled")
    try:
        provider = get_provider(row.provider)
    except KeyError as e:
        raise AutomationActionError(f"provider '{row.provider}' is not installed") from e

    declared = _declared_action(provider, key)
    if declared is None:
        raise AutomationActionError(f"provider '{row.provider}' has no action '{key}'")
    if getattr(declared, "requires_approval", False):
        raise AutomationActionError(f"'{row.provider}.{key}' requires approval and cannot run from a workflow")

    args = interpolate(action.get("args") or {}, context)
    if not isinstance(args, dict):
        raise AutomationActionError("integration action `args` must be an object")
    if dry_run:
        return {"dry_run": True, "kind": "integration", "integration": slug, "action": key, "args": args}
    from marvin.services.integrations.arg_secrets import MissingSecretError, resolve_arg_secrets

    try:
        args = resolve_arg_secrets(args, group_id)  # {{SLUG}} → the secret, for this call only
    except MissingSecretError as e:
        raise AutomationActionError(str(e)) from e

    from marvin.services.integrations import errors

    secret = resolve_secret(row.secret_ref, group_id) if row.secret_ref else None
    # A retry resumes from the provider's partial progress with the same idempotency seed (SDK 0.5.0+).
    resume, seed = errors.resume_state(session, group_id, row.id, key, context)
    ctx = errors.build_context(
        IntegrationContext, config=row.config or {}, secret=secret, logger=_logger(), http=build_http(), resume=resume, idempotency_seed=seed
    )
    try:
        result = provider.run_action(key, args, ctx)
    except Exception as e:  # noqa: BLE001 — every provider failure becomes a step failure the error policy can handle
        # A provider tags its error with a stable `code` (e.g. "blocked") — what its error policy and
        # on_failure steps branch on; anything untagged is "unknown".
        code = errors.error_code(e)
        raise IntegrationStepError(
            f"{row.provider}.{key} failed: {e}",
            code=code,
            detail=str(e),
            integration_id=row.id,
            integration_slug=slug,
            provider=row.provider,
            provider_name=getattr(provider, "name", None) or row.provider,
            action_key=key,
            policy=errors.policy_for(provider, key, code, row.error_overrides),
            partial=errors.error_partial(e),
            retry_after=errors.error_retry_after(e),
            seed=seed,
        ) from e
    errors.action_succeeded(session, group_id, row.id, key, context)
    return result if isinstance(result, dict) else {}


def _logger():
    from marvin.core.root_logger import get_logger

    return get_logger(__name__)
