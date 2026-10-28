"""The Playbooks API (``/groups/playbooks``): what Settings › AI › Playbooks shows.

A Playbook is an entry of the internal ``playbook`` type (services/playbooks). The editor saves through the ordinary entries API, so
drafts, history, the Trash and the role rules are the entries' own; this adds the two things that API cannot: the list with each
Playbook's status (internal entries are kept out of the entries list), and making the type the first time a Playbook is written
(reading never creates it). EDITOR and above.
"""

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import UUID4

from marvin.db.models.groups.ai_threads import AIThreadModel
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.users.roles import WorkspaceRole
from marvin.routes._base import BaseUserController, controller
from marvin.routes._base.checks import has_workspace_role, require_workspace_admin, require_workspace_editor
from marvin.schemas.group.playbooks import (
    PlaybookCopiedFrom,
    PlaybookFiles,
    PlaybookFileText,
    PlaybookGithubImport,
    PlaybookImported,
    PlaybookItem,
    PlaybookList,
    PlaybookOrigin,
    PlaybookType,
    PlaybookUse,
    PlaybookUses,
    SystemPlaybookCopy,
    SystemPlaybookFile,
    SystemPlaybookItem,
    SystemPlaybookList,
    SystemPlaybookRead,
    SystemPlaybookSwitch,
)
from marvin.services import playbooks
from marvin.services.assets.asset_storage_service import AssetStorageService
from marvin.services.blueprints.playbook_apply import provider_name
from marvin.services.entries.entry_service import EntryService
from marvin.services.playbooks import exporter, importer, system, system_copy
from marvin.services.playbooks import github as github_import
from marvin.services.playbooks.blueprint import PROVENANCE_KEY
from marvin.services.playbooks.memory import recent_uses

router = APIRouter(prefix="/groups/playbooks")


