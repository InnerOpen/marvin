"""Submission protection: decide whether a public submission looks suspicious, and watch for surges.

Deliberately a *classifier*, not a gate — the caller decides what the verdict means (land as
``needs_review``, or reject) according to the resolved ``mode``. Everything here is pure except the
two DB-touching methods on the service.
"""

import ipaddress
import re
from dataclasses import dataclass, field

from pydantic import UUID4
from sqlalchemy.orm import Session

from marvin.db.models.groups.preferences import GroupPreferencesModel
from marvin.schemas.platform.submission_protection import (
    SubmissionProtectionSettings,
    resolve_submission_protection,
)
from marvin.services.platform_settings import SUBMISSION_PROTECTION_KEY, PlatformSettingsService
from marvin.services.security.email_domain_presets import DISPOSABLE_DOMAINS, PERSONAL_DOMAINS
from marvin.services.security.rate_limit_service import RateLimitService

_EMAIL_RE = re.compile(r"^[^@\s]+@([^@\s]+\.[^@\s]+)$")

# Identifier used for the per-form (not per-IP) counter that feeds surge detection.
SURGE_COUNTER_IDENTIFIER = "*"


@dataclass(frozen=True)
class Verdict:
    reasons: list[str] = field(default_factory=list)

    @property
    def suspicious(self) -> bool:
        return bool(self.reasons)


def find_submitted_email(submission_data: dict) -> str | None:
    """The first value that looks like an email address. Prefers a field literally named ``email``."""
    preferred = submission_data.get("email")
    if isinstance(preferred, str) and _EMAIL_RE.match(preferred.strip()):
        return preferred.strip().lower()
    for value in submission_data.values():
        if isinstance(value, str) and _EMAIL_RE.match(value.strip()):
            return value.strip().lower()
    return None


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower()


def _domain_matches(domain: str, candidates: list[str] | frozenset[str]) -> bool:
    """Exact match or subdomain of any candidate (``mail.example.com`` matches ``example.com``)."""
    return any(domain == c or domain.endswith("." + c) for c in candidates)


def is_exempt_ip(ip_address: str | None, exempt: list[str]) -> bool:
    if not ip_address or not exempt:
        return False
    try:
        ip = ipaddress.ip_address(ip_address)
    except ValueError:
        return False
    for entry in exempt:
        try:
            if "/" in entry:
                if ip in ipaddress.ip_network(entry, strict=False):
                    return True
            elif ip == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False


def evaluate(settings: SubmissionProtectionSettings, submission_data: dict, ip_address: str | None) -> Verdict:
    """Classify one submission. Never raises; a submission with no email simply has no domain reasons."""
    if settings.mode == "off" or is_exempt_ip(ip_address, settings.exempt_ips):
        return Verdict()

    email = find_submitted_email(submission_data)
    if not email:
        return Verdict()
    domain = email_domain(email)

    reasons: list[str] = []
    if settings.allowed_domains and not _domain_matches(domain, settings.allowed_domains):
        reasons.append(f"domain_not_allowed:{domain}")
    if _domain_matches(domain, settings.blocked_domains):
        reasons.append(f"blocked_domain:{domain}")
    if settings.block_disposable_domains and _domain_matches(domain, DISPOSABLE_DOMAINS):
        reasons.append(f"disposable_domain:{domain}")
    if settings.block_personal_domains and _domain_matches(domain, PERSONAL_DOMAINS):
        reasons.append(f"personal_domain:{domain}")
    return Verdict(reasons)


class SubmissionProtectionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def effective_settings(self, group_id: UUID4) -> SubmissionProtectionSettings:
        """Platform defaults with this workspace's overrides applied."""
        platform = PlatformSettingsService(self.session).get(SUBMISSION_PROTECTION_KEY)
        prefs = self.session.query(GroupPreferencesModel).filter(GroupPreferencesModel.group_id == group_id).first()
        return resolve_submission_protection(platform, prefs.submission_protection_json if prefs else None)

    def record_and_detect_surge(self, settings: SubmissionProtectionSettings, subject_id: UUID4) -> int | None:
        """Count this submission against the form's window; return the count only on the submission
        that crosses the threshold, so a surge is reported once per window rather than per hit."""
        if not settings.surge_threshold:
            return None
        count = RateLimitService(self.session).record_submission(subject_id, SURGE_COUNTER_IDENTIFIER, settings.surge_window_minutes)
        return count if count == settings.surge_threshold else None
