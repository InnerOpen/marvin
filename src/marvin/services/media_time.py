"""Moments in a sound or video asset, for links that open it there.

Marvin Media writes a transcribed recording's timestamped transcript into the asset's description, a line per phrase led by where it
starts (``[0:01:05] words``), so a chunk the search index matched carries the minutes it covers. A citation of that chunk opens the
asset's page at the chunk's first marker (``/workspace/assets/<id>/view?t=65``), which the page plays from. The frontend twin is
frontend/src/lib/mediaTime.ts.
"""

from __future__ import annotations

import re

MARKER = re.compile(r"\[(\d+):([0-5]\d):([0-5]\d)\]")


def first_marker_seconds(text: str | None) -> int | None:
    """Seconds of the first ``[h:mm:ss]`` in ``text``; None when it holds none."""
    m = MARKER.search(text or "")
    return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) if m else None


def asset_page_path(asset_id: str, seconds: int | None = None) -> str:
    """An asset's page: its view page opened at ``seconds`` when there is a time, else the page an asset link has always opened."""
    if seconds is None:
        return f"/workspace/assets/{asset_id}"
    return f"/workspace/assets/{asset_id}/view?t={int(seconds)}"
