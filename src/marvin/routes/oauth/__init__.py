"""The remote MCP server's OAuth routes, mounted at the root (outside /api) like the health probes.

Every route answers 404 while the `remote_mcp` platform switch is off. None is in the OpenAPI document: they are
protocol endpoints for MCP clients, not part of Marvin's API.
"""

from fastapi import APIRouter

from . import authorization, well_known

router = APIRouter(include_in_schema=False)
router.include_router(well_known.router)
router.include_router(authorization.router)
