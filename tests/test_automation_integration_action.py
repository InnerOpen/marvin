"""The `integration` workflow step: run a provider action with templated args, keep its result.

This is what lets a workflow store a provider's returned ids on an entry — Square's `create_listing`
result feeds a following `set_metadata` step via `$steps.<id>.output`.
"""

import uuid

import pytest
from pytest import fixture

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider, ProviderAction  # noqa: E402

from marvin.db.models.groups.groups import Groups  # noqa: E402
from marvin.db.models.groups.integrations import IntegrationModel  # noqa: E402
from marvin.services.automation.actions.base import AutomationActionError  # noqa: E402
from marvin.services.automation.actions.integration import run_integration_action  # noqa: E402
from marvin.services.automation.authz import ROLE_ADMIN, ROLE_EDITOR  # noqa: E402


class _FakeShop(IntegrationProvider):
    slug = "fake_shop"
    name = "Fake shop"
    actions = (
        ProviderAction(key="create_listing", label="Create listing"),
        ProviderAction(key="refund", label="Refund", requires_approval=True),
    )

    def __init__(self):
        self.calls: list[tuple[str, dict, object]] = []

    def run_action(self, key, args, ctx):
        self.calls.append((key, args, ctx))
        if args.get("fail"):
            raise ValueError("price must be positive")
        if args.get("refuse"):
            error = ValueError("the shop refused it")
            error.code = "blocked"  # a provider's stable reason, for on_failure steps
            raise error
        return {"checkout_url": f"https://pay.example/{args['slug']}", "variation_id": "VAR1"}


@fixture
def shop(monkeypatch):
    provider = _FakeShop()
    monkeypatch.setitem(INTEGRATION_REGISTRY, provider.slug, provider)
    monkeypatch.setattr("marvin.services.secrets.resolver.resolve_secret", lambda ref, gid=None: "tok")
    return provider


@fixture
def workspace(db_session):
    gid = uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"shop-{marker}", slug=f"shop-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    for slug, enabled in (("shop", True), ("off", False)):
        db_session.add(
            IntegrationModel(
                session=db_session,
                group_id=gid,
                provider="fake_shop",
                name=slug,
                slug=slug,
                enabled=enabled,
                config={"location_id": "L1"},
                secret_ref="INTEGRATION_SHOP",
            )
        )
    db_session.commit()
    yield gid
    db_session.rollback()
    db_session.query(IntegrationModel).filter(IntegrationModel.group_id == gid).delete()
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _run(db_session, gid, action, *, role=ROLE_ADMIN, dry_run=False):
    context = {"event": {"entry_id": "e1", "entry": {"slug": "weightless-hour", "title": "Weightless Hour"}}, "steps": {}, "depth": 0}
    return run_integration_action(db_session, gid, {"kind": "integration", **action}, context, authorizer_role=role, dry_run=dry_run)


def test_integration_step_returns_provider_result_with_templated_args(db_session, workspace, shop):
    out = _run(db_session, workspace, {"integration": "shop", "action": "create_listing", "args": {"slug": "${event.entry.slug}"}})

    assert out == {"checkout_url": "https://pay.example/weightless-hour", "variation_id": "VAR1"}
    key, args, ctx = shop.calls[0]
    assert (key, args) == ("create_listing", {"slug": "weightless-hour"})
    assert ctx.secret == "tok" and ctx.config == {"location_id": "L1"}


def test_integration_step_dry_run_resolves_args_without_calling(db_session, workspace, shop):
    out = _run(db_session, workspace, {"integration": "shop", "action": "create_listing", "args": {"slug": "${event.entry.slug}"}}, dry_run=True)

    assert out["dry_run"] and out["args"] == {"slug": "weightless-hour"}
    assert shop.calls == []


def test_integration_step_provider_error_fails_the_step(db_session, workspace, shop):
    with pytest.raises(AutomationActionError, match="price must be positive"):
        _run(db_session, workspace, {"integration": "shop", "action": "create_listing", "args": {"slug": "x", "fail": True}})


