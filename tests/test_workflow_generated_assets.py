"""Images an integration step returns are kept as assets — the run carries references, never the image data.

A fake `image.generate` provider answers with base64 or a URL (fetched through the SSRF-guarded client, which the test
stubs at the network edge — and which really refuses a private host). The kept asset records how it was made; the
step's output and the run's snapshot stay small, so a run can wait for approval after generating and resume.
"""

# ruff: noqa: F811 — `ws` is a fixture, not a redefinition
import base64
import io
import json

import pytest
from PIL import Image

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider, ProviderAction  # noqa: E402

from marvin.db.models.groups.integrations import IntegrationModel  # noqa: E402
from tests.test_workflow_authoring import workspace, ws  # noqa: E402, F401 — fixtures
from tests.test_workflow_media import _entry, _fire, _last_run, _workflow, media  # noqa: E402, F401 — fixtures


def _picture(color=(30, 120, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(out, format="PNG")
    return out.getvalue()


PICTURE_B64 = base64.b64encode(_picture()).decode()


class _Painter(IntegrationProvider):
    slug = "wf_painter"
    name = "Painter"
    actions = (
        ProviderAction(key="paint", label="Paint", capability="image.generate", input_schema={"properties": {"prompt": {"type": "string"}}}),
        ProviderAction(
            key="paint_link", label="Paint (link)", capability="image.generate", input_schema={"properties": {"prompt": {"type": "string"}}}
        ),
        ProviderAction(key="touch_up", label="Touch up", capability="image.edit", input_schema={"properties": {"prompt": {"type": "string"}}}),
        ProviderAction(key="paid_paint", label="Paint (paid)", capability="image.generate", requires_approval=True),
        ProviderAction(key="list_it", label="List it", input_schema={"properties": {"title": {"type": "string"}}}),
    )

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.link = "https://images.example/out.png"

    def run_action(self, key, args, ctx):
        self.calls.append((key, args))
        usage = {"model": "paint-1", "total_tokens": 12}
        if key in ("paint", "paid_paint"):
            return {"images": [{"image_b64": PICTURE_B64}, {"image_b64": PICTURE_B64}], "usage": usage}
        if key == "paint_link":
            return {"images": [{"url": self.link}], "usage": usage}
        if key == "touch_up":
            return {"image_b64": PICTURE_B64, "usage": usage}
        return {"url": "https://shop.example/item/1", "id": "item-1"}


@pytest.fixture
def painter(media, monkeypatch):
    provider = _Painter()
    monkeypatch.setitem(INTEGRATION_REGISTRY, _Painter.slug, provider)
    monkeypatch.setattr("marvin.services.secrets.resolver.resolve_secret", lambda ref, gid=None: "tok")
    media.session.add(
        IntegrationModel(session=media.session, group_id=media.gid, provider=_Painter.slug, name="Painter", slug="painter", enabled=True)
    )
    media.session.commit()
    media.painter = provider
    return media


def _kept(ws):
    from marvin.db.models.platform.assets import Assets

    rows = ws.session.query(Assets).filter(Assets.group_id == ws.gid).all()
    return [a for a in rows if str((a.metadata_json or {}).get("derivation", "")).startswith("generated:")]


ON_PUBLISH = {"type": "event", "event": "entry_published"}


def _publish(ws, entry, correlation_id="corr-1"):
    _fire(ws, "entry_published", {"entry_id": str(entry.id)}, entity=entry.id, entity_type="entry", correlation_id=correlation_id)


def test_base64_images_become_assets_and_the_run_keeps_references(painter):
    article = _entry(painter, "Harbour")
    _workflow(
        painter,
        {
            "trigger": ON_PUBLISH,
            "actions": [
                {"kind": "integration", "id": "art", "integration": "painter", "action": "paint", "args": {"prompt": "A harbour at ${entry.title}"}}
            ],
        },
    )

    _publish(painter, article)

    first, second = sorted(_kept(painter), key=lambda a: a.name)
    assert (first.name, second.name) == ("Media Wf — Harbour (1)", "Media Wf — Harbour (2)")
    meta = first.metadata_json
    assert meta["generated_by"] == "wf_painter.paint" and meta["prompt"] == "A harbour at Harbour" and meta["model"] == "paint-1"
    assert meta["made_for_entry"] == str(article.id) and meta["workflow_slug"] == "media-wf" and "derived_from" not in meta
    assert (first.width, first.height, first.mime_type) == (64, 48, "image/png")
    output = _last_run(painter).actions[0].output_snapshot
    assert {img["asset"]["id"] for img in output["images"]} == {str(first.id), str(second.id)}
    assert "image_b64" not in json.dumps(output) and len(json.dumps(output)) < 4096
    assert output["usage"]["model"] == "paint-1"


def test_the_same_event_twice_keeps_one_set(painter):
    article = _entry(painter)
    _workflow(painter, {"trigger": ON_PUBLISH, "actions": [{"kind": "integration", "integration": "painter", "action": "touch_up", "args": {}}]})

    _publish(painter, article)
    _publish(painter, article)  # same correlation id: a redelivery
    assert len(_kept(painter)) == 1
    _publish(painter, article, correlation_id="corr-2")  # a new event: a new picture
    assert len(_kept(painter)) == 2
    assert set(_last_run(painter).actions[0].output_snapshot) == {"asset", "usage"}  # image.edit's top-level shape


def test_a_url_is_fetched_through_the_guarded_client(painter, monkeypatch):
    from marvin.services.integrations.http_client import MarvinHttpHelper, Response

    fetched = []

    def get(self, url, **kw):
        fetched.append((url, self._max_bytes))
        return Response(status_code=200, headers={}, content=_picture((200, 10, 10)))

    monkeypatch.setattr(MarvinHttpHelper, "get", get)
    article = _entry(painter)
    _workflow(
        painter,
        {"trigger": ON_PUBLISH, "actions": [{"kind": "integration", "integration": "painter", "action": "paint_link", "args": {"name": "Red"}}]},
    )

    _publish(painter, article)

    (red,) = _kept(painter)
    assert red.name == "Red" and fetched == [("https://images.example/out.png", 20 * 1024 * 1024)]


def test_a_url_on_a_private_host_is_refused(painter):
    painter.painter.link = "http://127.0.0.1:8080/secret.png"
    article = _entry(painter)
    _workflow(painter, {"trigger": ON_PUBLISH, "actions": [{"kind": "integration", "integration": "painter", "action": "paint_link", "args": {}}]})

    _publish(painter, article)

    run = _last_run(painter)
    assert run.status == "failed" and "can't be kept" in run.actions[0].error and "non-public host" in run.actions[0].error
    assert _kept(painter) == []


def test_other_actions_urls_are_left_alone(painter):
    article = _entry(painter)
    _workflow(
        painter, {"trigger": ON_PUBLISH, "actions": [{"kind": "integration", "integration": "painter", "action": "list_it", "args": {"title": "x"}}]}
    )

    _publish(painter, article)

    assert _last_run(painter).actions[0].output_snapshot == {"url": "https://shop.example/item/1", "id": "item-1"} and _kept(painter) == []


def test_attach_as_links_the_pictures_to_the_entry(painter):
    from marvin.db.models.platform.entry_assets import EntryAssets

    article = _entry(painter)
    _workflow(
        painter,
        {
            "trigger": ON_PUBLISH,
            "actions": [{"kind": "integration", "integration": "painter", "action": "touch_up", "attach_as": "cover-variant", "args": {}}],
        },
    )

    _publish(painter, article)

    (pic,) = _kept(painter)
    assert painter.session.query(EntryAssets).filter_by(entry_id=article.id, asset_id=pic.id).one().role == "cover-variant"


def test_a_run_can_wait_for_approval_after_generating_and_resume(painter):
    from marvin.db.models.groups.workflow_approvals import WorkflowApprovalModel
    from marvin.db.models.platform.entries import Entries
    from marvin.services.automation import approvals
    from marvin.services.automation.authz import ROLE_EDITOR

    article = _entry(painter)
    _workflow(
        painter,
        {
            "trigger": ON_PUBLISH,
            "actions": [
                {"kind": "approval", "id": "go", "message": "Paint a cover for ${entry.title}?"},
                {"kind": "integration", "id": "art", "integration": "painter", "action": "paid_paint", "args": {"prompt": "cover"}},
                {"kind": "approval", "id": "keep", "message": "Use this cover?"},
                {
                    "kind": "entry",
                    "op": "set_metadata",
                    "metadata": {"cover_asset": "${steps.art.output.images.0.asset.id}"},
                    "when": [{"field": "steps.keep.output.decision", "op": "eq", "value": "approved"}],
                },
            ],
        },
    )

    _publish(painter, article)
    (first,) = approvals.pending(painter.session, painter.gid, ROLE_EDITOR)
    approvals.decide(painter.session, painter.gid, first.id, "approve", user_id=painter.uid, role=ROLE_EDITOR)
    painter.session.expire_all()
    (second,) = approvals.pending(painter.session, painter.gid, ROLE_EDITOR)  # parked after generating
    snapshot = painter.session.get(WorkflowApprovalModel, second.id).snapshot
    assert snapshot is not None and len(json.dumps(snapshot)) < 8192 and "image_b64" not in json.dumps(snapshot)
    approvals.decide(painter.session, painter.gid, second.id, "approve", user_id=painter.uid, role=ROLE_EDITOR)
    painter.session.expire_all()

    kept_ids = {str(a.id) for a in _kept(painter)}
    assert painter.session.get(Entries, article.id).metadata_json["cover_asset"] in kept_ids
    assert [k for k, _ in painter.painter.calls] == ["paid_paint"]


def test_a_dry_run_says_the_pictures_would_be_kept(painter):
    from marvin.services.automation.engine import run_automation_now

    wf = _workflow(
        painter,
        {
            "trigger": {"type": "manual"},
            "target": {"entity": "entry", "query": {}},
            "actions": [{"kind": "integration", "integration": "painter", "action": "paint", "attach_as": "cover", "args": {"prompt": "p"}}],
        },
    )
    _entry(painter)

    result = run_automation_now(painter.session, painter.gid, wf, user_id=painter.uid, dry_run=True)

    (row,) = result["plan"]
    assert row["resolved"]["keeps_images_as_assets"] is True and row["resolved"]["attach_as"] == "cover"
    assert painter.painter.calls == [] and _kept(painter) == []


def test_attach_as_on_an_action_that_makes_no_image_is_refused(painter):
    from marvin.services.automation.authoring import draft_issues

    step = {"kind": "integration", "integration": "painter", "action": "list_it", "attach_as": "x", "args": {"title": "t"}}
    issues = draft_issues(painter.session, painter.gid, {"trigger": ON_PUBLISH, "actions": [step]})
    assert [i["path"] for i in issues] == ["actions[0].attach_as"], issues
