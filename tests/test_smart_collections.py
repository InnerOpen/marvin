"""Unit tests for the smart-collection rule evaluator.

`entry_matches_rules` decides whether an entry belongs in a smart collection. It's the pure
core of the materialized-membership machinery; the reaction listener and the sync helpers all
delegate to it.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from marvin.services.collections.smart_collections import entry_matches_rules, matches_rules


def _ago(days, aware=False):
    """A datetime `days` days in the past — naive UTC by default, matching the NaiveDateTime columns."""
    when = datetime.now(UTC) - timedelta(days=days)
    return when if aware else when.replace(tzinfo=None)


def _entry(type_slug="bench-note", status="published", tag_names=None, published_at=None, created_at=None):
    # `tag_names` = the entry's tag SLUGS. The matcher reads `entry.tag_names` (a property over the
    # real tags relationship), not `entry.tags` (which is now Tag objects).
    return SimpleNamespace(
        status=status,
        entry_type=SimpleNamespace(slug=type_slug),
        tag_names=tag_names,
        published_at=published_at,
        created_at=created_at,
    )


def test_empty_rules_match_nothing():
    assert entry_matches_rules(_entry(), None) is False
    assert entry_matches_rules(_entry(), {}) is False


def test_rules_with_no_recognized_dimension_match_nothing():
    # A non-empty rule dict with only `match` (no constraints) must not match everything.
    assert entry_matches_rules(_entry(), {"match": "all"}) is False


def test_entry_type_match():
    assert entry_matches_rules(_entry(type_slug="article"), {"entry_types": ["article"]}) is True
    assert entry_matches_rules(_entry(type_slug="bench-note"), {"entry_types": ["article"]}) is False


def test_status_match():
    assert entry_matches_rules(_entry(status="published"), {"statuses": ["published"]}) is True
    assert entry_matches_rules(_entry(status="inbox"), {"statuses": ["published"]}) is False


def test_match_all_requires_every_dimension():
    rules = {"entry_types": ["bench-note"], "statuses": ["published"]}
    assert entry_matches_rules(_entry("bench-note", "published"), rules) is True
    assert entry_matches_rules(_entry("bench-note", "inbox"), rules) is False  # wrong status
    assert entry_matches_rules(_entry("article", "published"), rules) is False  # wrong type


def test_match_any_requires_only_one_dimension():
    rules = {"entry_types": ["bench-note"], "statuses": ["published"], "match": "any"}
    assert entry_matches_rules(_entry("bench-note", "inbox"), rules) is True  # type matches
    assert entry_matches_rules(_entry("article", "published"), rules) is True  # status matches
    assert entry_matches_rules(_entry("article", "inbox"), rules) is False  # neither


def test_tags_dimension_matches_on_slug_overlap():
    # entry carrying tags → matches on overlap
    assert entry_matches_rules(_entry(tag_names=["leather", "waxed"]), {"tags": ["waxed"]}) is True
    assert entry_matches_rules(_entry(tag_names=["leather"]), {"tags": ["waxed"]}) is False
    # entry with no tags → inert, no crash
    assert entry_matches_rules(_entry(tag_names=None), {"tags": ["waxed"]}) is False


def test_tags_rule_is_slugified_so_display_names_match():
    # A rule may store the display name ("Waxed Canvas"); the entry carries the slug. They must match.
    assert entry_matches_rules(_entry(tag_names=["waxed-canvas"]), {"tags": ["Waxed Canvas"]}) is True
    assert entry_matches_rules(_entry(tag_names=["waxed-canvas"]), {"tags": ["waxed canvas"]}) is True


def test_entry_without_entry_type_relationship_does_not_crash():
    entry = SimpleNamespace(status="published", entry_type=None, tag_names=None)
    assert entry_matches_rules(entry, {"entry_types": ["article"]}) is False


# ── asset / resource target types (Phase: smart collections of assets/resources) ──────────────


def _asset(asset_type="image", tag_names=None, mime_type="image/jpeg"):
    return SimpleNamespace(asset_type=asset_type, tag_names=tag_names, mime_type=mime_type)


def _resource(resource_type="fabric", tag_names=None):
    return SimpleNamespace(resource_type=resource_type, tag_names=tag_names)


def test_asset_matches_on_asset_type_and_tags():
    assert matches_rules(_asset(asset_type="image"), {"asset_types": ["image"]}, "asset") is True
    assert matches_rules(_asset(asset_type="video"), {"asset_types": ["image"]}, "asset") is False
    assert matches_rules(_asset(tag_names=["hero"]), {"tags": ["Hero"]}, "asset") is True  # slugified
    # match=all across type + tags
    rules = {"asset_types": ["image"], "tags": ["hero"], "match": "all"}
    assert matches_rules(_asset("image", ["hero"]), rules, "asset") is True
    assert matches_rules(_asset("image", ["other"]), rules, "asset") is False


def test_asset_matches_on_exact_mime_type():
    # mime_types is finer than asset_types: an SVG (image/svg+xml) is asset_type "svg", a JPEG is
    # asset_type "image" — so mime_types distinguishes them where asset_types can't.
    svg = _asset(asset_type="svg", mime_type="image/svg+xml")
    jpg = _asset(asset_type="image", mime_type="image/jpeg")
    assert matches_rules(svg, {"mime_types": ["image/svg+xml"]}, "asset") is True
    assert matches_rules(jpg, {"mime_types": ["image/svg+xml"]}, "asset") is False
    # combines (AND) with tags
    rules = {"mime_types": ["image/svg+xml"], "tags": ["site-asset"], "match": "all"}
    assert matches_rules(_asset("svg", ["site-asset"], "image/svg+xml"), rules, "asset") is True
    assert matches_rules(_asset("image", ["site-asset"], "image/jpeg"), rules, "asset") is False


def test_resource_matches_on_resource_type_and_tags():
    assert matches_rules(_resource(resource_type="fabric"), {"resource_types": ["fabric"]}, "resource") is True
    assert matches_rules(_resource(resource_type="tool"), {"resource_types": ["fabric"]}, "resource") is False
    assert matches_rules(_resource(tag_names=["waxed-canvas"]), {"tags": ["Waxed Canvas"]}, "resource") is True


def test_target_type_dimensions_are_isolated():
    # An entry_types rule doesn't accidentally match an asset (wrong target type → dimension ignored,
    # no dimensions → matches nothing).
    assert matches_rules(_asset(), {"entry_types": ["article"]}, "asset") is False
    assert matches_rules(_resource(), {"statuses": ["published"]}, "resource") is False


def test_published_within_days_matches_only_inside_the_window():
    rules = {"published_within_days": 30}
    assert entry_matches_rules(_entry(published_at=_ago(2)), rules) is True
    assert entry_matches_rules(_entry(published_at=_ago(29)), rules) is True
    assert entry_matches_rules(_entry(published_at=_ago(31)), rules) is False


def test_published_within_days_reads_naive_dates_as_utc():
    # Columns are NaiveDateTime storing UTC; a naive value must not be read as local time.
    rules = {"published_within_days": 1}
    assert entry_matches_rules(_entry(published_at=_ago(0.25)), rules) is True
    assert entry_matches_rules(_entry(published_at=_ago(0.25, aware=True)), rules) is True


def test_never_published_entry_is_outside_any_window():
    assert entry_matches_rules(_entry(status="draft", published_at=None), {"published_within_days": 30}) is False


def test_a_broken_window_matches_nothing_rather_than_widening():
    # A misconfigured window must fail closed — never drop the constraint and swallow the workspace.
    for bad in (0, -5, "soon", None):
        assert entry_matches_rules(_entry(published_at=_ago(1)), {"published_within_days": bad}) is False


def test_window_combines_with_status_under_match_all():
    rules = {"statuses": ["published"], "published_within_days": 30}
    assert entry_matches_rules(_entry(status="published", published_at=_ago(3)), rules) is True
    assert entry_matches_rules(_entry(status="draft", published_at=_ago(3)), rules) is False
    assert entry_matches_rules(_entry(status="published", published_at=_ago(90)), rules) is False


def test_created_within_days_is_universal_across_target_types():
    asset = SimpleNamespace(asset_type="image", created_at=_ago(1), tag_names=None)
    stale = SimpleNamespace(asset_type="image", created_at=_ago(40), tag_names=None)
    rules = {"asset_types": ["image"], "created_within_days": 7}
    assert matches_rules(asset, rules, "asset") is True
    assert matches_rules(stale, rules, "asset") is False


def test_default_recent_collection_is_a_working_rolling_window():
    """The bootstrap "Recent" default must actually collect something — it shipped for a long time
    as a manual collection described as "recently published content", which nothing could fill."""
    from marvin.services.workspace.workspace_bootstrap_service import WorkspaceBootstrapService

    recent = next(c for c in WorkspaceBootstrapService.DEFAULT_COLLECTIONS if c["slug"] == "recent")
    assert recent["is_smart"] is True
    rules = recent["smart_rules"]
    assert entry_matches_rules(_entry(status="published", published_at=_ago(1)), rules) is True
    assert entry_matches_rules(_entry(status="published", published_at=_ago(400)), rules) is False
    assert entry_matches_rules(_entry(status="draft", published_at=None), rules) is False
