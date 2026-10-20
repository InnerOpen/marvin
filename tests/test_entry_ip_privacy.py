# ruff: noqa: F811  (pytest fixtures imported from test_audience_submissions are used as arguments)
"""A submitter's IP address (`metadata_json.submission.ip_address`, recorded on the entry by the public form route) is whole for an
ADMIN and above and masked for every other member, on every path that hands an entry's metadata to a member
(services/entry_privacy.py): the entries API (list, one, search, collection entries, update), the assistants' and MCP's get_entry
and find_entries, and the snapshot diff. The publishing API serves a site, so it never carries the address. Saving an entry never
overwrites the stored address with the masked form a member read.
"""

import json
from types import SimpleNamespace

import pytest

from marvin.db.models.platform.collections import Collections
from marvin.db.models.platform.entries import Entries
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.routes.publish import publishing_controller as pub
from marvin.services import entry_privacy as privacy
from marvin.services import snapshots
from marvin.services.ai.tools.base import ToolContext
from marvin.services.ai.tools.builtins import find_entries, get_entry
from marvin.services.collections.smart_collections import sync_collection
from tests.test_audience_submissions import (  # noqa: F401  (the `site`, `verdict` and `filled` fixtures)
    API,
    _client,
    filled,
    site,
    verdict,
    workspace,
)

FULL, MASKED = "203.0.113.77", "203.0.113.x"


def _stored_ip(site, entry_id):
    site.session.expire_all()
    return site.session.get(Entries, entry_id).metadata_json["submission"]["ip_address"]


def _ctx(site, role):
    user = SimpleNamespace(admin=False, platform_role=PlatformRole.NONE, get_workspace_role=lambda g: role)
    return ToolContext(session=site.session, group_id=site.gid, user=user, source="mcp")


ROLES = [(WorkspaceRole.AUTHOR, MASKED), (WorkspaceRole.EDITOR, MASKED), (WorkspaceRole.ADMIN, FULL), (WorkspaceRole.OWNER, FULL)]


# ── the masking itself ──────────────────────────────────────────────────────────────────────────────────────────


def test_the_helpers_mask_copy_and_leave_other_metadata_alone():
    meta = {"submission": {"ip_address": FULL, "user_agent": "ua"}, "other": 1}
    masked = privacy.mask_submission_ip(meta)
    assert masked == {"submission": {"ip_address": MASKED, "user_agent": "ua"}, "other": 1}
    assert meta["submission"]["ip_address"] == FULL  # the argument is untouched
    assert privacy.strip_submission_ip(meta) == {"submission": {"user_agent": "ua"}, "other": 1}
    for untouched in (None, {}, {"submission": {}}, {"submission": "x"}, {"other": 1}):
        assert privacy.mask_submission_ip(untouched) is untouched and privacy.strip_submission_ip(untouched) is untouched
    assert privacy.metadata_for(meta, True) is meta and privacy.metadata_for(meta, False) == masked
    assert privacy.mask_ip("2001:db8:85a3::8a2e:370:7334") == "2001:0db8:85a3::x" and privacy.mask_ip("bad") == "hidden"


def test_a_system_caller_with_no_user_gets_the_masked_form():
    assert privacy.can_see_full_ip(None, "any") is False


def test_keep_recorded_ip_puts_the_stored_address_back():
    stored = {"submission": {"ip_address": FULL, "user_agent": "ua"}}
    sent_back = {"submission": {"ip_address": MASKED, "user_agent": "ua2"}, "note": "x"}
    assert privacy.keep_recorded_ip(stored, sent_back) == {"submission": {"ip_address": FULL, "user_agent": "ua2"}, "note": "x"}
    assert privacy.keep_recorded_ip(stored, {"note": "x"}) == {"note": "x", "submission": {"ip_address": FULL}}  # they dropped the block
    assert privacy.keep_recorded_ip(stored, {"submission": {"ip_address": "9.9.9.9"}}) == {"submission": {"ip_address": FULL}}
    assert privacy.keep_recorded_ip({"a": 1}, {"submission": {"ip_address": "9.9.9.9"}}) == {"submission": {"ip_address": "9.9.9.9"}}
    assert privacy.keep_recorded_ip(stored, None) is None


# ── the entries API ─────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("role", "seen"), ROLES)
def test_one_entry_and_the_list_and_the_search_mask_below_admin(site, filled, role, seen):
    c = _client(site, role)
    one = c.get(f"{API}/entries/{filled.testimonial.id}")
    assert one.status_code == 200 and one.json()["metadataJson"]["submission"]["ip_address"] == seen
    listed = next(e for e in c.get(f"{API}/entries").json() if e["id"] == str(filled.testimonial.id))  # a content form is listed
    assert listed["metadataJson"]["submission"]["ip_address"] == seen
    found = c.post(f"{API}/entries/query", json={"spec": {"entry_type": "testimonial"}}).json()["entries"]
    assert [e["metadataJson"]["submission"]["ip_address"] for e in found] == [seen]
    internal = c.get(f"{API}/entries/{filled.contact.id}").json()  # an internal (Audience) entry read by id, the editor's data
    assert internal["metadataJson"]["submission"]["ip_address"] == seen
    assert _stored_ip(site, filled.testimonial.id) == FULL  # reading never changes what is stored


@pytest.mark.parametrize(("role", "seen"), ROLES)
def test_a_collections_entries_mask_below_admin(site, filled, role, seen):
    s = site.session
    coll = Collections(
        session=s,
        group_id=site.gid,
        slug="all-testimonials",
        name="Testimonials",
        is_smart=True,
        smart_rules={"entry_types": ["testimonial"], "match": "all"},
    )
    s.add(coll)
    s.commit()
    sync_collection(s, site.gid, coll)
    s.commit()
    rows = _client(site, role).get(f"{API}/collections/{coll.id}/entries").json()
    assert [r["metadataJson"]["submission"]["ip_address"] for r in rows] == [seen]


