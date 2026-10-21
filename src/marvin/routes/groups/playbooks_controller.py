"""The Playbooks API (``/groups/playbooks``): what Settings › AI › Playbooks shows.

A Playbook is an entry of the internal ``playbook`` type (services/playbooks). The editor saves through the ordinary entries API, so
drafts, history, the Trash and the role rules are the entries' own; this adds the two things that API cannot: the list with each
Playbook's status (internal entries are kept out of the entries list), and making the type the first time a Playbook is written
(reading never creates it). EDITOR and above.
"""

from fastapi import APIRouter, HTTPException
from pydantic import UUID4

from marvin.db.models.groups.ai_threads import AIThreadModel
from marvin.db.models.users.roles import WorkspaceRole
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import has_workspace_role, require_workspace_role
from marvin.schemas.group.playbooks import PlaybookItem, PlaybookList, PlaybookType, PlaybookUse, PlaybookUses
from marvin.services import playbooks
from marvin.services.playbooks.memory import recent_uses

router = APIRouter(prefix="/groups/playbooks")


@controller(router)
class PlaybooksController(BaseUserController):
    @router.get("", response_model=PlaybookList, summary="List Playbooks")
    def list_playbooks(self) -> PlaybookList:
        """Every Playbook of this workspace outside the Trash, by name, with its status. Creates nothing."""
        require_workspace_role(self.user, self.group_id, WorkspaceRole.EDITOR)
        uses = recent_uses(self.session, self.group_id, per_playbook=1)
        items = [
            PlaybookItem(
                id=row.id,
                name=row.slug,
                description=str((row.data_json or {}).get("description") or ""),
                status=row.status,
                manual_only=(row.data_json or {}).get("manual_only") is True,
                updated_at=row.update_at,
                last_used_at=(uses.get(str(row.id)) or [{}])[0].get("used_at"),
            )
            for row in playbooks.all_playbooks(self.session, self.group_id)
        ]
        return PlaybookList(entry_type_id=playbooks.playbook_type_id(self.session, self.group_id), items=items)

    @router.post("/type", response_model=PlaybookType, summary="Make the Playbook entry type")
    def ensure_type(self) -> PlaybookType:
        """The workspace's ``playbook`` entry type, created when missing (idempotent): call before saving the first Playbook."""
        require_workspace_role(self.user, self.group_id, WorkspaceRole.EDITOR)
        return PlaybookType(entry_type_id=playbooks.ensure_playbook_type(self.session, self.group_id))

    @router.get("/{entry_id}/uses", response_model=PlaybookUses, summary="Where a Playbook was used lately")
    def playbook_uses(self, entry_id: UUID4) -> PlaybookUses:
        """The runs that loaded this Playbook, newest first (at most 20): the agent, when, and the Ask conversation if it has one."""
        from marvin.services.ai.agents import agent_names

        require_workspace_role(self.user, self.group_id, WorkspaceRole.EDITOR)
        if not any(row.id == entry_id for row in playbooks.all_playbooks(self.session, self.group_id)):
            raise HTTPException(status_code=404, detail="No such Playbook.")
        names = agent_names(self.session, self.group_id)
        found = recent_uses(self.session, self.group_id).get(str(entry_id), [])
        # A conversation is its owner's (admins see all): another person's run is listed, but not linked.
        asked = [u["thread_id"] for u in found if u["thread_id"]]
        visible = self.session.query(AIThreadModel.id).filter(AIThreadModel.id.in_(asked), AIThreadModel.group_id == self.group_id)
        if asked and not has_workspace_role(self.user, self.group_id, WorkspaceRole.ADMIN):
            visible = visible.filter(AIThreadModel.created_by == self.user.id)
        openable = {str(row.id) for row in visible} if asked else set()
        found = [{**u, "thread_id": u["thread_id"] if u["thread_id"] in openable else None} for u in found]
        return PlaybookUses(items=[PlaybookUse(**u, agent_name=names.get(u["agent_slug"] or "")) for u in found])
