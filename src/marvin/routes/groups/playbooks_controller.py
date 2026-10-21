"""The Playbooks API (``/groups/playbooks``): what Settings › AI › Playbooks shows.

A Playbook is an entry of the internal ``playbook`` type (services/playbooks). The editor saves through the ordinary entries API, so
drafts, history, the Trash and the role rules are the entries' own; this adds the two things that API cannot: the list with each
Playbook's status (internal entries are kept out of the entries list), and making the type the first time a Playbook is written
(reading never creates it). EDITOR and above.
"""

from fastapi import APIRouter

from marvin.db.models.users.roles import WorkspaceRole
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import require_workspace_role
from marvin.schemas.group.playbooks import PlaybookItem, PlaybookList, PlaybookType
from marvin.services import playbooks

router = APIRouter(prefix="/groups/playbooks")


@controller(router)
class PlaybooksController(BaseUserController):
    @router.get("", response_model=PlaybookList, summary="List Playbooks")
    def list_playbooks(self) -> PlaybookList:
        """Every Playbook of this workspace outside the Trash, by name, with its status. Creates nothing."""
        require_workspace_role(self.user, self.group_id, WorkspaceRole.EDITOR)
        items = [
            PlaybookItem(
                id=row.id,
                name=row.slug,
                description=str((row.data_json or {}).get("description") or ""),
                status=row.status,
                manual_only=(row.data_json or {}).get("manual_only") is True,
                updated_at=row.update_at,
            )
            for row in playbooks.all_playbooks(self.session, self.group_id)
        ]
        return PlaybookList(entry_type_id=playbooks.playbook_type_id(self.session, self.group_id), items=items)

    @router.post("/type", response_model=PlaybookType, summary="Make the Playbook entry type")
    def ensure_type(self) -> PlaybookType:
        """The workspace's ``playbook`` entry type, created when missing (idempotent): call before saving the first Playbook."""
        require_workspace_role(self.user, self.group_id, WorkspaceRole.EDITOR)
        return PlaybookType(entry_type_id=playbooks.ensure_playbook_type(self.session, self.group_id))
