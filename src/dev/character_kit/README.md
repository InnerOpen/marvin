# Character kit

Prompts and references for drawing a bubble character's pose sheet with an AI image model. **Marvin builds the pack
itself** (`src/marvin/services/ai/character_sheets.py`, the recipe beside it in `character_recipe.json`): upload the
sheet the model returns in Admin → Character library (or a character picker) and Marvin cuts it, sizes it so nothing is
cut off, and composes the animations. This kit is only what comes before that: the prompt, each character's bible and
reference picture. Dev tooling: `src/dev` is not in the production image.

## The loop (per character)

1. **Prompt** — `uv run src/dev/character_kit/make_prompt.py rocky` prints the pose-sheet prompt for Rocky and writes
   `characters/rocky/layout-guide.png` (a 4×4 grid of boxes and ground lines, in a shade the builder keys away if the
   model copies it).
2. **Generate** — paste the prompt into ChatGPT (it follows a reference far better than Gemini's free tier) with
   `characters/rocky/reference.png` and the layout guide attached.
3. **Upload** — Admin → Character library → upload the image it returns. Marvin builds the pack. If the sheet comes back
   wrong (text on it, a gradient background, poses touching), regenerate rather than patch: the upload says what it found
   (`found 14 drawings, the recipe has 16 poses …`).

**A new character from just an idea** — skip the reference: write `characters/<slug>/character.json` (name, one-line
description, style, a few "always" rules), run `make_prompt.py <slug> --new` and paste it with only the layout guide
attached; the model designs the character and draws all 16 poses in one image, so they match. Keep the result as the
character's `reference.png` for later redraws (without `--new`).

**A ChatGPT pet** — ChatGPT's built-in pets and the ones its Create Pet skill makes (`reference/chatgpt-create-pet-skill.md`)
share one sprite-sheet layout; upload that sheet in the same place and Marvin keeps its own animation.

## What's here

| | |
|---|---|
| `characters/<slug>/character.json` | the character's bible: one-line description, style, rules that make it recognisable — edit these, they go straight into the prompt — and optionally `background` (a colour name or hex) and `height` (px) for a character too wide for the shared size. |
| `characters/<slug>/reference.png` | the picture attached to the prompt so the model redraws *this* character |
| `characters/<slug>/persona.md` | (some characters) the assistant persona text for that character |
| `prompt.md`, `intro-reference.md`, `intro-new.md` | the prompt template `make_prompt.py` fills, and its two openings: redraw the attached character, or design a new one (`--new`) |
| `make_prompt.py` | prints the filled prompt and writes the layout guide (not committed) |
| `reference/chatgpt-create-pet-skill.md` | ChatGPT's own Create Pet skill, for comparison and ideas |
| `src/marvin/services/ai/character_recipe.json` | the recipe: the 16 poses (with their prompt wording) and how each animation uses them — shared by every character and by Marvin's uploader |

Tests: `tests/test_character_kit.py` (the prompt), `tests/test_character_sheets.py` (the building, synthetic sheets), and
the upload tests (`tests/test_assistant_character.py`, `tests/test_character_library.py`).

## The sheet

A square image, 4×4 poses in the recipe's order, on one flat background colour with space between every pose. The colour
is chosen per character to keep clear of its own (the reference's colours, or the description's colour words for
`--new`): magenta by default, green for a pink or purple character, never green for a green one…; set `"background"` in
`character.json` to choose. Marvin keys whatever flat colour the border has, finds each drawing by the empty space around
it, and scales all 16 by one factor.
