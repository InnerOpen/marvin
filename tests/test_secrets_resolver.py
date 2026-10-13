"""{{SLUG}} resolution: per-send context vs. secrets/variables, and what an unresolved ref becomes."""

from types import SimpleNamespace

import marvin.core.config as config
from marvin.services.secrets import resolver
from marvin.services.secrets.resolver import UNRESOLVED_SENTINEL, resolve, resolve_dict


def _force_production(monkeypatch, value: bool) -> None:
    monkeypatch.setattr(config, "get_app_settings", lambda *_a, **_k: SimpleNamespace(PRODUCTION=value))


def test_resolve_uses_per_send_context_first():
    assert resolve("Hi {{ user_name }}", context={"user_name": "Ada"}) == "Hi Ada"


def test_resolve_leaves_text_without_refs_untouched():
    assert resolve("plain text", context={}) == "plain text"


def test_unresolved_lowercase_ref_is_left_for_jinja_in_production(monkeypatch):
    _force_production(monkeypatch, True)
    monkeypatch.setattr(resolver, "get_secret_backend", lambda: SimpleNamespace(get=lambda *_: None))
    out = resolve("{{webhook_name}} happened", context={"entry_title": "x"}, allow_secrets=False)
    assert out == "{{webhook_name}} happened" and UNRESOLVED_SENTINEL not in out


def test_unresolved_uppercase_ref_becomes_sentinel_in_production(monkeypatch):
    _force_production(monkeypatch, True)
    monkeypatch.setattr(resolver, "get_secret_backend", lambda: SimpleNamespace(get=lambda *_: None))
    monkeypatch.setattr(resolver, "_get_variable", lambda *_: None)
    assert resolve("Token {{MISSING_KEY}}") == f"Token {UNRESOLVED_SENTINEL}"


def test_unresolved_uppercase_ref_is_kept_in_dev(monkeypatch):
    _force_production(monkeypatch, False)
    monkeypatch.setattr(resolver, "get_secret_backend", lambda: SimpleNamespace(get=lambda *_: None))
    monkeypatch.setattr(resolver, "_get_variable", lambda *_: None)
    assert resolve("Token {{MISSING_KEY}}") == "Token {{MISSING_KEY}}"


def test_resolve_dict_drops_headers_with_sentinel(monkeypatch):
    _force_production(monkeypatch, True)
    monkeypatch.setattr(resolver, "get_secret_backend", lambda: SimpleNamespace(get=lambda slug, _g: "s3cret" if slug == "GOOD" else None))
    monkeypatch.setattr(resolver, "_get_variable", lambda *_: None)
    out = resolve_dict({"Authorization": "Token {{GOOD}}", "X-Bad": "{{MISSING}}", "Plain": "v"})
    assert out == {"Authorization": "Token s3cret", "Plain": "v"}
