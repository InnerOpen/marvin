"""Controller for email event subscriptions — links email templates to event types. Workspace-admin only."""

from functools import cached_property

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4

from marvin.routes._base.base_controllers import BaseUserController
from marvin.routes._base.checks import refuse_platform_events, require_workspace_admin
from marvin.routes._base.controller import controller
from marvin.schemas.group.email_event_subscription import (
    EmailEventSubscriptionCreate,
    EmailEventSubscriptionRead,
)

router = APIRouter(prefix="/groups/email-event-subscriptions")


@controller(router)
class EmailEventSubscriptionsController(BaseUserController):
    @cached_property
    def repo(self):
        return self.repos.email_event_subscriptions

    def _require_usable_template(self, template_id: UUID4) -> None:
        """A subscription may send this workspace's templates or a system one (no workspace). Another
        workspace's template gets the same 404 as a missing id, so its ids don't leak."""
        from sqlalchemy import or_

        from marvin.db.models.groups.email_templates import EmailTemplateModel

        found = (
            self.session.query(EmailTemplateModel.id)
            .filter(
                EmailTemplateModel.id == template_id,
                or_(EmailTemplateModel.group_id == self.group_id, EmailTemplateModel.group_id.is_(None)),
            )
            .first()
        )
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email template not found")

    def _replaces_marvins_email(self, data: EmailEventSubscriptionCreate) -> bool:
        """The connection of this workspace's own template of a system email's type to that email's event (the
        "Replaces Marvin's welcome email" switch): it changes what Marvin's email says, never who gets it
        (system_email_route), so it may name a platform event (user_signup)."""
        from marvin.db.models.groups.email_templates import EmailTemplateModel
        from marvin.services.email.system_email_events import get_template_type_for_event

        template_type = get_template_type_for_event(data.event_type)
        if template_type is None:
            return False
        return (
            self.session.query(EmailTemplateModel.id)
            .filter(
                EmailTemplateModel.id == data.template_id,
                EmailTemplateModel.group_id == self.group_id,
                EmailTemplateModel.template_type == template_type,
            )
            .first()
            is not None
        )

    @router.get("", response_model=list[EmailEventSubscriptionRead])
    def get_all(self) -> list[EmailEventSubscriptionRead]:
        """List all email event subscriptions for the current workspace."""
        require_workspace_admin(self.user, self.group_id)
        return self.repo.get_all()

    @router.post("", response_model=EmailEventSubscriptionRead, status_code=status.HTTP_201_CREATED)
    def create_one(self, data: EmailEventSubscriptionCreate) -> EmailEventSubscriptionRead:
        """Create a new email event subscription."""
        require_workspace_admin(self.user, self.group_id)
        self._require_usable_template(data.template_id)
        if not self._replaces_marvins_email(data):
            refuse_platform_events([data.event_type])
        save_data = data.model_copy(update={"group_id": self.group_id})
        return self.repo.create(save_data)

    @router.get("/{item_id}", response_model=EmailEventSubscriptionRead)
    def get_one(self, item_id: UUID4) -> EmailEventSubscriptionRead:
        """Get a specific email event subscription by ID."""
        require_workspace_admin(self.user, self.group_id)
        sub = self.repo.get_one(item_id)
        if sub is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
        return sub

    @router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_one(self, item_id: UUID4) -> None:
        """Delete an email event subscription."""
        require_workspace_admin(self.user, self.group_id)
        self.repo.delete(item_id)
