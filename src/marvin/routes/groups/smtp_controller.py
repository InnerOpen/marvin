"""Workspace SMTP Profiles API.

CRUD for named, workspace-scoped SMTP server configurations. A workspace may have
several profiles; at most one is active. Passwords are Fernet-encrypted at rest and
never returned. A per-profile test endpoint sends a live message through the profile.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4
from sqlalchemy import select

from marvin.db.models.groups.smtp_profiles import WorkspaceSMTPProfileModel, smtp_secret_ref
from marvin.routes._base import BaseUserController, controller
from marvin.schemas.group.smtp_profile import (
    SMTPProfileCreate,
    SMTPProfileRead,
    SMTPProfileTestRequest,
    SMTPProfileTestResult,
    SMTPProfileUpdate,
)
from marvin.services.email.email_senders import EmailOptions, Message
from marvin.services.secrets import get_secret_backend
from marvin.services.secrets.resolver import resolve_secret

router = APIRouter(prefix="/groups/smtp-profiles")


def _password_reference(value: str, group_id) -> str | None:
    """If `value` points at an existing workspace secret — as `{{SLUG}}` or a bare uppercase `SLUG`
    that exists — return that slug. Otherwise None, meaning treat `value` as a literal password."""
    import re

    bare = value.strip()
    m = re.fullmatch(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", bare)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Z0-9_]+", bare) and bare in get_secret_backend().list_slugs(group_id):
        return bare
    return None


def _to_read(profile: WorkspaceSMTPProfileModel) -> SMTPProfileRead:
    """Serialize a profile, exposing only whether a password is stored."""
    return SMTPProfileRead(
        id=profile.id,
        group_id=profile.group_id,
        name=profile.name,
        host=profile.host,
        port=profile.port,
        username=profile.username,
        from_name=profile.from_name,
        from_email=profile.from_email,
        auth_strategy=profile.auth_strategy,
        is_active=profile.is_active,
        has_password=bool(profile.secret_ref),
        created_at=getattr(profile, "created_at", None),
        updated_at=getattr(profile, "updated_at", None),
    )


@controller(router)
class SMTPProfilesController(BaseUserController):
    """Workspace SMTP profile management."""

    def _get_or_404(self, profile_id: UUID4) -> WorkspaceSMTPProfileModel:
        profile = self.session.get(WorkspaceSMTPProfileModel, profile_id)
        if not profile or profile.group_id != self.group_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SMTP profile not found.")
        return profile

    def _delete_managed_secret(self, profile: WorkspaceSMTPProfileModel) -> None:
        """Delete this profile's auto-managed secret — never a secret the user referenced by slug."""
        managed = smtp_secret_ref(profile.id)
        if profile.secret_ref == managed:
            try:
                get_secret_backend().delete(managed, self.group_id)
            except Exception as e:
                self.logger.warning(f"[smtp] could not delete secret {managed}: {e}")

    def _apply_password(self, profile: WorkspaceSMTPProfileModel, value: str) -> None:
        """Point the profile at a referenced secret, or store a literal under its managed secret."""
        ref = _password_reference(value, self.group_id)
        if ref:
            self._delete_managed_secret(profile)  # dropping our own secret in favour of a reference
            profile.secret_ref = ref
        else:
            managed = smtp_secret_ref(profile.id)
            get_secret_backend().set(managed, value, self.group_id)
            profile.secret_ref = managed

    def _deactivate_others(self, keep_id: UUID4 | None) -> None:
        """Ensure at most one active profile — clear is_active on every other row."""
        rows = (
            self.session.execute(
                select(WorkspaceSMTPProfileModel).where(
                    WorkspaceSMTPProfileModel.group_id == self.group_id,
                    WorkspaceSMTPProfileModel.is_active.is_(True),
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            if row.id != keep_id:
                row.is_active = False

    @router.get("", response_model=list[SMTPProfileRead], summary="List Workspace SMTP Profiles")
    def list_profiles(self) -> list[SMTPProfileRead]:
        rows = (
            self.session.execute(
                select(WorkspaceSMTPProfileModel).where(WorkspaceSMTPProfileModel.group_id == self.group_id).order_by(WorkspaceSMTPProfileModel.name)
            )
            .scalars()
            .all()
        )
        return [_to_read(r) for r in rows]

    @router.post("", response_model=SMTPProfileRead, status_code=status.HTTP_201_CREATED, summary="Create SMTP Profile")
    def create_profile(self, data: SMTPProfileCreate) -> SMTPProfileRead:
        profile = WorkspaceSMTPProfileModel(
            session=self.session,
            group_id=self.group_id,
            name=data.name,
            host=data.host,
            port=data.port,
            username=data.username or None,
            from_name=data.from_name or None,
            from_email=data.from_email or None,
            auth_strategy=data.auth_strategy,
            is_active=data.is_active,
        )
        self.session.add(profile)
        self.session.flush()  # assign id before deriving the secret ref
        if data.password:
            self._apply_password(profile, data.password)
        if data.is_active:
            self._deactivate_others(keep_id=profile.id)
        self.session.commit()
        self.session.refresh(profile)
        return _to_read(profile)

    @router.get("/{profile_id}", response_model=SMTPProfileRead, summary="Get an SMTP Profile")
    def get_profile(self, profile_id: UUID4) -> SMTPProfileRead:
        return _to_read(self._get_or_404(profile_id))

    @router.patch("/{profile_id}", response_model=SMTPProfileRead, summary="Update an SMTP Profile")
    def update_profile(self, profile_id: UUID4, data: SMTPProfileUpdate) -> SMTPProfileRead:
        profile = self._get_or_404(profile_id)

        for field in ("name", "host", "port", "username", "from_name", "from_email", "auth_strategy"):
            value = getattr(data, field)
            if value is not None:
                setattr(profile, field, value)

        # A non-empty password (literal or a {{SLUG}}/SLUG reference) replaces the stored one; an
        # explicit empty string clears it.
        if data.password is not None:
            if data.password:
                self._apply_password(profile, data.password)
            else:
                self._delete_managed_secret(profile)
                profile.secret_ref = None

        if data.is_active is not None:
            profile.is_active = data.is_active
            if data.is_active:
                self._deactivate_others(keep_id=profile.id)

        self.session.commit()
        self.session.refresh(profile)
        return _to_read(profile)

    @router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an SMTP Profile")
    def delete_profile(self, profile_id: UUID4) -> None:
        profile = self._get_or_404(profile_id)
        self._delete_managed_secret(profile)  # only our own secret, never a referenced one
        self.session.delete(profile)
        self.session.commit()

    @router.post("/{profile_id}/test", response_model=SMTPProfileTestResult, summary="Send a test email via this profile")
    def test_profile(self, profile_id: UUID4, data: SMTPProfileTestRequest) -> SMTPProfileTestResult:
        profile = self._get_or_404(profile_id)

        from_email = profile.from_email or self.settings.SMTP_FROM_EMAIL
        from_name = profile.from_name or self.settings.SMTP_FROM_NAME or "Marvin"
        if not from_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This profile has no From address and no global SMTP_FROM_EMAIL fallback is set.",
            )

        subject, html = self._render_notification_email(profile)

        strategy = (profile.auth_strategy or "TLS").upper()
        options = EmailOptions(
            host=profile.host,
            port=int(profile.port),
            username=profile.username or None,
            password=resolve_secret(profile.secret_ref, self.group_id) if profile.secret_ref else None,
            tls=strategy == "TLS",
            ssl=strategy == "SSL",
        )

        message = Message(
            subject=subject,
            html=html,
            mail_from_name=from_name,
            mail_from_address=from_email,
        )
        result = message.send(to_address=data.recipient_email, smtp_config=options)
        return SMTPProfileTestResult(success=result.success, message=result.message)

    def _render_notification_email(self, profile: WorkspaceSMTPProfileModel) -> tuple[str, str]:
        """Render the workspace notification email (the customized "custom" template if one
        exists, else the system default) so the test email mirrors a real notification. Falls
        back to a minimal message if no template is available or rendering fails."""
        from marvin.services.email.email_service import EmailService

        workspace_name = getattr(self.group, "name", "") or ""
        fallback = (
            f"Notification from {workspace_name}" if workspace_name else "Test notification",
            f"<p>This is a test email sent through the <strong>{profile.name}</strong> SMTP profile. If you received it, the profile works.</p>",
        )
        try:
            email_service = EmailService(group_id=str(self.group_id))
            template = email_service._get_db_template("custom", str(self.group_id))
            if not template:
                return fallback
            return email_service.render_db_template(template, {"workspace_name": workspace_name})
        except Exception as exc:
            self.logger.warning(f"Falling back to generic test email — notification render failed: {exc}")
            return fallback
