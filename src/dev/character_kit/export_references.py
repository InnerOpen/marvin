"""Make a reference.png (and a character.json to fill in) for each pack already in the character library.

    uv run src/dev/character_kit/export_references.py --api https://marvin.example.com --token "$MARVIN_TOKEN"
    uv run src/dev/character_kit/export_references.py --json packs.json      # {slug: {"name": …, "states": {state: url}}}

For every pack: the clearest frame of idle, greeting, success, thinking, error and move_left (whichever it has), side
by side on white, enlarged without smoothing — the picture to attach to make_prompt.py's prompt so the image model
redraws THAT character. An existing character.json is never overwritten; a missing one is written with the pack's
name and a description to fill in. Needs a platform admin's token for --api (GET /api/admin/character-packs).
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageSequence

KIT = Path(__file__).parent
SHOWN = ("idle", "greeting", "success", "thinking", "error", "move_left")
TILE = 384  # each pose enlarged to this square


def clearest_frame(data: bytes) -> Image.Image:
    """The frame showing the most of the character (a wave mid-wave, not its blank first frame)."""
    frames = [f.convert("RGBA") for f in ImageSequence.Iterator(Image.open(io.BytesIO(data)))]
    return max(frames, key=lambda f: int((np.array(f)[..., 3] > 128).sum()))


def reference_sheet(images: list[bytes]) -> Image.Image:
    sheet = Image.new("RGB", (TILE * len(images), TILE), (255, 255, 255))
    for i, data in enumerate(images):
        frame = clearest_frame(data)
        box = frame.getbbox() or (0, 0, frame.width, frame.height)
        frame = frame.crop(box)
        k = TILE * 0.9 / max(frame.size)  # every pose the same size, whatever the GIF's own size
        frame = frame.resize((round(frame.width * k), round(frame.height * k)), Image.NEAREST)  # no smoothing
        tile = Image.new("RGBA", (TILE, TILE), (255, 255, 255, 255))
        tile.alpha_composite(frame, ((TILE - frame.width) // 2, TILE - frame.height - TILE // 20))
        sheet.paste(tile.convert("RGB"), (i * TILE, 0))
    return sheet


def _get(url: str, token: str | None = None) -> bytes:
    headers = {"User-Agent": "marvin-character-kit/1"}  # the asset CDN refuses Python's default agent (403)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - a URL the operator gave
        return resp.read()


def packs_from_api(api: str, token: str) -> dict[str, dict]:
    rows = json.loads(_get(api.rstrip("/") + "/api/admin/character-packs", token))
    return {row["slug"]: {"name": row["name"], "states": row.get("states") or {}} for row in rows}


def export(packs: dict[str, dict], root: Path = KIT / "characters") -> list[str]:
    done = []
    for slug, pack in packs.items():
        urls = [pack["states"][s] for s in SHOWN if pack["states"].get(s)]
        if not urls:
            continue
        folder = root / slug
        folder.mkdir(parents=True, exist_ok=True)
        reference_sheet([_get(u) for u in urls]).save(folder / "reference.png")
        stub = folder / "character.json"
        if not stub.exists():
            stub.write_text(
                json.dumps(
                    {
                        "name": pack["name"],
                        "description": f"TODO: describe {pack['name']} in one line — what it is, its shape, its colours",
                        "style": "pixel-art",
                        "rules": [],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        done.append(slug)
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--api", help="Marvin's base URL")
    source.add_argument("--json", type=Path, help="a file of {slug: {name, states}}")
    parser.add_argument("--token", help="a platform admin's API token (with --api)")
    args = parser.parse_args(argv)
    if args.api and not args.token:
        parser.error("--api needs --token")
    packs = packs_from_api(args.api, args.token) if args.api else json.loads(args.json.read_text(encoding="utf-8"))
    for slug in export(packs):
        sys.stdout.write(f"characters/{slug}/reference.png\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
