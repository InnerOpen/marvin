"""Posting to social networks from a workflow: the `social.post` capability.

An integration step names `capability: "social.post"`; with no `integration` it posts to every connected network that
offers it. Posting is public, so a run must be past an Approval step (`_approved` in the run's context — the engine
sets it when it resumes a run after an approval; a dry run has `_approval_ahead` once it passed the step). The
providers here are fakes with a gated `post` action, shaped like the plugins' (text, images, alt, link, dry_run).
"""

import uuid
from datetime import UTC, datetime

import pytest
from pytest import fixture

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider, ProviderAction  # noqa: E402

from marvin.db.models.groups.groups import Groups  # noqa: E402
from marvin.db.models.groups.integrations import IntegrationModel  # noqa: E402
from marvin.db.models.platform import Assets  # noqa: E402
from marvin.db.models.users.users import Users  # noqa: E402
from marvin.services.automation.actions.base import AutomationActionError  # noqa: E402
from marvin.services.automation.actions.integration import run_integration_action  # noqa: E402
from marvin.services.automation.authoring import reference_issues, workspace_refs  # noqa: E402
from marvin.services.automation.authz import ROLE_ADMIN  # noqa: E402
from marvin.services.integrations.alert_routing import capabilities_of, capability_action  # noqa: E402

POST = {"kind": "integration", "capability": "social.post"}
CDN = "https://cdn.example/"


def _network(slug: str, limit: int, *, gated: bool = True):
    """A fake network: refuses a text over `limit` (like the plugins' `unsupported`), fails on "boom", and answers a
    dry run with what it would post."""

    class _Net(IntegrationProvider):
        name = f"Fake {slug}"
        actions = (
            ProviderAction(key="post", label="Post", capability="social.post", requires_approval=gated),
            ProviderAction(key="refund", label="Not social"),
        )

        def __init__(self):
            self.calls: list[dict] = []

        def run_action(self, key, args, ctx):
            self.calls.append(dict(args))
            if len(args["text"]) > limit:
                raise ValueError(f"{slug} takes at most {limit} characters")
            if "boom" in args["text"]:
                raise ValueError(f"{slug} is down")
            if args["dry_run"]:
                return {"posted": False, "network": slug, "would_post": {"text": args["text"], "images": args.get("images", [])}}
            return {"posted": True, "post_id": f"{slug}-1", "url": f"https://{slug}.example/p/1", "network": slug}

    _Net.slug = slug
    return _Net()


@fixture
def nets(monkeypatch):
    found = {"bluesky": _network("bluesky", 20), "mastodon": _network("mastodon", 500)}
    for slug, provider in found.items():
        monkeypatch.setitem(INTEGRATION_REGISTRY, slug, provider)
    monkeypatch.setattr("marvin.services.secrets.resolver.resolve_secret", lambda ref, gid=None: "tok")
    monkeypatch.setattr("marvin.services.storage.provider_factory.asset_public_url", lambda asset: f"{CDN}{asset.storage_key}")
    return found


@fixture
def ws(db_session, nets):
    """A workspace with two networks (named for their slugs, in reverse of the order they run), one switched off, and a user."""
    gid = uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"social-{marker}", slug=f"social-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    uid = uuid.uuid4()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid, group_id=gid, username=f"u-{marker}", email=f"u-{marker}@t.test", full_name="U", password="x",
            is_superuser=False, platform_role="NONE", auth_method="MARVIN",
        )
    )  # fmt: skip
    for slug, provider, enabled in (("zz-mastodon", "mastodon", True), ("aa-bluesky", "bluesky", True), ("old-mastodon", "mastodon", False)):
        db_session.add(IntegrationModel(session=db_session, group_id=gid, provider=provider, name=slug, slug=slug, enabled=enabled, config={}))
    db_session.commit()
    yield type("WS", (), {"gid": gid, "session": db_session, "uid": uid, "nets": nets})
    db_session.rollback()
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.query(Assets).filter(Assets.group_id == gid).delete()
    db_session.query(IntegrationModel).filter(IntegrationModel.group_id == gid).delete()
    purge_group_dependents(db_session, gid)  # what a test's run left behind: the workflow, its approval, wait and run rows
    db_session.execute(Users.__table__.delete().where(Users.id == uid))
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _asset(ws, name, *, mime="image/png", trashed=False, scope="library", **extra):
    slug = f"{name}-{uuid.uuid4().hex[:6]}"
    row = Assets(
        session=ws.session, group_id=ws.gid, slug=slug, name=name, original_filename=f"{name}.png", filename=f"{name}.png", extension="png",
        file_size=3, mime_type=mime, asset_type="image", checksum=uuid.uuid4().hex, storage_provider="local", storage_key=f"it/{slug}",
        uploaded_by=ws.uid, trashed_at=datetime.now(UTC) if trashed else None, scope=scope, **extra,
    )  # fmt: skip
    ws.session.add(row)
    ws.session.flush()
    return row


