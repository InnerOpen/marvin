"""Admin: the system Playbooks Marvin and its plugins give every workspace, and the platform switch (services/playbooks/system.py)."""

from fastapi import APIRouter, HTTPException

from marvin.routes._base import BaseAdminController, controller
from marvin.schemas.admin.system_playbooks import (
    AdminSystemPlaybook,
    AdminSystemPlaybooks,
    AdminSystemPlaybookSkipped,
    AdminSystemPlaybookSwitch,
)
from marvin.services.playbooks import system

router = APIRouter(prefix="/system-playbooks")


@controller(router)
class AdminSystemPlaybooksController(BaseAdminController):
    @router.get("", response_model=AdminSystemPlaybooks, summary="Admin: List System Playbooks")
    def list_system_playbooks(self) -> AdminSystemPlaybooks:
        """Every system Playbook of the installed packages by source, with its version, badges, the platform switch and how many
        workspaces switched it off, and what couldn't be loaded."""
        return AdminSystemPlaybooks(
            items=self._items(),
            skipped=[AdminSystemPlaybookSkipped(name=s.name, label=s.label, reason=s.reason) for s in system.catalog().skipped],
        )

    @router.put("/{name}", response_model=AdminSystemPlaybook, summary="Admin: Switch a System Playbook On or Off For The Platform")
    def switch_system_playbook(self, name: str, body: AdminSystemPlaybookSwitch) -> AdminSystemPlaybook:
        """Off means absent in every workspace (catalog, tools, agent settings), whatever each workspace chose."""
        if system.system_playbook(name) is None:
            raise HTTPException(status_code=404, detail="No such system Playbook.")
        system.switch_server(self.session, name.strip().lower(), body.enabled)
        return next(i for i in self._items() if i.name == name.strip().lower())

    def _items(self) -> list[AdminSystemPlaybook]:
        off = set(system.off_server(self.session))
        counts = system.switched_off_counts(self.session)
        return [
            AdminSystemPlaybook(
                name=p.name,
                description=p.description,
                label=p.label,
                source=p.source,
                version=p.version,
                manual_only=p.manual_only,
                allowed_tools=p.allowed_tools,
                warnings=list(p.warnings),
                files=len(p.files),
                server_off=p.name in off,
                workspaces_off=counts.get(p.name, 0),
            )
            for p in sorted(system.system_playbooks().values(), key=lambda p: (p.label, p.name))
        ]
