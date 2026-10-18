"""`integration` action — run one action of a workspace integration (provider) and keep its result.

The step's return value is the provider's result dict, so later steps read it as
`$steps.<id>.output.<key>` — e.g. Square's `create_listing` returns the checkout URL and catalog ids,
and a following `entry` `set_metadata` step stores them on the entry that was published.

Runs with the workspace's stored integration credentials, so it needs the same privilege as calling
a webhook. A provider action that declares `requires_approval` is refused: a workflow runs unattended,
with nobody to approve it.

A step may name a `capability` instead of an `action` — `notify` sends through whichever integration it names,
Slack or Apprise alike (services/integrations/alert_routing.py: capability_action), with the standard `title`
and `body` arguments; the Workflow Library's notification recipes are written that way.

A provider failure is raised as :class:`IntegrationStepError`, carrying the provider's error code and
its resolved error policy, which the engine applies (`services/integrations/errors.py`): review, retry,
notify, or carry on.

An action with an `image.*` capability (OpenAI Images' `generate`) returns pictures: each is kept as an asset and
replaced by a reference (`images: [{asset: {id, slug, url, …}}]`) before the output reaches the run, so a run can wait
for approval after generating and be retried — see media.keep_generated_images. `attach_as` links them to the run's
entry in that role.
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

    slug, key, capability = action.get("integration"), action.get("action"), action.get("capability")
    if not slug or not (key or capability):
        raise AutomationActionError(
            "integration action needs `integration` (the integration's slug) and `action` (the provider action key) or `capability`"
        )
    require_role(
        ROLE_OWNER if authorizer_role is None else authorizer_role, INTEGRATION_ACTION_MIN_ROLE, f"integration action '{slug}.{key or capability}'"
    )

    from marvin.services.integrations import INTEGRATIONS_AVAILABLE

    if not INTEGRATIONS_AVAILABLE:
        raise AutomationActionError("integrations are not available on this install (SDK not installed)")

    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.services.integrations import get_provider

    row = session.query(IntegrationModel).filter_by(group_id=group_id, slug=slug).first()
    if row is None:
        raise AutomationActionError(f"integration '{slug}' not found in this workspace")
    if not row.enabled:
        raise AutomationActionError(f"integration '{slug}' is disabled")
    try:
        provider = get_provider(row.provider)
    except KeyError as e:
        raise AutomationActionError(f"provider '{row.provider}' is not installed") from e

    args = interpolate(action.get("args") or {}, context)
    if not isinstance(args, dict):
        raise AutomationActionError("integration action `args` must be an object")
    if not key:  # a capability: this provider's action for it, with the arguments in its terms
        from marvin.services.integrations.alert_routing import capability_action

        found = capability_action(provider, capability, args)
        if found is None:
            raise AutomationActionError(f"'{slug}' ({row.provider}) can't {capability}: it has no action for that")
        key, args = found

    declared = _declared_action(provider, key)
    if declared is None:
        raise AutomationActionError(f"provider '{row.provider}' has no action '{key}'")
    # An action that needs a person's approval runs only in a run resumed `approved` at an approval step (a dry run
    # previews it after one) — services/automation/approvals.py.
    if getattr(declared, "requires_approval", False) and not (context.get("_approved") is True or (dry_run and context.get("_approval_ahead"))):
        raise AutomationActionError(f"'{row.provider}.{key}' requires approval: put an Approval step before it (it runs once approved)")
    from .media import returns_images

    keeps_images = returns_images(declared)
    src = _source_picture(session, group_id, action, context, keeps_images)
    # An idempotency_key that already made this call within its window: nothing is called, the earlier output is reused.
    from .. import idempotency

    gate = idempotency.open_gate(session, group_id, action, context, destination=f"integration:{slug}.{key}", dry_run=dry_run)
    if gate is not None and gate.duplicate and not dry_run:
        return gate.skipped()
    if dry_run:
        preview = {"dry_run": True, "kind": "integration", "integration": slug, "action": key, "args": args}
        if src is not None:
            preview["source"] = src.slug
        if keeps_images:
            preview["keeps_images_as_assets"] = True
            if action.get("attach_as"):
                preview["attach_as"] = interpolate(action["attach_as"], context)
        if gate is None:
            return preview
        return gate.skipped(preview) if gate.duplicate else {**preview, **gate.preview()}
    try:
        out = _call_provider(session, group_id, row, provider, key, args, src, keeps_images, action, context, user_id)
    except BaseException:
        if gate is not None:
            gate.release()  # a call that failed is made again by the retry, not skipped as a duplicate
        raise
    if gate is not None:
        gate.complete(out)
    return out


def _call_provider(session, group_id, row, provider, key, args, src, keeps_images, action, context, user_id) -> dict:
    """Make the provider call with the workspace's credentials and keep what it returns (the step's output)."""
    from marvin.services.integrations import IntegrationContext, build_http
    from marvin.services.secrets.resolver import resolve_secret

    from .media import keep_generated_images

    slug = action.get("integration")
    from marvin.services.integrations.arg_secrets import MissingSecretError, resolve_arg_secrets

    try:
        resolved = resolve_arg_secrets(args, group_id)  # {{SLUG}} → the secret, for this call only
    except MissingSecretError as e:
        raise AutomationActionError(str(e)) from e
    # The values {{SLUG}} resolved to — scrubbed from any error the provider raises, like its credential.
    arg_secrets = [v for k, v in resolved.items() if isinstance(v, str) and v != args.get(k)]
    plain_args, args = args, resolved  # what the workflow says (an image's lineage keeps its prompt without secrets)
    if src is not None:  # the picture, for this call only — never in the step's output or the image's lineage
        import base64

        from .media import _read_bytes

        args = {**args, "image_b64": base64.b64encode(_read_bytes(session, group_id, src)).decode("ascii"), "image_mime": src.mime_type}

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
        detail = errors.redact(str(e), errors.secret_values(secret, *arg_secrets))
        raise IntegrationStepError(
            f"{row.provider}.{key} failed: {detail}",
            code=code,
            detail=detail,
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
    out = result if isinstance(result, dict) else {}
    if keeps_images:
        made_by = f"{row.provider}.{key}"
        out = keep_generated_images(
            session,
            group_id,
            out,
            generated_by=made_by,
            args=plain_args,
            context=context,
            user_id=user_id,
            attach_as=action.get("attach_as"),
            tags=action.get("tags"),
            source=src,
        )
    return out


def _source_picture(session, group_id, action: dict, context: dict, keeps_images: bool):
    """The picture an image.* action works on (`source`, as a media step's), or None."""
    if not action.get("source"):
        return None
    if not keeps_images:
        raise AutomationActionError("source goes with an action that works on a picture (an image.* capability, e.g. image.edit)")
    from marvin.services.ai.media import transforms

    from .media import resolve_source

    src = resolve_source(session, group_id, action["source"], context)
    if not transforms.can_transform(src.mime_type):
        raise AutomationActionError(f"“{src.name}” ({src.mime_type or 'unknown type'}) is not an image Marvin can process (jpeg, png or webp)")
    return src


def _logger():
    from marvin.core.root_logger import get_logger

    return get_logger(__name__)