def _run(ws, step, *, approved=True, dry_run=False, context=None, role=ROLE_ADMIN):
    ctx = {
        "entry": {"title": "Weightless Hour — a long, drifting episode", "summary": "Floating.", "url": "https://e.example/w"},
        "steps": {},
        "depth": 0,
    }
    ctx |= {"_approved": True} if approved else {}
    ctx |= context or {}
    return run_integration_action(ws.session, ws.gid, {**POST, **step}, ctx, authorizer_role=role, dry_run=dry_run)


# ── routing: a gated action is allowed after approval, refused before it ─────────────────────────────────────────


def test_a_gated_social_action_counts_as_a_capability_and_routes_only_once_approved(nets):
    provider = nets["bluesky"]
    assert "social.post" in capabilities_of(provider)
    assert capability_action(provider, "social.post", {"text": "x"}) is None  # no approval: not routed
    assert capability_action(provider, "social.post", {"text": "x"}, approved=True) == ("post", {"text": "x"})


def test_other_gated_capabilities_stay_unroutable(nets):
    class _Images(IntegrationProvider):
        slug = "imgs"
        name = "Images"
        actions = (ProviderAction(key="generate", label="Generate", capability="image.generate", requires_approval=True),)

    provider = _Images()
    assert "image.generate" not in capabilities_of(provider)
    assert capability_action(provider, "image.generate", {}, approved=True) is None


def test_an_action_declaring_social_post_is_gated_even_if_the_plugin_forgot_to_say_so(monkeypatch, ws):
    monkeypatch.setitem(INTEGRATION_REGISTRY, "bluesky", _network("bluesky", 500, gated=False))
    with pytest.raises(AutomationActionError, match="needs a person's approval"):
        _run(ws, {"integration": "aa-bluesky", "args": {"text": "hi"}}, approved=False)


def test_a_run_not_past_an_approval_posts_nowhere(ws):
    for step in ({"args": {"text": "hi"}}, {"integration": "aa-bluesky", "args": {"text": "hi"}}):
        with pytest.raises(AutomationActionError, match="needs a person's approval.*put an Approval step before it"):
            _run(ws, step, approved=False)
    assert all(not p.calls for p in ws.nets.values())


def test_a_dry_run_needs_an_approval_step_ahead_too(ws):
    with pytest.raises(AutomationActionError, match="Approval step"):
        _run(ws, {"args": {"text": "hi"}}, approved=False, dry_run=True)
    out = _run(ws, {"args": {"text": "hi"}}, approved=False, dry_run=True, context={"_approval_ahead": True})
    assert out["dry_run"] is True and out["posted_count"] == 0


def test_a_person_must_be_an_admin_to_post(ws):
    from marvin.services.automation.authz import ROLE_EDITOR

    with pytest.raises(AutomationActionError):
        _run(ws, {"args": {"text": "hi"}}, role=ROLE_EDITOR)


# ── routing at save ──────────────────────────────────────────────────────────────────────────────────────────────


def _issues(ws, steps) -> list[tuple[str, str]]:
    definition = {"trigger": {"type": "manual"}, "actions": steps}
    return [(i["path"], i["message"]) for i in reference_issues(ws.session, ws.gid, definition)]


APPROVAL = {"kind": "approval", "message": "Post it?"}


