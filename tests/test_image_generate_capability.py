"""`image.generate` as a capability step: any image connection, after an Approval step when its action asks for one."""


def test_the_draft_check_wants_an_approval_step_before_image_generate_on_a_connection_that_asks_for_one():
    from marvin.services.automation.authoring import _image_generate_issue

    row = {"actions": [{"action": "generate", "capability": "image.generate", "requires_approval": True}]}
    seen: list[str] = []
    _image_generate_issue(row, "openai-images", "image.generate", False, lambda key, msg: seen.append(msg))
    _image_generate_issue(row, "openai-images", "image.generate", True, lambda key, msg: seen.append(msg))
    assert len(seen) == 1 and "Approval step" in seen[0]
