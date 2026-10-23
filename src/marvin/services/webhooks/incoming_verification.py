"""Answering a sender's verification request for an incoming webhook — the capability, not any sender's details.

Some senders check a webhook URL before they deliver to it: a GET carrying a challenge and the verify token they were
given, expecting the challenge back. A :class:`VerificationSpec` names the query parameters that carry them, and
optionally a mode parameter that must take one of a few values. Core knows no sender: an installed integration
contributes its senders' schemes (``verification_schemes`` on the provider — Meta's lives in the Instagram and Facebook
integrations), and ``custom`` lets a workspace describe any other.

The token is compared, in constant time, with the webhook's workspace secret (``verify_token_ref``). Anything missing —
the secret, the challenge, the token, a mode the scheme requires — refuses the request. A GET never delivers: it
answers the check and records an ``incoming_webhook_verified`` event, separate from deliveries (routes/hooks).
"""

import hmac
from collections.abc import Mapping
from dataclasses import dataclass, field

CUSTOM_SCHEME = "custom"
MAX_CHALLENGE_CHARS = 512
CONTENT_TYPES = ("text/plain", "application/json")
SPEC_FIELDS = ("challenge_param", "token_param", "mode_param", "mode_values", "content_type")


@dataclass(frozen=True)
class VerificationSpec:
    """Where one sender puts its challenge and verify token in the GET's query string."""

    challenge_param: str
    """The parameter whose value is echoed back."""
    token_param: str
    """The parameter carrying the verify token, compared with the webhook's secret."""
    mode_param: str | None = None
    """A parameter that must be present with one of ``mode_values`` (e.g. a subscribe / unsubscribe mode)."""
    mode_values: tuple[str, ...] = ()
    content_type: str = "text/plain"
    """How the challenge is sent back: text/plain (the bare value) | application/json (as a JSON string)."""
    notes: str = field(default="", compare=False)


def spec_problems(spec: VerificationSpec) -> list[str]:
    problems = []
    if not spec.challenge_param.strip() or not spec.token_param.strip():
        problems.append("challenge_param and token_param are both needed")
    if spec.mode_param and not spec.mode_values:
        problems.append("mode_param needs the mode_values it may take")
    if spec.content_type not in CONTENT_TYPES:
        problems.append(f"content_type must be one of {', '.join(CONTENT_TYPES)}")
    return problems


def _build(config: dict | None) -> VerificationSpec | None:
    """A spec from a declaration or a custom config; None when it isn't usable."""
    if not isinstance(config, dict):
        return None
    values = {k: v for k, v in config.items() if k in (*SPEC_FIELDS, "notes")}
    if isinstance(values.get("mode_values"), list | tuple):
        values["mode_values"] = tuple(str(v) for v in values["mode_values"])
    try:
        spec = VerificationSpec(**values)
    except TypeError:
        return None
    return spec if spec_problems(spec) == [] else None


def provider_presets() -> dict[str, tuple[VerificationSpec, str]]:
    """Schemes contributed by installed integrations: name → (spec, provider slug). A malformed declaration is skipped
    with a warning; the first integration to declare a name keeps it."""
    from marvin.services.integrations import INTEGRATIONS_AVAILABLE

    if not INTEGRATIONS_AVAILABLE:
        return {}
    from marvin.core.root_logger import get_logger
    from marvin.services.integrations import list_providers

    found: dict[str, tuple[VerificationSpec, str]] = {}
    for provider in list_providers():
        for name, config in (getattr(provider, "verification_schemes", None) or {}).items():
            if name == CUSTOM_SCHEME or name in found:
                continue
            spec = _build(config)
            if spec is None:
                get_logger(__name__).warning("integration %s declared an unusable verification scheme %r", getattr(provider, "slug", "?"), name)
                continue
            found[name] = (spec, provider.slug)
    return found


def available_schemes() -> list[dict]:
    """Every scheme a webhook can pick: integration presets, then `custom`."""
    rows = [{"name": name, "notes": spec.notes, "source": slug} for name, (spec, slug) in sorted(provider_presets().items())]
    return [*rows, {"name": CUSTOM_SCHEME, "notes": "Describe the parameters yourself in verification_config.", "source": "core"}]


def spec_for(scheme: str | None, config: dict | None) -> VerificationSpec | None:
    """The webhook's spec: its custom config, or an integration's scheme by name; None when there is none to use."""
    if not scheme:
        return None
    if scheme == CUSTOM_SCHEME:
        return _build(config)
    found = provider_presets().get(scheme)
    return found[0] if found else None


def usable(scheme: str | None, config: dict | None) -> str | None:
    """Why the scheme can't be saved, or None. No scheme at all is fine (verification off)."""
    if not scheme:
        return None
    if scheme == CUSTOM_SCHEME:
        if not isinstance(config, dict):
            return "a custom verification scheme needs verification_config"
        spec = _build(config)
        return None if spec else "; ".join(spec_problems(_lenient(config))) or "verification_config isn't usable"
    return None if scheme in provider_presets() else f"no installed integration offers the verification scheme {scheme!r}"


def _lenient(config: dict) -> VerificationSpec:
    """A spec for reporting what's wrong with a config that _build refused."""
    return VerificationSpec(
        challenge_param=str(config.get("challenge_param") or ""),
        token_param=str(config.get("token_param") or ""),
        mode_param=config.get("mode_param") or None,
        mode_values=tuple(config.get("mode_values") or ()),
        content_type=str(config.get("content_type") or "text/plain"),
    )


def answer(spec: VerificationSpec, params: Mapping[str, str], secret: str | None) -> str | None:
    """The challenge to send back, or None to refuse: the secret set, the mode allowed, a challenge present and not too
    long, and the token matching."""
    challenge, presented = params.get(spec.challenge_param), params.get(spec.token_param)
    if not secret or challenge is None or presented is None or len(challenge) > MAX_CHALLENGE_CHARS:
        return None
    if spec.mode_param and params.get(spec.mode_param) not in spec.mode_values:
        return None
    return challenge if hmac.compare_digest(presented.encode(), secret.encode()) else None


def is_verification(spec: VerificationSpec | None, params: Mapping[str, str]) -> bool:
    """Whether a GET looks like this scheme's check at all (it carries the challenge), as opposed to a stray visit."""
    return spec is not None and spec.challenge_param in params
