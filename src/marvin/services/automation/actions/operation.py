"""`operation` action — run an AI operation (the only AI-coupled action kind).

Thin adapter over the AI runner. Reachable only when an automation names an AI operation; the runner
enforces the `automation` invocation-source gate, so if AI is off / the source is disabled, the
action fails cleanly rather than running.
"""

from .base import register_action


@register_action("operation")
def run_operation(session, group_id, action, context, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    from ..runner import run_operation_action

    return run_operation_action(session, group_id, action, context, user_id=user_id, authorizer_role=authorizer_role, dry_run=dry_run)
