"""The length and sampling parameters an OpenAI-style chat model accepts — guessed, then learned.

Newer models reject `max_tokens` in favour of `max_completion_tokens`, and reasoning models also reject
a non-default temperature / top_p. A list of name prefixes can't keep up with new models (`gpt-6.1-sol`
was sent `max_tokens` and refused), so the name only gives the first guess. When the API answers 400
naming the parameter, the call is retried with the fix, and the fix is remembered for that model for the
life of the process — one failed round trip per model, not per call. Older models and OpenAI-compatible
servers that only know `max_tokens` are corrected the same way in the other direction.

Shared by the OpenAI and Azure OpenAI providers (on Azure, `model` is the deployment name).
"""

import logging

from ..base import CompletionOptions

logger = logging.getLogger(__name__)

# First guess only — a model not listed here is corrected by its first 400.
REASONING_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5", "gpt-6")

FIX_COMPLETION_TOKENS = "max_completion_tokens"  # the model wants max_completion_tokens
FIX_LEGACY_MAX_TOKENS = "max_tokens"  # the model / server only knows max_tokens
FIX_DEFAULT_SAMPLING = "default_sampling"  # the model accepts only the default temperature / top_p
MAX_FIXES = 2  # a length fix and a sampling fix

_learned: dict[str, set[str]] = {}


def sampling_kwargs(model: str, opts: CompletionOptions, *, include_top_p: bool = False) -> dict:
    """The length and sampling parameters to send this model; unset limits are left out."""
    fixes = _learned.get(model, set())
    named_reasoning = model.startswith(REASONING_MODEL_PREFIXES)
    completion_tokens = FIX_LEGACY_MAX_TOKENS not in fixes and (named_reasoning or FIX_COMPLETION_TOKENS in fixes)
    default_sampling = named_reasoning or FIX_DEFAULT_SAMPLING in fixes
    kwargs: dict = {}
    if opts.max_tokens is not None:
        kwargs["max_completion_tokens" if completion_tokens else "max_tokens"] = opts.max_tokens
    if not default_sampling:
        kwargs["temperature"] = opts.temperature
        if include_top_p:
            kwargs["top_p"] = opts.top_p
    return kwargs


def fix_for(error: Exception) -> str | None:
    """The parameter fix a 400 asks for, or None when the error is about something else."""
    if getattr(error, "status_code", None) != 400:
        return None
    body = getattr(error, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        body = body["error"]
    if not isinstance(body, dict):
        return None
    param = body.get("param")
    message = str(body.get("message") or "")
    if param == "max_tokens" and "max_completion_tokens" in message:
        return FIX_COMPLETION_TOKENS
    if param == "max_completion_tokens":
        return FIX_LEGACY_MAX_TOKENS
    if param in ("temperature", "top_p"):
        return FIX_DEFAULT_SAMPLING
    return None


def create_chat_completion(client, model: str, opts: CompletionOptions, *, include_top_p: bool = False, **request):
    """`client.chat.completions.create` with the parameters this model accepts, learning from a 400."""
    for _ in range(MAX_FIXES):
        try:
            return client.chat.completions.create(model=model, **request, **sampling_kwargs(model, opts, include_top_p=include_top_p))
        except Exception as e:
            fix = fix_for(e)
            if fix is None or fix in _learned.get(model, set()):
                raise
            _learned.setdefault(model, set()).add(fix)
            logger.info("model %s: retrying with %s after: %s", model, fix, e)
    return client.chat.completions.create(model=model, **request, **sampling_kwargs(model, opts, include_top_p=include_top_p))
