"""Run one AI operation and record it — the one runner behind the interactive route
(``POST /api/ai/operations/{slug}/execute``) and a workflow's ``operation`` step.

Each used to carry its own copy of the same sequence: an ``AIExecution`` row, the prompt built and its
``{{SLUG}}`` references resolved, the provider call (a custom operation's answer checked against its output
schema, with one retry told what was wrong), timing, token and cost accounting, and the row marked failed when
the call raised. The callers keep what differs: their gates (role, invocation source, budget), how they build
the context, what they raise (an HTTP status, an ``AutomationActionError``), their events, and the write-back.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from marvin.services.ai.base import Message
from marvin.services.ai.operations.custom import output_problems


@dataclass
class OperationRun:
    """A completed run: the recorded execution, the parsed answer, and the usage of every provider call."""

    execution: Any  # AIExecutionModel
    parsed: Any
    usage: list  # one CompletionResult per call — a checked custom answer may take two


class OperationFailed(RuntimeError):
    """The provider call (or the answer check) raised: the execution is recorded as failed and carried here, so a
    caller can emit its own events for it before answering with its own error type."""

    def __init__(self, execution, cause: Exception) -> None:
        super().__init__(str(cause))
        self.execution = execution
        self.cause = cause


def complete(provider, operation, messages: list, model: str, opts, *, check: bool) -> tuple[Any, list]:
    """The provider's structured answer and the usage of every call. With ``check`` (a custom operation) the answer
    must match the output schema: one more try, told what was wrong, then a ValueError (the run fails, logged as
    failed)."""
    parsed, completion = provider.execute_operation(messages, model, operation.output_schema, opts)
    usage = [completion]
    if check and (problems := output_problems(operation.output_schema, parsed)):
        retry = [
            *messages,
            Message(role="assistant", content=json.dumps(parsed)[:4000]),
            Message(role="user", content=f"That answer doesn't match the schema: {'; '.join(problems)}. Answer again with only the JSON object."),
        ]
        parsed, completion = provider.execute_operation(retry, model, operation.output_schema, opts)
        usage.append(completion)
        if problems := output_problems(operation.output_schema, parsed):
            raise ValueError(f"the answer doesn't match output_schema: {'; '.join(problems)}")
    return parsed, usage


def run_operation(
    session,
    group_id,
    operation,
    *,
    op_input: dict,
    ctx,
    provider,
    model: str,
    source: str,
    slug: str | None = None,
    user_id=None,
    entity_type: str | None = None,
    entity_id=None,
    check_schema: bool = False,
    log_inputs: bool = True,
    log_outputs: bool = True,
    finish: Callable[[Any], Any] | None = None,
) -> OperationRun:
    """Record an execution, call the provider, price the answer. ``finish`` may reshape the parsed answer before it is
    stored (the interactive route attaches a retrieval op's sources). Raises :class:`OperationFailed` with the failed
    row when the call or the check raised; the caller turns that into its own error and events."""
    from marvin.core.config import get_app_settings
    from marvin.db.models.groups.ai_executions import AIExecutionModel
    from marvin.services.ai import budget
    from marvin.services.ai.base import CompletionOptions
    from marvin.services.ai.context import resolve_prompt_messages
    from marvin.services.ai.pricing import estimate_cost

    execution = AIExecutionModel(
        session=session,
        group_id=group_id,
        operation_slug=slug or operation.slug,
        provider_type=provider.provider_type,
        model_id=model,
        status="running",
        triggered_by=user_id,
        trigger_type=source,
        entity_type=entity_type,
        entity_id=entity_id,
        input_json=op_input if log_inputs else None,
        started_at=datetime.now(UTC),
    )
    session.add(execution)
    session.commit()
    start = time.monotonic()
    try:
        opts = CompletionOptions(temperature=get_app_settings().AI_DEFAULT_TEMPERATURE, max_tokens=budget.max_output_tokens(session, group_id))
        messages = resolve_prompt_messages(operation.build_prompt(op_input, ctx), group_id, ctx.variables)
        parsed, usage = complete(provider, operation, messages, model, opts, check=check_schema)
        if finish is not None:
            parsed = finish(parsed)
        prompt_tokens = sum(c.prompt_tokens or 0 for c in usage)  # a retried custom answer costs both calls
        completion_tokens = sum(c.completion_tokens or 0 for c in usage)
        execution.status = "completed"
        execution.completed_at = datetime.now(UTC)
        execution.duration_ms = int((time.monotonic() - start) * 1000)
        execution.output_json = parsed if log_outputs else None
        execution.prompt_tokens = prompt_tokens
        execution.completion_tokens = completion_tokens
        execution.total_tokens = sum(c.total_tokens or 0 for c in usage)
        execution.estimated_cost_usd = estimate_cost(provider.provider_type, model, prompt_tokens, completion_tokens)
        session.commit()
    except Exception as e:
        execution.status = "failed"
        execution.error_message = str(e)
        execution.completed_at = datetime.now(UTC)
        execution.duration_ms = int((time.monotonic() - start) * 1000)
        session.commit()
        raise OperationFailed(execution, e) from e
    return OperationRun(execution=execution, parsed=parsed, usage=usage)
