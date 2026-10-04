"""Capability routing — discover connected integrations that provide a given capability.

The single entry point ``integrations_providing(kind, group_id)`` is what a capability resolver
(e.g. media enrichment) calls *first*, before falling back to the workspace model or local code.
It returns pre-authorized handlers (secret resolved, context built), highest-priority first, with
uninstalled/disabled integrations filtered out.

Handlers are pure with respect to Marvin: an image goes in as base64 (the resolver resolves an
asset → bytes), and the provider returns base64 bytes or a URL. The resolver owns all asset I/O —
the provider never touches the database.

Cost/logging: a paid capability provider surfaces a ``usage`` block in its output
(``{provider_type, model, input_tokens, output_tokens, total_tokens}``); the handler records an
``ai_executions`` row (the source of truth for the monthly AI-spend total) and emits
``ai_operation_executed`` (so the spend shows in the event log and is subscribable). Both are
best-effort — a logging/emit failure never breaks the capability call.

Canonical input/output dict shapes per capability kind (the resolver builds inputs / reads outputs):

    image.generate  in {prompt, count?, reference_image_b64?}     out {images: [{image_b64|url}]}
    image.edit      in {image_b64, prompt, strength?}             out {image_b64|url}
    image.describe  in {image_b64, prompt?}                       out {text}
    image.search    in {query, limit?}                            out {results: [{url, metadata?}]}
    image.upscale   in {image_b64, factor?}                       out {image_b64|url}
"""

import time
from dataclasses import dataclass, field

from marvin_integration_sdk import IntegrationContext, IntegrationProvider, get_provider
from pydantic import UUID4

from marvin.core.root_logger import get_logger

from .http_client import build_http

logger = get_logger(__name__)


