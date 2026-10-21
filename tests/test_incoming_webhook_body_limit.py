"""The incoming webhook receiver reads the body incrementally and stops at the cap (GitHub issue #21)."""

import asyncio

import pytest
from fastapi import HTTPException

from marvin.routes.hooks.hooks_controller import _MAX_BODY_BYTES, _read_capped


class _Request:
    """Just what _read_capped uses: headers and an async chunk stream that counts what was pulled."""

    def __init__(self, chunks, content_length=None):
        self.headers = {} if content_length is None else {"content-length": str(content_length)}
        self._chunks = chunks
        self.pulled = 0

    async def stream(self):
        for chunk in self._chunks:
            self.pulled += 1
            yield chunk


def _read(request, limit=_MAX_BODY_BYTES):
    return asyncio.run(_read_capped(request, limit))


def test_a_body_within_the_cap_is_read_whole():
    assert _read(_Request([b"ab", b"cd", b""]), limit=4) == b"abcd"


def test_a_body_exactly_at_the_cap_is_accepted():
    assert _read(_Request([b"x" * _MAX_BODY_BYTES])) == b"x" * _MAX_BODY_BYTES


def test_reading_stops_at_the_chunk_that_passes_the_cap():
    request = _Request([b"12", b"34", b"5", b"never read"])

    with pytest.raises(HTTPException) as err:
        _read(request, limit=4)

    assert err.value.status_code == 413
    assert request.pulled == 3  # the rest of an oversized body is never buffered


def test_a_declared_length_over_the_cap_is_refused_before_reading():
    request = _Request([b"x"], content_length=_MAX_BODY_BYTES + 1)

    with pytest.raises(HTTPException) as err:
        _read(request)

    assert err.value.status_code == 413 and request.pulled == 0


def test_a_false_small_content_length_is_still_caught_by_the_count():
    request = _Request([b"x" * 3, b"x" * 3], content_length=2)

    with pytest.raises(HTTPException) as err:
        _read(request, limit=4)

    assert err.value.status_code == 413
