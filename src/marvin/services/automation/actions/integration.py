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

`integration` may be a template (``${event.integration}``) on a capability step, resolved when the step runs: a run that
starts on ``social_comment_received`` answers the comment on the connection it came through. An action step names its slug.

`capability: "social.post"` posts to social networks (services/integrations/social.py): `images` may be library assets
(resolved to their public URLs), `per_network` overrides the arguments for one network, and it runs only after a person
approved the run — an Approval step earlier in the workflow (`approved_in_run`). With no `integration` it posts to every
enabled integration in the workspace that offers it, one after another by slug: output `results` (one entry per
network: integration, network, posted, url, post_id, error), `posted_count`, `failed_count`. One failing doesn't stop
the others; the step fails at the end when any failed, unless `fail_on_error: false`. A dry run asks each plugin what it
would post (`dry_run: true` in its arguments) and sends nothing.

The engagement capabilities (`social.comments`, `social.reply`, `social.like`, `social.hide`, `social.delete_comment`,
`social.repost`, `social.message`; services/integrations/social.py) act on one network's own ids, so they never fan out:
the step names its `integration` (a missing one is refused at save and here). `social.reply`, `social.message`,
`social.repost` and `social.delete_comment` need an Approval step before them, like `social.post`; `social.comments`,
`social.like` and `social.hide` don't. `social.reply` and `social.message` take `dry_run` from the run, as `social.post`
does. The one unattended sender is the engagement engine (services/integrations/social_engagement.py), not a step.

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


def approved_in_run(context: dict, dry_run: bool = False) -> bool:
    """Whether a person has approved this run — what lets an approval-gated action run. The engine resumes a run past an
    Approval step as ``_approved`` (engine.resume_after_approval); a dry run goes on as if approved once it has passed an
    Approval step (``_approval_ahead``, set by the approval step's preview)."""
    return context.get("_approved") is True or bool(dry_run and context.get("_approval_ahead"))


@register_action("integration")
def run_integration_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    from ..authz import INTEGRATION_ACTION_MIN_ROLE, ROLE_OWNER, require_role

    slug, key, capability = action.get("integration"), action.get("action"), action.get("capability")
    if isinstance(slug, str) and "${" in slug:
        # `integration: "${event.integration}"`: the slug a social_comment_received run carries. Only a capability step may take
        # one (an action key belongs to one provider), and it has to come out as a slug.
        if key:
            raise AutomationActionError("a templated `integration` goes with a `capability` step: an action key belongs to one provider")
        slug = str(interpolate(slug, context) or "").strip()
        if not slug:
            raise AutomationActionError(f"`integration` ({action['integration']}) came out empty: the run carries no connection to act on")
        action = {**action, "integration": slug}
    if not (key or capability) or not (slug or (capability and not key)):
        raise AutomationActionError(
            "integration action needs `integration` (the integration's slug) and `action` (the provider action key) or `capability` "
            "(only a `capability` step may leave `integration` out, to run on every integration that offers it)"
        )
    require_role(
        ROLE_OWNER if authorizer_role is None else authorizer_role,
        INTEGRATION_ACTION_MIN_ROLE,
        f"integration action '{slug or 'every integration'}.{key or capability}'",
    )

    from marvin.services.integrations import INTEGRATIONS_AVAILABLE

    if not INTEGRATIONS_AVAILABLE:
        raise AutomationActionError("integrations are not available on this install (SDK not installed)")
    from marvin.services.integrations.social import ENGAGEMENT_CAPABILITIES

    if not slug and capability in ENGAGEMENT_CAPABILITIES:
        raise AutomationActionError(
            f"'{capability}' acts on one network's own comment or post: name its `integration` (it never runs on every network)"
        )

    from marvin.db.models.groups.integrations import IntegrationModel

    if not slug:
        return _fan_out(session, group_id, action, context, user_id=user_id, dry_run=dry_run)
    row = session.query(IntegrationModel).filter_by(group_id=group_id, slug=slug).first()
    if row is None:
        raise AutomationActionError(f"integration '{slug}' not found in this workspace")
    if not row.enabled:
        raise AutomationActionError(f"integration '{slug}' is disabled")
    return _run_on(session, group_id, row, action, context, user_id=user_id, dry_run=dry_run)


def _run_on(session, group_id, row, action: dict, context: dict, *, user_id, dry_run) -> dict:
    """The step's action on one integration (a row of this workspace, enabled): its output."""
    from marvin.services.integrations import get_provider
    from marvin.services.integrations.social import DRY_RUN_CAPABILITIES, ENGAGEMENT_CAPABILITIES, SOCIAL_POST

    slug, key, capability = row.slug, action.get("action"), action.get("capability")
    try:
        provider = get_provider(row.provider)
    except KeyError as e:
        raise AutomationActionError(f"provider '{row.provider}' is not installed") from e

    args = interpolate(action.get("args") or {}, context)
    if not isinstance(args, dict):
        raise AutomationActionError("integration action `args` must be an object")
    approved = approved_in_run(context, dry_run)
    if not key:  # a capability: this provider's action for it, with the arguments in its terms
        from marvin.services.integrations.alert_routing import capability_action

        found = capability_action(provider, capability, args, approved=approved)
        if found is None:
            if approved is False and capability_action(provider, capability, args, approved=True) is not None:
                raise AutomationActionError(
                    f"'{row.provider}' needs a person's approval to {capability}: put an Approval step before it (it runs once approved)"
                )
            raise AutomationActionError(f"'{slug}' ({row.provider}) can't {capability}: it has no action for that")
        key, args = found
    by_capability = not action.get("action")  # a step that names the action passes that action's own arguments
    social = capability == SOCIAL_POST and by_capability
    engagement = capability in ENGAGEMENT_CAPABILITIES and by_capability
    if social:
        args = _social_args(session, group_id, row, action, args, context, dry_run)
    elif engagement:
        args = _engagement_args(row, capability, args, dry_run)

    declared = _declared_action(provider, key)
    if declared is None:
        raise AutomationActionError(f"provider '{row.provider}' has no action '{key}'")
    # An action that needs a person's approval runs only in a run resumed `approved` at an approval step (a dry run
    # previews it after one) — services/automation/approvals.py.
    from marvin.services.integrations.alert_routing import needs_approval

    if needs_approval(declared) and not approved:
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
        if (social or (engagement and capability in DRY_RUN_CAPABILITIES)) and (gate is None or not gate.duplicate):
            # A social post (or reply, or message): the plugin is asked what it would send (args.dry_run; it sends nothing)
            # so the preview shows its answer — and its refusal, e.g. a text too long for the network.
            answer = _call_provider(session, group_id, row, provider, key, args, src, keeps_images, action, context, user_id, dry_run=True)
            preview = {**answer, **preview}
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


