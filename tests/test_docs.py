"""Marvin's manual for agents: services/docs.py (load, split, rank) and the search_docs / read_doc tools.

These run against the real docs/manual of this checkout — the same files the image ships — so a page
that stops parsing, or a search that stops finding its section, fails here.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from marvin.services import docs as docs_service
from marvin.services.ai.agents import DOCS_RULE, POLICY_ALLOW, SYSTEM_AGENTS, AgentSpec, resolve_policy, workspace_preamble
from marvin.services.ai.operations.base import ROLE_VIEWER
from marvin.services.ai.tools import get_tool
from marvin.services.ai.tools.categories import CATEGORY_BY_ID, category_of
from marvin.services.docs import (
    DOCS_UNAVAILABLE,
    INDEX_PAGE,
    LEAD_IN_LEVEL,
    MAX_SEARCH_LIMIT,
    DocsIndex,
    find_docs_dir,
    get_docs,
    load_docs,
    normalize_page_path,
    page_url,
    stem,
    toc_slug,
    unique_slug,
)

BASE = "https://docs.example/marvin/"
CTX = SimpleNamespace(session=None, group_id=None)  # docs tools never touch the workspace


@pytest.fixture(scope="module")
def manual() -> DocsIndex:
    root = find_docs_dir()
    assert root is not None, "docs/manual should be found in a source checkout"
    return load_docs(root)


def _top(manual: DocsIndex, query: str, n: int = 3) -> list[tuple[str, str]]:
    return [(s.page, s.heading) for s, _ in manual.rank(query, n)]


# ── loading and splitting ────────────────────────────────────────────────────


def test_every_manual_page_loads_with_a_title_and_sections(manual):
    on_disk = sorted(p.relative_to(find_docs_dir()).as_posix() for p in find_docs_dir().rglob("*.md"))
    assert sorted(manual.pages) == on_disk
    for page in manual.pages.values():
        assert page.title, page.path
        assert page.sections, page.path
        assert all(s.page == page.path and s.page_title == page.title for s in page.sections)


def test_section_anchors_match_what_mkdocs_generates(manual):
    """Every heading's anchor equals the id python-markdown's toc (MkDocs) gives it, so links land."""
    markdown = pytest.importorskip("markdown")
    pytest.importorskip("pymdownx")

    def ids(tokens):
        for t in tokens:
            yield t["id"]
            yield from ids(t["children"])

    for page in manual.pages.values():
        md = markdown.Markdown(extensions=["toc", "attr_list", "tables", "admonition", "md_in_html", "pymdownx.superfences"])
        md.convert(page.markdown)
        mine = [s.anchor for s in page.sections if s.level < LEAD_IN_LEVEL and s.anchor]
        assert mine == list(ids(md.toc_tokens)), page.path


def test_split_keeps_heading_paths_skips_code_fences_and_splits_run_in_titles():
    text = (
        "# Page\n\nIntro.\n\n## Usage\n\nBody.\n\n```bash\n# not a heading\n```\n\n"
        "**Activity toasts.** Toasts show events.\n\n**Preview matches** is a button label.\n\n### Usage\n\nAgain.\n"
    )
    title, sections = docs_service._split_sections("p.md", text)
    assert title == "Page"
    assert [(s.heading, s.anchor) for s in sections] == [
        ("Page", "page"),
        ("Usage", "usage"),
        ("Activity toasts", "usage"),  # a run-in title links to its heading's anchor
        ("Usage", "usage_1"),  # toc de-duplicates repeats
    ]
    assert sections[2].heading_path == ("Page", "Usage", "Activity toasts")
    assert "Preview matches" in sections[2].body  # a bold label mid-text is not a run-in title
    assert "# not a heading" in sections[1].body


def test_slug_and_stem_helpers():
    assert toc_slug("Forms & submission protection") == "forms-submission-protection"
    assert toc_slug("run_integration_action") == "run_integration_action"
    used: set[str] = set()
    assert [unique_slug("api", used) for _ in range(3)] == ["api", "api_1", "api_2"]
    assert {stem(w) for w in ("update", "updates", "updated", "updating")} == {"updat"}
    assert stem("toasts") == stem("toast") and stem("limits") == stem("limit")


def test_page_urls_follow_mkdocs_directory_urls():
    assert page_url(BASE, "whats-new/workflows.md", "run-on-a-query-of-entries") == BASE + "whats-new/workflows/#run-on-a-query-of-entries"
    assert page_url(BASE, INDEX_PAGE) == BASE
    assert page_url(BASE, "whats-new/index.md") == BASE + "whats-new/"


def test_page_refs_accept_paths_urls_and_anchors():
    assert normalize_page_path("whats-new/workflows") == ("whats-new/workflows.md", None)
    assert normalize_page_path("https://inneropen.github.io/marvin/whats-new/workflows/#step-kinds") == ("whats-new/workflows.md", "step-kinds")
    assert normalize_page_path("docs/manual/glossary.md#x") == ("glossary.md", "x")
    assert normalize_page_path("") == (INDEX_PAGE, None)


# ── search ───────────────────────────────────────────────────────────────────


def test_search_bulk_update_finds_run_on_a_query_of_entries(manual):
    assert _top(manual, "bulk update", 1) == [("whats-new/workflows.md", "Run on a query of entries")]


def test_search_toast_finds_activity_toasts(manual):
    assert _top(manual, "toast", 1) == [("index.md", "Activity toasts")]


def test_search_monthly_cost_limit_finds_ai_usage_limits(manual):
    assert _top(manual, "monthly cost limit", 1) == [("whats-new/agents-and-ask.md", "Usage and limits")]


def test_search_results_carry_snippet_anchor_and_published_url(manual):
    hit = manual.search("bulk update", 1, base_url=BASE)[0]
    assert hit["page"] == "whats-new/workflows.md" and hit["anchor"] == "run-on-a-query-of-entries"
    assert hit["url"] == BASE + "whats-new/workflows/#run-on-a-query-of-entries"
    assert hit["headingPath"] == ["Workflows", "What it does", "Run on a query of entries"]
    assert "bulk update" in hit["snippet"] and len(hit["snippet"].split()) <= docs_service.SNIPPET_WORDS + 2


def test_search_is_deterministic_and_ignores_stop_words(manual):
    assert manual.rank("how do I bulk update", 5) == manual.rank("bulk update", 5)
    assert manual.rank("how do I", 5) == []  # nothing but stop words


def test_search_limit_is_clamped(manual):
    assert len(manual.search("workflow", 999, base_url=BASE)) == MAX_SEARCH_LIMIT
    assert docs_service.clamp_limit("junk") == docs_service.DEFAULT_SEARCH_LIMIT
    assert docs_service.clamp_limit(0) == 1


# ── read ─────────────────────────────────────────────────────────────────────


def test_read_page_returns_a_section_by_anchor_with_its_subsections(manual):
    got = manual.read_page("whats-new/workflows.md", "run-on-a-query-of-entries", base_url=BASE)
    assert got["heading"] == "Run on a query of entries"
    assert got["markdown"].startswith("### Run on a query of entries")
    assert "### Step kinds" not in got["markdown"]  # stops at the next sibling heading
    assert got["url"] == BASE + "whats-new/workflows/#run-on-a-query-of-entries"

    parent = manual.read_page("whats-new/workflows.md", "What it does", base_url=BASE)  # by heading text
    assert "### Run on a query of entries" in parent["markdown"] and "## Where" not in parent["markdown"]


def test_read_page_whole_page_and_unknown_section(manual):
    whole = manual.read_page("whats-new/workflows", base_url=BASE)
    assert whole["markdown"].startswith("# Workflows") and whole["url"] == BASE + "whats-new/workflows/"
    assert {"heading": "Step kinds", "anchor": "step-kinds", "level": 3} in whole["sections"]
    missing = manual.read_page("whats-new/workflows.md", "no-such-section", base_url=BASE)
    assert "error" in missing and missing["sections"]
    assert manual.read_page("nope.md") is None


# ── missing docs ─────────────────────────────────────────────────────────────


def test_missing_docs_dir_gives_an_empty_unavailable_index(tmp_path: Path):
    empty = load_docs(tmp_path / "absent")
    assert empty.available is False
    assert empty.rank("anything") == [] and empty.list_pages() == []
    assert load_docs(None).available is False


def test_docs_tools_report_unavailable_instead_of_failing(monkeypatch):
    monkeypatch.setattr(docs_service, "find_docs_dir", lambda: None)
    for name, args in (("search_docs", {"query": "toast"}), ("read_doc", {"path": "index.md"})):
        out = json.loads(get_tool(name).handler(CTX, args))
        assert out == {"available": False, "error": DOCS_UNAVAILABLE}


# ── tools, category, binding, preamble ───────────────────────────────────────


def test_search_docs_tool_returns_ranked_hits_with_links():
    out = json.loads(get_tool("search_docs").handler(CTX, {"query": "toast", "limit": 2}))
    assert len(out["results"]) == 2
    assert out["results"][0]["heading"] == "Activity toasts"
    assert out["results"][0]["url"].startswith(docs_service.docs_base_url().rstrip("/"))
    assert json.loads(get_tool("search_docs").handler(CTX, {"query": "  "})) == {"error": "query is required"}


def test_read_doc_tool_reads_a_section_and_lists_pages_for_an_unknown_path():
    got = json.loads(get_tool("read_doc").handler(CTX, {"path": "whats-new/agents-and-ask.md", "section": "usage-and-limits"}))
    assert got["heading"] == "Usage and limits" and "Monthly cost limit" in got["markdown"]
    missing = json.loads(get_tool("read_doc").handler(CTX, {"path": "no/such/page"}))
    assert "error" in missing and {"path": INDEX_PAGE, "title": get_docs().pages[INDEX_PAGE].title} in missing["pages"]


@pytest.mark.parametrize("name", ["search_docs", "read_doc"])
def test_docs_tools_are_read_only_docs_read_and_reachable_from_agents_and_mcp(name):
    spec = get_tool(name)
    assert spec.read_only is True and spec.min_role == ROLE_VIEWER
    assert {"agent", "mcp"} <= set(spec.sources)  # bound in-process and projected to MarvinMCP
    assert category_of(name, read_only=True) == "docs_read"
    assert CATEGORY_BY_ID["docs_read"].writes is False
    assert CATEGORY_BY_ID["docs_read"].label == "Read Marvin's documentation"


@pytest.mark.parametrize("name", ["search_docs", "read_doc"])
def test_docs_tools_are_allowed_for_read_only_agents_and_ask(name):
    read_only_agent = AgentSpec(slug="w", name="W")  # no allow_writes
    assert resolve_policy(read_only_agent, name, "docs_read", ROLE_VIEWER)[0] == POLICY_ALLOW
    assert resolve_policy(SYSTEM_AGENTS["ask"], name, "docs_read", ROLE_VIEWER)[0] == POLICY_ALLOW


def test_preamble_has_the_docs_rule_only_when_docs_are_bound():
    assert DOCS_RULE in workspace_preamble("W", ["search_docs", "read_doc"])
    assert DOCS_RULE not in workspace_preamble("W", ["search_content"])
    assert "search_docs" in DOCS_RULE and "cite" in DOCS_RULE