def test_a_member_saving_the_entry_as_they_read_it_keeps_the_stored_address(site, filled):
    c = _client(site, WorkspaceRole.EDITOR)
    eid = filled.testimonial.id
    read = c.get(f"{API}/entries/{eid}").json()
    meta = {**read["metadataJson"], "note": "followed up"}  # the editor posts back the metadata box
    res = c.patch(f"{API}/entries/{eid}", json={"metadata_json": meta, "title": "Great, edited"})
    assert res.status_code == 200, res.text
    assert res.json()["metadataJson"]["submission"]["ip_address"] == MASKED and res.json()["metadataJson"]["note"] == "followed up"
    assert _stored_ip(site, eid) == FULL
    # nor can they write another address, or drop the block
    c.patch(f"{API}/entries/{eid}", json={"metadata_json": {"submission": {"ip_address": "9.9.9.9"}}})
    assert _stored_ip(site, eid) == FULL
    c.patch(f"{API}/entries/{eid}", json={"metadata_json": {"note": "no block"}})
    assert _stored_ip(site, eid) == FULL


def test_an_admin_sees_it_whole_and_may_change_it(site, filled):
    c = _client(site, WorkspaceRole.ADMIN)
    eid = filled.testimonial.id
    read = c.get(f"{API}/entries/{eid}").json()
    assert read["metadataJson"]["submission"]["ip_address"] == FULL
    res = c.patch(f"{API}/entries/{eid}", json={"metadata_json": {**read["metadataJson"], "submission": {"ip_address": "198.51.100.1"}}})
    assert res.status_code == 200 and _stored_ip(site, eid) == "198.51.100.1"


# ── the assistants and MCP ──────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("role", "seen"), ROLES)
def test_get_entry_and_find_entries_mask_below_admin(site, filled, role, seen):
    got = json.loads(get_entry(_ctx(site, role), {"id_or_slug": str(filled.testimonial.id)}))
    assert got["metadataJson"]["submission"]["ip_address"] == seen
    found = json.loads(find_entries(_ctx(site, role), {"entry_type": "testimonial", "include_metadata": ["submission"]}))
    assert [e["metadata"]["submission"]["ip_address"] for e in found["entries"]] == [seen]
    assert _stored_ip(site, filled.testimonial.id) == FULL


def test_a_tool_run_with_no_user_is_masked(site, filled):
    ctx = ToolContext(session=site.session, group_id=site.gid, user=None, source="mcp")
    assert json.loads(get_entry(ctx, {"id_or_slug": str(filled.testimonial.id)}))["metadataJson"]["submission"]["ip_address"] == MASKED


# ── the snapshot diff ───────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("role", "seen"), ROLES[1:])  # an AUTHOR can't use snapshots on someone else's entry
def test_the_snapshot_diff_masks_below_admin(site, filled, role, seen):
    row, _ = snapshots.capture(site.session, site.gid, filled.testimonial.id, label="before")
    entry = site.session.get(Entries, filled.testimonial.id)
    entry.metadata_json = {**entry.metadata_json, "submission": {**entry.metadata_json["submission"], "ip_address": "198.51.100.200"}}
    site.session.commit()
    res = _client(site, role).get(f"{API}/entries/{filled.testimonial.id}/snapshots/{row.id}/diff", params={"parts": "content"})
    assert res.status_code == 200, res.text
    change = res.json()["content"]["metadata"]
    shown = json.dumps(change)
    assert (FULL in shown) == (seen == FULL) and seen in shown
    assert ("198.51.100.200" in shown) == (seen == FULL)  # the entry's current address too
    assert res.json()["changed"] is True  # what would change is decided on the real values


# ── the publishing API ──────────────────────────────────────────────────────────────────────────────────────────


def test_the_publishing_api_never_carries_the_address(site, filled):
    entry = site.session.get(Entries, filled.testimonial.id)
    assert pub._entry_to_read(entry, "ws").metadata["submission"].get("ip_address") is None
    assert pub._entry_to_list_item(entry, "ws").metadata["submission"].get("ip_address") is None
    assert pub._entry_to_read(entry, "ws").metadata["submission"]["user_agent"] == "pytest-agent"  # the rest of the block is unchanged


# ── the Event Log ───────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("role", "seen"), ROLES)
def test_the_event_log_detail_masks_a_submission_events_address(site, filled, role, seen):
    import uuid
    from datetime import UTC, datetime

    from marvin.db.models.platform.event_log import EventLogModel

    event_id = uuid.uuid4()
    site.session.add(
        EventLogModel(
            event_id=event_id,
            event_type="form_submission_received",
            occurred_at=datetime.now(UTC),
            workspace_id=site.gid,
            entity_id=filled.contact.id,
            entity_type="entry",
            integration_id="form_management",
            event_data={"documentData": {"ipAddress": FULL, "submissionData": {"email": "ann@x.test"}}, "nested": [{"ip_address": FULL}]},
            message_title="Submission received",
        )
    )
    site.session.commit()
    res = _client(site, role).get(f"{API}/events/{event_id}")
    assert res.status_code == 200, res.text
    data = res.json()["eventData"] if "eventData" in res.json() else res.json()["event_data"]
    assert data["documentData"]["ipAddress"] == seen and data["nested"][0]["ip_address"] == seen
    assert data["documentData"]["submissionData"]["email"] == "ann@x.test"
