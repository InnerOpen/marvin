"""Entry templates (services/entries/templates.py): presets on an entry type, entries made from pictures with one, existing
entries filled with one, set-based, behind REST and checked against the type's schema when saved.

The workspace here is committed for real (execute commits per chunk, and the HTTP tests' app opens its own sessions), so
each test makes its own and purges it afterwards, as tests/test_bulk_delete.py does.
"""

import time
import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.platform import Entries, EntryCollections, EntryTypes
from marvin.db.models.platform.assets import Assets
from marvin.db.models.platform.collections import Collections
from marvin.db.models.platform.entry_assets import EntryAssets
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services.entries import templates as T

SCHEMA = {
    "fields": [
        {"key": "image", "type": "asset", "label": "Image"},
        {"key": "gallery", "type": "asset-list", "label": "Gallery"},
        {"key": "medium", "type": "text", "label": "Medium"},
        {"key": "size", "type": "text", "label": "Size"},
        {"key": "price", "type": "number", "label": "Price"},
        {"key": "series", "type": "text", "label": "Series"},
        {"key": "sell_online", "type": "boolean", "label": "Sell online"},
    ]
}
ORNAMENT = {
    "slug": "ornament",
    "name": "Ornament",
    "title": "{asset.name}",
    "summary": "Ornament {n} of the {date} batch",
    "fields": {"medium": "Acrylic and Ink on Ceramic", "size": '3"', "price": 85, "series": "Ornament", "sell_online": True},
    "tags": ["Ornaments", "hand painted"],
    "collections": ["shop"],
    "asset_role": "featured",
    "asset_field": "image",
}


class _Spy:
    """An event bus that only remembers what it was asked to send."""

    last: list = []

    def __init__(self, *a, **k):
        pass

    def dispatch(self, *, event_type, document_data=None, message="", **_):
        _Spy.last.append((event_type.name, document_data, message))


