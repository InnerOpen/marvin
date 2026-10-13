"""Incoming (ingress) webhook routes: a public receiver + admin CRUD/token management."""

from fastapi import APIRouter

from . import hooks_controller, incoming_webhooks_controller

router = APIRouter()
router.include_router(incoming_webhooks_controller.router, tags=["Incoming Webhooks"])
router.include_router(hooks_controller.router, tags=["Incoming Webhooks"])
