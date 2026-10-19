"""A metric step in add mode, run by an event: each event is counted once — delivered again it adds nothing, a new event
adds again, a repeat's items each count — and a dry run for an event writes and claims nothing."""

import uuid

import pytest

from marvin.db.models.groups.metric_contributions import MetricContributionModel
from marvin.db.models.groups.metric_observations import MetricObservationModel
from marvin.services.automation.authoring import draft_issues
from tests.test_workflow_library import _entry, _entry_doc, _fire, _runs, ws  # noqa: F401 — the fixture


@pytest.fixture(autouse=True)
def observations_cleared(ws):  # noqa: F811
    yield
    ws.session.rollback()
    ws.session.query(MetricContributionModel).delete(synchronize_session=False)
    ws.session.query(MetricObservationModel).delete(synchronize_session=False)
    ws.session.commit()


def _rows(ws, **filters):  # noqa: F811
    ws.session.expire_all()
    return ws.session.query(MetricObservationModel).filter_by(group_id=ws.gid, **filters).all()


def _claims(ws):  # noqa: F811
    ws.session.expire_all()
    return ws.session.query(MetricContributionModel).filter_by(group_id=ws.gid).all()


def _install_counter(ws, actions):  # noqa: F811
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    definition = {"trigger": {"type": "event", "event": "entry_published"}, "actions": actions}
    assert draft_issues(ws.session, ws.gid, definition) == []
    wf = WorkspaceAutomationModel(
        session=ws.session, group_id=ws.gid, name="Counter", slug=f"counter-{uuid.uuid4().hex[:6]}", enabled=True, definition=definition
    )
    ws.session.add(wf)
    ws.session.commit()
    article = _entry(ws, "article", "Engraving brass", status="published", data={"body": "x"})
    return wf, article, _entry_doc(article)


def test_a_workflow_counts_each_published_event_once_even_when_it_is_delivered_again(ws):  # noqa: F811
    from marvin.services.automation.engine import dry_run_for_event

    wf, article, doc = _install_counter(ws, [{"kind": "metric", "id": "count", "op": "add", "metric": "published", "window": "2026-W42"}])

    def fire(correlation):
        _fire(ws, "entry_published", doc, entity=article.id, entity_type="entry", correlation_id=correlation)

    def total():
        return [r.value for r in _rows(ws, metric="published")]

    fire("pub-1")
    fire("pub-1")  # re-delivered
    assert total() == [1.0]
    assert _runs(ws, wf.slug)[-1].actions[0].output_snapshot["counted"] is False
    fire("pub-2")  # a second publish
    fire("pub-3")
    fire("pub-2")
    assert total() == [3.0]
    preview = dry_run_for_event(
        ws.session, ws.gid, wf, doc | {"event_type": "entry_published", "entry_id": str(article.id), "correlation_id": "pub-9"}
    )
    assert next(p for p in preview["plan"] if p["kind"] == "metric")["resolved"]["would"] == "add"
    assert total() == [3.0] and len(_claims(ws)) == 3


def test_an_add_inside_a_repeat_counts_each_item_once_per_event(ws):  # noqa: F811
    step = {"kind": "metric", "op": "add", "metric": "tagged", "window": "2026-W42", "subject": "${item}"}
    _, article, doc = _install_counter(ws, [{"kind": "repeat", "for_each": "red, red, blue", "as": "item", "steps": [step]}])
    for _ in range(2):
        _fire(ws, "entry_published", doc, entity=article.id, entity_type="entry", correlation_id="pub-1")
    got = {r.subject: r.value for r in _rows(ws, metric="tagged")}
    assert got == {"red": 2.0, "blue": 1.0}  # three items in the event, none of them counted again on the re-delivery
