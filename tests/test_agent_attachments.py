"""Files attached to an agent question (`attachments` on the run request) and the `read_attachment` tool.

The bubble and the Ask page send attached files as asset ids, separate from the page context. The run checks
each one is a live asset of the workspace, lists them in the system prompt with the tools that open them, and
stores them on the user's turn so the thread shows them. `read_attachment` reads a document's text.
"""

import io
import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from pytest import fixture

from marvin.routes.ai import operations_controller as oc
from marvin.schemas.group.ai_execution import AIAgentRequest
from marvin.services.ai import agent as loop_mod
from marvin.services.ai.agent import AgentResult
from marvin.services.ai.operations.base import ROLE_AUTHOR, ROLE_VIEWER
from marvin.services.ai.tools import builtins_attachments as ba
from marvin.services.ai.tools.categories import category_of


class _Bus:
    def dispatch(self, **kw):
        pass


class _Loop:
    """Scripted `run_agent_loop`: records the messages and tools each run is handed."""

    def __init__(self):
        self.messages: list = []
        self.tools: list = []

    def __call__(self, provider, model, messages, tools, options=None, max_steps=6, on_event=None, resume=None):
        self.messages.append(messages)
        self.tools.append({t.name for t in tools})
        return AgentResult(answer="ok", steps=[], prompt_tokens=1, completion_tokens=1, total_tokens=2, stopped_reason="complete")


@fixture
def ws(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    gid, uid = uuid.uuid4(), uuid.uuid4()
    slug = f"att-{gid.hex[:8]}"
    g = Groups(session=db_session, name=slug, slug=slug)
    g.id = gid
    db_session.add(g)
    db_session.flush()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid, group_id=gid, username=slug, email=f"{slug}@t.test", full_name="ATT", password="x",
            is_superuser=False, platform_role="NONE", auth_method="MARVIN",
        )
    )  # fmt: skip
    db_session.flush()
    yield SimpleNamespace(gid=gid, uid=uid, session=db_session)
    db_session.rollback()


def _asset(ws, name, mime, *, extension="bin", size=2048, group_id=None, trashed=False):
    from datetime import UTC, datetime

    from marvin.db.models.platform import Assets

    slug = f"{name}-{uuid.uuid4().hex[:6]}"
    row = Assets(
        session=ws.session, group_id=group_id or ws.gid, slug=slug, name=name, original_filename=name, filename=name,
        extension=extension, file_size=size, mime_type=mime, asset_type="document", checksum=uuid.uuid4().hex,
        storage_provider="local", storage_key=f"att/{slug}", uploaded_by=ws.uid, trashed_at=datetime.now(UTC) if trashed else None,
    )  # fmt: skip
    ws.session.add(row)
    ws.session.flush()
    return row


@fixture
def ctl(ws, monkeypatch):
    monkeypatch.setattr(ws.session, "commit", ws.session.flush)
    c = oc.AIOperationsController.__new__(oc.AIOperationsController)
    c.session = ws.session
    c.user = SimpleNamespace(id=ws.uid, admin=False, active_group_id=ws.gid, group_id=ws.gid, workspace_memberships=[])
    c._logger = None
    c.event_bus = _Bus()
    c.loop = _Loop()
    monkeypatch.setattr(oc.AIOperationsController, "group", property(lambda self: SimpleNamespace(name="ws")))
    monkeypatch.setattr(loop_mod, "run_agent_loop", c.loop)
    stubs = {
        "_user_role": lambda: ROLE_AUTHOR,  # the agent endpoint needs AUTHOR
        "_agent_context_block": lambda t, i: None,
        "_bounded_history": lambda turns: [],
        "_completion_opts": lambda: None,
        "_emit_budget_thresholds": lambda execution: None,
        "_maybe_emit_quota": lambda execution, error: None,
        "_check_budget": lambda: None,
        "_agent_provider": lambda: SimpleNamespace(provider_type="fake"),
        "_default_model": lambda: "m-default",
        "_require_tool_capable": lambda provider, model: None,
        "_resolve_entity_id": lambda t, i: None,
        "_external_mcp_tools": lambda: [],
        "_persona": lambda: ("Marvin", ""),
        "_register_clause": lambda *a, **k: "",
        "_default_register": lambda *a, **k: "auto",
        "_effective_register": lambda *a, **k: "auto",
    }
    for name, fn in stubs.items():
        monkeypatch.setattr(c, name, fn, raising=False)
    return c


def _ask(ctl, attachments, thread_id="new"):
    return ctl.run_agent(AIAgentRequest(message="what's in these?", source="bubble", threadId=thread_id, attachments=attachments))


def _system(ctl) -> str:
    return ctl.loop.messages[-1][0].content


# ── The request ──────────────────────────────────────────────────────────────


def test_more_than_four_attachments_is_refused():
    with pytest.raises(ValidationError):
        AIAgentRequest(message="hi", attachments=[uuid.uuid4() for _ in range(5)])


def test_attachments_default_to_none_and_ride_alongside_the_page_context():
    body = AIAgentRequest(message="hi", entityType="entry", entityId="e1", attachments=[str(uuid.uuid4())])
    assert body.entity_type == "entry" and len(body.attachments) == 1
    assert AIAgentRequest(message="hi").attachments == []


# ── The run ──────────────────────────────────────────────────────────────────


