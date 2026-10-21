"""Import a skill from a public GitHub link: ``https://github.com/<owner>/<repo>[/tree|blob/<ref>/<path>]``.

* ``parse_github_url`` reads the link (a skill folder under ``tree``, a ``SKILL.md`` under ``blob``, or a repository root).
* ``fetch_package`` pins the link to a commit and returns a ``Package``: it asks the GitHub API which commit the ref names,
  downloads the repository archive of **that commit** (one request, not a request per file), and reads the skill folder out of
  it in memory with the same limits and path checks as an uploaded zip (``importer.read_repo_archive``). Nothing is written to
  disk and no archive member name is used as a path.

Every request goes through core's guarded HTTP client (services/integrations/http_client.py), narrowed to the public GitHub
hosts for the first request and every redirect (the archive is served from ``codeload.github.com``). No token is sent: only
public repositories import, and GitHub's anonymous rate limit (60 an hour) applies. A ref with a slash in it (``feature/x``)
is ambiguous in a link, so each way of splitting it is tried, a few at most, until GitHub knows the ref.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

from marvin.services.playbooks.importer import ARCHIVE_MAX, SKILL_FILE, GithubSource, ImportRefused, Package, read_repo_archive

API = "https://api.github.com"
PAGE_HOSTS = {"github.com", "www.github.com"}
ALLOWED_HOSTS = frozenset({"github.com", "api.github.com", "codeload.github.com"})
REF_SPLITS_MAX = 4
TIMEOUT = 20
SOURCE_URL_MAX = 500  # characters of the link kept on the draft (`metadata.source.url`); not a Playbook field limit

_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class GithubLink:
    owner: str
    repo: str
    kind: str  # "repo" | "tree" | "blob"
    rest: tuple[str, ...] = ()  # the segments after tree/ or blob/: the ref, then the path


def parse_github_url(raw: str) -> GithubLink:
    """The link's parts. Raises ImportRefused (400) for anything that is not a github.com repository, folder or file link."""
    text = (raw or "").strip()
    if not text:
        raise ImportRefused("Paste a GitHub link to a skill folder or a SKILL.md file.")
    parsed = urlparse(text if "://" in text else f"https://{text}")
    if parsed.scheme not in ("http", "https") or (parsed.hostname or "").lower() not in PAGE_HOSTS or parsed.username or parsed.port:
        raise ImportRefused("Only public github.com links can be imported (for example https://github.com/owner/repo/tree/main/skills/name).")
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise ImportRefused("That link has no repository in it: use https://github.com/<owner>/<repo>/tree/<branch>/<folder>.")
    owner, repo = parts[0], parts[1].removesuffix(".git")
    if not _NAME.match(owner) or not _NAME.match(repo) or repo in (".", ".."):
        raise ImportRefused("That is not a valid GitHub repository link.")
    if len(parts) == 2:
        return GithubLink(owner, repo, "repo")
    if parts[2] not in ("tree", "blob") or len(parts) < 4:
        raise ImportRefused("Link a skill folder (…/tree/<branch>/<folder>) or a SKILL.md file (…/blob/<branch>/<folder>/SKILL.md).")
    rest = tuple(parts[3:])
    if any(p in (".", "..") or "/" in p or "\\" in p or "\x00" in p for p in rest):
        raise ImportRefused("That link's path is not valid.")
    return GithubLink(owner, repo, parts[2], rest)


def _candidates(link: GithubLink) -> list[tuple[str | None, str]]:
    """(ref, skill folder) readings of the link, most likely first. ``ref`` None is the repository's default branch."""
    if link.kind == "repo":
        return [(None, "")]
    if link.kind == "blob" and (len(link.rest) < 2 or link.rest[-1] != SKILL_FILE):
        raise ImportRefused("A file link must point at a SKILL.md. To import a whole skill, link its folder instead.")
    out: list[tuple[str | None, str]] = []
    for k in range(1, min(len(link.rest), REF_SPLITS_MAX) + 1):
        path = list(link.rest[k:])
        if link.kind == "blob":
            if not path:
                break
            path = path[:-1]
        out.append(("/".join(link.rest[:k]), "/".join(path)))
    return out


def _refused(response, what: str) -> ImportRefused:
    """A GitHub reply that was not a success, in words for the person importing."""
    status = response.status_code
    headers = {k.lower(): v for k, v in (response.headers or {}).items()}
    if status == 429 or (status == 403 and (headers.get("x-ratelimit-remaining") == "0" or "rate limit" in response.text.lower())):
        return ImportRefused("GitHub's rate limit for anonymous requests is used up for now. Try again in a little while.", 429)
    if status in (404, 410, 451):
        return ImportRefused("GitHub could not find that. Check the link, and that the repository is public.", 404)
    return ImportRefused(f"GitHub answered with an error ({status}) while {what}. Try again later.", 502)


def _get(http, url: str, accept: str):
    from marvin.services.integrations.http_client import SsrfError

    try:
        return http.get(url, headers={"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}, timeout=TIMEOUT)
    except SsrfError:
        raise ImportRefused("That link leads somewhere other than public GitHub.") from None
    except ValueError as e:
        if "size cap" in str(e):
            raise ImportRefused(
                f"That repository is too large to import (the limit is {ARCHIVE_MAX // 1048576} MB for the whole repository). "
                "Download just the skill folder as a zip and upload that.",
                413,
            ) from None
        raise
    except OSError:
        raise ImportRefused("Could not reach GitHub. Try again later.", 502) from None


def _resolve_commit(http, link: GithubLink, ref: str | None) -> str | None:
    """The full commit sha the ref names, or None when GitHub does not know the ref (the next reading is tried)."""
    from urllib.parse import quote

    url = f"{API}/repos/{link.owner}/{link.repo}/commits/{quote(ref or 'HEAD', safe='')}"
    response = _get(http, url, "application/vnd.github.sha")
    if response.status_code in (404, 422):
        return None
    if not response.ok:
        raise _refused(response, "looking up the commit")
    sha = response.text.strip().lower()
    if not _SHA.match(sha):
        raise ImportRefused("GitHub's answer about the commit was not understood.", 502)
    return sha


def fetch_package(url: str, http=None) -> tuple[Package, GithubSource]:
    """The Package for a GitHub link and its provenance ``{url, repo, path, commit}`` (the commit is the one the ref named just
    now, so the draft records exactly what was read). ``http`` is for tests; the default is the guarded client."""
    link = parse_github_url(url)
    candidates = _candidates(link)
    if http is None:
        from marvin.services.integrations.http_client import MarvinHttpHelper

        http = MarvinHttpHelper(max_bytes=ARCHIVE_MAX, allowed_hosts=ALLOWED_HOSTS)
    commit, subdir = None, ""
    for ref, path in candidates:
        commit = _resolve_commit(http, link, ref)
        if commit:
            subdir = path
            break
    if not commit:
        raise ImportRefused("GitHub could not find that branch, tag or commit. Check the link, and that the repository is public.", 404)
    archive = _get(http, f"{API}/repos/{link.owner}/{link.repo}/zipball/{commit}", "application/vnd.github+json")
    if not archive.ok:
        raise _refused(archive, "downloading the repository")
    package = read_repo_archive(archive.content, subdir)
    source: GithubSource = {"url": url.strip()[:SOURCE_URL_MAX], "repo": f"{link.owner}/{link.repo}", "path": subdir, "commit": commit}
    return package, source
