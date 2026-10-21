from fastapi import APIRouter

from marvin.services.integrations import INTEGRATIONS_AVAILABLE

from . import (
    ai_settings_controller,
    audience_controller,
    audit_settings_controller,
    automation_results_controller,
    blueprints_controller,
    custom_events_controller,
    email_branding_controller,
    email_event_subscriptions_controller,
    email_template_controller,
    invitation_controller,
    metrics_controller,
    notifications_controller,
    playbooks_controller,
    preferences_controller,
    removed_integration_controller,
    secrets_controller,
    smtp_controller,
    storage_settings_controller,
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
    router.include_router(integrations_controller.public_router, tags=["Groups: Integrations"])

    from . import social_inbox_controller

    router.include_router(social_inbox_controller.router, tags=["Groups: Social Inbox"])
router.include_router(audience_controller.router, tags=["Groups: Audience"])
router.include_router(playbooks_controller.router, tags=["Groups: Playbooks"])
router.include_router(automation_results_controller.router, tags=["Groups: Automation Results"])
router.include_router(preferences_controller.router, tags=["Groups: Preferences"])
router.include_router(email_template_controller.router, tags=["Groups: Email Templates"])
router.include_router(email_branding_controller.router, tags=["Groups: Email Branding"])
router.include_router(email_event_subscriptions_controller.router, tags=["Groups: Email Event Subscriptions"])
router.include_router(ai_settings_controller.router, tags=["Groups: AI Workflow Settings"])
router.include_router(storage_settings_controller.router, tags=["Groups: Storage"])
router.include_router(audit_settings_controller.router, tags=["Groups: Audit Settings"])
router.include_router(custom_events_controller.router, tags=["Groups: Custom Events"])
router.include_router(notifications_controller.router, tags=["Groups: Notifications"])
router.include_router(metrics_controller.router, tags=["Groups: Metrics"])
router.include_router(removed_integration_controller.router, tags=["Groups: Removed Integration Items"])
