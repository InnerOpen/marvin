"""Answering several waiting approvals at once (`approvals.decide_many`, `POST /api/automations/approvals/decide-many`): each
keeps its own choice and boxes, one that can't be taken says why while the rest still go, and the runs go on one after
another (twenty paid calls in turn, not at once)."""

import uuid

import pytest

from marvin.services.automation import approvals
from marvin.services.automation.authz import ROLE_EDITOR
from tests.test_workflow_approval_fields import ASK, SEND, _flow
from tests.test_workflow_approvals import _install, _published, signoff  # noqa: F401 — the fixture
from tests.test_workflow_library import _entry_doc, _fire, ws  # noqa: F401 — the fixture


@pytest.fixture
def inline(ws, monkeypatch):  # noqa: F811
    """The runs go on here, on the test's session, in the order the one thread would take them."""
    from marvin.db.models.groups.workflow_approvals import WorkflowApprovalModel
    from marvin.services.automation.engine import resume_after_approval

    order: list[str] = []

    class _Thread:
        def __init__(self, target, args=(), **_):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    def resume(approval_id, user_id):
        order.append(str(approval_id))
        resume_after_approval(ws.session, ws.session.get(WorkflowApprovalModel, approval_id))

    monkeypatch.setattr(approvals.threading, "Thread", _Thread)
    monkeypatch.setattr(approvals, "_resume_job", resume)
    return order


def _three(ws):  # noqa: F811
    _install(ws, _flow(ASK, SEND))
    for title in ("Onions", "Leeks", "Garlic"):
        article = _published(ws, title)
        _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id=f"c-{title}")
    return approvals.pending(ws.session, ws.gid, ROLE_EDITOR)


def test_approve_all_keeps_each_ones_own_box_and_the_runs_go_on_in_turn(ws, signoff, inline):  # noqa: F811
    a, b, c = _three(ws)

    done = approvals.decide_many(
        ws.session,
        ws.gid,
        [{"id": a.id}, {"id": b.id, "fields": {"prompt": "Leeks, sliced thin."}}, {"id": c.id}],
        "approve",
        user_id=ws.uid,
        role=ROLE_EDITOR,
    )

    assert [r["status"] for r in done] == ["approved"] * 3 and inline == [str(a.id), str(b.id), str(c.id)]
    assert [call[1]["to"] for call in signoff.calls] == [
        "  A knife chopping “Onions”, close up.\n",
        "Leeks, sliced thin.",
        "  A knife chopping “Garlic”, close up.\n",
    ]


def test_one_that_cant_be_taken_says_why_and_the_rest_still_go(ws, signoff, inline):  # noqa: F811
    a, b, c = _three(ws)
    approvals.decide(ws.session, ws.gid, a.id, "deny", user_id=ws.uid, role=ROLE_EDITOR)

    done = approvals.decide_many(
        ws.session, ws.gid, [{"id": a.id}, {"id": b.id, "fields": {"prompt": "{{ KEY }}"}}, {"id": c.id}], "approve", user_id=ws.uid, role=ROLE_EDITOR
    )

    assert (done[0]["code"], done[1]["code"], done[2]["status"]) == (409, 422, "approved")
    assert "already decided" in done[0]["error"] and [call[1]["to"] for call in signoff.calls] == ["  A knife chopping “Garlic”, close up.\n"]
    ws.session.refresh(b)
    assert b.status == "pending"  # refused, still waiting for its own answer


def test_deny_all(ws, signoff, inline):  # noqa: F811
    rows = _three(ws)

    done = approvals.decide_many(ws.session, ws.gid, [{"id": r.id} for r in rows], "deny", user_id=ws.uid, role=ROLE_EDITOR, note="Not today")

    assert [r["status"] for r in done] == ["denied"] * 3 and signoff.calls == []


def test_none_or_too_many_is_refused(ws):  # noqa: F811
    for items in ([], [{"id": uuid.uuid4()} for _ in range(approvals.MAX_DECIDE_MANY + 1)]):
        with pytest.raises(approvals.ApprovalError) as refused:
            approvals.decide_many(ws.session, ws.gid, items, "approve", user_id=ws.uid, role=ROLE_EDITOR)
        assert refused.value.status == 422
