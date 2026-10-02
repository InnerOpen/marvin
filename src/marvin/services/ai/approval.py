"""The workspace approval mode — may AI-generated content land on a record without a human?

One rule for every path that writes AI output (an operation's write-back, revise, a workflow's
operation step with write-back, compose's alt text), so none can bypass the review wall:

- ``suggest-only`` — always stage a suggestion; a person accepts it.
- ``allow-draft-update`` — apply to entries still being drafted (``inbox``/``draft``); stage anything
  further along (``needs_review``/``approved`` are mid-review, ``published``/``archived`` are live).
  Assets and resources have no publish lifecycle, so they count as drafts.
- ``allow-automatic-update`` — always apply.

Unset or unknown → suggest-only (the safe direction). What Ask Marvin may *do* on its own (tag, attach,
publish…) is the agent's permission matrix (allow / ask / block per tool), not this setting.
"""

APPROVAL_MODES = ("suggest-only", "allow-draft-update", "allow-automatic-update")
DEFAULT_APPROVAL_MODE = "suggest-only"
DRAFT_STATUSES = frozenset({"inbox", "draft"})


def normalize_mode(mode: str | None) -> str:
    return mode if mode in APPROVAL_MODES else DEFAULT_APPROVAL_MODE


def may_apply(mode: str | None, entity_type: str, status: str | None) -> bool:
    """True when AI output may be written straight onto the record; False means stage a suggestion."""
    mode = normalize_mode(mode)
    if mode == "allow-automatic-update":
        return True
    if mode == "allow-draft-update":
        return entity_type != "entry" or status in DRAFT_STATUSES
    return False


def workspace_approval_mode(session, group_id) -> str:
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    settings = session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first()
    return normalize_mode(settings.approval_mode if settings else None)
