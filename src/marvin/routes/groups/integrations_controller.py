"""
Workspace Integrations API.

CRUD for credentialed connections to external services, plus a provider catalog, a
health check, and an action test-fire. Credentials are written to the configured secret
backend and referenced by `secret_ref` — never stored on the row or returned.
"""

import re
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4
from slugify import slugify

from marvin.core.root_logger import get_logger
from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_admin
from marvin.schemas.group.integration import (
    AlertRouting,
    AlertRoutingUpdate,
    IntegrationActionResult,
    IntegrationAttention,
    IntegrationCheckResult,
    IntegrationCreate,
    IntegrationErrorOverrides,
    IntegrationEventSubscriptionCreate,
    IntegrationEventSubscriptionRead,
    IntegrationEventSubscriptionUpdate,
    IntegrationPluginInfo,
    IntegrationProviderInfo,
    IntegrationRead,
    IntegrationResolveResult,
    IntegrationUpdate,
)
from marvin.services.integrations import (
    INTEGRATION_REGISTRY,
    IntegrationContext,
    IntegrationProvider,
    build_http,
    errors,
    get_provider,
    list_providers,
    load_reports,
)
from marvin.services.secrets import get_secret_backend
from marvin.services.secrets.resolver import resolve_secret

router = APIRouter(prefix="/groups/integrations")
logger = get_logger(__name__)


def _secret_ref(slug: str) -> str:
    """Slug under which this integration's credential lives in the secret backend."""
    return f"INTEGRATION_{slug.upper()}"


_SECRET_REFERENCE = re.compile(r"^\{\{\s*([A-Za-z0-9_]+)\s*\}\}$")


def _referenced_secret(credential: str, group_id) -> str | None:
    """`{{SLUG}}` → that workspace secret's slug, so the integration reads the shared secret instead
    of holding a copy (one place to rotate it). A plain value → None (store it as before). A
    reference to a secret that doesn't exist is refused rather than saved broken."""
    match = _SECRET_REFERENCE.match(credential.strip())
    if not match:
        return None
    slug = match.group(1)
    if resolve_secret(slug, group_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No workspace secret '{slug}' — create it first, or paste the value itself.",
        )
    return slug


def _owns_secret(row: IntegrationModel) -> bool:
    """Whether the stored secret is this integration's own copy — never a referenced workspace
    secret, which deleting or rotating the integration must not touch."""
    return row.secret_ref == _secret_ref(row.slug)


def _to_read(row: IntegrationModel, alerts: list | None = None) -> IntegrationRead:
    # If the provider's package was uninstalled, the row is orphaned — surface that instead of a
    # stale "ok", so the UI can grey it out rather than pretend it still works.
    available = row.provider in INTEGRATION_REGISTRY
    return IntegrationRead(
        id=row.id,
        provider=row.provider,
        name=row.name,
        slug=row.slug,
        enabled=row.enabled,
        config=row.config,
        has_credential=bool(row.secret_ref),
        credential_secret=None if not row.secret_ref or _owns_secret(row) else row.secret_ref,
        status=row.status if available else "unavailable",
        last_checked_at=row.last_checked_at,
        last_error=row.last_error if available else f"Provider '{row.provider}' is not installed.",
        attention=[
            IntegrationAttention(
                id=a.id, code=a.code, message=a.message, count=a.count, first_at=a.first_at, last_at=a.last_at, samples=a.samples or []
            )
            for a in alerts or []
        ],
        error_overrides=row.error_overrides or {},
    )


