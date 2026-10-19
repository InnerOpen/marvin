"""The golden workspace bundle: a committed `tests/fixtures/bundles/golden-workspace.zip` that every engine's suite imports.

It is the format a workspace export writes (`WorkspaceExporter.export_workspace_bundle`): one root-level JSON with the
exporter's sections, and the asset binaries under `files/`. It carries a collection, tags, entry types, entries linked to
collections / assets / resources / tags, two files with real bytes, variables, an AI policy, and two secrets wrapped under
`GOLDEN_BACKUP_KEY` (the per-workspace backup key; it never travels in a bundle, a restore supplies it).

The key is a throwaway made for this fixture (derived from a phrase below), not a credential. Fernet tokens are random, so regenerating changes the
zip's bytes: commit a regenerated zip only when the bundle's *content* has to change, and update `GOLDEN` with it:

    uv run python -m tests.golden_bundle
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import sys
import zipfile
import zlib
from pathlib import Path

BUNDLE_PATH = Path(__file__).parent / "fixtures" / "bundles" / "golden-workspace.zip"
# A Fernet key derived from a phrase, so no key-shaped literal sits in the repository.
GOLDEN_BACKUP_KEY = base64.urlsafe_b64encode(hashlib.sha256(b"marvin golden bundle backup key").digest()).decode()


def _png() -> bytes:
    """A valid 2x2 PNG, built here so no hand-typed bytes can be wrong."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    rows = b"".join(b"\x00" + b"\xd4\xa0\x17" * 2 for _ in range(2))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


PNG_BYTES = _png()
NOTES_BYTES = b"Golden notes\nA file that must come back byte for byte.\n"

SECRETS = {"GOLDEN_API_KEY": "golden api credential", "GOLDEN_WEBHOOK_TOKEN": "golden webhook credential"}

# What importing the bundle into an empty workspace must produce: the importer's counts (the response's `imported`)
# for the sections the bundle fills, and the number of rows each leaves in the workspace.
GOLDEN = {
    "workspace_name": "Golden Co",
    "counts": {
        "collections": 2,
        "tags": 3,
        "entry_types": 2,
        "entries": 5,
        "resources": 2,
        "assets": 2,
        "variables": 2,
        "secrets": 2,
        "ai_settings": 1,
    },
    "files": {
        "golden-notes.txt": hashlib.sha256(NOTES_BYTES).hexdigest(),
        "golden-pixel.png": hashlib.sha256(PNG_BYTES).hexdigest(),
    },
    "secrets": SECRETS,
    "variables": {"SITE_URL": "https://golden.example.com", "SUPPORT_EMAIL": "help@golden.example.com"},
    "tags": ["golden", "launch", "notes"],
    "entries": {
        "welcome": {
            "entryType": "golden-note",
            "collection": "featured-notes",
            "tags": ["golden", "launch"],
            "asset": "golden-notes",
            "resource": "docs-home",
        },
        "launch-day": {"entryType": "golden-event", "collection": "featured-notes", "tags": ["launch"], "asset": "golden-pixel", "resource": None},
        "meeting-notes": {"entryType": "golden-note", "collection": "archive-notes", "tags": ["notes"], "asset": None, "resource": "style-guide"},
        "faq": {"entryType": "golden-note", "collection": None, "tags": [], "asset": None, "resource": None},
        "retro": {"entryType": "golden-event", "collection": "archive-notes", "tags": ["golden", "notes"], "asset": None, "resource": None},
    },
}

_SECTIONS = (
    "integrations", "ai_providers", "mcp_servers", "smtp_profiles", "webhooks", "agents", "incoming_webhooks", "automations",
    "scheduled_tasks", "forms", "email_templates", "email_subscriptions", "integration_subscriptions",
)  # fmt: skip


def _entry(slug: str, title: str, spec: dict, status: str) -> dict:
    entry: dict = {
        "entryType": spec["entryType"],
        "title": title,
        "slug": slug,
        "status": status,
        "summary": f"{title}: summary",
        "description": f"{title}: description",
        "data": {"body": f"The body of {title}.", "words": len(title.split())},
        "metadataJson": {"golden": True},
        "publishAt": None,
        "expireAt": None,
    }
    if spec["collection"]:
        entry["collections"] = [{"slug": spec["collection"], "order": 0}]
    if spec["asset"]:
        entry["assets"] = [{"slug": spec["asset"], "position": 0, "role": "attachment"}]
    if spec["resource"]:
        entry["resources"] = [{"slug": spec["resource"], "position": 0, "role": "reference"}]
    if spec["tags"]:
        entry["tags"] = list(spec["tags"])
    return entry


