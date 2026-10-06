"""Media enrichment — execute a recipe's ``derive`` media tokens on an entry's images.

Every derivation now routes through ``resolve_capability`` (capability.py), which picks the best
backend by precedence: workspace integration → vision model → local Pillow. In practice today:

  - ``grade:<preset>`` / ``crop:<WxH>`` — local Pillow handler (deterministic, no model, no cost),
    behaviourally identical to Phase 1.
  - ``crop:subject`` — resolves ``image.detect_subject`` (vision provider or an integration) for a
    normalized subject box, then crops locally to it. Skips cleanly when no vision backend exists.
  - ``recipe.enrichment.media`` steps — a generative pipeline (``image.edit`` / ``image.generate``)
    that lights up only when an integration provides the capability; otherwise skipped.

For each produced image we persist a NEW derivative asset (with provenance back to the source) and
link it to the entry under a derived role. The source asset is never mutated. Best-effort (a bad
image never breaks the caller) and idempotent per (source asset, token): a derivative already on
the entry is skipped, so re-running compose won't double-derive.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from marvin.services.ai.media import capability, transforms
from marvin.services.assets.asset_storage_service import AssetStorageService
from marvin.services.storage.provider_factory import get_storage_provider

logger = logging.getLogger(__name__)


class MediaEnrichmentService:
    def __init__(self, session, repos, group_id, user_id=None, provider=None, model=None) -> None:
        self.session = session
        self.repos = repos
        self.group_id = group_id
        self.user_id = user_id
        # Optional vision backend — enables ``crop:subject`` and generative media steps when a
        # vision-capable provider/model is available. Absent → those steps skip cleanly.
        self.provider = provider
        self.model = model
        # Workspace-effective grade presets (built-in defaults + per-workspace overrides), resolved
        # once per run in run_for_entry. None until resolved.
        self._grade_presets: dict | None = None

    def run_for_entry(self, entry_id) -> list[str]:
        """Derive media variants for one entry per its type's recipe. Returns human-readable
        summaries of what was produced (empty when the recipe declares no media tokens)."""
        from marvin.db.models.platform.assets import Assets
        from marvin.db.models.platform.entries import Entries
        from marvin.db.models.platform.entry_assets import EntryAssets
        from marvin.db.models.platform.entry_types import EntryTypes
        from marvin.schemas.platform.entry_type_recipe import EntryTypeRecipe

        entry = self.session.get(Entries, entry_id)
        if entry is None or not entry.entry_type_id:
            return []
        entry_type = self.session.get(EntryTypes, entry.entry_type_id)
        if entry_type is None or not entry_type.recipe_json:
            return []

        try:
            recipe = EntryTypeRecipe.model_validate(entry_type.recipe_json or {})
        except Exception as e:  # noqa: BLE001
            logger.debug("media: recipe parse failed for %s: %s", entry_id, e)
            return []
        if not recipe.assets or not recipe.assets.roles:
            return []

        # Resolve the workspace-effective grade presets once for this run (built-ins + overrides).
        self._grade_presets = self._resolve_grade_presets()

        # role -> media tokens declared for it
        role_tokens = {r.role: [t for t in (r.derive or []) if transforms.is_media_token(t)] for r in recipe.assets.roles}
        role_tokens = {role: toks for role, toks in role_tokens.items() if toks}
        if not role_tokens:
            return []

        assets_svc = AssetStorageService(self.repos, get_storage_provider())

        # Derivatives already on this entry — keyed (source_asset_id, token) — for idempotency.
        already: set[tuple[str, str]] = set()
        for a in entry.assets:
            mj = a.metadata_json or {}
            if mj.get("derived_from") and mj.get("derivation"):
                already.add((str(mj["derived_from"]), str(mj["derivation"])))

        summaries: list[str] = []
        for ea in list(entry.entry_assets):
            tokens = role_tokens.get(ea.role)
            if not tokens:
                continue
            src = self.session.get(Assets, ea.asset_id)
            if src is None or not transforms.can_transform(src.mime_type):
                continue
            for token in tokens:
                if (str(src.id), token) in already:
                    continue
                op, _, arg = token.partition(":")
                slug = f"{src.slug}--{op}-{arg}".replace(":", "-").replace("/", "-")[:200]
                try:
                    # Reuse an existing derivative of this (source, token) — the transform is
                    # deterministic, so a hero shared by two entries produces one graded asset
                    # linked to both (reuse-first, like resources).
                    new_asset = (
                        self.session.query(Assets)
                        .filter(
                            Assets.group_id == self.group_id,
                            Assets.slug == slug,
                        )
                        .first()
                    )
                    if new_asset is None:
                        out = self._produce(token, src, assets_svc)
                        if not out:
                            continue
                        name = f"{src.name or src.filename} ({op} {arg})".strip()
                        new_asset = assets_svc.create_derivative(
                            source=src,
                            data=out,
                            group_id=self.group_id,
                            derivation=token,
                            slug=slug,
                            name=name,
                            user_id=self.user_id,
                        )
                    already_linked = (
                        self.session.query(EntryAssets)
                        .filter(
                            EntryAssets.entry_id == entry.id,
                            EntryAssets.asset_id == new_asset.id,
                        )
                        .first()
                    )
                    if already_linked is None:
                        self.session.add(
                            EntryAssets(
                                entry_id=entry.id,
                                asset_id=new_asset.id,
                                role=f"{ea.role}-{op}",
                                position=(ea.position or 0) + 100,
                                metadata_json={"derived_from": str(src.id), "derivation": token},
                            )
                        )
                    self.session.commit()  # each derivative is atomic
                    already.add((str(src.id), token))
                    summaries.append(f"{ea.role}: {token} → {new_asset.slug}")
                except Exception as e:  # noqa: BLE001 — best-effort per asset/token
                    self.session.rollback()
                    logger.warning("media: %s on %s failed: %s", token, getattr(src, "slug", "?"), e)

        summaries.extend(self._run_media_pipeline(entry, recipe, assets_svc))
        return summaries

    # ── Capability routing ─────────────────────────────────────────────────────────────────

    def _produce(self, token: str, src, assets_svc) -> bytes | None:
        """Produce transformed bytes for one ``derive`` token via the resolved capability handler.

        ``grade:*`` / ``crop:<WxH>`` route to the local Pillow handler (deterministic, no cost);
        ``crop:subject`` routes to ``image.detect_subject`` (vision/integration) then crops to the
        returned box. Returns ``None`` (skip) when no handler is available or nothing is produced.
        """
        op, _, arg = token.partition(":")
        data = assets_svc.read_bytes(src)

        if op == "crop" and arg == "subject":
            return self._crop_subject(src, data)

        kind = capability.KIND_GRADE if op == "grade" else capability.KIND_CROP if op == "crop" else None
        if kind is None:
            return None
        handler = capability.resolve_capability(kind, session=self.session, group_id=self.group_id)
        if handler is None:
            return None
        inputs = {"image_bytes": data, "op": op, "arg": arg}
        if op == "grade":
            # Workspace-effective params for this preset (overrides win). Unknown preset → None,
            # and the handler falls back to the built-in lookup or skips (never crashes).
            presets = self._grade_presets if self._grade_presets is not None else self._resolve_grade_presets()
            inputs["params"] = presets.get(arg)
        return handler.invoke(inputs).get("image_bytes")

    def _resolve_grade_presets(self) -> dict:
        """Merge the workspace's ``media_presets`` setting over the built-in ``GRADE_PRESETS`` (a
        workspace preset replaces/extends a built-in by name). Missing/invalid setting → built-ins
        only, so behaviour is identical to today when nothing is configured."""
        from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

        overrides = None
        try:
            row = self.session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
            overrides = getattr(row, "media_presets", None) if row is not None else None
        except Exception as e:  # noqa: BLE001 — a settings read failure must not break enrichment
            logger.debug("media: media_presets read failed for %s: %s", self.group_id, e)
        if isinstance(overrides, dict) and overrides:
            return {**transforms.GRADE_PRESETS, **overrides}
        return dict(transforms.GRADE_PRESETS)

    def _crop_subject(self, src, data: bytes) -> bytes | None:
        """Detect the main subject (vision provider or integration) and crop to it. Skips cleanly
        (returns ``None``) when no vision backend is configured — never raises."""
        handler = capability.resolve_capability(
            capability.KIND_DETECT_SUBJECT,
            session=self.session,
            group_id=self.group_id,
            provider=self.provider,
            model=self.model,
        )
        if handler is None:
            logger.debug("media: crop:subject skipped for %s (no vision/integration backend)", src.slug)
            return None
        # Resolver owns asset I/O: pass the asset id (vision handler reads via ContextBuilder) and
        # base64 bytes (an integration handler is DB-free and consumes bytes in the inputs).
        result = handler.invoke(
            {
                "asset_id": src.id,
                "image_bytes": data,
                "image_b64": base64.b64encode(data).decode("ascii"),
            }
        )
        box = (result or {}).get("box")
        if not box:
            return None
        return transforms.crop_to_box(data, tuple(box))

    # ── enrichment.media generative pipeline (integration-gated scaffolding) ─────────────────

    def _run_media_pipeline(self, entry, recipe, assets_svc) -> list[str]:
        """Execute ``recipe.enrichment.media`` steps: a list of generative image ops.

        Each step is ``{op, target_role, prompt, source_role?, arg?}`` where ``op`` is ``generate``
        or ``edit`` (→ ``image.generate`` / ``image.edit``). For each step we resolve the capability;
        if an integration provides it we fetch the source bytes, invoke (base64 in → bytes/URL out),
        and persist a derivative — approval-gated: generative output is linked but flagged pending
        (junction metadata_json.suggested) for human review. No handler (the common case today) →
        skip. Ready for image-out integrations without requiring them.
        """
        enrichment = getattr(recipe, "enrichment", None)
        steps = enrichment.get("media") if isinstance(enrichment, dict) else None
        if not isinstance(steps, list) or not steps:
            return []

        _KIND = {"generate": capability.KIND_GENERATE, "edit": capability.KIND_EDIT}
        summaries: list[str] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            op = step.get("op")
            if not isinstance(op, str):
                continue
            kind = _KIND.get(op)
            if kind is None:
                continue
            handler = capability.resolve_capability(
                kind,
                session=self.session,
                group_id=self.group_id,
                provider=self.provider,
                model=self.model,
            )
            if handler is None:
                logger.debug("media: pipeline step %r skipped (no %s handler)", op, kind)
                continue
            try:
                summary = self._run_media_step(entry, step, op, handler, assets_svc)
                if summary:
                    summaries.append(summary)
            except Exception as e:  # noqa: BLE001 — best-effort per step
                self.session.rollback()
                logger.warning("media: pipeline step %r failed: %s", op, e)
        return summaries

    def _run_media_step(self, entry, step: dict, op: str, handler, assets_svc) -> str | None:
        """Run one resolved generative media step: fetch the source image (from ``source_role``, or
        the first linked image), invoke the handler, persist + link (flagged pending review when
        the handler requires approval)."""
        from marvin.db.models.platform.assets import Assets
        from marvin.db.models.platform.entry_assets import EntryAssets

        source_role = step.get("source_role")
        src = None
        for ea in entry.entry_assets:
            if source_role and ea.role != source_role:
                continue
            a = self.session.get(Assets, ea.asset_id)
            if a and transforms.can_transform(a.mime_type):
                src = a
                break
        if src is None:
            return None

        data = assets_svc.read_bytes(src)
        result = (
            handler.invoke(
                {
                    "asset_id": src.id,
                    "image_bytes": data,
                    "image_b64": base64.b64encode(data).decode("ascii"),
                    "prompt": step.get("prompt"),
                    "arg": step.get("arg"),
                }
            )
            or {}
        )

        out = self._materialize(result)
        if not out:
            return None

        derivation = f"media:{op}"
        target_role = step.get("target_role") or f"{src.slug}-{op}"
        slug = f"{src.slug}--{op}".replace(":", "-").replace("/", "-")[:200]
        new_asset = assets_svc.create_derivative(
            source=src,
            data=out,
            group_id=self.group_id,
            derivation=derivation,
            slug=slug,
            name=f"{src.name or src.filename} ({op})".strip(),
            user_id=self.user_id,
            extra_metadata={"media_op": op, "prompt": step.get("prompt")},
        )

        # Approval gate: generative output is ALWAYS linked to the entry, but when the handler
        # requires approval the junction is flagged pending (metadata_json.suggested) so the
        # workspace UI can review it and the publish API filters it out. Non-gated output links
        # as a normal derivative (the prior auto-link behaviour).
        requires_approval = getattr(handler, "requires_approval", True)
        metadata_json: dict[str, Any] = {"derived_from": str(src.id), "derivation": derivation}
        if requires_approval:
            metadata_json.update(
                {
                    "suggested": True,
                    "media_op": op,
                    "prompt": step.get("prompt"),
                }
            )
        already_linked = (
            self.session.query(EntryAssets)
            .filter(
                EntryAssets.entry_id == entry.id,
                EntryAssets.asset_id == new_asset.id,
            )
            .first()
        )
        if already_linked is None:
            self.session.add(
                EntryAssets(
                    entry_id=entry.id,
                    asset_id=new_asset.id,
                    role=target_role,
                    position=0,
                    metadata_json=metadata_json,
                )
            )
        self.session.commit()
        state = "suggested" if requires_approval else "linked"
        return f"{op}: {src.slug} → {new_asset.slug} ({state})"

    def _materialize(self, result: dict) -> bytes | None:
        """Turn a handler's output into bytes, across the canonical output shapes:
        - local handlers → raw ``image_bytes``
        - ``image.generate`` → ``{images: [{image_b64 | url}]}`` (first image)
        - ``image.edit`` / ``image.upscale`` → ``{image_b64 | url}``
        The resolver owns this I/O so integration handlers can stay DB-free (bytes/URL out)."""
        if not isinstance(result, dict):
            return None
        # local handler: raw bytes
        if result.get("image_bytes"):
            return result["image_bytes"]
        # generate: pick the first of the images array
        images = result.get("images")
        if isinstance(images, list) and images and isinstance(images[0], dict):
            result = images[0]
        # base64 (edit/upscale/generate) or a URL to fetch
        b64 = result.get("image_b64")
        if b64:
            try:
                return base64.b64decode(b64)
            except Exception as e:  # noqa: BLE001
                logger.warning("media: bad base64 image: %s", e)
                return None
        url = result.get("url")
        if not url:
            return None
        try:
            import httpx

            resp = httpx.get(url, timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
            return resp.content
        except Exception as e:  # noqa: BLE001 — a bad URL just yields no derivative
            logger.warning("media: could not fetch generated image %s: %s", url, e)
            return None
