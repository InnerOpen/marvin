"""The schema_check step: hold a JSON document (usually a fetch step's body) up against a JSON Schema and report what
doesn't fit — as output, never a failed run, unless the step says `fail_on_invalid`. A malformed schema is refused
when the workflow is written; the size of what is checked and of what is reported is bounded."""

# ruff: noqa: F811 — `ws` is a fixture, not a redefinition
import json
import uuid

import pytest

from marvin.schemas.group.automation_definition import SchemaCheckAction
from marvin.services.automation.actions.base import AutomationActionError
from marvin.services.automation.actions.schema_check import (
    FOUND_ERRORS_CAP,
    MAX_DOCUMENT_BYTES,
    check,
    run_schema_check_action,
    schema_problem,
)
from marvin.services.automation.authoring import draft_issues
from tests.test_workflow_authoring import workspace, ws  # noqa: F401 — fixtures
from tests.test_workflow_fetch import _web
from tests.test_workflow_item_targets import _resource

AGENT = {
    "type": "object",
    "required": ["name", "url", "capabilities"],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "url": {"type": "string", "pattern": "^https://"},
        "capabilities": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    },
    "additionalProperties": False,
}
GOOD = {"name": "Scribe", "url": "https://scribe.example", "capabilities": ["summarise"]}


# ── The check ─────────────────────────────────────────────────────────────────
def test_a_document_that_fits_is_valid():
    assert check(GOOD, AGENT) == {"valid": True, "errors": [], "error_count": 0, "truncated": False, "text": ""}


def test_what_doesnt_fit_is_listed_with_a_path_a_person_can_follow():
    doc = {"name": "", "url": "http://scribe.example", "capabilities": [1], "extra": True}
    out = check(doc, AGENT)
    assert out["valid"] is False and out["error_count"] == 4 and not out["truncated"]
    by_path = {e["path"]: e["message"] for e in out["errors"]}
    assert set(by_path) == {"$", "$.name", "$.url", "$.capabilities[0]"}
    assert "extra" in by_path["$"] and "does not match" in by_path["$.url"] and "not of type 'string'" in by_path["$.capabilities[0]"]
    assert [e["path"] for e in out["errors"]] == sorted(by_path)  # in path order: the same document always reads the same
    assert out["text"].splitlines()[0].startswith("- $: ")


def test_a_missing_required_field_is_reported_at_its_parent():
    out = check({"name": "Scribe"}, AGENT)
    assert [e["path"] for e in out["errors"]] == ["$"] * 2 and all("is a required property" in e["message"] for e in out["errors"])


def test_text_holding_json_is_read_as_json_and_other_text_as_itself():
    assert check(json.dumps(GOOD), AGENT)["valid"] is True
    assert check("a plain sentence", {"type": "string"})["valid"] is True
    assert check("a plain sentence", {"type": "object"})["valid"] is False
    broken = check('{"name": "Scribe"', AGENT)  # looks like JSON, isn't
    assert broken["valid"] is False and broken["errors"][0]["message"].startswith("not valid JSON")


def test_no_document_is_a_violation_not_an_exception():
    out = check(None, AGENT)
    assert out["valid"] is False and "no document" in out["errors"][0]["message"]


def test_a_document_over_the_size_bound_is_reported_not_checked():
    out = check({"name": "x" * MAX_DOCUMENT_BYTES}, AGENT)
    assert out["valid"] is False and out["error_count"] == 1 and "larger than" in out["errors"][0]["message"]
    assert len(json.dumps(out)) < 1000  # and the report doesn't carry the document


def test_a_deeply_nested_document_is_reported_not_crashed_on():
    doc: object = []
    for _ in range(3000):
        doc = [doc]
    out = check(doc, {"type": "array", "items": {"$ref": "#"}})
    assert out["valid"] is False and "deeply" in out["errors"][0]["message"]


def test_the_errors_reported_are_capped_but_counted():
    rows = [{"name": 1}] * 30  # 30 rows × 1 error each
    schema = {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}}}}
    out = check(rows, schema)  # default 20
    assert (len(out["errors"]), out["error_count"], out["truncated"]) == (20, 30, True)
    assert out["text"].count("\n") == 19
    assert len(check(rows, schema, max_errors=3)["errors"]) == 3
    assert len(check(rows, schema, max_errors=500)["errors"]) == 30  # the cap on what's asked for is 50, so all 30 fit
    many = check([{"name": 1}] * (FOUND_ERRORS_CAP + 500), schema, max_errors=50)
    assert (len(many["errors"]), many["error_count"]) == (50, FOUND_ERRORS_CAP)  # the validator stops looking


def test_a_message_never_carries_a_huge_value():
    out = check("x" * 50_000, {"type": "string", "maxLength": 3})
    assert len(out["errors"][0]["message"]) <= 300


