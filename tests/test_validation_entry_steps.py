"""The editor's "runs on an entry, but this trigger has none" warning is for steps that act on an existing entry. Creating
an entry, or a custom AI step that reads only its prompt, needs none — an incoming webhook's run can summarise its payload
into a new entry without a warning."""

from marvin.services.automation.validation import validate_definition

WEBHOOK = {"type": "incoming_webhook", "webhook": "inbox"}


def _no_entry_warnings(actions) -> list[str]:
    issues = validate_definition({"trigger": WEBHOOK, "actions": actions})
    return [i["message"] for i in issues if "has none" in i["message"]]


def test_creating_an_entry_or_a_prompt_only_ai_step_needs_no_entry():
    actions = [
        {"kind": "operation", "op": "custom", "id": "idea", "see": [], "prompt": "Sum up ${event.payload.text}", "output_schema": {"type": "object"}},
        {"kind": "entry", "op": "create", "entry_type": "reference", "title": "${steps.idea.output.title}"},
    ]

    assert _no_entry_warnings(actions) == []


def test_steps_that_act_on_the_runs_entry_still_warn():
    actions = [
        {"kind": "entry", "op": "publish"},
        {"kind": "operation", "op": "custom", "prompt": "Sum it up", "output_schema": {"type": "object"}},  # see unset: the item
        {"kind": "operation", "op": "custom", "see": ["item"], "prompt": "Sum it up", "output_schema": {"type": "object"}},
    ]

    assert len(_no_entry_warnings(actions)) == 3