def test_integration_step_provider_error_without_code_is_unknown(db_session, workspace, shop):
    # Untagged failures are "unknown" — the code an error policy's catch-all (and SDK 0.5.0's default) uses.
    with pytest.raises(AutomationActionError) as raised:
        _run(db_session, workspace, {"integration": "shop", "action": "create_listing", "args": {"slug": "x", "fail": True}})

    assert raised.value.code == "unknown"


def test_integration_step_provider_error_code_reaches_the_step_error(db_session, workspace, shop):
    with pytest.raises(AutomationActionError, match="the shop refused it") as raised:
        _run(db_session, workspace, {"integration": "shop", "action": "create_listing", "args": {"slug": "x", "refuse": True}})

    assert raised.value.code == "blocked"


def test_integration_step_refuses_actions_that_require_approval(db_session, workspace, shop):
    with pytest.raises(AutomationActionError, match="requires approval"):
        _run(db_session, workspace, {"integration": "shop", "action": "refund"})
    assert shop.calls == []


@pytest.mark.parametrize(
    ("action", "message"),
    [
        ({"integration": "nope", "action": "create_listing"}, "not found"),
        ({"integration": "off", "action": "create_listing"}, "disabled"),
        ({"integration": "shop", "action": "teleport"}, "no action"),
    ],
)
def test_integration_step_unusable_target_fails(db_session, workspace, shop, action, message):
    with pytest.raises(AutomationActionError, match=message):
        _run(db_session, workspace, action)


def test_integration_step_needs_admin_role(db_session, workspace, shop):
    with pytest.raises(AutomationActionError):
        _run(db_session, workspace, {"integration": "shop", "action": "create_listing", "args": {"slug": "x"}}, role=ROLE_EDITOR)
    assert shop.calls == []


# --- a step that names a capability (notify) instead of an action ------------------------------------------------


class _FakeChat(IntegrationProvider):
    """Slack-shaped: its message action takes `text` (and a title), declares `notify`."""

    slug = "fake_chat"
    name = "Fake chat"
    actions = (
        ProviderAction(
            key="send_message",
            label="Send message",
            capability="notify",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}, "channel": {"type": "string"}}},
        ),
    )

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def run_action(self, key, args, ctx):
        self.calls.append((key, args))
        return {"sent": True}


@fixture
def chat(monkeypatch, db_session, workspace):
    provider = _FakeChat()
    monkeypatch.setitem(INTEGRATION_REGISTRY, provider.slug, provider)
    monkeypatch.setattr("marvin.services.secrets.resolver.resolve_secret", lambda ref, gid=None: "tok")
    db_session.add(IntegrationModel(session=db_session, group_id=workspace, provider="fake_chat", name="chat", slug="chat", enabled=True))
    db_session.commit()
    return provider


def test_a_notify_step_sends_through_whatever_message_action_the_integration_has(db_session, workspace, chat):
    out = _run(
        db_session,
        workspace,
        {"integration": "chat", "capability": "notify", "args": {"title": "Published", "body": "${event.entry.title} is live", "channel": "#news"}},
    )
    assert out == {"sent": True}
    assert chat.calls == [("send_message", {"channel": "#news", "text": "*Published*\nWeightless Hour is live"})]  # title over body, in `text`


def test_a_notify_step_on_an_integration_that_cannot_notify_says_so(db_session, workspace, shop):
    with pytest.raises(AutomationActionError, match="can't notify"):
        _run(db_session, workspace, {"integration": "shop", "capability": "notify", "args": {"body": "x"}})


def test_a_capability_is_what_the_library_matches_a_notify_recipe_against(db_session, workspace, chat):
    from marvin.services.automation import recipes
    from marvin.services.automation.authoring import workspace_refs

    refs = workspace_refs(db_session, workspace)
    assert next(i for i in refs.integrations if i["slug"] == "chat")["capabilities"] == ["notify"]
    item = recipes.entry("deployment-celebration")
    assert recipes.missing_prerequisites(item, refs) == []  # Slack-shaped is enough: no Apprise needed
    refs.integrations = [i for i in refs.integrations if i["slug"] != "chat"]
    assert recipes.missing_prerequisites(item, refs) == ["needs a connected integration that can notify (Slack or Apprise)"]
