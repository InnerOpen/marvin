"""Unit tests for the per-request output-token cap (_max_output_tokens).

`budget_config.max_tokens_per_request` used to be stored and never read — every call used the
global AI_DEFAULT_MAX_TOKENS regardless. These pin the workspace override actually taking effect,
and the fallbacks around a missing / junk value.
"""

from unittest.mock import MagicMock, patch

from marvin.routes.ai.operations_controller import AIOperationsController

APP_DEFAULT = 2048


def _ctrl(budget_config):
    """A controller whose workspace settings carry the given budget_config (None = no row)."""
    ctrl = MagicMock()
    ctrl.group_id = "g1"
    settings = None if budget_config is None else MagicMock(budget_config=budget_config)
    ctrl.session.query.return_value.filter_by.return_value.first.return_value = settings
    return ctrl


def _call(budget_config):
    with patch("marvin.core.config.get_app_settings") as gs:
        gs.return_value = MagicMock(AI_DEFAULT_MAX_TOKENS=APP_DEFAULT)
        return AIOperationsController._max_output_tokens(_ctrl(budget_config))


def test_workspace_override_is_used_when_set():
    assert _call({"max_tokens_per_request": 512}) == 512


def test_falls_back_to_app_default_when_no_override():
    assert _call({"max_requests_per_day": 100}) == APP_DEFAULT  # other budget keys, no token cap


def test_falls_back_when_no_budget_config():
    assert _call({}) == APP_DEFAULT


def test_falls_back_when_no_settings_row():
    assert _call(None) == APP_DEFAULT


def test_zero_or_negative_is_ignored_not_clamped_to_nothing():
    # A misconfigured 0 must not silently truncate every response to empty.
    assert _call({"max_tokens_per_request": 0}) == APP_DEFAULT
    assert _call({"max_tokens_per_request": -5}) == APP_DEFAULT


def test_junk_value_falls_back():
    assert _call({"max_tokens_per_request": "lots"}) == APP_DEFAULT
    assert _call({"max_tokens_per_request": None}) == APP_DEFAULT


def test_string_number_is_accepted():
    assert _call({"max_tokens_per_request": "1000"}) == 1000
