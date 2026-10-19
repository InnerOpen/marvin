# Marvin Scripts

Utility scripts for deployment, dev environments and docs.

| Script | What it does |
| --- | --- |
| `deploy/` | Release promotion, rollback and smoke checks, called by the promote workflows |
| `helm-check.sh` | Lint the chart, render every values file and check its database engine (`helm.yml`, `task helm:lint`) |
| `dev-refresh.sh` | Refresh marvin-dev from production's newest backup (`task dev:refresh`) |
| `render_workflow_library.py` | Render `docs/workflow-library/catalogue.md` from the recipe catalogue |
| `server.py` | A very small HTTP server that logs the requests it receives |

> The Instagram integration used to be seeded by `seed_instagram_auto_reply.py`. It now declares its
> own content (entry types, collections, scheduled tasks) through the SDK, and the workspace applies
> it from the blueprint catalog after review — see `services/blueprints/`.
