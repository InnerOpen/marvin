"""Marvin's user manual (`docs/manual`), readable and searchable by agents at run time.

The manual is the single source of what Marvin knows about itself. It is served from the files
bundled with the running version (the image copies `docs/manual` beside the venv; a source checkout
has it at the repo root), so an answer always matches what is deployed rather than whatever the
published site says today.

Each page is split into sections by heading. A section keeps its page, its heading path and the
anchor MkDocs gives that heading (python-markdown's `toc` slugify, de-duplicated the same way), so a
hit links straight to the published page: DOCS_BASE_URL + page + `#anchor`.

Search is keyword ranking, deterministic and free: BM25 over each section's own text, with boosts for
a match in the section heading or the page title, a bonus when the words appear together as a phrase,
stop words dropped, light suffix stemming, and prefix matching so "month" also finds "monthly".

The manual only changes with a new image, so it is parsed once per process. Missing docs are not an
error: the index is simply empty and `available` is False.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import marvin
from marvin.core.config import get_app_settings
from marvin.core.root_logger import get_logger
from marvin.core.settings.static import BASE_DIR

logger = get_logger(__name__)

MANUAL_DIR = Path("docs") / "manual"
PAGE_SUFFIX = ".md"
INDEX_PAGE = "index.md"

DOCS_UNAVAILABLE = "Marvin's documentation is not available on this server (the manual is not bundled with this install)."

DEFAULT_SEARCH_LIMIT = 5
MAX_SEARCH_LIMIT = 20

# BM25 constants (the usual defaults): term-frequency saturation and length normalisation.
BM25_K1 = 1.2
BM25_B = 0.75
# A query word in the section heading says far more than one more mention in the body; in the page
# title it says the whole page is about it.
HEADING_BOOST = 2.0
TITLE_BOOST = 1.0
# Added (times the query's summed idf) when the query's words appear consecutively in the section.
PHRASE_BONUS = 0.5
# How hard a section is penalised for missing query words: score × (share of the query's idf it covers)^n.
COVERAGE_POWER = 2
# A prefix match ("month" → "monthly") counts for this much of an exact match.
PREFIX_WEIGHT = 0.5
# Shorter stems would prefix-match too much ("set" → "settings", "setup", "sets").
MIN_PREFIX_LEN = 4
SNIPPET_WORDS = 40
# Run-in titled paragraphs sit below every real heading (h1–h6), so a heading's section text still
# includes them and theirs ends at the next section of any kind.
LEAD_IN_LEVEL = 7

STOP_WORDS = frozenset(
    """
    a about above after again all also am an and any are as at be because been being below between both but by can
    could did do does doing done down during each else ever every few for from further get gets got had has have
    having he her here hers him his how i if in into is it its itself just let me more most my no nor not now of off
    on once only or other our ours out over own please same she should so some such than that the their theirs them
    then there these they this those through to too under until up us very via want was we were what when where
    which while who whom why will with would you your yours
    """.split()
)

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
# attr_list's explicit id: `## Heading {#custom-id}` or `{: #custom-id .class }`.
_ATTR_ID_RE = re.compile(r"\s*\{:?\s*[^}]*#([\w-]+)[^}]*\}\s*$")
_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_TAG_RE = re.compile(r"<[^>]+>")
_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|`)")
# A paragraph's bold run-in title, e.g. `**Activity toasts.** While the tab is visible…`.
_LEAD_IN_RE = re.compile(r"^\*\*([^*]+)\*\*")
_TOC_ID_COUNT_RE = re.compile(r"^(.*)_([0-9]+)$")
_WORD_RE = re.compile(r"[a-z0-9]+")
_URL_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


# ── text helpers ─────────────────────────────────────────────────────────────


def plain_text(markdown: str) -> str:
    """Markdown as readable text: links keep their label, emphasis/code marks and HTML tags go."""
    text = _LINK_RE.sub(r"\1", markdown)
    text = _TAG_RE.sub("", text)
    return _EMPHASIS_RE.sub("", text)


def toc_slug(heading_text: str) -> str:
    """The anchor python-markdown's `toc` extension (MkDocs' default) gives a heading's text."""
    value = unicodedata.normalize("NFKD", heading_text).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "-", value)


