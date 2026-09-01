"""Publishing API forms controller."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from jinja2 import Template
from sqlalchemy.orm import Session

from marvin.core.dependencies import get_publishing_context
from marvin.core.permissions import Permissions
from marvin.db.db_setup import generate_session
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.db.models.platform.form_submissions import FormSubmissions
from marvin.db.models.platform.forms import Forms
from marvin.schemas.platform.entry_type_rendering import CapabilitiesDefinition, SubmissionConfig
from marvin.schemas.platform.entry_type_schema import EntryTypeSchemaDefinition
from marvin.schemas.platform.forms import FormSchemaDefinition
from marvin.schemas.publishing import FormSubmissionResponse, PublishedFormRead
from marvin.services.content_validator import ContentValidationError, ContentValidator
from marvin.services.entries.entry_service import EntryService
from marvin.services.event_bus_service.event_bus_service import EventBusService
from marvin.services.event_bus_service.event_types import (
    EventFormSubmissionData,
    EventOperation,
    EventTypes,
)
from marvin.services.secrets.resolver import resolve
from marvin.services.security.captcha_service import CaptchaService
from marvin.services.security.rate_limit_service import RateLimitService

router = APIRouter()
logger = logging.getLogger(__name__)


def _derive_submission_title(cfg: SubmissionConfig, entry_type: EntryTypes, data: dict) -> str:
    """Title for the entry a submission becomes: config template → first text value → type + time."""
    if cfg.title_template:
        try:
            rendered = Template(cfg.title_template).render(**data).strip()
            if rendered:
                return rendered[:200]
        except Exception:  # noqa: BLE001 — a bad template must never break a submission
            pass
    for value in data.values():
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return f"{entry_type.name} submission {datetime.now(UTC).isoformat(timespec='seconds')}"


def _published_form_from_entry_type(entry_type: EntryTypes, cfg: SubmissionConfig) -> PublishedFormRead:
    """Expose a submittable entry type as a public form definition for a schema→form renderer.

    ``form_schema`` carries the entry type's own field schema (``EntryTypeSchemaDefinition``), so the
    site renders the form from the same schema the submission validates against. ``metadata`` carries
    the render-time bits: the success message and the honeypot field name (only when enabled, so the
    renderer knows to include the hidden trap input).
    """
    return PublishedFormRead(
        slug=entry_type.slug,
        name=entry_type.name,
        description=entry_type.description,
        form_schema=entry_type.schema_json or {},
        metadata={
            "successMessage": cfg.success_message,
            "honeypotField": cfg.honeypot_field if cfg.enable_honeypot else None,
        },
    )


async def _submit_to_entry_type(
    entry_type: EntryTypes,
    cfg: SubmissionConfig,
    submission_data: dict,
    request: Request,
    group,
    bg_tasks: BackgroundTasks,
    session: Session,
) -> FormSubmissionResponse:
    """Handle a public submission for a submittable entry type: create an ``inbox`` entry.

    A submittable entry type IS a form; a submission IS an entry of that type. The submitted values
    run the security gauntlet (rate limit → honeypot → CAPTCHA), validate against the type's own
    field schema, and land as an ``inbox`` entry (kept out of published output, visible in the admin
    Entries list). Notification stays on the scoped ``form_submission_received`` event — never
    ``entry_created``, which fires for every entry.
    """
    ip_address = request.client.host if request.client else "unknown"

    # Rate limit by IP, keyed on this submittable subject (opt-in via rate_limit_max).
    if cfg.rate_limit_max:
        window_minutes = max(1, (cfg.rate_limit_window_seconds or 3600) // 60)
        if not RateLimitService(session).check_subject_limit(
            entry_type.id, ip_address, cfg.rate_limit_max, window_minutes
        ):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
            )

    # Honeypot — a filled hidden field is almost certainly a bot; return success without persisting.
    if cfg.enable_honeypot:
        if submission_data.get(cfg.honeypot_field):
            return FormSubmissionResponse(success=True, message=cfg.success_message or "Thank you for your submission")
        submission_data.pop(cfg.honeypot_field, None)

    # CAPTCHA — the secret is a {{SLUG}} ref resolved from the workspace secret store, never plaintext.
    if cfg.enable_captcha:
        token = submission_data.pop("captchaToken", None)
        secret = resolve(cfg.captcha_secret_ref, group.id, allow_secrets=True) if cfg.captcha_secret_ref else None
        if not await CaptchaService().verify(token, cfg.captcha_provider or "hcaptcha", secret):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CAPTCHA verification failed")

    # Validate the submitted values against the entry type's own field schema.
    schema = entry_type.schema_json or {}
    if schema.get("fields"):
        try:
            schema_def = EntryTypeSchemaDefinition.model_validate(schema)
            ContentValidator().validate_content(schema_def, submission_data)
        except ContentValidationError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Validation failed: {e.message}") from e
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid submission data: {str(e)}"
            ) from e

    # One event bus for both the entry service (entry_created) and the scoped submission event.
    bus = EventBusService(bg_tasks=bg_tasks, session=session)
    entry = EntryService(session, group.id, event_bus=bus, actor_id=None).create(
        {
            "entry_type_id": entry_type.id,
            "title": _derive_submission_title(cfg, entry_type, submission_data),
            "data_json": submission_data,
            "status": "inbox",
            "created_by": None,
        }
    )

    if cfg.notify:
        try:
            bus.dispatch(
                integration_id="form_management",
                group_id=group.id,
                event_type=EventTypes.form_submission_received,
                document_data=EventFormSubmissionData(
                    operation=EventOperation.create,
                    form_id=entry_type.id,
                    form_name=entry_type.name,
                    submission_id=entry.id,
                    submission_data=submission_data,
                    workspace_id=group.id,
                    workspace_name=group.name,
                ),
                message=f"Submission received for '{entry_type.name}'",
                entity_id=entry.id,
                entity_type="entry",
            )
        except Exception as e:
            logger.error(f"Failed to dispatch form_submission_received event: {e}", exc_info=True)

    return FormSubmissionResponse(
        success=True,
        message=cfg.success_message or "Thank you for your submission",
        submission_id=entry.id,
        redirect_url=cfg.redirect_url,
    )


@router.get(
    "/{workspace_slug}/forms/{form_slug}",
    response_model=PublishedFormRead,
    summary="Get Form Definition",
)
async def get_form(
    workspace_slug: str,
    form_slug: str,
    context: tuple = Depends(get_publishing_context),
    session: Session = Depends(generate_session),
) -> PublishedFormRead:
    """
    Get published form definition for rendering.

    **Authentication**: Requires API client token
    **Permissions**: read:published_entries
    """
    api_client, group, perms = context

    # Check permission
    perms.require_permission(Permissions.READ_PUBLISHED_ENTRIES, "form definition")

    # Prefer a submittable entry type with this slug (forms-as-entry-types); fall back to legacy Forms.
    entry_type = (
        session.query(EntryTypes)
        .filter(EntryTypes.group_id == group.id, EntryTypes.slug == form_slug)
        .first()
    )
    if entry_type is not None:
        caps = CapabilitiesDefinition(**(entry_type.capabilities_json or {}))
        if caps.submittable:
            return _published_form_from_entry_type(entry_type, caps.submission or SubmissionConfig())

    # Get form
    form = (
        session.query(Forms)
        .filter(
            Forms.group_id == group.id,
            Forms.slug == form_slug,
            Forms.status == "published",
        )
        .first()
    )

    if not form:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found")

    return PublishedFormRead(
        slug=form.slug,
        name=form.name,
        description=form.description,
        form_schema=form.schema_json,
        metadata=form.metadata_json,
    )


@router.post(
    "/{workspace_slug}/forms/{form_slug}/submit",
    response_model=FormSubmissionResponse,
    summary="Submit Form Data",
)
async def submit_form(
    workspace_slug: str,
    form_slug: str,
    submission_data: dict,
    request: Request,
    bg_tasks: BackgroundTasks,
    context: tuple = Depends(get_publishing_context),
    session: Session = Depends(generate_session),
) -> FormSubmissionResponse:
    """
    Submit data to a published form.

    **Authentication**: Requires API client token
    **Permissions**: write:form_submissions
    **Security**: Rate limiting, CAPTCHA, honeypot
    """
    api_client, group, perms = context

    # Either permission grants submit: public-entry submit (the new entry-type path) or the legacy
    # form-submissions permission (which existing site tokens already hold).
    perms.require_any_permission(
        [Permissions.WRITE_PUBLIC_ENTRIES, Permissions.WRITE_FORM_SUBMISSIONS], "form submission"
    )

    # Forms are folding into submittable entry types: if a submittable entry type matches this slug,
    # the submission becomes an inbox entry of that type. Otherwise fall through to the legacy Forms
    # path (keeps existing forms working during migration; the submit URL is unchanged either way).
    entry_type = (
        session.query(EntryTypes)
        .filter(EntryTypes.group_id == group.id, EntryTypes.slug == form_slug)
        .first()
    )
    if entry_type is not None:
        caps = CapabilitiesDefinition(**(entry_type.capabilities_json or {}))
        if caps.submittable:
            return await _submit_to_entry_type(
                entry_type, caps.submission or SubmissionConfig(), submission_data, request, group, bg_tasks, session
            )

    # Get form
    form = (
        session.query(Forms)
        .filter(
            Forms.group_id == group.id,
            Forms.slug == form_slug,
            Forms.status == "published",
        )
        .first()
    )

    if not form:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found")

    # Get settings
    settings = form.settings_json or {}

    # Rate limiting check
    ip_address = request.client.host if request.client else "unknown"
    rate_limit_service = RateLimitService(session)
    if not rate_limit_service.check_limit(form.id, ip_address, settings):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
        )

    # CAPTCHA verification (if enabled)
    security_settings = settings.get("security", {})
    if security_settings.get("enableCaptcha"):
        captcha_service = CaptchaService()
        captcha_token = submission_data.pop("captchaToken", None)
        captcha_provider = security_settings.get("captchaProvider", "hcaptcha")
        captcha_secret = security_settings.get("captchaSecretKey")

        if not await captcha_service.verify(captcha_token, captcha_provider, captcha_secret):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CAPTCHA verification failed",
            )

    # Honeypot check (if enabled)
    if security_settings.get("enableHoneypot"):
        honeypot_field = security_settings.get("honeypotFieldName", "_website")
        if submission_data.get(honeypot_field):
            # Silent success - likely spam
            return FormSubmissionResponse(
                success=True,
                message=settings.get("successMessage", "Thank you for your submission"),
            )
        # Remove honeypot field from data
        submission_data.pop(honeypot_field, None)

    # Validate submission against schema
    if form.schema_json and form.schema_json.get("fields"):
        validator = ContentValidator()
        try:
            schema_def = FormSchemaDefinition.model_validate(form.schema_json)
            validator.validate_form_submission(schema_def, submission_data)
        except ContentValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Validation failed: {e.message}",
            ) from e
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid submission data: {str(e)}",
            ) from e

    # Create submission (if persistence enabled)
    submission_id = None
    if settings.get("persistSubmissions", True):
        submission = FormSubmissions(
            session=session,
            form_id=form.id,
            group_id=group.id,
            data_json=submission_data,
            metadata_json={
                "api_client_id": str(api_client.id),
                "referrer": request.headers.get("referer"),
            },
            ip_address=ip_address,
            user_agent=request.headers.get("user-agent"),
            submitted_at=datetime.now(UTC),
        )
        session.add(submission)
        session.commit()
        submission_id = submission.id

        # Update form stats
        form.submissions_count += 1
        form.last_submission_at = datetime.now(UTC)
        session.commit()

    # Notify subscribers (e.g. an admin email via EmailEventListener). Runs in the background so a
    # notification failure never fails the visitor's submission; the honeypot path returned earlier,
    # so confirmed spam never dispatches. Delivery requires a form_submission_received subscription.
    try:
        bus = EventBusService(bg_tasks=bg_tasks, session=session)
        bus.dispatch(
            integration_id="form_management",
            group_id=group.id,
            event_type=EventTypes.form_submission_received,
            document_data=EventFormSubmissionData(
                operation=EventOperation.create,
                form_id=form.id,
                form_name=form.name,
                submission_id=submission_id,
                submission_data=submission_data,
                workspace_id=group.id,
                workspace_name=group.name,
            ),
            message=f"Form '{form.name}' submission received",
            entity_id=form.id,
            entity_type="form",
        )
    except Exception as e:
        logger.error(f"Failed to dispatch form_submission_received event: {e}", exc_info=True)

    # Return response
    success_message = settings.get("successMessage", "Thank you for your submission")
    redirect_url = settings.get("redirectUrl")

    return FormSubmissionResponse(
        success=True,
        message=success_message,
        submission_id=submission_id,
        redirect_url=redirect_url,
    )
