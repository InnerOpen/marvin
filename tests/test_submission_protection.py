"""Submission protection: settings resolution, classification, exemptions, surge, platform storage."""

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from marvin.schemas.platform.submission_protection import (
    SubmissionProtectionSettings,
    resolve_submission_protection,
)
from marvin.services.platform_settings import SUBMISSION_PROTECTION_KEY, PlatformSettingsService
from marvin.services.security.client_info import get_client_ip
from marvin.services.security.submission_protection import (
    SubmissionProtectionService,
    evaluate,
    find_submitted_email,
    ip_in,
)

# --- resolution -------------------------------------------------------------------------------


def test_resolve_with_no_stored_settings_returns_defaults():
    s = resolve_submission_protection(None, None)
    assert s.mode == "review" and s.block_disposable_domains is True and s.surge_threshold is None


def test_resolve_workspace_field_overrides_platform_default():
    s = resolve_submission_protection({"mode": "review"}, {"mode": "reject"})
    assert s.mode == "reject"


def test_resolve_workspace_null_field_inherits_platform_value():
    s = resolve_submission_protection({"blocked_domains": ["spam.example"]}, {"blocked_domains": None, "mode": "off"})
    assert s.blocked_domains == ["spam.example"] and s.mode == "off"


def test_resolve_accepts_camel_case_stored_dicts_and_normalizes_domains():
    s = resolve_submission_protection({"blockedDomains": ["@Spam.Example ", "spam.example"]}, None)
    assert s.blocked_domains == ["spam.example"]


# --- classification ---------------------------------------------------------------------------


def _settings(**kw) -> SubmissionProtectionSettings:
    return SubmissionProtectionSettings(**kw)


def test_find_submitted_email_prefers_email_field_then_any_value():
    assert find_submitted_email({"name": "a@b.co", "email": "X@Y.com"}) == "x@y.com"
    assert find_submitted_email({"name": "n", "contact": "who@where.org"}) == "who@where.org"
    assert find_submitted_email({"name": "no email here"}) is None


def test_evaluate_disposable_domain_is_flagged_by_default():
    v = evaluate(_settings(), {"email": "bot@mailinator.com"}, "203.0.113.9")
    assert v.suspicious and v.reasons == ["disposable_domain:mailinator.com"]


def test_evaluate_blocked_domain_matches_subdomains():
    v = evaluate(_settings(blocked_domains=["spam.example"]), {"email": "x@mail.spam.example"}, None)
    assert v.reasons == ["blocked_domain:mail.spam.example"]


def test_evaluate_allow_list_flags_everything_else():
    s = _settings(allowed_domains=["corp.example"], block_disposable_domains=False)
    assert evaluate(s, {"email": "me@corp.example"}, None).suspicious is False
    assert evaluate(s, {"email": "me@gmail.com"}, None).reasons == ["domain_not_allowed:gmail.com"]


def test_evaluate_personal_domain_preset_is_opt_in():
    data = {"email": "me@gmail.com"}
    assert evaluate(_settings(), data, None).suspicious is False
    assert evaluate(_settings(block_personal_domains=True), data, None).reasons == ["personal_domain:gmail.com"]


def test_evaluate_mode_off_never_flags():
    assert evaluate(_settings(mode="off"), {"email": "bot@mailinator.com"}, None).suspicious is False


def test_evaluate_exempt_ip_skips_all_checks():
    s = _settings(blocked_domains=["spam.example"], exempt_ips=["10.0.0.0/8", "203.0.113.5"])
    data = {"email": "x@spam.example"}
    assert evaluate(s, data, "10.20.30.40").suspicious is False
    assert evaluate(s, data, "203.0.113.5").suspicious is False
    assert evaluate(s, data, "203.0.113.6").suspicious is True


def test_evaluate_blocked_ip_is_flagged_whatever_it_sends():
    s = _settings(blocked_ips=["198.51.100.7", "203.0.113.0/24"])
    assert evaluate(s, {"email": "a@fine.example"}, "198.51.100.7").reasons == ["blocked_ip:198.51.100.7"]
    assert evaluate(s, {"message": "no email at all"}, "203.0.113.40").reasons == ["blocked_ip:203.0.113.40"]
    assert not evaluate(s, {"email": "a@fine.example"}, "198.51.100.8").suspicious
    assert not evaluate(s, {"email": "a@fine.example"}, None).suspicious


