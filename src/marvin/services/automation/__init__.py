"""Flavor B — user-configurable orchestration (event → conditions → actions).

An automation is a DB row (`WorkspaceAutomationModel`) an admin authored, run by a generic event
listener (`AutomationReactionListener`) rather than a hardcoded reaction class. This package holds
the pure engine pieces:

- `matcher`  — condition evaluation + `$event.*`/`$previous.*` interpolation (no I/O).
- `runner`   — execute one action (a `generate-summary`-style operation) against a workspace.
- `engine`   — glue: for a matched event, run an automation's action pipeline in order.
"""
