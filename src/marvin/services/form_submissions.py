"""A form submission as a workflow and an AI operation read it.

A submission is one of two things: an entry of a submittable entry type (the public form route makes one for
every submission — "a submittable entry type IS a form") or a row of the legacy Forms table. `load` finds either
by id, inside one workspace, and returns the same small shape — what `${form_submission.*}` reads in a workflow
and what an operation such as classify-form-submission is shown.
"""

import uuid

from sqlalchemy.orm import Session


def is_submittable(entry_type) -> bool:
    """Whether an entry type takes public submissions (is a "form")."""
    caps = getattr(entry_type, "capabilities_json", None)
    return isinstance(caps, dict) and caps.get("submittable") is True


def _iso(moment) -> str | None:
    return moment.isoformat() if moment is not None else None


def from_entry(entry) -> dict | None:
    """The submission an entry is — None unless its type takes public submissions."""
    if not is_submittable(entry.entry_type):
        return None
    meta = entry.metadata_json if isinstance(entry.metadata_json, dict) else {}
    submission = meta.get("submission") if isinstance(meta.get("submission"), dict) else {}
    reasons = [str(r) for r in submission.get("review_reasons") or []]
    return {
        "id": str(entry.id),
        "form": entry.entry_type.name,
        "form_slug": entry.entry_type.slug,
        "data": entry.data_json if isinstance(entry.data_json, dict) else {},
        "status": entry.status,
        "submitted_at": str(submission.get("received_at") or _iso(entry.created_at) or ""),
        "flagged": bool(reasons),
        "review_reasons": reasons,
    }


def load(session: Session, group_id, submission_id) -> dict | None:
    """The submission `submission_id` in workspace `group_id`, or None when there is none (or it isn't one's).

    `{id, form, form_slug, data, status, submitted_at, flagged, review_reasons}` — `form` is the form's name, `data`
    the submitted values, `flagged` true when the submission protection held it for review (`review_reasons` says why).
    """
    try:
        sid = submission_id if isinstance(submission_id, uuid.UUID) else uuid.UUID(str(submission_id))
    except ValueError:
        return None
    from marvin.db.models.platform.entries import Entries

    entry = session.get(Entries, sid)
    if entry is not None and entry.group_id == group_id and (found := from_entry(entry)):
        return found
    from marvin.db.models.platform.form_submissions import FormSubmissions
    from marvin.db.models.platform.forms import Forms

    row = session.get(FormSubmissions, sid)
    if row is None or row.group_id != group_id:
        return None
    form = session.get(Forms, row.form_id)
    return {
        "id": str(row.id),
        "form": form.name if form else "",
        "form_slug": form.slug if form else "",
        "data": row.data_json or {},
        "status": row.status or "",
        "submitted_at": str(_iso(row.submitted_at) or ""),
        "flagged": False,
        "review_reasons": [],
    }
