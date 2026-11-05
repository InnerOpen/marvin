"""An integration's paid call, recorded in AI executions under the provider's own name (``elevenlabs``), apart from the AI spend.

A provider that bills for what it makes (speech by the character, an image by the picture) returns a ``usage`` block with its output:
``{provider_type, model, characters?, multiplier?, input_tokens?, output_tokens?}``. The workflow ``integration`` step writes one row per
call from it, so AI executions shows what was spent and where. The row has ``trigger_type="integration"``, which ``services/ai/budget.py``
keeps out of the monthly total, the limits and the unpriced list: those are for the AI set up in AI settings, not for integrations.
What a call used is kept in ``metadata_json`` (``unit``, ``units``, ``multiplier``) for the tally that card shows.
"""

from __future__ import annotations

from marvin.core.root_logger import get_logger

logger = get_logger(__name__)

INTEGRATION_TRIGGER = "integration"


def _number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def units_used(usage: dict) -> tuple[str, int]:
    """What the call used, as (unit, amount): characters when the provider reports them, else a plain call."""
    if "characters" in usage:
        return "characters", int(_number(usage.get("characters")))
    return "calls", 1


def record_call(session, group_id, row, operation: str, out: dict, *, user_id=None, elapsed_ms: int | None = None) -> None:
    """Write the call's AI-executions row if its output carries a usage block. Best-effort inside a savepoint: a logging failure never
    fails the step or undoes the work around it. ``row`` is the integration (``provider``, ``slug``, ``id``)."""
    usage = out.get("usage") if isinstance(out, dict) else None
    if not isinstance(usage, dict):
        return
    from marvin.db.models.groups.ai_executions import AIExecutionModel

    unit, units = units_used(usage)
    multiplier = _number(usage.get("multiplier"), 1.0)
    input_tokens, output_tokens = int(_number(usage.get("input_tokens"))), int(_number(usage.get("output_tokens")))
    try:
        with session.begin_nested():
            session.add(
                AIExecutionModel(
                    session=session,
                    group_id=group_id,
                    operation_slug=operation,
                    provider_type=str(usage.get("provider_type") or row.provider),
                    model_id=str(usage.get("model") or "unknown"),
                    status="completed",
                    triggered_by=user_id,
                    trigger_type=INTEGRATION_TRIGGER,
                    prompt_tokens=input_tokens or None,
                    completion_tokens=output_tokens or None,
                    total_tokens=(input_tokens + output_tokens) or None,
                    duration_ms=elapsed_ms,
                    metadata_json={
                        "integration": row.slug,
                        "integration_id": str(row.id),
                        "unit": unit,
                        "units": units,
                        "multiplier": multiplier,
                    },
                )
            )
    except Exception as e:  # noqa: BLE001 — recording spend must never break the call that spent it
        logger.warning("integration usage not recorded for %s: %s", operation, e)
