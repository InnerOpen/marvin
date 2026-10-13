"""FRONTEND_URL must decide where the frontend actually listens.

The setting advertised a port (used for OIDC callback redirects) that nothing bound to: the
container entrypoint hardcoded its own default, and the Astro config hardcoded a third value. So
changing FRONTEND_URL moved the redirect target while the server kept listening where it always
had. FRONTEND_PORT is now derived from FRONTEND_URL unless it is set explicitly, and startup reads
it.
"""

import pytest

from marvin.core.settings.settings import AppSettings


def _settings(**overrides) -> AppSettings:
    # SECRET is required and has no default; everything else falls back to its declared default.
    return AppSettings(SECRET="test-secret", **overrides)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://localhost:4322", 4322),
        ("http://localhost:9999", 9999),
        ("https://cms.example.com", 443),
        ("http://cms.example.com", 80),
        ("https://cms.example.com:8443", 8443),
    ],
)
def test_frontend_port_is_derived_from_frontend_url(url, expected):
    assert _settings(FRONTEND_URL=url).FRONTEND_PORT == expected


def test_default_settings_agree_with_the_default_url():
    """The advertised default and the bind default must not drift apart again."""
    settings = _settings()

    assert settings.FRONTEND_URL == "http://localhost:4322"
    assert settings.FRONTEND_PORT == 4322


def test_explicit_frontend_port_wins_over_the_url():
    """For proxied deployments where the public URL is not the socket."""
    settings = _settings(FRONTEND_URL="https://cms.example.com", FRONTEND_PORT=4321)

    assert settings.FRONTEND_PORT == 4321


def test_trailing_slash_does_not_break_derivation():
    """FRONTEND_URL is trailing-slash trimmed by a validator; derivation runs after it."""
    settings = _settings(FRONTEND_URL="http://localhost:4322/")

    assert settings.FRONTEND_URL == "http://localhost:4322"
    assert settings.FRONTEND_PORT == 4322


def test_unparseable_url_falls_back_to_the_dev_default():
    """A malformed value must not leave the port as None and crash startup."""
    settings = _settings(FRONTEND_URL="not-a-url")

    assert settings.FRONTEND_PORT == 4322
