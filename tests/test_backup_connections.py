"""Backup/restore carries workspace connections & config, re-resolving cross-references.

Covers the paths the live round-trip didn't: nested AI models, an email subscription re-linked to
its template by type, an integration subscription re-linked by slug, a webhook method enum that must
survive JSON, and the incoming-webhook token-collision guard.
"""

import uuid

from pytest import fixture

from marvin.db.models.groups import Groups
from marvin.db.models.groups.ai_providers import AIModelModel, AIProviderModel
from marvin.db.models.groups.email_event_subscriptions import EmailEventSubscriptionModel
from marvin.db.models.groups.email_templates import EmailTemplateModel
from marvin.db.models.groups.incoming_webhooks import WorkspaceIncomingWebhookModel
from marvin.db.models.groups.integration_event_subscriptions import IntegrationEventSubscriptionModel
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.groups.webhooks import GroupWebhooksModel, Method
from marvin.repos.all_repositories import get_repositories
from marvin.repos.seed.workspace_exporter import WorkspaceExporter
from marvin.repos.seed.workspace_seed_loader import WorkspaceSeedLoader

# FK-safe delete order (children before parents) for teardown.
_CLEANUP_MODELS = [
    IntegrationEventSubscriptionModel,
    EmailEventSubscriptionModel,
    EmailTemplateModel,
    AIModelModel,
    AIProviderModel,
    IntegrationModel,
    GroupWebhooksModel,
    WorkspaceIncomingWebhookModel,
]


def _mk_group(db_session, marker):
    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"conn-{marker}", slug=f"conn-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.commit()
    return gid


@fixture
def two_groups(db_session):
    src = _mk_group(db_session, uuid.uuid4().hex[:8])
    dst = _mk_group(db_session, uuid.uuid4().hex[:8])
    yield src, dst
    for gid in (src, dst):
        for model in _CLEANUP_MODELS:
            db_session.query(model).filter(model.group_id == gid).delete()
        db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _seed_source(db_session, gid):
    provider = AIProviderModel(session=db_session, group_id=gid, name="OpenAI", slug="openai", provider_type="openai", secret_ref="OPENAI_KEY")
    db_session.add(provider)
    db_session.flush()
    db_session.add(
        AIModelModel(
            session=db_session, group_id=gid, provider_id=provider.id, name="GPT-4o", model_id="gpt-4o", supports_vision=True, supports_tools=True
        )
    )
    db_session.add(AIModelModel(session=db_session, group_id=gid, provider_id=provider.id, name="GPT-4o mini", model_id="gpt-4o-mini"))

    integ = IntegrationModel(
        session=db_session, group_id=gid, provider="vercel_deploy", name="Vercel", slug="vercel", secret_ref="INTEGRATION_VERCEL"
    )
    db_session.add(integ)
    db_session.flush()
    db_session.add(
        IntegrationEventSubscriptionModel(
            session=db_session, group_id=gid, integration_id=integ.id, event_type="entry.published", action="deploy", args={"prod": True}
        )
    )

    tmpl = EmailTemplateModel(session=db_session, group_id=gid, template_type="custom", name="Custom", subject="Hi {{workspace_name}}")
    db_session.add(tmpl)
    db_session.flush()
    db_session.add(
        EmailEventSubscriptionModel(session=db_session, group_id=gid, template_id=tmpl.id, event_type="entry_created", recipient_type="admins")
    )

    db_session.add(
        GroupWebhooksModel(session=db_session, group_id=gid, name="Deploy", url="https://example.com/hook", method=Method.POST, enabled=True)
    )
    db_session.add(
        WorkspaceIncomingWebhookModel(session=db_session, group_id=gid, name="Ingress", slug="ingress", enabled=True, token="TOK-collision-123")
    )
    db_session.commit()


def test_connections_round_trip_with_cross_refs(db_session, two_groups):
    src, dst = two_groups
    _seed_source(db_session, src)

    data = WorkspaceExporter(get_repositories(db_session, group_id=src)).export_workspace()
    res = WorkspaceSeedLoader(get_repositories(db_session, group_id=None))._load_data(data, overwrite=True, target_group_id=str(dst))

    assert res["errors"] == 0
    assert res["ai_providers"] == 1 and res["integrations"] == 1
    assert res["email_templates"] == 1 and res["email_subscriptions"] == 1
    assert res["integration_subscriptions"] == 1 and res["webhooks"] == 1 and res["incoming_webhooks"] == 1

    # Nested models restored under the new provider.
    prov = db_session.query(AIProviderModel).filter_by(group_id=dst, slug="openai").one()
    models = db_session.query(AIModelModel).filter_by(provider_id=prov.id).all()
    assert {m.model_id for m in models} == {"gpt-4o", "gpt-4o-mini"}
    assert next(m for m in models if m.model_id == "gpt-4o").supports_vision is True

    # Email subscription re-linked to the restored template (new id), not the source's.
    dst_tmpl = db_session.query(EmailTemplateModel).filter_by(group_id=dst, template_type="custom").one()
    sub = db_session.query(EmailEventSubscriptionModel).filter_by(group_id=dst).one()
    assert sub.template_id == dst_tmpl.id and sub.event_type == "entry_created"

    # Integration subscription re-linked to the restored integration by slug; args preserved.
    dst_integ = db_session.query(IntegrationModel).filter_by(group_id=dst, slug="vercel").one()
    isub = db_session.query(IntegrationEventSubscriptionModel).filter_by(group_id=dst).one()
    assert isub.integration_id == dst_integ.id and isub.args == {"prod": True}

    # Webhook method enum survived the JSON round-trip.
    wh = db_session.query(GroupWebhooksModel).filter_by(group_id=dst).one()
    assert wh.method == Method.POST and str(wh.url).startswith("https://example.com")

    # Token already held by the source webhook on this instance → dropped on import (deny-by-default).
    inc = db_session.query(WorkspaceIncomingWebhookModel).filter_by(group_id=dst, slug="ingress").one()
    assert inc.token is None