def test_save_refuses_a_social_step_without_an_approval_step_before_it(ws):
    for step in ({**POST, "args": {"text": "x"}}, {**POST, "integration": "aa-bluesky", "args": {"text": "x"}}):
        [(path, message)] = _issues(ws, [step])
        assert path == "actions[0].capability" and "needs a person's approval: put an Approval step before it" in message
        [(path, message)] = _issues(ws, [step, APPROVAL])  # an approval after it is no help
        assert "Approval step before it" in message


def test_save_accepts_a_social_step_after_an_approval_step_everywhere_or_named(ws):
    assert _issues(ws, [APPROVAL, {**POST, "args": {"text": "x"}}]) == []
    assert _issues(ws, [APPROVAL, {**POST, "integration": "zz-mastodon", "args": {"text": "x"}}]) == []
    assert _issues(ws, [APPROVAL, {"kind": "repeat", "for_each": [1], "steps": [{**POST, "args": {"text": "x"}}]}]) == []


def test_save_refuses_a_named_gated_action_without_approval_and_accepts_it_after(ws):
    step = {"kind": "integration", "integration": "aa-bluesky", "action": "post", "args": {"text": "x"}}
    assert "needs a person's approval" in _issues(ws, [step])[0][1]
    assert _issues(ws, [APPROVAL, step]) == []


def test_save_refuses_every_network_when_none_is_connected(db_session, nets):
    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"empty-{gid.hex[:8]}", slug=f"empty-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.commit()
    try:
        ws = type("WS", (), {"gid": gid, "session": db_session})
        [(path, message)] = _issues(ws, [APPROVAL, {**POST, "args": {"text": "x"}}])
        assert path == "actions[1].capability" and "No connected integration can social.post" in message
    finally:
        db_session.rollback()
        db_session.query(Groups).filter(Groups.id == gid).delete()
        db_session.commit()


def test_a_recipe_prerequisite_counts_a_gated_social_post_action_as_provided(ws):
    from marvin.services.automation import recipes

    refs = workspace_refs(ws.session, ws.gid)
    assert next(i for i in refs.integrations if i["slug"] == "aa-bluesky")["capabilities"] == ["social.post"]
    item = {"prerequisites": {"integrations": [{"capability": "social.post", "examples": "Instagram, Bluesky or Mastodon"}]}}
    assert recipes.missing_prerequisites(item, refs) == []
    refs.integrations = []
    assert recipes.missing_prerequisites(item, refs) == ["needs a connected integration that can social.post (Instagram, Bluesky or Mastodon)"]


def test_the_schema_lets_only_a_capability_step_leave_the_integration_out():
    from pydantic import ValidationError

    from marvin.schemas.group.automation_definition import IntegrationAction

    assert IntegrationAction.model_validate({"kind": "integration", "capability": "social.post"}).integration is None
    with pytest.raises(ValidationError, match="only a `capability` step may leave it out"):
        IntegrationAction.model_validate({"kind": "integration", "action": "post"})
    with pytest.raises(ValidationError):
        IntegrationAction.model_validate({"kind": "integration"})


# ── fan-out ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_step_with_no_integration_posts_to_every_enabled_network_in_slug_order(ws):
    out = _run(ws, {"args": {"text": "Hello"}})

    assert [r["integration"] for r in out["results"]] == ["aa-bluesky", "zz-mastodon"]  # not the switched-off one
    assert out["results"][0] == {
        "integration": "aa-bluesky", "network": "bluesky", "posted": True,
        "url": "https://bluesky.example/p/1", "post_id": "bluesky-1", "error": None,
    }  # fmt: skip
    assert (out["posted_count"], out["failed_count"]) == (2, 0)
    assert [len(p.calls) for p in ws.nets.values()] == [1, 1]
    assert ws.nets["bluesky"].calls[0]["dry_run"] is False  # always passed, never left unset


def test_a_failure_on_one_network_does_not_stop_the_others_and_fails_the_step_at_the_end(ws):
    with pytest.raises(AutomationActionError) as raised:
        _run(ws, {"args": {"text": "A text well over the Bluesky limit"}})

    assert "1 of 2 failed to social.post" in str(raised.value) and "aa-bluesky: bluesky.post failed: bluesky takes at most 20 characters" in str(
        raised.value
    )
    assert "(posted to zz-mastodon)" in str(raised.value)
    assert len(ws.nets["mastodon"].calls) == 1  # went on after bluesky refused


