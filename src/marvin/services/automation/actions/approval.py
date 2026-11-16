"""Executor for the ``approval`` step: wait for a person (services/automation/approvals.py).

It doesn't wait itself: it resolves the message and hands the engine a park request (``PARK``), and the engine parks
the run there — recorded, the run ends ``waiting`` — until a decision resumes it from the next step. A dry run shows
what would be asked and doesn't wait.

Its `fields` (boxes the approver may change, e.g. the prompt a paid step sends) are resolved here, each starting from
the text a Redo with changes carried to this entry, else its `value` (approvals.starting_fields). With `approved_when`
holding, nobody is asked: the step goes on at once as approved, the boxes as they are.
"""

from __future__ import annotations

from ..matcher import interpolate
from .base import AutomationActionError, register_action

PARK = "_park"  # the key a park request comes back under (engine._StepRunner parks on it)
MAX_CHOICES = 8
MAX_LABEL = 200


@register_action("approval")
def run_approval_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    message = str(interpolate(action.get("message") or "", context) or "").strip()
    if not message:
        raise AutomationActionError("an approval step needs a message: what the approvers are asked")
    approvers = action.get("approvers") or "editor"
    from ..engine import approval_default_hours

    hours = int(action.get("expires_in_hours") or approval_default_hours(session, group_id))
    choices = _choices(action.get("choices"), context)
    image = _image(action.get("image"), context)
    detail = str(interpolate(action.get("detail") or "", context) or "").strip()
    from ..approvals import auto_approved, starting_fields

    entry_id = (context.get("entry") or {}).get("id")
    fields = starting_fields(session, group_id, entry_id, action.get("fields"), context, take=not dry_run)
    if action.get("approved_when") and _holds(action["approved_when"], context):
        return auto_approved(fields, choices)
    if dry_run:
        from ..approvals import question

        context["_approval_ahead"] = True  # the preview goes on as if approved, so the steps it guards show too
        message, kept = question(message, detail)  # as it would be asked: a long message cut, the whole of it in the detail
        out = {"dry_run": True, "kind": "approval", "message": message, "approvers": approvers, "expires_in_hours": hours, "would_wait": True}
        out.update({**({"detail": kept} if kept else {}), **({"choices": choices} if choices else {}), **({"image": image} if image else {})})
        if fields:  # the steps after it read the boxes as they would be approved unchanged
            out.update({"fields": {f["name"]: f["value"] for f in fields}, "edited": []})
        return out
    spec = {"message": message, "approvers": approvers, "expires_in_hours": hours, **({"image": image} if image else {})}
    if detail:
        spec["detail"] = detail
    if fields:
        spec["fields"] = fields
        if action.get("redo"):
            spec["redo"] = str(action["redo"])
    return {PARK: {**spec, "choices": choices} if choices else spec}


def _holds(conditions, context: dict) -> bool:
    from ..matcher import matches

    return bool(matches(conditions, context))


def _image(raw, context: dict) -> str | None:
    """The picture to show with the question: the template resolved to a URL. Nothing to show when the step names none
    or the template resolves empty (the picture is a courtesy, never a reason to fail the run); anything that isn't a URL
    is a mistake in the step."""
    if raw in (None, ""):
        return None
    value = interpolate(raw, context)
    if value in (None, ""):
        return None
    url = str(value).strip()
    if not url.startswith(("http://", "https://", "/")):
        raise AutomationActionError(f"an approval's image must resolve to a picture URL, not {url[:80]!r}")
    return url[:2000]


def _choices(raw, context: dict) -> list[str] | None:
    """The labels to pick from: each a template, or one template to a list. None when the step offers none; an
    error when it meant to and they resolved to fewer than two (or more than MAX_CHOICES)."""
    if raw in (None, "", []):
        return None
    resolved = interpolate(raw, context)
    items = resolved if isinstance(resolved, list) else [resolved]
    labels = [str(x).strip()[:MAX_LABEL] for x in items if x not in (None, "") and str(x).strip()]
    if len(labels) < 2:
        raise AutomationActionError(f"an approval's choices resolved to {len(labels)}: it needs at least two to pick from")
    if len(labels) > MAX_CHOICES:
        raise AutomationActionError(f"an approval offers at most {MAX_CHOICES} choices, not {len(labels)}")
    return labels
