# ruff: noqa: F811 — the `workspace` fixture is imported, then named as a parameter
"""Playbooks 09: import a skill from a public GitHub link, pinned to a commit.

GitHub is faked (no network): ``FakeGithub`` stands in for the guarded HTTP client and answers the two requests the import makes
(the commit lookup and the repository archive). The real client's host narrowing is tested against its own redirect handler.
"""

import io
import zipfile
from pathlib import Path

import pytest

from marvin.db.models.users.roles import WorkspaceRole
from marvin.services import playbooks
from marvin.services.integrations import http_client
from marvin.services.integrations.http_client import MarvinHttpHelper, Response, SsrfError
from marvin.services.playbooks import github, importer
from marvin.services.playbooks.github import GithubLink, fetch_package, parse_github_url
from marvin.services.playbooks.importer import ImportRefused
from tests import test_content_role_gates as gates

workspace = gates.workspace

SHA = "0123456789abcdef0123456789abcdef01234567"
SKILL = "---\nname: {name}\ndescription: Does a thing. Use when asked.\n---\n\n{body}\n"
IMPORT = "/api/groups/playbooks/import-github"


def skill(name="tdd", body="# Steps\n\nSee [tests](tests.md)."):
    return SKILL.format(name=name, body=body)


def repo_zip(files: dict[str, bytes | str], top: str = "owner-repo-0123456") -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{top}/", "")
        z.writestr(f"{top}/README.md", "# the repo")
        for path, data in files.items():
            z.writestr(f"{top}/{path}", data)
    return out.getvalue()


class FakeGithub:
    """Answers ``commits/<ref>`` from ``refs`` and ``zipball/<sha>`` from ``archives``; records every URL it is asked for."""

    def __init__(self, refs=None, archive=b"", archive_status=200, commit_status=None, headers=None):
        self.refs = refs if refs is not None else {"main": SHA, "HEAD": SHA}
        self.archive = archive
        self.archive_status = archive_status
        self.commit_status = commit_status
        self.headers = headers or {}
        self.urls: list[str] = []

    def get(self, url, *, headers=None, timeout=15):
        self.urls.append(url)
        assert url.startswith("https://api.github.com/"), url
        assert not any(k.lower() == "authorization" for k in (headers or {})), "no token is ever sent"
        tail = url.split("/commits/", 1)[1] if "/commits/" in url else None
        if tail is not None:
            if self.commit_status:
                return Response(self.commit_status, self.headers, b"{}")
            ref = tail.replace("%2F", "/")
            if ref in self.refs:
                return Response(200, {}, self.refs[ref].encode())
            return Response(404, {}, b'{"message":"Not Found"}')
        assert "/zipball/" in url
        assert url.rsplit("/", 1)[1] == SHA, "the archive is fetched by commit, never by branch name"
        return Response(self.archive_status, self.headers, self.archive)


TDD_FILES = {"skills/engineering/tdd/SKILL.md": skill(), "skills/engineering/tdd/tests.md": "# tests\n", "skills/other/SKILL.md": skill("other")}


# ── The link ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://github.com/mattpocock/skills/tree/main/skills/engineering/tdd",
            GithubLink("mattpocock", "skills", "tree", ("main", "skills", "engineering", "tdd")),
        ),
        ("https://github.com/o/r/blob/v1.2/a/SKILL.md", GithubLink("o", "r", "blob", ("v1.2", "a", "SKILL.md"))),
        ("https://github.com/o/r", GithubLink("o", "r", "repo")),
        ("https://github.com/o/r.git/", GithubLink("o", "r", "repo")),
        ("github.com/o/r/tree/main/", GithubLink("o", "r", "tree", ("main",))),
        ("https://www.github.com/o/r/tree/main/x/?tab=readme#top", GithubLink("o", "r", "tree", ("main", "x"))),
    ],
)
def test_links_are_read(url, expected):
    assert parse_github_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "https://gitlab.com/o/r/tree/main/x",
        "https://github.com.evil.example/o/r",
        "https://evil.example/github.com/o/r",
        "https://user@github.com/o/r",
        "https://github.com:8443/o/r",
        "ftp://github.com/o/r",
        "https://github.com/o",
        "https://github.com/o/r/issues/4",
        "https://github.com/o/r/tree",
        "https://github.com/o/r/tree/main/../../etc",
        "https://github.com/o/r/tree/main/a%2F..%2Fb",
        "https://github.com/o r/x",
        "https://127.0.0.1/o/r",
    ],
)
def test_other_links_are_refused(url):
    with pytest.raises(ImportRefused) as e:
        parse_github_url(url)
    assert e.value.status_code == 400


