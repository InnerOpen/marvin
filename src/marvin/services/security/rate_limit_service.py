"""Rate limiting service for form submissions."""

from datetime import UTC, datetime, timedelta

from pydantic import UUID4
from sqlalchemy.orm import Session

from marvin.db.models.platform.form_rate_limits import FormRateLimits
from marvin.db.models.platform.submission_rate_limits import SubmissionRateLimits


class RateLimitService:
    """Service for enforcing form submission rate limits."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def check_subject_limit(self, subject_id: UUID4, identifier: str, max_submissions: int, window_minutes: int) -> bool:
        """Windowed rate check for a submittable subject (an entry type). Generalizes ``check_limit``
        off the ``forms.id`` FK so the entry-type submit path can be rate-limited.

        Returns True if the submission is allowed, False if the limit is exceeded.
        """
        record = self._current_window(subject_id, identifier, window_minutes)
        if record is None:
            self._open_window(subject_id, identifier)
            return True
        if record.submission_count >= max_submissions:
            return False
        record.submission_count += 1
        self.session.commit()
        return True

    def record_submission(self, subject_id: UUID4, identifier: str, window_minutes: int) -> int:
        """Unconditionally count one submission for (subject, identifier) and return the window total.
        Feeds surge detection, which wants the count rather than an allow/deny."""
        record = self._current_window(subject_id, identifier, window_minutes)
        if record is None:
            self._open_window(subject_id, identifier)
            return 1
        record.submission_count += 1
        self.session.commit()
        return record.submission_count

    def _current_window(self, subject_id: UUID4, identifier: str, window_minutes: int) -> SubmissionRateLimits | None:
        window_start = datetime.now(UTC) - timedelta(minutes=window_minutes)
        return (
            self.session.query(SubmissionRateLimits)
            .filter(
                SubmissionRateLimits.subject_id == subject_id,
                SubmissionRateLimits.identifier == identifier,
                SubmissionRateLimits.window_start >= window_start,
            )
            .first()
        )

    def _open_window(self, subject_id: UUID4, identifier: str) -> SubmissionRateLimits:
        record = SubmissionRateLimits(
            session=self.session,
            subject_id=subject_id,
            identifier=identifier,
            window_start=datetime.now(UTC),
            submission_count=1,
        )
        self.session.add(record)
        self.session.commit()
        return record

    def check_limit(self, form_id: UUID4, identifier: str, settings: dict | None) -> bool:
        """Check if submission is within rate limit.

        Args:
            form_id: Form UUID
            identifier: IP address or API client ID
            settings: Form settings_json containing rate limit config

        Returns:
            True if submission is allowed, False if rate limit exceeded
        """
        # Get rate limit settings
        if not settings or not settings.get("security", {}).get("rateLimit", {}).get("enabled", True):
            return True  # Rate limiting disabled

        rate_config = settings.get("security", {}).get("rateLimit", {})
        max_submissions = rate_config.get("maxSubmissions", 10)
        window_minutes = rate_config.get("windowMinutes", 60)

        # Calculate window start
        now = datetime.now(UTC)
        window_start = now - timedelta(minutes=window_minutes)

        # Get or create rate limit record
        rate_limit = (
            self.session.query(FormRateLimits)
            .filter(
                FormRateLimits.form_id == form_id,
                FormRateLimits.identifier == identifier,
                FormRateLimits.window_start >= window_start,
            )
            .first()
        )

        if not rate_limit:
            # First submission in this window
            rate_limit = FormRateLimits(
                session=self.session,
                form_id=form_id,
                identifier=identifier,
                window_start=now,
                submission_count=1,
            )
            self.session.add(rate_limit)
            self.session.commit()
            return True

        # Check if limit exceeded
        if rate_limit.submission_count >= max_submissions:
            return False

        # Increment count
        rate_limit.submission_count += 1
        self.session.commit()
        return True

    def cleanup_old_records(self, days: int = 7) -> None:
        """Clean up rate limit records older than N days.

        Args:
            days: Number of days to keep records
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        self.session.query(FormRateLimits).filter(FormRateLimits.window_start < cutoff).delete()
        self.session.query(SubmissionRateLimits).filter(SubmissionRateLimits.window_start < cutoff).delete()
        self.session.commit()