def build(path: Path = BUNDLE_PATH) -> Path:
    """Write the golden bundle to `path` and return it."""
    from marvin.services.backup.keys import encrypt_secret_value

    titles = {"welcome": "Welcome", "launch-day": "Launch day", "meeting-notes": "Meeting notes", "faq": "FAQ", "retro": "Retro"}
    statuses = {"welcome": "published", "launch-day": "published", "meeting-notes": "draft", "faq": "draft", "retro": "draft"}
    asset_files = {
        "golden-notes": ("golden-notes.txt", "txt", "text/plain", "document", NOTES_BYTES, "golden/2026/10/0a1b2c3d-0000-4000-8000-000000000001.txt"),
        "golden-pixel": ("golden-pixel.png", "png", "image/png", "image", PNG_BYTES, "golden/2026/10/0a1b2c3d-0000-4000-8000-000000000002.png"),
    }
    assets = [
        {
            "name": slug.replace("-", " ").title(),
            "slug": slug,
            "originalFilename": filename,
            "filename": filename.rsplit(".", 1)[0],
            "checksum": hashlib.sha256(raw).hexdigest(),
            "extension": ext,
            "fileSize": len(raw),
            "mimeType": mime,
            "assetType": kind,
            "storageProvider": "local",
            "storageKey": key,
            "altText": f"{filename} (golden)",
            "tags": ["golden"] if slug == "golden-pixel" else [],
        }
        for slug, (filename, ext, mime, kind, raw, key) in asset_files.items()
    ]
    for asset in assets:
        if not asset["tags"]:
            del asset["tags"]
    data = {
        "version": 1,
        "workspace": {"name": GOLDEN["workspace_name"]},
        "site": {"title": "Golden Co", "tagline": "Restores byte for byte", "locale": "en", "timezone": "UTC"},
        "collections": [
            {"name": "Featured notes", "slug": "featured-notes", "description": "Pinned", "sortOrder": 1, "icon": "star", "color": "#d4a017"},
            {"name": "Archive notes", "slug": "archive-notes", "description": "Old", "sortOrder": 2, "icon": "archive", "color": "#667788"},
        ],
        "tags": [{"name": t.title(), "slug": t, "color": "#3366cc"} for t in GOLDEN["tags"]],
        "entry_types": [
            {
                "name": "Golden note", "slug": "golden-note", "icon": "note", "color": "#3366cc", "description": "A note", "sortOrder": 1,
                "schemaJson": {"type": "object", "properties": {"body": {"type": "string"}, "words": {"type": "integer"}}},
                "renderingJson": None, "capabilitiesJson": None, "recipeJson": None, "pageUrlPattern": None,
            },
            {
                "name": "Golden event", "slug": "golden-event", "icon": "calendar", "color": "#cc6633", "description": "An event", "sortOrder": 2,
                "schemaJson": {"type": "object", "properties": {"body": {"type": "string"}}},
                "renderingJson": None, "capabilitiesJson": None, "recipeJson": None, "pageUrlPattern": None,
            },
        ],
        "entries": [_entry(slug, titles[slug], spec, statuses[slug]) for slug, spec in sorted(GOLDEN["entries"].items())],
        "assets": assets,
        "resources": [
            {"name": "Docs home", "slug": "docs-home", "resourceType": "link", "description": "Where the docs live", "url": "https://docs.golden.example.com"},
            {"name": "Style guide", "slug": "style-guide", "resourceType": "material", "description": "House style"},
        ],
        "variables": [
            {"name": slug.replace("_", " ").title(), "slug": slug, "description": None, "value": value} for slug, value in GOLDEN["variables"].items()
        ],
        "ai_settings": {
            "enabled": True, "credentialMode": "own", "provider": "openai", "model": "gpt-golden", "secretRef": "GOLDEN_API_KEY",
            "assistantName": "Goldie", "defaultRegister": "playful",
        },
        "secrets": [
            {
                "name": slug.replace("_", " ").title(),
                "slug": slug,
                "description": "golden fixture",
                "encryptedBackupValue": encrypt_secret_value(value, GOLDEN_BACKUP_KEY),
            }
            for slug, value in sorted(SECRETS.items())
        ],
        **{section: [] for section in _SECTIONS},
        "notifications": None,
    }  # fmt: skip
    basename = "golden-co-backup-2026-10-18-0123456789abcdef"
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in (
            (f"{basename}.json", json.dumps(data, indent=2, ensure_ascii=False).encode()),
            *((f"files/{a['storageKey']}", raw) for a, (*_, raw, _key) in zip(assets, asset_files.values(), strict=True)),
        ):
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 18, 12, 0, 0))  # fixed: the zip's metadata never changes
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, content)
    return path


if __name__ == "__main__":
    sys.stdout.write(f"{build()}\n")