def unique_slug(slug: str, used: set[str]) -> str:
    """De-duplicate an anchor the way `toc` does: a repeat gets `_1`, `_2`, …"""
    while slug in used or not slug:
        m = _TOC_ID_COUNT_RE.match(slug)
        slug = f"{m.group(1)}_{int(m.group(2)) + 1}" if m else f"{slug}_1"
    used.add(slug)
    return slug


def stem(word: str) -> str:
    """Light suffix stripping so update/updates/updated/updating and limit/limits meet."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 4 and word.endswith("ed"):
        word = word[:-2]
    elif len(word) > 3 and word.endswith("es") and word[-3] in "sxz":
        word = word[:-2]
    elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if len(word) > 4 and word.endswith("e"):
        word = word[:-1]
    return word


def terms(text: str) -> list[str]:
    """Stemmed index terms of `text`, stop words dropped."""
    return [stem(w) for w in _WORD_RE.findall(text.lower()) if w not in STOP_WORDS]


# ── model ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DocSection:
    page: str  # "whats-new/workflows.md"
    page_title: str
    heading: str  # plain heading text
    heading_path: tuple[str, ...]  # ("Workflows", "What it does", "Run on a query of entries")
    anchor: str
    level: int
    start: int  # line index of the heading in the page (0 for a page with no leading heading)
    body: str  # this section's own markdown, up to the next heading or run-in title
    # Search data, derived from the text above.
    body_terms: tuple[str, ...] = field(repr=False)
    term_counts: Counter = field(repr=False, compare=False)
    heading_terms: frozenset[str] = field(repr=False)
    title_terms: frozenset[str] = field(repr=False)


@dataclass(frozen=True)
class DocPage:
    path: str
    title: str
    markdown: str
    sections: tuple[DocSection, ...]

    def section(self, ref: str) -> DocSection | None:
        """A section by anchor (`run-on-a-query-of-entries`, `#…`) or by heading text, case-insensitively."""
        key = (ref or "").strip().lstrip("#").strip()
        if not key:
            return None
        slug, lowered = toc_slug(key), key.lower()
        for matches in (
            lambda s: s.anchor == key,
            lambda s: s.anchor == slug,
            lambda s: s.heading.lower() == lowered,
        ):
            # The first section with an anchor is its heading; run-in titles below it share the anchor.
            found = next((s for s in self.sections if matches(s)), None)
            if found:
                return found
        return None

    def section_markdown(self, section: DocSection) -> str:
        """The section with its subsections: from its heading to the next heading at its level or above."""
        lines = self.markdown.splitlines()
        end = len(lines)
        for later in self.sections:
            if later.start > section.start and later.level <= section.level:
                end = later.start
                break
        return "\n".join(lines[section.start : end]).strip()


def _split_sections(page_path: str, markdown: str) -> tuple[str, list[DocSection]]:
    """The page title (first H1, else the file name) and its sections, one per heading."""
    lines = markdown.splitlines()
    headings: list[tuple[int, int, str, str | None]] = []  # (line, level, text, explicit id)
    in_fence = False
    for i, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        m = None if in_fence else _HEADING_RE.match(line)
        if m:
            raw = m.group(2)
            attr = _ATTR_ID_RE.search(raw)
            explicit = attr.group(1) if attr else None
            text = plain_text(_ATTR_ID_RE.sub("", raw)).strip()
            headings.append((i, len(m.group(1)), text, explicit))

    title = next((text for _, level, text, _ in headings if level == 1), None)
    title = title or Path(page_path).stem.replace("-", " ").capitalize()

    used: set[str] = set()
    sections: list[DocSection] = []
    stack: list[tuple[int, str]] = []  # (level, heading) of the enclosing headings
    if not headings or headings[0][0] > 0:
        # Text before the first heading belongs to the page itself (anchor-less, like a page top).
        first = headings[0][0] if headings else len(lines)
        sections += _with_lead_ins(page_path, title, lines, 0, first, title, (title,), "", 1)
    for n, (line, level, text, explicit) in enumerate(headings):
        end = headings[n + 1][0] if n + 1 < len(headings) else len(lines)
        anchor = unique_slug(explicit or toc_slug(text), used)
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, text))
        sections += _with_lead_ins(page_path, title, lines, line, end, text, tuple(h for _, h in stack), anchor, level)
    return title, sections


def _lead_in(lines: list[str], i: int) -> str | None:
    """The run-in title of a paragraph opening at line `i` with one (`**Activity toasts.** …`), else None."""
    if i > 0 and lines[i - 1].strip():
        return None  # not the start of a paragraph
    m = _LEAD_IN_RE.match(lines[i])
    if not m:
        return None
    label, rest = m.group(1).strip(), lines[i][m.end() :].strip()
    # `**Preview matches** shows …` is a UI label in a sentence, not a title: a run-in title ends with a
    # period inside the bold, or stands alone on its line.
    if label.endswith(".") or not rest:
        return label.rstrip(".").strip()
    return None


def _with_lead_ins(
    page: str, title: str, lines: list[str], start: int, end: int, heading: str, path: tuple[str, ...], anchor: str, level: int
) -> list[DocSection]:
    """One heading's section, then a section per run-in titled paragraph inside it.

    The manual uses bold run-in titles as minor headings inside long sections ("**Activity toasts.**"),
    so each is searchable on its own with its title boosted like a heading. MkDocs gives them no
    anchor, so they link to the enclosing heading's.
    """
    starts: list[tuple[int, str]] = []
    in_fence = False
    for i in range(start + 1, end):
        if _FENCE_RE.match(lines[i]):
            in_fence = not in_fence
        elif not in_fence and (label := _lead_in(lines, i)):
            starts.append((i, label))
    own_end = starts[0][0] if starts else end
    out = [_section(page, title, heading, path, anchor, level, start, "\n".join(lines[start:own_end]))]
    for n, (i, label) in enumerate(starts):
        stop = starts[n + 1][0] if n + 1 < len(starts) else end
        out.append(_section(page, title, label, (*path, label), anchor, LEAD_IN_LEVEL, i, "\n".join(lines[i:stop])))
    return out


def _section(page: str, title: str, heading: str, path: tuple[str, ...], anchor: str, level: int, start: int, body: str) -> DocSection:
    body_terms = tuple(terms(plain_text(body)))
    return DocSection(
        page=page,
        page_title=title,
        heading=heading,
        heading_path=path,
        anchor=anchor,
        level=level,
        start=start,
        body=body.strip(),
        body_terms=body_terms,
        term_counts=Counter(body_terms),
        heading_terms=frozenset(terms(heading)),
        title_terms=frozenset(terms(title)),
    )


# ── the index ────────────────────────────────────────────────────────────────


def normalize_page_path(ref: str) -> tuple[str, str | None]:
    """`(page path, section)` from what an agent may pass: a page path with or without `.md`, a
    published URL (`…/marvin/whats-new/workflows/#run-on-a-query-of-entries`) or `page.md#anchor`."""
    ref = (ref or "").strip()
    section = None
    if "#" in ref:
        ref, section = ref.split("#", 1)
        section = section or None
    if _URL_RE.match(ref):  # a published link: keep the path below the site's base path
        base_path = urlparse(docs_base_url()).path.rstrip("/")
        ref = urlparse(ref).path
        ref = ref[len(base_path) :] if base_path and ref.startswith(base_path + "/") else ref
    ref = ref.strip("/")
    if ref.startswith(str(MANUAL_DIR) + "/"):
        ref = ref[len(str(MANUAL_DIR)) + 1 :]
    if not ref:
        return INDEX_PAGE, section
    if not ref.endswith(PAGE_SUFFIX):
        ref += PAGE_SUFFIX  # `whats-new` may also mean whats-new/index.md: DocsIndex.page tries both
    return ref, section


class DocsIndex:
    """The parsed manual: pages by path, every section, and the search over them."""

    def __init__(self, pages: dict[str, DocPage]):
        self.pages = pages
        self.sections: list[DocSection] = [s for p in pages.values() for s in p.sections]
        self._vocabulary = sorted({t for s in self.sections for t in (*s.body_terms, *s.heading_terms)})
        lengths = [len(s.body_terms) for s in self.sections]
        self._avg_len = (sum(lengths) / len(lengths)) if lengths else 0.0

    @property
    def available(self) -> bool:
        return bool(self.pages)

    def page(self, ref: str) -> DocPage | None:
        path, _ = normalize_page_path(ref)
        if path in self.pages:
            return self.pages[path]
        # `whats-new/workflows/` style refs to a directory page, or `whats-new` → whats-new/index.md
        alt = path[: -len(PAGE_SUFFIX)] + "/" + INDEX_PAGE
        return self.pages.get(alt)

    # ── search ──

    def _matches(self, term: str) -> tuple[str, ...]:
        """Index terms a query term matches: itself, plus longer terms it prefixes."""
        if len(term) < MIN_PREFIX_LEN:
            return (term,)
        return (term, *(v for v in self._vocabulary if v != term and v.startswith(term)))

    def _idf(self, matched: tuple[str, ...]) -> float:
        n = len(self.sections)
        df = sum(1 for s in self.sections if any(m in s.term_counts or m in s.heading_terms for m in matched))
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def _score(self, section: DocSection, expanded: list[tuple[str, tuple[str, ...], float]], query_terms: list[str]) -> float:
        score = covered = 0.0
        length_norm = 1 - BM25_B + BM25_B * (len(section.body_terms) / self._avg_len if self._avg_len else 1)
        for term, matched, idf in expanded:
            tf = section.term_counts.get(term, 0) + PREFIX_WEIGHT * sum(section.term_counts.get(m, 0) for m in matched[1:])
            in_heading = any(m in section.heading_terms for m in matched)
            if tf:
                score += idf * (tf * (BM25_K1 + 1)) / (tf + BM25_K1 * length_norm)
            if in_heading:
                score += idf * HEADING_BOOST
            if any(m in section.title_terms for m in matched):
                score += idf * TITLE_BOOST
            if tf or in_heading:
                covered += idf
        if not score:
            return 0.0
        total_idf = sum(idf for _, _, idf in expanded)
        if len(query_terms) > 1 and _has_phrase(section.body_terms, query_terms):
            score += PHRASE_BONUS * total_idf
        # A section that has every query word beats one that only has the common word many times.
        return score * (covered / total_idf) ** COVERAGE_POWER if total_idf else score

    def rank(self, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[tuple[DocSection, float]]:
        """Sections ranked best first (score > 0 only), ties broken by page path then position."""
        query_terms = list(dict.fromkeys(terms(query)))
        if not query_terms or not self.sections:
            return []
        expanded = []
        for t in query_terms:
            matched = self._matches(t)
            expanded.append((t, matched, self._idf(matched)))
        scored = [(s, self._score(s, expanded, query_terms)) for s in self.sections]
        ranked = sorted((x for x in scored if x[1] > 0), key=lambda x: (-x[1], x[0].page, x[0].start))
        return ranked[: clamp_limit(limit)]

    # ── the public surface (what the agent tools and the API return) ──

    def list_pages(self) -> list[dict]:
        """Every page as `{path, title}`, the home page first."""
        paths = sorted(self.pages, key=lambda p: (p != INDEX_PAGE, p))
        return [{"path": p, "title": self.pages[p].title} for p in paths]

    def search(self, query: str, limit: int = DEFAULT_SEARCH_LIMIT, *, base_url: str | None = None) -> list[dict]:
        """Ranked sections, each with its page, heading, anchor, a snippet and the published link."""
        base = base_url or docs_base_url()
        return [
            {
                "page": s.page,
                "pageTitle": s.page_title,
                "heading": s.heading,
                "headingPath": list(s.heading_path),
                "anchor": s.anchor or None,
                "url": section_url(base, s),
                "snippet": snippet(s, query),
                "score": round(score, 2),
            }
            for s, score in self.rank(query, limit)
        ]

    def read_page(self, ref: str, section: str | None = None, *, base_url: str | None = None) -> dict | None:
        """A page's markdown, or one section of it (with its subsections); None if there is no such page.

        `ref` may carry the section itself (`page.md#anchor`, a published URL). An unknown section
        returns an `error` plus the page's outline, so the caller can pick a real one.
        """
        base = base_url or docs_base_url()
        page = self.page(ref)
        if page is None:
            return None
        section = section or normalize_page_path(ref)[1]
        outline = [{"heading": s.heading, "anchor": s.anchor, "level": s.level} for s in page.sections if s.level < LEAD_IN_LEVEL]
        if not section:
            return {"page": page.path, "title": page.title, "url": page_url(base, page.path), "markdown": page.markdown, "sections": outline}
        found = page.section(section)
        if found is None:
            return {"page": page.path, "title": page.title, "error": f"No section '{section}' on {page.path}.", "sections": outline}
        return {
            "page": page.path,
            "title": page.title,
            "heading": found.heading,
            "headingPath": list(found.heading_path),
            "anchor": found.anchor or None,
            "url": section_url(base, found),
            "markdown": page.section_markdown(found),
        }


def clamp_limit(limit: object) -> int:
    """A search limit from untrusted input: an int in [1, MAX_SEARCH_LIMIT], the default otherwise."""
    try:
        n = int(limit)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return DEFAULT_SEARCH_LIMIT
    return max(1, min(n, MAX_SEARCH_LIMIT))


def _has_phrase(body_terms: tuple[str, ...], phrase: list[str]) -> bool:
    n = len(phrase)
    return any(list(body_terms[i : i + n]) == phrase for i in range(len(body_terms) - n + 1))


def snippet(section: DocSection, query: str, words: int = SNIPPET_WORDS) -> str:
    """A short plain-text window of the section: the one holding the most distinct query words, then
    the most mentions, earliest on a tie."""
    text = " ".join(plain_text(section.body).split())
    # Drop the heading itself: the result already carries it.
    head = text.lstrip("#").strip()
    if head.startswith(section.heading):
        text = head[len(section.heading) :].lstrip(".: ")
    tokens = text.split(" ")
    wanted = set(terms(query))
    best_start = 0
    if len(tokens) > words and wanted:
        found = [_query_terms_in(token, wanted) for token in tokens]

        def rank(start: int) -> tuple[int, int]:
            window = found[start : start + words]
            return len(set().union(*window)), sum(1 for f in window if f)

        best_start = max(range(len(tokens) - words + 1), key=lambda i: (rank(i), -i))
    out = " ".join(tokens[best_start : best_start + words])
    return ("… " if best_start > 0 else "") + out + (" …" if best_start + words < len(tokens) else "")


def _query_terms_in(token: str, wanted: set[str]) -> set[str]:
    stems = [stem(w) for w in _WORD_RE.findall(token.lower())]
    return {q for q in wanted for st in stems if st == q or (len(q) >= MIN_PREFIX_LEN and st.startswith(q))}


# ── loading ──────────────────────────────────────────────────────────────────


def find_docs_dir() -> Path | None:
    """The manual beside this install: the image's /app (BASE_DIR) or a source checkout's root.

    Same two places services/changelog.py looks for CHANGELOG.md.
    """
    candidates = (BASE_DIR / MANUAL_DIR, Path(marvin.__file__).resolve().parents[2] / MANUAL_DIR)
    return next((p for p in candidates if p.is_dir()), None)


@lru_cache(maxsize=4)
def load_docs(root: Path | None) -> DocsIndex:
    """The manual under `root`, parsed once per process; empty when the directory is missing."""
    if root is None or not root.is_dir():
        logger.info("Marvin's manual was not found; docs tools will report it unavailable.")
        return DocsIndex({})
    pages: dict[str, DocPage] = {}
    for file in sorted(root.rglob(f"*{PAGE_SUFFIX}")):
        rel = file.relative_to(root).as_posix()
        try:
            markdown = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning(f"Could not read manual page {rel}: {exc}")
            continue
        title, sections = _split_sections(rel, markdown)
        pages[rel] = DocPage(path=rel, title=title, markdown=markdown, sections=tuple(sections))
    return DocsIndex(pages)


def get_docs() -> DocsIndex:
    return load_docs(find_docs_dir())


# ── published links ──────────────────────────────────────────────────────────


def docs_base_url() -> str:
    return get_app_settings().DOCS_BASE_URL


def section_url(base_url: str, section: DocSection) -> str:
    """A section's published link. A page's top (its h1, or text before any heading) needs no anchor."""
    return page_url(base_url, section.page, None if section.level == 1 else section.anchor)


def page_url(base_url: str, page: str, anchor: str | None = None) -> str:
    """The published MkDocs URL (use_directory_urls): `a/b.md` → `a/b/`, `a/index.md` → `a/`."""
    stem_path = page[: -len(PAGE_SUFFIX)] if page.endswith(PAGE_SUFFIX) else page
    if stem_path == "index" or stem_path.endswith("/index"):
        stem_path = stem_path[: -len("index")]
    else:
        stem_path += "/"
    url = base_url.rstrip("/") + "/" + stem_path.lstrip("/")
    return f"{url}#{anchor}" if anchor else url
