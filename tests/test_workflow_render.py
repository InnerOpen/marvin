"""A workflow's render step: an HTML/CSS template filled with text and pictures, screenshotted by headless Chromium into
a new asset. The page can't reach the network or run script (its Content-Security-Policy), so a template — built-in or
the step's own — is inert. Tests that take a screenshot need a headless Chromium and skip without one."""

# ruff: noqa: F811 — `ws` / `media` are fixtures, not redefinitions
import http.server
import io
import threading

import pytest
from PIL import Image

from marvin.services.ai.media import render
from marvin.services.automation.authoring import draft_issues
from tests.test_workflow_authoring import workspace, ws  # noqa: F401 — fixtures
from tests.test_workflow_media import _derivatives, _entry, _fire, _last_run, _link, _png, _stored, _workflow, media  # noqa: F401

needs_browser = pytest.mark.skipif(render.browser_path() is None, reason="no headless Chromium (chromium-headless-shell) here")


def _filled(slug: str, **fields) -> str:
    manifest = render.templates()[slug]
    images = dict.fromkeys(manifest["images"], "data:image/png;base64,AAAA")
    return render.fill(
        render.template_html(slug),
        fields=dict.fromkeys(manifest["fields"], "") | fields,
        images=images,
        width=manifest["width"],
        height=manifest["height"],
    )


# ── Filling a template ────────────────────────────────────────────────────────
def test_text_is_escaped_and_the_page_is_locked_down():
    page = _filled("card", title='<script>alert(1)</script> & "quotes"')
    assert "<script>alert" not in page and "&lt;script&gt;" in page
    assert render.CSP in page and "default-src 'none'" in page


def test_every_built_in_template_fills_with_its_required_fields():
    for slug, manifest in render.templates().items():
        required = {k: f"{k} text" for k, spec in manifest["fields"].items() if spec.get("required")}
        assert "<body>" in _filled(slug, **required), slug


def test_a_custom_template_naming_a_field_it_wasnt_given_fails_loudly():
    with pytest.raises(render.RenderError, match="couldn't be filled in"):
        render.fill("<h1>{{ fields.title }}</h1>", fields={}, images={}, width=100, height=100)


def test_the_sandbox_refuses_python_internals():
    with pytest.raises(render.RenderError):
        render.fill("{{ fields.__class__.__mro__ }}", fields={}, images={}, width=100, height=100)


def test_the_frontend_lists_the_same_templates():
    import json
    import pathlib

    copy = pathlib.Path(__file__).resolve().parents[1] / "frontend/src/lib/renderTemplates.json"
    assert json.loads(copy.read_text()) == render.templates(), "frontend/src/lib/renderTemplates.json is a copy of the manifest"


# ── Screenshots ───────────────────────────────────────────────────────────────
@needs_browser
def test_a_screenshot_is_exactly_the_size_asked():
    png = render.render('<div style="width:100vw;height:100vh;background:#123456"></div>', fields={}, images={}, width=640, height=360)
    img = Image.open(io.BytesIO(png)).convert("RGB")
    assert img.size == (640, 360) and img.getpixel((10, 10)) == (0x12, 0x34, 0x56)


@needs_browser
def test_a_template_cannot_reach_the_network_or_run_script():
    hits: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — the stdlib's name
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        html = (
            f'<img src="{base}/img"><link rel="stylesheet" href="{base}/css">'
            f'<div style="width:100vw;height:100vh;background:#fff url({base}/bg)"></div>'
            f"<script>document.body.style.background='red'; fetch('{base}/fetch')</script>"
            f'<iframe src="{base}/frame"></iframe>'
        )
        png = render.render(html, fields={}, images={}, width=200, height=200)
    finally:
        server.shutdown()
    assert hits == []
    assert Image.open(io.BytesIO(png)).convert("RGB").getpixel((150, 150)) == (255, 255, 255)  # the script didn't run


# ── The step ──────────────────────────────────────────────────────────────────
QUOTE_STEP = {
    "kind": "media",
    "id": "card",
    "op": "render",
    "template": "quote",
    "fields": {"quote": "Every painting starts as a question.", "attribution": "${entry.title}"},
    "images": {"background": "role:hero"},
    "attach_as": "quote-card",
    "tags": ["social"],
}