def test_attached_files_are_listed_with_the_tools_that_open_them(ctl, ws):
    photo = _asset(ws, "swatch.jpg", "image/jpeg", extension="jpg")
    spec = _asset(ws, "spec.pdf", "application/pdf", extension="pdf", size=3 * 1024 * 1024)

    _ask(ctl, [photo.id, spec.id])

    system = _system(ctl)
    assert "## Files the user attached to the question" in system
    assert f'"swatch.jpg" (image/jpeg, 2 KB) — asset id {photo.id}' in system
    assert f'"spec.pdf" (application/pdf, 3.0 MB) — asset id {spec.id}' in system
    assert "view_image" in system and "read_attachment" in system
    assert "look at them before you answer" in system  # "like it?" is about the file
    assert "nothing to import" in system and "not in the Assets library" in system  # an Ask file
    assert {"view_image", "read_attachment"} <= ctl.loop.tools[-1]


def test_a_run_without_attachments_has_no_attachment_section(ctl):
    _ask(ctl, [])
    assert "Files the user attached" not in _system(ctl)


@pytest.mark.parametrize("kind", ["another workspace", "trashed", "made up"])
def test_an_attachment_that_is_not_a_live_asset_here_is_refused(ctl, ws, kind):
    if kind == "another workspace":
        from marvin.db.models.groups import Groups

        other = Groups(session=ws.session, name=f"o-{uuid.uuid4().hex[:6]}", slug=f"o-{uuid.uuid4().hex[:6]}")
        ws.session.add(other)
        ws.session.flush()
        bad = _asset(ws, "theirs.pdf", "application/pdf", group_id=other.id).id
    elif kind == "trashed":
        bad = _asset(ws, "old.pdf", "application/pdf", trashed=True).id
    else:
        bad = uuid.uuid4()

    with pytest.raises(HTTPException) as exc:
        _ask(ctl, [bad])

    assert exc.value.status_code == 422 and str(bad) in exc.value.detail
    assert ctl.loop.messages == []  # refused before the model ran


def test_the_user_turn_keeps_its_attachments(ctl, ws):
    from marvin.db.models.groups.ai_threads import AIThreadModel

    doc = _asset(ws, "notes.md", "text/markdown", extension="md")
    out = _ask(ctl, [doc.id])

    thread = ws.session.get(AIThreadModel, uuid.UUID(out["threadId"]))
    user_turn = next(m for m in thread.messages if m.role == "user")
    assert user_turn.meta_json == {"attachments": [{"id": str(doc.id), "name": "notes.md", "mimeType": "text/markdown"}]}
    assert user_turn.content == "what's in these?"  # the message itself is unchanged


# ── read_attachment ──────────────────────────────────────────────────────────


def _pdf(text: str) -> bytes:
    """A one-page PDF whose page draws `text` (built by hand: pypdf reads but doesn't typeset)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref))
    return out.getvalue()


def _docx(*paragraphs: str) -> bytes:
    from docx import Document

    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@fixture
def files(monkeypatch):
    """Storage stand-in: storage_key → bytes."""
    store: dict[str, bytes] = {}
    monkeypatch.setattr("marvin.services.storage.provider_factory.provider_for", lambda name: SimpleNamespace(get=lambda key: io.BytesIO(store[key])))
    return store


def _read(ws, asset, **args) -> dict:
    ctx = SimpleNamespace(session=ws.session, group_id=ws.gid)
    return json.loads(ba.read_attachment(ctx, {"asset": str(asset.id), **args}))


def test_read_attachment_is_registered_read_only_and_categorised_as_a_read():
    from marvin.services.ai.tools import list_tools

    spec = next(t for t in list_tools() if t.name == "read_attachment")
    assert spec.read_only and spec.min_role == ROLE_VIEWER
    assert category_of("read_attachment", read_only=True) == "library_read"


def test_read_attachment_reads_text(ws, files):
    doc = _asset(ws, "notes.md", "text/markdown", extension="md")
    files[doc.storage_key] = b"# Fit notes\nTaper the leg 1 cm."
    out = _read(ws, doc)
    assert out["text"] == "# Fit notes\nTaper the leg 1 cm." and out["truncated"] is False


def test_read_attachment_reads_a_pdf(ws, files):
    doc = _asset(ws, "spec.pdf", "application/pdf", extension="pdf")
    files[doc.storage_key] = _pdf("Selvedge denim 14oz")
    assert "Selvedge denim 14oz" in _read(ws, doc)["text"]


def test_read_attachment_reads_a_word_document(ws, files):
    doc = _asset(ws, "brief.docx", ba.DOCX_MIME, extension="docx")
    files[doc.storage_key] = _docx("Brief", "Ship by Friday.")
    assert _read(ws, doc)["text"] == "Brief\nShip by Friday."


def test_read_attachment_cuts_long_documents_and_says_so(ws, files):
    doc = _asset(ws, "log.txt", "text/plain", extension="txt")
    files[doc.storage_key] = b"x" * 500
    out = _read(ws, doc, max_chars=100)
    assert len(out["text"]) == 100 and out["truncated"] is True and "100" in out["note"]


def test_read_attachment_refuses_files_it_cannot_read(ws, files):
    photo = _asset(ws, "swatch.jpg", "image/jpeg", extension="jpg")
    zipped = _asset(ws, "pack.zip", "application/zip", extension="zip")
    assert "view_image" in _read(ws, photo)["error"]
    assert "can't read this kind of file" in _read(ws, zipped)["error"]


def test_read_attachment_only_sees_this_workspace(ws, files):
    from marvin.db.models.groups import Groups

    other = Groups(session=ws.session, name=f"o-{uuid.uuid4().hex[:6]}", slug=f"o-{uuid.uuid4().hex[:6]}")
    ws.session.add(other)
    ws.session.flush()
    theirs = _asset(ws, "theirs.txt", "text/plain", extension="txt", group_id=other.id)
    files[theirs.storage_key] = b"secret"
    assert "no asset" in _read(ws, theirs)["error"]
    assert "no asset" in json.loads(ba.read_attachment(SimpleNamespace(session=ws.session, group_id=ws.gid), {"asset": "no-such-slug"}))["error"]
