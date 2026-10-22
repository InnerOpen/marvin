"""The Site links setup check (services/site_links.py): an entry's `url` needs the workspace's site address AND its type's
page URL pattern. The check lists what is missing; a workflow that uses `${entry.url}` warns when it can't be a link."""

import json
import uuid
from types import SimpleNamespace

from pytest import fixture

from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.ai.tools import get_tool
from marvin.services.site_links import probe_site_links, site_links_problems, workflow_url_issues
from tests import test_content_role_gates as gates

workspace = gates.workspace  # fixture: a workspace with a signed-in user (gates._sign_in)
AD = WorkspaceRole.ADMIN
SITE = "https://mashandburn.example.com"
NEWSLETTER = {"kind": "webhook", "url": "https://hooks.example.test/newsletter", "body": {"link": "${entry.url}"}}


@fixture
def site(db_session, workspace):
    """A workspace with a site address and four types: Bench Note (no pattern), Article (pattern), Helper (internal,
    no pattern) and Fragment (not publishable, no pattern)."""
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.db.models.platform import Entries, EntryTypes

    gid = workspace.gid
    prefs = db_session.query(GroupPreferencesModel).filter_by(group_id=gid).first()
    if prefs is None:
        prefs = GroupPreferencesModel(session=db_session, group_id=gid)
        db_session.add(prefs)
    prefs.site_canonical_url = SITE

    def make(name, slug, pattern=None, caps=None):
        et = EntryTypes(session=db_session, group_id=gid, name=name, slug=slug, schema_json={}, page_url_pattern=pattern, capabilities_json=caps)
        db_session.add(et)
        return et

    note = make("Bench Note", "bench-note")
    article = make("Article", "article", "/articles/{slug}/")
    make("Helper", "helper", caps={"listed": False})
    make("Fragment", "fragment", caps={"publishable": False})
    db_session.flush()
    for et, slug in ((article, "first-post"), (note, "first-note")):
        db_session.add(Entries(session=db_session, group_id=gid, entry_type_id=et.id, title=slug, slug=slug, status="published"))
    db_session.commit()
    yield SimpleNamespace(gid=gid, uid=workspace.uid, workspace=workspace, session=db_session, prefs=prefs, note=note, article=article)
    db_session.rollback()


def _definition(*actions, conditions=None, target=None):
    return {
        "trigger": {"type": "manual"} if target else {"type": "event", "event": "entry_published"},
        "conditions": conditions or [],
        "actions": list(actions) or [NEWSLETTER],
        **({"target": target} if target else {}),
    }


def _pin(slug):
    return [{"field": "entry.entry_type", "op": "eq", "value": slug}]


def _messages(site, definition):
    return [i["message"] for i in workflow_url_issues(site.session, site.gid, definition)]


def _problems(site):
    return {(p["kind"], p.get("entryType")) for p in site_links_problems(site.session, site.gid)}


# ── the workflow warning ─────────────────────────────────────────────────────


def test_warns_when_the_type_has_no_page_url_pattern(site):
    [message] = _messages(site, _definition(conditions=_pin("bench-note")))
    assert message == "`${entry.url}` will be empty: Bench Note has no page URL pattern (Site links, in Settings › General)."


def test_warns_when_there_is_no_site_address(site):
    site.prefs.site_canonical_url = None
    site.session.commit()
    [message] = _messages(site, _definition(conditions=_pin("article")))
    assert message.startswith("`${entry.url}` will be a bare path, not a link: the workspace has no site address")


def test_a_full_url_pattern_needs_no_site_address(site):
    site.prefs.site_canonical_url = None
    site.article.page_url_pattern = "https://blog.example.com/{slug}"
    site.session.commit()
    assert _messages(site, _definition(conditions=_pin("article"))) == []


def test_no_warning_when_both_exist(site):
    assert _messages(site, _definition(conditions=_pin("article"))) == []


