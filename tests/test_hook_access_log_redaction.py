"""The access log never carries an incoming webhook's credentials: the hook token in `/api/hooks/<token>` and a
verification request's verify token in its query string become ‹redacted›; every other path is logged as it was."""

import logging

from marvin.app import HookAccessRedactFilter, _uvicorn_log_config


def _access_line(path: str) -> logging.LogRecord:
    # Uvicorn's access record: msg '%s - "%s %s HTTP/%s" %d', args (client, method, path, http version, status).
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', ("203.0.113.7:0", "GET", path, "1.1", 200), None)


def test_a_hook_calls_token_and_query_string_are_redacted():
    record = _access_line("/api/hooks/s3cr3t-token?hub.mode=subscribe&hub.verify_token=phrase&hub.challenge=42")

    assert HookAccessRedactFilter().filter(record)  # the line is kept

    line = record.getMessage()
    assert "s3cr3t-token" not in line and "phrase" not in line
    assert line == '203.0.113.7:0 - "GET /api/hooks/‹redacted› HTTP/1.1" 200'


def test_other_paths_are_logged_as_they_were():
    record = _access_line("/api/entries?page=2")

    HookAccessRedactFilter().filter(record)

    assert "/api/entries?page=2" in record.getMessage()


def test_the_server_log_config_applies_it():
    assert "hook_credentials" in _uvicorn_log_config()["handlers"]["access"]["filters"]
