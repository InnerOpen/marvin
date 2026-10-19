# Archive

Historical, not maintained. These are the July 2026 build-era status reports, phase and sprint write-ups,
old plans and one-off setup notes, kept for reference only. Do not treat them as a description of how
Marvin works today: the manual (`docs/manual/`, published with mkdocs) is the source of truth, and
`docs/manual/reference/` holds the reference pages that are kept up to date.

| File | Added | Was in | What it is |
|---|---|---|---|
| `AI-ARCHITECTURE-PLAN.md` | 2026-07-16 | docs/ | AI platform architecture plan; phases 1-7 built, agents (phase 8) planned then. |
| `ai-intake-future.md` | 2026-07-04 | docs/ | Plan for AI-assisted content intake, marked as a future phase. |
| `api-token-security-settings.md` | 2026-07-05 | docs/ | Token and bcrypt settings; the live ones are in docs/manual/auth-and-tokens.md. |
| `ARCHITECTURE-REVIEW.md` | 2026-07-05 | docs/ | Architecture review of the first platform sprint (simulated lead-architect review). |
| `astro-integration.md` | 2026-07-04 | docs/ | Guide to building an Astro site from the publishing API, from the first trial. |
| `AUTH_USAGE.md` | 2026-07-06 | frontend/ | Frontend auth helper guide; requireAuth, requireAdmin and isAuthenticated still exist, getCurrentUser and isAdmin do not. |
| `CI_CD_IMPLEMENTATION.md` | 2026-07-13 | repo root | Summary of the first GitHub Actions pipeline; the workflows have changed since. |
| `CLI-SCHEDULED-TASKS.md` | 2026-07-09 | docs/ | CLI guide for scheduled tasks, written before the CLI moved to its own repo. |
| `configuration-settings.md` | 2026-07-05 | docs/ | Settings from the token-security and publishing upgrade; see settings.py for the live list. |
| `CONFIGURATION-UPGRADE.md` | 2026-07-05 | docs/ | Report on moving hardcoded auth/token/publishing values into settings. |
| `CURRENT_STATUS.md` | 2026-07-05 | docs/ | Implementation status snapshot of the marvin-platform-plan branch. |
| `data-model.md` | 2026-07-04 | docs/ | July data-model sketch (nine tables, old entry_type enum); the schema has since grown a lot. |
| `DEPLOYMENT_IMPLEMENTATION_COMPLETE.md` | 2026-07-04 | docs/ | Completion report for the first Helm/OpenShift deployment work. |
| `ENTRY_TYPE.md` | 2026-07-09 | docs/ | Plan for schema-driven entry types (field types, validation). Current field types: docs/manual/reference/entry-type-fields.md. |
| `ENTRY_TYPE_FIELD_SCHEMAS.json` | 2026-07-09 | docs/ | Field-type catalogue for entry type schemas; lacks embed, asset and resource fields. |
| `EXAMPLE_ALL_FIELDS_SCHEMA.json` | 2026-07-09 | docs/ | Example entry type schema using every field type of that day. |
| `FRONTEND-API-AUDIT.md` | 2026-07-10 | docs/ | Audit of direct fetch() calls in frontend pages, to plan the SDK migration. |
| `FRONTEND_SDK_MIGRATION.md` | 2026-07-07 | docs/ | Plan to move the frontend onto the official SDK package. |
| `FRONTEND_SDK_MIGRATION_STATUS.md` | 2026-07-07 | docs/ | Progress checklist for that SDK migration. |
| `frontmatter-and-entry-metadata.md` | 2026-07-04 | docs/ | Decision note: store structured metadata, export frontmatter on request. |
| `FUTURE-IMPROVEMENTS.md` | 2026-07-08 | docs/ | Notes on possible performance and caching improvements. |
| `IDEAS.md` | 2026-07-04 | docs/ | Design notebook of early ideas and direction. |
| `IMPLEMENTATION_SUMMARY.md` | 2026-07-04 | docs/ | Summary of the event-bus security and scheduler reliability work. |
| `intake-pipeline-plan.md` | 2026-07-06 | docs/ | Plan for an intake pipeline so users need not live in the admin UI. |
| `INTEGRATIONS_DESIGN.md` | 2026-07-21 | docs/ | Integrations data model and provider registry sketch; describes polling that was never built. |
| `INTEGRATIONS_PLUGIN_ARCHITECTURE.md` | 2026-07-21 | docs/ | Plan for integrations as installable packages; the SDK package is the real contract. |
| `marvin-platform-plan.md` | 2026-07-04 | docs/ | The original platform plan (private content engine, separate public sites). |
| `MARVIN_ROADMAP.md` | 2026-07-06 | docs/ | Early roadmap for the multi-workspace content and automation platform. |
| `MIGRATION_CHECKLIST.md` | 2026-07-06 | frontend/ | Checklist for moving pages to the requireAuth helpers. |
| `phase-3-publishing.md` | 2026-07-05 | docs/ | Phase 3 plan for the publishing API. |
| `PHASE-6-COMPLETE.md` | 2026-07-05 | docs/ | Completion report for phase 6, resources and assets. |
| `PHASE-7-TECH-DEBT-FIXES.md` | 2026-07-05 | docs/ | Completion report for phase 7, tech-debt fixes. |
| `PHASE_5_FRONTEND_STATUS.md` | 2026-07-09 | docs/ | Status of phase 5, the schema-driven frontend editor. |
| `platform-implementation-checklist.md` | 2026-07-04 | docs/ | Checklist for the first platform sprint. |
| `PUBLISHING-API-COMPLETE.md` | 2026-07-05 | docs/ | Completion report for the first publishing API (Mash & Burn Co. trial). |
| `PUBLISHING-API-IMPLEMENTATION.md` | 2026-07-05 | docs/ | Implementation plan for that first publishing API. |
| `RENDERER-ARCHITECTURE.md` | 2026-07-13 | docs/ | Renderer architecture review and plan (phases 1-6, implemented). |
| `resources-implementation-summary.md` | 2026-07-06 | docs/ | Summary of the resources feature (SDK, backend API, docs). |
| `SCHEDULED-TASKS-IMPLEMENTATION-COMPLETE.md` | 2026-07-09 | docs/ | Completion summary for scheduled tasks across backend, SDK and CLI. |
| `SDK-ARCHITECTURE-PLAN.md` | 2026-07-06 | docs/ | Plan for the TypeScript SDK architecture. |
| `SDK-SCHEDULED-TASKS.md` | 2026-07-09 | docs/ | SDK guide for scheduled tasks, written before the SDK moved to its own repo. |
| `SEED_IMPROVEMENTS.md` | 2026-07-05 | repo root | Analysis and proposals for the seed system. |
| `SEMANTIC_VERSIONING_SETUP.md` | 2026-07-13 | repo root | Setup summary for python-semantic-release; RELEASE_PROCESS.md is current. |
| `site-clients-and-publishing.md` | 2026-07-04 | docs/ | Site-client design note; now in docs/manual/whats-new/publishing-api.md. |
| `smart-collections-explained.md` | 2026-07-05 | docs/ | Design explainer for smart collections; the feature is in docs/manual/whats-new/collections.md. |
| `SPRINT-COMPLETE.md` | 2026-07-05 | docs/ | Status of the first platform sprint. |
| `TESTING_SUMMARY.md` | 2026-07-05 | repo root | Test and bug-fix log of the marvin-platform-plan branch. |
| `WORKFLOW_STATE_REVIEW.md` | 2026-07-21 | docs/ | Review of what the automation (Flavor B) design had already built. |
| `WORKFLOW_SUGGESTIONS.md` | 2026-07-21 | docs/ | Automation architecture review and design exercise that led to workflows. |
