"""
Publishing API routes.

Public-facing read-only API for accessing published content.
Authenticated via API client tokens (marvin_sk_ prefix).
"""

from fastapi import APIRouter

from .forms_controller import router as forms_router
from .publishing_controller import router as publishing_router

# Create main publishing router with /api/publish prefix
router = APIRouter(prefix="/publish", tags=["Publishing API"])

# Include all publishing sub-routes
router.include_router(publishing_router)
router.include_router(forms_router)

__all__ = ["router"]