@controller(router)
class IntegrationsController(BaseUserController):
    """Workspace integration management."""

    # ---- helpers -----------------------------------------------------------------

    def _get_or_404(self, integration_id: UUID4) -> IntegrationModel:
        row = self.session.get(IntegrationModel, integration_id)
        if not row or row.group_id != self.group_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found.")
        return row

    def _provider_or_none(self, slug: str) -> IntegrationProvider | None:
        """The provider, or None if its package isn't installed (an orphaned integration)."""
        try:
            return get_provider(slug)
        except KeyError:
            return None

    def _validate_config(self, provider, config: dict) -> None:
        """Light validation: required keys present. (Full JSON-schema validation is a later pass.)"""
        required = (provider.config_schema or {}).get("required", [])
        missing = [k for k in required if not (config or {}).get(k)]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Missing required config: {', '.join(missing)}.",
            )

    def _context(self, row: IntegrationModel) -> IntegrationContext:
        # Narrow, core-free context: providers get config + resolved secret + logger + safe http,
        # and nothing else. The core owns persistence and event dispatch.
        secret = resolve_secret(row.secret_ref, self.group_id) if row.secret_ref else None
        return IntegrationContext(config=row.config or {}, secret=secret, logger=logger, http=build_http())

    # ---- provider catalog --------------------------------------------------------

    @router.get("/providers", response_model=list[IntegrationProviderInfo])
    def list_provider_catalog(self):
        """The available integration providers (the 'add integration' catalog)."""
        return [IntegrationProviderInfo(**p.info()) for p in list_providers()]

    @router.get("/plugins", response_model=list[IntegrationPluginInfo])
    def list_plugins(self):
        """Installed provider sources — built-ins and plugin packages — with load status/version."""
        return [IntegrationPluginInfo(**asdict(r)) for r in load_reports()]

    # ---- integration alert routing ------------------------------------------------

    @router.get("/alert-routing", response_model=AlertRouting)
    def get_alert_routing(self):
        """Where integration alerts go besides the bell: admins by email, chat/notification connections."""
        require_workspace_admin(self.user, self.group_id)
        from marvin.services.integrations.alert_routing import get_routing

        return AlertRouting(**get_routing(self.session, self.group_id))

    @router.put("/alert-routing", response_model=AlertRouting)
    def set_alert_routing(self, data: AlertRoutingUpdate):
        require_workspace_admin(self.user, self.group_id)
        from marvin.services.integrations.alert_routing import set_routing

        try:
            routing = set_routing(
                self.session, self.group_id, email_admins=data.email_admins, integration_ids=data.integration_ids, reminder_hours=data.reminder_hours
            )
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        return AlertRouting(**routing)

    # ---- event connections (integration action ⇄ event) -------------------------

    def _sub_to_read(self, row: IntegrationEventSubscriptionModel) -> IntegrationEventSubscriptionRead:
        integ = self.session.get(IntegrationModel, row.integration_id)
        return IntegrationEventSubscriptionRead(
            id=row.id,
            integration_id=row.integration_id,
            integration_name=integ.name if integ else None,
            provider=integ.provider if integ else None,
            event_type=row.event_type,
            action=row.action,
            args=row.args,
            enabled=row.enabled,
        )

    @router.get("/subscriptions", response_model=list[IntegrationEventSubscriptionRead])
    def list_subscriptions(self, event_type: str | None = None):
        """Integration actions wired to events. Filter by ?event_type= for one event's connections."""
        q = self.session.query(IntegrationEventSubscriptionModel).filter(IntegrationEventSubscriptionModel.group_id == self.group_id)
        if event_type:
            q = q.filter(IntegrationEventSubscriptionModel.event_type == event_type)
        return [self._sub_to_read(r) for r in q.all()]

    @router.post("/subscriptions", response_model=IntegrationEventSubscriptionRead, status_code=status.HTTP_201_CREATED)
    def create_subscription(self, data: IntegrationEventSubscriptionCreate):
        """Wire an integration action to an event type."""
        integ = self.session.get(IntegrationModel, data.integration_id)
        if not integ or integ.group_id != self.group_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found.")
        provider = self._provider_or_none(integ.provider)
        if provider is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Provider '{integ.provider}' is not installed.")
        if provider.get_action(data.action) is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"'{integ.provider}' has no action '{data.action}'.")

        row = IntegrationEventSubscriptionModel(
            session=self.session,
            group_id=self.group_id,
            integration_id=data.integration_id,
            event_type=data.event_type,
            action=data.action,
            args=data.args or None,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return self._sub_to_read(row)

    @router.patch("/subscriptions/{sub_id}", response_model=IntegrationEventSubscriptionRead)
    def update_subscription(self, sub_id: UUID4, data: IntegrationEventSubscriptionUpdate):
        """Toggle a connection or change its templated args."""
        row = self.session.get(IntegrationEventSubscriptionModel, sub_id)
        if not row or row.group_id != self.group_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found.")
        if data.enabled is not None:
            row.enabled = data.enabled
        if data.args is not None:
            row.args = data.args or None
        self.session.commit()
        self.session.refresh(row)
        return self._sub_to_read(row)

    @router.delete("/subscriptions/{sub_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_subscription(self, sub_id: UUID4):
        """Remove an integration ⇄ event connection."""
        row = self.session.get(IntegrationEventSubscriptionModel, sub_id)
        if not row or row.group_id != self.group_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found.")
        self.session.delete(row)
        self.session.commit()

    # ---- CRUD --------------------------------------------------------------------

    @router.get("", response_model=list[IntegrationRead])
    def list_integrations(self):
        """List this workspace's configured integrations."""
        rows = self.session.query(IntegrationModel).filter(IntegrationModel.group_id == self.group_id).order_by(IntegrationModel.name).all()
        alerts = errors.open_alerts(self.session, self.group_id)
        return [_to_read(r, alerts.get(r.id)) for r in rows]

    @router.post("", response_model=IntegrationRead, status_code=status.HTTP_201_CREATED)
    def create_integration(self, data: IntegrationCreate):
        """Create an integration. Any credential is written to the secret backend."""
        try:
            provider = get_provider(data.provider)
        except KeyError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown provider '{data.provider}'.") from e

        slug = slugify(data.slug or data.name, separator="_")
        if not slug:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Could not derive a slug from the name.")

        existing = self.session.query(IntegrationModel).filter(IntegrationModel.group_id == self.group_id, IntegrationModel.slug == slug).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Integration slug '{slug}' already exists.")

        self._validate_config(provider, data.config)

        secret_ref = None
        if data.credential is not None:
            value = data.credential.get_secret_value()
            secret_ref = _referenced_secret(value, self.group_id)
            if secret_ref is None:
                secret_ref = _secret_ref(slug)
                get_secret_backend().set(secret_ref, value, self.group_id)

        row = IntegrationModel(
            session=self.session,
            group_id=self.group_id,
            provider=data.provider,
            name=data.name,
            slug=slug,
            config=data.config or None,
            secret_ref=secret_ref,
            status="unconfigured",
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)

        # Run an initial health check so the row lands with a real status.
        self._run_check(row)
        return _to_read(row, errors.open_alerts(self.session, self.group_id).get(row.id))

    @router.patch("/{integration_id}", response_model=IntegrationRead)
    def update_integration(self, integration_id: UUID4, data: IntegrationUpdate):
        """Update name/enabled/config, or rotate the credential."""
        row = self._get_or_404(integration_id)
        # Provider may be uninstalled (orphaned row); still allow rename / enable-disable / delete.
        provider = self._provider_or_none(row.provider)

        if data.name is not None:
            row.name = data.name
        if data.enabled is not None:
            row.enabled = data.enabled
        if data.config is not None:
            if provider is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Provider '{row.provider}' is not installed — cannot change its config.",
                )
            self._validate_config(provider, data.config)
            row.config = data.config or None
        if data.credential is not None:
            value = data.credential.get_secret_value()
            referenced = _referenced_secret(value, self.group_id)
            if referenced is not None:
                if _owns_secret(row):  # switching from an own copy to a shared secret: drop the copy
                    _delete_secret_quietly(row.secret_ref, self.group_id)
                row.secret_ref = referenced
            else:
                # A new value always lands in the integration's own slot — never over a shared secret it referenced.
                ref = _secret_ref(row.slug)
                get_secret_backend().set(ref, value, self.group_id)
                row.secret_ref = ref

        self.session.commit()
        self.session.refresh(row)
        if provider is not None:
            self._run_check(row)
        return _to_read(row, errors.open_alerts(self.session, self.group_id).get(row.id))

    @router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_integration(self, integration_id: UUID4):
        """Delete an integration and its stored credential."""
        row = self._get_or_404(integration_id)
        if row.secret_ref and _owns_secret(row):  # a referenced workspace secret is shared — leave it
            _delete_secret_quietly(row.secret_ref, self.group_id)
        self.session.delete(row)
        self.session.commit()

    # ---- health check ------------------------------------------------------------

    def _run_check(self, row: IntegrationModel) -> None:
        provider = self._provider_or_none(row.provider)
        if provider is None:
            status_str, err = "unavailable", f"Provider '{row.provider}' is not installed."
        else:
            try:
                status_str, err = provider.check(self._context(row))
            except Exception as e:  # noqa: BLE001 — a provider bug must not 500 the request
                status_str, err = "error", str(e)
        row.status = status_str
        row.last_error = err
        row.last_checked_at = datetime.now(UTC)
        self.session.commit()
        if status_str == "ok":  # a passing check resolves the connection's open alerts (and re-arms parked retries)
            errors.connection_succeeded(self.group_id, row.id, resolution="check", session=self.session, user_id=self.user.id)
        self.session.refresh(row)

    @router.post("/{integration_id}/check", response_model=IntegrationCheckResult)
    def check_integration(self, integration_id: UUID4):
        """Run the provider's health check and persist the result."""
        row = self._get_or_404(integration_id)
        self._run_check(row)
        return IntegrationCheckResult(status=row.status, last_error=row.last_error, last_checked_at=row.last_checked_at)

    # ---- error handling ----------------------------------------------------------

    @router.post("/{integration_id}/resolve", response_model=IntegrationResolveResult)
    def resolve_attention(self, integration_id: UUID4, alert_id: UUID4 | None = None):
        """Mark the connection's open alerts (or one, by `alert_id`) resolved — "I fixed it". Announces
        the resolution through the channels that delivered each alert and re-arms parked retries."""
        require_workspace_admin(self.user, self.group_id)
        row = self._get_or_404(integration_id)
        count = errors.resolve_alerts(self.session, self.group_id, row.id, resolution="manual", user_id=self.user.id, alert_id=alert_id)
        return IntegrationResolveResult(resolved=count)

    @router.put("/{integration_id}/error-overrides", response_model=IntegrationRead)
    def set_error_overrides(self, integration_id: UUID4, data: IntegrationErrorOverrides):
        """Adjust the provider's error policy for this connection: per declared code (or "*"), whether
        a failure sends the entry to review and whether it alerts admins. Retries stay the provider's."""
        require_workspace_admin(self.user, self.group_id)
        row = self._get_or_404(integration_id)
        provider = self._provider_or_none(row.provider)
        if provider is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Provider '{row.provider}' is not installed.")
        declared = errors.declared_codes(provider) | {"*"}
        unknown = sorted(code for code in data.overrides if code not in declared)
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"'{row.provider}' declares no error code {', '.join(unknown)}."
            )
        bad = sorted({flag for flags in data.overrides.values() for flag in flags if flag not in errors.OVERRIDABLE})
        if bad:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Only review and notify can be adjusted, not {', '.join(bad)}."
            )
        row.error_overrides = errors.clean_overrides(data.overrides) or None
        self.session.commit()
        self.session.refresh(row)
        return _to_read(row, errors.open_alerts(self.session, self.group_id).get(row.id))

    # ---- action test-fire --------------------------------------------------------

    @router.post("/{integration_id}/actions/{action_key}", response_model=IntegrationActionResult)
    def run_action(self, integration_id: UUID4, action_key: str, args: dict | None = None):
        """Manually fire a provider action (also how the automation engine will call it)."""
        row = self._get_or_404(integration_id)
        if not row.enabled:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Integration is disabled.")

        provider = self._provider_or_none(row.provider)
        if provider is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Provider '{row.provider}' is not installed.")
        if provider.get_action(action_key) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No action '{action_key}' on this provider.")

        from marvin.services.integrations.arg_secrets import MissingSecretError, resolve_arg_secrets

        try:
            resolved = resolve_arg_secrets(args, self.group_id)
        except MissingSecretError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        try:
            result = provider.run_action(action_key, resolved, self._context(row))
        except NotImplementedError as e:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No action '{action_key}' on this provider.") from e
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
        return IntegrationActionResult(ok=True, result=result)


def _delete_secret_quietly(ref: str, group_id) -> None:
    try:
        get_secret_backend().delete(ref, group_id)
    except Exception as e:  # noqa: BLE001 — best-effort cleanup, never block the caller
        logger.warning(f"[integrations] could not delete secret {ref}: {e}")