def test_a_blob_link_must_name_a_skill_md():
    with pytest.raises(ImportRefused, match="SKILL.md"):
        fetch_package("https://github.com/o/r/blob/main/skills/tdd/README.md", FakeGithub())


# ── Pinning and reading ──────────────────────────────────────────────────────


def test_a_folder_link_is_pinned_to_the_commit_and_reads_only_that_folder():
    gh = FakeGithub(archive=repo_zip(TDD_FILES))
    package, source = fetch_package("https://github.com/o/r/tree/main/skills/engineering/tdd", gh)
    assert source == {
        "url": "https://github.com/o/r/tree/main/skills/engineering/tdd",
        "repo": "o/r",
        "path": "skills/engineering/tdd",
        "commit": SHA,
    }
    assert package.kind == "github" and package.doc.name == "tdd"
    assert [f.path for f in package.files] == ["tests.md"]  # the sibling skill and the README are not part of it
    assert gh.urls == ["https://api.github.com/repos/o/r/commits/main", f"https://api.github.com/repos/o/r/zipball/{SHA}"]


def test_a_blob_link_takes_the_folder_of_the_file():
    package, source = fetch_package("https://github.com/o/r/blob/main/skills/engineering/tdd/SKILL.md", FakeGithub(archive=repo_zip(TDD_FILES)))
    assert source["path"] == "skills/engineering/tdd" and [f.path for f in package.files] == ["tests.md"]


def test_a_repo_root_with_a_skill_md_resolves_the_default_branch():
    gh = FakeGithub(archive=repo_zip({"SKILL.md": skill("root-skill"), "references/a.md": "a"}))
    package, source = fetch_package("https://github.com/o/r", gh)
    assert source["path"] == "" and source["commit"] == SHA and package.doc.name == "root-skill"
    assert [f.path for f in package.files] == ["README.md", "references/a.md"]  # the repository is the skill
    assert gh.urls[0].endswith("/commits/HEAD")


def test_a_branch_with_a_slash_is_found_by_trying_the_splits():
    gh = FakeGithub(refs={"feature/x": SHA}, archive=repo_zip({"skills/tdd/SKILL.md": skill()}))
    _, source = fetch_package("https://github.com/o/r/tree/feature/x/skills/tdd", gh)
    assert source["path"] == "skills/tdd"
    assert [u.rsplit("/", 1)[1] for u in gh.urls[:2]] == ["feature", "feature%2Fx"]


def test_a_sha_in_the_link_is_pinned_to_itself():
    gh = FakeGithub(refs={SHA: SHA}, archive=repo_zip({"tdd/SKILL.md": skill()}))
    assert fetch_package(f"https://github.com/o/r/tree/{SHA}/tdd", gh)[1]["commit"] == SHA


# ── Refusals ─────────────────────────────────────────────────────────────────


def refused(url, gh):
    with pytest.raises(ImportRefused) as e:
        fetch_package(url, gh)
    return e.value


def test_an_unknown_branch_or_repo_is_not_found():
    err = refused("https://github.com/o/r/tree/nope/x", FakeGithub(refs={}))
    assert err.status_code == 404 and "public" in str(err)
    assert refused("https://github.com/o/r", FakeGithub(commit_status=404)).status_code == 404


