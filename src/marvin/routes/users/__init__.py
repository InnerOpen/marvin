from fastapi import APIRouter

from . import (
    api_token_controller,
    forgot_password_controller,
    push_controller,
    registration_controller,
    user_controller,
    workspace_activation_controller,
)

user_prefix = "/users"


router = APIRouter()


router.include_router(registration_controller.router, prefix=user_prefix, tags=["Users: Registration"])
router.include_router(user_controller.user_router)
# router.include_router(user_controller.admin_router)
router.include_router(forgot_password_controller.router, prefix=user_prefix, tags=["Users: Passwords"])
router.include_router(api_token_controller.router)
router.include_router(push_controller.router)
router.include_router(workspace_activation_controller.router)