def test_fail_on_error_false_returns_the_failure_as_output(ws):
    out = _run(ws, {"args": {"text": "A text well over the Bluesky limit"}, "fail_on_error": False})

    assert (out["posted_count"], out["failed_count"]) == (1, 1)
    bluesky, mastodon = out["results"]
    assert bluesky["posted"] is False and bluesky["error"].endswith("takes at most 20 characters") and bluesky["url"] is None
    assert mastodon["posted"] is True and mastodon["error"] is None


def test_every_network_failing_names_each_and_posts_nothing(ws):
    with pytest.raises(AutomationActionError, match=r"2 of 2 failed .*bluesky is down.*mastodon is down.*nothing was posted"):
        _run(ws, {"args": {"text": "boom"}})


def test_an_integration_named_posts_to_that_one_only_and_its_failure_is_the_steps(ws):
    out = _run(ws, {"integration": "zz-mastodon", "args": {"text": "Hello"}})
    assert out["url"] == "https://mastodon.example/p/1" and "results" not in out
    assert ws.nets["bluesky"].calls == []
    with pytest.raises(AutomationActionError, match="mastodon is down"):
        _run(ws, {"integration": "zz-mastodon", "args": {"text": "boom"}})


def test_an_idempotency_key_makes_a_rerun_post_only_where_it_has_not(ws):
    step = {"args": {"text": "Hello"}, "idempotency_key": "share-1", "fail_on_error": False}
    first = _run(ws, {**step, "args": {"text": "A text well over the Bluesky limit"}}, context={"_step": {"workflow": "w"}})
    assert [r["posted"] for r in first["results"]] == [False, True]

    second = _run(ws, step, context={"_step": {"workflow": "w"}})
    assert [r["posted"] for r in second["results"]] == [True, True]
    assert second["results"][1].get("duplicate") is True  # mastodon had it already: nothing was sent again
    assert len(ws.nets["mastodon"].calls) == 1 and len(ws.nets["bluesky"].calls) == 2


def test_no_connected_network_is_a_clear_error(ws):
    ws.session.query(IntegrationModel).filter(IntegrationModel.group_id == ws.gid).update({"enabled": False})
    with pytest.raises(AutomationActionError, match="no connected integration can social.post"):
        _run(ws, {"args": {"text": "hi"}})


# ── per_network ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_per_network_overrides_the_arguments_for_a_network_by_name_or_slug_with_templates_and_filters(ws):
    out = _run(
        ws,
        {
            "args": {"text": "${entry.summary} ${entry.url}", "link": "${entry.url}"},
            "per_network": {"Bluesky": {"text": "${entry.title|truncate:15}"}, "zz-mastodon": {"link": "https://m.example/x"}},
        },
    )

    assert out["posted_count"] == 2
    bluesky, mastodon = ws.nets["bluesky"].calls[0], ws.nets["mastodon"].calls[0]
    assert bluesky["text"].startswith("Weightless") and len(bluesky["text"]) <= 15 and bluesky["link"] == "https://e.example/w"
    assert mastodon["text"] == "Floating. https://e.example/w" and mastodon["link"] == "https://m.example/x"


def test_an_integration_slug_wins_over_the_network_name(ws):
    _run(ws, {"args": {"text": "Hi"}, "per_network": {"mastodon": {"text": "by network"}, "zz-mastodon": {"text": "by slug"}}})
    assert ws.nets["mastodon"].calls[0]["text"] == "by slug"


def test_a_per_network_entry_must_be_an_object(ws):
    with pytest.raises(AutomationActionError, match="must be an object"):
        _run(ws, {"integration": "zz-mastodon", "args": {"text": "Hi"}, "per_network": {"mastodon": "short"}})


def test_text_is_required_for_a_network(ws):
    with pytest.raises(AutomationActionError, match="social.post needs `text`"):
        _run(ws, {"integration": "zz-mastodon", "args": {"text": ""}})


