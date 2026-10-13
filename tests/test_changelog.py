"""Release notes for the admin's update banner (services/changelog.py, GET /api/app/changes)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from marvin.services import changelog
from marvin.services.changelog import (
    FALLBACK_RELEASES,
    MAX_RELEASES,
    UNRELEASED_VERSION,
    load_releases,
    load_unreleased,
    parse_changelog,
    parse_unreleased,
    select_releases,
    version_key,
)

CHANGES_URL = "/api/app/changes"
COMMIT = "https://github.com/InnerOpen/marvin/commit/"

CHANGELOG = f"""# Changelog

All notable changes to the Marvin CMS server will be documented in this file.

<!-- version list -->

## v1.0.0-rc.10 (2026-10-03)

### Features

- **admin**: Group the admin nav, turn /admin into an overview
  ([`dffdd86`]({COMMIT}dffdd8682c5877d2a0207edef66ad28aa0ba6923))

### Chores

- Bump deps
  ([`aaaaaaa`]({COMMIT}aaaaaaa000000000000000000000000000000000))


## v1.0.0-rc.9 (2026-10-02)

### Documentation

- Publish the Marvin manual
  ([`888ba85`]({COMMIT}888ba85da32a4008ff6df49fa52f30395a3d0fa2))

### Bug Fixes

- Bugs the manual review found — fail-closed where ops, apply_many connection,
  stale UI copy
  ([`f08d0c2`]({COMMIT}f08d0c2495a75c9c8fe5ea13ec4a6b4f8f39a9d3))

- **bubble**: Keep threads per workspace; recover from a 404'd thread (slice C)
  ([`6bc32ec`]({COMMIT}6bc32ecc0702a1a85d754029facdd2c086b57618))


## v1.0.0-rc.2 (2026-07-24)

### Bug Fixes