@controller(router)
class PlaybooksController(BaseUserController):
    @router.get("", response_model=PlaybookList, summary="List Playbooks")
    def list_playbooks(self) -> PlaybookList:
        """Every Playbook of this workspace outside the Trash, by name, with its status. Creates nothing."""
        require_workspace_editor(self.user, self.group_id)
        uses = recent_uses(self.session, self.group_id, per_playbook=1)
        live = {str(i.id): i for i in self.session.query(IntegrationModel).filter_by(group_id=self.group_id)}
        items = [
            PlaybookItem(
                id=row.id,
                name=row.slug,
                description=str((row.data_json or {}).get("description") or ""),
                status=row.status,
                manual_only=(row.data_json or {}).get("manual_only") is True,
                updated_at=row.update_at,
                last_used_at=(uses.get(str(row.id)) or [{}])[0].get("used_at"),
                from_integration=self._origin(row, live),
                copied_from=self._copied_from(row),
            )
            for row in playbooks.all_playbooks(self.session, self.group_id)
        ]
        return PlaybookList(entry_type_id=playbooks.playbook_type_id(self.session, self.group_id), items=items)

    @router.post("/type", response_model=PlaybookType, summary="Make the Playbook entry type")
    def ensure_type(self) -> PlaybookType:
        """The workspace's ``playbook`` entry type, created when missing (idempotent): call before saving the first Playbook."""
        require_workspace_editor(self.user, self.group_id)
        return PlaybookType(entry_type_id=playbooks.ensure_playbook_type(self.session, self.group_id))

    @router.get("/system", response_model=SystemPlaybookList, summary="List the system Playbooks this workspace gets")
    def list_system(self) -> SystemPlaybookList:
        """The system Playbooks (shipped by Marvin and its plugins, read-only) with whether this workspace gets each one and why not.
        Includes the ones switched off. EDITOR and above."""
        require_workspace_editor(self.user, self.group_id)
        return SystemPlaybookList(items=[self._system_item(s) for s in system.system_states(self.session, self.group_id)])

    @router.get("/system/{name}", response_model=SystemPlaybookRead, summary="One system Playbook, read-only")
    def read_system(self, name: str) -> SystemPlaybookRead:
        require_workspace_editor(self.user, self.group_id)
        state = self._system_state(name)
        p = state.playbook
        return SystemPlaybookRead(
            **self._system_item(state).model_dump(),
            source=p.source,
            fingerprint=p.hash,
            body=p.body,
            files=[SystemPlaybookFile(path=path, text=text) for path, text in p.files],
            warnings=list(p.warnings),
        )

    @router.get("/system/{name}/uses", response_model=PlaybookUses, summary="Where a system Playbook was used lately")
    def system_uses(self, name: str) -> PlaybookUses:
        """The runs of this workspace that loaded it, newest first (at most 20), as for a workspace Playbook."""
        from marvin.services.ai.agents import agent_names

        require_workspace_editor(self.user, self.group_id)
        found = self._system_state(name).playbook
        names = agent_names(self.session, self.group_id)
        uses = recent_uses(self.session, self.group_id).get(found.id, [])
        asked = [u["thread_id"] for u in uses if u["thread_id"]]
        visible = self.session.query(AIThreadModel.id).filter(AIThreadModel.id.in_(asked), AIThreadModel.group_id == self.group_id)
        if asked and not has_workspace_role(self.user, self.group_id, WorkspaceRole.ADMIN):
            visible = visible.filter(AIThreadModel.created_by == self.user.id)
        openable = {str(row.id) for row in visible} if asked else set()
        uses = [{**u, "thread_id": u["thread_id"] if u["thread_id"] in openable else None} for u in uses]
        return PlaybookUses(items=[PlaybookUse(**u, agent_name=names.get(u["agent_slug"] or "")) for u in uses])

    @router.put("/system/{name}", response_model=SystemPlaybookItem, summary="Switch a system Playbook on or off for this workspace")
    def switch_system(self, name: str, body: SystemPlaybookSwitch) -> SystemPlaybookItem:
        """ADMIN and above. Off means absent everywhere in this workspace: the catalog, the tools, agents' chosen sets and always-load
        lists. The switch is kept by name, so it survives the plugin being uninstalled and installed again."""
        require_workspace_admin(self.user, self.group_id)
        self._system_state(name)  # 404 for a name that is not installed
        system.switch_here(self.session, self.group_id, name.strip().lower(), body.enabled)
        return self._system_item(self._system_state(name))

    @router.post("/system/{name}/copy", response_model=PlaybookImported, status_code=201, summary="Copy a system Playbook to customise it")
    def copy_system(self, name: str, body: SystemPlaybookCopy | None = None) -> PlaybookImported:
        """ADMIN and above. Makes a **draft** Playbook of this workspace from the system one (its text and files), named ``name`` (the
        suggestion when omitted; 409 when taken). Once the copy is published it replaces the original here."""
        require_workspace_admin(self.user, self.group_id)
        found = self._system_state(name).playbook
        try:
            done = system_copy.copy_system_playbook(
                self.session,
                found,
                group_id=self.group_id,
                user_id=self.user.id,
                entries=self._entries(),
                assets=self._assets(),
                name=body.name if body else None,
            )
        except importer.ImportRefused as e:
            raise HTTPException(status_code=e.status_code, detail=str(e)) from e
        return self._imported(done)

    @router.post("/{entry_id}/upstream-seen", status_code=204, summary="Mark the changed original of a copy as seen")
    def upstream_seen(self, entry_id: UUID4) -> Response:
        """ADMIN and above. The copy remembers the original's current version, so its hint goes away until the original changes again."""
        require_workspace_admin(self.user, self.group_id)
        if not system_copy.mark_seen(self.session, self._find(entry_id)):
            raise HTTPException(status_code=404, detail="This Playbook is not a copy of an installed system Playbook.")
        return Response(status_code=204)

    @router.get("/{entry_id}/files", response_model=PlaybookFiles, summary="A Playbook's reference files, with their text")
    def playbook_files(self, entry_id: UUID4) -> PlaybookFiles:
        """What an Admin reads before publishing: each reference file of the Playbook (any status) by path, with its text. Read-only."""
        require_workspace_editor(self.user, self.group_id)
        found = self._find(entry_id)
        return PlaybookFiles(items=[PlaybookFileText(**row) for row in playbooks.reference_texts(self.session, found.id)])

    @router.get("/{entry_id}/uses", response_model=PlaybookUses, summary="Where a Playbook was used lately")
    def playbook_uses(self, entry_id: UUID4) -> PlaybookUses:
        """The runs that loaded this Playbook, newest first (at most 20): the agent, when, and the Ask conversation if it has one."""
        from marvin.services.ai.agents import agent_names

        require_workspace_editor(self.user, self.group_id)
        self._find(entry_id)
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

    @router.get(
        "/{entry_id}/export",
        summary="Export a Playbook as a skill folder (zip)",
        response_class=Response,
        responses={200: {"content": {"application/zip": {}}}},
    )
    def export_playbook(self, entry_id: UUID4) -> Response:
        """A zip in the standard skill layout (``<name>/SKILL.md`` and the reference files at their paths; Marvin-only settings go under
        the frontmatter's ``metadata``). Any status; importing it gives back the Playbook."""
        require_workspace_editor(self.user, self.group_id)
        filename, data = exporter.export_playbook(self.session, self._find(entry_id), self._assets())
        return Response(content=data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @router.post("/import", response_model=PlaybookImported, status_code=201, summary="Import a SKILL.md or a skill zip as a draft Playbook")
    def import_playbook(self, file: UploadFile = File(...), name: str | None = Form(None)) -> PlaybookImported:
        """Make a **draft** Playbook from a ``SKILL.md`` or a zip of a skill folder. Reference files keep their paths (``scripts/``
        too, flagged and never run) and the review of what it asks for is stored on the entry. Never published: an Admin does that.
        409 when the name is taken: send another ``name``."""
        require_workspace_editor(self.user, self.group_id)
        if file.size is not None and file.size > importer.UPLOAD_MAX:
            raise HTTPException(status_code=413, detail=f"The upload is over the {importer.UPLOAD_MAX // 1048576} MB limit.")
        data = file.file.read(importer.UPLOAD_MAX + 1)
        try:
            done = importer.import_playbook(
                self.session,
                group_id=self.group_id,
                user_id=self.user.id,
                filename=file.filename or "",
                data=data,
                entries=self._entries(),
                assets=self._assets(),
                name=name,
            )
        except importer.ImportRefused as e:
            raise HTTPException(status_code=e.status_code, detail=str(e)) from e
        return self._imported(done)

    @router.post("/import-github", response_model=PlaybookImported, status_code=201, summary="Import a skill from a GitHub link as a draft Playbook")
    def import_playbook_from_github(self, body: PlaybookGithubImport) -> PlaybookImported:
        """Like the file import, from a public GitHub link to a skill folder or its ``SKILL.md``. The link is pinned to the commit
        it names now, recorded on the draft (``metadata.source``) and shown in its review. Only github.com is fetched, with no token."""
        require_workspace_editor(self.user, self.group_id)
        try:
            package, source = github_import.fetch_package(body.url)
            done = importer.import_package(
                self.session,
                package,
                group_id=self.group_id,
                user_id=self.user.id,
                filename=source["repo"],
                entries=self._entries(),
                assets=self._assets(),
                name=body.name,
                source=source,
            )
        except importer.ImportRefused as e:
            raise HTTPException(status_code=e.status_code, detail=str(e)) from e
        return self._imported(done)

    @staticmethod
    def _copied_from(row) -> PlaybookCopiedFrom | None:
        found = system_copy.upstream(row.metadata_json)
        return PlaybookCopiedFrom(**found) if found else None

    def _system_state(self, name: str):
        found = next((s for s in system.system_states(self.session, self.group_id) if s.playbook.name == str(name).strip().lower()), None)
        if found is None:
            raise HTTPException(status_code=404, detail="No such system Playbook.")
        return found

    def _system_item(self, state) -> SystemPlaybookItem:
        p = state.playbook
        suggestion = system_copy.suggested_name(p)
        free = importer.taken_where(self.session, self.group_id, suggestion) is None and system.system_playbook(suggestion) is None
        return SystemPlaybookItem(
            name=p.name,
            description=p.description,
            label=p.label,
            version=p.version,
            manual_only=p.manual_only,
            allowed_tools=p.allowed_tools,
            state=state.state,
            detail=state.detail,
            enabled=state.enabled_here,
            suggested_copy_name=suggestion if free else "",
            file_count=len(p.files),
        )

    @staticmethod
    def _origin(row, live: dict) -> PlaybookOrigin | None:
        """Where an integration's Playbook came from; ``removed`` when its integration is no longer in the workspace."""
        found = ((row.metadata_json or {}).get(PROVENANCE_KEY)) or {}
        source = found.get("source") if isinstance(found, dict) else None
        if not source:
            return None
        integration = live.get(str(found.get("integrationId") or "")) or next((i for i in live.values() if i.provider == source), None)
        return PlaybookOrigin(
            source=source,
            name=provider_name(source),
            integration_id=integration.id if integration is not None else None,
            removed=integration is None,
        )

    def _find(self, entry_id: UUID4):
        """The Playbook entry (any status but trashed) of this workspace; 404 when there is none."""
        found = next((row for row in playbooks.all_playbooks(self.session, self.group_id) if row.id == entry_id), None)
        if found is None:
            raise HTTPException(status_code=404, detail="No such Playbook.")
        return found

    def _entries(self) -> EntryService:
        return EntryService(self.session, self.group_id, event_bus=self.event_bus, actor_id=self.user.id)

    def _assets(self) -> AssetStorageService:
        return AssetStorageService.for_workspace(self.repos)

    @staticmethod
    def _imported(done) -> PlaybookImported:
        return PlaybookImported(
            id=done.entry.id,
            name=done.entry.slug,
            status=done.entry.status,
            file_count=done.file_count,
            skipped=done.review["skipped"],
            review=done.review,
        )