@dataclass
class CapabilityHandler:
    """A uniform, pre-authorized handle to one connected integration's capability action."""

    capability: str
    priority: int
    cost_hint: str | None
    requires_approval: bool
    integration_id: UUID4
    integration_name: str
    group_id: UUID4

    _provider: IntegrationProvider = field(repr=False)
    _action_key: str = field(repr=False)
    _ctx: IntegrationContext = field(repr=False)
    _model: str | None = field(repr=False, default=None)

    def invoke(self, inputs: dict) -> dict:
        """Run the capability with the canonical inputs; returns the canonical outputs.

        Records cost/usage against the monthly AI spend (best-effort) around the call.
        """
        start = time.monotonic()
        error: Exception | None = None
        output: dict = {}
        try:
            output = self._provider.run_action(self._action_key, inputs, self._ctx)
        except Exception as e:  # noqa: BLE001 — log the failed execution, then re-raise unchanged
            error = e
        elapsed_ms = int((time.monotonic() - start) * 1000)

        self._log_execution(inputs, output, elapsed_ms, error)
        # Connection scope: the provider's error policy may alert admins (notify only — nothing to
        # review or retry here); a success resolves the connection's open alerts.
        from . import errors

        if error is not None:
            errors.connection_failed(self.group_id, self.integration_id, self._provider, self._action_key, error, source="capability")
            raise error
        errors.connection_succeeded(self.group_id, self.integration_id)
        return output

    @staticmethod
    def _sanitize(value, _depth: int = 0):
        """Strip large blobs (base64 images, etc.) so the audit row stays readable.

        Long strings — anything over ~256 chars, which is every image payload — collapse to a
        ``<N chars omitted>`` marker; small fields (``usage``, counts, urls, prompts) pass through.
        """
        if _depth > 6:
            return "<…>"
        if isinstance(value, str):
            return value if len(value) <= 256 else f"<{len(value)} chars omitted>"
        if isinstance(value, dict):
            return {k: CapabilityHandler._sanitize(v, _depth + 1) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [CapabilityHandler._sanitize(v, _depth + 1) for v in value]
        return value

    def _log_flags(self, session) -> tuple[bool, bool]:
        """(log_inputs, log_outputs) from the workspace logging_config — inputs off, outputs on by default."""
        from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

        settings = session.query(WorkspaceAISettingsModel).filter_by(group_id=self.group_id).first()
        cfg = (settings.logging_config if settings else None) or {}
        return bool(cfg.get("log_inputs", False)), bool(cfg.get("log_outputs", True))

    def _log_execution(self, inputs: dict, output: dict, elapsed_ms: int, error: Exception | None) -> None:
        """Best-effort: write an ai_executions row + emit the ai_operation_executed event."""
        try:
            from marvin.db.db_setup import session_context
            from marvin.db.models.groups.ai_executions import AIExecutionModel
            from marvin.services.ai.pricing import estimate_cost

            usage = (output or {}).get("usage") or {}
            provider_type = usage.get("provider_type") or "integration"
            model_id = usage.get("model") or self._model or "unknown"
            pt = int(usage.get("input_tokens") or 0)
            ct = int(usage.get("output_tokens") or 0)
            tot = int(usage.get("total_tokens") or (pt + ct))
            cost = estimate_cost(provider_type, model_id, pt, ct) if (pt or ct) else None
            status = "failed" if error else "completed"

            with session_context() as session:
                log_inputs, log_outputs = self._log_flags(session)
                row = AIExecutionModel(
                    session=session,
                    group_id=self.group_id,
                    operation_slug=self.capability,
                    provider_type=provider_type,
                    model_id=model_id,
                    status=status,
                    trigger_type="capability",
                    input_json=self._sanitize(inputs) if log_inputs else None,
                    output_json=self._sanitize(output) if log_outputs else None,
                    prompt_tokens=pt or None,
                    completion_tokens=ct or None,
                    total_tokens=tot or None,
                    estimated_cost_usd=cost,
                    duration_ms=elapsed_ms,
                    error_message=str(error) if error else None,
                    metadata_json={"integration": self.integration_name, "integration_id": str(self.integration_id)},
                )
                session.add(row)
                session.commit()
                exec_id = row.id
                from marvin.db.models.groups.groups import Groups

                g = session.get(Groups, self.group_id)
                group_name = g.name if g else None
            self._emit(provider_type, model_id, tot, cost, status, exec_id, group_name, error)
        except Exception as e:  # noqa: BLE001 — logging must never break the capability call
            logger.warning(f"[capability] execution logging failed: {e}")

    def _emit(self, provider_type, model_id, total_tokens, cost, status, exec_id, group_name, error) -> None:
        """Emit ai_operation_executed so capability spend shows in the event log (best-effort)."""
        try:
            from marvin.services.event_bus_service.event_bus_service import EventBusService
            from marvin.services.event_bus_service.event_types import EventAIOperationData, EventTypes

            EventBusService(bg_tasks=None).dispatch(
                integration_id=f"capability:{self.capability}",
                group_id=self.group_id,
                event_type=EventTypes.ai_operation_executed if status == "completed" else EventTypes.ai_operation_failed,
                document_data=EventAIOperationData(
                    operation_slug=self.capability,
                    provider_type=provider_type,
                    model_id=model_id,
                    status=status,
                    execution_id=exec_id,
                    total_tokens=total_tokens or None,
                    estimated_cost_usd=cost,
                    error_message=str(error) if error else None,
                    workspace_id=self.group_id,
                    workspace_name=group_name,
                ),
                message=f"capability {self.capability} via {self.integration_name}",
                entity_id=exec_id,
                entity_type="ai_execution" if exec_id else None,
            )
        except Exception as e:  # noqa: BLE001 — event emit is best-effort, never breaks the call
            logger.warning(f"[capability] event emit failed: {e}")


@dataclass
class _Snapshot:
    provider: IntegrationProvider
    action_key: str
    capability: str
    priority: int
    cost_hint: str | None
    requires_approval: bool
    config: dict
    secret_ref: str | None
    integration_id: UUID4
    integration_name: str
    group_id: UUID4
    model: str | None


def _read_snapshots(kind: str, group_id: UUID4) -> list[_Snapshot]:
    """Read enabled group integrations whose (installed) provider has an action advertising `kind`."""
    from marvin.db.db_setup import session_context
    from marvin.db.models.groups.integrations import IntegrationModel

    snaps: list[_Snapshot] = []
    with session_context() as session:
        rows = session.query(IntegrationModel).filter(IntegrationModel.group_id == group_id, IntegrationModel.enabled.is_(True)).all()
        for row in rows:
            try:
                provider = get_provider(row.provider)  # skip uninstalled providers
            except KeyError:
                continue
            for action in provider.actions:
                if action.capability == kind:
                    snaps.append(
                        _Snapshot(
                            provider=provider,
                            action_key=action.key,
                            capability=action.capability,
                            priority=action.priority,
                            cost_hint=action.cost_hint,
                            requires_approval=action.requires_approval,
                            config=row.config or {},
                            secret_ref=row.secret_ref,
                            integration_id=row.id,
                            integration_name=row.name,
                            group_id=group_id,
                            model=(row.config or {}).get("model"),
                        )
                    )
    return snaps


def _build_handlers(snaps: list[_Snapshot], group_id: UUID4, resolve_secret_fn) -> list[CapabilityHandler]:
    """Assemble pre-authorized handlers from snapshots, sorted highest-priority-first."""
    handlers: list[CapabilityHandler] = []
    for snap in snaps:
        secret = resolve_secret_fn(snap.secret_ref, group_id) if snap.secret_ref else None
        ctx = IntegrationContext(config=snap.config, secret=secret, logger=logger, http=build_http())
        handlers.append(
            CapabilityHandler(
                capability=snap.capability,
                priority=snap.priority,
                cost_hint=snap.cost_hint,
                requires_approval=snap.requires_approval,
                integration_id=snap.integration_id,
                integration_name=snap.integration_name,
                group_id=snap.group_id,
                _provider=snap.provider,
                _action_key=snap.action_key,
                _ctx=ctx,
                _model=snap.model,
            )
        )
    handlers.sort(key=lambda h: h.priority, reverse=True)
    return handlers


def integrations_providing(kind: str, group_id: UUID4) -> list[CapabilityHandler]:
    """Connected integrations in this workspace that provide capability ``kind``.

    Highest-priority first; each handler is pre-authorized (secret resolved, context built).
    Uninstalled or disabled integrations are filtered out. Returns [] if none — the caller
    treats that as "no integration for this kind" and falls through to its next backend.
    """
    from marvin.services.secrets.resolver import resolve_secret

    return _build_handlers(_read_snapshots(kind, group_id), group_id, resolve_secret)
