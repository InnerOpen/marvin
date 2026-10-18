"""`schema_check` step — hold a JSON document up against a JSON Schema and report what doesn't fit.

`document`: the thing to check — usually an earlier step's parsed answer (`${steps.page.output.json}`, a `fetch`
step's JSON body), or any templated value (an entry field, an input). A string that holds a JSON object or array is
read as JSON text; any other string is checked as the string itself. `schema`: the JSON Schema inline (an object, or
a template that gives one or the JSON text of one), or `schema_resource`: a resource (id or slug) whose
`metadata.schema` holds it. Draft 2020-12 unless the schema says otherwise; `format` is not asserted; a `$ref` reaches
only into the schema itself (nothing is fetched).

Output: `valid`, `errors` ([{path, message}] — at most `max_errors`, in path order), `error_count` (how many were found,
counting to 1000), `truncated` and `text` (one line per error, for a note or an AI prompt). A document that doesn't fit is
the output, for a `when` to act on — never a failed step — unless the step says `fail_on_invalid`. What does fail the step is
a schema that can't be used (the editor refuses a malformed inline one when it is written; one that arrives by template or
resource is refused here). A dry run checks too when there is a document; when an earlier step didn't really run (a fetch that didn't
fetch, an AI answer that wasn't asked for) there is none, and the answer is `valid: null`.
"""

from __future__ import annotations

import json
from itertools import islice
from typing import Any

from ..matcher import interpolate
from .base import AutomationActionError, register_action

MAX_DOCUMENT_BYTES = 100_000  # as JSON text; a document beyond it is reported, not checked (a pattern can be slow)
MAX_SCHEMA_BYTES = 64_000
DEFAULT_MAX_ERRORS = 20
MAX_ERRORS_CAP = 50
FOUND_ERRORS_CAP = 1000  # what the validator is asked for; error_count counts to here
MAX_MESSAGE_CHARS = 300  # a message quotes the offending value, which may be a megabyte of text


def schema_problem(schema: Any) -> str | None:
    """Why `schema` can't be used as a JSON Schema — None when it can. Shared by the definition model (so the editor
    and the validator refuse it when it is written) and the step (a schema that arrives by template or resource)."""
    from jsonschema.exceptions import SchemaError
    from jsonschema.validators import validator_for

    if not isinstance(schema, dict | bool):
        return "a JSON Schema is an object (or true / false)"
    if len(json.dumps(schema)) > MAX_SCHEMA_BYTES:
        return f"the schema is larger than {MAX_SCHEMA_BYTES // 1000} KB"
    try:
        validator_for(schema).check_schema(schema)
    except SchemaError as e:
        where = "/".join(str(p) for p in e.absolute_path)
        return f"{e.message[:MAX_MESSAGE_CHARS]}" + (f" (at {where})" if where else "")
    except Exception as e:  # noqa: BLE001 — an unknown $schema and the like
        return f"{type(e).__name__}: {str(e)[:MAX_MESSAGE_CHARS]}"
    return None


def parse_text(value: Any) -> tuple[Any, str | None]:
    """(value, None), reading a string that looks like a JSON object or array as JSON text; (None, why) when it
    looks like one but isn't valid JSON."""
    if isinstance(value, str) and value.lstrip()[:1] in ("{", "["):
        try:
            return json.loads(value), None
        except (ValueError, RecursionError) as e:
            return None, f"not valid JSON: {str(e)[:200]}"
    return value, None