@needs_browser
def test_a_render_step_makes_a_new_asset_from_the_entrys_picture(media):
    from marvin.db.models.platform.entry_assets import EntryAssets

    article = _entry(media, "Harbour")
    hero = _stored(media, "hero", _png((800, 600)))
    _link(media, article, hero, "hero")
    _workflow(media, {"trigger": {"type": "event", "event": "entry_published"}, "actions": [QUOTE_STEP]})

    _fire(media, "entry_published", {"entry_id": str(article.id)}, entity=article.id, entity_type="entry")
    _fire(media, "entry_published", {"entry_id": str(article.id)}, entity=article.id, entity_type="entry", correlation_id="corr-2")

    (card,) = _derivatives(media, hero)  # made from the hero, once
    assert (card.width, card.height, card.mime_type, card.origin) == (1080, 1080, "image/png", "derived")
    meta = card.metadata_json
    assert meta["derivation"] == "render:quote" and meta["rendered_from"] == {"background": str(hero.id)} and meta["workflow_slug"] == "media-wf"
    assert media.session.query(EntryAssets).filter_by(entry_id=article.id, asset_id=card.id).one().role == "quote-card"
    assert sorted(t.slug for t in card.tags) == ["social"]
    out = _last_run(media).actions[0].output_snapshot
    assert out["reused"] is True and out["template"] == "quote"


@needs_browser
def test_a_render_without_pictures_is_a_generated_asset(media):
    from marvin.db.models.platform.assets import Assets

    _workflow(
        media,
        {
            "trigger": {"type": "manual"},
            "actions": [
                {
                    "kind": "media",
                    "op": "render",
                    "html": "<h1 style='font:40px sans-serif'>{{ fields.word }}</h1>",
                    "fields": {"word": "Hi"},
                    "width": 300,
                    "height": 120,
                    "format": "webp",
                }
            ],
        },
    )
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.services.automation.engine import run_automation_now

    wf = media.session.query(WorkspaceAutomationModel).filter_by(group_id=media.gid, slug="media-wf").one()
    assert run_automation_now(media.session, media.gid, wf, user_id=media.uid)["ok"]

    (made,) = media.session.query(Assets).filter(Assets.group_id == media.gid, Assets.origin == "generated").all()
    assert (made.width, made.height, made.mime_type) == (300, 120, "image/webp")
    assert made.metadata_json["generated_by"] == "render:custom" and made.source_asset_id is None


def test_a_dry_run_fills_the_template_but_starts_no_browser(media, monkeypatch):
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.services.automation.engine import run_automation_now

    monkeypatch.setattr(render, "screenshot", lambda *a, **k: pytest.fail("a dry run took a screenshot"))
    article = _entry(media, "Harbour")
    _link(media, article, _stored(media, "hero", _png()), "hero")
    _workflow(media, {"trigger": {"type": "manual"}, "target": {"entity": "entry", "query": {}}, "actions": [{**QUOTE_STEP, "attach_as": None}]})
    wf = media.session.query(WorkspaceAutomationModel).filter_by(group_id=media.gid, slug="media-wf").one()

    result = run_automation_now(media.session, media.gid, wf, user_id=media.uid, dry_run=True)

    (row,) = result["plan"]
    assert row["resolved"]["would_create"].startswith("hero-") and row["resolved"]["template"] == "quote"


def test_a_missing_required_field_fails_the_step(media):
    article = _entry(media, "Harbour")
    _link(media, article, _stored(media, "hero", _png()), "hero")
    step = {**QUOTE_STEP, "fields": {"quote": "${entry.data.nothing}"}}
    _workflow(media, {"trigger": {"type": "event", "event": "entry_published"}, "actions": [step]})

    _fire(media, "entry_published", {"entry_id": str(article.id)}, entity=article.id, entity_type="entry")

    assert "needs quote" in _last_run(media).actions[0].error


@pytest.mark.parametrize(
    ("step", "path"),
    [
        ({"kind": "media", "op": "render"}, "actions[0].media"),  # neither template nor html
        ({"kind": "media", "op": "render", "template": "quote", "html": "<p></p>", "fields": {"quote": "q"}}, "actions[0].media"),
        ({"kind": "media", "op": "render", "template": "postcard"}, "actions[0].template"),
        ({"kind": "media", "op": "render", "template": "quote", "fields": {}}, "actions[0].fields"),  # quote is required
        ({"kind": "media", "op": "render", "template": "quote", "fields": {"quote": "q", "colour": "red"}}, "actions[0].fields"),
        ({"kind": "media", "op": "render", "template": "meme", "fields": {"top": "x"}}, "actions[0].images"),  # image required
        ({"kind": "media", "op": "render", "template": "quote", "fields": {"quote": "q"}, "source": "x"}, "actions[0].media"),
    ],
)
def test_the_validator_names_what_a_render_step_lacks(ws, step, path):
    issues = draft_issues(ws.session, ws.gid, {"trigger": {"type": "event", "event": "entry_published"}, "actions": [step]})
    assert path in [i.get("path") for i in issues], issues
