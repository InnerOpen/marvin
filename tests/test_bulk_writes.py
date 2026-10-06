"""Big bulk writes ask first (services/ai/tools/bulk_writes.py + the agent loop's per-call check).

No DB: sizing is faked with BulkWrite values, the loop is driven by a scripted provider. The
DB-backed path through the real attach_tag tool is in tests/test_bulk_tag_tool.py.
"""

import json
import uuid
from types import SimpleNamespace

from marvin.services.ai.agent import AgentTool, PendingCall, deserialize_pending, run_agent_loop, serialize_pending
from marvin.services.ai.base import AIProvider, CompletionResult, ToolCall
from marvin.services.ai.tools import bulk_writes, get_tool
from marvin.services.ai.tools.bulk_writes import BULK_WRITE_ASK_ITEMS, BULK_WRITE_ASK_THRESHOLD, BulkWrite


def _write(targets: int, items: int, action="attach") -> BulkWrite:
    return BulkWrite(
        action=action,
        item_kind="tag",
        items=[f"t{i}" for i in range(items)],
        target_type="asset",
        target_ids=[f"a{i}" for i in range(targets)],
        label_targets=lambda ids: [f"Asset {i}" for i in ids],
    )


# ── Thresholds ───────────────────────────────────────────────────────────────


def test_needs_approval_small_write_runs_directly():
    assert not bulk_writes.needs_approval(_write(targets=2, items=3))


def test_needs_approval_whole_vocabulary_on_every_asset_asks():
    # The incident: ~25 tags on each of 19 untagged assets.
    assert bulk_writes.needs_approval(_write(targets=19, items=25))


def test_needs_approval_many_links_with_one_tag_asks():
    assert bulk_writes.needs_approval(_write(targets=BULK_WRITE_ASK_THRESHOLD + 1, items=1))


def test_needs_approval_at_the_threshold_runs_directly():
    assert not bulk_writes.needs_approval(_write(targets=4, items=BULK_WRITE_ASK_ITEMS))  # exactly 20 links


def test_needs_approval_many_tags_on_several_targets_asks():
    assert bulk_writes.needs_approval(_write(targets=2, items=BULK_WRITE_ASK_ITEMS + 1))


def test_needs_approval_many_tags_on_one_target_runs_directly():
    assert not bulk_writes.needs_approval(_write(targets=1, items=BULK_WRITE_ASK_ITEMS + 1))


def test_needs_approval_unsized_call_runs_directly():
    assert not bulk_writes.needs_approval(None)


# ── Preview + refusal ────────────────────────────────────────────────────────


def test_approval_preview_lists_targets_and_items():
    preview = bulk_writes.approval_preview(_write(targets=19, items=25))
    assert preview["summary"] == "Attach 25 tags to 19 assets (475 links)"
    assert preview["targets"][:2] == ["Asset a0", "Asset a1"] and preview["targetCount"] == 19
    assert len(preview["items"]) == 25


def test_approval_preview_caps_the_target_list():
    preview = bulk_writes.approval_preview(_write(targets=bulk_writes.PREVIEW_MAX_TARGETS + 7, items=1))
    assert len(preview["targets"]) == bulk_writes.PREVIEW_MAX_TARGETS
    assert preview["targetCount"] == bulk_writes.PREVIEW_MAX_TARGETS + 7


def test_refusal_tells_the_model_to_work_in_smaller_steps():
    out = json.loads(bulk_writes.refusal(_write(targets=19, items=25, action="detach")))
    assert "smaller steps" in out["error"] and "Detach 25 tags from 19 assets" in out["error"]
    assert out["links"] == 475 and out["limit"] == BULK_WRITE_ASK_THRESHOLD


# ── bind: the shared gate every bulk tool goes through ───────────────────────


def _spec(write: BulkWrite | None, calls: list):
    def handler(ctx, args):
        calls.append(args)
        return json.dumps({"ok": True})

    return SimpleNamespace(handler=handler, bulk_write=(lambda ctx, args: write))


def test_bind_on_a_parkable_run_flags_big_calls_and_leaves_the_handler_alone():
    calls: list = []
    run, check = bulk_writes.bind(_spec(_write(19, 25), calls), ctx=None, can_park=True)
    assert check({"x": 1})["links"] == 475
    assert calls == []  # the check never writes; the loop runs `run` only once approved
    run({"x": 1})
    assert calls == [{"x": 1}]


def test_bind_on_a_parkable_run_passes_small_calls():
    run, check = bulk_writes.bind(_spec(_write(2, 3), []), ctx=None, can_park=True)
    assert check({}) is None


def test_bind_without_a_thread_refuses_big_calls_without_writing():
    calls: list = []
    run, check = bulk_writes.bind(_spec(_write(19, 25), calls), ctx=None, can_park=False)
    assert check is None
    assert "error" in json.loads(run({}))
    assert calls == []


def test_bind_without_a_thread_runs_small_calls():
    calls: list = []
    run, _ = bulk_writes.bind(_spec(_write(2, 3), calls), ctx=None, can_park=False)
    assert json.loads(run({})) == {"ok": True} and len(calls) == 1


def test_bind_sizing_failure_lets_the_handler_report():
    calls: list = []

    def boom(ctx, args):
        raise ValueError("bad filter")

    spec = SimpleNamespace(handler=lambda ctx, args: calls.append(args) or "{}", bulk_write=boom)
    run, _ = bulk_writes.bind(spec, ctx=None, can_park=False)
    run({})
    assert len(calls) == 1


def test_bind_tool_without_bulk_write_has_no_check():
    spec = SimpleNamespace(handler=lambda ctx, args: "{}", bulk_write=None)
    _, check = bulk_writes.bind(spec, ctx=None, can_park=True)
    assert check is None


