"""Playbooks 08: the SKILL.md codec (services/playbooks/skill_md.py).

One module reads and writes the Agent Skills file format. Lenient on frontmatter keys it doesn't know (kept, so an
export can put them back), strict on the two the standard requires: name and description.
"""

from pathlib import Path

import pytest

from marvin.services.playbooks.skill_md import SkillFormatError, parse_skill_md, render_skill_md, split_tools

FIXTURES = Path(__file__).parent / "fixtures" / "skills"


def _fixture(name: str) -> str:
    return (FIXTURES / name / "SKILL.md").read_text(encoding="utf-8")


# ── Valid files ──────────────────────────────────────────────────────────────


def test_a_minimal_file_parses():
    doc = parse_skill_md("---\nname: release-notes\ndescription: Write release notes. Use at ship time.\n---\n\n# Steps\n\n1. Do it.\n")
    assert doc.name == "release-notes"
    assert doc.description == "Write release notes. Use at ship time."
    assert doc.body == "# Steps\n\n1. Do it.\n"
    assert doc.manual_only is False
    assert doc.allowed_tools == ""
    assert doc.extra == {}


def test_real_skills_parse():
    tdd = parse_skill_md(_fixture("tdd"))
    assert tdd.name == "tdd"
    assert tdd.description.startswith("Test-driven development.")
    assert tdd.body.startswith("# Test-Driven Development")
    assert "see [tests.md](tests.md)" in tdd.body.lower()


def test_disable_model_invocation_means_manual_only():
    assert parse_skill_md(_fixture("ask-matt")).manual_only is True
    assert parse_skill_md("---\nname: a\ndescription: d\ndisable-model-invocation: false\n---\nx").manual_only is False
    assert parse_skill_md("---\nname: a\ndescription: d\ndisable-model-invocation: 'true'\n---\nx").manual_only is True


def test_allowed_tools_become_a_space_separated_string():
    doc = parse_skill_md("---\nname: a\ndescription: d\nallowed-tools: find_entries get_entry\n---\nx")
    assert doc.allowed_tools == "find_entries get_entry"
    # A YAML list, or commas, as other tools write it, normalise to the same string; parentheses stay whole.
    assert parse_skill_md("---\nname: a\ndescription: d\nallowed-tools: [Read, Grep]\n---\nx").allowed_tools == "Read Grep"
    assert parse_skill_md("---\nname: a\ndescription: d\nallowed-tools: Bash(git add:*), Read\n---\nx").allowed_tools == "Bash(git add:*) Read"


def test_split_tools():
    assert split_tools("a  b\tc") == ["a", "b", "c"]
    assert split_tools("Bash(git diff:*) Read") == ["Bash(git diff:*)", "Read"]
    assert split_tools("") == []


# ── Lenient on the rest ──────────────────────────────────────────────────────


def test_unknown_keys_are_kept_with_their_values():
    doc = parse_skill_md(_fixture("pr"))
    assert doc.name == "pr"
    assert doc.extra["metadata"]["credits"]["skill"] == "show-me"
    doc = parse_skill_md("---\nname: a\ndescription: d\nversion: 3\nargument-hint: '[topic]'\n---\nx")
    assert doc.extra == {"version": 3, "argument-hint": "[topic]"}


def test_license_and_compatibility_are_read():
    doc = parse_skill_md("---\nname: a\ndescription: d\nlicense: MIT\ncompatibility: Needs the web tool.\n---\nx")
    assert (doc.license, doc.compatibility) == ("MIT", "Needs the web tool.")


def test_a_description_with_a_colon_still_parses():
    # Unquoted, this is invalid YAML (a second colon on the line); real skills do it all the time.
    doc = parse_skill_md("---\nname: a\ndescription: Use when asked: anything about tone\n---\nx")
    assert doc.description == "Use when asked: anything about tone"


def test_crlf_and_a_byte_order_mark_are_fine():
    doc = parse_skill_md("﻿---\r\nname: a\r\ndescription: d\r\n---\r\nline one\r\nline two\r\n")
    assert doc.name == "a"
    assert doc.body == "line one\nline two\n"


def test_a_body_may_be_empty():
    assert parse_skill_md("---\nname: a\ndescription: d\n---\n").body == ""


