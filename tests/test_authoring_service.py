"""Tests for AuthoringService association helpers (the parts that don't need a live model).

Focus: _attach_existing_resources must resolve a resource by id, slug, OR name. The grounding block
lists resources by *name*, so the model returns names — slug-only resolution silently linked nothing
(a bug that affected both compose and revise).
"""

import uuid

from pytest import fixture

from marvin.db.models.platform import Entries, EntryResources, EntryTypes, Resources
from marvin.services.ai.authoring import AuthoringService


@fixture
def workspace(db_session):
    """A throwaway workspace with one entry + one resource ('Waxed Canvas' / 'waxed-canvas')."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"auth-{marker}", slug=f"auth-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()

    uid = uuid.uuid4()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=f"u-{marker}",
            email=f"u-{marker}@t.test",
            full_name="U",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )
    et = EntryTypes(session=db_session, group_id=gid, name="Note", slug="note", schema_json={})
    et.id = uuid.uuid4()
    db_session.add(et)
    db_session.flush()
    entry = Entries(session=db_session, group_id=gid, entry_type_id=et.id, title="T", slug=f"t-{marker}")
    db_session.add(entry)
    res = Resources(session=db_session, group_id=gid, name="Waxed Canvas", slug="waxed-canvas", resource_type="material", created_by=uid)
    db_session.add(res)
    db_session.commit()

    yield gid, entry.id, res.id

    from marvin.db.models.platform import Assets, EntryAssets

    db_session.query(EntryResources).delete()
    db_session.query(EntryAssets).delete()
    db_session.query(Resources).filter(Resources.group_id == gid).delete()
    db_session.execute(Assets.__table__.delete().where(Assets.group_id == gid))
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.execute(Users.__table__.delete().where(Users.group_id == gid))
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _svc(db_session, gid):
    return AuthoringService(db_session, gid, user=None, provider=None, model=None)


def _count(db_session, entry_id, res_id):
    return db_session.query(EntryResources).filter_by(entry_id=entry_id, resource_id=res_id).count()


def test_attach_existing_resources_resolves_by_name(db_session, workspace):
    # THE regression: the model returns the resource NAME from the grounding, not the slug.
    gid, entry_id, res_id = workspace
    attached = _svc(db_session, gid)._attach_existing_resources(entry_id, ["Waxed Canvas"])
    db_session.commit()  # the caller (compose/revise) commits after
    assert attached == ["waxed-canvas"]
    assert _count(db_session, entry_id, res_id) == 1


def test_attach_existing_resources_resolves_by_slug_and_id(db_session, workspace):
    gid, entry_id, res_id = workspace
    svc = _svc(db_session, gid)
    assert svc._attach_existing_resources(entry_id, ["waxed-canvas"]) == ["waxed-canvas"]  # by slug
    db_session.commit()
    assert svc._attach_existing_resources(entry_id, [str(res_id)]) == []  # by id, already attached → no dup
    db_session.commit()
    assert _count(db_session, entry_id, res_id) == 1


def test_attach_existing_resources_ignores_unknown(db_session, workspace):
    gid, entry_id, res_id = workspace
    assert _svc(db_session, gid)._attach_existing_resources(entry_id, ["Does Not Exist", ""]) == []
    db_session.commit()
    assert _count(db_session, entry_id, res_id) == 0


# ── B2b: recipe-vs-attachment validation ──────────────────────────────────────
def test_validate_recipe_assets_warns_on_missing_hero_and_too_few(db_session, workspace):
    from marvin.schemas.platform.entry_type_recipe import EntryTypeRecipe

    gid, _, _ = workspace
    svc = _svc(db_session, gid)
    recipe = EntryTypeRecipe.model_validate({"assets": {"min": 1, "roles": [{"role": "hero", "required": True}]}})

    warnings = svc._validate_recipe_assets(recipe, [])  # nothing attached
    assert any("at least 1" in w for w in warnings)  # min unmet
    assert any("'hero'" in w for w in warnings)  # required role missing

    assert svc._validate_recipe_assets(recipe, [{"role": "hero", "position": 0}]) == []  # contract satisfied
    assert svc._validate_recipe_assets(EntryTypeRecipe.model_validate({}), []) == []  # no contract → no noise


# ── B2a: apply_fields "resources" target (used when a revise is STAGED for review) ─────
def test_apply_fields_resources_target_attaches_reuse_only(db_session, workspace):
    from marvin.repos.all_repositories import get_repositories

    gid, entry_id, res_id = workspace
    repos = get_repositories(db_session, group_id=gid)

    repos.entries.apply_fields(entry_id, {"resources": ["Waxed Canvas"]})  # by name (as grounding lists them)
    assert _count(db_session, entry_id, res_id) == 1
    repos.entries.apply_fields(entry_id, {"resources": ["waxed-canvas", str(res_id), "Nope"]})  # slug/id dup + unknown
    assert _count(db_session, entry_id, res_id) == 1  # additive + reuse-only: no duplicate, unknown ignored


# ── Compose asset auto-attach: resolve existing assets by name/slug/id (reuse-only) ────
def test_resolve_asset_refs_by_name_slug_id_and_exclude(db_session, workspace):
    from marvin.db.models.platform import Assets
    from marvin.db.models.users.users import Users

    gid, _, _ = workspace
    uid = db_session.query(Users.id).filter(Users.group_id == gid).scalar()
    aid = uuid.uuid4()
    db_session.execute(
        Assets.__table__.insert().values(
            id=aid,
            group_id=gid,
            slug="studio-shot",
            name="Studio Shot",
            original_filename="s.jpg",
            filename="s",
            extension="jpg",
            file_size=1,
            mime_type="image/jpeg",
            asset_type="image",
            checksum="x",
            storage_provider="local",
            storage_key=f"k/{gid.hex[:6]}.jpg",
            uploaded_by=uid,
        )
    )
    db_session.commit()
    svc = _svc(db_session, gid)

    assert svc._resolve_asset_refs(["Studio Shot"]) == [(aid, "studio-shot")]  # by name (grounding lists names)
    assert svc._resolve_asset_refs(["studio-shot"]) == [(aid, "studio-shot")]  # by slug
    assert svc._resolve_asset_refs([str(aid)]) == [(aid, "studio-shot")]  # by id
    assert svc._resolve_asset_refs(["Studio Shot"], exclude_ids=[aid]) == []  # caller already has it
    assert svc._resolve_asset_refs(["nope", "", "Studio Shot", "studio-shot"]) == [(aid, "studio-shot")]  # unknown/blank/dup collapsed


# ── Recipe enrichment: alt-text opt-in gate + best-effort guard ────────────────────────
def test_alt_text_requested_reads_enrichment_flag_and_role_derive(db_session, workspace):
    from marvin.schemas.platform.entry_type_recipe import EntryTypeRecipe

    gid, _, _ = workspace
    svc = _svc(db_session, gid)

    assert svc._alt_text_requested(EntryTypeRecipe.model_validate({"enrichment": {"alt_text": True}})) is True
    assert svc._alt_text_requested(EntryTypeRecipe.model_validate({"assets": {"roles": [{"role": "hero", "derive": ["alt_text"]}]}})) is True
    assert svc._alt_text_requested(EntryTypeRecipe.model_validate({})) is False
    assert svc._alt_text_requested(EntryTypeRecipe.model_validate({"enrichment": {"voice": "wry"}})) is False


def test_recipe_instructions_block_injects_verbatim(db_session, workspace):
    from marvin.schemas.platform.entry_type_recipe import EntryTypeRecipe

    gid, _, _ = workspace
    svc = _svc(db_session, gid)

    block = svc._recipe_instructions_block(EntryTypeRecipe.model_validate({"instructions": "Keep the body to two short paragraphs. No images."}))
    assert "Keep the body to two short paragraphs. No images." in block
    assert "follow these" in block.lower()
    assert svc._recipe_instructions_block(EntryTypeRecipe.model_validate({"instructions": "   "})) == ""  # blank → none
    assert svc._recipe_instructions_block(EntryTypeRecipe.model_validate({})) == ""


def test_recipe_asset_hint_keys_off_required_vs_optional(db_session, workspace):
    from marvin.schemas.platform.entry_type_recipe import EntryTypeRecipe

    gid, _, _ = workspace
    svc = _svc(db_session, gid)

    # A required role → the hint URGES attachment.
    req = svc._recipe_asset_hint(EntryTypeRecipe.model_validate({"assets": {"roles": [{"role": "hero", "required": True}]}}))
    assert "needs images" in req.lower() and "hero" in req

    # min > 0 also counts as needed.
    m = svc._recipe_asset_hint(EntryTypeRecipe.model_validate({"assets": {"roles": [{"role": "hero", "min": 1}]}}))
    assert "needs images" in m.lower()

    # All-optional (like page-with-navigation) → gated on the brief, does NOT urge; states the max.
    opt = svc._recipe_asset_hint(
        EntryTypeRecipe.model_validate({"assets": {"max": 5, "roles": [{"role": "hero", "max": 1}, {"role": "gallery", "max": 4}]}})
    )
    assert "optional" in opt.lower() and "brief explicitly calls" in opt
    assert "needs images" not in opt.lower()
    assert "at most 5" in opt

    assert svc._recipe_asset_hint(EntryTypeRecipe.model_validate({"assets": {"min": 1}})) == ""  # no roles → no hint
    assert svc._recipe_asset_hint(EntryTypeRecipe.model_validate({})) == ""


def test_resolvers_are_group_id_type_safe(db_session, workspace):
    # Regression: a string group_id (as MCP/JSON callers can pass) once made the UUID != str guard
    # always true, silently dropping every asset/resource. Both resolvers must match by value.
    from marvin.db.models.platform import Assets
    from marvin.db.models.users.users import Users

    gid, entry_id, res_id = workspace
    uid = db_session.query(Users.id).filter(Users.group_id == gid).scalar()
    aid = uuid.uuid4()
    db_session.execute(
        Assets.__table__.insert().values(
            id=aid,
            group_id=gid,
            slug="loom",
            name="Loom",
            original_filename="l.jpg",
            filename="l",
            extension="jpg",
            file_size=1,
            mime_type="image/jpeg",
            asset_type="image",
            checksum="y",
            storage_provider="local",
            storage_key=f"k/{gid.hex[:5]}.jpg",
            uploaded_by=uid,
        )
    )
    db_session.commit()

    svc = AuthoringService(db_session, str(gid), user=None, provider=None, model=None)  # STRING group_id
    assert svc._resolve_asset_refs(["Loom"]) == [(aid, "loom")]  # asset resolves
    assert svc._attach_existing_resources(entry_id, ["Waxed Canvas"]) == ["waxed-canvas"]  # resource resolves
    db_session.commit()
    assert _count(db_session, entry_id, res_id) == 1


def test_alt_text_enrichment_noops_without_a_vision_provider(db_session, workspace):
    from marvin.schemas.platform.entry_type_recipe import EntryTypeRecipe

    gid, _, _ = workspace
    svc = _svc(db_session, gid)  # provider=None
    recipe = EntryTypeRecipe.model_validate({"enrichment": {"alt_text": True}})
    assert svc._run_alt_text_enrichment(recipe, [{"asset_id": str(uuid.uuid4())}]) == []  # no provider → skip
