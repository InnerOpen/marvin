"""Settings promoted out of code (2026-10-14): the security policy and email branding an admin edits; the agent and
workflow limits a workspace sets."""

import uuid

import pytest

from marvin.services import platform_policy as pp


@pytest.fixture(autouse=True)
def _fresh_policy(db_session):
    from marvin.services.platform_settings import PlatformSettingsService

    svc = PlatformSettingsService(db_session)
    saved = {k: svc.get(k) for k in (pp.SECURITY_KEY, pp.EMAIL_BRANDING_KEY)}
    pp.clear_cache()
    yield
    for key, value in saved.items():
        svc.set(key, value or {})
    pp.clear_cache()


def test_an_admin_security_value_wins_over_the_environment_and_clearing_it_goes_back(db_session):
    env_value = pp.security("SECURITY_PASSWORD_MIN_LENGTH")
    rows = pp.save_security(db_session, {"SECURITY_PASSWORD_MIN_LENGTH": 12})
    row = next(r for r in rows if r["key"] == "SECURITY_PASSWORD_MIN_LENGTH")
    assert row["value"] == 12 and row["overridden"] and row["default"] == env_value
    assert pp.security("SECURITY_PASSWORD_MIN_LENGTH") == 12

    from marvin.schemas.user.password_rules import check_password_length

    with pytest.raises(ValueError, match="at least 12"):
        check_password_length("elevenchars")
    pp.save_security(db_session, {"SECURITY_PASSWORD_MIN_LENGTH": None})
    assert pp.security("SECURITY_PASSWORD_MIN_LENGTH") == env_value


def test_out_of_range_and_unknown_security_values_are_refused(db_session):
    with pytest.raises(pp.PolicyError, match="between 6 and 128"):
        pp.save_security(db_session, {"SECURITY_PASSWORD_MIN_LENGTH": 3})
    with pytest.raises(pp.PolicyError, match="not an editable"):
        pp.save_security(db_session, {"SECRET": 1})


def test_email_branding_reaches_the_rendered_email(db_session, tmp_path):
    from marvin.services.email.email_service import EmailService, EmailTemplate

    pp.save_email_branding(db_session, {"product_name": "Mash & Burn", "footer_text": "Sent from the workshop", "accent_color": "#AA3300"})
    template = EmailService().default_template
    html = EmailTemplate(subject="Hi", header_text="Hello", message_top="Body").render_html(template)
    assert "Sent from the workshop" in html or "Mash &amp; Burn" in html or "Mash & Burn" in html
    assert "#aa3300" in html
    with pytest.raises(pp.PolicyError, match="hex colour"):
        pp.save_email_branding(db_session, {"accent_color": "orange"})
    assert pp.save_email_branding(db_session, {})["product_name"] == "Marvin"  # blank goes back to the default


@pytest.fixture
def workspace(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    gid = uuid.uuid4()
    group = Groups(session=db_session, name=f"lim-{gid.hex[:8]}", slug=f"lim-{gid.hex[:8]}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.add(GroupPreferencesModel(session=db_session, group_id=gid))
    db_session.add(WorkspaceAISettingsModel(session=db_session, group_id=gid))
    db_session.commit()
    yield gid
    db_session.rollback()
    db_session.query(WorkspaceAISettingsModel).filter_by(group_id=gid).delete()
    db_session.query(GroupPreferencesModel).filter_by(group_id=gid).delete()
    db_session.query(Groups).filter_by(id=gid).delete()
    db_session.commit()


def test_agent_limits_come_from_the_workspace_within_bounds(db_session, workspace):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.services.ai.budget import agent_limit

    assert agent_limit(db_session, workspace, "history_turns") == 10
    assert agent_limit(db_session, workspace, "bulk_ask_threshold") == 20
    row = db_session.query(WorkspaceAISettingsModel).filter_by(group_id=workspace).one()
    row.budget_config = {"history_turns": 4, "bulk_ask_threshold": 5, "agent_max_steps": 99}
    db_session.commit()
    assert agent_limit(db_session, workspace, "history_turns") == 4
    assert agent_limit(db_session, workspace, "bulk_ask_threshold") == 5
    assert agent_limit(db_session, workspace, "agent_max_steps") == 12  # past the platform cap: trimmed to it, not dropped
    row.budget_config = {"history_turns": 1}
    db_session.commit()
    assert agent_limit(db_session, workspace, "history_turns") == 2  # below the floor: raised to it


def test_workflow_limits_come_from_the_workspace(db_session, workspace):
    from marvin.db.models.groups.preferences import GroupPreferencesModel
    from marvin.services.automation.engine import approval_default_hours, workflow_max_steps
    from marvin.services.automation.validation import validate_definition

    assert workflow_max_steps(db_session, workspace) == 10 and approval_default_hours(db_session, workspace) == 72
    prefs = db_session.query(GroupPreferencesModel).filter_by(group_id=workspace).one()
    prefs.workflow_max_steps, prefs.approval_expires_hours = 15, 24
    db_session.commit()
    assert workflow_max_steps(db_session, workspace) == 15 and approval_default_hours(db_session, workspace) == 24

    twelve = {"trigger": {"type": "manual"}, "actions": [{"kind": "emit_event", "event": "entry_updated"}] * 12}
    assert not any("only the first" in i["message"] for i in validate_definition(twelve, 15))
    assert any("only the first 10" in i["message"] for i in validate_definition(twelve))


def test_the_admin_overview_reads_health_workspaces_and_spend(db_session, workspace):
    from marvin.services.admin_overview import SPEND_DAYS, overview

    data = overview(db_session)
    assert {d.key for d in data.health} >= {"tasks", "unpriced", "push", "ui_address"}
    assert all(d.tone in ("ok", "warn", "bad", "off") for d in data.health)
    assert any(w.id == str(workspace) for w in data.workspaces)
    assert len(data.spend) == SPEND_DAYS and data.spend[0].day < data.spend[-1].day
