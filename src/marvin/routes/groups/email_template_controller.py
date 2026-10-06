"""Email template management controller for workspace-scoped email templates."""

from functools import cached_property

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4, BaseModel, EmailStr

from marvin.db.models.users.roles import WORKSPACE_ROLE_HIERARCHY
from marvin.routes._base import MarvinCrudRoute
from marvin.routes._base.base_controllers import BaseUserController
from marvin.routes._base.controller import controller
from marvin.schemas.group.email_template import (
    EmailTemplateCreate,
    EmailTemplateRead,
    EmailTemplateSummary,
    EmailTemplateUpdate,
    SystemEmailRead,
    SystemEmailVariable,
)
from marvin.services.event_bus_service.event_types import EventEmailTemplateData, EventOperation, EventTypes

router = APIRouter(prefix="/platform/workspaces/{group_id}/email-templates", route_class=MarvinCrudRoute)


class TestEmailRequest(BaseModel):
    """Request to send a test email."""

    recipient_email: EmailStr


@controller(router)
class EmailTemplateController(BaseUserController):
    """
    Controller for managing workspace email templates.

    Provides CRUD operations for email templates that can customize
    invitation, password reset, and notification emails per workspace.
    """

    @cached_property
    def repo(self):
        """Repository for email templates."""
        if not self.user:
            raise Exception("No user logged in")
        from marvin.db.models.groups.email_templates import EmailTemplateModel
        from marvin.repos.repository_generic import RepositoryGeneric
        from marvin.schemas.group.email_template import EmailTemplateRead

        return RepositoryGeneric(
            self.repos.session,
            primary_key="id",
            sql_model=EmailTemplateModel,
            schema=EmailTemplateRead,
        )

    @router.get("", response_model=list[EmailTemplateSummary], summary="List Email Templates")
    def list_templates(self, group_id: UUID4) -> list[EmailTemplateSummary]:
        """
        List all email templates for the workspace.

        Returns both workspace-specific and system-wide templates.

        Args:
            group_id: Workspace ID

        Returns:
            List of email template summaries
        """
        self._check_workspace_access(group_id)

        from sqlalchemy import or_

        from marvin.db.models.groups.email_templates import EmailTemplateModel

        all_templates = (
            self.repos.session.query(EmailTemplateModel)
            .filter(or_(EmailTemplateModel.group_id == group_id, EmailTemplateModel.group_id.is_(None)))
            .order_by(EmailTemplateModel.template_type, EmailTemplateModel.group_id.nullslast())
            .all()
        )

        # Show all — system + workspace overrides. User enables the one they want active.
        # If a workspace override exists, auto-disable the system template visually
        # (the email service already prefers workspace templates over system ones).
        return [EmailTemplateSummary.model_validate(t) for t in all_templates]

    @router.get("/event-connections", summary="Get System Email Event Connections")
    def get_event_connections(self, group_id: UUID4) -> list[dict]:
        """Return the event connection state for all system email template types.

        For each entry in SYSTEM_TEMPLATE_EVENT_MAP, returns whether the system template
        exists, whether a workspace template override is active, and the subscription ID
        (if any) for the workspace template.
        """
        self._check_workspace_access(group_id)

        from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel
        from marvin.db.models.groups.email_templates import EmailTemplateModel
        from marvin.services.email.system_email_events import SYSTEM_TEMPLATE_EVENT_MAP

        session = self.repos.session
        result = []

        for template_type, mapping in SYSTEM_TEMPLATE_EVENT_MAP.items():
            # Find system template (group_id IS NULL)
            system_tmpl = (
                session.query(EmailTemplateModel)
                .filter(
                    EmailTemplateModel.template_type == template_type,
                    EmailTemplateModel.group_id.is_(None),
                )
                .first()
            )

            # Find workspace template (group_id = this workspace)
            workspace_tmpl = (
                session.query(EmailTemplateModel)
                .filter(
                    EmailTemplateModel.template_type == template_type,
                    EmailTemplateModel.group_id == group_id,
                )
                .first()
            )

            # Find active subscription for the workspace template (if any)
            subscription = None
            if workspace_tmpl:
                subscription = (
                    session.query(EmailEventSubscriptionModel)
                    .filter(
                        EmailEventSubscriptionModel.template_id == workspace_tmpl.id,
                        EmailEventSubscriptionModel.event_type == mapping["event_type"],
                    )
                    .first()
                )

            import uuid as _uuid

            def _fmt(raw) -> str | None:
                """Return UUID with dashes to match Pydantic UUID4 serialisation."""
                if raw is None:
                    return None
                s = str(raw).replace("-", "")
                try:
                    return str(_uuid.UUID(s))
                except ValueError:
                    return str(raw)

            result.append(
                {
                    "template_type": template_type,
                    "event_type": mapping["event_type"],
                    "recipient_type": mapping["recipient_type"],
                    "recipient_field": mapping.get("recipient_field"),
                    "system_template": ({"id": _fmt(system_tmpl.id), "name": system_tmpl.name} if system_tmpl else None),
                    "workspace_template": ({"id": _fmt(workspace_tmpl.id), "name": workspace_tmpl.name} if workspace_tmpl else None),
                    "subscription_id": _fmt(subscription.id) if subscription else None,
                    "has_workspace_override": subscription is not None,
                }
            )

        return result

    @router.get("/system-emails", response_model=list[SystemEmailRead], summary="List Marvin's Replaceable System Emails")
    def list_system_emails(self, group_id: UUID4) -> list[SystemEmailRead]:
        """Marvin's own emails a workspace template can replace (welcome, password reset, invitation): the event each
        is sent on, its variables (from the event catalog), whether it sends now and which workspace templates replace
        it. The email template page offers "Replaces Marvin's … email" from this, so it never has to list platform
        events. Workspace OWNER/ADMIN."""
        self._check_admin_access(group_id)

        from marvin.db.models.groups.email_templates import EmailTemplateModel
        from marvin.services.email.system_email_events import SYSTEM_TEMPLATE_EVENT_MAP
        from marvin.services.events import connections
        from marvin.services.events.event_catalog import get_catalog_entry

        session = self.repos.session
        system_ids = dict(
            session.query(EmailTemplateModel.template_type, EmailTemplateModel.id).filter(
                EmailTemplateModel.group_id.is_(None), EmailTemplateModel.template_type.in_(list(SYSTEM_TEMPLATE_EVENT_MAP))
            )
        )
        out = []
        for template_type, mapping in SYSTEM_TEMPLATE_EVENT_MAP.items():
            event_type = mapping["event_type"]
            entry = get_catalog_entry(event_type)
            sends, replaced_by = connections.system_email(session, group_id, event_type)
            out.append(
                SystemEmailRead(
                    template_type=template_type,
                    label=mapping["label"],
                    event_type=event_type,
                    event_name=entry.name if entry else event_type,
                    recipient_type=mapping["recipient_type"],
                    recipient_field=mapping.get("recipient_field"),
                    system_template_id=system_ids.get(template_type),
                    system_sends=sends,
                    replaced_by=replaced_by,
                    variables=[
                        SystemEmailVariable(slug=v.slug, description=v.description, example=v.example, type=v.type)
                        for v in (entry.variables if entry else [])
                    ],
                )
            )
        return out

    @router.get("/{template_id}", response_model=EmailTemplateRead, summary="Get Email Template")
    def get_template(self, group_id: UUID4, template_id: UUID4) -> EmailTemplateRead:
        """
        Get a specific email template by ID.

        Args:
            group_id: Workspace ID
            template_id: Template ID

        Returns:
            Email template details
        """
        self._check_workspace_access(group_id)
        return self._template_or_404(group_id, template_id)

    @router.post("", response_model=EmailTemplateRead, status_code=status.HTTP_201_CREATED, summary="Create Email Template")
    def create_template(self, group_id: UUID4, data: EmailTemplateCreate) -> EmailTemplateRead:
        """
        Create a new email template for the workspace.

        Args:
            group_id: Workspace ID
            data: Template data

        Returns:
            Created email template
        """
        self._check_admin_access(group_id)

        # Ensure group_id matches
        if data.group_id and str(data.group_id) != str(group_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Template group_id must match workspace group_id",
            )

        # Set group_id from path
        create_data = data.model_dump()
        create_data["group_id"] = group_id

        # Create template using SQLAlchemy directly
        from marvin.db.models.groups.email_templates import EmailTemplateModel

        # Create model instance - id and timestamps will auto-generate
        template = EmailTemplateModel(session=self.repos.session)
        template.group_id = group_id
        template.template_type = data.template_type
        template.name = data.name
        template.subject = data.subject
        template.description = data.description
        template.body_markdown = data.body_markdown
        template.custom_html = data.custom_html
        template.available_variables = data.available_variables
        template.enabled = data.enabled if data.enabled is not None else True

        self.repos.session.add(template)
        self.repos.session.commit()
        self.repos.session.refresh(template)

        # Auto-connect only if no workspace template of this type is already connected

        from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel
        from marvin.db.models.groups.email_templates import EmailTemplateModel as _ETM
        from marvin.services.email.system_email_events import SYSTEM_TEMPLATE_EVENT_MAP

        sys_mapping = SYSTEM_TEMPLATE_EVENT_MAP.get(template.template_type)
        if sys_mapping:
            already_connected = (
                self.repos.session.query(EmailEventSubscriptionModel)
                .join(_ETM, EmailEventSubscriptionModel.template_id == _ETM.id)
                .filter(
                    EmailEventSubscriptionModel.group_id == group_id,
                    EmailEventSubscriptionModel.event_type == sys_mapping["event_type"],
                    _ETM.template_type == template.template_type,
                    _ETM.group_id == group_id,
                )
                .first()
            )
            if not already_connected:
                sub = EmailEventSubscriptionModel(session=self.repos.session)
                sub.group_id = group_id
                sub.template_id = template.id
                sub.event_type = sys_mapping["event_type"]
                sub.recipient_type = sys_mapping["recipient_type"]
                sub.recipient_field = sys_mapping.get("recipient_field")
                sub.recipient_email = sys_mapping.get("recipient_email")
                sub.enabled = True
                self.repos.session.add(sub)
                self.repos.session.commit()

        # Dispatch event
        self.event_bus.dispatch(
            integration_id="email_template_management",
            group_id=group_id,
            event_type=EventTypes.email_template_created,
            document_data=EventEmailTemplateData(
                operation=EventOperation.create,
                template_id=str(template.id),
                template_type=template.template_type,
                system_template=False,
                workspace_id=group_id,
            ),
            message=f"Email template created: {template.name} ({template.template_type})",
            user_id=self.user.id if self.user else None,
        )

        return EmailTemplateRead.model_validate(template)

    @router.patch("/{template_id}", response_model=EmailTemplateRead, summary="Update Email Template")
    def update_template(self, group_id: UUID4, template_id: UUID4, data: EmailTemplateUpdate) -> EmailTemplateRead:
        """
        Update an email template.

        Args:
            group_id: Workspace ID
            template_id: Template ID
            data: Updated template data

        Returns:
            Updated email template
        """
        self._check_admin_access(group_id)

        # This workspace's template, or a system one (refused below); anything else is a 404.
        template = self._template_or_404(group_id, template_id)

        # Don't allow updating system templates from workspace controller
        if template.group_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot update system-wide templates from workspace controller",
            )

        update_data = data.model_dump(exclude_unset=True)
        updated_template = self.repo.update(template_id, update_data)

        # Dispatch event
        self.event_bus.dispatch(
            integration_id="email_template_management",
            group_id=group_id,
            event_type=EventTypes.email_template_updated,
            document_data=EventEmailTemplateData(
                operation=EventOperation.update,
                template_id=str(template_id),
                template_type=updated_template.template_type,
                system_template=False,
                workspace_id=group_id,
            ),
            message=f"Email template updated: {updated_template.name}",
            user_id=self.user.id if self.user else None,
        )

        return EmailTemplateRead.model_validate(updated_template)

    @router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Email Template")
    def delete_template(self, group_id: UUID4, template_id: UUID4) -> None:
        """
        Delete an email template.

        Args:
            group_id: Workspace ID
            template_id: Template ID
        """
        self._check_admin_access(group_id)

        # This workspace's template, or a system one (refused below); anything else is a 404.
        template = self._template_or_404(group_id, template_id)

        # Don't allow deleting system templates from workspace controller
        if template.group_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot delete system-wide templates from workspace controller",
            )

        template_name = template.name
        template_type = template.template_type

        self.repo.delete(template_id)

        # Dispatch event
        self.event_bus.dispatch(
            integration_id="email_template_management",
            group_id=group_id,
            event_type=EventTypes.email_template_deleted,
            document_data=EventEmailTemplateData(
                operation=EventOperation.delete,
                template_id=str(template_id),
                template_type=template_type,
                system_template=False,
                workspace_id=group_id,
            ),
            message=f"Email template deleted: {template_name}",
            user_id=self.user.id if self.user else None,
        )

    @router.post("/{template_id}/test", status_code=status.HTTP_200_OK, summary="Send Test Email")
    def send_test_email(self, group_id: UUID4, template_id: UUID4, data: TestEmailRequest) -> dict:
        """
        Send a test email using the specified template. Workspace OWNER/ADMIN only: it sends mail
        through the workspace's SMTP to any address, like the /platform/email test routes.

        Args:
            group_id: Workspace ID
            template_id: Template ID
            data: Test email request with recipient address

        Returns:
            Success message
        """
        self._check_admin_access(group_id)
        template = self._template_or_404(group_id, template_id)

        # Send test email
        from marvin.services.email.email_service import EmailService

        email_service = EmailService()

        # Build test variables covering all system template types
        test_variables = {
            "workspace_name": "Test Workspace",
            "inviter_name": "A Teammate",
            "invitee_email": data.recipient_email,
            "invitation_url": f"{self.settings.BASE_URL}/register?token=test",
            "reset_url": f"{self.settings.BASE_URL}/reset-password/?token=test",
            "login_url": str(self.settings.BASE_URL),
            "button_link": str(self.settings.BASE_URL),
            "username": "testuser",
            "first_name": "Test",
            "email": data.recipient_email,
            "email_address": data.recipient_email,
            "message_title": "Test Email",
            "message_body": "This is a test email from Marvin.",
        }

        try:
            success = email_service._send_db_template(data.recipient_email, template, test_variables)

            if not success:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to send test email. Check SMTP configuration.",
                )

            return {"message": f"Test email sent to {data.recipient_email}"}

        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error sending test email: {str(e)}",
            ) from e

    def _template_or_404(self, group_id: UUID4, template_id: UUID4) -> EmailTemplateRead:
        """The template if it belongs to `group_id` or is a system template (no workspace).

        Another workspace's template gets the same 404 as a missing id, so its ids don't leak. Callers
        that change a template refuse system ones themselves (workspaces override them by creating
        their own template of that type, never by editing the system row).
        """
        from sqlalchemy import or_

        from marvin.db.models.groups.email_templates import EmailTemplateModel

        template = (
            self.repos.session.query(EmailTemplateModel)
            .filter(
                EmailTemplateModel.id == template_id,
                or_(EmailTemplateModel.group_id == group_id, EmailTemplateModel.group_id.is_(None)),
            )
            .first()
        )
        if template is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Email template not found: {template_id}")
        return EmailTemplateRead.model_validate(template)

    def _check_workspace_access(self, group_id: UUID4) -> bool:
        """Check if user has access to workspace."""
        if self.user.admin:
            return True

        has_access = any(m.group_id == group_id for m in self.user.workspace_memberships)
        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this workspace",
            )
        return True

    def _check_admin_access(self, group_id: UUID4) -> bool:
        """Check if user has admin access to workspace."""
        if self.user.admin:
            return True

        for membership in self.user.workspace_memberships:
            if membership.group_id == group_id:
                if WORKSPACE_ROLE_HIERARCHY.get(membership.workspace_role, 0) >= 4:  # ADMIN or OWNER
                    return True

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be a workspace ADMIN or OWNER to manage email templates",
        )
