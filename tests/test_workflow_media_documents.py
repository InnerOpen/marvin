"""The media step on documents and for privacy: `extract_text` (a PDF's text layer, scanned pages and pictures read by
the vision model), `pages` (PDF pages as pictures), `find_sensitive` and `redact` (faces, plates and personal text
pixelated in a new copy). The vision model is faked; PDFs are written here so their text layer is real."""

# ruff: noqa: F811 — `ws` / `media` are fixtures, not redefinitions
import io
import uuid

import pytest
from PIL import Image

from marvin.services.automation.engine import run_automation_now
from marvin.services.automation.recorder import ExecutionRecorder
from tests.test_workflow_authoring import workspace, ws  # noqa: F401 — fixtures
from tests.test_workflow_media import _derivatives, _entry, _last_run, _link, _png, _stored, _workflow, media  # noqa: F401


def pdf(pages: list[str]) -> bytes:
    """A PDF with one line of Helvetica text per page ("" makes a page with no text layer, like a scan)."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        stream = f"BT /F1 18 Tf 72 700 Td ({text}) Tj ET".encode() if text else b""
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
        content = len(objects)
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + (body if isinstance(body, bytes) else body.encode()) + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    out.write("".join(f"{o:010d} 00000 n \n" for o in offsets).encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return out.getvalue()


class _Vision:
    """A vision model that reads every picture the same way, and counts its calls."""

    def __init__(self, text="", regions=()):
        self.answer = {"text": text, "regions": list(regions)}
        self.calls, self.last_usage, self.provider, self.model = [], None, None, "fake"

    def invoke(self, inputs):
        self.calls.append(inputs)
        return self.answer


@pytest.fixture
def vision(monkeypatch):
    from marvin.services.automation.actions import media as media_step

    fake = _Vision(text="Handwritten: wax the canvas twice.", regions=[{"kind": "face", "box": [0.25, 0.25, 0.25, 0.25]}])
    monkeypatch.setattr(media_step, "vision_handler", lambda session, group_id, kind: (fake, None))
    return fake


def _run(ws, step: dict, **kwargs):
    slug = f"doc-{uuid.uuid4().hex[:6]}"
    row = _workflow(ws, {"trigger": {"type": "manual"}, "actions": [{"id": "s", **step}]}, slug=slug)
    result = run_automation_now(ws.session, ws.gid, row, user_id=ws.uid, recorder=ExecutionRecorder(ws.session, ws.gid), **kwargs)
    run = _last_run(ws, slug)
    return result, (run.actions[0] if run and run.actions else None)


# ── extract_text ─────────────────────────────────────────────────────────────
def test_a_pdfs_text_layer_is_read_page_by_page_without_ai(media, vision):
    doc = _stored(media, "guide", pdf(["Waxing canvas: warm the wax first.", "Let it cure for a week before use."]), mime="application/pdf")

    result, step = _run(media, {"kind": "media", "op": "extract_text", "source": doc.slug})

    out = step.output_snapshot
    assert result["ok"] and (out["page_count"], out["read_with_ai"]) == (2, 0) and vision.calls == []
    assert [p["text"] for p in out["pages"]] == ["Waxing canvas: warm the wax first.", "Let it cure for a week before use."]
    assert out["text"].startswith("[page 1]\nWaxing canvas") and "[page 2]\nLet it cure" in out["text"]


def test_a_scanned_page_is_read_by_the_vision_model(media, vision):
    doc = _stored(media, "notes", pdf(["Typed page with enough words to count.", ""]), mime="application/pdf")

    _, step = _run(media, {"kind": "media", "op": "extract_text", "source": doc.slug})
    _, never = _run(media, {"kind": "media", "op": "extract_text", "source": doc.slug, "ocr": "never"})

    pages = step.output_snapshot["pages"]
    assert [(p["method"], p["text"]) for p in pages] == [
        ("pdf", "Typed page with enough words to count."),
        ("vision", "Handwritten: wax the canvas twice."),
    ]
    assert len(vision.calls) == 1 and Image.open(io.BytesIO(vision.calls[0]["image_bytes"])).width == 1600  # the page, as a picture
    assert never.output_snapshot["pages"][1]["text"] == "" and "ocr: never" in never.output_snapshot["note"]


def test_a_picture_needs_a_vision_model(media, monkeypatch):
    from marvin.services.automation.actions import media as media_step

    monkeypatch.setattr(media_step, "vision_handler", lambda *a: (None, "no AI model that can see images"))
    photo = _stored(media, "whiteboard", _png())

    result, step = _run(media, {"kind": "media", "op": "extract_text", "source": photo.slug})

    assert not result["ok"] and "needs an AI model that can see images" in step.error


def test_a_dry_run_of_extract_text_asks_no_ai(media, vision):
    doc = _stored(media, "guide", pdf(["x" * 40]), mime="application/pdf")
    row = _workflow(media, {"trigger": {"type": "manual"}, "actions": [{"kind": "media", "op": "extract_text", "source": doc.slug}]})
    result = run_automation_now(media.session, media.gid, row, user_id=media.uid, dry_run=True)
    assert result["ok"] and result["plan"][0]["resolved"]["text"] == "‹the text of guide›" and vision.calls == []


# ── pages ────────────────────────────────────────────────────────────────────
def test_pages_become_pictures_made_once_and_attached(media):
    from marvin.db.models.platform.entry_assets import EntryAssets

    article = _entry(media, "Field guide")
    doc = _stored(media, "field-guide", pdf(["Cover", "Tools", "Steps"]), mime="application/pdf")
    _link(media, article, doc, "download")
    step = {"kind": "media", "op": "pages", "source": doc.slug, "count": 2, "width": 600, "attach_as": "preview"}
    definition = {"trigger": {"type": "manual", "inputs": [{"name": "piece", "type": "entry"}]}, "actions": [{"id": "s", **step}]}
    row = _workflow(media, definition)

    for _ in range(2):
        assert run_automation_now(
            media.session, media.gid, row, user_id=media.uid, recorder=ExecutionRecorder(media.session, media.gid), inputs={"piece": article.slug}
        )["ok"]

    made = sorted(_derivatives(media, doc), key=lambda a: a.metadata_json["page"])
    assert [(a.metadata_json["page"], a.width, a.mime_type) for a in made] == [(1, 600, "image/webp"), (2, 600, "image/webp")]
    assert _last_run(media).actions[0].output_snapshot["reused"] is True  # the second run made nothing new
    roles = media.session.query(EntryAssets).filter_by(entry_id=article.id, role="preview").count()
    assert roles == 2


def test_pages_of_a_page_that_isnt_there_fail_plainly(media):
    doc = _stored(media, "short", pdf(["Only page"]), mime="application/pdf")
    result, step = _run(media, {"kind": "media", "op": "pages", "source": doc.slug, "page": 3})
    assert not result["ok"] and "has 1 page, not a page 3" in step.error


# ── find_sensitive / redact ──────────────────────────────────────────────────
def test_find_then_redact_asks_the_model_once_and_blurs_a_copy(media, vision):
    photo = _stored(media, "market", _png((400, 400), color=(250, 250, 250)))
    row = _workflow(
        media,
        {
            "trigger": {"type": "manual"},
            "actions": [
                {"id": "find", "kind": "media", "op": "find_sensitive", "source": photo.slug},
                {
                    "id": "blur",
                    "kind": "media",
                    "op": "redact",
                    "source": photo.slug,
                    "when": {"field": "steps.find.output.count", "op": "gt", "value": 0},
                },
            ],
        },
    )

    assert run_automation_now(media.session, media.gid, row, user_id=media.uid, recorder=ExecutionRecorder(media.session, media.gid))["ok"]

    found, blurred = (a.output_snapshot for a in _last_run(media).actions)
    assert found["count"] == 1 and found["regions"][0]["kind"] == "face" and len(vision.calls) == 1  # redact reused it
    (copy,) = _derivatives(media, photo)
    assert copy.metadata_json["media_op"] == "redact" and blurred["asset"]["id"] == str(copy.id)


def test_redact_takes_boxes_and_makes_nothing_when_there_is_nothing_to_blur(media, vision):
    from marvin.services.automation.actions.media_documents import pixelate

    photo = _stored(media, "street", _png((300, 300)))
    _, nothing = _run(media, {"kind": "media", "op": "redact", "source": photo.slug, "boxes": []})
    assert nothing.output_snapshot == {"source_id": str(photo.id), "count": 0, "regions": []} and _derivatives(media, photo) == []

    detailed = Image.new("RGB", (200, 200), "white")
    for x in range(50, 150):
        for y in range(50, 150):
            detailed.putpixel((x, y), (0, 0, 0) if (x // 2 + y // 2) % 2 else (255, 255, 255))
    buf = io.BytesIO()
    detailed.save(buf, "PNG")
    blurred = Image.open(io.BytesIO(pixelate(buf.getvalue(), [[0.25, 0.25, 0.5, 0.5]]))).convert("L")
    edges = sum(abs(blurred.getpixel((x, 100)) - blurred.getpixel((x + 1, 100))) for x in range(60, 140))
    assert edges < 400 and blurred.getpixel((5, 5)) == 255  # the checkerboard is gone; outside the box is untouched


@pytest.mark.parametrize(
    ("step", "path"),
    [
        ({"kind": "media", "op": "pages", "colors": 3}, "actions[0].media"),
        ({"kind": "media", "op": "extract_text", "ocr": "sometimes"}, "actions[0].ocr"),
        ({"kind": "media", "op": "redact", "find": ["tattoo"]}, "actions[0].find"),
    ],
)
def test_the_validator_names_what_a_document_step_gets_wrong(ws, step, path):
    from marvin.services.automation.authoring import draft_issues

    issues = draft_issues(ws.session, ws.gid, {"trigger": {"type": "manual"}, "actions": [step]})
    assert any(str(i.get("path", "")).startswith(path) for i in issues), issues
