"""`{{SLUG}}` in an integration action's arguments → that workspace secret's value.

The same reference rule integration credentials use, for actions that must hand a secret to the
provider — e.g. Cloudflare Pages' Connect notifications needs the webhook's signing secret to set up
Cloudflare's side — so nobody pastes a secret into a form or a workflow. Only a whole top-level
string value that is exactly a reference is resolved, only from the action's own workspace, and the
resolved value goes to the provider call only (never back into the stored workflow or the response).
"""

import re

_REFERENCE = re.compile(r"^\{\{\s*([A-Za-z0-9_]+)\s*\}\}$")


class MissingSecretError(ValueError):
    """An argument names a workspace secret that doesn't exist."""


def resolve_arg_secrets(args: dict | None, group_id) -> dict:
    from marvin.services.secrets.resolver import resolve_secret

    out = dict(args or {})
    for key, value in out.items():
        match = _REFERENCE.match(value.strip()) if isinstance(value, str) else None
        if not match:
            continue
        resolved = resolve_secret(match.group(1), group_id)
        if resolved is None:
            raise MissingSecretError(f"argument '{key}' names workspace secret '{match.group(1)}', which doesn't exist")
        out[key] = resolved
    return out
