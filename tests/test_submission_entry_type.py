"""Unit tests for the forms-as-entry-types submission plumbing.

Covers the pure pieces of the public submit → inbox-entry path: the entry-title derivation and the
`SubmissionConfig` that hangs off a submittable entry type's capabilities. The full HTTP flow
(submit → EntryService.create) is exercised as an integration test once the legacy Forms fallback
is removed (Phase 3).
"""

from types import SimpleNamespace

from marvin.routes.publish.forms_controller import _derive_submission_title, _published_form_from_entry_type
from marvin.schemas.platform.entry_type_rendering import CapabilitiesDefinition, SubmissionConfig


def _type(name="Contact"):
    return SimpleNamespace(name=name)


def test_title_uses_the_config_template():
    cfg = SubmissionConfig(title_template="Contact from {{ name }}")
    title = _derive_submission_title(cfg, _type(), {"name": "Jared", "message": "hi"})
    assert title == "Contact from Jared"


def test_title_falls_back_to_first_text_value_when_no_template():
    cfg = SubmissionConfig()
    title = _derive_submission_title(cfg, _type(), {"name": "Jared Mashburn", "message": "hi"})
    assert title == "Jared Mashburn"


def test_title_ignores_non_string_and_empty_values():
    cfg = SubmissionConfig()
    title = _derive_submission_title(cfg, _type(), {"agree": True, "count": 3, "name": "  Jared  "})
    assert title == "Jared"


def test_title_fallback_when_template_renders_empty():
    cfg = SubmissionConfig(title_template="{{ missing }}")
    title = _derive_submission_title(cfg, _type("Newsletter"), {"email": "a@b.com"})
    # Empty template render → first text value.
    assert title == "a@b.com"


def test_title_final_fallback_to_type_name():
    cfg = SubmissionConfig()
    title = _derive_submission_title(cfg, _type("Newsletter"), {"agree": True})
    assert title.startswith("Newsletter submission ")


def test_capabilities_parses_submission_config():
    caps = CapabilitiesDefinition.model_validate(
        {
            "submittable": True,
            "submission": {
                "successMessage": "Thanks!",
                "enableHoneypot": True,
                "honeypotField": "_website",
                "notify": True,
            },
        }
    )
    assert caps.submittable is True
    assert caps.submission is not None
    assert caps.submission.success_message == "Thanks!"
    assert caps.submission.enable_honeypot is True
    assert caps.submission.honeypot_field == "_website"


def test_capabilities_default_has_no_submission():
    caps = CapabilitiesDefinition()
    assert caps.submittable is False
    assert caps.submission is None


def _entry_type(**over):
    base = {
        "slug": "inquiry",
        "name": "Inquiry",
        "description": "Contact inquiries",
        "schema_json": {"fields": [{"type": "text", "key": "email", "label": "Email"}]},
    }
    base.update(over)
    return SimpleNamespace(**base)


def test_published_form_exposes_the_type_schema_and_success_message():
    cfg = SubmissionConfig(enable_honeypot=True, honeypot_field="_website", success_message="Thanks!")
    pub = _published_form_from_entry_type(_entry_type(), cfg)
    assert pub.slug == "inquiry"
    assert pub.form_schema["fields"][0]["key"] == "email"
    assert pub.metadata["successMessage"] == "Thanks!"
    assert pub.metadata["honeypotField"] == "_website"


def test_published_form_omits_honeypot_field_when_disabled():
    pub = _published_form_from_entry_type(_entry_type(), SubmissionConfig(enable_honeypot=False))
    assert pub.metadata["honeypotField"] is None
