"""Form routes."""

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4

from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_admin, require_workspace_editor
from marvin.schemas.platform.form_submissions import FormSubmissionRead
from marvin.schemas.platform.forms import FormCreate, FormRead, FormUpdate
from marvin.services.event_bus_service.event_types import EventFormData, EventOperation, EventTypes

router = APIRouter(prefix="/forms")


@controller(router)
class FormsController(BaseUserController):
    """Authenticated CRUD routes for forms. Any member reads the form definitions. A form is
    structure (its schema decides what the public can submit), so creating, editing and deleting one is
    workspace-admin only; submissions carry submitters' data and IP addresses, so reading them is
    EDITOR and above."""

    @router.get("", response_model=list[FormRead], summary="List Forms")
    def list_forms(self) -> list[FormRead]:
        return self.repos.forms.get_all(order_by="name")

    @router.post("", response_model=FormRead, status_code=status.HTTP_201_CREATED, summary="Create Form")
    def create_form(self, data: FormCreate) -> FormRead:
        require_workspace_admin(self.user, self.group_id)
        form = self.repos.forms.create(data)

        # Emit event
        try:
            self.event_bus.dispatch(
                integration_id="form_management",
                group_id=self.group_id,
                event_type=EventTypes.form_created,
                document_data=EventFormData(
                    operation=EventOperation.create,
                    form_id=form.id,
                    form_name=form.name,
                    workspace_id=form.group_id,
                    workspace_name=self.group.name if self.group else None,
                    author_id=self.user.id if self.user else None,
                    author_name=self.user.full_name if self.user else None,
                ),
                message=f"Form '{form.name}' created",
                user_id=self.user.id if self.user else None,
                entity_id=form.id,
                entity_type="form",
            )
        except Exception as e:
            self.logger.error(f"Failed to dispatch form_created event: {e}", exc_info=True)

        return form

    @router.get("/{item_id}", response_model=FormRead, summary="Get Form")
    def get_form(self, item_id: UUID4) -> FormRead:
        form = self.repos.forms.get_one(item_id)
        if not form:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found.")
        return form

    @router.patch("/{item_id}", response_model=FormRead, summary="Update Form")
    def update_form(self, item_id: UUID4, data: FormUpdate) -> FormRead:
        require_workspace_admin(self.user, self.group_id)
        old_form = self.repos.forms.get_one(item_id)
        if not old_form:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found.")

        form = self.repos.forms.update(item_id, data)

        # Emit event
        try:
            self.event_bus.dispatch(
                integration_id="form_management",
                group_id=self.group_id,
                event_type=EventTypes.form_updated,
                document_data=EventFormData(
                    operation=EventOperation.update,
                    form_id=form.id,
                    form_name=form.name,
                    workspace_id=form.group_id,
                    workspace_name=self.group.name if self.group else None,
                    author_id=self.user.id if self.user else None,
                    author_name=self.user.full_name if self.user else None,
                ),
                message=f"Form '{form.name}' updated",
                user_id=self.user.id if self.user else None,
                entity_id=form.id,
                entity_type="form",
            )
        except Exception as e:
            self.logger.error(f"Failed to dispatch form_updated event: {e}", exc_info=True)

        # Emit status change events
        if old_form.status != form.status:
            try:
                if form.status == "published":
                    self.event_bus.dispatch(
                        integration_id="form_management",
                        group_id=self.group_id,
                        event_type=EventTypes.form_published,
                        document_data=EventFormData(
                            operation=EventOperation.update,
                            form_id=form.id,
                            form_name=form.name,
                            workspace_id=form.group_id,
                            workspace_name=self.group.name if self.group else None,
                            author_id=self.user.id if self.user else None,
                            author_name=self.user.full_name if self.user else None,
                        ),
                        message=f"Form '{form.name}' published",
                        user_id=self.user.id if self.user else None,
                        entity_id=form.id,
                        entity_type="form",
                    )
                elif form.status == "archived":
                    self.event_bus.dispatch(
                        integration_id="form_management",
                        group_id=self.group_id,
                        event_type=EventTypes.form_archived,
                        document_data=EventFormData(
                            operation=EventOperation.update,
                            form_id=form.id,
                            form_name=form.name,
                            workspace_id=form.group_id,
                            workspace_name=self.group.name if self.group else None,
                            author_id=self.user.id if self.user else None,
                            author_name=self.user.full_name if self.user else None,
                        ),
                        message=f"Form '{form.name}' archived",
                        user_id=self.user.id if self.user else None,
                        entity_id=form.id,
                        entity_type="form",
                    )
            except Exception as e:
                self.logger.error(f"Failed to dispatch form status event: {e}", exc_info=True)

        return form

    @router.delete("/{item_id}", summary="Delete Form")
    def delete_form(self, item_id: UUID4) -> dict:
        require_workspace_admin(self.user, self.group_id)
        form = self.repos.forms.get_one(item_id)
        if not form:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found.")

        # Emit event before deletion
        try:
            self.event_bus.dispatch(
                integration_id="form_management",
                group_id=self.group_id,
                event_type=EventTypes.form_deleted,
                document_data=EventFormData(
                    operation=EventOperation.delete,
                    form_id=form.id,
                    form_name=form.name,
                    workspace_id=form.group_id,
                    workspace_name=self.group.name if self.group else None,
                    author_id=self.user.id if self.user else None,
                    author_name=self.user.full_name if self.user else None,
                ),
                message=f"Form '{form.name}' deleted",
                user_id=self.user.id if self.user else None,
                entity_id=form.id,
                entity_type="form",
            )
        except Exception as e:
            self.logger.error(f"Failed to dispatch form_deleted event: {e}", exc_info=True)

        self.repos.forms.delete(item_id)
        return {"status": "ok", "message": "Form deleted"}

    @router.get("/{form_id}/submissions", response_model=list[FormSubmissionRead], summary="List Form Submissions")
    def list_submissions(self, form_id: UUID4, limit: int = 100, offset: int = 0) -> list[FormSubmissionRead]:
        require_workspace_editor(self.user, self.group_id)
        # Verify form exists and belongs to workspace
        form = self.repos.forms.get_one(form_id)
        if not form:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found.")

        return self.repos.form_submissions.get_by_form(form_id, limit=limit, offset=offset)