@fixture
def ws(db_session, monkeypatch):
    """A committed workspace with an artwork type carrying the Ornament template, a hand-picked 'shop' collection, the
    system collections (Inbox is a smart one), users by role and pictures. Events go to the spy."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.db.models.users.users import Users
    from marvin.services.collections.system_collections import seed_system_workflow_collections
    from marvin.services.group.group_purge import purge_group_dependents

    monkeypatch.setattr("marvin.services.event_bus_service.event_bus_service.EventBusService", _Spy)
    _Spy.last = []
    session = db_session
    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=session, name=f"tpl-{marker}", slug=f"tpl-{marker}")
    g.id = gid
    session.add(g)
    session.flush()
    if session.query(GroupPreferencesModel).filter_by(group_id=gid).first() is None:
        session.add(GroupPreferencesModel(session=session, group_id=gid))
    users = {}
    for who in ("editor", "author", "other"):
        uid = uuid.uuid4()
        session.execute(
            Users.__table__.insert().values(
                id=uid,
                group_id=gid,
                username=f"{who}-{marker}",
                email=f"{who}-{marker}@t.test",
                full_name=who,
                password="x",
                is_superuser=False,
                platform_role="NONE",
                auth_method="MARVIN",
            )
        )
        users[who] = uid
    et = EntryTypes(session=session, group_id=gid, name="Artwork", slug="artwork", schema_json=SCHEMA)
    et.id = uuid.uuid4()
    et.templates_json = T.check_templates([ORNAMENT], SCHEMA)
    session.add(et)
    shop = Collections(session=session, group_id=gid, name="Shop", slug="shop")
    session.add(shop)
    session.flush()
    seed_system_workflow_collections(session, gid)
    session.commit()

    def picture(name: str, filename: str | None = None) -> Assets:
        slug = f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}"
        a = Assets(
            session=session,
            group_id=gid,
            slug=slug,
            name=name,
            original_filename=filename or f"{slug}.png",
            filename=f"{slug}.png",
            extension="png",
            file_size=1,
            mime_type="image/png",
            asset_type="image",
            checksum=slug,
            storage_provider="local",
            storage_key=f"{gid.hex}/{slug}.png",
            uploaded_by=users["editor"],
        )
        session.add(a)
        session.commit()
        return a

    def pictures(n: int) -> list:
        from datetime import UTC, datetime

        now = datetime.now(UTC).replace(tzinfo=None)
        rows = []
        for i in range(n):
            slug = f"pic-{i}-{uuid.uuid4().hex[:6]}"
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "group_id": gid,
                    "slug": slug,
                    "name": f"Snowy Owl {i}",
                    "original_filename": f"IMG_{i}.png",
                    "filename": f"{slug}.png",
                    "extension": "png",
                    "file_size": 1,
                    "mime_type": "image/png",
                    "asset_type": "image",
                    "checksum": slug,
                    "storage_provider": "local",
                    "storage_key": f"{gid.hex}/{slug}.png",
                    "uploaded_by": users["editor"],
                    "created_at": now,
                    "update_at": now,
                }
            )
        session.execute(Assets.__table__.insert(), rows)
        session.commit()
        return [str(r["id"]) for r in rows]

    def entry(title: str, *, status="draft", owner="editor", **data) -> Entries:
        e = Entries(session=session, group_id=gid, entry_type_id=et.id, title=title, slug=f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:4]}")
        e.data_json = data
        e.status = status
        e.created_by = users[owner]
        session.add(e)
        session.commit()
        return e

    yield SimpleNamespace(gid=gid, session=session, users=users, type=et, shop=shop, picture=picture, pictures=pictures, entry=entry)
    app.dependency_overrides.pop(get_current_user, None)
    session.rollback()
    session.query(EntryAssets).filter(EntryAssets.asset_id.in_(session.query(Assets.id).filter(Assets.group_id == gid))).delete(
        synchronize_session=False
    )
    session.query(Assets).filter(Assets.group_id == gid).delete(synchronize_session=False)
    purge_group_dependents(session, gid)
    session.query(Users).filter(Users.group_id == gid).delete()
    session.query(Groups).filter(Groups.id == gid).delete()
    session.commit()


def _count(ws) -> int:
    ws.session.expire_all()
    return ws.session.query(Entries).filter(Entries.group_id == ws.gid).count()


def _events(name="entry_template_applied") -> list:
    return [e for e in _Spy.last if e[0] == name]


# ── Saving ─────────────────────────────────────────────────────────────────────


class TestCheckTemplates:
    def test_a_good_template_is_stored_with_its_defaults(self):
        [t] = T.check_templates([{"slug": "plain", "name": "Plain"}], SCHEMA)
        assert t["title"] == "{asset.name}" and t["status"] == "inbox" and t["asset_role"] == "featured" and t["fields"] == {}

    def test_none_and_an_empty_list_store_nothing(self):
        assert T.check_templates(None, SCHEMA) is None
        assert T.check_templates([], SCHEMA) is None

    @pytest.mark.parametrize(
        "change, said",
        [
            ({"title": "{asset.title}"}, "{asset.title}, which is not a variable"),
            ({"summary": "Made {when}"}, "summary uses {when}"),
            ({"fields": {"medium": "{colour}"}}, "field medium uses {colour}"),
            ({"fields": {"frame": "oak"}}, "'frame' is not a field of this entry type"),
            ({"fields": {"price": "eighty"}}, "field price"),
            ({"asset_field": "medium"}, "'medium', which is not an asset field (asset fields: image, gallery)"),
            ({"asset_field": "image", "fields": {"image": "x"}}, "field image is where the picture goes"),
            ({"status": "published"}, "status"),
            ({"slug": "Not A Slug"}, "slug"),
        ],
    )
    def test_a_template_that_does_not_fit_is_refused_naming_why(self, change, said):
        with pytest.raises(T.TemplateError) as e:
            T.check_templates([{**ORNAMENT, **change}], SCHEMA)
        assert said in str(e.value)

    def test_two_templates_with_one_slug_are_refused(self):
        with pytest.raises(T.TemplateError, match="two templates have this slug"):
            T.check_templates([ORNAMENT, {**ORNAMENT, "name": "Again"}], SCHEMA)


class TestSavedOnTheType:
    def test_the_repository_checks_templates_against_the_schema_it_stores(self, ws):
        from marvin.repos.repository_factory import AllRepositories

        repos = AllRepositories(ws.session, group_id=ws.gid)
        with pytest.raises(HTTPException) as e:
            repos.entry_types.update(ws.type.id, {"templates": [{**ORNAMENT, "title": "{asset.title}"}]})
        assert e.value.status_code == 400 and "{asset.title}" in e.value.detail
        # Dropping a field a template fills is refused too: the pair is checked as it will be stored.
        fewer = {"fields": [f for f in SCHEMA["fields"] if f["key"] != "price"]}
        with pytest.raises(HTTPException) as e:
            repos.entry_types.update(ws.type.id, {"schema_json": fewer})
        assert "'price' is not a field" in e.value.detail
        read = repos.entry_types.update(ws.type.id, {"templates": [ORNAMENT, {"slug": "plain", "name": "Plain"}]})
        assert [t.slug for t in read.templates] == ["ornament", "plain"]
        assert read.model_dump(by_alias=True)["templatesJson"][0]["assetField"] == "image"

    def test_a_package_installs_its_templates_and_an_update_adds_only_the_ones_lacking(self, ws):
        from marvin.schemas.platform.blueprints import Blueprint
        from marvin.services.blueprints.apply import apply_blueprint, update_entry_type

        payload = {"name": "Print", "schema_json": SCHEMA, "templates_json": [ORNAMENT]}
        made = apply_blueprint(ws.session, ws.gid, Blueprint(kind="entry_type", slug="print", name="Print", payload=payload))
        assert made.created, made.detail
        row = ws.session.query(EntryTypes).filter_by(group_id=ws.gid, slug="print").one()
        assert row.templates_json[0]["slug"] == "ornament"
        row.templates_json = [{**row.templates_json[0], "name": "Edited here"}]
        ws.session.flush()
        newer = {**payload, "templates_json": [{**ORNAMENT, "name": "Changed upstream"}, {"slug": "plain", "name": "Plain"}]}
        done = update_entry_type(ws.session, ws.gid, Blueprint(kind="entry_type", slug="print", name="Print", payload=newer), row)
        assert done.updated and "template plain" in done.detail
        assert [(t["slug"], t["name"]) for t in row.templates_json] == [("ornament", "Edited here"), ("plain", "Plain")]

    def test_a_package_template_that_does_not_fit_its_type_is_refused(self, ws):
        from marvin.schemas.platform.blueprints import Blueprint
        from marvin.services.blueprints.apply import apply_blueprint

        payload = {"name": "Bad", "schema_json": SCHEMA, "templates_json": [{**ORNAMENT, "fields": {"frame": "oak"}}]}
        made = apply_blueprint(ws.session, ws.gid, Blueprint(kind="entry_type", slug="bad", name="Bad", payload=payload))
        assert not made.created and "'frame' is not a field" in made.detail


# ── Making entries from pictures ───────────────────────────────────────────────


class TestFromPictures:
    def test_a_preview_names_each_entry_after_its_picture_and_changes_nothing(self, ws):
        a = ws.picture("Snowy Owl", "IMG_0042.png")
        b = ws.picture("Red Cardinal")
        before = _count(ws)
        plan = T.plan_from_assets(ws.session, ws.gid, "artwork", "ornament", [str(a.id), b.slug])
        out = T.describe(plan)
        assert _count(ws) == before and not _events()
        assert out["create"] == 2 and out["errors"] == 0 and out["text"] == "make 2 artworks"
        first = out["rows"][0]
        assert first["title"] == "Snowy Owl" and first["asset"]["filename"] == "IMG_0042.png"
        today = time.strftime("%Y-%m-%d", time.gmtime())
        assert first["changes"]["summary"] == f"Ornament 1 of the {today} batch"
        assert first["changes"]["fields"] == {**ORNAMENT["fields"], "image": str(a.id)}
        assert first["tags"] == ["Ornaments", "hand painted"] and first["collections"] == ["shop"] and first["attach"]
        assert out["rows"][1]["changes"]["summary"].startswith("Ornament 2 ")

    def test_create_makes_inbox_drafts_with_the_picture_set_and_attached_as_featured(self, ws):
        from marvin.db.models.platform import Tags
        from marvin.db.models.platform.entry_tags import EntryTags

        a, b = ws.picture("Snowy Owl"), ws.picture("Snowy Owl")
        out = T.execute(ws.session, ws.gid, T.plan_from_assets(ws.session, ws.gid, "artwork", "ornament", [str(a.id), str(b.id)]))
        assert out["created"] == 2 and len(out["entry_ids"]) == 2
        ws.session.expire_all()
        rows = ws.session.query(Entries).filter(Entries.id.in_([uuid.UUID(i) for i in out["entry_ids"]])).order_by(Entries.slug).all()
        assert [e.title for e in rows] == ["Snowy Owl", "Snowy Owl"]
        assert sorted(e.slug for e in rows) == ["snowy-owl", "snowy-owl-2"]
        assert {e.status for e in rows} == {"inbox"} and {str(e.created_by) for e in rows} == {"None"}
        for e in rows:
            link = ws.session.query(EntryAssets).filter_by(entry_id=e.id).one()
            assert (link.role, link.position, e.data_json["image"]) == ("featured", 0, str(link.asset_id))
            assert e.data_json["price"] == 85
        tag_slugs = {s for (s,) in ws.session.query(Tags.slug).join(EntryTags, EntryTags.tag_id == Tags.id).filter(EntryTags.entry_id == rows[0].id)}
        assert tag_slugs == {"ornaments", "hand-painted"}
        held = {c for (c,) in ws.session.query(Collections.slug).join(EntryCollections).filter(EntryCollections.entry_id == rows[0].id)}
        assert "shop" in held and "inbox" in held  # the hand-picked one, and the smart Inbox as its listener would
        [event] = _events()
        assert event[1].created == 2 and event[1].template == "ornament" and "made 2 artworks" in event[2]
        assert not _events("entry_created")

    def test_a_picture_already_made_into_an_entry_fills_that_entry_instead(self, ws):
        a, b = ws.picture("Snowy Owl"), ws.picture("Blue Jay")
        first = T.execute(ws.session, ws.gid, T.plan_from_assets(ws.session, ws.gid, "artwork", "ornament", [str(a.id)]))
        again = T.describe(T.plan_from_assets(ws.session, ws.gid, "artwork", "ornament", [str(a.id), str(b.id)]))
        assert [r["action"] for r in again["rows"]] == ["skip", "create"]
        assert again["rows"][0]["entry_id"] == first["entry_ids"][0] and "already has everything" in again["rows"][0]["note"]
        # One the AI made before (the picture in its image field, not attached, no price): filled, not made twice.
        old = ws.entry("Ornament 7", image=str(b.id), medium="Oil")
        out = T.execute(ws.session, ws.gid, T.plan_from_assets(ws.session, ws.gid, "artwork", "ornament", [str(b.id)]))
        assert out["updated"] == 1 and out["created"] == 0
        ws.session.expire_all()
        e = ws.session.get(Entries, old.id)
        assert e.title == "Ornament 7" and e.data_json["medium"] == "Oil" and e.data_json["price"] == 85  # fill-empty
        assert ws.session.query(EntryAssets).filter_by(entry_id=old.id, asset_id=b.id).one().role == "featured"

    def test_replace_overwrites_what_an_entry_has_title_included(self, ws):
        b = ws.picture("Blue Jay")
        old = ws.entry("Ornament 7", image=str(b.id), medium="Oil")
        T.execute(ws.session, ws.gid, T.plan_from_assets(ws.session, ws.gid, "artwork", "ornament", [str(b.id)], replace=True))
        ws.session.expire_all()
        e = ws.session.get(Entries, old.id)
        assert e.title == "Blue Jay" and e.data_json["medium"] == "Acrylic and Ink on Ceramic"

    def test_a_row_with_an_error_stops_everything(self, ws):
        required = {"fields": [*SCHEMA["fields"], {"key": "story", "type": "text", "label": "Story", "required": True}]}
        ws.type.schema_json = required
        ws.session.commit()
        a = ws.picture("Snowy Owl")
        plan = T.plan_from_assets(ws.session, ws.gid, "artwork", "ornament", [str(a.id)])
        assert T.describe(plan)["rows"][0]["error"] == "story: Required field is missing or null"
        before = _count(ws)
        with pytest.raises(T.TemplateError, match="Nothing was changed"):
            T.execute(ws.session, ws.gid, plan)
        assert _count(ws) == before

    def test_unknown_things_are_named(self, ws):
        a = ws.picture("Snowy Owl")
        with pytest.raises(T.TemplateNotFound, match="templates: ornament"):
            T.plan_from_assets(ws.session, ws.gid, "artwork", "nope", [str(a.id)])
        with pytest.raises(T.TemplateNotFound, match="no picture 'gone'"):
            T.plan_from_assets(ws.session, ws.gid, "artwork", "ornament", ["gone"])
        with pytest.raises(T.TemplateError, match="more than 200"):
            T.plan_from_assets(ws.session, ws.gid, "artwork", "ornament", [str(uuid.uuid4()) for _ in range(201)])


class TestBulk:
    @staticmethod
    def _statements(ws, n: int) -> int:
        ids = ws.pictures(n)
        engine = ws.session.get_bind()
        seen: list = []

        def count(conn, cursor, statement, *args):
            seen.append(statement)

        sa.event.listen(engine, "before_cursor_execute", count)
        try:
            T.execute(ws.session, ws.gid, T.plan_from_assets(ws.session, ws.gid, "artwork", "ornament", ids))
        finally:
            sa.event.remove(engine, "before_cursor_execute", count)
        return len(seen)

    def test_the_statement_count_does_not_grow_with_the_number_of_entries(self, ws):
        self._statements(ws, 1)  # the first run makes the template's tags; after that every run reads the same
        assert self._statements(ws, 5) == self._statements(ws, 60)

    def test_a_hundred_entries_are_made_fast(self, ws):
        ids = ws.pictures(100)
        started = time.monotonic()
        out = T.execute(ws.session, ws.gid, T.plan_from_assets(ws.session, ws.gid, "artwork", "ornament", ids))
        took = time.monotonic() - started
        print(f"\n100 entries from a template ({ws.session.get_bind().dialect.name}, plan + make): {took:.3f}s")  # noqa: T201
        assert out["created"] == 100 and took < 5


# ── Filling existing entries ───────────────────────────────────────────────────


class TestApply:
    def test_fill_empty_by_default_and_the_status_is_never_changed(self, ws):
        b = ws.picture("Blue Jay")
        e = ws.entry("Ornament 3", medium="Oil")
        ws.session.add(EntryAssets(entry_id=e.id, asset_id=b.id, position=0))
        ws.session.commit()
        out = T.execute(ws.session, ws.gid, T.plan_for_entries(ws.session, ws.gid, "artwork", "ornament", [str(e.id)]))
        assert out["updated"] == 1
        ws.session.expire_all()
        e = ws.session.get(Entries, e.id)
        assert e.data_json["medium"] == "Oil" and e.data_json["size"] == '3"' and e.status == "draft"
        assert e.data_json["image"] == str(b.id)  # its picture (attached, none in the field) goes in the image field
        assert e.summary.startswith("Ornament 1 of the ")

    def test_an_entry_with_no_picture_leaves_out_what_needs_one(self, ws):
        e = ws.entry("Plain")
        ws.type.templates_json = T.check_templates([{**ORNAMENT, "summary": "{asset.name}, hand painted"}], SCHEMA)
        ws.session.commit()
        out = T.describe(T.plan_for_entries(ws.session, ws.gid, "artwork", "ornament", [str(e.id)]))
        row = out["rows"][0]
        assert row["action"] == "fill" and "summary" not in row["changes"] and "left out summary" in row["note"]

    def test_published_and_other_types_are_left_alone(self, ws):
        live = ws.entry("Live", status="published")
        other = EntryTypes(session=ws.session, group_id=ws.gid, name="Note", slug="note", schema_json={})
        ws.session.add(other)
        ws.session.flush()
        note = Entries(session=ws.session, group_id=ws.gid, entry_type_id=other.id, title="N", slug=f"n-{uuid.uuid4().hex[:4]}")
        ws.session.add(note)
        ws.session.commit()
        out = T.describe(T.plan_for_entries(ws.session, ws.gid, "artwork", "ornament", [str(live.id), str(note.id)]))
        assert [r["action"] for r in out["rows"]] == ["skip", "skip"]
        assert out["rows"][0]["note"].startswith("published") and out["rows"][1]["note"] == "not an entry of type Artwork"


# ── REST ───────────────────────────────────────────────────────────────────────


def _sign_in(ws, role: WorkspaceRole, who: str = "editor") -> TestClient:
    from marvin.db.models.users.roles import workspace_role_has_higher_or_equal_privilege

    def role_in(group_id):
        return role if str(group_id) == str(ws.gid) else None

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=ws.users[who],
        group_id=ws.gid,
        active_group_id=ws.gid,
        admin=False,
        is_superuser=False,
        full_name=who,
        email=f"{who}@t.test",
        platform_role=PlatformRole.NONE,
        workspace_memberships=[SimpleNamespace(group_id=ws.gid, workspace_role=role)],
        get_workspace_role=role_in,
        has_workspace_role=lambda group_id, required: role_in(group_id) is not None
        and workspace_role_has_higher_or_equal_privilege(role_in(group_id), required),
    )
    return TestClient(app)


class TestRest:
    def test_preview_then_create(self, ws):
        a = ws.picture("Snowy Owl")
        client = _sign_in(ws, WorkspaceRole.AUTHOR, "author")
        body = {"entryType": "artwork", "template": "ornament", "assets": [str(a.id)]}
        r = client.post("/api/platform/entries/from-template", json=body)
        assert r.status_code == 200, r.text
        assert r.json()["preview"] is True and r.json()["rows"][0]["title"] == "Snowy Owl" and not _events()
        r = client.post("/api/platform/entries/from-template", json={**body, "preview": False})
        assert r.status_code == 200, r.text
        made = r.json()
        assert made["created"] == 1 and made["rows"][0]["entryId"] == made["entryIds"][0]
        ws.session.expire_all()
        assert str(ws.session.get(Entries, uuid.UUID(made["entryIds"][0])).created_by) == str(ws.users["author"])

    def test_a_viewer_may_not_and_unknown_templates_are_404(self, ws):
        a = ws.picture("Snowy Owl")
        body = {"entryType": "artwork", "template": "ornament", "assets": [str(a.id)]}
        assert _sign_in(ws, WorkspaceRole.VIEWER).post("/api/platform/entries/from-template", json=body).status_code == 403
        r = _sign_in(ws, WorkspaceRole.EDITOR).post("/api/platform/entries/from-template", json={**body, "template": "nope"})
        assert r.status_code == 404 and "templates: ornament" in r.json()["detail"]

    def test_an_author_fills_only_their_own_entries(self, ws):
        mine, theirs = ws.entry("Mine", owner="author"), ws.entry("Theirs", owner="other")
        client = _sign_in(ws, WorkspaceRole.AUTHOR, "author")
        body = {"entryType": "artwork", "template": "ornament", "entries": [str(mine.id), str(theirs.id)], "preview": False}
        assert client.post("/api/platform/entries/apply-template", json=body).status_code == 403
        r = client.post("/api/platform/entries/apply-template", json={**body, "entries": [str(mine.id)]})
        assert r.status_code == 200 and r.json()["updated"] == 1
        r = _sign_in(ws, WorkspaceRole.EDITOR).post("/api/platform/entries/apply-template", json={**body, "preview": True})
        assert r.status_code == 200 and r.json()["fill"] == 1  # mine is full now; theirs would be filled by an editor

    def test_the_type_carries_its_templates(self, ws):
        r = _sign_in(ws, WorkspaceRole.EDITOR).get(f"/api/platform/entry-types/{ws.type.id}")
        assert r.status_code == 200 and r.json()["templatesJson"][0]["assetField"] == "image"
        r = _sign_in(ws, WorkspaceRole.ADMIN).patch(
            f"/api/platform/entry-types/{ws.type.id}", json={"templatesJson": [{**ORNAMENT, "title": "{asset.title}"}]}
        )
        assert r.status_code == 400 and "{asset.title}" in r.json()["detail"]


# ── Workflow steps ─────────────────────────────────────────────────────────────


class TestWorkflowSteps:
    def test_preview_then_create_with_the_preview_s_todo(self, ws):
        from marvin.services.automation.actions.entry_templates import run_create_entries_from_template_action as run

        a, b = ws.picture("Snowy Owl"), ws.picture("Blue Jay")
        step = {"kind": "create_entries_from_template", "entry_type": "artwork", "template": "ornament", "assets": "${steps.pick.output.ids}"}
        context = {"steps": {"pick": {"output": {"ids": [str(a.id), {"id": str(b.id)}]}}}, "depth": 0}
        before = _count(ws)
        preview = run(ws.session, ws.gid, step, context)
        assert preview["todo"] == 2 and [r["title"] for r in preview["rows"]] == ["Snowy Owl", "Blue Jay"] and _count(ws) == before
        dry = run(ws.session, ws.gid, {**step, "mode": "create", "confirm_total": 2}, context, dry_run=True)
        assert dry["dry_run"] and _count(ws) == before
        made = run(ws.session, ws.gid, {**step, "mode": "create", "confirm_total": 2}, context)
        assert made["created"] == 2 and _count(ws) == before + 2

    def test_a_create_that_no_longer_matches_its_preview_changes_nothing(self, ws):
        from marvin.services.automation.actions.base import AutomationActionError
        from marvin.services.automation.actions.entry_templates import run_create_entries_from_template_action as run

        a = ws.picture("Snowy Owl")
        step = {"kind": "create_entries_from_template", "entry_type": "artwork", "template": "ornament", "assets": [str(a.id)]}
        before = _count(ws)
        with pytest.raises(AutomationActionError, match="the preview counted 3 to do, there are 1 now"):
            run(ws.session, ws.gid, {**step, "mode": "create", "confirm_total": 3}, {})
        assert _count(ws) == before

    def test_apply_needs_an_editor_author(self, ws):
        from marvin.services.automation.actions.base import AutomationActionError
        from marvin.services.automation.actions.entry_templates import run_apply_template_action as run
        from marvin.services.automation.authz import ROLE_AUTHOR, ROLE_EDITOR

        e = ws.entry("Ornament 3")
        step = {"kind": "apply_template", "entry_type": "artwork", "template": "ornament", "entries": [str(e.id)]}
        with pytest.raises(AutomationActionError, match="requires role"):
            run(ws.session, ws.gid, step, {}, authorizer_role=ROLE_AUTHOR)
        out = run(ws.session, ws.gid, {**step, "mode": "apply", "confirm_total": 1}, {}, authorizer_role=ROLE_EDITOR)
        assert out["updated"] == 1

    def test_the_definition_and_its_validation(self):
        from pydantic import TypeAdapter, ValidationError

        from marvin.schemas.group.automation_definition import Action
        from marvin.services.automation.validation import unasked_template_issues

        step = {"kind": "create_entries_from_template", "entry_type": "artwork", "template": "ornament", "assets": ["x"], "mode": "create"}
        with pytest.raises(ValidationError, match="confirm_total"):
            TypeAdapter(Action).validate_python(step)
        TypeAdapter(Action).validate_python({**step, "confirm_total": "${steps.preview.output.todo}"})
        on_event = {"trigger": {"type": "event"}, "actions": [{**step, "confirm_total": 1}]}
        assert "without asking" in unasked_template_issues(on_event)[0]["message"]
        assert not unasked_template_issues({"trigger": {"type": "manual"}, "actions": [{**step, "confirm_total": 1}]})
        replacing = {"trigger": {"type": "manual"}, "actions": [{**step, "confirm_total": 1, "replace": True}]}
        assert "replaces what entries already have" in unasked_template_issues(replacing)[0]["message"]
        asked = {"trigger": {"type": "event"}, "actions": [{"kind": "approval"}, {**step, "confirm_total": 1, "replace": True}]}
        assert not unasked_template_issues(asked)
