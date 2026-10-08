"""
Workspace Integrations API.

CRUD for credentialed connections to external services, plus a provider catalog, a
health check, and an action test-fire. Credentials are written to the configured secret
backend and referenced by `secret_ref` — never stored on the row or returned.

Every route is workspace-admin only except the provider catalog (what can be installed, no workspace
data) and the public logo route: connections carry config, checks and actions spend the workspace's
credentials, and the workflow engine already requires ADMIN for integration actions.
"""

import re
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import UUID4
from slugify import slugify

from marvin.core.root_logger import get_logger
from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import refuse_platform_events, require_workspace_admin
from marvin.schemas.group.integration import (
    HandledFailurePage,
    IntegrationActionResult,
    IntegrationAlertPage,
    IntegrationAttention,
    IntegrationCheckResult,
    IntegrationCreate,
    IntegrationErrorOverrides,
    IntegrationEventSubscriptionCreate,
    IntegrationEventSubscriptionRead,
    IntegrationEventSubscriptionUpdate,
    IntegrationHealthRow,
    IntegrationOption,
    IntegrationOptionsRequest,
    IntegrationPluginInfo,
    IntegrationProviderInfo,
    IntegrationRead,
    IntegrationResolveResult,
    IntegrationRetryRead,
    IntegrationUpdate,
)
from marvin.services.integrations import (
    INTEGRATION_REGISTRY,
    IntegrationContext,
    IntegrationProvider,
    build_http,
    errors,
    get_provider,
    health,
    list_providers,
    load_reports,
    logos,
)
from marvin.services.secrets import get_secret_backend
from marvin.services.secrets.resolver import resolve_secret

router = APIRouter(prefix="/groups/integrations")
# Unauthenticated routes. Separate because `controller()` rewrites `router`'s prefix while binding the
# class, so a plain function on it would lose `/groups/integrations`.
public_router = APIRouter(prefix="/groups/integrations")
logger = get_logger(__name__)