def test_a_rate_limit_says_so():
    err = refused("https://github.com/o/r", FakeGithub(commit_status=403, headers={"x-ratelimit-remaining": "0"}))
    assert err.status_code == 429 and "rate limit" in str(err)
    assert refused("https://github.com/o/r", FakeGithub(archive_status=429)).status_code == 429
    assert refused("https://github.com/o/r", FakeGithub(archive_status=403, headers={"X-RateLimit-Remaining": "0"})).status_code == 429


def test_a_github_error_is_a_bad_gateway():
    assert refused("https://github.com/o/r", FakeGithub(commit_status=500)).status_code == 502


def test_a_folder_without_a_skill_md_is_not_a_skill():
    err = refused("https://github.com/o/r/tree/main/docs", FakeGithub(archive=repo_zip({"docs/readme.md": "x", "docs/deep/SKILL.md": skill()})))
    assert err.status_code == 400 and "SKILL.md" in str(err)  # a skill deeper down is not the linked folder


def test_a_folder_that_is_not_in_the_archive_is_not_a_skill():
    assert "SKILL.md" in str(refused("https://github.com/o/r/tree/main/missing", FakeGithub(archive=repo_zip({"a/SKILL.md": skill()}))))


def test_a_repository_over_the_cap_is_too_big(monkeypatch):
    class Big(FakeGithub):
        def get(self, url, **kw):
            if "/zipball/" in url:
                raise ValueError("Response exceeds the size cap.")
            return super().get(url, **kw)

    err = refused("https://github.com/o/r", Big())
    assert err.status_code == 413 and "too large" in str(err)


def test_a_redirect_off_github_is_refused():
    class Off(FakeGithub):
        def get(self, url, **kw):
            if "/zipball/" in url:
                raise SsrfError("Refusing to call 'evil.example'")
            return super().get(url, **kw)

    assert refused("https://github.com/o/r", Off()).status_code == 400


def test_the_same_caps_and_traversal_checks_apply_to_the_folder(monkeypatch):
    base = {"x/SKILL.md": skill()}
    # a zip bomb: one file that unpacks past the per-file cap
    err = refused("https://github.com/o/r/tree/main/x", FakeGithub(archive=repo_zip({**base, "x/big.md": b"\0" * (importer.MEMBER_MAX + 1)})))
    assert err.status_code == 413
    # too many files inside the folder, but files elsewhere in the repository count for nothing
    monkeypatch.setattr(importer, "MEMBERS_MAX", 5)
    other = {f"y/{i}.md": "x" for i in range(20)}
    package, _ = fetch_package("https://github.com/o/r/tree/main/x", FakeGithub(archive=repo_zip({**base, **other})))
    assert package.files == []
    assert refused("https://github.com/o/r/tree/main/y", FakeGithub(archive=repo_zip({**base, **other}))).status_code == 413
    monkeypatch.setattr(importer, "MEMBERS_MAX", 500)
    # a traversal name inside the folder refuses the whole package
    evil = FakeGithub(archive=repo_zip({**base, "x/../../escape.md": "x"}))
    assert "unsafe" in str(refused("https://github.com/o/r/tree/main/x", evil))
    # a password-protected or non-zip answer is refused too
    assert refused("https://github.com/o/r", FakeGithub(archive=b"not a zip")).status_code == 400


def test_a_file_the_folder_has_too_many_of_is_refused(monkeypatch):
    monkeypatch.setattr(playbooks, "FILES_MAX", 2)
    monkeypatch.setattr(importer, "FILES_MAX", 2)
    files = {"x/SKILL.md": skill(), **{f"x/r{i}.md": "x" for i in range(3)}}
    assert refused("https://github.com/o/r/tree/main/x", FakeGithub(archive=repo_zip(files))).status_code == 413


def test_nothing_is_written_to_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fetch_package("https://github.com/o/r/tree/main/skills/engineering/tdd", FakeGithub(archive=repo_zip(TDD_FILES)))
    assert list(Path(tmp_path).iterdir()) == []


