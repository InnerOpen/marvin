# STATUS — feat/workflow-library-audit

## Done (all passing: `uv run pytest tests/test_workflow_library.py tests/test_workflow_authoring.py`)
- One recipe store: `src/marvin/services/automation/recipes/` — `catalogue.json` (104 entries: the brief's 100
  ideas + the 4 former authoring-guide examples), 21 `<id>.json` + `<id>.vars.json`, loader `__init__.py`.
- Typed `{{placeholder}}` substitution: `src/marvin/services/automation/library.py`.
- Authoring guide examples come from the store, filtered by status + workspace prerequisites
  (`authoring.py::_examples`); `workflow_authoring_guide` takes `recipe=`; `draft_workflow` takes `recipe` + `vars`.
- Docs: `docs/workflow-library/{README,compatibility-audit,roadmap,catalogue}.md`; renderer
  `scripts/render_workflow_library.py` (test fails if `catalogue.md` is stale).
- Engine fix: `actions/entry.py` JSON-encodes templated `set_metadata`/`set_data` patches (UUID/datetime).
- Counts: 21 verified-current, 11 supported-after-configuration, 56 needs-engine-capability, 16 needs-adapter, 0 concept.

## Left
- Full suite: `tests/test_platform_workspace.py` fails in this worktree with sqlite "no such table:
  group_slug_aliases / event_log" (looks environmental/pre-existing — untested against clean origin/develop).
  Everything else up to that point passed (`-x` stopped there). Re-run `uv run pytest tests/` to confirm.
- mkdocs: the docs live outside `docs/manual` (mkdocs `docs_dir`), so they are not in the nav; `mkdocs build
  --strict` was not run.
- Rebase onto latest origin/develop (6+ commits ahead when checked) — see git status.
- Phase 2 (Library UI / install flow) not started.

## Resume
`cd /home/jared/.claude/jobs/4c563d7f/tmp/wflib-wt && uv sync && uv run pytest tests/test_workflow_library.py`
The authoring helper that generated catalogue.json is `/home/jared/.claude/jobs/4c563d7f/tmp/build_catalogue.py`
(not committed; the JSON is the source of truth now).
