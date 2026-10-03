"""`{{SLUG}}` in integration action arguments resolves to the workspace secret — for the call only."""

import pytest

from marvin.services.integrations import arg_secrets
from marvin.services.integrations.arg_secrets import MissingSecretError, resolve_arg_secrets


@pytest.fixture
def secrets(monkeypatch):
    store = {("G", "CLOUDFLARE_NOTIFY_TOKEN"): "s3cret"}
    monkeypatch.setattr("marvin.services.secrets.resolver.resolve_secret", lambda slug, gid: store.get((gid, slug)))
    return store


def test_a_whole_value_reference_resolves(secrets):
    out = resolve_arg_secrets({"webhook_secret": "{{ CLOUDFLARE_NOTIFY_TOKEN }}", "webhook_url": "https://x"}, "G")
    assert out == {"webhook_secret": "s3cret", "webhook_url": "https://x"}


def test_only_whole_values_and_only_this_workspace(secrets):
    args = {"note": "pass {{CLOUDFLARE_NOTIFY_TOKEN}} along", "n": 3}
    assert resolve_arg_secrets(args, "G") == args  # embedded text and non-strings are left alone
    with pytest.raises(MissingSecretError):
        resolve_arg_secrets({"webhook_secret": "{{CLOUDFLARE_NOTIFY_TOKEN}}"}, "OTHER-WORKSPACE")


def test_the_input_is_not_modified(secrets):
    args = {"webhook_secret": "{{CLOUDFLARE_NOTIFY_TOKEN}}"}
    resolve_arg_secrets(args, "G")
    assert args == {"webhook_secret": "{{CLOUDFLARE_NOTIFY_TOKEN}}"}  # the stored workflow keeps the reference


def test_module_documents_its_scope():
    assert "never back into the stored workflow" in arg_secrets.__doc__