def test_no_warning_without_entry_url(site):
    assert _messages(site, _definition({"kind": "webhook", "url": "https://hooks.example.test", "body": {"t": "${entry.title}"}})) == []


def test_the_type_is_inferred_from_a_condition_or_the_target(site):
    assert _messages(site, _definition(conditions=_pin("article"))) == []
    assert "Bench Note" in _messages(site, _definition(conditions=_pin("bench-note")))[0]
    assert _messages(site, _definition(target={"entity": "entry", "query": {"entry_type": "article"}})) == []
    assert "Bench Note" in _messages(site, _definition(target={"entity": "entry", "query": {"entry_type": "bench-note"}}))[0]


def test_an_unpinned_workflow_checks_every_publishable_type(site):
    [message] = _messages(site, _definition())
    assert message == "`${entry.url}` will be empty for some entries: Bench Note has no page URL pattern (Site links, in Settings › General)."
    assert "Helper" not in message and "Fragment" not in message  # internal / unpublishable types never get a page


def test_a_condition_reading_entry_url_counts(site):
    definition = _definition({"kind": "webhook", "url": "https://hooks.example.test"}, conditions=[{"field": "entry.url", "op": "exists"}])
    assert _messages(site, definition)


def test_validate_route_carries_the_warning_without_blocking(site):
    client = gates._sign_in(site.workspace, AD)
    res = client.post("/api/automations/validate", json={"definition": _definition(conditions=_pin("bench-note"))})
    assert res.status_code == 200
    [issue] = [i for i in res.json()["issues"] if "entry.url" in i["message"]]
    assert issue["level"] == "warning" and "Bench Note" in issue["message"]


def test_a_dry_run_shows_it(site):
    client = gates._sign_in(site.workspace, AD)
    definition = _definition(target={"entity": "entry", "query": {"entry_type": "bench-note"}})
    row = client.post("/api/automations", json={"name": "Newsletter", "definition": definition})
    assert row.status_code == 201, row.text
    plan = client.post(f"/api/automations/{row.json()['id']}/run", params={"dry_run": "true"}).json()
    assert plan["status"] == "dry_run" and "Bench Note has no page URL pattern" in plan["warnings"][0]
    site.note.page_url_pattern = "/bench-notes/{slug}/"
    site.session.commit()
    again = client.post(f"/api/automations/{row.json()['id']}/run", params={"dry_run": "true"}).json()
    assert "warnings" not in again


def test_draft_workflow_reports_it(site):
    from marvin.db.models.users.workspace_members import WorkspaceMembers

    site.session.add(WorkspaceMembers(session=site.session, user_id=site.uid, group_id=site.gid, workspace_role=AD))
    site.session.commit()
    member = SimpleNamespace(group_id=site.gid, workspace_role=AD)
    user = SimpleNamespace(id=site.uid, admin=False, workspace_memberships=[member])
    ctx = SimpleNamespace(session=site.session, group_id=site.gid, user=user, provider=None, logger=None)
    out = json.loads(get_tool("draft_workflow").handler(ctx, {"name": "Newsletter", "definition": _definition(conditions=_pin("bench-note"))}))
    assert out["created"] is True and "Bench Note has no page URL pattern" in out["warnings"][0]


# ── the setup check ──────────────────────────────────────────────────────────


def test_the_check_lists_types_without_a_pattern_and_ignores_internal_ones(site):
    assert _problems(site) == {("no_page_pattern", "bench-note")}
    [problem] = site_links_problems(site.session, site.gid)
    assert problem["message"] == "Bench Note has no page URL pattern, so its entries have no link."
    assert problem["fix"]["path"] == f"/workspace/entry-types/{site.note.id}"


def test_the_check_lists_a_missing_site_address(site):
    site.prefs.site_canonical_url = ""
    site.session.commit()
    assert _problems(site) == {("no_site_address", None), ("no_page_pattern", "bench-note")}


def test_a_set_up_workspace_has_no_problems(site):
    site.note.page_url_pattern = "/bench-notes/{slug}/"
    site.session.commit()
    assert site_links_problems(site.session, site.gid) == []


