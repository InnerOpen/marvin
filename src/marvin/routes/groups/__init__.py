from fastapi import APIRouter

from marvin.services.integrations import INTEGRATIONS_AVAILABLE

from . import (
    ai_settings_controller,
    blueprints_controller,
    email_event_subscriptions_controller,
    email_template_controller,
    invitation_controller,
    notification_controller,
    preferences_controller,
    secrets_controller,
    smtp_controller,
    variables_controller,
    webhook_controller,
)

router = APIRouter()

router.include_router(invitation_controller.router, tags=["Groups: Invitations"])
router.include_router(blueprints_controller.router, tags=["Groups: Blueprints"])
router.include_router(webhook_controller.router, tags=["Groups: Webhooks"])
router.include_router(secrets_controller.router, tags=["Groups: Secrets"])
router.include_router(smtp_controller.router, tags=["Groups: SMTP Profiles"])
router.include_router(variables_controller.router, tags=["Groups: Variables"])
if INTEGRATIONS_AVAILABLE:
    from . import integrations_controller

    router.include_router(integrations_controller.router, tags=["Groups: Integrations"])
router.include_router(notification_controller.router, tags=["Groups: Event Notifications"])
router.include_router(preferences_controller.router, tags=["Groups: Preferences"])
router.include_router(email_template_controller.router, tags=["Groups: Email Templates"])
router.include_router(email_event_subscriptions_controller.router, tags=["Groups: Email Event Subscriptions"])
router.include_router(ai_settings_controller.router, tags=["Groups: AI Workflow Settings"])