# ── images: assets become public URLs ────────────────────────────────────────────────────────────────────────────


def test_an_asset_id_or_slug_becomes_its_public_url_and_a_plain_https_url_passes_through(ws):
    one = _asset(ws, "cover", alt_text="A cover")
    two = _asset(ws, "back")
    _run(ws, {"integration": "zz-mastodon", "args": {"text": "Hi", "images": [str(one.id), two.slug, "https://img.example/x.png"]}})

    sent = ws.nets["mastodon"].calls[0]
    assert sent["images"] == [f"{CDN}{one.storage_key}", f"{CDN}{two.storage_key}", "https://img.example/x.png"]
    assert sent["alt"] == ["A cover", "", ""]  # the assets' own alt text, when the step gives none


def test_alt_the_step_gives_is_not_replaced(ws):
    one = _asset(ws, "cover", alt_text="A cover")
    _run(ws, {"integration": "zz-mastodon", "args": {"text": "Hi", "images": [one.slug], "alt": ["Mine"]}})
    assert ws.nets["mastodon"].calls[0]["alt"] == ["Mine"]


def test_images_may_be_a_templated_list_of_rows_or_one_template(ws):
    one, two = _asset(ws, "cover"), _asset(ws, "back")
    rows = [{"id": str(one.id), "name": "cover"}, {"entry_type": "article", "title": "No picture", "image": None}, {"asset": {"id": str(two.id)}}]
    _run(
        ws,
        {"integration": "zz-mastodon", "args": {"text": "Hi", "images": "${steps.pics.output.rows}"}},
        context={"steps": {"pics": {"output": {"rows": rows}}}},
    )
    assert ws.nets["mastodon"].calls[0]["images"] == [f"{CDN}{one.storage_key}", f"{CDN}{two.storage_key}"]  # the entry with no picture is left out

    _run(
        ws,
        {"integration": "zz-mastodon", "args": {"text": "Hi", "images": "${steps.pic.output.asset.id}"}},
        context={"steps": {"pic": {"output": {"asset": {"id": str(one.id)}}}}},
    )
    assert ws.nets["mastodon"].calls[1]["images"] == [f"{CDN}{one.storage_key}"]


def test_per_network_images_are_resolved_too(ws):
    one = _asset(ws, "cover")
    _run(ws, {"args": {"text": "Hi"}, "per_network": {"mastodon": {"images": [one.slug]}}})
    assert ws.nets["bluesky"].calls[0]["images"] == [] and ws.nets["mastodon"].calls[0]["images"] == [f"{CDN}{one.storage_key}"]


@pytest.mark.parametrize(
    ("make", "wording"),
    [
        (lambda ws: "no-such-asset", "no asset “no-such-asset” in this workspace"),
        (lambda ws: _asset(ws, "gone", trashed=True).slug, "is in the Trash"),
        (lambda ws: _asset(ws, "secret", scope="ask").slug, "is private"),
        (lambda ws: _asset(ws, "doc", mime="application/pdf").slug, "isn't a picture"),
        (lambda ws: "http://img.example/x.png", "must be a public https:// address"),
        (lambda ws: "/assets/it/x.png", "must be a public https:// address"),
    ],
)
def test_a_missing_private_or_unusable_picture_is_refused_by_name_and_nothing_is_posted(ws, make, wording):
    with pytest.raises(AutomationActionError, match=wording):
        _run(ws, {"args": {"text": "Hi", "images": [make(ws)]}})
    assert all(not p.calls for p in ws.nets.values())


def test_an_asset_not_served_over_https_is_refused(ws, monkeypatch):
    one = _asset(ws, "cover")
    monkeypatch.setattr("marvin.services.storage.provider_factory.asset_public_url", lambda asset: f"http://localhost:9000/{asset.storage_key}")
    with pytest.raises(AutomationActionError, match="isn't a public https:// address"):
        _run(ws, {"integration": "zz-mastodon", "args": {"text": "Hi", "images": [one.slug]}})


def test_more_than_ten_pictures_is_refused(ws):
    with pytest.raises(AutomationActionError, match="at most 10 pictures"):
        _run(ws, {"integration": "zz-mastodon", "args": {"text": "Hi", "images": [f"https://img.example/{n}.png" for n in range(11)]}})


