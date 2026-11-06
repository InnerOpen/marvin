"""A revise stages only what it changes.

The model re-emits the full field set (unchanged ones as-is) and always returns tags and resources, and the review wall
shows a Current/Suggested pair per staged key. Staging all of it buried a one-field edit (e.g. a place name) under
identical rows on every other field.
"""

from types import SimpleNamespace

from marvin.services.ai.authoring import changed_only


def _entry(**over):
    base = {
        "title": "Between Lives",
        "summary": "A quiet sea.",
        "data_json": {"medium": "Acrylic on canvas", "price": "$1,170", "status": "sold", "soldNear": "", "size": "20 x 20 in"},
        "tag_names": ["sea"],
        "tags": [SimpleNamespace(slug="sea")],
        "resources": [SimpleNamespace(id="11111111-1111-1111-1111-111111111111", slug="waxed-canvas", name="Waxed Canvas")],
    }
    return SimpleNamespace(**{**base, **over})


def _revise(entry, **over):
    args = {
        "title": entry.title,
        "summary": entry.summary,
        "fields": dict(entry.data_json),
        "tags": list(entry.tag_names),
        "resources": ["Waxed Canvas"],
    }
    return changed_only(entry, **{**args, **over})


def test_one_changed_field_among_many_stages_only_that_field():
    entry = _entry()
    fields = {**entry.data_json, "soldNear": "Asheville, NC"}
    proposed, tags, resources = _revise(entry, fields=fields)
    assert proposed == {"data_json.soldNear": "Asheville, NC"}
    assert tags == [] and resources == []


def test_nothing_changed_stages_nothing():
    proposed, tags, resources = _revise(_entry())
    assert proposed == {} and tags == [] and resources == []


def test_whitespace_and_empty_reemission_are_not_changes():
    entry = _entry()
    fields = {**entry.data_json, "medium": "Acrylic on canvas ", "soldNear": None, "series": ""}
    proposed, _, _ = _revise(entry, title=" Between Lives", summary="A quiet sea. ", fields=fields)
    assert proposed == {}


def test_title_and_summary_staged_when_they_change():
    proposed, _, _ = _revise(_entry(), title="Between Lives II", summary="A quiet, grey sea.")
    assert proposed == {"title": "Between Lives II", "summary": "A quiet, grey sea."}


def test_only_new_tags_and_resources_are_staged():
    entry = _entry()
    proposed, tags, resources = _revise(entry, tags=["Sea", "coast", "coast"], resources=["waxed-canvas", "Linen"])
    assert tags == ["coast"] and resources == ["Linen"]
    assert proposed == {"tags": ["coast"], "resources": ["Linen"]}