- **migrations**: Make the webhook_type enum change reversible on Postgres
  ([#20](https://github.com/InnerOpen/marvin/pull/20),
  [`de14656`]({COMMIT}de146566f1bfbeae10083e871d3a4bc98d8f0e4c))


## v1.0.0-rc.1 (2026-07-24)

- Initial Release

## [0.2.0] - 2026-07-10

Initial version tracking setup with Python Semantic Release.

### Added
- Semantic versioning automation

[0.2.0]: https://github.com/InnerOpen/marvin/releases/tag/v0.2.0
"""

RELEASES = parse_changelog(CHANGELOG)


def _versions(releases):
    return [r.version for r in releases]


def _many_releases(count: int) -> str:
    return "\n\n".join(f"## v1.0.0-rc.{n} (2026-10-01)\n\n### Features\n\n- Change {n}" for n in range(count, 0, -1))


# ── parsing ──────────────────────────────────────────────────────────────────


def test_parse_changelog_reads_every_release_with_its_date():
    assert [(r.version, r.date) for r in RELEASES] == [
        ("1.0.0-rc.10", "2026-10-03"),
        ("1.0.0-rc.9", "2026-10-02"),
        ("1.0.0-rc.2", "2026-07-24"),
        ("1.0.0-rc.1", "2026-07-24"),
        ("0.2.0", "2026-07-10"),
    ]


def test_parse_changelog_groups_items_under_their_section_titles():
    assert [s.title for s in RELEASES[1].sections] == ["Documentation", "Bug Fixes"]


def test_parse_changelog_splits_scope_summary_and_full_commit():
    item = RELEASES[0].sections[0].items[0]
    assert (item.scope, item.summary, item.commit, item.commit_url) == (
        "admin",
        "Group the admin nav, turn /admin into an overview",
        "dffdd8682c5877d2a0207edef66ad28aa0ba6923",
        f"{COMMIT}dffdd8682c5877d2a0207edef66ad28aa0ba6923",
    )


def test_parse_changelog_joins_wrapped_summaries_and_keeps_plain_parentheses():
    unscoped, scoped = RELEASES[1].sections[1].items
    assert (unscoped.scope, unscoped.summary) == (None, "Bugs the manual review found — fail-closed where ops, apply_many connection, stale UI copy")
    assert scoped.summary == "Keep threads per workspace; recover from a 404'd thread (slice C)"


def test_parse_changelog_finds_the_commit_after_a_pr_link():
    item = RELEASES[2].sections[0].items[0]
    assert (item.summary, item.commit) == ("Make the webhook_type enum change reversible on Postgres", "de146566f1bfbeae10083e871d3a4bc98d8f0e4c")


def test_parse_changelog_puts_unsectioned_bullets_in_a_default_section():
    (section,) = RELEASES[3].sections
    assert (section.title, [i.summary for i in section.items], section.items[0].commit) == ("Changes", ["Initial Release"], None)


def test_parse_changelog_of_an_empty_file_is_empty():
    assert parse_changelog("") == []


# ── versions ─────────────────────────────────────────────────────────────────


def test_version_key_orders_rc_numbers_numerically():
    assert sorted(["1.0.0-rc.158", "1.0.0-rc.10", "1.0.0-rc.9"], key=version_key) == ["1.0.0-rc.9", "1.0.0-rc.10", "1.0.0-rc.158"]


def test_version_key_puts_a_final_release_after_its_prereleases():
    assert version_key("1.0.0-rc.158") < version_key("1.0.0") < version_key("1.0.1-rc.1") < version_key("1.0.1")


def test_version_key_orders_plain_semver_and_accepts_a_v_prefix():
    assert version_key("0.2.0") < version_key("v0.10.0") < version_key("1.2.3")


def test_version_key_orders_numeric_identifiers_before_alphanumeric():
    assert version_key("1.0.0-alpha") < version_key("1.0.0-alpha.1") < version_key("1.0.0-alpha.beta") < version_key("1.0.0-beta")


@pytest.mark.parametrize("garbage", ["", "unknown", "dev", "1.0", "1.0.0-", "6bc32ecc0702"])
def test_version_key_of_a_non_version_is_none(garbage):
    assert version_key(garbage) is None


# ── selecting ────────────────────────────────────────────────────────────────


def test_select_releases_returns_only_newer_than_since_newest_first():
    assert _versions(select_releases(RELEASES, since="1.0.0-rc.2", until="1.0.0-rc.10")) == ["1.0.0-rc.10", "1.0.0-rc.9"]


def test_select_releases_includes_until_and_nothing_after_it():
    assert _versions(select_releases(RELEASES, since="1.0.0-rc.1", until="1.0.0-rc.9")) == ["1.0.0-rc.9", "1.0.0-rc.2"]


def test_select_releases_defaults_until_to_the_running_version(monkeypatch):
    monkeypatch.setattr(changelog, "APP_VERSION", "1.0.0-rc.9")
    assert _versions(select_releases(RELEASES, since="1.0.0-rc.2")) == ["1.0.0-rc.9"]


def test_select_releases_at_the_current_version_is_empty():
    assert select_releases(RELEASES, since="1.0.0-rc.10", until="1.0.0-rc.10") == []


def test_select_releases_caps_the_count():
    many = parse_changelog(_many_releases(MAX_RELEASES + 5))
    picked = select_releases(many, since="0.0.1", until=f"1.0.0-rc.{MAX_RELEASES + 5}")
    assert (len(picked), picked[0].version) == (MAX_RELEASES, f"1.0.0-rc.{MAX_RELEASES + 5}")


@pytest.mark.parametrize("since", [None, "unknown", "not-a-version"])
def test_select_releases_without_a_usable_since_returns_the_latest_few(since):
    many = parse_changelog(_many_releases(FALLBACK_RELEASES + 3))
    picked = select_releases(many, since=since, until=f"1.0.0-rc.{FALLBACK_RELEASES + 3}")
    assert _versions(picked) == [f"1.0.0-rc.{n}" for n in range(FALLBACK_RELEASES + 3, 3, -1)]


def test_select_releases_since_commit_starts_after_the_release_listing_it():
    picked = select_releases(RELEASES, since="1.0.0-rc.10", until="1.0.0-rc.10", since_commit="6bc32ecc0702")
    assert _versions(picked) == ["1.0.0-rc.10"]


def test_select_releases_since_commit_matches_without_since():
    assert _versions(select_releases(RELEASES, until="1.0.0-rc.10", since_commit="de146566f1bf")) == ["1.0.0-rc.10", "1.0.0-rc.9"]


def test_select_releases_prefers_a_placed_commit_over_the_lagging_version():
    # An image built from 6bc32ec still reports the release before it (rc.2): the commit is finer.
    picked = select_releases(RELEASES, since="1.0.0-rc.2", until="1.0.0-rc.10", since_commit="6bc32ecc0702")
    assert _versions(picked) == ["1.0.0-rc.10"]


@pytest.mark.parametrize("commit", ["0123456789ab", "dff", "zzzzzzzzzzzz"])
def test_select_releases_with_an_unknown_commit_falls_back_to_since(commit):
    assert _versions(select_releases(RELEASES, since="1.0.0-rc.9", until="1.0.0-rc.10", since_commit=commit)) == ["1.0.0-rc.10"]


# ── unreleased commits ───────────────────────────────────────────────────────

FEAT_SHA = "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
CHORE_SHA = "2222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
FIX_SHA = "3333333ccccccccccccccccccccccccccccccccc"
DOCS_SHA = "4444444ddddddddddddddddddddddddddddddddd"

UNRELEASED = parse_unreleased(
    "# since: v1.0.0-rc.10\n"
    "# built: 2026-10-04T09:30:00Z\n"
    f"{FEAT_SHA}\tfeat(ui): pick a bubble character from cards, not a dropdown\n"
    f"{CHORE_SHA}\tchore(deps): bump astro\n"
    f"{FIX_SHA}\tfix!: keep threads per workspace\n"
    f"{DOCS_SHA}\tdocs: publish the Marvin manual\n"
)


def _unreleased_entry(picked):
    assert picked and picked[0].version == UNRELEASED_VERSION
    return picked[0]


def test_parse_unreleased_reads_the_build_date_and_every_commit():
    assert (UNRELEASED.built, [c.sha for c in UNRELEASED.commits]) == ("2026-10-04", [FEAT_SHA, CHORE_SHA, FIX_SHA, DOCS_SHA])


def test_parse_unreleased_splits_conventional_subjects():
    feat = UNRELEASED.commits[0]
    assert (feat.type, feat.scope, feat.summary) == ("feat", "ui", "Pick a bubble character from cards, not a dropdown")


def test_parse_unreleased_keeps_a_free_form_subject_untyped():
    (commit,) = parse_unreleased(f"{FEAT_SHA}\tMerge the thing\n").commits
    assert (commit.type, commit.summary) == (None, "Merge the thing")


def test_parse_unreleased_of_a_header_only_file_has_no_commits():
    assert parse_unreleased("# since: v1.0.0-rc.10\n# built: 2026-10-04T09:30:00Z\n").commits == ()


def test_unreleased_entry_groups_by_type_and_drops_bookkeeping():
    entry = _unreleased_entry(select_releases(RELEASES, since="1.0.0-rc.10", unreleased=UNRELEASED))
    assert [(s.title, [i.commit for i in s.items]) for s in entry.sections] == [
        ("Features", [FEAT_SHA]),
        ("Bug Fixes", [FIX_SHA]),
        ("Documentation", [DOCS_SHA]),
    ]


def test_unreleased_entry_links_commits_like_the_changelog_and_carries_the_build_date():
    entry = _unreleased_entry(select_releases(RELEASES, since="1.0.0-rc.10", unreleased=UNRELEASED))
    assert (entry.date, entry.sections[0].items[0].commit_url) == ("2026-10-04", f"{COMMIT}{FEAT_SHA}")


def test_select_releases_puts_unreleased_first_then_releases(monkeypatch):
    monkeypatch.setattr(changelog, "APP_VERSION", "1.0.0-rc.10")
    picked = select_releases(RELEASES, since="1.0.0-rc.2", unreleased=UNRELEASED)
    assert _versions(picked) == [UNRELEASED_VERSION, "1.0.0-rc.10", "1.0.0-rc.9"]


def test_select_releases_since_an_unreleased_commit_lists_only_newer_unreleased_ones(monkeypatch):
    monkeypatch.setattr(changelog, "APP_VERSION", "1.0.0-rc.10")
    picked = select_releases(RELEASES, since="1.0.0-rc.10", since_commit=FIX_SHA[:12], unreleased=UNRELEASED)
    (entry,) = picked
    assert [i.commit for s in entry.sections for i in s.items] == [FEAT_SHA]


def test_select_releases_since_the_newest_unreleased_commit_is_empty(monkeypatch):
    monkeypatch.setattr(changelog, "APP_VERSION", "1.0.0-rc.10")
    assert select_releases(RELEASES, since="1.0.0-rc.9", since_commit=FEAT_SHA[:12], unreleased=UNRELEASED) == []


def test_select_releases_skips_an_unreleased_entry_with_only_bookkeeping(monkeypatch):
    monkeypatch.setattr(changelog, "APP_VERSION", "1.0.0-rc.10")
    chores = parse_unreleased(f"{CHORE_SHA}\tchore(deps): bump astro\nci: cache\n")
    assert _versions(select_releases(RELEASES, since="1.0.0-rc.9", unreleased=chores)) == ["1.0.0-rc.10"]


def test_select_releases_with_an_explicit_until_leaves_unreleased_out():
    assert _versions(select_releases(RELEASES, since="1.0.0-rc.9", until="1.0.0-rc.10", unreleased=UNRELEASED)) == ["1.0.0-rc.10"]


def test_load_unreleased_of_a_missing_file_is_none(tmp_path: Path):
    assert (load_unreleased(tmp_path / "UNRELEASED.txt"), load_unreleased(None)) == (None, None)


# ── loading ──────────────────────────────────────────────────────────────────


def test_load_releases_of_a_missing_file_is_empty(tmp_path: Path):
    assert load_releases(tmp_path / "CHANGELOG.md") == ()


def test_load_releases_without_a_changelog_is_empty():
    assert load_releases(None) == ()


def test_load_releases_reads_the_file_once(tmp_path: Path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(CHANGELOG, encoding="utf-8")
    first = load_releases(path)
    path.write_text("", encoding="utf-8")
    assert load_releases(path) is first


def test_the_source_checkout_changelog_is_found_and_parses():
    path = changelog.find_changelog()
    assert path is not None and load_releases(path)[0].version


# ── endpoint ─────────────────────────────────────────────────────────────────


@pytest.fixture
def signed_in(client):
    from marvin.app import app
    from marvin.core.dependencies import get_current_user

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1", admin=False, is_superuser=False)
    yield client
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def fixture_changelog(monkeypatch):
    monkeypatch.setattr(changelog, "get_releases", lambda: tuple(RELEASES))
    monkeypatch.setattr(changelog, "get_unreleased", lambda: None)
    monkeypatch.setattr(changelog, "APP_VERSION", "1.0.0-rc.10")


def test_changes_endpoint_requires_auth(client):
    assert client.get(CHANGES_URL).status_code == 401


def test_changes_endpoint_returns_releases_since_a_version(signed_in, fixture_changelog):
    res = signed_in.get(CHANGES_URL, params={"since": "1.0.0-rc.9"})
    assert res.status_code == 200
    (release,) = res.json()
    first_item = release["sections"][0]["items"][0]
    assert (release["version"], first_item["commitUrl"]) == ("1.0.0-rc.10", f"{COMMIT}dffdd8682c5877d2a0207edef66ad28aa0ba6923")


def test_changes_endpoint_accepts_since_commit(signed_in, fixture_changelog):
    res = signed_in.get(CHANGES_URL, params={"since": "1.0.0-rc.10", "since_commit": "6bc32ecc0702"})
    assert [r["version"] for r in res.json()] == ["1.0.0-rc.10"]


def test_changes_endpoint_without_a_changelog_is_an_empty_list(signed_in, monkeypatch):
    monkeypatch.setattr(changelog, "find_changelog", lambda: None)
    res = signed_in.get(CHANGES_URL, params={"since": "garbage"})
    assert (res.status_code, res.json()) == (200, [])


def test_changes_endpoint_leads_with_unreleased_commits(signed_in, fixture_changelog, monkeypatch):
    monkeypatch.setattr(changelog, "get_unreleased", lambda: UNRELEASED)
    res = signed_in.get(CHANGES_URL, params={"since": "1.0.0-rc.10", "since_commit": DOCS_SHA[:12]})
    assert [(r["version"], [s["title"] for s in r["sections"]]) for r in res.json()] == [(UNRELEASED_VERSION, ["Features", "Bug Fixes"])]


def test_changes_endpoint_without_an_unreleased_file_still_lists_releases(signed_in, monkeypatch):
    monkeypatch.setattr(changelog, "get_releases", lambda: tuple(RELEASES))
    monkeypatch.setattr(changelog, "find_unreleased", lambda: None)
    monkeypatch.setattr(changelog, "APP_VERSION", "1.0.0-rc.10")
    res = signed_in.get(CHANGES_URL, params={"since": "1.0.0-rc.9"})
    assert [r["version"] for r in res.json()] == ["1.0.0-rc.10"]
