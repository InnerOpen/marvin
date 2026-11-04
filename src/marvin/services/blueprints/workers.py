"""The blueprints Workers needs: the three kinds of record a worker reads and writes.

Workers are a core feature (Settings -> Workers, the `marvin-worker` project), so core names the content they depend on, the one exception to
"core invents no entry types" (see `catalog.py`). Nothing is created until someone applies them: the Workers page offers it when they are
missing. Like any blueprint they create what is missing and never overwrite what exists.
"""

from marvin.schemas.platform.blueprints import Blueprint

CATEGORY_WORKERS = "Workers"

#: The slugs, in the order they are offered. The worker code and the Workers page look these up by slug.
WORKER_ENTRY_TYPES = ("job", "job-kind", "worker")

_PAYLOADS = {
    "job": {
        "name": "Job",
        "icon": "⚙️",
        "description": "A heavy task handed to a worker: what to run (kind, args) and how it went. The dispatcher picks up queued jobs, starts a "
        "worker for each, and the worker writes the outcome back here.",
        "sort_order": 0,
        "is_rendered": False,
        "schema_json": {
            "fields": [
                {
                    "key": "kind",
                    "label": "Kind",
                    "type": "text",
                    "required": True,
                    "helpText": "What to run: a kind of job the worker image has (see Job kinds), e.g. audio-cut.",
                },
                {"key": "args", "label": "Arguments", "type": "json", "helpText": 'The job\'s own input, e.g. {"story": "the-last-onion"}.'},
                {
                    "key": "status",
                    "label": "Status",
                    "type": "select",
                    "options": ["queued", "claimed", "running", "done", "failed"],
                    "defaultValue": "queued",
                    "helpText": "queued: waiting for the dispatcher. claimed: picked up and being started. running: the worker is "
                    "on it. done or failed.",
                },
                {"key": "result", "label": "Result", "type": "json", "helpText": "What the job produced: asset ids, a timeline, counts."},
                {"key": "log", "label": "Log", "type": "textarea", "rows": 6, "helpText": "What happened, and why it failed if it did."},
                {"key": "attempts", "label": "Attempts", "type": "number", "min": 0, "defaultValue": 0},
                {
                    "key": "claimed_at",
                    "label": "Claimed at",
                    "type": "text",
                    "helpText": "When the dispatcher picked it up (UTC, ISO). A claimed or running job with no progress past its "
                    "kind's timeout is marked failed.",
                },
                {"key": "claimed_by", "label": "Claimed by", "type": "text", "helpText": "Which worker took it."},
            ]
        },
    },
    "job-kind": {
        "name": "Job kind",
        "icon": "🧰",
        "description": "A kind of job and where it runs: which image does it, how it is started, and how long it may take.",
        "sort_order": 0,
        "is_rendered": False,
        "schema_json": {
            "fields": [
                {"key": "kind", "label": "Kind", "type": "text", "required": True, "helpText": "The name jobs ask for, e.g. audio-cut."},
                {
                    "key": "mode",
                    "label": "How it is started",
                    "type": "select",
                    "options": ["kubernetes", "docker", "http", "local"],
                    "defaultValue": "kubernetes",
                    "helpText": "kubernetes: a Job per run. docker: a container per run on a Docker host. http: sent to a "
                    "standing worker's URL. local: a process on the dispatcher's own machine.",
                },
                {
                    "key": "image",
                    "label": "Image",
                    "type": "text",
                    "helpText": "The container image that does this kind (kubernetes and docker modes).",
                },
                {"key": "url", "label": "Worker URL", "type": "text", "helpText": "http mode: the standing worker's address (its /jobs)."},
                {"key": "timeout_seconds", "label": "Time allowed (seconds)", "type": "number", "min": 30, "defaultValue": 3600},
                {
                    "key": "resources",
                    "label": "Resources",
                    "type": "json",
                    "helpText": 'Kubernetes requests and limits, e.g. {"cpu": "1", "memory": "1Gi"}.',
                },
                {"key": "notes", "label": "Notes", "type": "textarea", "rows": 3},
            ]
        },
    },
    "worker": {
        "name": "Worker",
        "icon": "🧰",
        "description": "A dispatcher's heartbeat: it rewrites last_seen about once a minute, so Settings → Workers can show whether anything is "
        "watching the queue.",
        "sort_order": 0,
        "is_rendered": False,
        "schema_json": {
            "fields": [
                {"key": "role", "label": "Role", "type": "text", "helpText": "dispatcher"},
                {"key": "host", "label": "Machine", "type": "text"},
                {"key": "modes", "label": "Starts", "type": "text", "helpText": "The modes it starts workers in, e.g. docker, kubernetes."},
                {"key": "last_seen", "label": "Last seen", "type": "text", "helpText": "UTC, ISO. Written by the dispatcher about once a minute."},
                {"key": "started_at", "label": "Started", "type": "text"},
                {"key": "jobs_started", "label": "Jobs started", "type": "number", "min": 0},
                {"key": "status", "label": "Status", "type": "text", "helpText": "idle or busy."},
                {"key": "current_job", "label": "Current job", "type": "text", "helpText": "The job it is running now, if any."},
                {
                    "key": "kinds",
                    "label": "Kinds it can do",
                    "type": "json",
                    "helpText": "Each kind it offers, with its contract: what it takes (inputs), the media types it accepts, what "
                    "it produces, and what it needs.",
                },
                {"key": "tags", "label": "Needs / has", "type": "text", "helpText": "What this machine has that its kinds need, e.g. ffmpeg."},
                {"key": "jobs_done", "label": "Jobs done", "type": "number", "min": 0},
            ]
        },
    },
}

WORKER_BLUEPRINTS: tuple[Blueprint, ...] = tuple(
    Blueprint(
        kind="entry_type",
        slug=slug,
        name=_PAYLOADS[slug]["name"],
        description=_PAYLOADS[slug]["description"],
        category=CATEGORY_WORKERS,
        payload=_PAYLOADS[slug],
    )
    for slug in WORKER_ENTRY_TYPES
)