OPTIONS_HINT = "x-marvin-options"
MAX_OPTIONS = 500


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
        # has_logo is core's verdict, not the SDK's: a logo the validator refused reads as none.
        return [IntegrationProviderInfo(**{**p.info(), "has_logo": logos.has_logo(p.slug)}) for p in list_providers()]

    @router.get("/plugins", response_model=list[IntegrationPluginInfo])
    def list_plugins(self):
        """Installed provider sources — built-ins and plugin packages — with load status/version."""
        require_workspace_admin(self.user, self.group_id)
        return [IntegrationPluginInfo(**asdict(r)) for r in load_reports()]

    # ---- alerts & health page ----------------------------------------------------

    @router.get("/health", response_model=list[IntegrationHealthRow])
    def get_health(self):
        """Each connection at a glance: last successful action, last check, 7-day failures, open alerts."""
        require_workspace_admin(self.user, self.group_id)
        return health.health(self.session, self.group_id)

    @router.get("/alerts", response_model=IntegrationAlertPage)
    def list_alerts(self, status_: Literal["open", "resolved"] = Query("open", alias="status"), page: int = 1, per_page: int = 25):
        """The workspace's open alerts, or its resolved ones (how long each was open, how it resolved)."""
        require_workspace_admin(self.user, self.group_id)
        return health.list_alerts(self.session, self.group_id, status=status_, page=page, per_page=per_page)

    @router.get("/retries", response_model=list[IntegrationRetryRead])
    def list_retries(self):
        """Failed workflow steps waiting to be retried (pending, parked until the connection recovers, running)."""
        require_workspace_admin(self.user, self.group_id)
        return health.list_retries(self.session, self.group_id)

    def _retry_lever(self, lever, retry_id: UUID4) -> IntegrationRetryRead:
        try:
            row = lever(self.session, self.group_id, retry_id)
        except health.RetryConflict as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Retry not found.")
        return row

    @router.post("/retries/{retry_id}/retry-now", response_model=IntegrationRetryRead)
    def retry_now(self, retry_id: UUID4):
        """Make a pending or parked retry due now. The retry sweep runs it on its next tick (about a
        minute) — never this request. 409 while it is running, or once it has finished."""
        require_workspace_admin(self.user, self.group_id)
        return self._retry_lever(health.retry_now, retry_id)

    @router.post("/retries/{retry_id}/give-up", response_model=IntegrationRetryRead)
    def give_up_retry(self, retry_id: UUID4):
        """Stop retrying: the chain ends as superseded and nothing else happens (no review, no alert).
        409 while it is running, or once it has finished."""
        require_workspace_admin(self.user, self.group_id)
        return self._retry_lever(health.give_up, retry_id)

    @router.get("/handled-failures", response_model=HandledFailurePage)
    def list_handled_failures(self, since: datetime | None = None, page: int = 1, per_page: int = 25):
        """Failed integration steps an error policy took in hand (default: the last 7 days), newest first."""
        require_workspace_admin(self.user, self.group_id)
        return health.handled_failures(self.session, self.group_id, since=since, page=page, per_page=per_page)

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
            source_integration_id=row.source_integration_id,
            source_blueprint=row.source_blueprint,
        )

    @router.get("/subscriptions", response_model=list[IntegrationEventSubscriptionRead])
    def list_subscriptions(self, event_type: str | None = None):
        """Integration actions wired to events. Filter by ?event_type= for one event's connections."""
        require_workspace_admin(self.user, self.group_id)
        q = self.session.query(IntegrationEventSubscriptionModel).filter(IntegrationEventSubscriptionModel.group_id == self.group_id)
        if event_type:
            q = q.filter(IntegrationEventSubscriptionModel.event_type == event_type)
        return [self._sub_to_read(r) for r in q.all()]

    @router.post("/subscriptions", response_model=IntegrationEventSubscriptionRead, status_code=status.HTTP_201_CREATED)
    def create_subscription(self, data: IntegrationEventSubscriptionCreate):
        """Wire an integration action to an event type."""
        require_workspace_admin(self.user, self.group_id)
        refuse_platform_events([data.event_type])
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
        require_workspace_admin(self.user, self.group_id)
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
        require_workspace_admin(self.user, self.group_id)
        row = self.session.get(IntegrationEventSubscriptionModel, sub_id)
        if not row or row.group_id != self.group_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found.")
        self.session.delete(row)
        self.session.commit()

    # ---- CRUD --------------------------------------------------------------------

    @router.get("", response_model=list[IntegrationRead])
    def list_integrations(self):
        """List this workspace's configured integrations."""
        require_workspace_admin(self.user, self.group_id)
        rows = self.session.query(IntegrationModel).filter(IntegrationModel.group_id == self.group_id).order_by(IntegrationModel.name).all()
        alerts = errors.open_alerts(self.session, self.group_id)
        return [_to_read(r, alerts.get(r.id)) for r in rows]

    @router.post("", response_model=IntegrationRead, status_code=status.HTTP_201_CREATED)
    def create_integration(self, data: IntegrationCreate):
        """Create an integration. Any credential is written to the secret backend."""
        require_workspace_admin(self.user, self.group_id)
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
                get_secret_backend().set(secret_ref, value, self.group_id, session=self.session)

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
        require_workspace_admin(self.user, self.group_id)
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
                    _delete_secret_quietly(row.secret_ref, self.group_id, self.session)
                row.secret_ref = referenced
            else:
                # A new value always lands in the integration's own slot — never over a shared secret it referenced.
                ref = _secret_ref(row.slug)
                get_secret_backend().set(ref, value, self.group_id, session=self.session)
                row.secret_ref = ref

        self.session.commit()
        self.session.refresh(row)
        if provider is not None:
            self._run_check(row)
        return _to_read(row, errors.open_alerts(self.session, self.group_id).get(row.id))

    @router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_integration(self, integration_id: UUID4):
        """Delete an integration and its stored credential."""
        require_workspace_admin(self.user, self.group_id)
        row = self._get_or_404(integration_id)
        if row.secret_ref and _owns_secret(row):  # a referenced workspace secret is shared — leave it
            _delete_secret_quietly(row.secret_ref, self.group_id, self.session)
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
        require_workspace_admin(self.user, self.group_id)
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

    def _runnable(self, integration_id: UUID4) -> tuple[IntegrationModel, IntegrationProvider]:
        """The workspace's enabled connection and its installed provider, or the HTTP error why not."""
        row = self._get_or_404(integration_id)
        if not row.enabled:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Integration is disabled.")
        provider = self._provider_or_none(row.provider)
        if provider is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Provider '{row.provider}' is not installed.")
        return row, provider

    def _execute(self, row: IntegrationModel, provider: IntegrationProvider, action_key: str, args: dict | None) -> dict:
        """Run one provider action with `{{SECRET}}` args resolved — the one path Run action and the
        option picker share."""
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
        return result

    @router.post("/{integration_id}/actions/{action_key}", response_model=IntegrationActionResult)
    def run_action(self, integration_id: UUID4, action_key: str, args: dict | None = None):
        """Manually fire a provider action (also how the automation engine will call it)."""
        require_workspace_admin(self.user, self.group_id)
        row, provider = self._runnable(integration_id)
        return IntegrationActionResult(ok=True, result=self._execute(row, provider, action_key, args))

    # ---- option source for action inputs -------------------------------------------

    @router.post("/{integration_id}/options", response_model=list[IntegrationOption])
    def action_input_options(self, integration_id: UUID4, data: IntegrationOptionsRequest):
        """The choices for one action input, from the read action its `x-marvin-options` hint names.

        Only that hinted action runs, with the hint's static args — the caller names an input, never an
        action — so this can't be used to fire arbitrary actions. Same access as Run action. Errors come
        back as a 4xx with a plain message; the picker shows it and keeps free text."""
        require_workspace_admin(self.user, self.group_id)
        row, provider = self._runnable(integration_id)
        hint = _options_hint(provider, data.action_key, data.input)
        try:
            result = self._execute(row, provider, hint["action"], dict(hint.get("args") or {}))
        except HTTPException as e:
            if e.status_code < 500:
                raise
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Couldn't load the options: {e.detail}") from e
        except Exception as e:  # noqa: BLE001 — a provider bug must not 500 the picker
            logger.warning(f"[integrations] options for {row.provider}.{data.action_key}.{data.input} failed: {e}")
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Couldn't load the options: the integration failed.") from e
        return _project_options(result, hint["value"], hint.get("label") or hint["value"])