# ── Strict on name and description ───────────────────────────────────────────


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("# just markdown", "frontmatter"),
        ("---\nname: a\ndescription: d\n", "closing"),
        ("---\ndescription: d\n---\nx", "name"),
        ("---\nname: a\n---\nx", "description"),
        ("---\nname: ''\ndescription: d\n---\nx", "name"),
        ("---\nname: Release Notes\ndescription: d\n---\nx", "lowercase"),
        ("---\nname: -bad-\ndescription: d\n---\nx", "lowercase"),
        ("---\nname: bad--name\ndescription: d\n---\nx", "lowercase"),
        (f"---\nname: {'a' * 65}\ndescription: d\n---\nx", "64"),
        (f"---\nname: a\ndescription: {'d' * 1025}\n---\nx", "1024"),
        (f"---\nname: a\ndescription: d\ncompatibility: {'c' * 501}\n---\nx", "500"),
        ("---\nname: [a]\ndescription: d\n---\nx", "name"),
        ("---\n- a\n- b\n---\nx", "frontmatter"),
    ],
)
def test_invalid_files_are_refused_with_a_reason(text, fragment):
    with pytest.raises(SkillFormatError) as err:
        parse_skill_md(text)
    assert fragment in str(err.value)


# ── Writing, ready for a round trip ──────────────────────────────────────────


def test_a_written_file_parses_back_to_the_same_document():
    for fixture in ("tdd", "pr", "ask-matt"):
        first = parse_skill_md(_fixture(fixture))
        again = parse_skill_md(render_skill_md(first))
        assert again == first, fixture


def test_writing_uses_the_standard_key_names_in_a_stable_order():
    doc = parse_skill_md("---\nname: a\ndescription: d\nallowed-tools: x y\ndisable-model-invocation: true\nlicense: MIT\nowner: me\n---\nBody\n")
    out = render_skill_md(doc)
    head = out.split("---\n")[1]
    assert head.splitlines() == [
        "name: a",
        "description: d",
        "license: MIT",
        "allowed-tools: x y",
        "disable-model-invocation: true",
        "owner: me",
        "metadata:",
        "  marvin-manual-only: 'true'",
    ]
    assert out.endswith("---\n\nBody\n")


def test_optional_keys_are_left_out_when_empty():
    out = render_skill_md(parse_skill_md("---\nname: a\ndescription: d\n---\nB"))
    assert out == "---\nname: a\ndescription: d\n---\n\nB\n"


def test_a_tricky_description_survives_writing():
    doc = parse_skill_md("---\nname: a\ndescription: \"Say 'hi': then # stop\"\n---\nx")
    assert parse_skill_md(render_skill_md(doc)).description == "Say 'hi': then # stop"


def test_an_entry_converts_to_a_document_and_back():
    from marvin.services.playbooks.skill_md import SkillDoc

    data = {"name": "a", "description": "d", "body": "B\n", "license": "MIT", "compatibility": "", "allowed_tools": "x y", "manual_only": True}
    doc = SkillDoc.from_entry_data(data, extra={"owner": "me"})
    assert doc.manual_only and doc.extra == {"owner": "me"}
    assert doc.to_entry_data() == {**data, "compatibility": ""}


# ── Playbooks 10: Marvin-only settings live under `metadata` (string keys prefixed "marvin-") ───────────────────────


def test_marvin_settings_are_written_under_metadata_as_strings():
    import yaml

    from marvin.services.playbooks.skill_md import SkillDoc

    text = render_skill_md(SkillDoc(name="a", description="d", manual_only=True))
    front = yaml.safe_load(text.split("---")[1])
    assert front["metadata"] == {"marvin-manual-only": "true"}  # the standard's metadata is a string-to-string map
    assert front["disable-model-invocation"] is True  # Claude Code's own key still says it


def test_no_marvin_section_when_there_are_no_marvin_settings():
    from marvin.services.playbooks.skill_md import SkillDoc

    assert "metadata" not in render_skill_md(SkillDoc(name="a", description="d"))


def test_marvin_settings_are_read_back_and_kept_out_of_extra():
    doc = parse_skill_md("---\nname: a\ndescription: d\nmetadata:\n  marvin-manual-only: 'true'\n  author: me\n---\nB")
    assert doc.manual_only is True
    assert doc.extra == {"metadata": {"author": "me"}}  # another tool's metadata is kept, Marvin's is a field


def test_a_marvin_only_flag_alone_sets_manual_only_and_leaves_no_extra():
    doc = parse_skill_md("---\nname: a\ndescription: d\nmetadata:\n  marvin-manual-only: 'true'\n---\nB")
    assert doc.manual_only and doc.extra == {}


def test_other_tools_metadata_survives_next_to_the_marvin_section():
    from marvin.services.playbooks.skill_md import SkillDoc

    doc = SkillDoc(name="a", description="d", manual_only=True, extra={"metadata": {"author": "me"}})
    assert parse_skill_md(render_skill_md(doc)) == doc
