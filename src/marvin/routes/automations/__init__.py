from fastapi import APIRouter

from . import automations_controller

router = APIRouter()
router.include_router(automations_controller.router, tags=["Automations"])
