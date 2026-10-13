"""Fetch an image a provider returned as a URL — through core's SSRF-guarded client, never a raw HTTP get.

A generated image's URL comes from a third party; following it blindly (or its redirects) could reach the cluster's
own network. ``MarvinHttpHelper`` refuses private, loopback and link-local hosts, re-checks every redirect and caps
the bytes read.
"""

from __future__ import annotations

MAX_IMAGE_BYTES = 20 * 1024 * 1024  # the same cap as importing an image by URL (ai/tools/builtins_actions.py)
FETCH_TIMEOUT = 60  # seconds; generated images are often served from a slow CDN on first read


def fetch_image(url: str) -> bytes:
    """The bytes at ``url``; ValueError when it can't be fetched (a non-public host, a non-2xx, too big, empty)."""
    from marvin.services.integrations.http_client import MarvinHttpHelper

    try:
        resp = MarvinHttpHelper(max_bytes=MAX_IMAGE_BYTES).get(str(url), timeout=FETCH_TIMEOUT)
    except ValueError:
        raise
    except Exception as e:  # noqa: BLE001 — a network failure is reported, not raised raw
        raise ValueError(f"could not fetch the image: {e}") from e
    if not resp.ok:
        raise ValueError(f"could not fetch the image: HTTP {resp.status_code}")
    if not resp.content:
        raise ValueError("the image URL returned nothing")
    return resp.content
