"""CRUD + connection-test routes for external MCP servers the workspace agent draws tools from.

ADMIN/OWNER-managed (registering a server is a trust decision). The `/test` endpoint powers the
UI's "connect → show tools → allowlist" flow. Deny-by-default: a server's tools stay off until
listed in `allowed_tools` AND the workspace `external_mcp_enabled` master switch is on (P4 gate).
"""

import re

from fastapi import APIRouter, HTTPException, status
from pydantic import UUID4

from marvin.db.models.groups.mcp_servers import WorkspaceMcpServerModel
from marvin.routes._base import MarvinCrudRoute
from marvin.routes._base.base_controllers import BaseUserController
from marvin.routes._base.controller import controller
from marvin.schemas.group.mcp_server import (
    McpServerCreate,
    McpServerRead,
    McpServerTestResult,
    McpServerToolInfo,
    McpServerUpdate,
)

router = APIRouter(prefix="/ai/mcp-servers", route_class=MarvinCrudRoute)

ALLOWED_TRANSPORTS = ("http", "sse")  # stdio (local subprocess) intentionally unsupported


def _require_admin(user, group_id: UUID4) -> None:
    if user.admin:
        return
    for m in user.workspace_memberships:
        if m.group_id == group_id and m.workspace_role.value >= 4:  # ADMIN=4, OWNER=5
            return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ADMIN or OWNER role required.")


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "mcp-server"


def _get_or_404(session, server_id: UUID4, group_id: UUID4) -> WorkspaceMcpServerModel:
    row = session.get(WorkspaceMcpServerModel, server_id)
    if not row or row.group_id != group_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP server not found.")
    return row


@controller(router)
class McpServersController(BaseUserController):
    """Manage the workspace's external MCP servers (ADMIN/OWNER only)."""

    @router.get("", response_model=list[McpServerRead], summary="List MCP Servers")
    def list_servers(self) -> list[McpServerRead]:
        _require_admin(self.user, self.group_id)
        rows = self.session.query(WorkspaceMcpServerModel).filter_by(group_id=self.group_id).order_by(WorkspaceMcpServerModel.name).all()
        return [McpServerRead.model_validate(r) for r in rows]

    @router.post("", response_model=McpServerRead, status_code=status.HTTP_201_CREATED, summary="Register MCP Server")
    def create_server(self, data: McpServerCreate) -> McpServerRead:
        _require_admin(self.user, self.group_id)
        if data.transport not in ALLOWED_TRANSPORTS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"transport must be one of {ALLOWED_TRANSPORTS}; stdio is not supported.",
            )
        slug = data.slug or _slugify(data.name)
        if self.session.query(WorkspaceMcpServerModel).filter_by(group_id=self.group_id, slug=slug).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"MCP server slug '{slug}' already exists.")

        payload = data.model_dump()
        payload["slug"] = slug
        row = WorkspaceMcpServerModel(session=self.session, group_id=self.group_id, created_by=self.user.id, **payload)
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return McpServerRead.model_validate(row)

    @router.get("/{server_id}", response_model=McpServerRead, summary="Get MCP Server")
    def get_server(self, server_id: UUID4) -> McpServerRead:
        _require_admin(self.user, self.group_id)
        return McpServerRead.model_validate(_get_or_404(self.session, server_id, self.group_id))

    @router.patch("/{server_id}", response_model=McpServerRead, summary="Update MCP Server")
    def update_server(self, server_id: UUID4, data: McpServerUpdate) -> McpServerRead:
        _require_admin(self.user, self.group_id)
        row = _get_or_404(self.session, server_id, self.group_id)
        if data.transport is not None and data.transport not in ALLOWED_TRANSPORTS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"transport must be one of {ALLOWED_TRANSPORTS}; stdio is not supported.",
            )
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(row, field, value)
        self.session.commit()
        self.session.refresh(row)
        return McpServerRead.model_validate(row)

    @router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete MCP Server")
    def delete_server(self, server_id: UUID4) -> None:
        _require_admin(self.user, self.group_id)
        row = _get_or_404(self.session, server_id, self.group_id)
        self.session.delete(row)
        self.session.commit()

    @router.post("/{server_id}/test", response_model=McpServerTestResult, summary="Test MCP Server (tools/list)")
    def test_server(self, server_id: UUID4) -> McpServerTestResult:
        """Connect to the server and return its tools/list — for building the allowlist in the UI."""
        _require_admin(self.user, self.group_id)
        row = _get_or_404(self.session, server_id, self.group_id)
        from marvin.services.ai import mcp_client

        try:
            tools = mcp_client.list_server_tools(row)
            return McpServerTestResult(
                success=True,
                message=f"Connected — {len(tools)} tool(s) available.",
                tools=[
                    McpServerToolInfo(
                        name=t.name, description=t.description, input_schema=t.input_schema, read_only=t.read_only, destructive=t.destructive
                    )
                    for t in tools
                ],
            )
        except Exception as e:
            return McpServerTestResult(success=False, message=str(e), tools=[])
