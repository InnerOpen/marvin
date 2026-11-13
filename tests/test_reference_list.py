"""`references` on an image action: a list, comma text, or a list whose items are themselves a list or comma text, flattened in order."""

from marvin.services.automation.actions.integration import _reference_list


def test_comma_text_and_a_plain_list_are_what_they_were():
    assert _reference_list("a,b, c") == ["a", "b", "c"]
    assert _reference_list(["a", "b"]) == ["a", "b"]
    assert _reference_list("a,,  ,b") == ["a", "b"]  # blanks are dropped
    assert _reference_list(None) == []


def test_an_item_that_is_a_list_or_comma_text_is_flattened_in_order():
    assert _reference_list([["m1", "m2"], "anchor"]) == ["m1", "m2", "anchor"]  # a field's pictures, then one more
    assert _reference_list(["m1,m2", "anchor"]) == ["m1", "m2", "anchor"]  # an older field that holds comma text
    assert _reference_list([[], None, "", "anchor"]) == ["anchor"]  # an empty field and a missing anchor add nothing
    assert _reference_list([["a", ["b", "c"]], "d"]) == ["a", "b", "c", "d"]
