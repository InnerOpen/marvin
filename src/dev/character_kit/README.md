# Character kit

Make a bubble character's whole animation pack from **one** AI image. The image model draws 16 still poses; everything
else — cutting, scaling, the 13 animations, peek ledges, timing, naming — is these scripts, with no AI and no tokens.
Dev tooling: `src/dev` is not in the production image.

## The loop (per character)

1. **Prompt** — `uv run src/dev/character_kit/make_prompt.py rocky` prints the pose-sheet prompt for Rocky.
2. **Generate** — paste it into ChatGPT (it follows a reference far better than Gemini's free tier) with
   `characters/rocky/reference.png` attached. Save the image it returns as `characters/rocky/poses.png`.
3. **Build** — `uv run src/dev/character_kit/character_from_poses.py rocky` writes `characters/rocky/out/rocky-pack.zip`
   and `out/preview.png`. Look at the preview first.
4. **Upload** — Admin → Character library → the pack → replace its files with the zip. Every file fills its slot by name;
   the peek-ledge margins are measured on upload.

If the sheet comes back wrong (text on it, a gradient background, poses touching), regenerate rather than patch: the
builder says what it found (`found 14 drawings, the recipe has 16 poses …`).

## What's here

| | |
|---|---|
| `characters/<slug>/character.json` | the character's bible: one-line description, style, rules that make it recognisable. Edit these — they go straight into the prompt. |
| `characters/<slug>/reference.png` | the picture attached to the prompt so the model redraws *this* character |
| `characters/<slug>/poses.png` | the 16-pose sheet the model returned — the only AI output. **Not in git** (often over the 500 KB commit limit): keep your own copy, e.g. in Drive. Any path works with `--sheet`. |
| `characters/<slug>/out/` | generated pack + preview (not committed) |
| `recipe.json` | the 16 poses (with their prompt wording) and how each animation uses them — shared by every character. Change it and rebuild every pack. |
| `prompt.md` | the prompt template `make_prompt.py` fills |
| `make_prompt.py` | prints the filled prompt |
| `character_from_poses.py` | sheet → pack |
| `export_references.py` | builds a `reference.png` (and a `character.json` stub) for every pack already in the library: `--api <url> --token <platform admin token>`, or `--json packs.json` |

Tests: `tests/test_character_kit.py` (a synthetic sheet through the whole build).

## The sheet

A square image, 4×4 poses in `recipe.json`'s order, on flat `#FF00FF` magenta with space between every pose and no
magenta in the character. The builder keys out the magenta, finds each drawing by the empty space around it, scales all
16 by one factor (pose 1 becomes `height` px tall in a `frame`-px frame, feet on `ground`), and composes the animations.
Side peeks lean out from behind a drawn ledge from the feet (only the head clears the edge); top and bottom slide out;
each peek plays once over ~1.9 s, the time the bubble is out.