def test_the_check_is_per_workspace(site, db_session):
    from marvin.db.models.groups import Groups

    other = Groups(session=db_session, name="sl-other", slug=f"sl-other-{uuid.uuid4().hex[:6]}")
    db_session.add(other)
    db_session.commit()
    try:
        assert ("no_page_pattern", "bench-note") not in {(p["kind"], p.get("entryType")) for p in site_links_problems(db_session, other.id)}
        client = gates._sign_in(site.workspace, AD)
        assert client.get(f"/api/groups/{other.id}/preferences/site-links").status_code == 403
    finally:
        db_session.query(Groups).filter(Groups.id == other.id).delete()
        db_session.commit()


def test_the_routes_and_the_tool_agree(site):
    client = gates._sign_in(site.workspace, AD)
    res = client.get(f"/api/groups/{site.gid}/preferences/site-links").json()
    assert res["ok"] is False and [(p["kind"], p["entryType"]) for p in res["problems"]] == [("no_page_pattern", "bench-note")]
    assert res["problems"][0]["fix"]["label"] == "Set a page URL pattern for Bench Note"
    ctx = SimpleNamespace(session=site.session, group_id=site.gid, user=None, provider=None, logger=None)
    assert json.loads(get_tool("check_site_links").handler(ctx, {}))["problems"][0]["entryType"] == "bench-note"
    assert get_tool("check_site_links").read_only


def test_probing_needs_an_admin(site):
    viewer = gates._sign_in(site.workspace, WorkspaceRole.VIEWER)
    assert viewer.post(f"/api/groups/{site.gid}/preferences/site-links/probe").status_code == 403


# ── the probe ────────────────────────────────────────────────────────────────


class _FakeHttp:
    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def get(self, url, *, timeout):
        self.asked.append((url, timeout))
        answer = self.answers[url]
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(status_code=answer)


def test_the_probe_reports_a_link_that_is_not_200(site):
    http = _FakeHttp({f"{SITE}/articles/first-post/": 404})
    [problem] = probe_site_links(site.session, site.gid, http)
    assert (problem["kind"], problem["entryType"], problem["url"]) == ("probe_failed", "article", f"{SITE}/articles/first-post/")
    assert problem["message"].startswith(f"Article: {SITE}/articles/first-post/ answered 404.")
    assert http.asked == [(f"{SITE}/articles/first-post/", 5)]  # one entry per type with a pattern; Bench Note has none


def test_the_probe_is_quiet_when_pages_answer(site):
    assert probe_site_links(site.session, site.gid, _FakeHttp({f"{SITE}/articles/first-post/": 200})) == []


def test_the_probe_reports_a_site_that_does_not_answer(site):
    problems = probe_site_links(site.session, site.gid, _FakeHttp({f"{SITE}/articles/first-post/": TimeoutError()}))
    assert "did not answer (TimeoutError)" in problems[0]["message"]


def test_the_probe_skips_without_a_site_address(site):
    site.prefs.site_canonical_url = None
    site.session.commit()
    assert probe_site_links(site.session, site.gid, _FakeHttp({})) == []


def test_the_probe_route_uses_the_guarded_client(site, monkeypatch):
    seen = {}

    def fake(session, group_id, http=None):
        seen["group"] = group_id
        return []

    monkeypatch.setattr("marvin.services.site_links.probe_site_links", fake)
    res = gates._sign_in(site.workspace, AD).post(f"/api/groups/{site.gid}/preferences/site-links/probe")
    assert res.json() == {"ok": True, "problems": []} and seen["group"] == site.gid


def test_probe_candidates_are_published_entries_only(site):
    from marvin.db.models.platform import Entries

    site.session.query(Entries).filter(Entries.group_id == site.gid).update({"status": "draft"})
    site.session.commit()
    assert probe_site_links(site.session, site.gid, _FakeHttp({})) == []
