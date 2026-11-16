"""A workspace's daily limit on paid approvals (Settings → General → Workflows, `paid_approvals_per_day`): an approval that
guards a paid step is marked so when it parks, approving one past today's limit is refused (deny never is), and the card
says how much of the day's limit is used."""

import pytest

from marvin.services.automation import approvals
from marvin.services.automation.authz import ROLE_EDITOR
from tests.test_approval_estimate import _asked, studio  # noqa: F401 — the fixture
from tests.test_workflow_approvals import _install, _published
from tests.test_workflow_library import _entry_doc, _fire, ws  # noqa: F401 — the fixture

PAID = {
    "trigger": {"type": "event", "event": "entry_published"},
    "actions": [
        {"kind": "approval", "id": "spend", "message": "Make it?"},
        {"kind": "integration", "id": "fx", "integration": "studio", "action": "sound_effect", "args": {"text": "x"}},
    ],
}


@pytest.fixture
def limit(ws):  # noqa: F811
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    prefs = ws.session.query(GroupPreferencesModel).filter_by(group_id=ws.gid).first()
    if prefs is None:
        prefs = GroupPreferencesModel(session=ws.session, group_id=ws.gid)
        ws.session.add(prefs)

    def set_to(n):
        prefs.paid_approvals_per_day = n
        ws.session.commit()

    yield set_to
    set_to(None)


def _approve(ws, row):  # noqa: F811
    return approvals.decide(ws.session, ws.gid, row.id, "approve", user_id=ws.uid, role=ROLE_EDITOR)


def _paid(ws, title):  # noqa: F811
    """One more run of the paid workflow (installed once), waiting at its spend."""
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    if not ws.session.query(WorkspaceAutomationModel).filter_by(group_id=ws.gid, name="Feature with sign-off").count():
        _install(ws, PAID)
    article = _published(ws, title)
    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id=f"c-{title}")
    return next(r for r in approvals.pending(ws.session, ws.gid, ROLE_EDITOR) if r.entry_id == article.id)


def test_an_approval_that_guards_a_paid_step_is_marked_paid(ws, studio):  # noqa: F811
    assert _paid(ws, "Onions").paid is True


def test_one_that_guards_a_free_step_is_not(ws, studio):  # noqa: F811
    assert _asked(ws, "voices", {}, title="Free").paid is False


def test_past_todays_limit_approving_is_refused_and_deny_still_works(ws, studio, limit):  # noqa: F811
    limit(2)
    first = _paid(ws, "One")
    assert approvals.spend_limit(ws.session, ws.gid)["used_today"] == 0
    _approve(ws, first)
    _approve(ws, _paid(ws, "Two"))

    third = _paid(ws, "Three")
    with pytest.raises(approvals.ApprovalError) as refused:
        _approve(ws, third)

    assert refused.value.status == 409 and "limit of 2 paid approvals" in str(refused.value)
    assert approvals.spend_limit(ws.session, ws.gid)["used_today"] == 2
    assert approvals.decide(ws.session, ws.gid, third.id, "deny", user_id=ws.uid, role=ROLE_EDITOR).status == "denied"


def test_no_limit_set_means_none(ws, studio):  # noqa: F811
    assert approvals.spend_limit(ws.session, ws.gid) is None


def test_the_card_says_how_much_of_the_day_is_used(ws, studio, limit):  # noqa: F811
    from marvin.routes.automations.automations_controller import _approval_read

    limit(5)
    card = _approval_read(ws.session, _paid(ws, "Card"))

    assert card.paid is True and (card.spend_limit.limit, card.spend_limit.used_today) == (5, 0)


def test_a_batch_that_makes_inside_a_repeat_counts_and_one_that_only_queues_does_not(ws, studio):  # noqa: F811
    from marvin.services.integrations.estimate import guards_paid

    make = {"kind": "integration", "id": "fx", "integration": "studio", "action": "sound_effect", "args": {"text": "${item}"}}
    record = [
        {"kind": "approval", "id": "spend", "message": "Record them?"},
        {"kind": "repeat", "id": "each", "for_each": ["a", "b"], "steps": [make]},
    ]
    queue = [
        {"kind": "approval", "id": "spend", "message": "Make them?"},
        {"kind": "repeat", "id": "each", "for_each": ["a"], "steps": [{"kind": "entry", "op": "set_data", "data": {"status": "queued"}}]},
    ]
    both = [
        {"kind": "approval", "id": "spend", "message": "Both?"},
        {"kind": "parallel", "id": "p", "branches": [{"name": "one", "steps": [make]}, {"name": "two", "steps": [make]}]},
    ]

    assert guards_paid(ws.session, ws.gid, record, 0, {}) is True
    assert guards_paid(ws.session, ws.gid, queue, 0, {}) is False
    assert guards_paid(ws.session, ws.gid, both, 0, {}) is True