# ── ask_first: a per-call ask about what a call touches, not how much ───────


def _ask_spec(flag: bool, calls: list):
    ask = bulk_writes.AskFirst(preview={"summary": "Archive 1 entry"}, refusal=json.dumps({"error": "cannot pause"}))

    def handler(ctx, args):
        calls.append(args)
        return json.dumps({"ok": True})

    return SimpleNamespace(handler=handler, bulk_write=None, ask_first=lambda ctx, args: ask if flag else None)


def test_bind_ask_first_on_a_parkable_run_pends_with_its_preview():
    calls: list = []
    run, check = bulk_writes.bind(_ask_spec(True, calls), ctx=None, can_park=True)
    assert check({}) == {"summary": "Archive 1 entry"} and calls == []
    _, check = bulk_writes.bind(_ask_spec(False, calls), ctx=None, can_park=True)
    assert check({}) is None


def test_bind_ask_first_without_a_thread_answers_with_its_refusal():
    calls: list = []
    run, check = bulk_writes.bind(_ask_spec(True, calls), ctx=None, can_park=False)
    assert check is None and json.loads(run({})) == {"error": "cannot pause"} and calls == []


def test_ask_first_check_that_raises_lets_the_handler_report():
    calls: list = []

    def boom(ctx, args):
        raise ValueError("bad")

    spec = SimpleNamespace(handler=lambda ctx, args: calls.append(args) or "{}", bulk_write=None, ask_first=boom)
    run, check = bulk_writes.bind(spec, ctx=None, can_park=True)
    assert check({}) is None
    bulk_writes.unattended(spec, None)({})
    assert len(calls) == 1


def test_unattended_refuses_ask_first_calls_but_leaves_bulk_sizing_alone():
    calls: list = []
    assert json.loads(bulk_writes.unattended(_ask_spec(True, calls), None)({})) == {"error": "cannot pause"} and calls == []
    # MarvinMCP's invoke never applied the bulk gate; unattended doesn't add it
    bulk = _spec(_write(19, 25), calls)
    assert json.loads(bulk_writes.unattended(bulk, None)({})) == {"ok": True} and len(calls) == 1


# ── Every bulk-write action tool opts in ─────────────────────────────────────


def test_bulk_capable_action_tools_declare_bulk_write():
    for name in ("attach_tag", "detach_tag", "import_asset"):
        assert get_tool(name).bulk_write is not None, name


def test_import_asset_sizing_counts_one_link_per_attached_image():
    size = get_tool("import_asset").bulk_write
    entry = str(uuid.uuid4())  # a UUID resolves without a lookup
    ctx = SimpleNamespace(session=None, group_id=None)
    many = size(ctx, {"attach_to": entry, "images": [{"url": f"https://x.test/{i}.jpg"} for i in range(BULK_WRITE_ASK_THRESHOLD + 1)]})
    few = size(ctx, {"attach_to": entry, "images": [{"url": "https://x.test/1.jpg"}, {"url": "https://x.test/2.jpg"}]})
    assert bulk_writes.needs_approval(many) and not bulk_writes.needs_approval(few)


def test_import_asset_without_attach_is_not_a_bulk_write():
    assert get_tool("import_asset").bulk_write(None, {"images": [{"url": "https://x.test/1.jpg"}] * 30}) is None


# ── The loop pends a flagged call, with its preview ──────────────────────────


class _Provider(AIProvider):
    provider_type = "fake"
    display_name = "Fake"
    supports_tool_calls = True

    def __init__(self, results):
        self._results = list(results)

    def complete_with_tools(self, messages, model, tools, options=None, tool_choice="auto"):
        return self._results.pop(0)

    def complete(self, messages, model, options=None):  # pragma: no cover
        raise NotImplementedError

    def complete_structured(self, messages, model, output_schema, options=None):  # pragma: no cover
        raise NotImplementedError

    def list_models(self):  # pragma: no cover
        return []

    def test_connection(self):  # pragma: no cover
        return True, ""


def _result(content="", tool_calls=None):
    return CompletionResult(content=content, prompt_tokens=1, completion_tokens=1, total_tokens=2, model="m", tool_calls=tool_calls or [])


def _tool(ran: list, preview):
    return AgentTool(
        name="attach_tag",
        description="",
        input_schema={},
        run=lambda a: ran.append(a) or "{}",
        category="links",
        approval_check=lambda a: preview,
    )


def test_loop_pends_a_call_its_check_flags():
    ran: list = []
    provider = _Provider([_result(tool_calls=[ToolCall(id="c1", name="attach_tag", arguments={"tags": ["a"]})])])
    res = run_agent_loop(provider, "m", [], [_tool(ran, {"summary": "Attach 25 tags to 19 assets (475 links)"})])
    assert res.stopped_reason == "awaiting_approval"
    assert res.pending_calls[0].preview["summary"].startswith("Attach 25 tags")
    assert ran == []


def test_loop_runs_a_call_its_check_passes():
    ran: list = []
    provider = _Provider([_result(tool_calls=[ToolCall(id="c1", name="attach_tag", arguments={"tag": "a"})]), _result(content="done")])
    res = run_agent_loop(provider, "m", [], [_tool(ran, None)])
    assert res.stopped_reason == "complete" and ran == [{"tag": "a"}]


def test_pending_preview_survives_parking():
    calls = [PendingCall(id="c1", tool="attach_tag", arguments={}, preview={"summary": "s"}), PendingCall(id="c2", tool="x", arguments={})]
    data = serialize_pending(calls)
    assert "preview" not in data[1]
    assert [c.preview for c in deserialize_pending(data)] == [{"summary": "s"}, None]