def test_evaluate_blocked_ip_and_blocked_domain_both_give_a_reason():
    s = _settings(blocked_ips=["198.51.100.7"], blocked_domains=["spam.example"])
    assert evaluate(s, {"email": "x@spam.example"}, "198.51.100.7").reasons == ["blocked_ip:198.51.100.7", "blocked_domain:spam.example"]


def test_evaluate_an_ip_on_both_lists_is_exempt():
    s = _settings(blocked_ips=["10.0.0.0/8"], exempt_ips=["10.1.1.1"])
    assert not evaluate(s, {"email": "a@fine.example"}, "10.1.1.1").suspicious
    assert evaluate(s, {"email": "a@fine.example"}, "10.2.2.2").suspicious


def test_resolve_workspace_blocked_ips_replace_the_platform_list():
    merged = resolve_submission_protection({"blocked_ips": ["198.51.100.7"]}, {"blockedIps": [" 203.0.113.9 ", ""]})
    assert merged.blocked_ips == ["203.0.113.9"]
    assert resolve_submission_protection({"blocked_ips": ["198.51.100.7"]}, {"blocked_ips": None}).blocked_ips == ["198.51.100.7"]


def test_ip_in_ignores_garbage_entries_and_unknown_ips():
    assert ip_in("unknown", ["10.0.0.0/8"]) is False
    assert ip_in("10.1.1.1", ["not-an-ip", "10.0.0.0/8"]) is True


# --- client ip --------------------------------------------------------------------------------


def _req(headers: dict, peer: str | None = "127.0.0.1"):
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=peer) if peer else None)


def test_get_client_ip_prefers_first_forwarded_then_cloudflare_then_peer():
    assert get_client_ip(_req({"x-forwarded-for": "198.51.100.2, 10.0.0.1", "cf-connecting-ip": "1.1.1.1"})) == "198.51.100.2"
    assert get_client_ip(_req({"cf-connecting-ip": "1.1.1.1"})) == "1.1.1.1"
    assert get_client_ip(_req({})) == "127.0.0.1"
    assert get_client_ip(_req({}, peer=None)) == "unknown"


# --- storage + surge (db) ---------------------------------------------------------------------


def test_platform_settings_roundtrip_and_overwrite(db_session):
    svc = PlatformSettingsService(db_session)
    key = f"test_{uuid.uuid4().hex}"
    assert svc.get(key) is None
    svc.set(key, {"a": 1})
    svc.set(key, {"a": 2})
    assert svc.get(key) == {"a": 2}


def test_effective_settings_merges_platform_row_for_unknown_workspace(db_session):
    PlatformSettingsService(db_session).set(SUBMISSION_PROTECTION_KEY, {"mode": "reject"})
    try:
        s = SubmissionProtectionService(db_session).effective_settings(uuid.uuid4())
        assert s.mode == "reject"
    finally:
        PlatformSettingsService(db_session).set(SUBMISSION_PROTECTION_KEY, {})


def test_surge_reports_only_on_the_crossing_submission(db_session):
    svc = SubmissionProtectionService(db_session)
    policy = _settings(surge_threshold=3, surge_window_minutes=10)
    subject = uuid.uuid4()
    assert [svc.record_and_detect_surge(policy, subject) for _ in range(5)] == [None, None, 3, None, None]


def test_surge_disabled_when_no_threshold(db_session):
    assert SubmissionProtectionService(db_session).record_and_detect_surge(_settings(), uuid.uuid4()) is None


# --- admin endpoint auth ----------------------------------------------------------------------


def test_admin_submission_protection_requires_authentication(client: TestClient):
    assert client.get("/api/admin/submission-protection").status_code in (401, 403)
    assert client.put("/api/admin/submission-protection", json={}).status_code in (401, 403)