def _options_hint(provider: IntegrationProvider, action_key: str, input_key: str) -> dict:
    """The validated `x-marvin-options` hint on one input of one of the provider's actions. The action
    it names must be one of the same provider's actions."""
    action = provider.get_action(action_key)
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No action '{action_key}' on this provider.")
    prop = ((action.input_schema or {}).get("properties") or {}).get(input_key)
    hint = prop.get(OPTIONS_HINT) if isinstance(prop, dict) else None
    if not isinstance(hint, dict):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"'{action_key}.{input_key}' has no option source.")
    source, value, label, args = hint.get("action"), hint.get("value"), hint.get("label"), hint.get("args")
    if not (isinstance(source, str) and isinstance(value, str) and value and (label is None or isinstance(label, str))):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"'{action_key}.{input_key}' has a malformed option source.")
    if args is not None and not isinstance(args, dict):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"'{action_key}.{input_key}' has a malformed option source.")
    source_action = provider.get_action(source)
    if source_action is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"The option source '{source}' is not an action of this provider."
        )
    if getattr(source_action, "requires_approval", False):  # it runs whenever a picker opens — read actions only
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"The option source '{source}' needs approval to run.")
    return hint


def _project_options(result, value_field: str, label_field: str) -> list[IntegrationOption]:
    """A read action's result — a list of objects, or an object with an `items` list — as up to
    `MAX_OPTIONS` distinct {value, label}. Items without a usable value are skipped."""
    items = result.get("items") if isinstance(result, dict) else result
    if not isinstance(items, list):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Couldn't load the options: the integration returned no list.")
    options: list[IntegrationOption] = []
    seen: set = set()
    for item in items:
        if isinstance(item, dict):
            value, label = item.get(value_field), item.get(label_field)
        else:
            value, label = item, None
        if not isinstance(value, str | int | float) or value == "" or value in seen:
            continue
        seen.add(value)
        options.append(IntegrationOption(value=value, label=str(label) if label not in (None, "") else str(value)))
        if len(options) >= MAX_OPTIONS:
            break
    return options


def _logo_headers(logo) -> dict[str, str]:
    return {
        "ETag": logo.etag,
        "Cache-Control": "public, max-age=3600",
        "X-Content-Type-Options": "nosniff",
        # The logo is ours to serve but not ours to trust: nothing in it may load, run or navigate,
        # even when opened directly rather than through <img>.
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
    }


@public_router.get(
    "/providers/{slug}/logo", response_class=Response, responses={200: {"content": {"image/svg+xml": {}, "image/png": {}}}, 304: {}, 404: {}}
)
def provider_logo(slug: str, request: Request):
    """A provider's validated logo. Public: logos aren't secret, they're platform-wide rather than
    per-workspace, and an <img> can't send a Bearer header. 404 → the UI shows the provider's emoji."""
    logo = logos.get_logo(slug)
    if logo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No logo.")
    headers = _logo_headers(logo)
    if logo.etag in [tag.strip() for tag in request.headers.get("if-none-match", "").split(",")]:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=logo.data, media_type=logo.content_type, headers=headers)


def _delete_secret_quietly(ref: str, group_id, session) -> None:
    try:
        get_secret_backend().delete(ref, group_id, session=session)
    except Exception as e:  # noqa: BLE001 — best-effort cleanup, never block the caller
        logger.warning(f"[integrations] could not delete secret {ref}: {e}")
