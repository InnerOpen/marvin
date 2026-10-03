"""What changed between two versions of Marvin — the release notes behind the admin's update banner.

The banner knows the versions its page was rendered with and the live ones; it asks the live
backend for the releases in between. Any signed-in user can see them (the banner shows for all).
"""

from fastapi import Query

from marvin.routes._base import UserAPIRouter
from marvin.schemas.app import ChangelogRelease
from marvin.services import changelog

router = UserAPIRouter()


@router.get("/changes", response_model=list[ChangelogRelease], summary="What changed between two versions")
def get_app_changes(
    since: str | None = Query(None, description="The version the caller is on; only newer releases are returned."),
    until: str | None = Query(None, description="The newest release to include; defaults to the running version."),
    since_commit: str | None = Query(None, description="A commit sha (prefix) the caller's frontend was built from."),
) -> list[ChangelogRelease]:
    """Release notes from CHANGELOG.md, newest first.

    Starts after the older of `since` and the release listing `since_commit`; falls back to the
    latest few releases when neither can be placed. Empty when the changelog isn't installed.
    """
    return changelog.select_releases(changelog.get_releases(), since=since, until=until, since_commit=since_commit)
