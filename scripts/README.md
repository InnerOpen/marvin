# Marvin Scripts

Utility scripts for deployment, dev environments and docs.

| Script | What it does |
| --- | --- |
| `deploy/` | Release promotion, rollback and smoke checks, called by the promote workflows |
| `helm-check.sh` | Lint the chart, render every values file and check its database engine (`helm.yml`, `task helm:lint`) |
| `dev-refresh.sh` | Refresh marvin-dev from production's newest backup (`task dev:refresh`) |
| `pytest-workers.sh` | How many pytest-xdist workers to run: the container's CPU quota, else `auto` (`test.yml`) |
| `render_workflow_library.py` | Render `docs/workflow-library/catalogue.md` from the recipe catalogue |
| `seed_timeline_demos.py` | Make the sample event, content plan, team calendar and shift roster of the Timeline Demos package (`docs/examples/`) through the API, skipping what is there |
| `server.py` | A very small HTTP server that logs the requests it receives |

> The Instagram integration used to be seeded by `seed_instagram_auto_reply.py`. It now declares its
> own content (the token-refresh task) through the SDK, and the workspace applies it from the
> blueprint catalog after review — see `services/blueprints/`. Its keyword auto-reply was replaced by Social.