def test_the_schema_is_held_to_its_own_dialect_and_refs_reach_only_into_itself():
    schema = {"$defs": {"n": {"type": "integer", "minimum": 1}}, "properties": {"a": {"$ref": "#/$defs/n"}}}
    assert check({"a": 2}, schema)["valid"] is True and check({"a": 0}, schema)["valid"] is False
    with pytest.raises(AutomationActionError, match="can't be applied"):
        check({"a": 2}, {"properties": {"a": {"$ref": "https://schemas.example/n.json"}}})  # nothing is fetched


# ── A malformed schema ────────────────────────────────────────────────────────
@pytest.mark.parametrize("schema", [{"type": "nonsense"}, {"minimum": "high"}, {"required": "name"}, [1, 2], "x", 3])
def test_a_malformed_schema_is_a_problem(schema):
    assert schema_problem(schema)


def test_a_usable_schema_is_no_problem():
    assert schema_problem(AGENT) is None and schema_problem(True) is None and schema_problem({}) is None


def test_the_editor_and_validator_refuse_a_malformed_inline_schema(ws):
    steps = [
        {"kind": "schema_check", "document": "${steps.p.output.json}", "schema": {"type": "nonsense"}},  # bad
        {"kind": "schema_check", "document": "x"},  # neither schema nor resource
        {"kind": "schema_check", "document": "x", "schema": {"type": "object"}, "schema_resource": "r"},  # both
        {"kind": "schema_check", "schema": {"type": "object"}},  # no document
        {"kind": "schema_check", "document": "x", "schema": {"type": "object"}, "max_errors": 500},
        {"kind": "schema_check", "document": "${steps.p.output.json}", "schema": AGENT, "fail_on_invalid": True},  # fine
        {"kind": "schema_check", "document": "x", "schema": "${resource.metadata.schema}"},  # a template: checked when it runs
    ]
    issues = draft_issues(ws.session, ws.gid, {"trigger": {"type": "manual"}, "actions": steps})
    paths = [str(i.get("path", "")) for i in issues]
    for index in range(5):
        assert any(p.startswith(f"actions[{index}]") for p in paths), (index, issues)
    assert not any(p.startswith(("actions[5]", "actions[6]")) for p in paths), issues
    assert any("not a valid JSON Schema" in str(i.get("message", i)) for i in issues)


def test_the_model_reads_schema_under_its_own_name():
    step = SchemaCheckAction.model_validate({"kind": "schema_check", "document": "${x}", "schema": AGENT})
    assert step.schema_ == AGENT and step.max_errors == 20 and step.fail_on_invalid is False


# ── The step ──────────────────────────────────────────────────────────────────
def _step(ws, **fields):
    return run_schema_check_action(ws.session, ws.gid, {"kind": "schema_check", **fields}, {"steps": {}, "previous": {}})


def test_an_invalid_document_is_output_unless_the_step_says_to_fail(ws):
    assert _step(ws, document={"name": "x"}, schema=AGENT)["valid"] is False
    with pytest.raises(AutomationActionError, match=r"doesn't fit its schema: \$.*more") as caught:
        _step(ws, document={"name": "x"}, schema=AGENT, fail_on_invalid=True)
    assert caught.value.code == "invalid_document"
    assert _step(ws, document=GOOD, schema=AGENT, fail_on_invalid=True)["valid"] is True  # a good one never fails


def test_a_schema_that_arrives_by_template_is_checked_when_the_step_runs(ws):
    ctx = {
        "steps": {},
        "previous": {},
        "entry": {"metadata": {"schema": {"type": "string"}, "bad": {"type": "nonsense"}, "text": '{"type": "object"}'}},
    }

    def run(schema):
        return run_schema_check_action(ws.session, ws.gid, {"kind": "schema_check", "document": "hi", "schema": schema}, ctx)

    assert run("${entry.metadata.schema}")["valid"] is True
    assert run("${entry.metadata.text}")["valid"] is False  # JSON text works too
    with pytest.raises(AutomationActionError, match="can't be used"):
        run("${entry.metadata.bad}")
    with pytest.raises(AutomationActionError, match="can't be used"):
        run("${entry.metadata.nothing}")  # no schema at all


def test_dollar_signs_in_an_inline_schema_stay_as_written(ws):
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "string", "pattern": "$", "$comment": "${steps.x.output.y}"}
    assert _step(ws, document="anything", schema=schema)["valid"] is True


@pytest.fixture
def schema_resource(ws):
    from marvin.db.models.platform import Resources

    made = {
        "object": _resource(ws, "agent-shape", metadata_json={"schema": AGENT}),
        "text": _resource(ws, "agent-shape-text", metadata_json={"schema": json.dumps(AGENT)}),
        "none": _resource(ws, "no-schema", metadata_json={"other": 1}),
        "gone": _resource(ws, "trashed-shape", metadata_json={"schema": AGENT}, trashed=True),
    }
    ws.session.commit()
    yield made
    ws.session.query(Resources).filter(Resources.group_id == ws.gid).delete(synchronize_session=False)
    ws.session.commit()


