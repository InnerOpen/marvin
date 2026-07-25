"""Restoring a backup must skip Marvin's system (workflow) collections.

The export bundles every collection, including the workflow collections (inbox/drafts/needs-review/
approved/archive). Those are seeded per workspace and locked from create/edit, so the importer's
attempt to (re)create or overwrite them failed with a 403 — noisy on every restore. They are
status-driven (entries land in them by status), so the importer skips them; the data is unaffected.
"""

from unittest.mock import MagicMock

from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader
from marvin.services.collections.system_collections import SYSTEM_COLLECTION_SLUGS


def _loader():
    repos = MagicMock()
    repos.collections.multi_query.return_value = []  # nothing pre-existing
    return WorkspaceSeedLoader(repos), repos


def test_system_collections_are_skipped_on_import():
    for slug in SYSTEM_COLLECTION_SLUGS:
        loader, repos = _loader()
        loader._create_collection({"slug": slug, "name": slug.title()})
        repos.collections.create.assert_not_called()
        repos.collections.update.assert_not_called()


def test_user_collections_are_still_created():
    loader, repos = _loader()
    loader._create_collection({"slug": "featured", "name": "Featured"})
    repos.collections.create.assert_called_once()


def test_the_five_workflow_slugs_are_covered():
    assert SYSTEM_COLLECTION_SLUGS == frozenset({"inbox", "drafts", "needs-review", "approved", "archive"})
