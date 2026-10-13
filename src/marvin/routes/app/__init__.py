from fastapi import APIRouter

from . import app_about, app_changes, health

router = APIRouter(prefix="/app")
router.include_router(app_about.router, tags=["App: About"])
router.include_router(app_about.public_router, tags=["App: About (Public)"])
router.include_router(app_changes.router, tags=["App: About"])
router.include_router(health.router, tags=["App: Health Check"])