def check(document: Any, schema: Any, *, max_errors: int = DEFAULT_MAX_ERRORS) -> dict:
    """The step's output for `document` against `schema` (assumed usable — see `schema_problem`)."""
    from jsonschema.validators import validator_for

    max_errors = max(1, min(int(max_errors), MAX_ERRORS_CAP))
    found: list[dict] = []
    document, unreadable = parse_text(document)
    if unreadable:
        found = [{"path": "$", "message": unreadable}]
    elif document is None:
        found = [{"path": "$", "message": "there is no document to check (what the step points at came out empty)"}]
    else:
        try:
            size = len(json.dumps(document, default=str))
        except (ValueError, TypeError, RecursionError):
            size = MAX_DOCUMENT_BYTES + 1
        if size > MAX_DOCUMENT_BYTES:
            found = [{"path": "$", "message": f"the document is larger than {MAX_DOCUMENT_BYTES // 1000} KB, so it was not checked"}]
        else:
            try:
                errors = islice(validator_for(schema)(schema).iter_errors(document), FOUND_ERRORS_CAP)
                found = sorted(
                    ({"path": _path(e.absolute_path), "message": e.message[:MAX_MESSAGE_CHARS]} for e in errors),
                    key=lambda e: (e["path"], e["message"]),
                )
            except RecursionError:
                found = [{"path": "$", "message": "the document is nested too deeply to check"}]
            except Exception as e:  # noqa: BLE001 — a $ref that points outside the schema, a pattern that isn't a regex
                raise AutomationActionError(f"the schema can't be applied: {type(e).__name__}: {str(e)[:MAX_MESSAGE_CHARS]}") from e
    shown = found[:max_errors]
    return {
        "valid": not found,
        "errors": shown,
        "error_count": len(found),
        "truncated": len(found) > len(shown),
        "text": "\n".join(f"- {e['path']}: {e['message']}" for e in shown),
    }


def _path(parts) -> str:
    """`$.agents[0].name` — a path a person can follow into the document."""
    out = "$"
    for part in parts:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if str(part).isidentifier() else f"[{json.dumps(str(part))}]")
    return out


@register_action("schema_check")
def run_schema_check_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    if "document" not in action:
        raise AutomationActionError("a schema_check step needs `document` (what to check, e.g. ${steps.page.output.json})")
    schema = _schema(session, group_id, action, context)
    document = interpolate(action["document"], context)
    if dry_run and _nothing_real(document):
        return {"dry_run": True, "valid": None, "errors": [], "error_count": 0, "truncated": False, "text": "", "note": "no document in a dry run"}
    out = check(document, schema, max_errors=action.get("max_errors") or DEFAULT_MAX_ERRORS)
    if dry_run:
        out["dry_run"] = True
    if action.get("fail_on_invalid") and not out["valid"]:
        first = out["errors"][0]
        more = f" (and {out['error_count'] - 1} more)" if out["error_count"] > 1 else ""
        raise AutomationActionError(f"the document doesn't fit its schema: {first['path']}: {first['message']}{more}", code="invalid_document")
    return out


def _nothing_real(document: Any) -> bool:
    """In a dry run: no document yet — an earlier step didn't run (a fetch gave nothing) or its answer is a stand-in."""
    from ..runner import is_stand_in

    return document is None or is_stand_in(document)


def _schema(session, group_id, action: dict, context: dict) -> Any:
    """The schema to hold the document to: inline (a template may give it), or a resource's `metadata.schema`."""
    if bool(action.get("schema") is not None) == bool(action.get("schema_resource")):
        raise AutomationActionError(
            "a schema_check step takes `schema` (the JSON Schema) or `schema_resource` (a resource that holds it), one of them"
        )
    if action.get("schema_resource"):
        schema = _resource_schema(session, group_id, str(interpolate(action["schema_resource"], context) or "").strip())
    else:
        # Not interpolated as a whole: a schema's own "$ref" / "$defs" / a pattern like "$" must stay as written.
        raw = action["schema"]
        schema = interpolate(raw, context) if isinstance(raw, str) else raw
        schema, unreadable = parse_text(schema)
        if unreadable:
            raise AutomationActionError(f"the schema {unreadable}")
    if problem := schema_problem(schema):
        raise AutomationActionError(f"the schema can't be used: {problem}")
    return schema


def _resource_schema(session, group_id, ref: str) -> Any:
    import uuid

    from marvin.db.models.platform import Resources

    if not ref:
        raise AutomationActionError("schema_resource is empty: name a resource (its id or slug)")
    query = session.query(Resources).filter(Resources.group_id == group_id, Resources.trashed_at.is_(None))
    try:
        row = query.filter(Resources.id == uuid.UUID(ref)).first()
    except ValueError:
        row = None
    row = row or query.filter(Resources.slug == ref).first()
    if row is None:
        raise AutomationActionError(f"no resource “{ref}” in this workspace to take the schema from")
    schema = (row.metadata_json or {}).get("schema")
    if schema is None:
        raise AutomationActionError(f"resource “{row.name}” has no `schema` in its metadata (an object, or JSON text)")
    schema, unreadable = parse_text(schema)
    if unreadable:
        raise AutomationActionError(f"resource “{row.name}”: its schema is {unreadable}")
    return schema
