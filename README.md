# Marvin

Marvin is a headless CMS: a FastAPI backend with a per-workspace content model (entry types,
entries, collections, assets, resources), a public publishing API for sites, automation
(events, workflows, webhooks, scheduled tasks), installable integrations, and AI agents.
A TypeScript SDK (`@inneropen/marvin-sdk`), a CLI (`@inneropen/marvin-cli`), an MCP server
(`@inneropen/marvin-mcp`) and an Astro helper (`@inneropen/marvin-astro`) sit on top of it.

**Documentation:** https://inneropen.github.io/marvin/ — the manual, plus the
[SDK](https://inneropen.github.io/marvin/sdk/), [CLI](https://inneropen.github.io/marvin/cli/)
and [REST API](https://inneropen.github.io/marvin/api/) references.

## Development

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/); tasks run through [Task](https://taskfile.dev/).

    uv sync          # install, dev group included
    task --list      # everything else (dev services, frontend, tests, docs)
    task docs        # serve the manual at http://127.0.0.1:8000/marvin/

Releases are cut from `develop` by semantic-release (`1.0.0-rc.N`); see `CHANGELOG.md`.