def _social_args(session, group_id, row, action: dict, args: dict, context: dict, dry_run: bool) -> dict:
    """A social.post call's arguments for this integration: the step's, with its `per_network` entry (matched by the
    provider's name, then the integration's slug) over them, `images` as public URLs, and `dry_run` set by the run alone
    (a `dry_run` typed into the arguments is ignored: it would make a real post a quiet no-op that an idempotency key then remembers)."""
    from marvin.services.integrations.social import SocialPostError, post_args

    try:
        merged = post_args(session, group_id, args, interpolate(action.get("per_network"), context), row.provider, row.slug)
    except SocialPostError as e:
        raise AutomationActionError(f"{row.slug}: {e}") from e
    return {**merged, "dry_run": bool(dry_run)}


def _engagement_args(row, capability: str, args: dict, dry_run: bool) -> dict:
    """A social engagement call's arguments: the step's, checked for what the capability needs, `dry_run` set by the run alone."""
    from marvin.services.integrations.social import SocialPostError, engagement_args

    try:
        return engagement_args(capability, args, dry_run)
    except SocialPostError as e:
        raise AutomationActionError(f"{row.slug}: {e}") from e


def _fan_out(session, group_id, action: dict, context: dict, *, user_id, dry_run) -> dict:
    """A capability step with no `integration`: the action on every enabled integration that offers the capability, one
    after another by slug. Each is its own call (its own idempotency claim, its own failure): the output lists them, and
    the step fails at the end if any failed, unless `fail_on_error: false`."""
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.services.integrations import get_provider
    from marvin.services.integrations.alert_routing import GATED_CAPABILITIES, capability_action

    capability = action["capability"]
    if capability in GATED_CAPABILITIES and not approved_in_run(context, dry_run):
        # Everything is refused up front, before the first network: a post goes out only once a person approved it.
        raise AutomationActionError(f"'{capability}' needs a person's approval: put an Approval step before it (it runs once approved)")
    rows = []
    for row in session.query(IntegrationModel).filter_by(group_id=group_id, enabled=True).order_by(IntegrationModel.slug).all():
        try:
            provider = get_provider(row.provider)
        except KeyError:
            continue
        if capability_action(provider, capability, {}, approved=True) is not None:
            rows.append((row, provider))
    if not rows:
        raise AutomationActionError(f"no connected integration can {capability}: connect one in Settings → Integrations")
    results = [_fan_out_one(session, group_id, row, provider, action, context, user_id, dry_run) for row, provider in rows]
    failed = [r for r in results if r["error"]]
    out = {
        "results": results,
        "posted_count": sum(1 for r in results if r["posted"]),
        "failed_count": len(failed),
    }
    if dry_run:
        return {"dry_run": True, "kind": "integration", "capability": capability, **out}
    if failed and action.get("fail_on_error", True):
        said = "; ".join(f"{r['integration']}: {r['error']}" for r in failed)
        done = ", ".join(r["integration"] for r in results if r["posted"])
        raise AutomationActionError(
            f"{len(failed)} of {len(results)} failed to {capability} — {said}" + (f" (posted to {done})" if done else " (nothing was posted)"),
            code="partial_failure" if done else None,
        )
    return out


def _fan_out_one(session, group_id, row, provider, action: dict, context: dict, user_id, dry_run) -> dict:
    """One integration's entry in a fan-out's `results`: the call's outcome, or why it failed."""
    entry = {"integration": row.slug, "network": row.provider, "posted": False, "url": None, "post_id": None, "error": None}
    try:
        out = _run_on(session, group_id, row, action, context, user_id=user_id, dry_run=dry_run)
    except Exception as e:  # noqa: BLE001 — one network failing never stops the others; it is this entry's error
        entry["error"] = str(e) or type(e).__name__
        return entry
    entry["network"] = out.get("network") or row.provider
    entry["url"], entry["post_id"] = out.get("url"), out.get("post_id")
    if dry_run:
        entry["would_post"] = out.get("would_post")
        return entry
    entry["posted"] = bool(out.get("posted", True))
    if not entry["posted"]:
        entry["error"] = str(out.get("error") or "the network did not post it")
    if (out.get("idempotency") or {}).get("duplicate"):
        entry["duplicate"] = True
    return entry


def _call_provider(session, group_id, row, provider, key, args, src, keeps_images, action, context, user_id, *, dry_run=False) -> dict:
    """Make the provider call with the workspace's credentials and keep what it returns (the step's output)."""
    from marvin.services.integrations import IntegrationContext, build_http
    from marvin.services.secrets.resolver import resolve_secret

    from .media import keep_generated_images

    slug = row.slug
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
    if not dry_run:  # a dry run asked the plugin what it would do: nothing was spent, nothing is proven to work
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