def test_a_schema_can_live_in_a_resource_by_slug_or_id(ws, schema_resource):
    for key in ("object", "text"):
        row = schema_resource[key]
        assert _step(ws, document=GOOD, schema_resource=row.slug)["valid"] is True
        assert _step(ws, document={"name": "x"}, schema_resource=str(row.id))["valid"] is False
    for key, why in (("none", "no `schema`"), ("gone", "no resource")):
        with pytest.raises(AutomationActionError, match=why):
            _step(ws, document=GOOD, schema_resource=schema_resource[key].slug)
    with pytest.raises(AutomationActionError, match="no resource"):
        _step(ws, document=GOOD, schema_resource="missing")


def test_a_step_needs_exactly_one_place_for_its_schema_and_a_document(ws):
    with pytest.raises(AutomationActionError, match="one of them"):
        _step(ws, document=GOOD)
    with pytest.raises(AutomationActionError, match="one of them"):
        _step(ws, document=GOOD, schema=AGENT, schema_resource="x")
    with pytest.raises(AutomationActionError, match="needs `document`"):
        _step(ws, schema=AGENT)


def _run(ws, actions, *, dry_run=False):
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.services.automation.engine import run_automation_now
    from marvin.services.automation.recorder import ExecutionRecorder

    wf = WorkspaceAutomationModel(
        session=ws.session,
        group_id=ws.gid,
        name="Check",
        slug=f"check-{uuid.uuid4().hex[:8]}",
        enabled=True,
        definition={"trigger": {"type": "manual"}, "actions": actions},
    )
    ws.session.add(wf)
    ws.session.commit()
    return run_automation_now(ws.session, ws.gid, wf, user_id=ws.uid, recorder=ExecutionRecorder(ws.session, ws.gid), dry_run=dry_run)


# ── In a run: fetch → check ───────────────────────────────────────────────────
FETCH_THEN_CHECK = [
    {"kind": "fetch", "id": "page", "url": "https://agents.example/scribe.json"},
    {"kind": "schema_check", "id": "doc", "document": "${steps.page.output.json}", "schema": AGENT},
    {"kind": "collect", "id": "gate", "entity": "entry", "query": {}, "when": {"field": "steps.doc.output.valid", "op": "eq", "value": False}},
]


def test_a_fetched_document_is_checked_and_a_when_acts_on_the_verdict(ws, monkeypatch):
    _web(monkeypatch, {"https://agents.example/scribe.json": (200, "application/json", json.dumps({"name": "Scribe", "url": "http://x.example"}))})
    checked = _run(ws, FETCH_THEN_CHECK[:2])  # a run's result is its last step's output
    assert checked["ok"], checked  # an invalid document never fails the run
    assert checked["result"]["valid"] is False and {e["path"] for e in checked["result"]["errors"]} == {"$", "$.url"}
    gated = _run(ws, FETCH_THEN_CHECK)
    assert gated["ok"] and "count" in gated["result"], gated  # the step gated on `valid == false` ran


def test_a_valid_fetched_document_skips_the_gated_step(ws, monkeypatch):
    _web(monkeypatch, {"https://agents.example/scribe.json": (200, "application/json", json.dumps(GOOD))})
    assert _run(ws, FETCH_THEN_CHECK[:2])["result"]["valid"] is True
    gated = _run(ws, FETCH_THEN_CHECK)
    assert gated["ok"] and "count" not in gated["result"], gated  # skipped: the previous output stands


def test_a_page_that_didnt_answer_is_an_invalid_document_not_a_crash(ws, monkeypatch):
    _web(monkeypatch, {})
    result = _run(ws, FETCH_THEN_CHECK[:2])
    assert result["ok"] and "no document" in result["result"]["errors"][0]["message"], result


def test_fail_on_invalid_fails_the_run_at_that_step(ws, monkeypatch):
    _web(monkeypatch, {"https://agents.example/scribe.json": (200, "application/json", "{}")})
    steps = [FETCH_THEN_CHECK[0], {**FETCH_THEN_CHECK[1], "fail_on_invalid": True}]
    result = _run(ws, steps)
    assert not result["ok"], result


def test_a_dry_run_makes_no_request_and_says_nothing_is_wrong_or_right(ws, monkeypatch):
    calls = _web(monkeypatch, {})
    result = _run(ws, [*FETCH_THEN_CHECK[:2], {**FETCH_THEN_CHECK[1], "id": "strict", "fail_on_invalid": True}], dry_run=True)
    assert calls == [] and result["ok"], result  # the fetch didn't run, so there is no document: nothing to fail on
    resolved = [p["resolved"] for p in result["plan"]]
    assert resolved[1]["valid"] is None and resolved[2]["valid"] is None


def test_a_dry_run_checks_a_document_it_has(ws):
    result = _run(ws, [{"kind": "schema_check", "id": "doc", "document": {"name": "x"}, "schema": AGENT}], dry_run=True)
    assert result["ok"] and result["plan"][0]["resolved"]["valid"] is False
    failing = _run(ws, [{"kind": "schema_check", "document": {"name": "x"}, "schema": AGENT, "fail_on_invalid": True}], dry_run=True)
    assert not failing["ok"]  # the preview shows the run would stop here