# ── dry run ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_dry_run_collects_each_plugins_answer_and_sends_nothing(ws):
    one = _asset(ws, "cover")
    out = _run(ws, {"args": {"text": "Hello", "images": [one.slug]}}, dry_run=True, approved=False, context={"_approval_ahead": True})

    assert out["dry_run"] is True and (out["posted_count"], out["failed_count"]) == (0, 0)
    bluesky, mastodon = out["results"]
    assert bluesky["would_post"] == {"text": "Hello", "images": [f"{CDN}{one.storage_key}"]} and bluesky["posted"] is False and bluesky["url"] is None
    assert mastodon["network"] == "mastodon" and mastodon["would_post"]["text"] == "Hello"
    assert all(c["dry_run"] is True for p in ws.nets.values() for c in p.calls)  # the plugin was asked to send nothing


def test_a_dry_run_shows_a_networks_refusal_without_failing_the_preview(ws):
    out = _run(ws, {"args": {"text": "A text well over the Bluesky limit"}}, dry_run=True, approved=False, context={"_approval_ahead": True})
    assert out["failed_count"] == 1 and out["results"][0]["error"].endswith("takes at most 20 characters") and out["results"][1]["error"] is None


def test_a_named_dry_run_shows_the_plugins_answer(ws):
    out = _run(ws, {"integration": "zz-mastodon", "args": {"text": "Hello"}}, dry_run=True, approved=False, context={"_approval_ahead": True})
    assert out["dry_run"] is True and out["would_post"]["text"] == "Hello" and out["args"]["dry_run"] is True


def test_a_dry_run_typed_into_the_arguments_does_not_turn_a_real_post_into_one(ws):
    _run(ws, {"integration": "zz-mastodon", "args": {"text": "Hello", "dry_run": True}})
    assert ws.nets["mastodon"].calls[0]["dry_run"] is False


def test_the_authoring_guide_has_a_social_section_and_the_index_points_to_it(ws):
    from marvin.services.automation.authoring import authoring_guide

    assert "social" in authoring_guide(ws.session, ws.gid)["sections"]
    note = authoring_guide(ws.session, ws.gid, "social")["social"]["note"]
    assert "Approval step must come before it" in note and "per_network" in note and "every connected network" in note


# ── approved, then a Wait: still approved when it goes on ────────────────────


def test_an_approved_run_that_waits_still_posts_when_its_time_comes(ws):
    """Approve now, post at 9 tomorrow: the approval is kept in the wait's snapshot, so the post after the Wait runs."""
    from datetime import timedelta

    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.services.automation import approvals, waits
    from marvin.services.automation.authz import ROLE_OWNER
    from marvin.services.automation.engine import run_automation_now
    from marvin.services.automation.recorder import ExecutionRecorder

    row = WorkspaceAutomationModel(
        session=ws.session, group_id=ws.gid, name="Later post", slug=f"later-post-{uuid.uuid4().hex[:6]}", enabled=True,
        definition={"trigger": {"type": "manual"}, "actions": [
            {"kind": "approval", "id": "ok", "message": "Post it?"},
            {"kind": "wait", "for": "1h"},
            {**POST, "id": "post", "args": {"text": "Open studio"}},
        ]},
    )  # fmt: skip
    ws.session.add(row)
    ws.session.commit()
    run_automation_now(ws.session, ws.gid, row, user_id=ws.uid, recorder=ExecutionRecorder(ws.session, ws.gid))
    (waiting,) = approvals.pending(ws.session, ws.gid, ROLE_OWNER)
    approvals.decide(ws.session, ws.gid, waiting.id, "approve", user_id=ws.uid, role=ROLE_OWNER)
    assert ws.nets["bluesky"].calls == []  # parked at the Wait
    assert waits.resume_due(ws.session, now_=waits.now() + timedelta(hours=2)) == 1
    assert [c["text"] for c in ws.nets["bluesky"].calls] == ["Open studio"]
    assert [c["dry_run"] for c in ws.nets["mastodon"].calls] == [False]
