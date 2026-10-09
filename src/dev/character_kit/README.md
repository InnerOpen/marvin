# Character kit

Make a bubble character's whole animation pack from **one** AI image. The image model draws 16 still poses; everything
else — cutting, scaling, the 14 animations, peek ledges, timing, naming — is code, with no AI and no tokens.

**The building is Marvin's own** (`src/marvin/services/ai/character_sheets.py`, the recipe beside it in
`character_recipe.json`): upload the sheet itself — the image ChatGPT gave you, or a ChatGPT pet sheet — in Admin →
Character library or a character picker, and Marvin builds the pack, sized so nothing is cut off. This kit is the
command line over the same code, plus what only a developer needs: prompts, each character's bible and reference, the
Downloads pickup, preview.png. Dev tooling: `src/dev` is not in the production image.

## The loop (per character)

1. **Prompt** — `uv run src/dev/character_kit/make_prompt.py rocky` prints the pose-sheet prompt for Rocky.
2. **Generate** — paste it into ChatGPT (it follows a reference far better than Gemini's free tier) with
   `characters/rocky/reference.png` and `characters/rocky/layout-guide.png` attached (make_prompt writes the guide: a
   4×4 grid of boxes and ground lines, in a shade the builder keys away if it's copied). Save the image it returns as
   `characters/rocky/poses.png`.
3. **Build** — `uv run src/dev/character_kit/character_from_poses.py rocky` writes `characters/rocky/out/Rocky.zip`
   and `out/preview.png` (a newer sheet named like the character in Downloads is picked up first). Look at the preview.
4. **Upload** — Admin → Character library → the pack → replace its files with the zip. Every file fills its slot by name;
   the peek-ledge margins are measured on upload. (Or skip 3 and upload `poses.png` itself: same result, no preview.)

**A new character from just an idea** — skip the reference: write `characters/<slug>/character.json` (name, one-line
description, style, a few "always" rules), run `make_prompt.py <slug> --new` and paste it with nothing attached; the
model designs the character and draws all 16 poses in one image, so they match. The first build saves a
`reference.png` from that sheet, and later redraws (without `--new`) keep that look.

**A ChatGPT pet** — ChatGPT's built-in pets and the ones its Create Pet skill makes (`reference/chatgpt-create-pet-skill.md`)
share one sprite-sheet layout, with hand-drawn animation for every state. `pet_to_pack.py <sheet.webp> <name>` keeps
all of it (one scale and placement for the whole sheet, so jumps and gaits stay as drawn), adds look-loop from its
look-direction rows and the kit's edge peeks, and picks the largest size at which nothing is cut off.

If the sheet comes back wrong (text on it, a gradient background, poses touching), regenerate rather than patch: the
builder says what it found (`found 14 drawings, the recipe has 16 poses …`).

A wide character whose arms would run off the frame is built smaller on its own: without a `height`, the builder
takes the largest height (from the recipe's down) at which no frame is cut off, and says so (`built at height 96`).
`"height"` in `character.json` (or `--height`) fixes one instead; then it warns `… cut off at the left edge in frames
2, 4` if it doesn't fit. Tilts (the dizzy wobble, side peeks) stay on the ground line and jumps top out at the frame.

## What's here

| | |
|---|---|
| `characters/<slug>/character.json` | the character's bible: one-line description, style, rules that make it recognisable — edit these, they go straight into the prompt — and optionally `height` (px) for a character too wide for the shared size. |
| `characters/<slug>/reference.png` | the picture attached to the prompt so the model redraws *this* character |
| `characters/<slug>/poses.png` | the 16-pose sheet the model returned — the only AI output. **Not in git** (often over the 500 KB commit limit): keep your own copy, e.g. in Drive. Any path works with `--sheet`. |
| `characters/<slug>/out/` | generated pack + preview (not committed) |
| `src/marvin/services/ai/character_recipe.json` | the recipe: the 16 poses (with their prompt wording) and how each animation uses them — shared by every character and by Marvin's uploader. Change it and rebuild every pack. |
| `prompt.md`, `intro-reference.md`, `intro-new.md` | the prompt template `make_prompt.py` fills, and its two openings: redraw the attached character, or design a new one (`--new`) |
| `make_prompt.py` | prints the filled prompt |
| `character_from_poses.py` | sheet → pack (the command line over `character_sheets.py`) |
| `pet_to_pack.py` | a ChatGPT pet sprite sheet → a pack (its own animation kept, peeks added) |
| `reference/chatgpt-create-pet-skill.md` | ChatGPT's own Create Pet skill, for comparison and ideas |
| `export_references.py` | builds a `reference.png` (and a `character.json` stub) for every pack already in the library: `--api <url> --token <platform admin token>`, or `--json packs.json` |

Tests: `tests/test_character_sheets.py` (the building, synthetic sheets), `tests/test_character_kit.py` (these command
lines), and the upload tests (`tests/test_assistant_character.py`, `tests/test_character_library.py`).

## The sheet

A square image, 4×4 poses in the recipe's order, on one flat background colour with space between every pose. The
colour is chosen per character to keep clear of its own (the reference's colours, or the description's colour words
for `--new`): magenta by default, green for a pink or purple character, never green for a green one…; set
`"background"` in `character.json` to choose. The builder keys whatever flat colour the border has. The builder keys out the magenta, finds each drawing by the empty space around it, scales all
16 by one factor (pose 1 becomes `height` px tall in a `frame`-px frame, feet on `ground`), and composes the animations.
Side peeks lean out from behind a drawn ledge from the feet (only the head clears the edge); top and bottom slide out;
each peek plays once over ~1.9 s, the time the bubble is out.
