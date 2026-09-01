"""Subject-keyed rate limiting for public submissions to submittable entry types."""

import uuid

from marvin.services.security.rate_limit_service import RateLimitService


def test_subject_rate_limit_allows_up_to_max_then_blocks(db_session):
    svc = RateLimitService(db_session)
    subject, ip = uuid.uuid4(), "1.2.3.4"
    # max 3 within the window: three allowed, fourth blocked.
    assert svc.check_subject_limit(subject, ip, 3, 60) is True
    assert svc.check_subject_limit(subject, ip, 3, 60) is True
    assert svc.check_subject_limit(subject, ip, 3, 60) is True
    assert svc.check_subject_limit(subject, ip, 3, 60) is False


def test_subject_rate_limit_is_isolated_per_subject_and_identifier(db_session):
    svc = RateLimitService(db_session)
    subject_a, subject_b = uuid.uuid4(), uuid.uuid4()

    assert svc.check_subject_limit(subject_a, "1.1.1.1", 1, 60) is True
    assert svc.check_subject_limit(subject_a, "1.1.1.1", 1, 60) is False  # a / ip1 exhausted
    # A different subject or a different IP has its own independent budget.
    assert svc.check_subject_limit(subject_b, "1.1.1.1", 1, 60) is True
    assert svc.check_subject_limit(subject_a, "2.2.2.2", 1, 60) is True
