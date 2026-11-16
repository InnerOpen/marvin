"""A paid step's likely cost on the approval that guards it (services/integrations/estimate.py): read from this workspace's own
earlier calls of the same kind, never guessed; "cost unknown" when there is nothing to go by.

The case: a sound effect, a voice line and a picture, each made by a paid action after an approval."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider, ProviderAction

from marvin.services.integrations.estimate import approval_estimate, combine
from tests.test_workflow_approvals import _install, _published, _waiting  # noqa: F401
from tests.test_workflow_library import _entry_doc, _fire, ws  # noqa: F401 — the fixture


class _Studio(IntegrationProvider):
    slug = "fakestudio"
    name = "Fake Studio"
    actions = (
        ProviderAction(key="sound_effect", label="Sound", cost_hint="paid"),
        ProviderAction(key="speak", label="Speak", cost_hint="paid"),
        ProviderAction(key="picture", label="Picture", cost_hint="paid", requires_approval=True),
        ProviderAction(key="voices", label="Voices", cost_hint="free"),
    )

    def run_action(self, key, args, ctx):
        return {}


@pytest.fixture
def studio(ws, monkeypatch):  # noqa: F811
    from marvin.db.models.groups.integrations import IntegrationModel

    monkeypatch.setitem(INTEGRATION_REGISTRY, "fakestudio", _Studio())
    row = IntegrationModel(session=ws.session, group_id=ws.gid, provider="fakestudio", name="Studio", slug="studio", enabled=True, config={})
    ws.session.add(row)
    ws.session.commit()
    yield row
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    ws.session.query(AIExecutionModel).filter(AIExecutionModel.group_id == ws.gid).delete(synchronize_session=False)
    ws.session.commit()


def _earlier(ws, studio, key, *, meta, args=None, out=None, usd=None, minutes=1):  # noqa: F811
    """One earlier call, as the integration step records it (services/integrations/usage_log.py)."""
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    ws.session.add(
        AIExecutionModel(
            session=ws.session,
            group_id=ws.gid,
            operation_slug=f"fakestudio.{key}",
            provider_type="fakestudio",
            model_id="m1",
            status="completed",
            trigger_type="integration",
            estimated_cost_usd=usd,
            input_json={"args": args or {}},
            output_json=out or {},
            metadata_json={"integration": "studio", "integration_id": str(studio.id), "unit": "calls", "units": 1, "multiplier": 1.0, **meta},
            created_at=datetime.now(UTC) - timedelta(minutes=minutes),
        )
    )
    ws.session.commit()


def _asked(ws, key, args, *, title="Onions", extra=None):  # noqa: F811
    steps = [
        {"kind": "approval", "id": "spend", "message": "Make it?", "fields": [{"name": "prompt", "value": "a knife on a board"}]},
        {"kind": "integration", "id": "make", "integration": "studio", "action": key, "args": args},
        *(extra or []),
    ]
    _install(ws, {"trigger": {"type": "event", "event": "entry_published"}, "actions": steps})
    article = _published(ws, f"{title} {uuid.uuid4().hex[:4]}")
    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry")
    return _waiting(ws)


def test_nothing_made_before_is_cost_unknown_never_a_guess(ws, studio):  # noqa: F811
    estimate = approval_estimate(ws.session, _asked(ws, "sound_effect", {"text": "${steps.spend.output.fields.prompt}"}))

    (item,) = estimate["items"]
    assert item["unknown"] is True and "cost unknown" in estimate["text"] and "total" not in estimate


def test_a_sound_is_estimated_by_its_seconds_from_what_earlier_sounds_cost_per_second(ws, studio):  # noqa: F811
    for credits, seconds in ((200, 2.0), (500, 5.0), (300, 3.0)):  # 100 credits a second, as the provider measured them
        _earlier(ws, studio, "sound_effect", meta={"credits": credits}, out={"duration_seconds": seconds})

    estimate = approval_estimate(ws.session, _asked(ws, "sound_effect", {"text": "x", "duration_seconds": 4}))

    assert estimate["total"] == {"amount": 400, "unit": "Fake Studio credits"}
    assert estimate["text"] == "About 400 Fake Studio credits (for 4 seconds, going by the last 3 like it)"


def test_a_sound_with_no_length_asked_goes_by_the_typical_call(ws, studio):  # noqa: F811
    for credits in (100, 300, 200):
        _earlier(ws, studio, "sound_effect", meta={"credits": credits}, out={"duration_seconds": 2.0})

    estimate = approval_estimate(ws.session, _asked(ws, "sound_effect", {"text": "x"}))

    assert estimate["total"]["amount"] == 200 and "a call" in estimate["text"]


def test_a_voice_line_is_estimated_by_its_characters_at_the_models_rate(ws, studio):  # noqa: F811
    # 100 characters at a 0.5 multiplier: half a credit a character (not measured: units times the multiplier, as the tally counts)
    _earlier(ws, studio, "speak", meta={"unit": "characters", "units": 100, "multiplier": 0.5})

    estimate = approval_estimate(ws.session, _asked(ws, "speak", {"text": "${steps.spend.output.fields.prompt}"}))

    assert estimate["total"]["amount"] == 9  # "a knife on a board": 18 characters at 0.5
    assert "for these 18 characters" in estimate["text"] and "the last call like it" in estimate["text"]


def test_a_picture_is_priced_from_calls_of_the_same_size_only(ws, studio):  # noqa: F811
    _earlier(ws, studio, "picture", meta={}, args={"size": "1024x1536"}, usd=0.25)
    _earlier(ws, studio, "picture", meta={}, args={"size": "1024x1024"}, usd=0.04)
    _earlier(ws, studio, "picture", meta={}, args={"size": "1024x1024"}, usd=0.06)

    estimate = approval_estimate(ws.session, _asked(ws, "picture", {"prompt": "x", "size": "1024x1024"}))

    assert estimate["total"] == {"amount": 0.05, "unit": "USD"} and estimate["text"].startswith("About $0.05 (a call")


def test_another_workspaces_or_integrations_calls_dont_count(ws, studio):  # noqa: F811
    from marvin.db.models.groups.integrations import IntegrationModel

    other = IntegrationModel(session=ws.session, group_id=ws.gid, provider="fakestudio", name="Other", slug="other", enabled=True, config={})
    ws.session.add(other)
    ws.session.commit()
    _earlier(ws, other, "sound_effect", meta={"credits": 999})

    assert approval_estimate(ws.session, _asked(ws, "sound_effect", {"text": "x"}))["items"][0]["unknown"] is True


def test_a_free_step_says_nothing(ws, studio):  # noqa: F811
    assert approval_estimate(ws.session, _asked(ws, "voices", {})) is None


def test_a_branch_the_run_would_not_take_says_nothing(ws, studio):  # noqa: F811
    skipped = [
        {
            "kind": "integration",
            "id": "x",
            "integration": "studio",
            "action": "sound_effect",
            "args": {},
            "when": {"field": "entry.title", "op": "eq", "value": "never"},
        }
    ]

    assert approval_estimate(ws.session, _asked(ws, "voices", {}, extra=skipped)) is None


def test_two_paid_steps_add_up_when_they_share_a_unit_and_are_both_known():
    a = {"amount": 100, "unit": "X credits", "text": "About 100 X credits"}
    b = {"amount": 50, "unit": "X credits", "text": "About 50 X credits"}
    assert combine([a, b])["text"] == "About 150 X credits in all"
    unknown = {"unknown": True, "text": "X: cost unknown"}
    mixed = combine([a, unknown])
    assert "total" not in mixed and mixed["text"] == "About 100 X credits · X: cost unknown"


def test_the_card_carries_the_estimate(ws, studio):  # noqa: F811
    from marvin.routes.automations.automations_controller import _approval_read

    _earlier(ws, studio, "sound_effect", meta={"credits": 120})
    card = _approval_read(ws.session, _asked(ws, "sound_effect", {"text": "x"}))

    assert card.estimate.total.amount == 120 and card.estimate.items[0].calls == 1


def test_an_approval_asked_instead_of_another_is_passed_over(ws, studio):  # noqa: F811
    """An actor's sheet: a person's spend, then an animal's (asked only for an animal), then the paid step for each."""
    _earlier(ws, studio, "sound_effect", meta={"credits": 70})
    animal = {"kind": "approval", "id": "spend_animal", "message": "An animal?", "when": {"field": "entry.title", "op": "eq", "value": "never"}}

    estimate = approval_estimate(
        ws.session,
        _asked(ws, "voices", {}, extra=[animal, {"kind": "integration", "id": "fx", "integration": "studio", "action": "sound_effect", "args": {}}]),
    )

    assert estimate["total"]["amount"] == 70
