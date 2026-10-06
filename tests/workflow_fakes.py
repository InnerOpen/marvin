"""A stand-in for `WorkspaceAutomationModel` in tests that run the engine without a database.

The engine reads a workflow's trigger from its columns (`trigger_type`, `trigger_event`, …) and the
assembled `trigger` / `definition`, so a fake has to carry all of them — split exactly the way the
model splits them.
"""

from types import SimpleNamespace

from marvin.db.models.groups.automations import assemble_trigger, split_trigger


def fake_workflow(*, definition: dict | None = None, **fields) -> SimpleNamespace:
    columns = split_trigger((definition or {}).get("trigger"))
    return SimpleNamespace(
        **fields,
        **columns,
        definition=definition,
        trigger=assemble_trigger(columns["trigger_type"], columns["trigger_event"], columns["trigger_ref"], columns["trigger_config"]),
    )