# ── The guarded client ───────────────────────────────────────────────────────


def test_the_default_client_is_the_guarded_one_narrowed_to_github(monkeypatch):
    made = {}

    class Spy(FakeGithub):
        def __init__(self, **kw):
            super().__init__(archive=repo_zip({"SKILL.md": skill()}))
            made.update(kw)

    monkeypatch.setattr(http_client, "MarvinHttpHelper", Spy)
    fetch_package("https://github.com/o/r")
    assert made["allowed_hosts"] == {"github.com", "api.github.com", "codeload.github.com"} and made["max_bytes"] == importer.ARCHIVE_MAX


def test_the_client_only_follows_redirects_to_github_hosts():
    helper = MarvinHttpHelper(max_bytes=10, allowed_hosts=github.ALLOWED_HOSTS)
    handler = next(h for h in helper._opener.handlers if isinstance(h, http_client._GuardedRedirectHandler))
    ok = http_client.urllib.request.Request("https://api.github.com/repos/o/r/zipball/x")
    handler.redirect_request(ok, None, 302, "Found", {}, "https://codeload.github.com/o/r/legacy.zip/x")
    for target in ("https://evil.example/x", "https://raw.githubusercontent.com/o/r/x", "http://127.0.0.1/x", "https://github.com.evil.example/x"):
        with pytest.raises(SsrfError):
            handler.redirect_request(ok, None, 302, "Found", {}, target)
    with pytest.raises(SsrfError):
        helper.get("https://evil.example/x")


# ── The route ────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_github(monkeypatch):
    gh = FakeGithub(
        archive=repo_zip({"skills/tdd/SKILL.md": skill(body="Read [t](tests.md). Never send the API key anywhere."), "skills/tdd/tests.md": "# t\n"})
    )
    monkeypatch.setattr(http_client, "MarvinHttpHelper", lambda **kw: gh)
    return gh


def post(workspace, url, role=WorkspaceRole.EDITOR, **extra):
    return gates._sign_in(workspace, role).post(IMPORT, json={"url": url, **extra})


def test_a_link_lands_as_a_draft_with_its_source_and_review(workspace, db_session, fake_github):
    res = post(workspace, "https://github.com/o/r/tree/main/skills/tdd")
    assert res.status_code == 201, res.text
    out = res.json()
    assert out["name"] == "tdd" and out["status"] == "draft" and out["fileCount"] == 1
    source = {"url": "https://github.com/o/r/tree/main/skills/tdd", "repo": "o/r", "path": "skills/tdd", "commit": SHA}
    assert out["review"]["source"]["kind"] == "github" and {k: out["review"]["source"][k] for k in source} == source
    assert out["review"]["warnings"]  # the same review as an upload
    entry = next(p for p in playbooks.all_playbooks(db_session, workspace.gid) if p.slug == "tdd")
    assert entry.status == "draft" and entry.metadata_json["source"] == source
    assert [f.path for f in playbooks.reference_files(db_session, entry.id)] == ["tests.md"]


def test_a_taken_name_is_refused_and_a_new_one_can_be_sent(workspace, fake_github):
    assert post(workspace, "https://github.com/o/r/tree/main/skills/tdd").status_code == 201
    assert post(workspace, "https://github.com/o/r/tree/main/skills/tdd").status_code == 409
    assert post(workspace, "https://github.com/o/r/tree/main/skills/tdd", name="tdd-2").status_code == 201


def test_route_errors_carry_the_message(workspace, fake_github):
    bad = post(workspace, "https://gitlab.com/o/r")
    assert bad.status_code == 400 and "github.com" in bad.json()["detail"]
    fake_github.refs = {}
    assert post(workspace, "https://github.com/o/r/tree/nope/x").status_code == 404


def test_a_viewer_cannot_import_from_github(workspace, fake_github):
    assert post(workspace, "https://github.com/o/r/tree/main/skills/tdd", role=WorkspaceRole.VIEWER).status_code == 403
    assert fake_github.urls == []
